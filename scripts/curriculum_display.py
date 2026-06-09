"""网页课程地图 / 指标展示 — 与 build_curriculum_xlsx.DATA 完全同源。

VIPKID Dino 0–6 线下绘本：级别配色 = 练习册同款；维度 = 教研 Excel 对标总表。
"""
from __future__ import annotations

import io
from pathlib import Path

from build_curriculum_xlsx import (
    DATA,
    HEADER_AGE,
    HEADER_GRADE,
    LEVEL_KEYS,
    LEVELS,
    SUGGEST,
)
from config import LEVEL_LEXILE, brand_color_hex, resolve_ip_age, rr_question_distribution

_ROOT = Path(__file__).resolve().parent.parent
_BAR_HEIGHTS = (32, 42, 53, 66, 80, 95, 110)


def mini_map_rows() -> list[tuple]:
    """迷你梯度图一行数据（与 Excel 同源）。

    (level_key, 阅读阶段, 年龄, 年级, CEFR, RAZ, 剑桥YLE, 核心目标, bar_h)
    """
    stage = DATA["① 阶段与培养目标"]["阅读阶段"]
    cefr = DATA["② 对标基准"]["欧标 CEFR"]
    raz = DATA["② 对标基准"]["RAZ 阅读体系"]
    yle = DATA["② 对标基准"]["剑桥少儿 (YLE)"]
    goal = DATA["④ 学习重点与考察"]["核心目标"]
    rows = []
    for i, k in enumerate(LEVEL_KEYS):
        rows.append((
            k, stage[i], HEADER_AGE[i], HEADER_GRADE[i],
            cefr[i], raz[i], yle[i], goal[i], _BAR_HEIGHTS[i],
        ))
    return rows


def level_metrics_rows() -> list[dict]:
    """指标页主表 — 汇总对标 + 绘本生成相关字段。"""
    try:
        from ai_extractor import _STORY_WORD_TARGETS
    except Exception:
        _STORY_WORD_TARGETS = {}

    d = DATA["② 对标基准"]
    stage = DATA["① 阶段与培养目标"]["阅读阶段"]
    lang_dev = DATA["① 阶段与培养目标"]["语言发展"]
    goal = DATA["④ 学习重点与考察"]["核心目标"]
    direction = DATA["④ 学习重点与考察"]["考察方向"]
    strategy = DATA["④ 学习重点与考察"]["阅读策略"]
    per_book = d["单本正文字数"]
    cum_words = d["累计阅读字数"]
    cum_vocab = d["词汇量 (累计)"]
    lexile_official = d["蓝思 Lexile"]

    rows = []
    for i, k in enumerate(LEVEL_KEYS):
        rr_n = len(rr_question_distribution(k))
        rows.append({
            "级别": LEVELS[i],
            "阅读阶段": stage[i],
            "语言发展": lang_dev[i],
            "学生年龄": HEADER_AGE[i],
            "国内年级": HEADER_GRADE[i],
            "CEFR": d["欧标 CEFR"][i],
            "蓝思 Lexile": lexile_official[i],
            "RAZ": d["RAZ 阅读体系"][i],
            "AR": d["AR 值 (ATOS)"][i],
            "剑桥少儿": d["剑桥少儿 (YLE)"][i],
            "累计阅读字数": cum_words[i],
            "单本正文字数": per_book[i],
            "累计词汇量": cum_vocab[i],
            "IP参考年龄": f"{resolve_ip_age(k)}岁",
            "AI故事字数": _STORY_WORD_TARGETS.get(k, "—"),
            "RR表达题": f"{rr_n}题",
            "词表格式": "双行 M+E" if k in ("0", "1", "2") else "单行4词",
            "考察方向": direction[i],
            "阅读策略": strategy[i],
            "核心目标": goal[i],
        })
    return rows


def curriculum_section_tables() -> list[tuple[str, dict[str, list[str]]]]:
    """按 Excel 分段返回维度表（供指标页展开）。"""
    return list(DATA.items())


