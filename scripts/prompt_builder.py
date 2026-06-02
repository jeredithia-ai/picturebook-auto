"""即梦 4.6 单页 prompt 构造（v1.3）。

v1.3 官方人物设定沉淀（用户提供 L4-6 完整 8/10/12 岁三档总设定图）：
  1. IP_BLOCKS 按官方设定图回填：
     - 8 岁档：Mia 紫色短袖 T + Tommy 蓝白条短袖 T
     - 10 岁档：Mia 紫色长袖卫衣 + Tommy 蓝色长袖卫衣
     - 12 岁档：Mia 紫色长袖针织 + Tommy 海军蓝短袖 polo
  2. CONSISTENCY_LOCK 删全局"长袖"硬规则，改为"严格按参考图"驱动
  3. mia/tommy_age{N}.png 单角色设定图保持最高参考图优先级
  4. character_bible_l4-6_clean.png 作为多角色场景下的兜底参考

v1.2.x 迭代（沉淀自 L4 Visiting Scotland 多轮调试）：
  1. CONSISTENCY_LOCK 铁律段，独立放在 prompt 末尾受保护区
  2. Mia 发型描述：中后位单束马尾 + 面侧散发框脸
  3. 每个 IP 块显式声明 "bare wrists" + NO_ACCESSORY 反例

v1.2 紧急修复（沉淀自 L4 Visiting Scotland 第三轮：v1.1 反作用导致只画 Mia/Tommy）：
  1. SCENE 段前置且永远受保护、永不截断 —— 模型最先看到要画什么场景
  2. 新增 MUST_INCLUDE 强制角色/道具清单 —— 把配角必须出现写进硬约束
  3. 删除 GROUP_COMPOSITION_RULE 那句 "Mia and Tommy ... largest" 误导
  4. IP 描述压成一行放在 SCENE 之后，仅作"外观锚定"不喧宾夺主
  5. SHOT 占比下调（medium 40-55%, full 30-45%），给配角和道具留位置
  6. 删冗余的 FACIAL_VOLUME / HANDS_RULE 独立段（合并入 STYLE）
  7. character_bible 默认用 _clean 净版（中文水印已涂白）

结构（v1.2.2）：
  [HEAD - 受保护]   STYLE_SHORT + SHOT
  [MID  - 受保护]   SCENE + MUST_INCLUDE
  [ANCHOR - 可压]   IP_INLINE + EXPRESSION + HANDS（条件）
  [LOCK - 受保护]   CONSISTENCY_LOCK（马尾/长袖/无手表）
  [TAIL - 受保护]   COMPOSITION_TIPS + 留白 + 禁文字
"""
from __future__ import annotations

import re as _re
from pathlib import Path
from dataclasses import dataclass

from character_registry import (
    REGISTRY as CHAR_REGISTRY,
    get_description as registry_get_desc,
    get_reference_path as registry_get_ref,
    resolve_name as registry_resolve_name,
)
from config import CHARACTERS_DIR, STYLE_DIR, TEXT_SAFE_RATIO_MIN, TEXT_SAFE_RATIO_MAX
from parser import BookOutline, PageSpec


# ---------- 风格基线（v1.2.1：删手部强制；改为条件触发）----------
STYLE_BIBLE = (
    "Warm watercolor children's book illustration, layered wash with visible brush texture, "
    "clear faces with soft volume and rosy cheeks, "
    "low saturation gentle gradient, soft simplified background. "
    "NOT chibi, NOT flat anime sticker, NOT 3D render, NOT pixel art"
)

# 手部规则（条件触发，仅当场景含手部动作时附加）
HANDS_ACTION_KEYWORDS = (
    "holding", "hold", "reaching", "reach", "waving", "wave",
    "clapping", "clap", "grabbed", "grab", "pointing", "point",
    "handing", "hand-", "carrying", "carry", "throwing", "throw",
    "catching", "catch", "lifting", "lift", "raising", "raise",
    "hugging", "hug", "shaking hands",
)
HANDS_RULE = (
    "Hands of human characters: each hand has exactly five fingers, anatomically correct, "
    "when holding props all fingers visibly wrap around object; no extra fingers, no fused fingers"
)

