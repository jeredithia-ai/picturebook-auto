"""DeepSeek 专用：写"中文画面描述 scene_cn"和"润色生图 prompt"。

核心思路：
- Doubao text 在写"详细中文画面"上能力一般，词汇朴素、缺空间感和氛围
- DeepSeek V4 Pro 在中文长文本理解 + 视觉描述上明显更强
- 用 DeepSeek 专门负责这两件事，最终 prompt 喂给 Seedream 4.5 出图

模块对外暴露 3 个函数：
  - write_scene_cn(...)              → 给一页故事 + 上下文，写 120-220 字 scene_cn
  - polish_image_prompt(...)         → 给当前完整 prompt，DeepSeek 润色到 Seedream 4.5 最佳实践
  - is_available()                   → 检查 DeepSeek 是否可用（key + 模型激活）

如果 DeepSeek 不可用，调用方应该 fallback 到 Doubao 或返回原 prompt。
"""
from __future__ import annotations

import json
from typing import Optional

from deepseek_client import DeepSeekError, deepseek_chat, is_deepseek_available


def is_available() -> bool:
    return is_deepseek_available()


# ============================================================
# 1. 写 scene_cn：给一页故事文本 + 上下文 → 120-220 字详细画面描述
# ============================================================

_SCENE_SYSTEM_PROMPT = """你是 VIPKID 儿童绘本视觉描述专家，专门为水彩童书风插画师写画面描述。

你的任务：根据老师给的英文故事句子 + 上下文（人物 IP、风格、必出现/必避免），
写一段 **120-220 字的中文画面描述**，作为画师作画的 brief。

写作铁律（不可违反）：
1. 必须包含 4 个维度（按顺序）：
   - **主体**：每个出现人物的姓名 + 年龄 + 标志性外观（如 "12 岁 Anna 戴琥珀色细框眼镜，黑色双低马尾"）
   - **动作**：具体动词姿势（如 "右手撑下巴，左手摆弄铅笔"，不要"她在思考"这种泛词）
   - **环境**：可见的物品（如 "桌上有 5 本课本和一支橡皮"，不要"教室"这种泛词）
   - **氛围**：光照 + 情绪色调（如 "晨光从左侧斜射，整体清新柔和"）

2. 必须确保人物形象一致 — 老师给的 IP 形象描述必须完整照搬进去，不能简化
3. 禁止"她看起来很紧张"这种**抽象情绪词**，必须用**具体动作**表达情绪（"右手攥着衣角，肩膀微微缩起"）
4. 禁止"教室一角"这种**模糊空间词**，必须给空间锚点（"靠窗的第二排课桌"）
5. 必出现的元素必须放在第一句，避免漏掉
6. 字数严格 120-220，超出请精简

输出：纯文本，不要任何 markdown 符号、不要前缀（如"画面："），直接开始描述。"""


def write_scene_cn(
    *,
    story_sentence: str,
    page_idx: int,
    book_title: str,
    level: str,
    ip_age: int,
    cast_descriptions: list[str],
    style_summary: str = "",
    must_include: str = "",
    must_avoid: str = "",
    previous_pages_summary: str = "",
) -> str:
    """用 DeepSeek 写一页的中文画面描述。

    Args:
        story_sentence: 当前页的英文故事原文
        page_idx: 页号（2-8 故事页；0 是封面）
        book_title: 书名（封面会用）
        level: VIPKID 级别（影响人物年龄/复杂度）
        ip_age: 当前 level 对应的 IP 年龄（如 L5=12）
        cast_descriptions: 已锁定的 IP 形象描述列表（如 ["12 岁 Anna，黑色双低马尾..."]）
        style_summary: Step 3 风格设定的一句话总结（"温暖水彩 + 学校教室 + 清新柔和"）
        must_include: 教师锁定的必出现元素（多行字符串）
        must_avoid: 教师锁定的必避免元素（多行字符串）
        previous_pages_summary: 前几页的简短摘要（保持连续性）

    Returns:
        120-220 字的中文画面描述。
        如果 DeepSeek 不可用，抛 DeepSeekError 让调用方 fallback。
    """
    if not is_available():
        raise DeepSeekError("DeepSeek 未激活，请回 fallback")

    page_label = "封面" if page_idx == 0 else f"Page {page_idx}"

    cast_block = "\n".join(f"  - {c}" for c in cast_descriptions) if cast_descriptions else "  - 无指定 IP，按 generic 儿童形象"

    must_inc_lines = "\n".join(f"  - {l.strip()}" for l in (must_include or "").splitlines() if l.strip())
    must_avd_lines = "\n".join(f"  - {l.strip()}" for l in (must_avoid or "").splitlines() if l.strip())

    user_msg = f"""# 任务背景
绘本《{book_title}》(Level {level}, IP 年龄 {ip_age} 岁)
现在为 **{page_label}** 写画面描述。

# 这一页的英文故事
{story_sentence}

# 已锁定的人物 IP 形象（必须照搬到描述里）
{cast_block}

# 全局风格设定
{style_summary or "（无）"}

# 教师锁定 · 必出现元素
{must_inc_lines or "（无）"}

# 教师锁定 · 必避免元素
{must_avd_lines or "（无）"}

# 前几页摘要（保持人物形象/服装连续性）
{previous_pages_summary or "（首页）"}

请输出 120-220 字的中文画面描述。"""

    return deepseek_chat(
        system=_SCENE_SYSTEM_PROMPT,
        user=user_msg,
        temperature=0.4,
        max_tokens=600,
    ).strip()


