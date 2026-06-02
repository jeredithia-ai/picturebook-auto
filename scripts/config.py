"""项目配置：路径、IP 年龄档、即梦 4.6 API、PPT 几何与字体。"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# Streamlit Cloud 兼容：把 st.secrets 的值同步进 os.environ
# 这样 Cloud 上不用改 .env 就能读 ARK_API_KEY / DOUBAO_MODEL 等
def _hydrate_from_streamlit_secrets() -> None:
    try:
        import streamlit as st
        if not hasattr(st, "secrets"):
            return
        for key, val in dict(st.secrets).items():
            if isinstance(val, (str, int, float, bool)) and not os.getenv(key):
                os.environ[key] = str(val)
    except Exception:
        pass


_hydrate_from_streamlit_secrets()

# ---------- 路径 ----------
INPUTS_DIR = ROOT / "inputs"
OUTPUTS_DIR = ROOT / "outputs"
ASSETS_DIR = ROOT / "assets"
CHARACTERS_DIR = ASSETS_DIR / "characters"
STYLE_DIR = ASSETS_DIR / "style"
BRAND_DIR = ASSETS_DIR / "brand"
FONTS_DIR = ASSETS_DIR / "fonts"
POPPINS_DIR = FONTS_DIR / "Poppins"
TEMPLATES_DIR = ROOT / "templates"
WORKSHEET_TEMPLATE = TEMPLATES_DIR / "worksheet_a4.pptx"

# ============================================================
#  imarouter 统一 API（2026-06-02 迁移）
#  - 文本：Claude / GPT（OpenAI 兼容 /chat/completions）
#  - 生图：gpt-image-2（异步任务制，详见 seedream_client.py）
#  旧的火山（DeepSeek + Seedream）变量名保留，全部重指向 imarouter，
#  避免改动各 import 处。
# ============================================================
IMAROUTER_API_KEY = (
    os.getenv("IMAROUTER_API_KEY", "").strip()
    or os.getenv("ARK_API_KEY", "").strip()
)
IMAROUTER_BASE = os.getenv("IMAROUTER_BASE", "https://api.imarouter.com/v1").rstrip("/")
TEXT_MODEL = os.getenv("TEXT_MODEL", "claude-opus-4-7")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-2")

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "240"))
REQUEST_RETRIES = int(os.getenv("REQUEST_RETRIES", "2"))

# ---------- 生图（gpt-image-2 via imarouter，异步任务）----------
JIMENG_API_KEY = IMAROUTER_API_KEY                # 兼容旧名
JIMENG_BASE_URL = IMAROUTER_BASE
JIMENG_MODEL = IMAGE_MODEL
# 绘本正文页 3:2 横版（gpt-image-2 仅支持 1024x1024 / 1024x1536 / 1536x1024）
IMAGE_SIZE = os.getenv("IMAGE_SIZE", "1536x1024")
IMAGE_WATERMARK = os.getenv("IMAGE_WATERMARK", "false").lower() in ("1", "true", "yes")
# gpt-image-2 异步轮询参数
IMAGE_POLL_INTERVAL = float(os.getenv("IMAGE_POLL_INTERVAL", "5"))
IMAGE_POLL_MAX_TRIES = int(os.getenv("IMAGE_POLL_MAX_TRIES", "60"))
# 参考图托管（gpt-image-2 只收 URL，本地图需先托管；临时图床即可，生成时拉取一次）
IMAGE_HOST_PROVIDER = os.getenv("IMAGE_HOST_PROVIDER", "tmpfiles")

# ---------- 文本（Claude/GPT via imarouter；旧 DOUBAO_/DEEPSEEK_ 名重指向）----------
DOUBAO_API_KEY = IMAROUTER_API_KEY
DOUBAO_BASE_URL = IMAROUTER_BASE
DOUBAO_MODEL = TEXT_MODEL

DEEPSEEK_API_KEY = IMAROUTER_API_KEY
DEEPSEEK_BASE_URL = IMAROUTER_BASE
DEEPSEEK_MODEL = TEXT_MODEL
# 仍可用 DeepSeek 那套 scene_cn / 润色函数，只是底层模型换成 Claude/GPT
USE_DEEPSEEK_FOR_SCENE = (
    os.getenv("USE_DEEPSEEK_FOR_SCENE", "true").lower() in ("1", "true", "yes")
    and bool(IMAROUTER_API_KEY)
)

# 无 Key 时降级
MOCK_IMAGES = (
    os.getenv("MOCK_IMAGES", "false").lower() in ("1", "true", "yes")
    or not IMAROUTER_API_KEY
)
MOCK_AI_EXTRACT = (
    os.getenv("MOCK_AI_EXTRACT", "false").lower() in ("1", "true", "yes")
    or not IMAROUTER_API_KEY
)

# ---------- IP 年龄映射（可被大纲 IP_Age 字段覆盖）----------
# 用户拍板 v3（2026-05-31）：L0-L3=8 岁 / L4=10 岁 / L5-L6=12 岁
LEVEL_TO_AGE_DEFAULT: dict[str, int] = {
    "smart": 8,
    "0": 8, "1": 8, "2": 8, "3": 8,
    "4": 10,
    "5": 12, "6": 12,
}


def resolve_ip_age(level: str, explicit_age: int | None = None) -> int:
    if explicit_age:
        return int(explicit_age)
    key = _level_key(level)
    return LEVEL_TO_AGE_DEFAULT.get(key, 10)


def _level_key(level: str) -> str:
    """把 'L5' / 'Level 5' / '5' / 'Smart' 统一成 dict key。"""
    s = str(level).strip().lower()
    if "smart" in s:
        return "smart"
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits or "1"


# ---------- VIPKID Dino 品牌色（每 Level 主题色，从 A4 模板提取） ----------
# 用作 Worksheet 外框 + footer 文字色等
BRAND_COLORS: dict[str, str] = {
    "smart": "#5E9F49",   # 绿
    "0":     "#5E9F49",   # 兼容 L0 = Smart
    "1":     "#F18200",   # 橙
    "2":     "#54C2F0",   # 浅蓝
    "3":     "#E94653",   # 红
    "4":     "#00B0C4",   # 青
    "5":     "#E95283",   # 粉
    "6":     "#0677B7",   # 深蓝
}


def brand_color_hex(level: str) -> str:
    return BRAND_COLORS.get(_level_key(level), "#E95283")


def brand_color_rgb(level: str) -> tuple[int, int, int]:
    h = brand_color_hex(level).lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


# ---------- Reading Report 题量梯度（按口径） ----------
# L0-L2 = 4 题（1×⭐ + 2×⭐⭐ + 1×⭐⭐⭐）
# L3-L6 = 5 题（1×⭐ + 3×⭐⭐ + 1×⭐⭐⭐）
def rr_question_distribution(level: str) -> list[int]:
    """返回每题星数列表，例: [1, 2, 2, 3]"""
    key = _level_key(level)
    if key in ("smart", "0", "1", "2"):
        return [1, 2, 2, 3]
    return [1, 2, 2, 2, 3]


# ============================================================
#  绘本画面 构图 / 比例策略（底层逻辑：只读展示 + 自动注入提示词）
#  用户拍板（2026-06-02）：
#   - 主角必须是画面唯一视觉中心，占画面高度约 50–60%（清晰饱满）
#   - 同框其他人物按真实身高比例：同龄人身高相近、成人比儿童高，
#     但任何人都不能比同框同龄人明显大一圈
#   - 动物按真实比例（仓鼠≈成人手掌大，不能画成猫狗大小）
#   - 背景占 40–50%，环境元素清晰可辨但不喧宾夺主
#   - 留约 20% 浅色区给文字；默认平视；水彩治愈童书风
#  ⚠️ 这些不是“仅展示”，会真正注入每页正向/反向提示词。
# ============================================================
COMPOSITION_POLICY: dict[str, str] = {
    "protagonist_pct": "50–60%",
    "background_pct": "40–50%",
    "text_safe_pct": "约 20%",
    "perspective": "默认平视（与儿童视线齐平）",
    "style": "温暖治愈水彩童书风（低饱和、柔和晕染、圆润线条）",
    "protagonist_rule": "主角是画面唯一视觉中心，清晰饱满，占画面高度约 50–60%",
    "scale_rule": (
        "同框其他人物按真实身高比例（同龄人身高相近，成人比儿童高），"
        "任何人都不能比同框同龄人明显大一圈"
    ),
    "animal_rule": "动物按真实比例（仓鼠≈成人手掌大小，不能画成猫狗大小）",
    "background_rule": "背景占画面 40–50%，有清晰可辨的环境元素，但不喧宾夺主",
}


def composition_prompt_cn() -> str:
    """构图/比例策略 → 注入正向 prompt 的中文硬性要求串。"""
    p = COMPOSITION_POLICY
    return (
        f"构图与比例（硬性要求）：{p['protagonist_rule']}；"
        f"{p['scale_rule']}；{p['animal_rule']}；{p['background_rule']}。"
    )


def composition_negative_cn() -> str:
    """构图/比例策略 → 注入反向 prompt 的中文禁忌串。"""
    return (
        "主角被画得过小（主角应占画面 50–60%）；"
        "配角或动物比主角还大；同框同龄人身高差异过大；"
        "动物体型失真（仓鼠被画成猫狗大小）；主角偏离画面视觉中心"
    )


# ---------- PPT 几何 ----------
SLIDE_WIDTH_IN = 10.0
SLIDE_HEIGHT_IN = 7.5

# 字体（Poppins SemiBold；若用户机器未安装会回退）
FONT_FAMILY = "Poppins SemiBold"
FONT_BOLD = False           # SemiBold 已是字面体，不要再叠加 PowerPoint bold

# 字号（pt）
FONT_SIZE_TITLE = 40       # 封面书名（固定）
FONT_SIZE_BADGE = 16       # Level/Book 徽章
FONT_SIZE_BODY = 22        # 正文（标准范围 20–24，长文取 20，短文取 24）
FONT_SIZE_PAGE_NUM = 14    # 页码
FONT_SIZE_META_HEAD = 18   # 元信息字段名
FONT_SIZE_META_BODY = 16   # 元信息值

# 颜色（RGB）
ORANGE_BADGE = (0xF4, 0x73, 0x32)  # 橙色胶囊填充
WHITE = (0xFF, 0xFF, 0xFF)
BLACK = (0x12, 0x12, 0x12)
LIGHT_GRAY_BORDER = (0x33, 0x33, 0x33)

# 留白与文字框
TEXT_SAFE_RATIO_MIN = 0.10   # 生图必须留出的最小留白比例
TEXT_SAFE_RATIO_MAX = 0.15
TEXT_BOX_WIDTH_RATIO = 0.40  # 文字框宽 = 40% 页宽
TEXT_BOX_PADDING_IN = 0.18

# 页码圆参数
PAGE_NUM_DIAMETER_IN = 0.55
PAGE_NUM_MARGIN_IN = 0.30


def text_box_position(corner: str) -> tuple[float, float]:
    """根据角位返回 (left_in, top_in)。"""
    margin = 0.35
    w = SLIDE_WIDTH_IN * TEXT_BOX_WIDTH_RATIO
    if corner == "top-left":
        return (margin, margin)
    if corner == "top-right":
        return (SLIDE_WIDTH_IN - w - margin, margin)
    if corner == "bottom-left":
        return (margin, SLIDE_HEIGHT_IN - margin - 1.6)
    if corner == "bottom-right":
        return (SLIDE_WIDTH_IN - w - margin, SLIDE_HEIGHT_IN - margin - 1.6)
    return (margin, margin)