# 主角占比 + 镜头景别（v1.2 下调，给配角和道具留位置）
SUBJECT_SCALE_BY_SHOT: dict[str, str] = {
    "close": (
        "Composition: close-up, main characters' heads-and-shoulders fill 50-65% of frame, "
        "foreground center, sharp focus on faces"
    ),
    "medium": (
        "Composition: medium shot, main characters fill 40-55% of frame height, "
        "foreground center-or-right, sharp focus on characters"
    ),
    "full": (
        "Composition: full body, main characters fully visible head-to-feet, fill 30-45% of frame height, "
        "foreground, sharp focus on characters, with clear scene environment around them"
    ),
    "wide": (
        "Composition: wide shot with environment, main characters fully visible at 25-35% of frame height, "
        "foreground center, environment elements (buildings, hills, landmarks) clearly painted around them"
    ),
}
DEFAULT_SHOT = "medium"

STYLE_TAIL_TPL = (
    "Reserve {lo:.0%}-{hi:.0%} clean blank area at {corner_phrase} for caption "
    "(no people/props/text there). "
    "No text, no letters, no numbers, no watermarks anywhere in the image."
)


# ---------- IP 描述（v1.3：严格按官方人物设定图，按年龄段区分长/短袖）----------
# 官方资产：assets/characters/character_bible_l4-6_clean.png（L4-6 三档总设定）
#            assets/characters/{mia,tommy}_age{8,10,12}.png（单角色四视图+表情）
NO_ACCESSORY = "NO watch (especially NO black watch on left wrist), NO bracelet, NO necklace, NO earrings, NO glasses, NO hat"

# Mia 发型：所有年龄段共用（官方设定图都是中后位单束马尾）
PONYTAIL_RULE = (
    "Mia's hair EXACTLY matches the Mia reference sheet: long brown ponytail tied at back-middle "
    "of head, tail flows past shoulders, soft strands frame face. NO loose hair, NO bun, NO puff"
)

# v1.3：删除全局"长袖"硬规则；改为"严格按参考图"，由 IP_BLOCKS 描述各年龄段服装
CONSISTENCY_LOCK = (
    "CRITICAL (no exception): "
    "(1) " + PONYTAIL_RULE + ". "
    "(2) Each character's outfit EXACTLY matches the character reference sheet provided "
    "(top color, sleeve length, pants, shoes must match the reference for that character's age). "
    "(3) Bare wrists: NO watch on ANY wrist (even in pockets/by side/on hips), "
    "NO smartwatch, NO bracelet, NO band of any kind on wrists or arms"
)

# Mia 发型短描述（IP_BLOCKS 内复用，关键词与 PONYTAIL_RULE 完全一致）
_MIA_PONYTAIL = (
    "long brown hair in a single soft ponytail tied at back-middle of head around ear level "
    "with long tail flowing down past shoulders, soft face-framing strands in front"
)

