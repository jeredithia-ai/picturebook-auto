"""Streamlit 单页 Web App：从老师输入到 4 件套 ZIP 下载。

启动：
    cd picturebook-auto
    streamlit run scripts/web_app.py

流程：
    1. 表单：Title / Level / Book# / Theme / 7 句故事原文 / IP 年龄
    2. AI 抽取（Claude 文本）→ 可编辑预览：词表/分页/语法/拼读/RR 题/Worksheet 题
    3. 一键 Generate All → Picture Book PPT + 7 张图 + Worksheet PPTX + RR DOCX + TG DOCX
    4. 全部打包 ZIP，供老师下载
"""
from __future__ import annotations

import contextlib
import io
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

# 让 streamlit run 也能找到同级模块
sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st

from ai_extractor import (
    QUESTION_INSTRUCTIONS, QUESTION_POOL, QUESTION_TITLES,
    apply_extracted_to_outline, extract_all, generate_one_worksheet_question,
)
from auto_fill import auto_summary
from config import (
    DOUBAO_API_KEY, JIMENG_API_KEY, MOCK_AI_EXTRACT, MOCK_IMAGES,
    OUTPUTS_DIR, brand_color_hex, resolve_ip_age, rr_question_distribution,
    COMPOSITION_POLICY,
)
from cn_prompt_builder import build_cn_page_prompt, page_display_name
from parser import BookOutline, PageSpec
from ppt_builder import build_picturebook_pptx, safe_filename
from prompt_builder import build_page_prompt  # legacy: fallback only
from reading_report_builder import attach_rr_questions, build_reading_report
from seedream_client import generate_image
from teacher_guide_builder import build_teacher_guide
from worksheet_builder import attach_worksheet_questions, build_worksheet


LEVEL_OPTIONS = ["Smart", "1", "2", "3", "4", "5", "6"]
SHOT_OPTIONS = ["close", "medium", "full", "wide"]


# =============================== v2.0 严格解锁框架 ===============================
#
# 绘本组装 7 步工作流（每步必须点 ✓ 确认才能进入下一步）：
#   1 📚 输入 + AI 抽取
#   2 🎭 人物 IP 锁定
#   3 🎨 风格背景设定
#   4 📖 分页事件编辑
#   5 📝 提示词预览
#   6 🖼️ 单页生图（Phase 2 升级为 3 候选）
#   7 📦 组装 PPT
# ============================================================================

BOOK_STEPS = [
    (1, "📚 输入 + AI 抽取"),
    (2, "📐 底层逻辑（只读）"),
    (3, "🎭 IP + 🎨 画风锁定"),
    (4, "🖼️ 生图工作台"),
    (5, "📦 组装 4 件套"),
]


def _step_status(step_num: int) -> str:
    """返回步骤状态：'done' / 'active' / 'locked'。"""
    unlocked = st.session_state.get("book_unlocked_step", 1)
    if step_num < unlocked:
        return "done"
    if step_num == unlocked:
        return "active"
    return "locked"


def _step_icon(status: str) -> str:
    return {"done": "✅", "active": "⏳", "locked": "🔒"}[status]


