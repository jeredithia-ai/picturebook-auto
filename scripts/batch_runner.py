"""批量生产：N 个绘本大纲 → N×4 件套（绘本 PPT / 练习册 / 阅读报告 / 教师指南）。

设计要点（用户 2026-06-03 拍板）：
- 数据隔离：每本独立 BookOutline 实例，互不串混。
- N 进 N×4 出：单本失败不影响其他本，记录到日志，支持单独重跑。
- 资源管理：并发可配（ThreadPool）、单本超时 ≤30min。
- 绘本图全自动出图（不逐页停），每本标记『待人工抽查』，可事后回单本模式逐页重生。
- 输出两模式：每本子文件夹 / 平铺 + 规范命名；可选打包 ZIP。
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import threading
import time
import traceback
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from ai_extractor import apply_extracted_to_outline, extract_all
from cn_prompt_builder import build_cn_page_prompt, validate_page_ip_lock
from config import L02_PIPELINE, OUTPUTS_DIR, resolve_image_backend, resolve_ip_age
from parser import BookOutline, PageSpec, enrich_from_syllabus
from ppt_builder import build_picturebook_pptx, safe_filename
from reading_report_builder import attach_rr_questions, build_reading_report
from seedream_client import generate_image, generate_image_for_level
from teacher_guide_builder import build_teacher_guide
from worksheet_builder import attach_worksheet_questions, build_worksheet

try:
    from auto_fill import auto_summary
except Exception:  # pragma: no cover
    auto_summary = None  # type: ignore

PER_BOOK_TIMEOUT_S = int(os.getenv("PER_BOOK_TIMEOUT_S", str(45 * 60)))  # 单本超时 45 分钟（生图重试更耐心后放大）
WEB_BATCH_MAX = 5  # Web 端单次批量上限（CLI 不受此限）
WEB_BATCH_LIMIT_HINT = "单次最多 5 本，系列备课请分批或联系管理员走 CLI"

# 出图前/后耗时估算（仅用于 Dry-run 预检展示，非精确）
EST_SECS_PER_IMAGE = 16
EST_SECS_TEXT = 30
IMAGES_PER_BOOK = 8

# ============================================================
#  ① 图片全局并发池：限制「所有本子在途出图请求总数」≤ image_concurrency，
#     与本级并发解耦（本并发 × 每本页并发 都受这一个信号量统一节流，贴 API RPM 上限）。
# ============================================================
_IMG_SEM: Optional[threading.BoundedSemaphore] = None

# ============================================================
#  ①.5 LLM 抽取串行化锁（用户拍板 2026-06-08）：
#     文本抽取是无状态 HTTP，本不该串味，但为彻底排除任何客户端竞态/限流交叠，
#     并按"分层执行"原则（LLM 串行、出图并发），用全局锁保证同一时刻只有一本在抽取。
#     抽取很快（相对出图），串行化对总墙钟影响小；出图仍由 _IMG_SEM 并发节流。
# ============================================================
_EXTRACT_LOCK = threading.Lock()


def set_image_concurrency(n: int) -> None:
    global _IMG_SEM
    _IMG_SEM = threading.BoundedSemaphore(max(1, int(n)))


@contextlib.contextmanager
def _img_guard():
    if _IMG_SEM is None:
        yield
        return
    _IMG_SEM.acquire()
    try:
        yield
    finally:
        _IMG_SEM.release()


@dataclass
class BatchItem:
    title: str
    level: str
    book_number: str
    story: str
    cefr: str = ""
    theme: str = ""
    fiction_type: str = ""   # 可选强制体裁："fiction" / "non-fiction"（留空则交给 AI 抽取判定）
    frame_mode: str = "A+"   # 框架寓言呈现模式（老师拍板 2026-06-08 默认 A+：封面拿书+中间纯故事+末页结尾&合书）；仅对框架式寓言生效

    @property
    def name_prefix(self) -> str:
        # safe_filename 会补 .pptx 后缀，这里去掉，只要干净标题
        t = re.sub(r"\.pptx$", "", safe_filename(self.title))
        return f"Level {self.level}_Book{self.book_number}_{t}"


@dataclass
class BatchResult:
    item: BatchItem
    status: str = "pending"          # pending | ok | failed
    outputs: list[str] = field(default_factory=list)
    zip_path: str = ""
    error: str = ""
    elapsed_s: float = 0.0
    needs_human_review: bool = True  # 默认待抽查；跑完 evals 后按结果收紧
    fact_notes: str = ""             # 科普非虚构：科学事实校验日志（非致命）
    eval_level: str = ""             # ④ evals 体检结论：ok / warn / error（空=未跑）
    eval_msgs: list[str] = field(default_factory=list)  # 红/黄项摘要（定向抽查用）
    skipped_pages: int = 0           # ② 断点续跑：本次复用的已存在页数
    placeholder_pages: list[int] = field(default_factory=list)  # mock/失败兜底占位页 index


# ============================================================
#  解析批量输入
# ============================================================
def validate_web_batch_limit(items: list[BatchItem]) -> str | None:
    """Web 批量上限校验；超限返回错误文案，否则 None。"""
    n = len(items)
    if n > WEB_BATCH_MAX:
        return (
            f"本次解析到 **{n} 本**，超过 Web 单次上限 **{WEB_BATCH_MAX} 本**。{WEB_BATCH_LIMIT_HINT}。"
        )
    return None


def _book_display_status(r: BatchResult) -> str:
    """批量产出表用：ok / partial / failed。"""
    if r.status == "failed":
        return "failed"
    if r.placeholder_pages or (r.error or "").strip():
        return "partial"
    return "ok"


def parse_batch_outlines(raw: str) -> list[BatchItem]:
    """解析多本大纲文本。每本用 `===` 分隔；每本第一行 = `Title | Level | Book#`，其后为故事。"""
    items: list[BatchItem] = []
    blocks = [b.strip() for b in re.split(r"^\s*={3,}\s*$", raw or "", flags=re.MULTILINE)]
    for blk in blocks:
        if not blk.strip():
            continue
        lines = [ln for ln in blk.splitlines() if ln.strip()]
        if not lines:
            continue
        head = lines[0]
        parts = [p.strip() for p in head.split("|")]
        title = parts[0] if parts else "Untitled"
        level = (parts[1] if len(parts) > 1 else "5").lstrip("Ll").strip() or "5"
        book_no = (parts[2] if len(parts) > 2 else "01").strip()
        # 规范 book# 两位
        if book_no.isdigit():
            book_no = f"{int(book_no):02d}"
        story = "\n".join(lines[1:]).strip()
        items.append(BatchItem(title=title, level=level, book_number=book_no, story=story))
    return items


# ============================================================
#  单本流水线（隔离）
# ============================================================
def _story_lines(story: str) -> list[str]:
    out = []
    for ln in story.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        # 去掉 "Page 1:" 前缀
        m = re.match(r"^[Pp]age\s*\d+\s*[:：]\s*(.+)$", ln)
        out.append(m.group(1).strip() if m else ln)
    return out[:7]


def run_one(item: BatchItem, out_root: Path, *, mock: bool = False,
            flat: bool = False, resume: bool = False,
            image_workers: int = 4, prompts_only: bool = False) -> BatchResult:
    """跑一本：抽取 → outline → 生图 → 4 件套 → zip。失败抛异常由上层捕获。

    resume=True：已存在且非空的 page_xx.png 直接复用（断点续跑/重跑失败本只补缺页）。
    prompts_only=True：只构建并落盘 image_prompts.txt，不出图、不组装文档（供复查对齐）。
    image_workers：本本内出图并发数；实际在途总数仍由全局 _IMG_SEM 统一节流。
    """
    t0 = time.time()
    res = BatchResult(item=item)
    ip_age = resolve_ip_age(item.level)

    cefr, theme = item.cefr, item.theme
    if auto_summary and (not cefr or not theme):
        try:
            auto = auto_summary(item.level, item.story, item.title)
            cefr = cefr or auto.get("cefr", "")
            theme = theme or auto.get("theme", "")
        except Exception:
            pass

    # LLM 抽取串行化（分层执行：抽取串行、出图并发）→ 杜绝并发抽取的任何交叠污染。
    with _EXTRACT_LOCK:
        ec = extract_all(item.story, item.title, item.level, cefr=cefr, theme=theme, mock=mock)

    pages = [PageSpec(index=0, page_type="cover", text="")]
    for i, line in enumerate(_story_lines(item.story), start=1):
        pages.append(PageSpec(index=i, page_type="story", text=line))
    # 不足 7 页补空，保证 8 页结构
    while len(pages) < 8:
        pages.append(PageSpec(index=len(pages), page_type="story", text=""))

    outline = BookOutline(
        title=item.title, pages=pages, level=item.level, book_number=item.book_number,
        cefr=cefr, ip_age=ip_age, theme=theme,
    )
    apply_extracted_to_outline(outline, ec)

    # 可选：强制体裁（老师/调用方显式指定时覆盖 AI 抽取的判定）
    if item.fiction_type:
        outline.fiction_type = item.fiction_type

    # 框架寓言呈现模式（A / B / A+）：仅对框架式寓言生效（默认 A+）
    outline.frame_mode = item.frame_mode or "A+"

    # 官方 S&S 大纲注入：命中则用权威 Strategy/Skill/GO 等真值（未命中维持启发式）
    if enrich_from_syllabus(outline):
        print(f"[{item.name_prefix}] 已命中官方 S&S 大纲，注入 Strategy/Skill/GO")

    # 科普非虚构：科学事实正确性校验（核查文字+画面，自动应用修正；非致命）
    if not mock:
        try:
            from cn_prompt_builder import _is_nonfiction
            from fact_check import fact_check_outline, apply_fixes_to_outline, summarize_issues
            if _is_nonfiction(outline):
                issues = fact_check_outline(outline)
                if issues:
                    n = apply_fixes_to_outline(outline, issues)
                    res.fact_notes = summarize_issues(issues) + f"\n（已自动应用 {n} 处修正）"
                    print(f"[{item.name_prefix}] {res.fact_notes}")
        except Exception as e:  # noqa: BLE001
            print(f"[{item.name_prefix}] 科学事实校验跳过: {e}")

    attach_rr_questions(outline, ec.rr_questions)
    attach_worksheet_questions(outline, ec.worksheet_questions, reading_q_count=4)

    # 输出目录：子文件夹 or 平铺
    book_dir = out_root if flat else (out_root / item.name_prefix)
    img_dir = book_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    # 绘本全自动出图（不逐页停）
    # IP 一致性（单锚策略）：gpt-image-2 只吃一张参考图。锁定「全书主角定妆裁切图」为最强单锚，
    # 主角在本页出现时置顶为唯一参考（锁主角=锁全书一家人），本页无任何角色时用全书风格锚兜底。
    from cn_prompt_builder import book_primary_anchor_ref, book_style_anchor_ref
    from seedream_client import crop_character_portrait, build_reference_sheet
    anchor_dir = img_dir / "_anchors"
    prot_ref = book_primary_anchor_ref(outline, ip_age)
    style_anchor = book_style_anchor_ref()

    # 书内角色册（用户拍板 2026-06-07）：登记反复出场的一次性/非 IP 角色，
    # 为它们生成【书内定妆锚图】并挂到 outline.book_cast → 出图时全书锁同一形象。
    try:
        from book_cast import build_book_cast, anchor_prompt
        book_cast = build_book_cast(outline)
        if book_cast:
            role_dir = anchor_dir / "_roles"
            for r in book_cast.values():
                if not r.needs_anchor:
                    continue
                ap = role_dir / f"role_{r.rid.replace(' ', '_')}.png"
                if resume and (not mock) and ap.exists() and ap.stat().st_size > 0:
                    r.anchor_path = str(ap)
                    continue
                # prompts_only（dry-run）：只登记角色 + 计算外观锁文本，绝不调图片 API 生成锚图。
                #   外观锁文本（desc_en）注入与锚图是否存在无关，足够复查 prompt。
                if prompts_only:
                    if ap.exists() and ap.stat().st_size > 0:
                        r.anchor_path = str(ap)
                    continue
                try:
                    ap.parent.mkdir(parents=True, exist_ok=True)
                    # 一次性角色（永远是非 IP）锚图【一律不挂含主角的三人组风格锚 trio】：
                    #   trio_style_anchor 含 Mia/Tommy，挂上去会把命名儿童角色(如 Ben)直接带成
                    #   Tommy 的翻版（同棕色蓬松短发/浅蓝衣/相似脸）——Book57 Ben 克隆 Tommy 的根因。
                    #   成人角色→空参考(已有成人锁)；非成人儿童命名角色→同样空参考，靠 anchor_prompt
                    #   里的【全新独立·国际化·反克隆】锁 + 治愈水彩画风描述全新生成。
                    role_refs = []
                    with _img_guard():
                        generate_image(prompt=anchor_prompt(r), dest=ap,
                                       references=role_refs,
                                       label=f"{item.name_prefix} 角色锚:{r.display}", mock=mock)
                    r.anchor_path = str(ap)
                except Exception as e:  # noqa: BLE001
                    print(f"[{item.name_prefix}] 一次性角色锚图生成失败({r.display}): {e}")
            outline.book_cast = book_cast
            named = "、".join(f"{r.display}" for r in book_cast.values() if r.needs_anchor)
            if named:
                print(f"[{item.name_prefix}] 书内角色册：为反复出场角色锁定形象 -> {named}")
    except Exception as e:  # noqa: BLE001
        print(f"[{item.name_prefix}] 书内角色册跳过: {e}")

    def _ip_name(ref_path) -> str:
        try:
            from ip_library import load_library
            rp = str(Path(ref_path)).lower()
            for e in load_library():
                if str(e.image_path).lower() == rp:
                    return e.name_base
        except Exception:
            pass
        return ""

    # 出图后端：L0-2=即梦(可收多张独立 base64 参考图)，L3-6=gpt-image-2(只收 1 张)。
    # 参考图策略按后端分流（2026-06-08 修：即梦不再拼定妆表，避免多人物页注意力摊薄/IP 漂移）。
    img_backend = resolve_image_backend(item.level)
    # 新流程(gpt_then_jimeng)：L0-2 第①段也是 gpt-image-2(只收1张)→应走"合并定妆表/单锚"；
    # 仅旧流程(即梦直出)才发多张独立 base64 定妆图。
    use_multi_ref = (img_backend == "jimeng_refine" and L02_PIPELINE != "gpt_then_jimeng")

    # ---- 阶段 1：顺序构建每页 prompt + 参考锚（CPU/IO，确定性，便于断点续跑判断）----
    jobs: list[tuple] = []          # (index, dest, page_prompt, page_refs, fallback_prompt)
    image_paths: list[Path] = []
    ip_lock_issues: list[str] = []  # 出图前自检门累计的主角铁律违规
    built_pages: list[tuple] = []   # SOP 第8条导出层复用：(page, BuiltPromptCN)，不重算
    for page in outline.pages:
        built = build_cn_page_prompt(page, outline, ip_age)
        built_pages.append((page, built))
        # 出图前自检门（用户拍板 2026-06-07）：校验主角铁律，违规累计 → 标记人工抽查
        _viol = validate_page_ip_lock(built, outline, ip_age, page)
        if _viol:
            tag = "封面" if (page.page_type == "cover" or page.index == 0) else f"P{page.index}"
            ip_lock_issues.append(f"[{tag}] " + "；".join(_viol))
        dest = img_dir / f"page_{page.index:02d}.png"
        image_paths.append(dest)    # 顺序占位，保证组装时按页序
        # 图生图 IP 锁定（用户拍板 2026-06-06）：本页每个出场 IP 都用官方定妆图驱动。
        # 主角置顶 → 多角色拼「定妆表」、单角色裁单锚；并加“照表还原·只改姿势表情”强约束。
        refs = [Path(r) for r in built.references if r]
        # 参考排序（用户拍板 2026-06-09·Book57 关键）：主角锚置顶，但【一次性角色锚(book_cast/_roles)】
        #   紧随其后、绝不被多余 IP 挤出 5 张上限；再放其余 IP 参考。这样剧情主体/配角锚都能进参考表，
        #   且定妆表左→右顺序 = (主角→一次性角色→其它)，与配色轮"第N个配角穿X色"的左→右排序对齐。
        def _is_oneoff_anchor(p: Path) -> bool:
            return "_roles" in p.parts or p.stem.startswith("role_")
        leads = [r for r in refs if prot_ref and r == Path(prot_ref)]
        oneoffs = [r for r in refs if _is_oneoff_anchor(r) and r not in leads]
        others = [r for r in refs if r not in leads and r not in oneoffs]
        refs = (leads + oneoffs + others)[:5]
        local = [r for r in refs if r.exists()]

        def _oneoff_label(p: Path) -> str:
            # role_<rid>.png → 用 used_characters 里的 display；回退用 rid。
            if not _is_oneoff_anchor(p):
                return ""
            rid = p.stem[len("role_"):] if p.stem.startswith("role_") else p.stem
            for _c in (built.used_characters or []):
                if str(_c.get("key", "")) == f"oneoff:{rid}":
                    return _c.get("name", "") or rid
            return rid
        names = [(_ip_name(r) or _oneoff_label(r)) for r in local]
        anchor, note = None, ""
        if use_multi_ref and local:
            # 即梦支持最多 4 张独立 base64 参考图：逐角色发"独立定妆图"，不拼定妆表。
            # 多人物页（如《My Family》）拼图会把注意力摊薄→每人都还原不准、Mia/Tommy 漂移；
            # 拆成独立锚图后，每个角色（主角优先）各占一张干净参考，锁形象更稳。
            cleaned: list[Path] = []
            for i, rp in enumerate(local[:4]):
                cp = crop_character_portrait(
                    rp, anchor_dir / f"anchor_p{page.index:02d}_{i}.png") or rp
                cleaned.append(cp)
            page_refs = cleaned
            disp = "、".join(n for n in names[:len(cleaned)] if n) or "本页角色"
            note = (
                f"【参考图＝{len(cleaned)} 张独立角色定妆图·形象永久锁定】依次对应【{disp}】，每张只锁一个角色；"
                "逐一 1:1 还原五官/发型/发色/肤色/服装与配色、与往期同一个人、不串用；"
                "只改姿势/动作与表情，不照搬白底/站姿/排版。"
            )
        else:
            # L3-6 gpt-image-2 只收 1 张：多角色拼「定妆表」、单角色裁单锚。
            if len(local) >= 2:
                sheet = build_reference_sheet(
                    local, anchor_dir / "_refsheets" / f"sheet_p{page.index:02d}.png",
                    labels=names)
                if sheet is not None:
                    anchor = sheet
                    disp = "、".join(n for n in names if n) or "本页角色"
                    note = (
                        f"【参考图＝白底角色定妆表·形象永久锁定】并排展示本页出场角色（{disp}，上方有英文名标签）；"
                        "把每个角色的脸型/五官/发型/发色/肤色/服装与配色 1:1 还原、与往期同一个人；"
                        "只改姿势/动作与表情，严禁照搬白底/并排站姿/多视图排版。"
                    )
            if anchor is None and local:
                anchor = crop_character_portrait(
                    local[0], anchor_dir / f"anchor_p{page.index:02d}.png") or local[0]
                nm = names[0] or "主角"
                note = (
                    f"【参考图＝{nm} 官方定妆图（连续性绘本·形象永久锁定）】请把 {nm} 的脸型/五官/发型/"
                    "发色/肤色/服装款式与配色 1:1 精确还原，与往期绘本同一个人。"
                    "【唯一允许改变：该角色的姿势/动作与面部表情】，形象其余不得改动；不要照搬参考图背景或姿势。"
                )
            elif anchor is None and prot_ref and Path(prot_ref).exists():
                # 本页无任何角色定妆图，但本书有系列主角 → 优先挂【主角新定妆单锚】(mia_10/tommy_10)，
                #   绝不回退到含旧形象的 trio 兜底图（根因一·2026-06-10：代词页脱模/Tommy 漂深蓝）。
                anchor = crop_character_portrait(
                    prot_ref, anchor_dir / f"anchor_p{page.index:02d}.png") or Path(prot_ref)
                nm = _ip_name(prot_ref) or "主角"
                note = (
                    f"【参考图＝{nm} 官方定妆图（连续性绘本·形象永久锁定）】请把 {nm} 的脸型/五官/发型/"
                    "发色/肤色/服装款式与配色 1:1 精确还原，与往期绘本同一个人。"
                    "【唯一允许改变：该角色的姿势/动作与面部表情】，形象其余不得改动；不要照搬参考图背景或姿势。"
                )
            elif anchor is None and style_anchor:
                anchor = style_anchor
            page_refs = [anchor] if anchor else []
        # 即梦页若本页无任何角色定妆图，用全书风格锚兜底
        if img_backend == "jimeng_refine" and not page_refs and style_anchor:
            page_refs = [style_anchor]
        page_prompt = built.prompt + ("\n\n" + note if note else "")
        # 定向修图(补人/改色)需要精确 IP 锁：gpt-image-2 修图只吃 1 张参考(草图)，
        # 没法再塞 IP 定妆图 → 把每个出场角色的精确服装/发型锁(按本书年龄)作为文字带进修图，
        # 杜绝"补出的人/改后的人"漂移成藏青/黑发路人(用户拍板 2026-06-09：IP 连续锁定)。
        cast_lock: list[str] = []
        try:
            from character_registry import get_description as _get_desc
            for _c in (built.used_characters or []):
                _k = (_c.get("key") or "").split("_")[0]
                _d = _get_desc(_k, ip_age) if _k else None
                if _d:
                    cast_lock.append(_d)
        except Exception:
            cast_lock = []
        review_meta = {
            "page_text": page.text or "",
            "scene_cn": getattr(built, "scene_cn", "") or "",
            "story_lock": getattr(built, "story_lock", "") or "",
            "cast_names": [c.get("name", "") for c in (built.used_characters or [])],
            "ip_age": ip_age,
            "cast_lock": cast_lock,
        }
        jobs.append((page.index, dest, page_prompt, page_refs, built.prompt, review_meta))

    # ---- 落盘：把每页出图提示词写到 image_prompts.txt（便于复查/对齐 IP 与画风）----
    try:
        from config import GPT_CLEAN_STYLE_DIRECTIVE as _STY, GPT_CLEAN_STYLE_ECHO as _ECHO
        _lv_dump = str(item.level).strip().lower().lstrip("l")
        _is_l36 = _lv_dump in ("3", "4", "5", "6")
        _lines = [f"# {item.name_prefix} 出图提示词（共 {len(jobs)} 页）", ""]
        if _is_l36:
            _lines += ["【全局画风·前缀（每页自动前置）】", _STY.strip(),
                       "", "【全局画风·末尾回声（每页自动后置）】", _ECHO.strip(),
                       "", "=" * 60, ""]
        for _idx, _dest, _pp, _refs, _fb, _rm in sorted(jobs, key=lambda j: j[0]):
            _tag = "封面" if _idx == 0 else f"P{_idx}"
            _refnames = "、".join(Path(r).name for r in (_refs or []))
            _lines += [f"—— {_tag} —— 参考图: {_refnames or '无'}", _pp.strip(), "", "-" * 60, ""]
        (book_dir / "image_prompts.txt").write_text("\n".join(_lines), encoding="utf-8")
        print(f"[prompts] 已落盘 → {book_dir / 'image_prompts.txt'}", flush=True)
    except Exception as _e:  # noqa: BLE001
        print(f"[prompts] 提示词落盘失败（不影响出图）：{_e}")

    # ---- SOP 第8条 · 对外交付 4 部分纯文本 Prompt 文档（复用已构建分页 prompt，不重算）----
    #   纯新增产物，与 image_prompts.txt / PPT / RR 并存、不冲突；失败不影响出图。
    try:
        from export_sop_prompts import write_sop_document
        _sop = write_sop_document(outline, built_pages, book_dir, item.name_prefix)
        print(f"[SOP] 对外交付4部分文档已落盘 → {_sop}", flush=True)
    except Exception as _e:  # noqa: BLE001
        print(f"[SOP] 对外交付文档落盘失败（不影响出图）：{_e}")

    if prompts_only:
        res.status = "ok"
        res.elapsed = time.time() - t0
        return res

    # ---- 阶段 2：并行出图（页间无先后依赖，各写各的 dest）----
    #   断点续跑：已存在且非空的页直接复用；全局 _IMG_SEM 统一节流在途总数。
    def _gen_page(job: tuple) -> tuple[int, str, bool]:
        idx, dest, page_prompt, page_refs, fallback_prompt, review_meta = job
        if resume and (not mock) and dest.exists() and dest.stat().st_size > 0:
            return idx, "", True
        try:
            with _img_guard():
                # 按 level 分流：L0-2 即梦全程出图+GPT视觉自审定向修图；L3-6 走纯 gpt-image-2 单段
                generate_image_for_level(item.level, prompt=page_prompt, dest=dest,
                                         references=page_refs,
                                         label=f"{item.name_prefix} P{idx}", mock=mock,
                                         review_meta=review_meta)
            return idx, "", False
        except Exception as e:  # noqa: BLE001
            # 单页失败不致命：用占位让组装继续，标记待人工抽查
            generate_image(prompt=fallback_prompt, dest=dest, mock=True,
                           label=f"P{idx} FALLBACK")
            return idx, f"[P{idx} img: {e}] ", False

    workers = max(1, min(image_workers, len(jobs)))
    with ThreadPoolExecutor(max_workers=workers) as iex:
        for _idx, err, skipped in iex.map(_gen_page, jobs):
            if err:
                res.error += err
            if skipped:
                res.skipped_pages += 1

    # 占位图检测：mock 或 API 失败兜底页 → 标记 partial + 强制人工抽查
    try:
        from seedream_client import scan_placeholder_pages
        res.placeholder_pages = scan_placeholder_pages(img_dir)
        if res.placeholder_pages:
            res.needs_human_review = True
            if res.eval_level not in ("error",):
                res.eval_level = res.eval_level or "warn"
            ph_note = f"占位图页：P{','.join(str(p) for p in res.placeholder_pages)}"
            res.eval_msgs = [ph_note] + res.eval_msgs
            res.eval_msgs = res.eval_msgs[:12]
            print(f"[{item.name_prefix}] [WARN] {ph_note}，需重生占位页", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[{item.name_prefix}] 占位图扫描跳过: {e}")

    # ---- 涂色线稿（用户拍板 2026-06-08 / 2026-06-09 扩到 L3）：worksheet 读后页 = 涂色线稿 + 自主造句 ----
    #   单独黑白线稿（不走水彩画风指令），失败则 worksheet 自动用留白画框兜底，绝不阻断出书。
    coloring_path: Optional[Path] = None
    _lv = str(item.level).strip().lower().lstrip("l")
    if _lv in ("smart", "0", "1", "2", "3"):
        cp = img_dir / "coloring.png"
        if resume and (not mock) and cp.exists() and cp.stat().st_size > 0:
            coloring_path = cp
        else:
            try:
                # 画题取【故事最简单的一句】(通常第 1 句)，让涂色内容贴本书核心概念、可被老师复用；
                # 缺省再退回主题/书名。例：'Shoes always come in a pair.' → 一双鞋。
                _first_line = ""
                for _pg in outline.pages:
                    if getattr(_pg, "page_type", "") == "story" and (_pg.text or "").strip():
                        _first_line = (_pg.text or "").strip()
                        break
                subj = _first_line or (outline.theme or item.title or "the story").strip()
                color_prompt = (
                    "Black-and-white COLORING BOOK line art for young children (ages 4-7). "
                    f"One simple, clear scene that illustrates this sentence: \"{subj}\". "
                    "Draw only the key objects from the sentence as large simple shapes "
                    "(e.g. if it is about a pair of items, draw that matching pair). "
                    "Thick clean bold black outlines only, NO shading, NO color, NO gray fills, "
                    "pure solid white background, large simple shapes with generous space to color, "
                    "centered and uncluttered. No text, no words, no letters anywhere."
                )
                with _img_guard():
                    generate_image(prompt=color_prompt, dest=cp, references=[],
                                   label=f"{item.name_prefix} 涂色线稿", mock=mock)
                coloring_path = cp
            except Exception as e:  # noqa: BLE001
                print(f"[{item.name_prefix}] 涂色线稿生成失败（worksheet 用留白画框兜底）: {e}")
                coloring_path = None

    pre = item.name_prefix
    pb = book_dir / f"{pre}_Reader.pptx"
    build_picturebook_pptx(outline, image_paths, pb)
    ws = book_dir / f"{pre}_Worksheet.pptx"
    build_worksheet(outline, ws, image_paths=image_paths, coloring_image=coloring_path)
    rr = book_dir / f"{pre}_Reading_Report.docx"
    build_reading_report(outline, rr)
    tg = book_dir / f"{pre}_Teachers_Guide.docx"
    build_teacher_guide(outline, tg)

    res.outputs = [str(pb), str(ws), str(rr), str(tg)]

    # ④ 自动体检（evals）：跑完即查，按结论收紧「待人工抽查」标记 → 定向抽查
    try:
        from evals import run_all, WARN, ERROR
        rep = run_all(outline=outline,
                      worksheet_questions=getattr(ec, "worksheet_questions", None),
                      rr_items=getattr(ec, "rr_questions", None))
        res.eval_level = "error" if not rep.passed else ("warn" if rep.n_warn else "ok")
        res.eval_msgs = [f"[{i.category}] {i.msg}" for i in rep.issues
                         if i.level in (ERROR, WARN)][:8]
        # 出图占位失败 或 体检非全绿 → 需人工抽查；全绿且无出图失败 → 可直接放行
        res.needs_human_review = bool(res.error) or (res.eval_level != "ok")
    except Exception as e:  # noqa: BLE001
        res.eval_level = ""
        res.needs_human_review = True
        print(f"[{item.name_prefix}] evals 跳过: {e}")

    # 出图前自检门结果并入体检：主角铁律违规 → 至少 warn + 强制人工抽查（红线，优先展示）
    if ip_lock_issues:
        res.eval_msgs = [f"[IP锁] {m}" for m in ip_lock_issues][:8] + res.eval_msgs
        res.eval_msgs = res.eval_msgs[:12]
        res.needs_human_review = True
        if res.eval_level not in ("error",):
            res.eval_level = "warn"
        print(f"[{item.name_prefix}] [WARN] 主角铁律自检命中 {len(ip_lock_issues)} 处，已标记人工抽查")

    # 单本 ZIP
    zp = book_dir / f"{pre}_Full_Set.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in [pb, ws, rr, tg]:
            z.write(f, arcname=f.name)
        for img in image_paths:
            if img.exists():
                z.write(img, arcname=f"images/{img.name}")
    res.zip_path = str(zp)
    res.status = "ok"
    res.elapsed_s = time.time() - t0
    return res


# ============================================================
#  批量编排（并发 + 隔离 + 重试 + 日志）
# ============================================================
def run_batch(
    items: list[BatchItem],
    *,
    out_root: Optional[Path] = None,
    concurrency: int = 2,
    image_concurrency: int = 4,
    flat: bool = False,
    make_master_zip: bool = True,
    mock: bool = False,
    resume: bool = False,
    retries: int = 1,
    progress_cb: Optional[Callable[[int, int, BatchResult], None]] = None,
) -> dict:
    """跑一批。返回 summary dict（含每本结果 + 日志路径）。

    image_concurrency：① 全局出图并发上限（所有本子在途请求总数，贴 API RPM）。
    resume：② 断点续跑——已存在的页/本不重复出图（重跑失败本时配合 out_root 复用）。
    """
    out_root = out_root or (OUTPUTS_DIR / f"batch_{time.strftime('%Y%m%d_%H%M%S')}")
    out_root.mkdir(parents=True, exist_ok=True)
    set_image_concurrency(image_concurrency)   # ① 启动全局出图节流
    results: list[BatchResult] = []
    total = len(items)
    done = 0

    def _task(it: BatchItem) -> BatchResult:
        last_err = ""
        for attempt in range(retries + 1):
            try:
                return run_one(it, out_root, mock=mock, flat=flat,
                               resume=resume, image_workers=image_concurrency)
            except Exception as e:  # noqa: BLE001
                last_err = f"{e}\n{traceback.format_exc()[:800]}"
                time.sleep(2)
        r = BatchResult(item=it, status="failed", error=last_err)
        return r

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        futures = {ex.submit(_task, it): it for it in items}
        for fut in as_completed(futures):
            it = futures[fut]
            try:
                r = fut.result(timeout=PER_BOOK_TIMEOUT_S)
            except Exception as e:  # noqa: BLE001 (含超时)
                r = BatchResult(item=it, status="failed", error=f"timeout/exec: {e}")
            results.append(r)
            done += 1
            if progress_cb:
                progress_cb(done, total, r)

    # 主 ZIP（把每本的全套 zip 再合并）
    master_zip = ""
    if make_master_zip:
        master_zip = str(out_root / "ALL_BOOKS.zip")
        with zipfile.ZipFile(master_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for r in results:
                if r.zip_path and Path(r.zip_path).exists():
                    z.write(r.zip_path, arcname=Path(r.zip_path).name)

    # 处理日志
    log = {
        "out_root": str(out_root),
        "total": total,
        "ok": sum(1 for r in results if r.status == "ok"),
        "failed": sum(1 for r in results if r.status == "failed"),
        "need_review": sum(1 for r in results if r.status == "ok" and r.needs_human_review),
        "clean_pass": sum(1 for r in results
                          if r.status == "ok" and not r.needs_human_review),
        "master_zip": master_zip,
        "books": [
            {
                "title": r.item.title, "level": r.item.level, "book": r.item.book_number,
                "name_prefix": r.item.name_prefix,
                "status": r.status, "display_status": _book_display_status(r),
                "elapsed_s": round(r.elapsed_s, 1),
                "outputs": r.outputs, "zip": r.zip_path,
                "needs_human_review": r.needs_human_review,
                "eval_level": r.eval_level, "eval_msgs": r.eval_msgs,
                "skipped_pages": r.skipped_pages,
                "placeholder_pages": r.placeholder_pages,
                "placeholder_count": len(r.placeholder_pages),
                "error": r.error[:500],
            }
            for r in results
        ],
    }
    log_path = out_root / "batch_log.json"
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    log["log_path"] = str(log_path)
    return log


# ============================================================
#  ③ Dry-run 预检：开跑前本地校验（不花 API），列出每本张数/命中/预估
# ============================================================
def preflight(items: list[BatchItem]) -> list[dict]:
    """对解析出的每本做廉价本地预检：页数、官方大纲/出图Prompt 命中、预估张数/耗时。

    全部走本地 JSON（syllabus.match / image_prompts.match），不调用任何 AI 接口。
    """
    try:
        from image_prompts import match as _img_match
    except Exception:  # pragma: no cover
        _img_match = None  # type: ignore
    try:
        from syllabus import match as _syl_match
    except Exception:  # pragma: no cover
        _syl_match = None  # type: ignore

    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for it in items:
        n_story = len(_story_lines(it.story))
        imgs = max(IMAGES_PER_BOOK, n_story + 1)
        syl_hit = bool(_syl_match and _syl_match(it.level, it.title))
        img_hit = bool(_img_match and _img_match(it.level, it.title))
        key = (it.level, re.sub(r"\s+", "", it.title.lower()))
        warns = []
        if not it.title.strip():
            warns.append("缺标题")
        if n_story < 5:
            warns.append(f"正文仅{n_story}句(建议≥7)")
        if not syl_hit:
            warns.append("未命中官方S&S(走启发式)")
        if not img_hit:
            warns.append("未命中官方出图Prompt")
        if key in seen:
            warns.append("疑似重复本")
        seen.add(key)
        rows.append({
            "Level": it.level, "Book#": it.book_number, "Title": it.title,
            "正文句数": n_story, "出图张数": imgs,
            "官方S&S": "✅" if syl_hit else "—",
            "官方出图Prompt": "✅" if img_hit else "—",
            "预估耗时": f"{(EST_SECS_TEXT + imgs * EST_SECS_PER_IMAGE) // 60}分{(EST_SECS_TEXT + imgs * EST_SECS_PER_IMAGE) % 60}秒",
            "提示": "；".join(warns) or "ok",
        })
    return rows


def items_from_failed_log(log_path: str | Path) -> list[BatchItem]:
    """从既往 batch_log.json 读取 failed / 待抽查的本，重建 BatchItem 供重跑。

    注意：日志不含故事原文，重跑需调用方在 items 里带上原 story；此处仅用于
    定位"哪些本要重跑"。配合 UI：从原始批量输入里按 (level,title,book#) 过滤。
    """
    p = Path(log_path)
    if not p.exists():
        return []
    try:
        log = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    out: list[BatchItem] = []
    for b in log.get("books", []):
        out.append(BatchItem(title=b.get("title", ""), level=str(b.get("level", "")),
                             book_number=str(b.get("book", "")), story=""))
    return out


def select_failed_items(all_items: list[BatchItem], log_path: str | Path) -> list[BatchItem]:
    """用既往日志里 failed 或 needs_human_review 的 (level,title,book#) 过滤原始 items（保留 story）。"""
    p = Path(log_path)
    if not p.exists():
        return []
    try:
        log = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    keys = {
        (str(b.get("level", "")), re.sub(r"\s+", "", str(b.get("title", "")).lower()),
         str(b.get("book", "")))
        for b in log.get("books", [])
        if b.get("status") == "failed" or b.get("needs_human_review")
    }
    picked = []
    for it in all_items:
        k = (str(it.level), re.sub(r"\s+", "", it.title.lower()), str(it.book_number))
        if k in keys:
            picked.append(it)
    return picked


# ============================================================
#  Streamlit 入口
# ============================================================
def preflight_from_ui() -> None:
    """③ 从 UI 跑 Dry-run 预检并展示一张校验表（不花 API）。"""
    import streamlit as st

    items = parse_batch_outlines(st.session_state.get("batch_outlines_raw", ""))
    if not items:
        st.warning("没解析到任何大纲。请检查格式：每本第一行 `Title | Level | Book#`，多本用 `===` 分隔。")
        return
    limit_err = validate_web_batch_limit(items)
    if limit_err:
        st.error(limit_err)
        return
    rows = preflight(items)
    total_imgs = sum(r["出图张数"] for r in rows)
    total_secs = sum(EST_SECS_TEXT + r["出图张数"] * EST_SECS_PER_IMAGE for r in rows)
    img_conc = max(1, int(st.session_state.get("batch_image_concurrency", 4)))
    wall = total_secs / img_conc
    n_warn = sum(1 for r in rows if r["提示"] != "ok")
    st.info(
        f"共 **{len(rows)} 本** · 预计出图 **{total_imgs} 张** · "
        f"并发 {img_conc} 下预估总墙钟 **约 {wall/60:.0f} 分钟** · "
        f"{'⚠️ ' + str(n_warn) + ' 本有提示' if n_warn else '✅ 全部就绪'}"
    )
    st.dataframe(rows, width="stretch", hide_index=True)
    if n_warn:
        st.caption("「提示」非阻断，可照常开跑；未命中官方大纲/出图Prompt 的本会走启发式，注意抽查。")


def run_batch_from_ui() -> None:
    """从 web_app 的 session_state 读取配置并跑批量，带实时进度表 + 定向抽查。"""
    import streamlit as st

    raw = st.session_state.get("batch_outlines_raw", "")
    items = parse_batch_outlines(raw)
    if not items:
        st.warning("没解析到任何大纲。请检查格式：每本第一行 `Title | Level | Book#`，多本用 `===` 分隔。")
        return
    limit_err = validate_web_batch_limit(items)
    if limit_err:
        st.error(limit_err)
        return

    concurrency = int(st.session_state.get("batch_concurrency", 2))
    image_conc = int(st.session_state.get("batch_image_concurrency", 4))
    flat = st.session_state.get("batch_output_mode") == "平铺 + 规范命名"
    make_zip = bool(st.session_state.get("batch_zip", True))
    mock = bool(st.session_state.get("batch_mock", False))
    resume = bool(st.session_state.get("batch_resume", False))

    # ② 重跑失败本：若勾选且填了既往日志，则只挑 failed/待抽查的本，复用其 out_root + 续跑
    rerun_log = (st.session_state.get("batch_rerun_log") or "").strip()
    out_root = None
    if rerun_log:
        picked = select_failed_items(items, rerun_log)
        if picked:
            items = picked
            out_root = Path(rerun_log).parent
            resume = True
            st.warning(f"♻️ 重跑模式：仅跑 {len(items)} 本（failed/待抽查），复用目录 `{out_root}` 并续跑已出图。")
        else:
            st.info("既往日志里没有需要重跑的本（或标题对不上），按全量跑。")

    st.info(f"共 {len(items)} 本 → {len(items) * 4} 件交付物 · 本并发 {concurrency} · 出图全局并发 {image_conc}"
            + ("（续跑）" if resume else ""))
    bar = st.progress(0.0, "批量生产中...")

    # ⑤ 每本一行的实时进度表：先全量预填「排队中」，每完成一本就地更新
    table_box = st.empty()
    rows = {
        it.name_prefix: {"本": it.name_prefix, "状态": "⏳ 排队/进行中",
                         "用时": "", "体检": "", "抽查": "", "备注": ""}
        for it in items
    }

    def _render_table() -> None:
        table_box.dataframe(list(rows.values()), width="stretch", hide_index=True)

    _render_table()

    def _cb(done: int, total: int, r: BatchResult) -> None:
        bar.progress(done / total, f"已完成 {done}/{total} 本")
        key = r.item.name_prefix
        if key in rows:
            eval_icon = {"ok": "🟢", "warn": "🟡", "error": "🔴", "": "—"}.get(r.eval_level, "—")
            ph = f"占位{len(r.placeholder_pages)}页" if r.placeholder_pages else ""
            rows[key] = {
                "本": key,
                "状态": "✅ 完成" if r.status == "ok" else "❌ 失败",
                "用时": f"{r.elapsed_s:.0f}s",
                "体检": eval_icon,
                "抽查": "需抽查" if r.needs_human_review else "可放行",
                "备注": ph or (r.error[:80] or (f"复用{r.skipped_pages}页" if r.skipped_pages else "")),
            }
            _render_table()

    summary = run_batch(
        items, out_root=out_root, concurrency=concurrency, image_concurrency=image_conc,
        flat=flat, make_master_zip=make_zip, mock=mock, resume=resume, progress_cb=_cb,
    )
    bar.progress(1.0, "完成")
    st.success(
        f"完成：成功 {summary['ok']} / 失败 {summary['failed']} · "
        f"🟢 可直接放行 {summary.get('clean_pass', 0)} · 🟡🔴 需抽查 {summary.get('need_review', 0)}"
        f" · 输出目录 `{summary['out_root']}`"
    )

    # ④ 定向抽查：只把「需人工抽查」的本 + 体检红/黄项列出来，把人力用在刀刃上
    review = [b for b in summary["books"] if b.get("needs_human_review")]
    if review:
        with st.expander(f"🔎 需人工抽查（{len(review)} 本）— 其余已体检通过可直接放行", expanded=True):
            for b in review:
                tag = {"error": "🔴", "warn": "🟡"}.get(b.get("eval_level"), "⚪")
                st.markdown(f"{tag} **{b['title']}** (L{b['level']} · Book{b['book']}) — "
                            f"{b['status']}{' · ' + b['error'][:120] if b.get('error') else ''}")
                for m in b.get("eval_msgs", []):
                    st.caption(f"　• {m}")
    else:
        st.caption("🟢 全部体检通过，无需逐本抽查。")

    failed = [b for b in summary["books"] if b["status"] == "failed"]
    if failed:
        st.error(f"❌ {len(failed)} 本失败。勾选「重跑失败本」并把下方日志路径填回即可只补跑这些本：")
        st.code(summary.get("log_path", ""), language="text")

    if summary.get("master_zip"):
        mz = summary["master_zip"]
        if Path(mz).exists():
            with open(mz, "rb") as f:
                st.download_button("⬇️ 下载全部（ALL_BOOKS.zip）", data=f.read(),
                                   file_name="ALL_BOOKS.zip", mime="application/zip")
    with st.expander("📋 完整 JSON 日志", expanded=False):
        st.json(summary)
    st.session_state["batch_last_summary"] = summary
    try:
        from web_app import render_batch_output_table
        render_batch_output_table(summary, expanded=True)
    except Exception:
        pass
    return summary