# 超紧凑 IP 块（多角色场景启用，把 LOCK + 参考图当主锁，文字只留外观关键差异点）
# 触发条件：cast 里同时有 Mia + Tommy 或 Mia/Tommy + Parents
COMPACT_IP_BLOCKS: dict[tuple[str, int], str] = {
    ("mia", 8):    "Mia: 12y GIRL, ponytail, purple SHORT-SLEEVE tee, denim jeans, white sneakers",
    ("tommy", 8):  "Tommy: 8y BOY, short brown hair, blue-and-white striped SHORT-SLEEVE tee, denim jeans, white sneakers",
    ("mia", 10):   "Mia: 10y GIRL, ponytail, lavender LONG-SLEEVE sweatshirt, gray sweatpants, white sneakers",
    ("tommy", 10): "Tommy: 10y BOY, short messy brown hair, light blue LONG-SLEEVE sweatshirt, khaki pants, white sneakers",
    ("mia", 12):   "Mia: 12y GIRL — HAIR LOCK: long brown hair tied UP into a HIGH PONYTAIL at the back-top of the head with a small white scrunchie, ponytail tail flows down behind her shoulders. CRITICAL CONSISTENCY across viewing angles — from FRONT/3-quarter view: you see her face with short fringe bangs and a few thin face-framing strands; the LONG part of her hair is GATHERED UP high behind the head (NOT cascading loose on both sides past the chest); from SIDE view: the high ponytail is clearly visible at the back-crown of the head; from BACK view: the full high ponytail flows down. NEVER full loose flowing shoulder-length hair on both sides of the face, NEVER a center-parted curtain of long hair framing the entire face. Outfit: lavender LONG-SLEEVE polo-collar pullover, white wide-leg trousers, white sneakers, NO accessories",
    ("tommy", 12): "Tommy: 12y BOY, short messy brown hair, navy SHORT-SLEEVE polo, blue jeans, white sneakers",
}
COMPACT_PARENTS_BLOCK = "Mom: long brown wavy hair, cream top, blue jeans. Dad: short brown hair, gray polo, khaki pants"

# IP_BLOCKS：与官方人物设定图（L4-6 三个年龄段）一一对应
IP_BLOCKS: dict[tuple[str, int], str] = {
    # ----- 8 岁档（L0-L3 启蒙绘本，参考设定图 = 短袖夏装）-----
    ("mia", 8):    "Mia: 8y GIRL, " + _MIA_PONYTAIL + ", "
                   "lavender purple SHORT-SLEEVE tee, denim jeans, white sneakers, "
                   "bare wrists, " + NO_ACCESSORY,
    ("tommy", 8):  "Tommy: 8y BOY (NOT a girl, NO ponytail, NO long hair), short tidy brown hair, "
                   "blue-and-white striped SHORT-SLEEVE tee, denim jeans, white sneakers, "
                   "bare wrists, " + NO_ACCESSORY,
    # ----- 10 岁档（L4-L5 中级绘本，参考设定图 = 长袖卫衣）-----
    ("mia", 10):   "Mia: 10y GIRL, " + _MIA_PONYTAIL + ", "
                   "lavender purple LONG-SLEEVE sweatshirt (sleeves cover wrists), "
                   "light gray sweatpants, white sneakers, bare wrists, " + NO_ACCESSORY,
    ("tommy", 10): "Tommy: 10y BOY (NOT a girl, NO ponytail, NO long hair), short messy brown hair, "
                   "light blue LONG-SLEEVE sweatshirt (sleeves cover wrists), khaki straight pants, "
                   "white sneakers, bare wrists, " + NO_ACCESSORY,
    # ----- 12 岁档（L5-L6 高级绘本，参考设定图 = Mia 长袖 polo 领 / Tommy 短袖 polo）-----
    ("mia", 12):   "Mia: 12y GIRL, " + _MIA_PONYTAIL + ", "
                   "lavender purple LONG-SLEEVE polo-collar pullover with V-neck collar "
                   "(sleeves cover wrists), white wide-leg loose trousers, white sneakers, "
                   "bare wrists, " + NO_ACCESSORY,
    ("tommy", 12): "Tommy: 12y BOY (NOT a girl, NO ponytail, NO long hair), short messy brown hair, "
                   "navy SHORT-SLEEVE polo shirt with V-collar, blue denim straight-cut jeans, "
                   "white sneakers, bare wrists, " + NO_ACCESSORY,
}

PARENTS_BLOCK = (
    "Mom: adult woman, long brown wavy hair, cream LONG-SLEEVE top, blue jeans, gentle smile, bare wrists. "
    "Dad: adult man, short tidy brown hair, gray LONG-SLEEVE shirt, khaki trousers, warm smile, bare wrists"
)


# ---------- 角色识别（仅认显式人物词；代词 they/their 不算父母出场）----------
# v1.3.1：用单词边界正则，避免 "moment" 触发 "mom" 这类假阳性
_PARENT_WORDS_RE = _re.compile(r"\b(mom|mum|dad|parent|mother|father|family)\b", _re.I)
_MIA_RE = _re.compile(r"\bmia\b", _re.I)
_TOMMY_RE = _re.compile(r"\btommy\b", _re.I)