def _cjk_font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    win = Path("C:/Windows/Fonts")
    candidates = [
        win / ("msyhbd.ttc" if bold else "msyh.ttc"),
        win / ("simhei.ttf" if bold else "simsun.ttc"),
        _ROOT / "assets/fonts/Poppins/Poppins-Bold.ttf" if bold else _ROOT / "assets/fonts/Poppins/Poppins-Regular.ttf",
    ]
    for p in candidates:
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                continue
    return ImageFont.load_default()


def mini_map_png_bytes() -> bytes:
    """竖版迷你梯度图 PNG（中文可渲染；无外部文件依赖）。"""
    from PIL import Image, ImageDraw

    rows = mini_map_rows()
    w, h = 1280, 480
    img = Image.new("RGB", (w, h), "#fff8f3")
    draw = ImageDraw.Draw(img)
    font = _cjk_font(13)
    font_b = _cjk_font(15, bold=True)
    font_s = _cjk_font(11)
    font_xs = _cjk_font(10)

    draw.text((24, 14), "VIPKID Dino · 0–6 课程地图", fill="#1f2937", font=font_b)
    draw.text((24, 36), "北美外教阅读体系 · 与教研对标总表同源", fill="#9aa1ab", font=font_s)

    col_w = (w - 48) // len(rows)
    x0 = 24
    y_top = 58
    for i, (key, stage, age, grade, cefr, raz, _yle, goal, bar_h) in enumerate(rows):
        color = brand_color_hex(key)
        x = x0 + i * col_w
        draw.rounded_rectangle(
            [x + 6, y_top, x + col_w - 6, y_top + 18],
            radius=8, fill=color, outline=color,
        )
        tw = draw.textlength(stage[:4], font=font_xs)
        draw.text((x + (col_w - tw) / 2 - 6, y_top + 3), stage[:4], fill="#ffffff", font=font_xs)
        bh = min(bar_h * 2, 200)
        y_base = h - 78
        draw.rounded_rectangle(
            [x + 10, y_base - bh, x + col_w - 10, y_base],
            radius=6, fill=color,
        )
        lv = f"L{key}"
        tw = draw.textlength(lv, font=font_b)
        draw.text((x + (col_w - tw) / 2 - 6, y_base - bh + 10), lv, fill="#ffffff", font=font_b)
        draw.text((x + 10, y_base + 6), cefr, fill=color, font=font_s)
        draw.text((x + 10, y_base + 22), f"RAZ {raz}", fill="#6b7280", font=font_s)
        goal_short = goal.replace(" · ", "·")[:10]
        draw.text((x + 8, y_top + 24), goal_short, fill="#374151", font=font_s)
        draw.text((x + 8, y_top + 40), age, fill="#9aa1ab", font=font_xs)

    draw.text(
        (24, h - 28),
        "颜色=练习册级别色 · 权威值来自官方 S&S · 带「参考」维度见 Excel 说明",
        fill="#9aa1ab", font=font_xs,
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_mini_map_html(logo_html: str = "") -> str:
    """内联 HTML 迷你梯度图（概览页常驻）。"""
    d = DATA["② 对标基准"]
    lang = DATA["① 阶段与培养目标"]["语言发展"]
    cum = d["累计阅读字数"]
    cells = []
    for i, (key, stage, age, grade, cefr, raz, yle, goal, bar_h) in enumerate(mini_map_rows()):
        color = brand_color_hex(key)
        cells.append(
            f"<div class='cm-col'>"
            f"<div class='cm-stage' style='color:{color};border-color:{color}55'>{stage}</div>"
            f"<div class='cm-lang'>{lang[i]}</div>"
            f"<div class='cm-goal'>{goal}</div>"
            f"<div class='cm-bar' style='height:{bar_h}px;background:linear-gradient(180deg,{color},{color}cc)'>"
            f"<span class='cm-lv'>L{key}</span></div>"
            f"<div class='cm-cefr' style='color:{color}'>{cefr}</div>"
            f"<div class='cm-raz'>RAZ {raz}</div>"
            f"<div class='cm-exam'>{yle}</div>"
            f"<div class='cm-cum'>累计约 {cum[i]} 词</div>"
            f"<div class='cm-age'>{age} · {grade}</div>"
            f"</div>"
        )
    bands = (
        ("夯实基础", 3, "#fff5ef"),
        ("进阶提升", 2, "#f0f9ff"),
        ("流利阅读", 1, "#fdf2f8"),
        ("自主阅读", 1, "#eff6ff"),
    )
    band_html = "".join(
        f"<div class='cm-band' style='flex:{n};background:{bg}'>{label}</div>"
        for label, n, bg in bands
    )
    return f"""
    <style>
      .cm-wrap{{border:1px solid #f0e3da;border-radius:14px;padding:12px 16px 10px;
        background:linear-gradient(135deg,#fff,#fff8f3);margin:2px 0 8px;}}
      .cm-head{{display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap;}}
      .cm-head .t{{font-weight:800;font-size:16px;color:#1f2937;}}
      .cm-head .s{{font-size:12px;color:#9aa1ab;line-height:1.4;}}
      .cm-bands{{display:flex;gap:4px;margin-bottom:8px;border-radius:8px;overflow:hidden;}}
      .cm-band{{text-align:center;font-size:11px;font-weight:700;color:#6b7280;padding:4px 0;}}
      .cm-row{{display:flex;align-items:flex-end;gap:8px;}}
      .cm-col{{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;min-width:0;}}
      .cm-stage{{font-size:10px;font-weight:800;border:1px solid;border-radius:999px;
        padding:1px 6px;margin-bottom:3px;white-space:nowrap;background:#fff;max-width:100%;overflow:hidden;text-overflow:ellipsis;}}
      .cm-lang{{font-size:9.5px;color:#9aa1ab;margin-bottom:3px;}}
      .cm-goal{{font-size:11px;font-weight:700;color:#374151;margin-bottom:5px;height:15px;
        white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;text-align:center;}}
      .cm-bar{{width:100%;border-radius:9px 9px 4px 4px;display:flex;align-items:flex-start;
        justify-content:center;padding-top:6px;box-shadow:0 3px 8px rgba(0,0,0,.08);}}
      .cm-lv{{color:#fff;font-weight:900;font-size:15px;letter-spacing:.5px;text-shadow:0 1px 2px rgba(0,0,0,.2);}}
      .cm-cefr{{font-size:11px;font-weight:800;margin-top:5px;}}
      .cm-raz{{font-size:9.5px;color:#6b7280;font-weight:700;margin-top:1px;}}
      .cm-exam{{font-size:9.5px;color:#6b7280;font-weight:600;text-align:center;}}
      .cm-cum{{font-size:9px;color:#9aa1ab;margin-top:2px;}}
      .cm-age{{font-size:9.5px;color:#9aa1ab;margin-top:1px;text-align:center;}}
      .cm-foot{{font-size:11px;color:#9aa1ab;margin-top:10px;text-align:center;line-height:1.5;}}
    </style>
    <div class='cm-wrap'>
      <div class='cm-head'>{logo_html}
        <span class='t'>0–6 课程地图</span>
        <span class='s'>北美外教阅读能力达成 · 阅读阶段 / 欧标 / RAZ / 剑桥 / 累计阅读量 / 核心目标
        （详细维度见「指标」页或下载 Excel）</span>
      </div>
      <div class='cm-bands'>{band_html}</div>
      <div class='cm-row'>{"".join(cells)}</div>
      <div class='cm-foot'>级别配色 = 练习册同款 · 与《课程对标总表_L0-L6.xlsx》100% 同源 ·
      不含 IELTS/TOEFL-iBT（超出 0–6 绘本体系）</div>
    </div>
    """


def section_to_rows(section: dict[str, list[str]]) -> list[dict]:
    """把一个 Excel 分段转成 dataframe 行（维度 × L0–L6）。"""
    rows = []
    for dim, vals in section.items():
        tag = " ᴿ" if dim in SUGGEST else ""
        row: dict = {"维度": dim + tag}
        for i, lv in enumerate(LEVELS):
            row[lv] = vals[i] if i < len(vals) else ""
        rows.append(row)
    return rows