# ============================================================
# 2. 润色生图 prompt：把当前 prompt 喂给 DeepSeek 强化
# ============================================================

_POLISH_SYSTEM_PROMPT = """你是 Seedream 4.5（火山即梦 4.6）图像生成的提示词工程师。

你的任务：把老师/系统给的现有"绘本生图 prompt"重写一版，让它**更适合 Seedream 4.5 的生成习惯**，
画出的图人物更清晰、风格更稳定、细节更丰富。

Seedream 4.5 提示词最佳实践：
1. **单段流畅自然语言**，不要标签式 (a, b, c)、不要换行分点
2. 开头先说"风格 + 媒介"（如 "温暖水彩童书风插画，柔和晕染"）
3. 然后写"主体"，每个人物：姓名 + 年龄 + 完整外观（发型/服装/配饰）+ 当下姿势
4. 然后写"环境"：空间位置 + 可见物品（具体到数量和颜色）
5. 然后写"光线 + 氛围"
6. 最后写构图（人物占比 30-40%、留白位置）
7. 全程**中文为主**，少量必要英文术语（如 close-up / wide shot）可保留
8. 长度 300-600 字最佳
9. 严禁出现"模糊"、"不清楚"、"可能"等不确定词
10. 严禁出现矛盾约束（如同时"特写"和"远景"）

# 重要：必须保留的元素
- 必须保留原 prompt 里所有的【人物姓名 + 标志性外观】
- 必须保留【必出现】里的元素
- 不能新增故事中没有的人物或道具

# 输出格式
直接输出润色后的 prompt 全文（一段），不要任何前缀、解释、markdown。"""


def polish_image_prompt(
    *,
    current_prompt: str,
    story_sentence: str = "",
    style_summary: str = "",
    must_include: str = "",
    must_avoid: str = "",
) -> str:
    """让 DeepSeek 润色当前 prompt，返回优化版。

    传入当前完整的正向 prompt（含人物锁定、必出现等）+ 故事上下文，
    DeepSeek 会按 Seedream 4.5 最佳实践重写成更适合出图的一段。

    Raises:
        DeepSeekError: DeepSeek 未激活或调用失败。
    """
    if not is_available():
        raise DeepSeekError("DeepSeek 未激活")

    user_msg = f"""# 当前正向 prompt（待润色）
{current_prompt}

# 这一页对应的英文故事原文
{story_sentence or "（无）"}

# 全局风格设定
{style_summary or "（无）"}

# 教师锁定 · 必出现
{must_include or "（无）"}

# 教师锁定 · 必避免（这些不要写进正向，只供你判断不要画什么）
{must_avoid or "（无）"}

请输出润色后的 prompt 全文，单段中文，300-600 字。"""

    return deepseek_chat(
        system=_POLISH_SYSTEM_PROMPT,
        user=user_msg,
        temperature=0.3,
        max_tokens=1200,
    ).strip()


# ============================================================
# 3. 给已有 Doubao scene_cn 做 DeepSeek 二次升级（fallback 链路用）
# ============================================================

def upgrade_doubao_scene_cn(*, doubao_scene: str, story_sentence: str,
                            cast_descriptions: list[str]) -> str:
    """如果 Doubao 已经生成了 scene_cn，让 DeepSeek 在其基础上加强。

    比 write_scene_cn 更轻量（不重写，只补充缺失维度）。
    """
    if not is_available():
        raise DeepSeekError("DeepSeek 未激活")

    cast_block = "\n".join(f"  - {c}" for c in cast_descriptions) if cast_descriptions else "（无）"

    user_msg = f"""请基于以下 Doubao 生成的中文画面描述做"轻度补强"：
- 检查 4 维度（主体/动作/环境/氛围）是否齐全，缺哪补哪
- 检查人物形象是否完整，没写到的标志性外观请补上
- 总字数控制在 120-220 字

# Doubao 生成的画面描述
{doubao_scene}

# 这一页的英文故事
{story_sentence}

# 已锁定的 IP 形象（用于补全人物外观）
{cast_block}

请直接输出补强后的画面描述（不要任何前缀）。"""

    return deepseek_chat(
        system=_SCENE_SYSTEM_PROMPT,
        user=user_msg,
        temperature=0.3,
        max_tokens=600,
    ).strip()