def detect_cast(text: str, aliases: dict[str, str] | None = None) -> dict[str, bool]:
    """识别页面文本里出现的 IP。

    aliases: 形如 {"anna": "mia", "kevin": "tommy"}。
            scene 出现 "Anna" 时也会触发 cast["mia"] = True，
            让模型用 Mia 的形象去画 Anna。
    """
    t = text or ""
    cast = {
        "mia": bool(_MIA_RE.search(t)),
        "tommy": bool(_TOMMY_RE.search(t)),
        "parents": bool(_PARENT_WORDS_RE.search(t)),
    }
    if aliases:
        for alias_name, target in aliases.items():
            if alias_name and target in cast:
                # 用单词边界匹配别名，避免 "anna" 命中 "channel" 之类
                if _re.search(rf"\b{_re.escape(alias_name)}\b", t, _re.I):
                    cast[target] = True
    return cast


def _format_ip_block_with_alias(ip_block: str, target: str, alias_name: str) -> str:
    """把 IP_BLOCKS 里的 "Mia: ..." 改写成 "Anna (Mia visual): ..."。
    模型读到时知道：这个角色叫 Anna，但视觉用 Mia 参考图。"""
    target_proper = target.capitalize()
    alias_proper = alias_name.capitalize()
    if ip_block.startswith(target_proper + ":"):
        rest = ip_block[len(target_proper) + 1:].lstrip()
        return f"{alias_proper} (use {target_proper} reference visual): {rest}"
    return ip_block


# ---------- v1.2：从 scene 自动抽取"必须出现的元素"清单 ----------
# 这是关键修复：让模型先看到"必须画"清单，再看到 Mia/Tommy 外观锚定
MUST_INCLUDE_KEYWORDS: list[tuple[str, str]] = [
    # 次要人物
    (r"\bmom\b|\bmother\b|\bmum\b",  "Mom (adult woman, NOT a child)"),
    (r"\bdad\b|\bfather\b",  "Dad (adult man, NOT a child)"),
    (r"\bgrandma\b|\belderly\b|\bgrandmother\b|\bnice woman\b", "elderly woman (NOT a child, NOT Mia, mature wrinkled face)"),
    (r"\bgrandpa\b|\bgrandfather\b|\bold man\b", "elderly man (NOT a child, NOT Tommy, mature wrinkled face)"),
    (r"\bkilt\b|\bscotsman\b|\bscotsmen\b|\bbagpip\w*\b", "adult Scotsman in kilt (NOT a child, NOT Mia, NOT Tommy)"),
    (r"\bteacher\b", "adult teacher (NOT a child)"),
    (r"\bchef\b|\bcook\b", "adult chef (NOT a child)"),
    (r"\bshopkeeper\b|\bvendor\b|\bseller\b", "adult shopkeeper (NOT a child)"),
    # 动物
    (r"\bsheep\b", "white fluffy sheep"),
    (r"\bdog\b", "dog"),
    (r"\bcat\b", "cat"),
    (r"\brabbit\b|\bbunny\b", "rabbit"),
    (r"\bhorse\b", "horse"),
    (r"\bbird\b", "bird"),
    (r"\bcow\b", "cow"),
    (r"\bduck\b", "duck"),
    (r"\bfish\b", "fish"),
    # 建筑/地标
    (r"\bcastle\b", "tall stone castle"),
    (r"\bloch\b|\blake\b", "blue water"),
    (r"\bhill\b", "green hill"),
    (r"\bmountain\b", "mountain"),
    (r"\bbridge\b", "bridge"),
    (r"\bchurch\b", "church"),
    (r"\bcottage\b", "stone cottage"),
    (r"\bmarket\b", "market stalls"),
    (r"\bshop\b|\bstore\b", "shop front"),
    (r"\bschool\b", "school building"),
    (r"\bpark\b", "park with trees"),
    # 道具
    (r"\bmap\b", "folded paper map"),
    (r"\bbagpip\w*\b", "bagpipes instrument"),
    (r"\bteapot\b|\bteacup\b|\btea\b", "white porcelain teapot and teacups"),
    (r"\bcake\b", "cake"),
    (r"\bbook\b", "book"),
    (r"\bball\b", "ball"),
    (r"\bbicycle\b|\bbike\b", "bicycle"),
    (r"\bumbrella\b", "umbrella"),
    (r"\bbasket\b", "basket"),
]