def _render_progress_bar() -> None:
    """渲染 7 步进度条（顶部）。"""
    cols = st.columns(len(BOOK_STEPS))
    for i, (num, title) in enumerate(BOOK_STEPS):
        status = _step_status(num)
        icon = _step_icon(status)
        color = {"done": "#10b981", "active": "#f59e0b", "locked": "#9ca3af"}[status]
        bg = {"done": "#d1fae5", "active": "#fef3c7", "locked": "#f3f4f6"}[status]
        cols[i].markdown(
            f"<div style='text-align:center;padding:0.5rem 0.2rem;"
            f"background:{bg};border-radius:8px;border:2px solid {color};'>"
            f"<div style='font-size:1.2rem'>{icon}</div>"
            f"<div style='font-size:0.7rem;color:{color};font-weight:600;'>"
            f"Step {num}</div>"
            f"<div style='font-size:0.65rem;color:#6b7280;'>{title}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )


def _locked_step_expander(step_num: int, title: str, default_expanded: bool = True):
    """带状态徽章 + 锁定逻辑的 expander 上下文管理器替身。

    locked → 渲染灰色不可点提示，返回 None（调用方应跳过内容）。
    done/active → 返回 expander 上下文（with ... as exp:）。
    """
    status = _step_status(step_num)
    icon = _step_icon(status)

    if status == "locked":
        st.markdown(
            f"<div style='padding:0.7rem 1rem;background:#f9fafb;border-radius:8px;"
            f"color:#9ca3af;margin:0.4rem 0;border:1px dashed #d1d5db;'>"
            f"{icon} <b>Step {step_num}：{title}</b> &nbsp;&nbsp;"
            f"<span style='font-size:0.85rem'>（请先完成上一步并点 ✅ 确认才能解锁）</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        return None

    expanded = (status == "active") and default_expanded
    label_color = {"done": "#10b981", "active": "#f59e0b"}[status]
    return st.expander(f"{icon} **Step {step_num}：{title}**", expanded=expanded)


def _confirm_next_step(step_num: int, label: str = "", help_text: str = "") -> None:
    """在某步底部渲染 ✓ 确认按钮，点击后解锁下一步。"""
    if _step_status(step_num) != "active":
        return
    st.markdown("&nbsp;", unsafe_allow_html=True)
    cols = st.columns([3, 1])
    cols[0].caption(help_text or "👉 确认无误后，点击右侧按钮解锁下一步")
    if cols[1].button(
        label or f"✅ 确认 Step {step_num} 并进入下一步",
        type="primary",
        key=f"confirm_step_{step_num}",
        width="stretch",
    ):
        cur = st.session_state.get("book_unlocked_step", 1)
        st.session_state["book_unlocked_step"] = max(cur, step_num + 1)
        st.rerun()


def _reset_workflow_button() -> None:
    """顶部重置按钮 — 回到 Step 1。"""
    if st.button("🔄 重置工作流（回到 Step 1）", key="reset_workflow"):
        st.session_state["book_unlocked_step"] = 1
        st.rerun()


# ============================================================================
# Step 3：🎨 风格背景设定（6 字段）
# ============================================================================

VISUAL_STYLE_OPTIONS = [
    "温暖水彩童书风（推荐 L0-L4）",
    "细腻插画书风（推荐 L5-L6）",
    "扁平卡通风",
    "写实插画风",
    "黑白线稿风",
]

MAIN_SCENE_OPTIONS = [
    "🤖 由故事自动推断",
    "学校教室",
    "家中客厅 / 卧室",
    "户外公园 / 操场",
    "旅行风景",
    "森林 / 动物世界",
    "海边 / 海洋",
    "城市街道",
    "魔法 / 童话场景",
]

COLOR_TONE_OPTIONS = [
    "温暖明亮（暖黄+橘粉，适合家/朋友主题）",
    "清新柔和（淡蓝+薄荷绿，适合学校/成长）",
    "低饱和柔和（米白+灰粉，文艺感）",
    "鲜艳活泼（高饱和，适合冒险/动物）",
    "冷调宁静（蓝紫+雪白，适合夜晚/思考）",
]

COMPOSITION_OPTIONS = [
    "人物为主 50-60%（人物特写）",
    "人物中等 30-40%（推荐 — 留白配文字）",
    "环境为主 20-30%（远景叙事）",
]

LIGHT_SOURCE_OPTIONS = [
    "柔和自然光（推荐）",
    "温暖阳光（侧光，暖色调）",
    "逆光剪影（情绪感）",
    "室内灯光（暖黄）",
    "黄昏 / 黎明（梦幻）",
]

# v3.2 B 层：视角 + 焦点（全局默认，可调）
VIEW_ANGLE_OPTIONS = [
    "平视（推荐 — 与儿童视线齐平，最自然）",
    "微俯视（成人视角看儿童，温柔感）",
    "微仰视（儿童视角看世界，开阔感）",
    "侧面视角（叙事感，多用于互动场景）",
    "🤖 由 AI 按每页内容自动选",
]

FOCUS_HANDLING_OPTIONS = [
    "主体清晰 + 背景轻度虚化（推荐 — 突出主角）",
    "全画面清晰（信息密集型，多元素并存）",
    "主体清晰 + 背景大幅虚化（特写情绪，少元素）",
]

# v3.2 A 层：每页可调的人物状态字段
POSE_OPTIONS = [
    "🤖 由 AI 按故事推断", "站立", "坐着", "蹲下", "趴着",
    "走动", "奔跑", "拥抱", "对话中", "思考中", "举手",
    "手指指向", "回头", "弯腰", "趴在桌上",
]
EMOTION_OPTIONS = [
    "🤖 由 AI 按故事推断", "开心微笑", "紧张不安", "认真专注",
    "惊讶张嘴", "平静放松", "略带难过", "兴奋大笑",
    "好奇凝视", "害羞低头", "自豪挺胸",
]
GAZE_OPTIONS = [
    "🤖 自动", "看镜头（与读者眼神交流）", "看向对话角色",
    "看向手中物品", "看向远方", "看向另一角色背影",
    "低头看地面",
]
POSITION_OPTIONS = [
    "🤖 自动", "画面正中（焦点）", "左前景", "右前景",
    "左中景", "右中景", "中远景", "左侧远景", "右侧远景",
]
INTERACTION_OPTIONS = [
    "🤖 自动", "面对面对话", "并肩同行 / 同伴",
    "一方主动一方被动", "陌生人擦肩", "正在合作做事",
    "对立 / 争执", "围观 / 围聚",
]
TEXT_SAFE_POSITION = [
    "🤖 自动（跟全局留白）", "顶部留白（文字放上方）",
    "底部留白（文字放下方）", "左侧留白", "右侧留白",
    "无文字 / 不留",
]

_DEFAULT_GLOBAL_AVOID = (
    "丑陋 / 畸形\n"
    "多手指 / 错位关节\n"
    "字幕 / 水印 / logo\n"
    "暴力 / 血腥 / 恐怖\n"
    "成人化妆容\n"
    "低分辨率 / 模糊"
)


def _render_style_panel_step(step_num: int, embed: bool = False) -> None:
    """Step 3：风格背景设定（6 字段）。embed=True 时内联渲染（无 expander/confirm）。"""
    if embed:
        exp = contextlib.nullcontext()
    else:
        exp = _locked_step_expander(step_num, "🎨 风格背景设定（全局应用到所有 7 页）")
        if exp is None:
            return

    with exp:
        st.caption(
            "🤖 **默认全自动**：视觉风格 / 主场景 / 色调 / 构图 / 视角 等都由 AI 按本页故事自动决定，"
            "并自动注入每页提示词。一般**不用动**；只在需要时补下面的「必出现元素」，或展开「高级覆盖」微调。"
        )

        defaults = st.session_state.get("style_config", {})

        # 默认全自动取值（不展开高级覆盖时直接用这些默认）
        visual_style = defaults.get("visual_style", VISUAL_STYLE_OPTIONS[0])
        main_scene = defaults.get("main_scene", MAIN_SCENE_OPTIONS[0])
        color_tone = defaults.get("color_tone", COLOR_TONE_OPTIONS[0])
        composition = defaults.get("composition", COMPOSITION_OPTIONS[1])
        light_source = defaults.get("light_source", LIGHT_SOURCE_OPTIONS[0])
        text_safe_zone = defaults.get("text_safe_zone", True)
        view_angle = defaults.get("view_angle", VIEW_ANGLE_OPTIONS[0])
        focus_handling = defaults.get("focus_handling", FOCUS_HANDLING_OPTIONS[0])

        # 高级覆盖用复选框开关（不能用嵌套 expander）
        if st.checkbox("⚙️ 显示高级覆盖（默认全自动，一般不用动）", value=False, key="cfg_show_adv"):
            col1, col2, col3 = st.columns(3)
            with col1:
                visual_style = st.selectbox(
                    "① 视觉风格",
                    VISUAL_STYLE_OPTIONS,
                    index=VISUAL_STYLE_OPTIONS.index(defaults.get("visual_style", VISUAL_STYLE_OPTIONS[0]))
                    if defaults.get("visual_style") in VISUAL_STYLE_OPTIONS else 0,
                    key="cfg_visual",
                    help="决定全本水彩童书画风的关键关键词",
                )
            with col2:
                main_scene = st.selectbox(
                    "② 主场景",
                    MAIN_SCENE_OPTIONS,
                    index=MAIN_SCENE_OPTIONS.index(defaults.get("main_scene", MAIN_SCENE_OPTIONS[0]))
                    if defaults.get("main_scene") in MAIN_SCENE_OPTIONS else 0,
                    key="cfg_scene",
                    help="选 🤖 自动 → AI 按每页文本逐页推断；选具体场景 → 强制锁定",
                )
            with col3:
                color_tone = st.selectbox(
                    "③ 色调",
                    COLOR_TONE_OPTIONS,
                    index=COLOR_TONE_OPTIONS.index(defaults.get("color_tone", COLOR_TONE_OPTIONS[0]))
                    if defaults.get("color_tone") in COLOR_TONE_OPTIONS else 0,
                    key="cfg_tone",
                )

            col4, col5, col6 = st.columns(3)
            with col4:
                composition = st.selectbox(
                    "④ 构图（人物占比）",
                    COMPOSITION_OPTIONS,
                    index=1,  # 默认推荐
                    key="cfg_comp",
                )
            with col5:
                light_source = st.selectbox(
                    "⑤ 光源",
                    LIGHT_SOURCE_OPTIONS,
                    index=LIGHT_SOURCE_OPTIONS.index(defaults.get("light_source", LIGHT_SOURCE_OPTIONS[0]))
                    if defaults.get("light_source") in LIGHT_SOURCE_OPTIONS else 0,
                    key="cfg_light",
                )
            with col6:
                text_safe_zone = st.checkbox(
                    "⚠️ 顶/底 25% 留白给文字",
                    value=defaults.get("text_safe_zone", True),
                    key="cfg_textsafe",
                    help="开启后，提示词会强制顶部和底部留白，避免文字遮住主体",
                )

            # v3.2 B 层：视角 + 焦点
            col7, col8 = st.columns(2)
            with col7:
                view_angle = st.selectbox(
                    "⑦ 视角（B 层 · 镜头角度）",
                    VIEW_ANGLE_OPTIONS,
                    index=VIEW_ANGLE_OPTIONS.index(defaults.get("view_angle", VIEW_ANGLE_OPTIONS[0]))
                    if defaults.get("view_angle") in VIEW_ANGLE_OPTIONS else 0,
                    key="cfg_view_angle",
                    help="推荐用平视，与儿童视线齐平最自然。AI 自动模式 = Claude 按每页内容选",
                )
            with col8:
                focus_handling = st.selectbox(
                    "⑧ 焦点处理（B 层 · 景深）",
                    FOCUS_HANDLING_OPTIONS,
                    index=FOCUS_HANDLING_OPTIONS.index(defaults.get("focus_handling", FOCUS_HANDLING_OPTIONS[0]))
                    if defaults.get("focus_handling") in FOCUS_HANDLING_OPTIONS else 0,
                    key="cfg_focus",
                    help="主体清晰 + 背景虚化 → 突出主角；全清晰 → 适合信息密集页面",
                )

        st.markdown("---")
        col7, col8 = st.columns(2)
        with col7:
            global_must = st.text_area(
                "📌 全局必出现元素（每行一个，会追加到每页正向提示词）",
                value=defaults.get("global_must", ""),
                height=120,
                key="cfg_must",
                placeholder="例如：\nAnna 戴琥珀色细框眼镜\nMia 始终扎双低马尾\n所有场景必有教室元素",
            )
        with col8:
            global_avoid = st.text_area(
                "🚫 全局必避免元素（每行一个，会追加到每页反向提示词）",
                value=defaults.get("global_avoid", _DEFAULT_GLOBAL_AVOID),
                height=120,
                key="cfg_avoid",
            )

        new_cfg = {
            "visual_style": visual_style,
            "main_scene": main_scene,
            "color_tone": color_tone,
            "composition": composition,
            "light_source": light_source,
            "text_safe_zone": text_safe_zone,
            "global_must": global_must,
            "global_avoid": global_avoid,
            # v3.2 B 层新增
            "view_angle": view_angle,
            "focus_handling": focus_handling,
        }
        st.session_state["style_config"] = new_cfg

        # 实时预览：把当前 6 字段拼成一段中文 style block，给老师看效果
        style_preview = _format_style_config_preview(new_cfg)
        with st.expander("🔍 实时风格设定预览（会注入到每页提示词）", expanded=False):
            st.markdown(f"**全局正向（追加到每页正向末尾）：**")
            st.code(style_preview["positive_block"], language="text")
            st.markdown(f"**全局反向（追加到每页反向末尾）：**")
            st.code(style_preview["negative_block"], language="text")

        if not embed:
            _confirm_next_step(
                step_num,
                label="✅ 确认风格设定，进入分页编辑",
                help_text="👉 风格设定一旦确认，会自动注入到 7 页的提示词。后续仍可回到本步重设。",
            )


# ============================================================================
# Step 2：🎭 人物 IP 锁定（包住已有的 auto_summary_panel）
# ============================================================================

def _render_step2_ip_lock(step_num: int, embed: bool = False) -> None:
    if embed:
        exp = contextlib.nullcontext()
    else:
        exp = _locked_step_expander(step_num, "🎭 人物 IP 锁定（确认故事里的角色形象）")
        if exp is None:
            return
    with exp:
        st.caption(
            "💡 系统已从故事里识别到的角色 + 让你**勾选 IP 库**里的形象做参考图。"
            "如果故事里出现 \"a girl\" / \"a boy\" 这类未命名角色，可以在下方"
            "把它们映射到具体 IP（如 Mia / Tommy / Anna）。"
        )
        if st.session_state.get("auto") is not None:
            _render_auto_summary_panel()
        else:
            st.info("ℹ️ Step 1 抽取完成后会显示主角识别面板。")

        if not embed:
            _confirm_next_step(
                step_num,
                label="✅ 确认人物 IP，进入风格设定",
                help_text="👉 IP 一旦确认，生图时会自动加载对应的参考图（多角色场景最多 3 张）",
            )


# ============================================================================
# Step 4（合并 4+5）：📖 分页事件 + 提示词（事实和 prompt 同页编辑，实时联动）
# ============================================================================

def _render_step4_combined(step_num: int, embed: bool = False) -> None:
    """合并版：每页一张大卡片，左列编辑事实 / 右列实时显示 prompt + DeepSeek 按钮。"""
    if embed:
        exp = contextlib.nullcontext()
    else:
        exp = _locked_step_expander(
            step_num, "📖 分页事件 + 提示词（左编事实 / 右看 prompt / Claude 智能润色）"
        )
        if exp is None:
            return
    with exp:
        st.caption(
            "💡 一张卡片 = 一页绘本。"
            "**左列**编辑故事/画面事实，**右列**实时显示 prompt（点 🔄 重建按钮同步）。"
            "**🩺 Claude 润色** 把当前 prompt 喂给 Claude 优化（需配置 IMAROUTER_API_KEY）。"
        )

        # 检查 DeepSeek 可用性
        try:
            from scene_cn_writer import is_available as ds_available
            deepseek_ok = ds_available()
        except Exception:
            deepseek_ok = False

        if not deepseek_ok:
            st.warning(
                "⚠️ 文本模型未配置。🤖 写 scene_cn / 🩺 润色按钮将不可用。"
                "请在 .env 设置 `IMAROUTER_API_KEY`（文本默认走 `claude-opus-4-7`）。"
            )

        # 全局重建按钮
        col_rebuild, col_ds_all = st.columns([1, 1])
        with col_rebuild:
            if st.button(
                "🔄 基于最新事实/风格重建全部 prompt",
                type="secondary",
                key="s4_rebuild_all",
                width="stretch",
                help="把 Step 3 风格设定 + 当前分页事实 重新组装成提示词（覆盖已编辑的 prompt）",
            ):
                _rebuild_all_cn_prompts()
                st.success("✅ 已重建全部 prompt")
                st.rerun()
        with col_ds_all:
            if st.button(
                "🤖 用 Claude 重写全部 scene_cn（强烈推荐）",
                type="secondary",
                key="s4_ds_all_scenes",
                width="stretch",
                disabled=not deepseek_ok,
                help="让 Claude 给 7 页全部写新的 120-220 字中文画面描述",
            ):
                _deepseek_rewrite_all_scenes()
                st.rerun()

        st.divider()

        ec = st.session_state.extracted
        page_prompts = st.session_state.get("page_prompts") or {}
        ec_pages_by_idx = {p.get("index"): p for p in (ec.pages or [])}

        for idx in sorted(page_prompts.keys()):
            entry = page_prompts[idx]
            ec_page = ec_pages_by_idx.get(idx) or {}
            display_name = entry.get("display_name") or page_display_name(idx)
            label_kind = "封面" if idx == 0 else "故事页"
            refs = entry.get("references", [])
            ref_badge = f"🖼️ {len(refs)} 张参考图" if refs else "⚠️ 无参考图"

            st.markdown(f"#### {display_name} · {label_kind} · {ref_badge}")

            # 单页 DeepSeek 操作按钮
            bcol1, bcol2, bcol3 = st.columns([1, 1, 1])
            with bcol1:
                if st.button(
                    "🤖 Claude 写 scene_cn",
                    key=f"s4_ds_scene_{idx}",
                    disabled=not deepseek_ok,
                    width="stretch",
                    help="让 Claude 重写本页 120-220 字中文画面描述",
                ):
                    _deepseek_rewrite_one_scene(idx)
                    st.rerun()
            with bcol2:
                if st.button(
                    "🩺 Claude 润色 prompt",
                    key=f"s4_ds_polish_{idx}",
                    disabled=not deepseek_ok,
                    width="stretch",
                    help="把本页正向 prompt 喂给 Claude 按画面结构最佳实践重写",
                ):
                    _deepseek_polish_one_prompt(idx)
                    st.rerun()
            with bcol3:
                if st.button(
                    "🔄 仅重建本页 prompt（用模板）",
                    key=f"s4_rebuild_one_{idx}",
                    width="stretch",
                    help="只用 cn_prompt_builder 模板重建本页（不调 Claude）",
                ):
                    _rebuild_one_cn_prompt(idx)
                    st.rerun()

            # 双栏布局
            left, right = st.columns([1, 1])

            # === 左列：事实编辑 ===
            with left:
                st.caption("① 故事原文（英文）")
                new_text = st.text_area(
                    f"text_{idx}",
                    value=ec_page.get("text", ""),
                    height=100,
                    key=f"s4_text_{idx}",
                    label_visibility="collapsed",
                )
                if new_text != ec_page.get("text", ""):
                    ec_page["text"] = new_text

                st.caption("② 中文画面描述 scene_cn（120-220 字）")
                new_scene_cn = st.text_area(
                    f"scene_cn_{idx}",
                    value=ec_page.get("scene_cn", ""),
                    height=150,
                    key=f"s4_scene_cn_{idx}",
                    label_visibility="collapsed",
                    placeholder=(
                        "主体（人物+具体外观）+ 动作（具体动词姿势）+ 环境（可见物品）+ 氛围（光照）\n"
                        "👆 点上方 🤖 Claude 写 scene_cn 让它帮你写"
                    ),
                )
                if new_scene_cn != ec_page.get("scene_cn", ""):
                    ec_page["scene_cn"] = new_scene_cn

                fc1, fc2 = st.columns(2)
                with fc1:
                    st.caption("③ 必出现（每行一条）")
                    entry["must_include"] = st.text_area(
                        f"must_inc_{idx}",
                        value=entry.get("must_include", ""),
                        height=110,
                        key=f"s4_must_{idx}",
                        label_visibility="collapsed",
                        placeholder="Anna 戴琥珀色细框眼镜\n桌上 5 本课本",
                    )
                with fc2:
                    st.caption("④ 必避免（每行一条）")
                    entry["page_avoid"] = st.text_area(
                        f"page_avoid_{idx}",
                        value=entry.get("page_avoid", ""),
                        height=110,
                        key=f"s4_avoid_{idx}",
                        label_visibility="collapsed",
                        placeholder="本页不应有宠物\nMia 不能散发",
                    )

                cur_shot = ec_page.get("shot", "medium") or "medium"
                new_shot = st.selectbox(
                    "镜头",
                    SHOT_OPTIONS,
                    index=max(0, SHOT_OPTIONS.index(cur_shot) if cur_shot in SHOT_OPTIONS else 1),
                    key=f"s4_shot_{idx}",
                )
                if new_shot != cur_shot:
                    ec_page["shot"] = new_shot

                # v3.2 A 层：🎭 人物状态字段（每页可调）
                with st.expander("🎭 A 层 · 人物状态（推荐每页都设，强约束）", expanded=False):
                    p_cur = entry.get("page_constraints") or {}

                    cc1, cc2 = st.columns(2)
                    with cc1:
                        pose = st.selectbox(
                            "主角姿势",
                            POSE_OPTIONS,
                            index=POSE_OPTIONS.index(p_cur.get("pose", POSE_OPTIONS[0]))
                            if p_cur.get("pose") in POSE_OPTIONS else 0,
                            key=f"s4a_pose_{idx}",
                        )
                        emotion = st.selectbox(
                            "情绪表达",
                            EMOTION_OPTIONS,
                            index=EMOTION_OPTIONS.index(p_cur.get("emotion", EMOTION_OPTIONS[0]))
                            if p_cur.get("emotion") in EMOTION_OPTIONS else 0,
                            key=f"s4a_emo_{idx}",
                        )
                        gaze = st.selectbox(
                            "视线方向",
                            GAZE_OPTIONS,
                            index=GAZE_OPTIONS.index(p_cur.get("gaze", GAZE_OPTIONS[0]))
                            if p_cur.get("gaze") in GAZE_OPTIONS else 0,
                            key=f"s4a_gaze_{idx}",
                        )
                    with cc2:
                        position = st.selectbox(
                            "画面位置",
                            POSITION_OPTIONS,
                            index=POSITION_OPTIONS.index(p_cur.get("position", POSITION_OPTIONS[0]))
                            if p_cur.get("position") in POSITION_OPTIONS else 0,
                            key=f"s4a_position_{idx}",
                        )
                        interaction = st.selectbox(
                            "互动关系（多角色时）",
                            INTERACTION_OPTIONS,
                            index=INTERACTION_OPTIONS.index(p_cur.get("interaction", INTERACTION_OPTIONS[0]))
                            if p_cur.get("interaction") in INTERACTION_OPTIONS else 0,
                            key=f"s4a_inter_{idx}",
                        )
                        text_pos = st.selectbox(
                            "文字预留位置",
                            TEXT_SAFE_POSITION,
                            index=TEXT_SAFE_POSITION.index(p_cur.get("text_pos", TEXT_SAFE_POSITION[0]))
                            if p_cur.get("text_pos") in TEXT_SAFE_POSITION else 0,
                            key=f"s4a_textpos_{idx}",
                        )
                    focus_char = st.text_input(
                        "焦点角色（输入名字，留空 = AI 自动判断）",
                        value=p_cur.get("focus_char", ""),
                        key=f"s4a_focus_{idx}",
                        placeholder="例：Anna",
                    )
                    entry["page_constraints"] = {
                        "pose": pose, "emotion": emotion, "gaze": gaze,
                        "position": position, "interaction": interaction,
                        "text_pos": text_pos, "focus_char": focus_char,
                    }

            # === 右列：prompt 编辑 ===
            with right:
                st.caption("✅ 正向 Prompt（火山风单段流畅自然语言）")
                cur_pos = entry.get("positive", entry.get("prompt", ""))
                new_pos = st.text_area(
                    label="正向 Prompt",
                    value=cur_pos,
                    height=200,
                    key=f"s4_positive_{idx}",
                    label_visibility="collapsed",
                )
                entry["positive"] = new_pos

                st.caption("❌ 反向 Prompt（每行一条）")
                cur_neg = entry.get("negative", "")
                new_neg = st.text_area(
                    label="反向 Prompt",
                    value=cur_neg,
                    height=180,
                    key=f"s4_negative_{idx}",
                    label_visibility="collapsed",
                )
                entry["negative"] = new_neg

            # 折叠显示最终组装效果
            with st.expander(
                f"🔍 {display_name} · 最终组装效果（含全局风格 + 必出现/避免）",
                expanded=False,
            ):
                final_pos, final_neg = _preview_final_prompt(idx)
                st.markdown("**✅ 正向（最终）：**")
                st.code(final_pos, language="text")
                st.markdown("**❌ 反向（最终）：**")
                st.code(final_neg, language="text")

            if refs:
                st.caption(
                    "🎨 参考图: " + " | ".join(Path(r).name for r in refs[:4])
                )

            st.divider()

        if not embed:
            _confirm_next_step(
                step_num,
                label="✅ 事实和提示词都 OK，进入生图",
                help_text="👉 确认后进入生图步骤。建议至少跑过 Claude 润色（如已配置）",
            )


def _preview_final_prompt(idx: int) -> tuple[str, str]:
    """返回某页（已加全局风格 + A 层人物状态 + 必出现/避免）的最终正向/反向 prompt 文本，供 UI 预览。"""
    page_prompts = st.session_state.get("page_prompts") or {}
    entry = page_prompts.get(idx) or {}
    final_pos = entry.get("positive", "")
    final_neg = entry.get("negative", "")
    style_cfg = st.session_state.get("style_config") or {}
    blocks = _format_style_config_preview(style_cfg) if style_cfg else {
        "positive_block": "", "negative_block": ""
    }
    if blocks["positive_block"]:
        final_pos = f"【全局风格】{blocks['positive_block']}\n\n{final_pos}"
    if blocks["negative_block"]:
        final_neg = (final_neg.rstrip() + "\n" if final_neg else "") + blocks["negative_block"]
    # v3.2 A 层注入
    pc_block = _format_page_constraints(entry.get("page_constraints"))
    if pc_block:
        final_pos = final_pos.rstrip() + "\n\n【A 层 · 本页人物状态约束】\n" + pc_block
    must_inc = (entry.get("must_include") or "").strip()
    if must_inc:
        final_pos = final_pos.rstrip() + "\n\n【教师锁定 · 必须出现】\n" + must_inc
    page_avoid = (entry.get("page_avoid") or "").strip()
    if page_avoid:
        final_neg = (final_neg.rstrip() + "\n" if final_neg else "") + page_avoid
    # v3.2 反馈学习的负向（来自问题反馈面板）
    learned_neg = (entry.get("learned_negatives") or "").strip()
    if learned_neg:
        final_neg = (final_neg.rstrip() + "\n" if final_neg else "") + learned_neg
    return final_pos, final_neg


def _rebuild_one_cn_prompt(page_idx: int) -> None:
    """只重建单页的 prompt（用 cn_prompt_builder 模板）。"""
    ec = st.session_state.extracted
    outline = st.session_state.outline
    if not ec or not outline:
        return
    apply_extracted_to_outline(outline, ec)
    ip_age = outline.ip_age or resolve_ip_age(outline.level)
    page_prompts = st.session_state.get("page_prompts") or {}
    cast_pool = st.session_state.get("story_cast_pool") or None
    generic_overrides = st.session_state.get("generic_overrides") or None
    for page in outline.pages:
        if page.index != page_idx:
            continue
        built = build_cn_page_prompt(
            page, outline, ip_age,
            cast_pool=cast_pool, generic_overrides=generic_overrides,
        )
        prev_must = (page_prompts.get(page_idx) or {}).get("must_include", "")
        prev_avoid = (page_prompts.get(page_idx) or {}).get("page_avoid", "")
        page_prompts[page_idx] = {
            "positive": built.positive,
            "negative": built.negative,
            "prompt": built.prompt,
            "references": [str(r) for r in built.references],
            "must_include": prev_must,
            "page_avoid": prev_avoid,
            "label": page.label,
            "display_name": page_display_name(page.index),
        }
        break
    st.session_state.page_prompts = page_prompts
    st.success(f"✅ 已重建 {page_display_name(page_idx)} 的 prompt")


def _deepseek_rewrite_one_scene(page_idx: int) -> None:
    """让 DeepSeek 重写单页的 scene_cn。"""
    from scene_cn_writer import write_scene_cn, DeepSeekError

    ec = st.session_state.extracted
    outline = st.session_state.outline
    if not ec or not outline:
        return
    page = next((p for p in outline.pages if p.index == page_idx), None)
    ec_page = next((p for p in (ec.pages or []) if p.get("index") == page_idx), None)
    if not page or not ec_page:
        return

    page_prompts = st.session_state.get("page_prompts") or {}
    entry = page_prompts.get(page_idx) or {}
    style_cfg = st.session_state.get("style_config") or {}
    blocks = _format_style_config_preview(style_cfg) if style_cfg else {"positive_block": ""}
    cast_pool = st.session_state.get("story_cast_pool") or []

    # 取人物描述
    cast_descs = _cast_descriptions_from_pool(cast_pool, int(outline.ip_age or 12))

    # 取前几页 scene_cn 做摘要（保持连续性）
    prev_summary = ""
    for prev_idx in sorted(p.get("index") for p in (ec.pages or [])):
        if prev_idx >= page_idx or prev_idx == 0:
            continue
        prev_text = next((p.get("scene_cn", "")[:80] for p in ec.pages if p.get("index") == prev_idx), "")
        if prev_text:
            prev_summary += f"P{prev_idx}: {prev_text}...\n"

    try:
        with st.spinner(f"Claude 正在为 {page_display_name(page_idx)} 写画面描述..."):
            new_scene = write_scene_cn(
                story_sentence=ec_page.get("text", ""),
                page_idx=page_idx,
                book_title=outline.title,
                level=outline.level,
                ip_age=int(outline.ip_age or 12),
                cast_descriptions=cast_descs,
                style_summary=blocks.get("positive_block", ""),
                must_include=entry.get("must_include", ""),
                must_avoid=entry.get("page_avoid", ""),
                previous_pages_summary=prev_summary,
            )
        ec_page["scene_cn"] = new_scene
        st.success(f"✅ Claude 已重写 {page_display_name(page_idx)} 的 scene_cn（{len(new_scene)} 字）")
    except DeepSeekError as e:
        st.error(f"❌ Claude 调用失败：{e}")
    except Exception as e:
        st.error(f"❌ 未预期错误：{e}")


def _deepseek_rewrite_all_scenes() -> None:
    """让 DeepSeek 重写全部 7 页 scene_cn。"""
    ec = st.session_state.extracted
    if not ec or not ec.pages:
        return
    progress = st.progress(0.0)
    total = len(ec.pages)
    for i, ec_page in enumerate(ec.pages, 1):
        idx = ec_page.get("index")
        try:
            _deepseek_rewrite_one_scene(idx)
        except Exception:
            pass
        progress.progress(i / total, text=f"Claude 写第 {i}/{total} 页 scene_cn...")
    progress.empty()
    st.success(f"🎉 Claude 已重写全部 {total} 页 scene_cn。建议下一步点 🔄 重建全部 prompt 让新 scene_cn 注入到 prompt。")


def _deepseek_polish_one_prompt(page_idx: int) -> None:
    """让 DeepSeek 润色单页的正向 prompt。"""
    from scene_cn_writer import polish_image_prompt, DeepSeekError

    page_prompts = st.session_state.get("page_prompts") or {}
    entry = page_prompts.get(page_idx) or {}
    cur_pos = entry.get("positive", "")
    if not cur_pos:
        st.warning("当前页没有正向 prompt，请先点 🔄 重建本页")
        return

    ec = st.session_state.extracted
    ec_page = next((p for p in (ec.pages or []) if p.get("index") == page_idx), None)
    story_sent = ec_page.get("text", "") if ec_page else ""

    style_cfg = st.session_state.get("style_config") or {}
    blocks = _format_style_config_preview(style_cfg) if style_cfg else {"positive_block": ""}

    try:
        with st.spinner(f"Claude 正在润色 {page_display_name(page_idx)} 的 prompt..."):
            polished = polish_image_prompt(
                current_prompt=cur_pos,
                story_sentence=story_sent,
                style_summary=blocks.get("positive_block", ""),
                must_include=entry.get("must_include", ""),
                must_avoid=entry.get("page_avoid", ""),
            )
        entry["positive"] = polished
        page_prompts[page_idx] = entry
        st.session_state.page_prompts = page_prompts
        st.success(f"✅ Claude 已润色 {page_display_name(page_idx)} 的正向 prompt（{len(polished)} 字）")
    except DeepSeekError as e:
        st.error(f"❌ Claude 调用失败：{e}")
    except Exception as e:
        st.error(f"❌ 未预期错误：{e}")


def _cast_descriptions_from_pool(cast_pool: list[str], ip_age: int) -> list[str]:
    """从 cast_pool (IP key 列表) 转成完整的人物形象描述，喂给 DeepSeek。

    优先用 cn_prompt_builder._key_lock_phrase（已包含完整中文外观），
    fallback 到 ip_library 的 description 字段。
    """
    out: list[str] = []
    # 1) 优先：cn_prompt_builder._key_lock_phrase
    try:
        from cn_prompt_builder import _key_lock_phrase
        for key in cast_pool:
            try:
                phrase = _key_lock_phrase(key, ip_age)
                if phrase and phrase.strip():
                    out.append(phrase.strip())
            except Exception:
                continue
        if out:
            return out
    except ImportError:
        pass

    # 2) Fallback: ip_library
    try:
        from ip_library import get_ip
        for key in cast_pool:
            ip = get_ip(key)
            if ip and ip.get("description"):
                out.append(f"{key}：{ip['description']}")
    except ImportError:
        pass
    return out


def _render_step4_page_facts(step_num: int) -> None:
    exp = _locked_step_expander(step_num, "📖 分页事件编辑（7 页的故事文本 + 画面事实）")
    if exp is None:
        return
    with exp:
        st.caption(
            "💡 这一步**只编辑事实**：每页讲什么故事、画面里有什么、必须出现/必避免什么道具。"
            "提示词在下一步 Step 5 由这些事实自动重建。"
        )
        ec = st.session_state.extracted
        page_prompts = st.session_state.get("page_prompts") or {}
        ec_pages_by_idx = {p.get("index"): p for p in (ec.pages or [])}

        for idx in sorted(page_prompts.keys()):
            entry = page_prompts[idx]
            ec_page = ec_pages_by_idx.get(idx) or {}
            display_name = entry.get("display_name") or page_display_name(idx)
            label_kind = "封面" if idx == 0 else "故事页"

            st.markdown(f"#### {display_name} · {label_kind}")

            c1, c2 = st.columns([1, 1])
            with c1:
                st.caption("① 故事原文（英文）")
                new_text = st.text_area(
                    f"text_{idx}",
                    value=ec_page.get("text", ""),
                    height=120,
                    key=f"s4_text_{idx}",
                    label_visibility="collapsed",
                )
                if new_text != ec_page.get("text", ""):
                    ec_page["text"] = new_text
            with c2:
                st.caption("② 中文画面描述（120-220 字，AI 已生成可改）")
                new_scene_cn = st.text_area(
                    f"scene_cn_{idx}",
                    value=ec_page.get("scene_cn", ""),
                    height=120,
                    key=f"s4_scene_cn_{idx}",
                    label_visibility="collapsed",
                    placeholder=(
                        "AI 应该生成 120-220 字连贯描述：\n"
                        "主体（人物+具体外观）+ 动作（具体动词姿势）+ 环境（可见物品）+ 氛围（光照）"
                    ),
                )
                if new_scene_cn != ec_page.get("scene_cn", ""):
                    ec_page["scene_cn"] = new_scene_cn

            c3, c4 = st.columns([1, 1])
            with c3:
                st.caption("③ 必须出现（每行一条，会追加到正向提示词）")
                entry["must_include"] = st.text_area(
                    f"must_inc_{idx}",
                    value=entry.get("must_include", ""),
                    height=100,
                    key=f"s4_must_{idx}",
                    label_visibility="collapsed",
                    placeholder="Anna 戴琥珀色细框眼镜\nAnna 黑色双低马尾\n桌上 5 本课本\n教室背景：绿色黑板",
                )
            with c4:
                st.caption("④ 必避免（每行一条，会追加到反向提示词）")
                entry["page_avoid"] = st.text_area(
                    f"page_avoid_{idx}",
                    value=entry.get("page_avoid", ""),
                    height=100,
                    key=f"s4_avoid_{idx}",
                    label_visibility="collapsed",
                    placeholder="本页不应有宠物\n不要 Tommy 戴眼镜\nMia 不能散发",
                )

            bc1, bc2 = st.columns([1, 3])
            with bc1:
                cur_shot = ec_page.get("shot", "medium") or "medium"
                new_shot = st.selectbox(
                    f"镜头_{idx}",
                    SHOT_OPTIONS,
                    index=max(0, SHOT_OPTIONS.index(cur_shot) if cur_shot in SHOT_OPTIONS else 1),
                    key=f"s4_shot_{idx}",
                )
                if new_shot != cur_shot:
                    ec_page["shot"] = new_shot
            with bc2:
                refs = entry.get("references", [])
                if refs:
                    st.caption(
                        "🎨 参考图: " + " | ".join(Path(r).name for r in refs[:4])
                    )

            st.divider()

        _confirm_next_step(
            step_num,
            label="✅ 确认分页事件，重建提示词",
            help_text="👉 确认后会基于新事实**重建所有 7 页提示词**，进入 Step 5 审核",
        )


# ============================================================================
# Step 5：📝 提示词预览（基于事实重建 + 单页正向/反向编辑）
# ============================================================================

def _render_step5_prompts(step_num: int) -> None:
    exp = _locked_step_expander(step_num, "📝 提示词预览与微调（正向 + 反向 双段）")
    if exp is None:
        return
    with exp:
        st.caption(
            "💡 提示词 = Step 3 风格设定 + Step 4 分页事实 自动组装。"
            "可以手动微调；如果改回事实，请回 Step 4。"
        )

        page_prompts = st.session_state.get("page_prompts") or {}

        col_rebuild, _ = st.columns([1, 3])
        with col_rebuild:
            if st.button(
                "🔄 基于最新事实/风格重建全部 prompt",
                type="secondary",
                key="s5_rebuild_all",
                width="stretch",
                help="把 Step 3 风格设定 + Step 4 分页事实 重新组装成提示词，会**覆盖**当前已编辑的 prompt",
            ):
                _rebuild_all_cn_prompts()
                st.success("✅ 已重建全部 prompt")
                st.rerun()

        for idx in sorted(page_prompts.keys()):
            entry = page_prompts[idx]
            display_name = entry.get("display_name") or page_display_name(idx)
            refs = entry.get("references", [])
            ref_badge = f"🖼️ {len(refs)} 张参考图" if refs else "⚠️ 无参考图"
            st.markdown(f"#### {display_name} · {ref_badge}")

            c3a, c3b = st.columns([3, 2])
            with c3a:
                st.caption("✅ 正向 Prompt（火山风单段流畅自然语言）")
                cur_pos = entry.get("positive", entry.get("prompt", ""))
                new_pos = st.text_area(
                    f"s5_positive_{idx}",
                    value=cur_pos,
                    height=200,
                    key=f"s5_pos_{idx}",
                    label_visibility="collapsed",
                )
                entry["positive"] = new_pos
            with c3b:
                st.caption("❌ 反向 Prompt（每行一条，不要什么）")
                cur_neg = entry.get("negative", "")
                new_neg = st.text_area(
                    f"s5_negative_{idx}",
                    value=cur_neg,
                    height=200,
                    key=f"s5_neg_{idx}",
                    label_visibility="collapsed",
                )
                entry["negative"] = new_neg

            with st.expander(f"🔍 {display_name} 最终组装效果（含 Step 3 全局设定）", expanded=False):
                final_pos = entry.get("positive", "")
                final_neg = entry.get("negative", "")
                style_cfg = st.session_state.get("style_config") or {}
                blocks = _format_style_config_preview(style_cfg) if style_cfg else {
                    "positive_block": "", "negative_block": ""
                }
                if blocks["positive_block"]:
                    final_pos = f"【全局风格】{blocks['positive_block']}\n\n{final_pos}"
                if blocks["negative_block"]:
                    final_neg = (final_neg.rstrip() + "\n" if final_neg else "") + blocks["negative_block"]
                must_inc = (entry.get("must_include") or "").strip()
                if must_inc:
                    final_pos = final_pos.rstrip() + "\n\n【教师锁定 · 必须出现】\n" + must_inc
                page_avoid = (entry.get("page_avoid") or "").strip()
                if page_avoid:
                    final_neg = (final_neg.rstrip() + "\n" if final_neg else "") + page_avoid

                st.markdown("**✅ 正向（最终）：**")
                st.code(final_pos, language="text")
                st.markdown("**❌ 反向（最终）：**")
                st.code(final_neg, language="text")

            st.divider()

        _confirm_next_step(
            step_num,
            label="✅ 提示词 OK，进入生图",
            help_text="👉 确认后进入生图步骤。生图时会自动用最终组装的提示词。",
        )


# ============================================================================
# Step 6：🖼️ 单页生图（Phase 1 保持当前 1 图，Phase 2 升级 3 候选）
# ============================================================================

def _render_step6_image_gen(step_num: int, embed: bool = False) -> None:
    if embed:
        exp = contextlib.nullcontext()
    else:
        exp = _locked_step_expander(step_num, "🖼️ 单页生图（生成 → 审核 → 单图重生）")
        if exp is None:
            return
    with exp:
        st.caption(
            "💡 每页生 1 张图（gpt-image-2，主角恒为首位参考图保持一致），不满意可单页重生。"
        )

        _force_mock = not bool(JIMENG_API_KEY)
        mock_imgs = st.checkbox(
            "🟡 仅调试版式时勾选（不调用 gpt-image-2 API，用占位图代替）",
            value=_force_mock,
            disabled=_force_mock,
            help="**正式出图请保持不勾**。",
            key="s6_mock_imgs",
        )
        if mock_imgs:
            st.warning("⚠️ 当前为 **占位图模式**。要出正式 PPT 请先取消勾选。")

        col_a, col_b = st.columns([4, 1])
        with col_a:
            n_pages = len(st.session_state.outline.pages) if st.session_state.outline else 8
            est_seconds = n_pages * 15
            if not mock_imgs:
                st.info(
                    f"🎨 将调用 gpt-image-2 出 {n_pages} 张水彩绘本插画，"
                    f"约需 {est_seconds//60} 分 {est_seconds%60} 秒。"
                )
        with col_b:
            if st.button("🎨 生成 / 重新生成所有图", type="primary",
                         width="stretch", key="s6_gen_btn"):
                _run_image_generation_only(mock_imgs)

        if st.session_state.get("image_results"):
            st.divider()
            _render_image_review_panel(mock_imgs)
            n_locked = sum(1 for r in st.session_state.image_results.values() if r.get("locked"))
            n_total = len(st.session_state.image_results)
            if n_locked < n_total:
                st.warning(f"还有 {n_total - n_locked} 张图未锁定 ✅。")
            else:
                st.success(f"🎉 全部 {n_total} 张图已锁定。")

            if not embed:
                _confirm_next_step(
                    step_num,
                    label="✅ 图都满意，进入组装",
                    help_text="👉 建议先把全部图勾 ✅ 锁定再进入下一步",
                )


# ============================================================================
# Step 7：📦 组装 4 件套
# ============================================================================

def _render_step7_assemble(step_num: int) -> None:
    exp = _locked_step_expander(step_num, "📦 组装 4 件套（PPT / Worksheet / RR / TG）")
    if exp is None:
        return
    with exp:
        st.caption("💡 点击下方按钮，会用 Step 6 锁定的图 + Step 1-5 的数据，一键打包成 ZIP。")

        if not st.session_state.get("image_results"):
            st.error("⚠️ 还没有生图结果，请回 Step 6 先生图")
            return

        n_locked = sum(1 for r in st.session_state.image_results.values() if r.get("locked"))
        n_total = len(st.session_state.image_results)
        st.info(f"📊 当前 {n_locked}/{n_total} 张图已锁定")

        if st.button("📦 组装 4 件套 + 打包 ZIP", type="primary",
                     width="stretch", key="s7_assemble"):
            _run_docs_assembly()


def _format_page_constraints(pc: dict | None) -> str:
    """把 A 层 page_constraints 字段拼成一段可注入正向 prompt 的文字。

    自动跳过 🤖 字段（让 AI 自己推断）。
    """
    if not pc:
        return ""
    bits: list[str] = []
    pose = pc.get("pose", "")
    if pose and not pose.startswith("🤖"):
        bits.append(f"主角姿势：{pose}")
    emo = pc.get("emotion", "")
    if emo and not emo.startswith("🤖"):
        bits.append(f"情绪：{emo}")
    gaze = pc.get("gaze", "")
    if gaze and not gaze.startswith("🤖"):
        bits.append(f"视线：{gaze.split('（')[0]}")
    pos = pc.get("position", "")
    if pos and not pos.startswith("🤖"):
        bits.append(f"画面位置：{pos.split('（')[0]}")
    inter = pc.get("interaction", "")
    if inter and not inter.startswith("🤖"):
        bits.append(f"互动关系：{inter}")
    text_pos = pc.get("text_pos", "")
    if text_pos and not text_pos.startswith("🤖") and not text_pos.startswith("无"):
        bits.append(f"留白：{text_pos.split('（')[0]}")
    focus = (pc.get("focus_char") or "").strip()
    if focus:
        bits.append(f"焦点角色：{focus}（应当更大、更清晰、位置更接近中心）")
    return "；".join(bits)


def _format_style_config_preview(cfg: dict) -> dict:
    """把 6 字段拼成可注入提示词的两段（正向 + 反向）。"""
    pos_parts: list[str] = []
    # 视觉风格
    vs = cfg.get("visual_style", "")
    if vs:
        pos_parts.append(f"风格：{vs.split('（')[0]}")
    # 主场景（自动则不强制）
    scene = cfg.get("main_scene", "")
    if scene and not scene.startswith("🤖"):
        pos_parts.append(f"全本主场景：{scene}")
    # 色调
    tone = cfg.get("color_tone", "")
    if tone:
        pos_parts.append(f"色调：{tone.split('（')[0]}")
    # 构图
    comp = cfg.get("composition", "")
    if comp:
        pos_parts.append(f"构图：{comp.split('（')[0]}")
    # 光源
    light = cfg.get("light_source", "")
    if light:
        pos_parts.append(f"光源：{light.split('（')[0]}")
    # 留白
    if cfg.get("text_safe_zone"):
        pos_parts.append("画面顶部和底部 25% 留白给文字，主体居中偏下")
    # v3.2 B 层：视角
    view = cfg.get("view_angle", "")
    if view and not view.startswith("🤖"):
        pos_parts.append(f"视角：{view.split('（')[0]}")
    # v3.2 B 层：焦点处理
    focus = cfg.get("focus_handling", "")
    if focus:
        pos_parts.append(f"景深：{focus.split('（')[0]}")
    # 全局必出现
    must = (cfg.get("global_must") or "").strip()
    if must:
        items = [l.strip() for l in must.splitlines() if l.strip()]
        if items:
            pos_parts.append("全局必出现：" + "；".join(items))

    positive_block = "；".join(pos_parts)

    avoid = (cfg.get("global_avoid") or "").strip()
    avoid_items = [l.strip() for l in avoid.splitlines() if l.strip()]
    negative_block = "；".join(avoid_items)

    return {"positive_block": positive_block, "negative_block": negative_block}


# =============================== 主入口 ===============================
# ============================================================================
# v3.3：5 步工作流（合并 IP+画风、新增只读底层逻辑、合并提示词+生图为工作台）
# ============================================================================

def _render_step_ip_style(step_num: int) -> None:
    """Step 2（合并旧 IP 锁定 + 画风设定）：先锁人，再定调。"""
    exp = _locked_step_expander(step_num, "🎭 人物 IP + 🎨 画风背景（先锁人，再定调）")
    if exp is None:
        return
    with exp:
        st.markdown("#### 🎭 A · 人物 IP 锁定")
        _render_step2_ip_lock(step_num, embed=True)
        st.divider()
        st.markdown("#### 🎨 B · 画风 / 背景设定（全局应用到所有页）")
        _render_style_panel_step(step_num, embed=True)
        _confirm_next_step(
            step_num,
            label="✅ 人物 + 画风都锁定，进入生图工作台",
            help_text="👉 IP 决定参考图、画风注入每页提示词；确认后进入生图工作台",
        )


def _render_step_rules(step_num: int) -> None:
    """Step 3（新）：底层逻辑 / 系统硬规则（只读，无需输入）。"""
    exp = _locked_step_expander(step_num, "📐 底层逻辑（系统自动套用的硬规则 · 只读）")
    if exp is None:
        return
    with exp:
        outline: BookOutline = st.session_state.outline
        level_key = (outline.level_key if outline else "5")
        is_dual = level_key in ("smart", "0", "1", "2")
        rr_dist = rr_question_distribution(outline.level if outline else "5")
        star = " + ".join(
            f"{rr_dist.count(s)}×{'⭐' * s}" for s in sorted(set(rr_dist))
        )
        st.caption("💡 以下规则**全自动套用**到所有交付物，无需你输入。列在这里是为了让你心里有数。")

        cp = COMPOSITION_POLICY
        st.markdown(
            "**🎯 画面构图 / 比例（AI 按故事自动决定，自动注入每页提示词）**\n"
            f"- 主角是**画面唯一视觉中心**，占画面 **{cp['protagonist_pct']}**（清晰饱满）\n"
            f"- 同框人物按**真实身高比例**（谁都不能比同框同龄人明显大一圈）\n"
            f"- 动物按**真实比例**（仓鼠≈手掌大，不会画成猫狗大小）\n"
            f"- 背景占 **{cp['background_pct']}**，环境清晰但不喧宾夺主\n"
            f"- 视角：{cp['perspective']}　·　画风：{cp['style']}"
        )
        st.divider()

        c1, c2 = st.columns(2)
        with c1:
            st.markdown(
                "**🖼️ 绘本图片**\n"
                "- 比例 **3:2 横版**（1536×1024，gpt-image-2）\n"
                "- 主角**恒为首位参考图**，保证全本不跳帧\n"
                "- 每页预留 **~20% 浅色区**给文字，模型自动选边\n"
                "- 页数 = **封面 + 7 故事 = 8 页**（PPT 补足 4 的倍数）"
            )
            st.markdown(
                "**📝 词汇显示**\n"
                + ("- 当前 **L0-L2 双行**：Mastery + Exposure\n"
                   if is_dual else
                   "- 当前 **L3-L6 单行**：Vocabulary 4 词\n")
                + "- 全部 **lemma 原型 + 小写 + 无标点**"
            )
        with c2:
            st.markdown(
                "**📄 文档规格**\n"
                "- Reading Report：**A4 竖版**，控制在 **1 页**\n"
                f"- RR 阅读表达题：**{len(rr_dist)} 题**（{star}），标 (P×) 出处\n"
                "- Worksheet：固定 **2 词汇 + 2 句子 + 2 阅读** 方向\n"
                "- 阅读字数 = **纯故事字数**（不含题目）"
            )
            st.markdown(
                "**📦 命名 / 打包**\n"
                "- 文件名：`Level X_BookXX_品类_标题.后缀`\n"
                "- 字体：标题 Poppins 40pt / 副标题 22pt\n"
                "- 一键打包 **绘本+练习册+RR+TG → ZIP**"
            )
        _confirm_next_step(
            step_num,
            label="✅ 我了解这些规则，进入 IP + 画风锁定",
            help_text="👉 这些是系统硬规则（含构图/比例），自动生效；确认后进入 IP + 画风锁定",
        )


def _render_step_workbench(step_num: int) -> None:
    """Step 4（合并旧 分页提示词 + 单页生图）：生图工作台。"""
    exp = _locked_step_expander(
        step_num, "🖼️ 生图工作台（一键出 8 图 → 图旁看故事 → 逐页重生/锁定）"
    )
    if exp is None:
        return
    with exp:
        st.caption(
            "💡 **图在前**：先一键出 8 张图；每张图旁边直接显示「该页故事原文 + 剧情要点」，"
            "提示词默认折叠。不满意就点 🔁 重生 / 展开提示词改了再出（像即梦逐页调）。"
        )
        # 🎨 主区：生成 + 逐页审核（图大、文字在旁、提示词折叠）
        _render_step6_image_gen(step_num, embed=True)

        st.divider()
        # ✍️ 次要：分页提示词总览（默认收起；用 checkbox 而非 expander，避免与内部 expander 嵌套）
        if st.checkbox(
            "✍️ 展开高级：分页提示词总览（批量查看 / Claude 润色，一般不用动）",
            value=False,
            key="wb_show_prompt_overview",
        ):
            _render_step4_combined(step_num, embed=True)

        _confirm_next_step(
            step_num,
            label="✅ 图都满意，进入组装",
            help_text="👉 建议先把全部图勾 ✅ 锁定再进入组装",
        )


def main() -> None:
    st.set_page_config(
        page_title="VIPKID Dino 绘本工作流",
        page_icon="📘",
        layout="wide",
    )
    _inject_css()

    st.title("📘 VIPKID Dino 绘本工作流 v3.3")
    st.caption(
        "输入故事原文 → AI 抽取词汇/分页/语法/题目 → 老师微调 → 一键产出 4 件套（绘本 PPT / Worksheet / Reading Report / Teacher Guide）  \n"
        "**v3.3 更新**：文本走 Claude（claude-opus-4-7）· 生图走 gpt-image-2（主角恒首位参考，全本不跳帧）· 中文 prompt（主体+行为+环境结构）· 5 步工作流"
    )

    _key_status_banner()

    # Session 状态
    if "extracted" not in st.session_state:
        st.session_state.extracted = None
    if "outline" not in st.session_state:
        st.session_state.outline = None

    # ---------- Section A：输入表单 ----------
    # v1.8.2：极简输入 — 必填只有 3 项，其余全自动 + 透明展示
    st.success(
        "🎯 **必填只有 3 项**：① Book Title  ② Level  ③ 故事原文  \n"
        "   其余全部由 AI 根据这 3 项自动推断（CEFR / 蓝思 / 字数 / 故事类型 / 主题 / 主角识别 / Phonics / 语法 / 词表）  \n"
        "   👇 填完点 AI 抽取后，会立即显示「📊 AI 推断卡片」+「🎭 主角识别面板」让你审核。"
    )

    with st.form("input_form"):
        # === 必填区 ===
        st.subheader("1️⃣  必填基础信息")
        col1, col2 = st.columns([3, 1])
        with col1:
            title = st.text_input(
                "📕 Book Title *",
                value="What Makes a Good Friend?",
                help="必填。系统会用它做文件名 / 封面 / 各文档大标题。",
            )
        with col2:
            level = st.selectbox(
                "🎚️ Level *", LEVEL_OPTIONS, index=5,
                help="必填。Smart / 0-2 = 双行词表，3-6 = 单行词表。决定 CEFR / Reader Type / 题数。",
            )

        st.markdown("**📝 故事原文 \\* —— 7 句以内，每句一行 = 一页绘本**")
        raw_story = st.text_area(
            "Raw story",
            label_visibility="collapsed",
            height=200,
            value=(
                "Anna felt nervous on her first day in the new class. Her hands shook as she sat down at a small wooden desk.\n"
                "At recess she saw a girl drop a pile of books on the floor. Anna helped pick up the books and smiled at the girl.\n"
                "Later she shared pencils and glue with a quiet boy at his table. The boy looked up and said thank you to her softly.\n"
                "A class hamster grabbed Anna's eraser and ran under a chair. The hamster looked like a tiny thief and everyone laughed together.\n"
                "Anna listened when classmates told stories about pets and games. She said, 'Tell me more,' and asked each person kind questions.\n"
                "Her classmates all liked her because she cared about them and helped them. Anna felt glad she had been kind from her very first day.\n"
                "By the week's end Anna had many new friends and a plan. The next week she would bake cookies and bring them for everyone in the class."
            ),
        )

        # === 选填区（折叠）===
        st.subheader("2️⃣  选填（不填 AI 全自动）")
        with st.expander("⚙️  选填字段（让交付物更精准）", expanded=False):
            col1, col2, col3 = st.columns(3)
            with col1:
                book_number = st.text_input(
                    "Book #", value="01",
                    help="书号，用于文件名 `Level X_BookXX_品类_标题.后缀`",
                )
                theme = st.text_input(
                    "Theme",
                    value="friendship",
                    help="主题，会用在 Writing 页 \"Write about ...\" 和 TG 的目标里",
                )
            with col2:
                cefr = st.text_input(
                    "CEFR (留空 = 按 Level 自动)",
                    value="",
                    help="Smart/L0/L1=Pre-A1, L2=A1, L3=A1+, L4=A2, L5=B1, L6=B1+",
                )
                ip_age_default = resolve_ip_age(level)
                ip_age = st.number_input(
                    "IP 年龄（默认按 Level）",
                    min_value=6, max_value=14, value=ip_age_default,
                    help="Smart/L0-3 = 8 岁；L4 = 10 岁；L5-6 = 12 岁",
                )
            with col3:
                # L3-6 才让选 Fiction / Non-Fiction
                level_digits = "".join(ch for ch in level if ch.isdigit())
                try:
                    lvl_n = int(level_digits) if level_digits else 0
                except ValueError:
                    lvl_n = 0
                if lvl_n >= 3:
                    fiction_type = st.selectbox(
                        "Reader Type (L3-6)",
                        ["fiction", "non-fiction"],
                        index=0,
                        help="L3-6 在 Reading Report 第一行显示为 'Fiction' 或 'Non-Fiction'",
                    )
                else:
                    fiction_type = ""
                    rt_map = {
                        "smart": "Concept & Knowledge - Building Readers",
                        "0": "Concept & Knowledge - Building Readers",
                        "1": "Patterned Narrative & Informational Readers",
                        "2": "Early Independent Genre-Exposure Readers",
                    }
                    rt = rt_map.get(level.lower(), rt_map.get(level_digits, ""))
                    st.info(f"📖 Reader Type：**{rt}**（按 Level 固定，无需选）")

            st.divider()
            st.markdown("**👥 角色设定**（已注册角色系统自动识别，新人物才需在下方手填）")
            try:
                from character_registry import list_available
                chars = list_available()
                cols = st.columns(3)
                for i, ch in enumerate(chars):
                    with cols[i % 3]:
                        ages_str = "/".join(str(a) for a in ch["age_options"])
                        emoji = {"protagonist": "⭐", "supporting": "👥", "adult": "👩‍🏫",
                                 "pet": "🐱", "brand": "🦖", "family": "👨‍👩‍👧"}.get(ch["kind"], "•")
                        check = "✅" if ch["reference_exists"] else "⚠️"
                        st.markdown(f"{emoji} **{ch['key']}** ({ages_str}) {check}")
                st.caption("✅ = 有官方参考图  ⚠️ = 缺参考图。出现这些名字时系统会自动加载形象。")
            except Exception as e:
                st.warning(f"角色注册表加载失败：{e}")
            custom_chars_text = st.text_area(
                "🆕 新人物注册（只在故事出现 \"全新\" 人物时填，每行：name | description）",
                value="",
                height=60,
                help="如：lucy | 8y GIRL, twin braids, red sweater, freckles —— 已在角色库的角色（mia/tommy/anna/teacher_kim/winnie 等）不用填",
            )

        submitted = st.form_submit_button(
            "🤖 AI 抽取 / 重新抽取", type="primary", width="stretch",
        )

    if submitted:
        with st.spinner("Claude 正在抽词、拆段、出题..."):
            # 先做 AI 自动推断（角色识别 + CEFR/Lexile/Theme/Fiction-NF）
            auto = auto_summary(level, raw_story, title)
            # 用户没填 cefr / theme / fiction_type 时，用自动值兜底
            cefr_final = cefr.strip() or auto["cefr"]
            theme_final = theme.strip() or auto["theme"]
            fiction_final = fiction_type.strip() or auto["fiction_type"]

            ec = extract_all(
                raw_story=raw_story,
                title=title,
                level=level,
                cefr=cefr_final,
                theme=theme_final,
            )
            outline = _build_outline(
                title=title, level=level, book_number=book_number,
                cefr=cefr_final, theme=theme_final, ip_age=int(ip_age),
                raw_story=raw_story, custom_chars_text=custom_chars_text,
                fiction_type=fiction_final,
            )
            apply_extracted_to_outline(outline, ec)
            st.session_state.extracted = ec
            st.session_state.outline = outline
            st.session_state.auto = auto
            st.session_state.auto["_lexile"] = auto["lexile"]  # 留作生成阶段元信息

            # v1.9：预生成每页中文 prompt（按 Seedream 4.5 官方指南），存 session 供用户编辑
            ip_age_val = int(ip_age)
            page_prompts: dict[int, dict] = {}
            cast_pool = st.session_state.get("story_cast_pool") or None
            generic_overrides = st.session_state.get("generic_overrides") or None
            for page in outline.pages:
                built = build_cn_page_prompt(
                    page, outline, ip_age_val,
                    cast_pool=cast_pool, generic_overrides=generic_overrides,
                )
                page_prompts[page.index] = {
                    "positive": built.positive,
                    "negative": built.negative,
                    "prompt": built.prompt,
                    "references": [str(r) for r in built.references],
                    "must_include": "",
                    "label": page.label,
                    "display_name": page_display_name(page.index),
                }
            st.session_state.page_prompts = page_prompts

        st.success(
            "✅ 抽取完成。请审核下方「AI 推断 + 主角识别 + 每页卡片（文本+场景+prompt+必须出现）」，"
            "再点最底部 Generate All。"
        )

    # ---------- v2.0：7 步严格解锁绘本组装工作流 ----------
    if st.session_state.extracted is not None:
        # 抽取完成 → 至少解锁到 Step 2
        if st.session_state.get("book_unlocked_step", 1) < 2:
            st.session_state["book_unlocked_step"] = 2

        st.divider()
        st.subheader("🛠️ 制作工作台（绘本 / Worksheet 双轨并行）")
        st.caption(
            "两条轨道**共享同一份 AI 抽取数据**（词表/分页/题目）。"
            "📘 绘本轨负责出图；📝 Worksheet 轨负责逐题打磨。"
            "最终 4 件套在「📘 绘本轨 · Step 5 组装」一键打包（含 Worksheet / Reading Report / Teacher Guide）。"
        )

        tab_book, tab_ws = st.tabs(["📘 绘本工作流", "📝 Worksheet / 阅读报告 工作流"])

        with tab_book:
            st.subheader("📘 绘本组装工作流（5 步严格解锁 · 每步点 ✅ 才能进入下一步）")
            _render_progress_bar()

            col_reset, _ = st.columns([1, 5])
            with col_reset:
                _reset_workflow_button()

            # Step 2：📐 底层逻辑（只读硬规则）— 上移到最前，先让老师心里有数
            _render_step_rules(step_num=2)

            # Step 3：🎭 人物 IP + 🎨 画风（合并）
            _render_step_ip_style(step_num=3)

            # Step 4：🖼️ 生图工作台（提示词编辑 + 生成 + 审核重生）
            _render_step_workbench(step_num=4)

            # Step 5：📦 组装 4 件套
            _render_step7_assemble(step_num=5)

        with tab_ws:
            st.subheader("📝 Worksheet / Reading Report 过程性出题")
            st.caption(
                "💡 在这里逐题打磨题目：①换题型/难度 ②🤖 AI 重出 ③手动改。"
                "词表为两轨共享（绘本 PPT 也用）。改完点「👀 生成 Worksheet 初稿」预览，"
                "或回「📘 绘本工作流 · Step 5」一键组装 4 件套。"
            )
            _render_editable_preview()


# =============================== 编辑器 ===============================
def _render_auto_summary_panel() -> None:
    """v1.8.2：AI 自动推断 + 主角识别透明化面板。

    展示两块内容，让老师在生图前能审核：
      1. AI 推断卡片 — CEFR / 蓝思 / 字数 / 故事类型 / 主题
      2. 主角识别面板 — 故事里识别到的官方 IP（含参考图 ✓/⚠️）+ 未命名 girl/boy 的默认形象建议
    """
    auto = st.session_state.auto

    st.divider()
    st.subheader("🤖 AI 自动推断（你不用填，系统已根据故事 + 级别算好）")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("📏 CEFR 等级", auto["cefr"])
    c2.metric("📊 蓝思 Lexile", auto["lexile"])
    c3.metric("🔢 故事字数", auto["word_count"])
    c4.metric("📖 故事类型", "Fiction" if auto["fiction_type"] == "fiction" else "Non-Fiction")
    c5.metric("🏷️ 主题", auto["theme"] or "(空)")

    st.caption(
        "💡 以上字段 AI 自动生成，需要覆盖请去顶部「⚙️ 选填字段」展开后填入对应项 → 会覆盖自动值。"
    )

    # === 主角识别面板 ===
    st.subheader("🎭 主角识别（让你确认 AI 理解的故事人物是谁）")
    chars = auto.get("characters", [])
    generic = auto.get("generic_roles", [])

    if not chars and not generic:
        st.info("ℹ️ 未在故事里识别到已注册的 IP 角色。系统将按通用 girl/boy 生成（默认套 Mia/Tommy 形象）。")
        return

    if chars:
        st.markdown(f"**✅ 已匹配到 {len(chars)} 个官方 IP**（生图时会自动用对应参考图保证形象一致）：")
        ncols = min(len(chars), 4)
        cols = st.columns(ncols)
        for i, ch in enumerate(chars):
            with cols[i % ncols]:
                ref_badge = "✅ 有官方参考图" if ch["reference_exists"] else "⚠️ 缺参考图"
                kind_emoji = {
                    "protagonist": "⭐", "supporting": "👥", "adult": "👩‍🏫",
                    "pet": "🐱", "brand": "🦖", "family": "👨‍👩‍👧",
                }.get(ch["kind"], "•")
                st.markdown(
                    f"### {kind_emoji} {ch['name_in_story']}\n"
                    f"**Registry key**: `{ch['matched_key']}`  \n"
                    f"**类别**: {ch['kind']}  |  **性别**: {ch['gender']}  |  **年龄**: {ch['age']}y  \n"
                    f"**参考图**: {ref_badge}"
                )
                if ch["reference_exists"] and ch["reference_path"]:
                    try:
                        st.image(ch["reference_path"], width="stretch")
                    except Exception:
                        pass
                with st.expander(f"形象描述（生图 prompt 用）"):
                    st.caption(ch["description"])

    # === v2.1 新增：故事人物库 IP 选择器 + 无名角色映射 ===
    _render_ip_cast_panel(chars, generic)

    st.warning(
        "🔍 **请审核以上识别结果。** 如果识别错了（例如把 Mary 误识别为 Mia），"
        "请去顶部「⚙️ 选填字段」→「🆕 新人物注册」加一行 `mary | 12y GIRL, ...` 把新人物注册进来，"
        "再点 AI 重新抽取。"
    )


def _render_ip_cast_panel(detected_chars: list[dict], detected_generic: list[dict]) -> None:
    """v2.1: 故事人物库可视化选择器 + 无名角色映射。

    UI 结构：
      1. 「📚 这本绘本会出现的全部 IP」— 按 kind 分组，每个 IP 显示缩略图，
         可勾选。默认勾选已检测到的 IP，老师可加勾其他 IP。
      2. 「🎭 无名角色映射」— 故事文本里出现的 a girl/a boy 等，老师选用谁的形象。
      3. 结果写入 st.session_state['story_cast_pool'] (list of IP key) 和
         st.session_state['generic_overrides'] (dict role→key)，
         供 cn_prompt_builder 使用。
    """
    from ip_library import list_by_kind, get_ip
    from config import resolve_ip_age

    st.markdown("---")
    st.subheader("📚 这本绘本会出现的全部 IP（勾选 = 生图时会作为参考形象）")
    st.caption(
        "✅ 已自动勾选「故事里识别到的角色」。"
        "如果某页需要其他 IP 出场（如班里其他同学、家人探班），可加勾。"
        "**勾选项越多，生图时可挑选的参考图越多**。"
    )

    # 当前 outline 的 IP age（用于挑年龄档）
    outline = st.session_state.get("outline")
    level = outline.level if outline else "5"
    target_age = resolve_ip_age(level)

    # 自动默认勾选：识别到的 IP（按 age 档匹配） + 无名角色默认套的 IP
    auto_keys: set[str] = set()
    for ch in detected_chars:
        # ch["matched_key"] 可能是 base（"anna"），我们要带 age 后缀的（"anna_12"）
        from ip_library import resolve_name_to_ip
        ip = resolve_name_to_ip(ch["matched_key"], target_age)
        if ip:
            auto_keys.add(ip.key)
    for g in detected_generic:
        from ip_library import resolve_generic_role
        ip = resolve_generic_role(g["role"], target_age)
        if ip:
            auto_keys.add(ip.key)

    # 上次手动选过的话，沿用；否则用 auto 默认
    if "story_cast_pool" not in st.session_state or not st.session_state["story_cast_pool"]:
        st.session_state["story_cast_pool"] = sorted(auto_keys)

    selected: set[str] = set(st.session_state.get("story_cast_pool", []))

    # 按 kind 分组渲染（每个 kind 一个 expander）
    kind_label = {
        "protagonist": "⭐ 主角",
        "supporting":  "👥 朋友/同学",
        "family":      "👨‍👩‍👧 家人",
        "adult":       "👩‍🏫 老师/成人",
        "pet":         "🐱 宠物",
        "brand":       "🦖 品牌（Dino 等）",
    }
    grouped = list_by_kind()

    new_selected: set[str] = set()
    for kind in ["protagonist", "supporting", "family", "adult", "pet", "brand"]:
        if kind not in grouped:
            continue
        entries = grouped[kind]
        expanded = (kind in ("protagonist", "supporting"))  # 主角/朋友默认展开
        with st.expander(f"{kind_label.get(kind, kind)} ({len(entries)})", expanded=expanded):
            ncols = 4
            for row_start in range(0, len(entries), ncols):
                cols = st.columns(ncols)
                for j, e in enumerate(entries[row_start:row_start + ncols]):
                    with cols[j]:
                        try:
                            st.image(str(e.image_path), width="stretch")
                        except Exception:
                            pass
                        is_checked = st.checkbox(
                            e.name,
                            value=(e.key in selected),
                            key=f"ip_pick_{e.key}",
                            help=e.desc[:120],
                        )
                        if is_checked:
                            new_selected.add(e.key)

    st.session_state["story_cast_pool"] = sorted(new_selected)
    st.success(f"✅ 已选 **{len(new_selected)}** 个 IP 进入这本绘本的人物池")

    # === 无名角色映射器 ===
    if detected_generic:
        st.markdown("---")
        st.markdown("##### 🎭 无名角色映射（故事里 a girl / a boy 等 → 用哪个 IP 形象）")
        st.caption("默认按规则套（girl→Mia / boy→Tommy / woman→Mom 等）。可改成你想要的 IP。")

        overrides = st.session_state.get("generic_overrides", {}) or {}
        new_overrides: dict[str, str] = {}

        # 候选 IP = 当前选中的人物池（按 gender 过滤）
        pool_entries = [get_ip(k) for k in new_selected if get_ip(k)]
        # 性别过滤候选
        def _pick_options(role_gender: str) -> list[tuple[str, str]]:
            """返回 [(key, label), ...] 候选。"""
            cands = pool_entries
            if role_gender in ("girl", "woman"):
                cands = [e for e in pool_entries if e.gender in ("girl", "woman")]
            elif role_gender in ("boy", "man"):
                cands = [e for e in pool_entries if e.gender in ("boy", "man")]
            elif role_gender in ("cat",):
                cands = [e for e in pool_entries if e.kind == "pet"]
            opts = [("__skip__", "（跳过 / 不强制 IP）")]
            opts += [(e.key, e.name) for e in cands]
            return opts

        role_gender_map = {
            "girl": "girl", "boy": "boy",
            "woman": "woman", "man": "man",
            "old woman": "woman", "old man": "man",
            "cat": "cat", "kitty": "cat",
        }

        for g in detected_generic:
            role = g["role"]
            role_g = role_gender_map.get(role.lower(), "")
            opts = _pick_options(role_g)

            # 当前选择：先看 override，否则用 detected 的 default_key + age
            current = overrides.get(role, "")
            if not current:
                # 用 auto 推断
                from ip_library import resolve_generic_role
                ip = resolve_generic_role(role, target_age)
                current = ip.key if ip else "__skip__"

            keys_list = [o[0] for o in opts]
            labels_list = [o[1] for o in opts]
            default_idx = keys_list.index(current) if current in keys_list else 0

            sel = st.selectbox(
                f"故事里的 **{role}** → 套用谁？",
                options=range(len(opts)),
                index=default_idx,
                format_func=lambda i: labels_list[i],
                key=f"generic_pick_{role}",
                help=g.get("note", ""),
            )
            chosen_key = keys_list[sel]
            if chosen_key != "__skip__":
                new_overrides[role] = chosen_key

        st.session_state["generic_overrides"] = new_overrides


def _generate_worksheet_preview() -> None:
    """v1.9：基于当前编辑过的题目，立即生成一份 worksheet.pptx 初稿供老师下载预览。

    复用已生图的 page_xx.png 作为 Sentence 页/Match 页的图片来源；如果还没生图，用占位图。
    """
    ec = st.session_state.extracted
    outline: BookOutline = st.session_state.outline
    if not ec or not outline:
        st.error("请先点 AI 抽取按钮。")
        return
    apply_extracted_to_outline(outline, ec)
    rqc = int(st.session_state.get("ws_reading_q_count", 4))
    attach_worksheet_questions(outline, ec.worksheet_questions, reading_q_count=rqc)

    run_dir, img_dir, name_prefix = _ensure_run_dir()
    # 已生图就按 index 排序复用；没生图就传空列表（builder 用占位）
    image_results = st.session_state.get("image_results") or {}
    image_paths: list[Path] = []
    for idx in sorted(image_results.keys()):
        p = image_results[idx].get("path")
        if p and Path(p).exists():
            image_paths.append(Path(p))

    draft_path = run_dir / f"{name_prefix}_Worksheet_DRAFT.pptx"
    try:
        with st.spinner("正在生成 Worksheet 初稿..."):
            build_worksheet(
                outline,
                draft_path,
                image_paths=image_paths or None,
            )
    except Exception as e:
        st.error(f"Worksheet 初稿生成失败：{e}")
        return
    st.session_state.ws_draft_path = str(draft_path)
    st.toast("✅ Worksheet 初稿已生成，下方可下载", icon="✅")


def _rebuild_all_cn_prompts() -> None:
    """v1.9：用最新 outline + ec.pages 重生所有页的中文 prompt（保留 must_include）。"""
    ec = st.session_state.extracted
    outline: BookOutline = st.session_state.outline
    if not ec or not outline:
        return
    # 把 UI 上改过的 text / scene 应用到 outline
    apply_extracted_to_outline(outline, ec)
    ip_age = outline.ip_age or resolve_ip_age(outline.level)
    page_prompts = st.session_state.get("page_prompts") or {}
    cast_pool = st.session_state.get("story_cast_pool") or None
    generic_overrides = st.session_state.get("generic_overrides") or None
    for page in outline.pages:
        built = build_cn_page_prompt(
            page, outline, ip_age,
            cast_pool=cast_pool, generic_overrides=generic_overrides,
        )
        prev_must = (page_prompts.get(page.index) or {}).get("must_include", "")
        page_prompts[page.index] = {
            "positive": built.positive,     # v3: 正向
            "negative": built.negative,     # v3: 反向
            "prompt": built.prompt,         # v3: 拼接后兜底（向后兼容）
            "references": [str(r) for r in built.references],
            "must_include": prev_must,
            "label": page.label,
            "display_name": page_display_name(page.index),
        }
    st.session_state.page_prompts = page_prompts


def _render_unified_page_panel() -> None:
    """v1.9：合并面板 — 每页一张卡片，包含：
      ① 故事文本（可改）
      ② AI 场景描述（可改）
      ③ 配图 prompt（中文，可改）
      ④ 必须出现（可加）
      ⑤ 参考图 + Shot + Expression

    页编号约定：Cover / Page 2 / Page 3 ... / Page 8（无 Page 1，Cover 即第 1 页印刷面）。
    """
    ec = st.session_state.extracted
    page_prompts = st.session_state.page_prompts

    with st.expander(
        f"🖼️ 每页详情（共 {len(page_prompts)} 页 — 强烈建议先审一遍再生图）",
        expanded=True,
    ):
        st.caption(
            "💡 一张卡片 = 一页绘本。改动顺序：先看 ① 故事原文 → 改 ② 场景描述 → 看 ③ 中文 prompt 是否到位 → "
            "在 ④ 必须出现 里补关键角色/道具（会追加到 prompt 末尾）。  \n"
            "📌 **页编号约定**：**Cover** 就是封面（印刷第 1 页）；**Page 2** 是故事第 1 句对应的图（印刷第 2 页），以此类推到 Page 8。**没有 Page 1**。"
        )

        ec_pages_by_idx = {p.get("index"): p for p in (ec.pages or [])}

        for idx in sorted(page_prompts.keys()):
            entry = page_prompts[idx]
            display_name = entry.get("display_name") or page_display_name(idx)
            refs = entry.get("references", [])
            ref_count = len(refs)
            ref_badge = f"🖼️ {ref_count} 张参考图" if ref_count else "⚠️ 无参考图"

            ec_page = ec_pages_by_idx.get(idx) or {}
            label_kind = "封面" if idx == 0 else "故事页"

            st.markdown(f"#### {display_name} · {label_kind} · {ref_badge}")

            # 第 1 行：故事文本 + 中文画面描述（scene_cn 是 prompt 的主体）
            c1, c2 = st.columns([1, 1])
            with c1:
                st.caption("① 故事原文（英文）")
                new_text = st.text_area(
                    f"text_{idx}",
                    value=ec_page.get("text", ""),
                    height=140,
                    key=f"uni_text_{idx}",
                    label_visibility="collapsed",
                )
                if new_text != ec_page.get("text", ""):
                    ec_page["text"] = new_text
            with c2:
                st.caption("② 中文画面描述 scene_cn（AI 生成 → 喂给画图模型，最关键）")
                new_scene_cn = st.text_area(
                    f"scene_cn_{idx}",
                    value=ec_page.get("scene_cn", ""),
                    height=140,
                    key=f"uni_scene_cn_{idx}",
                    label_visibility="collapsed",
                    placeholder=(
                        "AI 应该生成 120-220 字连贯描述：\n"
                        "主体（人物+具体外观）+ 动作（具体动词姿势）+ 环境（可见物品）+ 氛围（光照）\n"
                        "例：教室一角，12 岁 Anna 戴琥珀色细框眼镜...坐在木课桌后双手颤抖..."
                    ),
                )
                if new_scene_cn != ec_page.get("scene_cn", ""):
                    ec_page["scene_cn"] = new_scene_cn

            # 第 2 行：v3 正向 prompt + 反向 prompt + 必须出现
            c3a, c3b, c4 = st.columns([3, 2, 2])
            with c3a:
                st.caption("③✅ 正向 Prompt（火山风单段流畅自然语言，画什么）")
                # 兼容老 session：如果 entry 只有 "prompt" 没有 "positive"，把它当 positive
                cur_pos = entry.get("positive", entry.get("prompt", ""))
                new_pos = st.text_area(
                    f"positive_{idx}",
                    value=cur_pos,
                    height=240,
                    key=f"uni_pos_{idx}",
                    label_visibility="collapsed",
                )
                entry["positive"] = new_pos
            with c3b:
                st.caption("③❌ 反向 Prompt（不要什么）")
                cur_neg = entry.get("negative", "")
                new_neg = st.text_area(
                    f"negative_{idx}",
                    value=cur_neg,
                    height=240,
                    key=f"uni_neg_{idx}",
                    label_visibility="collapsed",
                    placeholder=(
                        "本页禁忌（每行一条），例如：\n"
                        "Tommy 戴眼镜\n"
                        "Mia 散发\n"
                        "除 Anna 外任何人穿绿色\n"
                        "画面出现宠物（本页不应有）"
                    ),
                )
                entry["negative"] = new_neg
            with c4:
                st.caption("④ 必须出现（追加到正向末尾，每行一条）")
                entry["must_include"] = st.text_area(
                    f"must_{idx}",
                    value=entry.get("must_include", ""),
                    height=180,
                    key=f"uni_must_{idx}",
                    label_visibility="collapsed",
                    placeholder=(
                        "（可选）写明必须画上的元素，例如：\n"
                        "Anna 戴琥珀色细框眼镜\n"
                        "Anna 黑色双低马尾，每条垂在肩前\n"
                        "桌上有一摞 5 本课本\n"
                        "教室背景：绿色黑板 + 几张课桌"
                    ),
                )
                # Shot + 参考图
                bc1, bc2 = st.columns([1, 1])
                with bc1:
                    cur_shot = ec_page.get("shot", "medium") or "medium"
                    new_shot = st.selectbox(
                        "镜头",
                        SHOT_OPTIONS,
                        index=max(0, SHOT_OPTIONS.index(cur_shot) if cur_shot in SHOT_OPTIONS else 1),
                        key=f"uni_shot_{idx}",
                    )
                    if new_shot != cur_shot:
                        ec_page["shot"] = new_shot
                with bc2:
                    st.text_input(
                        "表情",
                        value=ec_page.get("expression", ""),
                        key=f"uni_expr_{idx}",
                        on_change=None,
                    )
                if refs:
                    st.caption(
                        "🎨 参考图: " + " | ".join(Path(r).name for r in refs[:4])
                    )

            st.divider()


def _render_editable_preview() -> None:
    ec = st.session_state.extracted
    outline: BookOutline = st.session_state.outline

    st.divider()
    st.subheader("✏️  AI 抽取结果（请核对/微调）")

    # 词表
    with st.expander("📚 词汇表 / 语法 / 拼读 / 读者类型", expanded=True):
        col1, col2 = st.columns(2)
        is_dual = outline.is_dual_vocab_level
        with col1:
            if is_dual:
                ec.mastery = _csv_input("Mastery（3-4 词，lemma 原型小写）",
                                         ec.mastery, key="mastery")
                ec.exposure = _csv_input("Exposure（3-4 词，lemma 原型小写）",
                                          ec.exposure, key="exposure")
            else:
                ec.vocabulary = _csv_input("Vocabulary（4 词，lemma 原型小写）",
                                            ec.vocabulary, key="vocab")
        with col2:
            ec.grammar_focus = st.text_input(
                "Grammar Focus", value=ec.grammar_focus, key="grammar")
            ec.phonics = st.text_input(
                "Phonics", value=ec.phonics, key="phonics")
            ec.reader_type = st.text_input(
                "Reader Type", value=ec.reader_type, key="reader")
            ec.word_count = st.number_input(
                "Word Count", min_value=0, value=int(ec.word_count or 0), key="wc")

    # v2.0：unified_page_panel 已被 Step 4 + Step 5 取代，这里不再渲染

    # RR 题目
    with st.expander("📝 Reading Report 阅读表达题（按 Level 题量梯度）", expanded=False):
        for i, q in enumerate(ec.rr_questions):
            star = "⭐" * int(q.get("stars") or 1)
            cols = st.columns([10, 2])
            with cols[0]:
                q["q"] = st.text_input(
                    f"Q{i + 1} {star}", value=q.get("q", ""),
                    key=f"rr_q_{i}",
                )
            with cols[1]:
                if q.get("page") is None:
                    st.caption("(开放题)")
                    q["page"] = None
                else:
                    page_val = max(2, int(q.get("page") or 2))
                    q["page"] = st.number_input(
                        "P#", min_value=2, max_value=8, value=page_val,
                        key=f"rr_p_{i}", label_visibility="collapsed",
                        help="P1 = 封面，故事页是 P2-P8",
                    )

    # Worksheet 题目
    with st.expander("📋 Worksheet 6 道题（题型 + 题项 JSON）", expanded=False):
        st.caption("题项是 JSON 格式（list of dict），如需自由编辑可直接改下面文本框。")

        # v2.0：Reading MC 页题数选择（4/6/8）
        cur_rqc = int(st.session_state.get("ws_reading_q_count", 4))
        st.session_state["ws_reading_q_count"] = st.select_slider(
            "📖 Reading MC 页题量（影响 Worksheet 第 4 页 reading 题量）",
            options=[4, 6, 8],
            value=cur_rqc,
            help=(
                "官方 L5-1 Worksheet 标准是 8 题。"
                "如果题目太多挤不下，可降到 6 或 4（默认 4）。"
            ),
            key="ws_rqc_slider",
        )

        # v1.9：初稿预览按钮（即时生成 worksheet.pptx 让老师看）
        st.markdown("---")
        col_pv1, col_pv2 = st.columns([3, 2])
        with col_pv1:
            st.caption(
                "👀 **生成前先看初稿**：点右边按钮会立即用当前编辑的题目生成一份 worksheet.pptx，"
                "你可以下载下来在 PowerPoint 里查看版式/字号/题目效果，确认无误再去步骤 C 组装。"
            )
        with col_pv2:
            if st.button(
                "👀 生成 Worksheet 初稿（预览）",
                key="ws_preview_btn",
                width="stretch",
            ):
                _generate_worksheet_preview()

        # 初稿下载链接
        ws_draft = st.session_state.get("ws_draft_path")
        if ws_draft and Path(ws_draft).exists():
            st.success(f"✅ 初稿已生成：`{Path(ws_draft).name}`（约 {Path(ws_draft).stat().st_size//1024} KB）")
            with open(ws_draft, "rb") as f:
                st.download_button(
                    "⬇️ 下载 Worksheet 初稿 PPTX 查看",
                    data=f.read(),
                    file_name=Path(ws_draft).name,
                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    key="ws_draft_dl",
                )

        st.markdown("---")
        # v3.3 过程性出题：难度梯度说明（按 Level 自动匹配）
        _render_ws_difficulty_header(outline.level)
        st.caption(
            "💡 固定结构 **2 词汇 + 2 句子 + 2 阅读**。每道题可：① 换题型/难度 ② 🤖 AI 重出（紧扣故事+级别）"
            "③ 手动改 word / 句子 / 选项。改完点上方「👀 生成 Worksheet 初稿」看效果。"
        )
        for i, ws in enumerate(ec.worksheet_questions):
            qtype = (ws.get("type") or "").lower()
            section = _WS_SECTION_BY_SLOT[i] if i < len(_WS_SECTION_BY_SLOT) else "reading"
            sec_label = {"vocab": "📖 词汇", "sentence": "✍️ 句子", "reading": "📚 阅读"}[section]
            with st.container(border=True):
                st.markdown(f"**Activity {i + 1} · {sec_label} · {QUESTION_TITLES.get(qtype, qtype)}**")

                # ① 题型 / 难度切换（限定在本 section 内，保证版式不乱）
                tcol, bcol = st.columns([3, 2])
                with tcol:
                    _render_ws_type_switch(ws, i, section)
                with bcol:
                    st.markdown("&nbsp;", unsafe_allow_html=True)
                    if st.button(
                        "🤖 AI 重出这道题",
                        key=f"ws_regen_{i}",
                        width="stretch",
                        help="让 AI 按当前题型 + 故事内容 + 本级别难度，重新生成这道题的题项",
                    ):
                        _regenerate_one_worksheet_question(i)
                        st.rerun()

                # ② 结构化题项编辑
                _render_ws_item_editor(ws, i)


# ============================================================================
# v3.3 过程性出题：题型切换 / 单题 AI 重出 / 难度梯度说明
# ============================================================================

# 6 道题固定结构：2 词汇 + 2 句子 + 2 阅读
_WS_SECTION_BY_SLOT = ["vocab", "vocab", "sentence", "sentence", "reading", "reading"]

# 每个 section 允许切换的题型（限定在 builder 能正确排版的范围内）
# (legacy type id, 中文/英文短标签, 难度星级)
_WS_TYPE_CHOICES: dict[str, list[tuple[str, str, int]]] = {
    "vocab": [
        ("color_match", "Color the Words", 1),
        ("circle_match", "Match Pictures", 1),
        ("word_to_pic", "Word ↔ Picture", 1),
        ("fill_blank_simple", "Fill Blanks (simple)", 1),
        ("unscramble", "Unscramble Letters", 2),
        ("fill_blank", "Fill Blanks", 2),
        ("emotion_fill", "Choose the Emotion", 3),
        ("fill_blank_advanced", "Fill Blanks (advanced)", 3),
        ("match_definition", "Match Word ↔ Definition", 3),
    ],
    "sentence": [
        ("true_false_simple", "True / False (simple)", 1),
        ("word_order_simple", "Word Order (simple)", 1),
        ("true_false", "True / False", 2),
        ("word_order", "Sentence Order", 2),
        ("fill_blank", "Complete the Sentence", 2),
        ("story_sequence", "Story Sequence", 3),
        ("rewrite_tense", "Rewrite (tense)", 3),
        ("rewrite_voice", "Rewrite (voice/style)", 3),
    ],
    "reading": [
        ("draw_favorite", "Draw Favorite Page", 1),
        ("personal_simple", "About Me", 1),
        ("plot_chart", "Story Chart", 2),
        ("inference", "Read & Infer (MCQ)", 3),
        ("plot_chart_pbl", "Plot & Reflection", 3),
        ("compare_contrast", "Compare & Contrast", 3),
        ("personal_write", "Write About Yourself", 3),
        ("open_ended_pbl", "Project Response", 3),
        ("essay_short", "Short Essay", 3),
        ("research_pbl", "Mini Research", 3),
    ],
}


def _render_ws_difficulty_header(level: str) -> None:
    """显示本 Level 的难度梯度（星级分布），让老师知道难度是按级别自动匹配的。"""
    try:
        from worksheet_question_types import _DIFFICULTY_PROFILE
        key = str(level or "5").strip().lower().lstrip("l").strip()
        if "smart" in str(level).lower():
            key = "smart"
        if key not in _DIFFICULTY_PROFILE:
            key = "5"
        n1, n2, n3 = _DIFFICULTY_PROFILE[key]
        st.info(
            f"🎚️ **Level {level} 难度梯度**：6 道题里约 "
            f"**{n1} 道 ⭐**（基础识记） · **{n2} 道 ⭐⭐**（理解运用） · **{n3} 道 ⭐⭐⭐**（推理/写作）。"
            "低级别更偏图/识记，高级别更偏推理/写作 —— 切题型时括号里的星级就是难度。"
        )
    except Exception:
        pass


def _render_ws_type_switch(ws: dict, idx: int, section: str) -> None:
    """本 section 内切换题型（带难度星级），换型时同步 title/instruction。"""
    choices = list(_WS_TYPE_CHOICES.get(section, []))
    cur_type = (ws.get("type") or "").lower()
    ids = [c[0] for c in choices]
    if cur_type and cur_type not in ids:
        # 当前题型不在候选里（兼容旧数据）→ 补进去当首选
        choices = [(cur_type, QUESTION_TITLES.get(cur_type, cur_type.replace("_", " ").title()), 2)] + choices
        ids = [c[0] for c in choices]

    labels = [f"{lbl} ({'⭐' * stars})" for _tid, lbl, stars in choices]
    cur_index = ids.index(cur_type) if cur_type in ids else 0
    sel = st.selectbox(
        "题型 / 难度",
        options=list(range(len(choices))),
        index=cur_index,
        format_func=lambda k: labels[k],
        key=f"ws_type_{idx}",
        help="只在本类（词汇/句子/阅读）里换，保证 Worksheet 版式不乱。括号内为难度。",
    )
    new_type = ids[sel]
    if new_type != cur_type:
        ws["type"] = new_type
        ws["title"] = QUESTION_TITLES.get(new_type, new_type.replace("_", " ").title())
        ws["instruction"] = QUESTION_INSTRUCTIONS.get(new_type, "")
        # 换题型后建议点「🤖 AI 重出这道题」重新出题项


def _regenerate_one_worksheet_question(idx: int) -> None:
    """逐题 AI 重出：用故事原文 + 当前题型 + 级别，重新生成这道题的题项。"""
    ec = st.session_state.extracted
    outline: BookOutline = st.session_state.outline
    if not ec or idx >= len(ec.worksheet_questions):
        return
    ws = ec.worksheet_questions[idx]
    qtype = (ws.get("type") or "").lower()
    raw_story = "\n".join((p.get("text") or "") for p in (ec.pages or []) if p.get("text"))
    title = getattr(outline, "title", "") or ""
    level = getattr(outline, "level", "") or "5"
    theme = getattr(outline, "theme", "") or ""
    cefr = getattr(outline, "cefr", "") or ""
    with st.spinner(f"🤖 正在按「{QUESTION_TITLES.get(qtype, qtype)}」+ 故事 + Level {level} 重出这道题..."):
        try:
            new_q = generate_one_worksheet_question(
                qtype, raw_story, title, level, cefr=cefr, theme=theme,
            )
            ec.worksheet_questions[idx] = new_q
            st.session_state.extracted = ec
            st.toast("✅ 已重出这道题，下面可继续微调。", icon="🤖")
        except Exception as e:  # noqa: BLE001
            st.error(f"重出失败：{e}")


def _render_ws_item_editor(ws: dict, idx: int) -> None:
    """v1.9：按 worksheet 题型展开成结构化输入（替代原 JSON 编辑器）。

    题型 → 结构：
      match_definition → 5 行 (word, def)
      fill_blank / fill_blank_advanced / emotion_fill → 5 行 (sentence, answer)
      true_false → 4 行 (statement, T/F)
      inference / reading_mc → 4 行 (q, options[3], correct)
      unscramble → 5 行 (scrambled, answer)
      其他 → 简化的 items JSON
    """
    qtype = (ws.get("type") or "").lower()
    items = ws.get("items") or []

    if qtype == "match_definition":
        st.caption("每行：单词 → 词典定义（小学生能看懂的简单解释）")
        new_items = []
        for j, it in enumerate(items[:5]):
            c1, c2 = st.columns([1, 4])
            with c1:
                w = st.text_input(f"word_{idx}_{j}", value=it.get("word", ""),
                                   key=f"ws{idx}_w{j}", label_visibility="collapsed")
            with c2:
                d = st.text_input(f"def_{idx}_{j}",
                                   value=it.get("def") or it.get("definition", ""),
                                   key=f"ws{idx}_d{j}", label_visibility="collapsed",
                                   placeholder="feeling worried about something that will happen")
            if w.strip():
                new_items.append({"word": w.strip(), "def": d.strip()})
        ws["items"] = new_items

    elif qtype in ("fill_blank", "fill_blank_simple", "fill_blank_advanced", "emotion_fill"):
        st.caption("每行：句子（用 ____ 留空） → 答案")
        new_items = []
        for j, it in enumerate(items[:5]):
            c1, c2 = st.columns([4, 1])
            with c1:
                s = st.text_input(f"sent_{idx}_{j}", value=it.get("sentence", ""),
                                   key=f"ws{idx}_s{j}", label_visibility="collapsed",
                                   placeholder="Anna ____ on her first day.")
            with c2:
                a = st.text_input(f"ans_{idx}_{j}", value=it.get("answer", ""),
                                   key=f"ws{idx}_a{j}", label_visibility="collapsed",
                                   placeholder="felt nervous")
            if s.strip():
                new_items.append({"sentence": s.strip(), "answer": a.strip()})
        ws["items"] = new_items
        ws["extra"] = st.text_input(
            f"词库 extra_{idx}", value=ws.get("extra", ""), key=f"ws{idx}_e",
            placeholder="逗号分隔的词库，如：nervous, shared, helped, listened",
        )

    elif qtype in ("true_false", "true_false_simple"):
        st.caption("每行：陈述句 + T/F")
        new_items = []
        for j, it in enumerate(items[:4]):
            c1, c2 = st.columns([5, 1])
            with c1:
                s = st.text_input(f"stmt_{idx}_{j}", value=it.get("statement", ""),
                                   key=f"ws{idx}_st{j}", label_visibility="collapsed",
                                   placeholder="Anna shared pencils with a quiet boy.")
            with c2:
                a = st.selectbox(f"tf_{idx}_{j}", ["T", "F"],
                                  index=0 if (it.get("answer") or "T").upper() == "T" else 1,
                                  key=f"ws{idx}_tf{j}", label_visibility="collapsed")
            if s.strip():
                new_items.append({"statement": s.strip(), "answer": a})
        ws["items"] = new_items

    elif qtype in ("inference", "reading_mc"):
        st.caption("每行：问题 + 3 个选项 + 正确答案 (A/B/C)")
        new_items = []
        for j, it in enumerate(items[:4]):
            q = st.text_input(f"infq_{idx}_{j}", value=it.get("q") or it.get("question", ""),
                               key=f"ws{idx}_q{j}",
                               label_visibility="visible",
                               placeholder="Why did Anna help pick up the books?")
            opts = list(it.get("options") or ["", "", ""])
            while len(opts) < 3:
                opts.append("")
            cc1, cc2, cc3, cc4 = st.columns([3, 3, 3, 1])
            with cc1:
                opts[0] = st.text_input(f"o0_{idx}_{j}", value=opts[0],
                                          key=f"ws{idx}_o0{j}", label_visibility="collapsed",
                                          placeholder="A. She wanted to be kind.")
            with cc2:
                opts[1] = st.text_input(f"o1_{idx}_{j}", value=opts[1],
                                          key=f"ws{idx}_o1{j}", label_visibility="collapsed",
                                          placeholder="B. The teacher told her.")
            with cc3:
                opts[2] = st.text_input(f"o2_{idx}_{j}", value=opts[2],
                                          key=f"ws{idx}_o2{j}", label_visibility="collapsed",
                                          placeholder="C. She wanted the books.")
            with cc4:
                cur = int(it.get("correct", 0))
                cur = max(0, min(2, cur))
                ans = st.selectbox(f"co_{idx}_{j}", ["A", "B", "C"], index=cur,
                                    key=f"ws{idx}_co{j}", label_visibility="collapsed")
            if q.strip():
                new_items.append({
                    "q": q.strip(),
                    "options": [o.strip() for o in opts],
                    "correct": {"A": 0, "B": 1, "C": 2}[ans],
                })
        ws["items"] = new_items

    elif qtype == "unscramble":
        st.caption("每行：打散字母 → 正确答案")
        new_items = []
        for j, it in enumerate(items[:5]):
            c1, c2 = st.columns([2, 2])
            with c1:
                sc = st.text_input(f"sc_{idx}_{j}", value=it.get("scrambled", ""),
                                    key=f"ws{idx}_sc{j}", label_visibility="collapsed",
                                    placeholder="o c k l")
            with c2:
                a = st.text_input(f"sca_{idx}_{j}", value=it.get("answer", ""),
                                    key=f"ws{idx}_sca{j}", label_visibility="collapsed",
                                    placeholder="lock")
            if sc.strip():
                new_items.append({"scrambled": sc.strip(), "answer": a.strip()})
        ws["items"] = new_items

    else:
        # 兜底（compare_contrast、plot_chart、写作类等）：保留 JSON 但收起
        with st.expander("📝 items JSON（高级题型用 JSON 编辑）", expanded=False):
            import json
            items_str = st.text_area(
                f"items_json_{idx}",
                value=json.dumps(items, ensure_ascii=False, indent=2),
                height=120, key=f"ws_json_{idx}",
                label_visibility="collapsed",
            )
            try:
                ws["items"] = json.loads(items_str)
            except json.JSONDecodeError:
                st.warning("items JSON 解析失败，保留旧值")
        ws["extra"] = st.text_input(
            f"extra_{idx}", value=ws.get("extra", ""), key=f"ws_e_{idx}",
            placeholder="题目附加说明（如反思问题、写作 prompt）",
        )


def _csv_input(label: str, words: list[str], *, key: str) -> list[str]:
    raw = st.text_input(label, value=", ".join(words or []), key=key)
    return [w.strip().lower() for w in raw.split(",") if w.strip()]


def _name_prefix(outline: BookOutline) -> str:
    """新规范：Level X_BookXX_品类_标题  →  品类 + 后缀由调用方拼接。

    返回去除非法字符（/\\:*?"<>| 及空格替换为下划线）的前缀串。
    """
    level_s = outline.level or "1"
    if "smart" in level_s.lower():
        lvl_part = "Smart"
    else:
        digits = "".join(ch for ch in level_s if ch.isdigit())
        lvl_part = f"Level {digits or '1'}"
    book_s = (outline.book_number or "01").strip()
    if not book_s.lower().startswith("book"):
        book_s = f"Book{book_s}"
    title = re.sub(r'[\\/:*?"<>|]', "_", (outline.title or "Untitled"))
    title = re.sub(r"_+", "_", title).strip("_ ")
    return f"{lvl_part}_{book_s}_{title}"


# =============================== 生成器 ===============================
def _ensure_run_dir() -> tuple[Path, Path, str]:
    """复用同一次 run 目录（生图 + 组装文档共用），避免每次重新生图都换路径。"""
    outline: BookOutline = st.session_state.outline
    if not st.session_state.get("run_dir"):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = OUTPUTS_DIR / f"{outline.slug}_{timestamp}"
        st.session_state.run_dir = str(run_dir)
        st.session_state.run_name_prefix = _name_prefix(outline)
    run_dir = Path(st.session_state.run_dir)
    img_dir = run_dir / "images"
    run_dir.mkdir(parents=True, exist_ok=True)
    img_dir.mkdir(parents=True, exist_ok=True)
    return run_dir, img_dir, st.session_state.run_name_prefix


def _build_final_prompt_for_page(page, outline: BookOutline, ip_age: int) -> tuple[str, list[Path]]:
    """v3.1：组装最终 prompt =
       (Step3 风格设定正向 + page positive + 教师必须出现)
       + ==请勿出现==
       + (page negative + Step3 风格设定反向)

    优先用老师在 UI 上编辑过的正向/反向；否则用 build_cn_page_prompt 现场生成。
    Step3 的全局风格设定如果存在，会自动**前置**到正向 + **追加**到反向。
    """
    from cn_prompt_builder import BuiltPromptCN

    style_cfg = st.session_state.get("style_config") or {}
    style_blocks = _format_style_config_preview(style_cfg) if style_cfg else {
        "positive_block": "", "negative_block": ""
    }
    style_pos = style_blocks.get("positive_block", "").strip()
    style_neg = style_blocks.get("negative_block", "").strip()

    page_prompts = st.session_state.get("page_prompts") or {}
    edited = page_prompts.get(page.index)
    if edited:
        positive = edited.get("positive") or edited.get("prompt") or ""
        negative = edited.get("negative") or ""

        # v3.2 A 层：注入 page_constraints（姿势/情绪/视线/位置/互动/文字位置/焦点）
        pc_block = _format_page_constraints(edited.get("page_constraints"))
        if pc_block:
            positive = positive.rstrip() + "\n\n【A 层 · 本页人物状态约束】\n" + pc_block

        must_inc = (edited.get("must_include") or "").strip()
        if must_inc:
            positive = (
                positive.rstrip()
                + "\n\n【教师锁定 · 必须出现】\n"
                + must_inc
            )
        refs = [Path(r) for r in edited.get("references", []) if r]
    else:
        cast_pool = st.session_state.get("story_cast_pool") or None
        generic_overrides = st.session_state.get("generic_overrides") or None
        built = build_cn_page_prompt(
            page, outline, ip_age,
            cast_pool=cast_pool, generic_overrides=generic_overrides,
        )
        positive = built.positive if hasattr(built, "positive") else built.prompt
        negative = built.negative if hasattr(built, "negative") else ""
        refs = built.references

    # v3.1 注入 Step 3 风格设定
    if style_pos:
        positive = f"【全局风格设定】\n{style_pos}\n\n" + positive
    if style_neg:
        negative = (negative.rstrip() + "\n" if negative else "") + style_neg

    # v3.2 反馈学习的负向（来自每页生图后的问题反馈面板）
    if edited:
        learned_neg = (edited.get("learned_negatives") or "").strip()
        if learned_neg:
            negative = (negative.rstrip() + "\n" if negative else "") + learned_neg

    # v3.3：主角恒为「首位参考图」。gpt-image-2 只吃单张参考，必须保证它是主角，
    # 否则主角（尤其用 she/he 代称、本句没点名时）会跳帧。
    prot_ref = _book_protagonist_ref(outline, ip_age)
    if prot_ref is not None and page.page_type != "cover":
        refs = [Path(r) for r in refs]
        if prot_ref in refs:
            refs.remove(prot_ref)
        refs.insert(0, prot_ref)

    final_prompt = BuiltPromptCN.join(positive, negative)
    return final_prompt, refs


@st.cache_data(show_spinner=False)
def _book_protagonist_ref_cached(cast_keys: tuple[str, ...], all_text: str, title: str, ip_age: int) -> str:
    """识别全书主角的参考图路径（字符串）。主角 = cast_pool 里 kind=protagonist
    且名字在标题/正文出现最多的那个。返回 '' 表示无。
    """
    from ip_library import get_ip
    best_key, best_score = "", -1
    text_low = (title + " " + all_text).lower()
    for key in cast_keys:
        ip = get_ip(key)
        if not ip or ip.kind != "protagonist":
            continue
        name = ip.name_base.lower()
        score = text_low.count(name)
        if score > best_score:
            best_key, best_score = key, score
    if not best_key:
        return ""
    ip = get_ip(best_key)
    return str(ip.image_path) if ip and ip.image_path else ""


def _book_protagonist_ref(outline: BookOutline, ip_age: int) -> Path | None:
    cast_pool = st.session_state.get("story_cast_pool") or []
    if not cast_pool:
        return None
    all_text = " ".join((p.text or "") for p in outline.pages)
    p = _book_protagonist_ref_cached(tuple(cast_pool), all_text, outline.title or "", ip_age)
    return Path(p) if p else None


def _run_image_generation_only(mock_images: bool) -> None:
    """v1.8.3 步骤 A：只生图，不组装文档。生成完把结果存到 session_state.image_results 供审核。"""
    ec = st.session_state.extracted
    outline: BookOutline = st.session_state.outline
    apply_extracted_to_outline(outline, ec)
    attach_rr_questions(outline, ec.rr_questions)
    rqc = int(st.session_state.get("ws_reading_q_count", 4))
    attach_worksheet_questions(outline, ec.worksheet_questions, reading_q_count=rqc)

    run_dir, img_dir, _ = _ensure_run_dir()
    ip_age = outline.ip_age or resolve_ip_age(outline.level)

    progress = st.progress(0, "Initializing image generation...")
    status = st.empty()

    n = len(outline.pages)
    image_results: dict[int, dict] = st.session_state.get("image_results") or {}

    for i, page in enumerate(outline.pages):
        display_name = page_display_name(page.index)
        progress.progress(i / n, f"绘图 {display_name} ({page.label})...")
        status.text(f"图 {i + 1}/{n}: {display_name} · {page.label}")
        final_prompt, refs = _build_final_prompt_for_page(page, outline, ip_age)
        prev = image_results.get(page.index, {})
        version = int(prev.get("version", 0)) + 1
        dest = img_dir / f"page_{page.index:02d}_v{version}.png"
        try:
            generate_image(
                prompt=final_prompt, dest=dest,
                references=refs, mock=mock_images, label=page.label,
            )
        except Exception as e:
            st.error(f"{display_name} 生图失败：{e}")
            return
        image_results[page.index] = {
            "path": str(dest),
            "prompt": final_prompt,
            "label": page.label,
            "version": version,
            "locked": prev.get("locked", False),  # 重生时保留锁定状态
        }

    st.session_state.image_results = image_results
    progress.progress(1.0, "✅ 8 张图全部生成")
    status.empty()
    st.success(
        f"✅ 已生成 {n} 张图到 `{img_dir}`。"
        f"下方按页审核 —— 不满意的可点 🔁 单张重生；满意的勾 ✅ 锁定。"
    )


def _regenerate_single_image(page_index: int, mock_images: bool) -> None:
    """单张重生（用最新的 prompt + must_include）。"""
    outline: BookOutline = st.session_state.outline
    ip_age = outline.ip_age or resolve_ip_age(outline.level)
    _, img_dir, _ = _ensure_run_dir()

    page = next((p for p in outline.pages if p.index == page_index), None)
    if not page:
        st.error(f"找不到页 index={page_index}")
        return
    display_name = page_display_name(page_index)

    final_prompt, refs = _build_final_prompt_for_page(page, outline, ip_age)
    image_results = st.session_state.image_results
    prev = image_results.get(page_index, {})
    version = int(prev.get("version", 0)) + 1
    dest = img_dir / f"page_{page_index:02d}_v{version}.png"
    with st.spinner(f"重新生成 {display_name} (v{version})..."):
        try:
            generate_image(
                prompt=final_prompt, dest=dest,
                references=refs, mock=mock_images, label=page.label,
            )
        except Exception as e:
            st.error(f"{display_name} 重生失败：{e}")
            return
    image_results[page_index] = {
        "path": str(dest),
        "prompt": final_prompt,
        "label": page.label,
        "version": version,
        "locked": False,
    }
    st.session_state.image_results = image_results
    st.success(f"✅ {display_name} 已重新生成（v{version}）")


def _render_image_review_panel(mock_imgs: bool) -> None:
    """生图后展示 8 张缩略图，每张可：🔁 重生 / ✏️ 改 prompt 重生 / ✅ 锁定。"""
    image_results = st.session_state.image_results
    n_total = len(image_results)
    n_locked = sum(1 for r in image_results.values() if r.get("locked"))
    st.caption(
        f"已生成 {n_total} 张图，已锁定 ✅ {n_locked} 张。"
        "建议每张都点 🔁 重生几次直到满意，再勾 ✅ 锁定，所有图锁定后再组装文档。"
    )

    # v3.3 图在前：每页一行，左图（大）右信息（故事原文 / 剧情要点 / 操作 / 提示词折叠）
    outline = st.session_state.get("outline")
    pages_by_idx = {p.index: p for p in (outline.pages if outline else [])}

    indices = sorted(image_results.keys())
    for idx in indices:
        entry = image_results[idx]
        page = pages_by_idx.get(idx)
        display_name = page_display_name(idx)
        lock_emoji = "🔒 已锁定" if entry.get("locked") else ""
        st.markdown(
            f"#### {display_name} · {entry.get('label', '')} · v{entry.get('version', 1)}　{lock_emoji}"
        )

        c_img, c_info = st.columns([3, 2])
        with c_img:
            img_path = entry.get("path")
            if img_path and Path(img_path).exists():
                try:
                    st.image(img_path, width="stretch")
                except Exception as e:
                    st.warning(f"图片无法显示：{e}")
            else:
                st.caption("⚠️ 图片不存在")

        with c_info:
            # 图在前，文字在旁：该页故事原文 + 剧情要点
            story_text = (page.text or "").strip() if page else ""
            plot = (getattr(page, "scene_cn", "") or "").strip() if page else ""
            if story_text:
                st.markdown(f"**📖 该页故事**\n\n{story_text}")
            else:
                st.markdown("**📖 该页**：封面")
            if plot:
                st.caption(f"🎬 剧情要点：{plot}")

            bcol1, bcol2 = st.columns(2)
            with bcol1:
                if st.button(
                    "🔁 重生",
                    key=f"regen_btn_{idx}",
                    width="stretch",
                    help="用当前 prompt 重新生成一次（保留参考图）",
                ):
                    _regenerate_single_image(idx, mock_imgs)
                    st.rerun()
            with bcol2:
                new_lock = st.checkbox(
                    "✅ 锁定",
                    value=bool(entry.get("locked")),
                    key=f"lock_chk_{idx}",
                    help="勾上表示这张图满意，组装时用它",
                )
                if new_lock != bool(entry.get("locked")):
                    entry["locked"] = new_lock
                    st.session_state.image_results[idx] = entry

            # 提示词折叠（默认收起，不刷屏；像即梦：图为主，提示词点开才看）
            with st.expander("✏️ 提示词（点开编辑 + 重生）", expanded=False):
                page_prompts = st.session_state.get("page_prompts") or {}
                pp = page_prompts.get(idx, {})
                cur_prompt = pp.get("prompt", entry.get("prompt", ""))
                cur_must = pp.get("must_include", "")
                new_prompt = st.text_area(
                    "中文 Prompt",
                    value=cur_prompt,
                    height=180,
                    key=f"reedit_prompt_{idx}",
                )
                new_must = st.text_area(
                    "必须出现（追加到 prompt 末尾）",
                    value=cur_must,
                    height=70,
                    key=f"reedit_must_{idx}",
                    placeholder="例如：\nAnna 必须戴琥珀色细框眼镜\nTommy 必须微笑看向 Anna",
                )
                if st.button(f"💾 保存并重生 {display_name}", key=f"reedit_save_{idx}"):
                    pp["prompt"] = new_prompt
                    pp["must_include"] = new_must
                    page_prompts[idx] = pp
                    st.session_state.page_prompts = page_prompts
                    _regenerate_single_image(idx, mock_imgs)
                    st.rerun()

            # v3.2 问题反馈面板：勾选问题 → 自动加进 learned_negatives，下次重生立即生效
            _render_image_feedback_panel(idx, mock_imgs)

        st.divider()


# v3.2 问题反馈面板的固定问题清单（问题 → 自动注入到反向 prompt 的文本）
_IMAGE_FEEDBACK_ITEMS = [
    ("frame_jump", "🔀 人物跳帧（外观和前后页不一致）",
     "人物外观与故事其他页不一致；服装/发型/配饰跳变；同一角色出现不同面孔"),
    ("multi_finger", "✋ 手指/手部畸形（多手指、缺手指、融合）",
     "多手指、缺手指、融合手指、第六根手指、手部畸形、手腕扭曲"),
    ("char_too_small", "🔍 人物太小（淹没在背景里）",
     "人物在画面中过小、淹没在背景、远景小人；主角必须占画面 30-40% 以上"),
    ("char_too_big", "🔭 人物太大（占满画面没有环境）",
     "人物占满画面、没有环境上下文、特写过头；必须保留环境留白"),
    ("background_messy", "🌪️ 背景杂乱（元素太碎太多）",
     "背景元素过多过碎、视觉混乱、注意力被背景抢走；背景要简洁"),
    ("ratio_wrong", "📐 角色间比例不对（成人/儿童/宠物大小关系错）",
     "角色之间比例失调；成年人比儿童矮、儿童比宠物小、宠物大如人；比例必须真实"),
    ("gaze_wrong", "👀 视线混乱（角色没看对地方）",
     "角色视线方向错误；对话中角色没看对方；眼神涣散；应当根据互动调整视线"),
    ("clothing_mismatch", "👕 服装与故事/IP 不符",
     "角色服装与 IP 锁定不符；同一本书内服装跳变；服装颜色错误"),
    ("emotion_wrong", "😐 表情和故事情绪不匹配",
     "角色表情与故事情境不符；该笑的没笑、该紧张的太放松"),
    ("extra_chars", "👥 多了不该出现的人物 / 少了关键角色",
     "画面里出现故事没有提到的人物；或者缺失故事里关键的角色"),
]


def _render_image_feedback_panel(idx: int, mock_imgs: bool) -> None:
    """v3.2 问题反馈面板：勾选这张图的问题 → 自动加进 learned_negatives → 一键重生。"""
    page_prompts = st.session_state.setdefault("page_prompts", {})
    entry = page_prompts.setdefault(idx, {})
    saved_codes: list[str] = entry.get("feedback_codes") or []

    with st.expander("🚨 这张图有问题？勾选 → 下次自动避免", expanded=False):
        st.caption("勾选的问题会作为反向 prompt 写进下次生图。你也可以补一句自由文本。")
        new_codes: list[str] = []
        for code, label, _ in _IMAGE_FEEDBACK_ITEMS:
            checked = st.checkbox(
                label,
                value=(code in saved_codes),
                key=f"fb_{idx}_{code}",
            )
            if checked:
                new_codes.append(code)

        free_text = st.text_input(
            "其他问题（自由写一句，自动加进反向）",
            value=entry.get("feedback_free", ""),
            key=f"fb_free_{idx}",
            placeholder="例：Anna 的眼镜框颜色不对，应该是琥珀色",
        )

        # 实时拼出"会注入的负向 prompt"预览
        neg_bits: list[str] = []
        for code, _, neg in _IMAGE_FEEDBACK_ITEMS:
            if code in new_codes:
                neg_bits.append(neg)
        if free_text.strip():
            neg_bits.append(free_text.strip())
        learned_neg = "；".join(neg_bits)

        if learned_neg:
            st.markdown("**🔬 将注入的反向 prompt：**")
            st.code(learned_neg, language="text")

        bb1, bb2 = st.columns(2)
        with bb1:
            if st.button("💾 保存反馈（不重生）", key=f"fb_save_{idx}", width="stretch"):
                entry["feedback_codes"] = new_codes
                entry["feedback_free"] = free_text
                entry["learned_negatives"] = learned_neg
                page_prompts[idx] = entry
                st.session_state.page_prompts = page_prompts
                st.success("已保存。下次任何形式的重生都会带上这些反向约束。")
        with bb2:
            if st.button("🔁 保存并重生本页", key=f"fb_regen_{idx}", width="stretch", type="primary"):
                entry["feedback_codes"] = new_codes
                entry["feedback_free"] = free_text
                entry["learned_negatives"] = learned_neg
                page_prompts[idx] = entry
                st.session_state.page_prompts = page_prompts
                _regenerate_single_image(idx, mock_imgs)
                st.rerun()


def _run_docs_assembly() -> None:
    """v1.8.3 步骤 C：用 session 里的图组装 4 件套 + 打包 ZIP。"""
    ec = st.session_state.extracted
    outline: BookOutline = st.session_state.outline
    apply_extracted_to_outline(outline, ec)
    attach_rr_questions(outline, ec.rr_questions)
    rqc = int(st.session_state.get("ws_reading_q_count", 4))
    attach_worksheet_questions(outline, ec.worksheet_questions, reading_q_count=rqc)

    image_results = st.session_state.get("image_results") or {}
    if not image_results:
        st.error("还没生图。请先点上面的「🎨 生成所有图」。")
        return

    run_dir, _, name_prefix = _ensure_run_dir()

    # 按 page.index 顺序取图（用最新的 path）
    image_paths: list[Path] = []
    for page in outline.pages:
        entry = image_results.get(page.index)
        if not entry or not entry.get("path") or not Path(entry["path"]).exists():
            st.error(f"P{page.index} 缺图，请先点 🎨 生成。")
            return
        image_paths.append(Path(entry["path"]))

    progress = st.progress(0, "组装文档中...")

    # 1. Picture Book PPT
    progress.progress(1 / 5, "组装 Picture Book PPT...")
    pb_path = run_dir / f"{name_prefix}_绘本.pptx"
    build_picturebook_pptx(outline, image_paths, pb_path)

    # 2. Worksheet
    progress.progress(2 / 5, "生成 Worksheet PPTX...")
    ws_path = run_dir / f"{name_prefix}_练习册.pptx"
    build_worksheet(outline, ws_path, image_paths=image_paths)

    # 3. Reading Report
    progress.progress(3 / 5, "生成 Reading Report DOCX...")
    rr_path = run_dir / f"{name_prefix}_阅读报告.docx"
    build_reading_report(outline, rr_path)

    # 4. Teacher's Guide
    progress.progress(4 / 5, "生成 Teacher's Guide DOCX...")
    tg_path = run_dir / f"{name_prefix}_教师指南.docx"
    build_teacher_guide(outline, tg_path)

    # 5. ZIP
    zip_path = run_dir / f"{name_prefix}_全套.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for path in [pb_path, ws_path, rr_path, tg_path]:
            z.write(path, arcname=path.name)
        # 也带上图片
        for img in image_paths:
            z.write(img, arcname=f"images/{img.name}")

    progress.progress(1.0, "完成 ✅")

    st.success("4 件套已生成。点击下面按钮下载：")
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        _download_button(pb_path, "📘 绘本 PPT")
    with col2:
        _download_button(ws_path, "📋 Worksheet")
    with col3:
        _download_button(rr_path, "📝 Reading Report")
    with col4:
        _download_button(tg_path, "📖 Teacher Guide")
    with col5:
        _download_button(zip_path, "📦 全套 ZIP", primary=True)

    # 预览图片
    with st.expander("🖼️ 预览生成的图片", expanded=False):
        for img in image_paths:
            st.image(str(img), caption=img.name, width="stretch")


def _download_button(path: Path, label: str, *, primary: bool = False) -> None:
    if not path.exists():
        st.error(f"{label}: 文件不存在")
        return
    with open(path, "rb") as f:
        st.download_button(
            label=label,
            data=f.read(),
            file_name=path.name,
            mime="application/octet-stream",
            type="primary" if primary else "secondary",
            width="stretch",
        )


# =============================== 工具 ===============================
def _build_outline(
    *, title: str, level: str, book_number: str, cefr: str, theme: str,
    ip_age: int, raw_story: str, custom_chars_text: str,
    fiction_type: str = "",
) -> BookOutline:
    """从表单数据搭一个 BookOutline 骨架（pages 留空，等 AI 抽取后填）。"""
    pages: list[PageSpec] = [PageSpec(index=0, page_type="cover", text=title, scene="")]
    for i in range(1, 8):
        pages.append(PageSpec(index=i, page_type="story", text="", scene=""))

    custom_chars: dict[str, str] = {}
    for line in (custom_chars_text or "").splitlines():
        if "|" in line:
            name, desc = line.split("|", 1)
            name = name.strip().lower()
            desc = desc.strip()
            if name and desc:
                custom_chars[name] = desc

    return BookOutline(
        title=title.strip() or "Picture Book",
        pages=pages,
        level=level,
        book_number=book_number,
        cefr=cefr,
        theme=theme,
        ip_age=ip_age,
        custom_characters=custom_chars,
        fiction_type=fiction_type,
    )


def _key_status_banner() -> None:
    ai_ok = bool(DOUBAO_API_KEY) and not MOCK_AI_EXTRACT
    img_ok = bool(JIMENG_API_KEY) and not MOCK_IMAGES

    msgs = []
    if ai_ok:
        msgs.append("🟢 Claude 文本可用")
    else:
        msgs.append("🟡 Claude 文本走 mock（无 key 或强制 mock）")
    if img_ok:
        msgs.append("🟢 gpt-image-2 图生成可用")
    else:
        msgs.append("🟡 gpt-image-2 走 mock 占位图")
    st.caption("&nbsp;&nbsp;|&nbsp;&nbsp;".join(msgs), unsafe_allow_html=True)


def _inject_css() -> None:
    st.markdown(
        """<style>
        .stButton button { font-weight: 600; }
        .block-container { max-width: 1280px; padding-top: 1.2rem; }
        textarea { font-family: 'Poppins', 'Segoe UI', sans-serif !important; }
        </style>""",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