def _detect_must_include(scene_text: str) -> list[str]:
    t = (scene_text or "").lower()
    items: list[str] = []
    seen: set[str] = set()
    for pattern, label in MUST_INCLUDE_KEYWORDS:
        if _re.search(pattern, t) and label not in seen:
            items.append(label)
            seen.add(label)
    return items


_CORNER_PHRASE = {
    "top-left": "top-left",
    "top-right": "top-right",
    "bottom-left": "bottom-left",
    "bottom-right": "bottom-right",
}


@dataclass
class BuiltPrompt:
    prompt: str
    references: list[Path]


def build_page_prompt(page: PageSpec, book: BookOutline, ip_age: int) -> BuiltPrompt:
    cast_text = (page.text or "") + " " + (page.scene or "")
    aliases = getattr(book, "aliases", {}) or {}
    custom_characters = getattr(book, "custom_characters", {}) or {}
    cast = detect_cast(cast_text, aliases)

    # ==== v1.4: 自动识别 registry 里所有已知角色（含 Anna / Teacher Kim / Winnie / Cate 等）====
    # 跳过已经被 detect_cast 处理过的 mia/tommy/parents
    handled = {"mia", "tommy", "mom", "dad"}
    registry_in_scene: list[dict] = []  # 每项 {key, name_in_story, description, ref_path}
    for key, char in CHAR_REGISTRY.items():
        if key in handled:
            continue
        # 匹配 key 本身 OR 任何 alias
        name_to_match = [key.replace("_", " ")] + list(char.get("aliases", []))
        matched_alias = None
        for name in name_to_match:
            if _re.search(rf"\b{_re.escape(name)}\b", cast_text, _re.I):
                matched_alias = name
                break
        if not matched_alias:
            continue
        # 取年龄合适的描述
        if char.get("kind") in ("adult", "pet", "brand", "family"):
            age_key = next(iter(char.get("description_by_age", {}).keys()), "adult")
        else:
            age_key = ip_age
        desc = registry_get_desc(key, age_key) or ""
        ref = registry_get_ref(key, age_key)
        registry_in_scene.append({
            "key": key,
            "name_in_story": matched_alias.capitalize(),
            "description": desc,
            "ref_path": ref,
        })

    # 检测自定义角色（向后兼容 BookOutline.custom_characters，如手动注册的）
    custom_in_scene: list[tuple[str, str]] = []
    for name, desc in custom_characters.items():
        # 若 registry 已经处理过同名角色，跳过避免重复
        if any(r["name_in_story"].lower() == name.lower() or r["key"] == name.lower() for r in registry_in_scene):
            continue
        if _re.search(rf"\b{_re.escape(name)}\b", cast_text, _re.I):
            custom_in_scene.append((name, desc))

    # 封面默认所有主角出场：优先 registry/custom；否则默认 Mia+Tommy
    if (page.page_type == "cover" and not (cast["mia"] or cast["tommy"])
            and not registry_in_scene and not custom_in_scene):
        cast["mia"] = True
        cast["tommy"] = True

    # 镜头景别
    shot = (page.shot or DEFAULT_SHOT).strip().lower()
    if shot not in SUBJECT_SCALE_BY_SHOT:
        shot = DEFAULT_SHOT
    shot_text = SUBJECT_SCALE_BY_SHOT[shot]

    # 场景文本
    scene = (page.scene or page.text or "").strip()

    # 表情
    expression = page.expression or _infer_expression(page.text)

    # 反向别名表：mia -> [anna], tommy -> [kevin]（同 target 可有多别名）
    inv_aliases: dict[str, list[str]] = {}
    for alias_name, target in aliases.items():
        inv_aliases.setdefault(target, []).append(alias_name)

    # 同框人数 ≥2 时改用 COMPACT_IP_BLOCKS（LOCK + 参考图当主锁，文字只留关键差异点）
    total_chars = (
        sum([cast["mia"], cast["tommy"], cast["parents"]])
        + len(custom_in_scene)
        + len(registry_in_scene)
    )
    multi_char = total_chars >= 2
    mia_src = COMPACT_IP_BLOCKS if multi_char else IP_BLOCKS
    tommy_src = COMPACT_IP_BLOCKS if multi_char else IP_BLOCKS
    parents_block = COMPACT_PARENTS_BLOCK if multi_char else PARENTS_BLOCK

    # IP 行（合并所有角色为一行，作为外观锚定）
    # 顺序：registry 已知主角/配角先（按故事中出场顺序）→ custom → Mia/Tommy → parents
    ip_lines: list[str] = []
    for r in registry_in_scene:
        ip_lines.append(r["description"])
    for _name, desc in custom_in_scene:
        ip_lines.append(desc)
    if cast["mia"]:
        block = mia_src[("mia", ip_age)]
        for alias_name in inv_aliases.get("mia", []):
            if alias_name in cast_text.lower():
                block = _format_ip_block_with_alias(block, "mia", alias_name)
                break  # 一本书一个别名足矣
        ip_lines.append(block)
    if cast["tommy"]:
        block = tommy_src[("tommy", ip_age)]
        for alias_name in inv_aliases.get("tommy", []):
            if alias_name in cast_text.lower():
                block = _format_ip_block_with_alias(block, "tommy", alias_name)
                break
        ip_lines.append(block)
    if cast["parents"] and page.page_type == "story":
        ip_lines.append(parents_block)
    ip_anchor = " ".join(ip_lines)

    # 必含清单（v1.2 关键新机制）
    must_items = _detect_must_include(cast_text)

    # 角部留白
    if page.page_type == "cover":
        corner_phrase = "top 35%"
        cover_layout = (
            "Cover composition: upper 35% must be clean empty pale sky area, "
            "ABSOLUTELY NO TEXT, NO LETTERS, NO BOOK TITLE, NO WORDS rendered in the image"
        )
    else:
        corner = page.text_corner or "top-left"
        corner_phrase = _CORNER_PHRASE.get(corner, "top-left")
        cover_layout = ""

    tail_keep = STYLE_TAIL_TPL.format(
        lo=TEXT_SAFE_RATIO_MIN, hi=TEXT_SAFE_RATIO_MAX, corner_phrase=corner_phrase
    )

    # 拼装顺序（v1.2.2 重排）：
    # 1. STYLE + SHOT（受保护，短）
    # 2. SCENE: <完整场景>（受保护，永不截断）
    # 3. MUST INCLUDE: <角色/道具清单>（受保护）
    # 4. Cover layout（仅封面）
    # 5. IP anchor（受保护，短）
    # 6. Expression（受保护）
    # 7. CONSISTENCY_LOCK（受保护：马尾辫+长袖+无手表 铁律）
    # 8. tail_keep（留白 + 禁文字）

    head_parts: list[str] = [STYLE_BIBLE, shot_text]
    head = ". ".join(b.strip().rstrip(".") for b in head_parts) + "."

    mid_parts: list[str] = []
    if scene:
        mid_parts.append(f"Scene: {scene}")
    if must_items:
        mid_parts.append("Must include in image: " + ", ".join(must_items))
    if cover_layout:
        mid_parts.append(cover_layout)
    mid = (". ".join(p.rstrip(".") for p in mid_parts) + ".") if mid_parts else ""

    anchor_parts: list[str] = []
    if ip_anchor:
        anchor_parts.append("Character appearance: " + ip_anchor)
    if expression and page.page_type == "story":
        anchor_parts.append(f"Expression (MUST match): {expression}")
    # 手部规则：仅当场景含手部动作关键词且有人物时才追加，避免远景凭空生手
    cast_text_lower = cast_text.lower()
    if (cast["mia"] or cast["tommy"] or cast["parents"]) and any(
        kw in cast_text_lower for kw in HANDS_ACTION_KEYWORDS
    ):
        anchor_parts.append(HANDS_RULE)
    anchor = (". ".join(p.rstrip(".") for p in anchor_parts) + ".") if anchor_parts else ""

    # 一致性铁律（v1.2.2：只要有 Mia/Tommy/Parents 任意一个就追加）
    lock = ""
    if cast["mia"] or cast["tommy"] or cast["parents"]:
        lock = CONSISTENCY_LOCK

    # 长度控制：head + mid + anchor + lock + tail ≤ 4000
    # 优先级（高→低）：head(必保) + anchor(必保，含 Custom IP 与 HAIR RULE) + lock(必保) + tail(必保) > mid(可压缩)
    # anchor 永远保留（Custom_Anna 等 IP 描述是身份核心），不够空间就截 mid。
    LIMIT = 4000
    base_len = len(head) + len(anchor) + len(lock) + len(tail_keep) + 4
    budget_for_mid = LIMIT - base_len
    if budget_for_mid < 0:
        # anchor + lock + tail 单独都超 4000，先截 anchor 的尾巴（保留前面 Custom_Anna）
        over = -budget_for_mid
        if len(anchor) > over + 3:
            anchor = anchor[: max(0, len(anchor) - over - 3)].rstrip() + "..."
        mid = ""
    elif len(mid) > budget_for_mid:
        mid = mid[: max(0, budget_for_mid - 3)].rstrip() + "..."

    prompt = " ".join(part for part in (head, mid, anchor, lock, tail_keep) if part).strip()

    # 参考图收集（registry 角色 + custom 角色 + Mia/Tommy + 配角）
    scene_text_for_refs = f"{page.text or ''} {page.scene or ''}"
    secondary_refs = _detect_secondary_refs(scene_text_for_refs)
    custom_names_in_scene = [name for name, _ in custom_in_scene]
    registry_refs = [r["ref_path"] for r in registry_in_scene if r["ref_path"]]
    references = _collect_references_v2(
        cast, ip_age, secondary_refs,
        custom_names=custom_names_in_scene,
        registry_refs=registry_refs,
    )
    return BuiltPrompt(prompt=prompt, references=references)


_EMOTION_KEYWORDS: list[tuple[str, str]] = [
    ("excit",  "excited bright eyes, open joyful smile"),
    ("amaz",   "amazed wide eyes, open mouth in wonder"),
    ("surpr",  "surprised wide eyes, raised brows, open mouth"),
    ("worry",  "worried furrowed brows, tight mouth, anxious eyes"),
    ("scared", "scared wide eyes, slight frown"),
    ("happy",  "happy bright smile"),
    ("sad",    "sad downturned mouth, soft eyes"),
    ("curio",  "curious tilted head, soft interested smile"),
    ("relie",  "relieved gentle smile, soft eyes"),
    ("grate",  "grateful soft smile, warm eyes"),
    ("farewell", "warm bittersweet farewell smile, soft eyes"),
    ("unfor",  "warm fond smile, slightly wistful eyes"),
]


def _infer_expression(text: str) -> str:
    t = (text or "").lower()
    found: list[str] = []
    for key, phrase in _EMOTION_KEYWORDS:
        if key in t and phrase not in found:
            found.append(phrase)
    return "; ".join(found[:2])


def _select_character_bible(ip_age: int) -> Path | None:
    """按年龄优先取人物设定大表。优先净版（_clean）。"""
    candidates = [
        CHARACTERS_DIR / f"character_bible_l{_age_bracket(ip_age)}_clean.png",
        CHARACTERS_DIR / "character_bible_l4-6_clean.png",
        CHARACTERS_DIR / f"character_bible_l{_age_bracket(ip_age)}.png",
        CHARACTERS_DIR / "character_bible_l4-6.png",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _age_bracket(ip_age: int) -> str:
    if ip_age <= 8:
        return "0-3"
    if ip_age <= 10:
        return "4-5"
    return "6"


SECONDARY_CHAR_REFS: list[tuple[str, str]] = [
    (r"\bkilt\b",       "kilt_men_reference.png"),
    (r"\bscotsman\b",   "kilt_men_reference.png"),
    (r"\bscotsmen\b",   "kilt_men_reference.png"),
    (r"\bbagpip\w*\b",  "kilt_men_reference.png"),
    (r"\bsheep\b",      "sheep_reference.png"),
    (r"\bshepherd\b",   "shepherd_reference.png"),
]


def _detect_secondary_refs(scene_text: str) -> list[Path]:
    t = (scene_text or "").lower()
    refs: list[Path] = []
    seen_files: set[str] = set()
    for pattern, filename in SECONDARY_CHAR_REFS:
        if _re.search(pattern, t) and filename not in seen_files:
            p = CHARACTERS_DIR / filename
            if p.exists():
                refs.append(p)
                seen_files.add(filename)
    return refs


def _collect_references_v2(
    cast: dict[str, bool],
    ip_age: int,
    secondary_refs: list[Path],
    custom_names: list[str] | None = None,
    registry_refs: list[Path] | None = None,
) -> list[Path]:
    """参考图优先级（受 4 张上限约束，v1.4：registry 角色升至最高优先级）：
    0. registry 角色专属图（含 Anna / Teacher Kim / Winnie 等）—— 本书的主角
    1. <custom_name>_age{N}.png           —— 旧版手工注册的自定义角色
    2. mia_age{N}.png / tommy_age{N}.png  —— 经典 IP 单角色设定
    3. character_bible（净版优先）        —— 多角色合体设定图（兜底）
    4. parents_reference                  —— 父母 IP
    5. secondary refs                     —— 苏格兰人/羊 等次要角色
    6. clean_watercolor                   —— 风格兜底
    """
    refs: list[Path] = []

    # v1.4: registry 已知角色（如 Anna 主角）最高优先级
    for p in registry_refs or []:
        if p and p.exists():
            refs.append(p)

    # 向后兼容：旧版手工 custom_characters 注册的
    for name in custom_names or []:
        p = CHARACTERS_DIR / f"{name}_age{ip_age}.png"
        if p.exists():
            refs.append(p)

    mia_individual_ok = False
    tommy_individual_ok = False
    if cast["mia"]:
        p = CHARACTERS_DIR / f"mia_age{ip_age}.png"
        if p.exists():
            refs.append(p)
            mia_individual_ok = True
    if cast["tommy"]:
        p = CHARACTERS_DIR / f"tommy_age{ip_age}.png"
        if p.exists():
            refs.append(p)
            tommy_individual_ok = True

    # 优化：当本页需要的 Mia/Tommy 都已有专属年龄图时，跳过 bible 兜底
    # （character_bible 包含多视角，部分视角发型/服装与专属图不一致，会污染模型）
    needs_bible = (cast["mia"] and not mia_individual_ok) or (cast["tommy"] and not tommy_individual_ok)
    if needs_bible:
        bible = _select_character_bible(ip_age)
        if bible:
            refs.append(bible)

    if cast["parents"]:
        p = CHARACTERS_DIR / "parents_reference.png"
        if p.exists():
            refs.append(p)

    refs.extend(secondary_refs)

    style_clean = STYLE_DIR / "clean_watercolor_reference.png"
    if style_clean.exists():
        refs.append(style_clean)

    seen = set()
    out: list[Path] = []
    for r in refs:
        k = str(r.resolve())
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out[:4]


# 兼容旧调用名
def _collect_references(
    cast: dict[str, bool], ip_age: int, scene_text: str = ""
) -> list[Path]:
    return _collect_references_v2(cast, ip_age, _detect_secondary_refs(scene_text))
