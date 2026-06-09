"""AI 文本抽取器（v3.2 已切换到 DeepSeek-V4-Pro）：
把老师输入的原始 7 句故事 + 元信息 一次性转成结构化 JSON。

输出包含:
  - pages: 7 段重写后的 Page 文本 + scene 描述（喂给图生）
  - mastery / exposure: 词汇（lemma 原型小写，遵守 Storybook Style Guide）
  - phonics: 自然拼读规则
  - grammar_focus: 主语法点
  - reader_type: 读者类型
  - word_count: 总词数
  - rr_questions: Reading Report 阅读表达题（按 Level 4/5 题，星级 + P# 严格按口径）
  - worksheet_questions: 6 道 worksheet 题（按 Level 题型池随机抽 + 内容紧扣绘本）

无可用 API KEY 时使用 mock 模式回退（基于规则），保证 web 流程能跑。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from config import (
    EXTRACT_MODEL,
    MOCK_AI_EXTRACT,
    rr_question_distribution,
)


# ---------- 题型池（按 Level 区分，对照官方 worksheet 样本） ----------
QUESTION_POOL: dict[str, list[str]] = {
    "smart": [
        "color_match", "circle_match", "fill_blank_simple",
        "word_to_pic", "draw_favorite", "personal_simple",
    ],
    "0": [
        "color_match", "circle_match", "fill_blank_simple",
        "word_to_pic", "draw_favorite", "personal_simple",
    ],
    "1": [
        "circle_match", "fill_blank_simple", "word_order_simple",
        "true_false_simple", "draw_favorite", "personal_simple",
    ],
    "2": [
        "fill_blank", "word_order", "true_false",
        "match_definition", "story_sequence", "personal_write",
    ],
    "3": [
        "unscramble", "fill_blank", "match_definition",
        "rewrite_tense", "true_false", "plot_chart",
    ],
    "4": [
        "unscramble", "fill_blank", "rewrite_tense",
        "emotion_fill", "true_false", "plot_chart_pbl",
    ],
    "5": [
        "match_definition", "fill_blank_advanced", "rewrite_voice",
        "compare_contrast", "inference", "open_ended_pbl",
    ],
    "6": [
        "match_definition", "fill_blank_advanced", "essay_short",
        "compare_contrast", "inference", "research_pbl",
    ],
}

# ---------- 题型轮换（同一渲染槽位内换题型，告别"每级雷同"；版式不变） ----------
# 每个 level 给 6 个槽位，每个槽位列出"渲染到同一版式槽"的可互换题型；按种子在槽内轮换。
# 关键：同一槽位的所有候选必须落到 attach_worksheet_questions 的同一 out 槽，保证版式恒定。
QUESTION_POOL_ALTS: dict[str, list[list[str]]] = {
    "smart": [["color_match", "circle_match", "word_to_pic"], ["circle_match", "color_match"],
              ["fill_blank_simple"], ["word_to_pic", "circle_match"],
              ["draw_favorite", "personal_simple"], ["personal_simple", "draw_favorite"]],
    "0": [["color_match", "circle_match", "word_to_pic"], ["circle_match", "color_match"],
          ["fill_blank_simple"], ["word_to_pic", "circle_match"],
          ["draw_favorite", "personal_simple"], ["personal_simple", "draw_favorite"]],
    "1": [["circle_match", "word_to_pic", "color_match"], ["fill_blank_simple"],
          ["word_order_simple", "story_sequence"], ["true_false_simple"],
          ["draw_favorite", "personal_simple"], ["personal_simple", "draw_favorite"]],
    "2": [["fill_blank"], ["word_order", "story_sequence"], ["true_false"],
          ["match_definition"], ["story_sequence", "word_order"], ["personal_write", "draw_favorite"]],
    "3": [["unscramble", "fill_blank"], ["fill_blank", "unscramble"], ["match_definition"],
          ["rewrite_tense"], ["true_false"], ["plot_chart", "compare_contrast"]],
    "4": [["unscramble", "fill_blank"], ["fill_blank", "rewrite_tense"], ["rewrite_tense", "rewrite_voice"],
          ["emotion_fill", "fill_blank"], ["true_false"], ["plot_chart_pbl", "compare_contrast"]],
    "5": [["match_definition"], ["fill_blank_advanced", "unscramble"], ["rewrite_voice", "rewrite_tense"],
          ["compare_contrast", "plot_chart_pbl"], ["inference"], ["open_ended_pbl", "essay_short"]],
    "6": [["match_definition"], ["fill_blank_advanced", "unscramble"], ["essay_short", "open_ended_pbl"],
          ["compare_contrast", "plot_chart_pbl"], ["inference"], ["research_pbl", "essay_short"]],
}


def _pool_seed(*parts) -> int:
    """由书名等稳定信息派生一个轮换种子（同一本书结果稳定、不同书结果不同）。"""
    s = "|".join(str(p) for p in parts if p)
    if not s:
        return 0
    return int(hashlib.md5(s.encode("utf-8")).hexdigest()[:8], 16)


def select_question_pool(level_key: str, seed: int = 0) -> list[str]:
    """在每个槽位的可互换题型里按 seed 轮换，得到本书的 6 道题型（版式不变、内容多样）。"""
    alts = QUESTION_POOL_ALTS.get(level_key)
    if not alts:
        return list(QUESTION_POOL.get(level_key, QUESTION_POOL["4"]))
    out: list[str] = []
    for i, opts in enumerate(alts):
        out.append(opts[(seed + i) % len(opts)] if opts else "")
    return out


# 题型展示标题（worksheet 大标题）
QUESTION_TITLES: dict[str, str] = {
    "color_match": "Color the Words", "circle_match": "Match the Pictures",
    "fill_blank_simple": "Fill in the Blanks", "word_to_pic": "Match Words to Pictures",
    "draw_favorite": "Draw Your Favorite Page", "personal_simple": "About Me",
    "word_order_simple": "Put the Words in Order", "true_false_simple": "True or False",
    "fill_blank": "Fill in the Blanks", "word_order": "Put the Sentences in Order",
    "true_false": "True or False", "match_definition": "Match the Words to the Definitions",
    "story_sequence": "Story Sequence", "personal_write": "Write About Yourself",
    "unscramble": "Unscramble the Words", "rewrite_tense": "Rewrite the Sentences",
    "plot_chart": "Story Chart", "emotion_fill": "Choose the Emotion",
    "plot_chart_pbl": "Story Plot & Reflection", "fill_blank_advanced": "Fill in the Blanks",
    "rewrite_voice": "Rewrite the Sentences", "compare_contrast": "Compare & Contrast",
    "inference": "Read & Infer", "open_ended_pbl": "Project: Express Your Idea",
    "essay_short": "Short Essay", "research_pbl": "Mini Research Project",
}

QUESTION_INSTRUCTIONS: dict[str, str] = {
    "color_match": "Color the words you remember from the story.",
    "circle_match": "Circle the picture that matches each word.",
    "fill_blank_simple": "Fill in the blanks with the correct words.",
    "word_to_pic": "Draw a line to match each word to the picture.",
    "draw_favorite": "Draw your favorite page from the book.",
    "personal_simple": "Tell us about yourself.",
    "word_order_simple": "Put the words in the right order to make a sentence.",
    "true_false_simple": "Read each sentence. Circle T for True or F for False.",
    "fill_blank": "Fill in the blanks with the correct vocabulary words.",
    "word_order": "Number the sentences in the order they happened in the story.",
    "true_false": "Read the story and mark each statement True (T) or False (F).",
    "match_definition": "Match the words to their definitions.",
    "story_sequence": "Number these events in the order they happened.",
    "personal_write": "Write 2-3 sentences about yourself related to the story.",
    "unscramble": "Rearrange the letters to spell the correct words.",
    "rewrite_tense": "Rewrite the sentences using the correct grammar pattern.",
    "plot_chart": "Fill in the chart to show the main events of the story.",
    "emotion_fill": "Complete the sentences with the correct emotion words from the box.",
    "plot_chart_pbl": "Fill in the chart and answer the question below.",
    "fill_blank_advanced": "Fill in the blanks using the vocabulary words.",
    "rewrite_voice": "Rewrite each sentence in the new voice or style as instructed.",
    "compare_contrast": "Compare and contrast the two ideas from the passage.",
    "inference": "Read each section and answer the inference questions.",
    "open_ended_pbl": "Plan and write a short response to the project prompt.",
    "essay_short": "Write a short essay (4-6 sentences) on the prompt below.",
    "research_pbl": "Choose one topic from the book to research and present.",
}


@dataclass
class ExtractedContent:
    """AI 抽取后的结构化结果。所有字段都可在 UI 中编辑。"""
    pages: list[dict] = field(default_factory=list)  # [{index, text, scene, expression, shot}]
    mastery: list[str] = field(default_factory=list)
    exposure: list[str] = field(default_factory=list)
    vocabulary: list[str] = field(default_factory=list)  # L3-L6 单行用
    grammar_focus: str = ""
    phonics: str = ""
    reader_type: str = ""
    word_count: int = 0
    rr_questions: list[dict] = field(default_factory=list)  # [{q, stars, page}]
    worksheet_questions: list[dict] = field(default_factory=list)  # [{type, title, instruction, items, answer_key}]
    # 专用阅读理解题（worksheet 阅读页用）：[{kind: mc|tf|short, q, options, correct, answer, page}]
    reading_questions: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pages": self.pages,
            "mastery": self.mastery,
            "exposure": self.exposure,
            "vocabulary": self.vocabulary,
            "grammar_focus": self.grammar_focus,
            "phonics": self.phonics,
            "reader_type": self.reader_type,
            "word_count": self.word_count,
            "rr_questions": self.rr_questions,
            "worksheet_questions": self.worksheet_questions,
            "reading_questions": self.reading_questions,
        }


def extract_all(
    raw_story: str,
    title: str,
    level: str,
    cefr: str = "",
    theme: str = "",
    *,
    mock: bool | None = None,
) -> ExtractedContent:
    """主入口：把原文一次性抽成全套结构化内容。

    raw_story: 老师输入的整段故事（可以是 7 句、也可以是大段散文，模型会拆段）
    level:     'Smart' / 'L0' / '5' / 'Level 4' 都支持
    """
    use_mock = MOCK_AI_EXTRACT if mock is None else mock
    if use_mock:
        return _mock_extract(raw_story, title, level, cefr, theme)
    # 真实抽取：失败时重试（含 json_repair 兜底），最多 3 次，避免偶发 JSON/网络错误
    # 直接静默回退 mock（mock 是占位假数据，会让交付物内容明显变差）。
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            return _doubao_extract(raw_story, title, level, cefr, theme)
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"[ai_extractor] 真实抽取第 {attempt}/3 次失败：{e}")
    print(f"[ai_extractor] ⚠️ 真实抽取连续失败，回退 mock（内容为占位，质量下降）：{last_err}")
    return _mock_extract(raw_story, title, level, cefr, theme)


# ---------- 从书名 + 级别生成故事草稿（老师微调后再抽取）----------
_STORY_WORD_TARGETS: dict[str, str] = {
    "smart": "40–80", "0": "40–80", "1": "60–100", "2": "80–130",
    "3": "100–160", "4": "130–200", "5": "160–250", "6": "200–320",
}


def generate_story_draft(title: str, level: str, theme: str = "", *, mock: bool | None = None) -> str:
    """根据书名 + 级别生成英文故事草稿（约 7 句，供拆 7 页正文）。"""
    title = (title or "").strip()
    if not title:
        raise ValueError("Book Title 不能为空")
    use_mock = MOCK_AI_EXTRACT if mock is None else mock
    level_key = _level_key(level)
    theme_hint = (theme or "").strip()
    if use_mock:
        return _mock_story_draft(title, level_key, theme_hint)
    from deepseek_client import deepseek_chat

    wc = _STORY_WORD_TARGETS.get(level_key, "100–160")
    ip_note = "Use VIPKID characters (Mia, Tommy, Anna, Teacher Kim, Winnie) when they fit the story."
    system = (
        "You are a VIPKID Dino children's picture-book writer. "
        "Write ONE complete English story for offline teaching. "
        "Rules:\n"
        f"- Level L{level_key} vocabulary and sentence length; target {wc} words total.\n"
        "- Exactly 7 sentences (one per story page; cover is separate).\n"
        "- American English; past tense narrative for fiction; simple, vivid, kid-safe.\n"
        "- Match the book title theme; clear beginning–middle–end.\n"
        f"- {ip_note}\n"
        "- Output ONLY the story text: 7 sentences as plain paragraphs or one block. "
        "No title line, no page labels, no markdown."
    )
    user = f"Book title: {title}\nLevel: L{level_key}"
    if theme_hint:
        user += f"\nTheme hint: {theme_hint}"
    raw = deepseek_chat(
        system=system,
        user=user,
        model=EXTRACT_MODEL,
        max_tokens=1200,
        temperature=0.65,
        timeout=120,
    )
    text = (raw or "").strip()
    if not text:
        raise RuntimeError("AI 未返回故事内容")
    return text


def _mock_story_draft(title: str, level_key: str, theme: str) -> str:
    """无 API 时的占位故事（仍可走通流程）。"""
    t = theme or title.split()[0] if title else "school"
    name = "Mia" if level_key in ("smart", "0", "1", "2") else "Anna"
    return (
        f"{name} wanted to learn about {title.lower()} at school one sunny morning. "
        f"She listened carefully when Teacher Kim explained why {t} matters to good friends. "
        f"At recess {name} helped a classmate and shared a kind smile. "
        f"A small surprise made everyone laugh together in the classroom. "
        f"{name} asked thoughtful questions and waited for each answer. "
        f"By the end of the day she felt proud of what she had learned. "
        f"She made a plan to practice {t} again with her friends tomorrow."
    )


# ---------- 真实调用（2026-06-02 已切到 imarouter Claude/GPT，走 deepseek_chat 健壮封装）----------
def _doubao_extract(
    raw_story: str, title: str, level: str, cefr: str, theme: str,
) -> ExtractedContent:
    from deepseek_client import deepseek_chat

    level_key = _level_key(level)
    is_dual = level_key in ("smart", "0", "1", "2")
    rr_dist = rr_question_distribution(level)
    pool = select_question_pool(level_key, _pool_seed(title, level))

    system_prompt = _build_system_prompt(level_key, is_dual, rr_dist, pool)
    user_prompt = _build_user_prompt(raw_story, title, level, cefr, theme)
    # 追加：Claude 不一定支持 response_format，强制要求纯 JSON 输出
    system_prompt += "\n\n严格要求：只输出一个 JSON 对象，不要任何解释、不要 markdown 代码块包裹。"

    raw = deepseek_chat(
        system=system_prompt,
        user=user_prompt,
        model=EXTRACT_MODEL,
        max_tokens=16000,  # 抽取 JSON 较大（pages+scene_cn+题目），防截断
        json_mode=True,  # 不支持时 deepseek_chat 会自动剔除 response_format 重试
        # 用户拍板 2026-06-08：抽取调低 temperature=0.2，降随机/降角色漂移（批量串名整改）。
        # 模型不支持 temperature 时 deepseek_chat 会自动剔除重试。
        temperature=0.2,
        timeout=240,
    )
    data = _loads_robust(raw)
    return _parse_doubao_payload(data, level_key, is_dual, rr_dist, raw_story, pool=pool)


def ai_define_words(words: list[str], story: str, level: str = "3",
                    *, mock: bool | None = None) -> dict[str, str]:
    """为给定词批量生成"儿童词典式"释义，返回 {小写词: 释义}。

    用于 worksheet 词汇页（看词义猜词 / 谜语四选一）保证有真实释义、绝不出现
    "meaning of X" 占位。AI 失败 / mock → 返回 {}（上层用 _KID_DICT/留空兜底）。"""
    seen: list[str] = []
    for w in words or []:
        s = str(w or "").strip()
        if s and s.lower() not in {x.lower() for x in seen}:
            seen.append(s)
    if not seen:
        return {}
    use_mock = MOCK_AI_EXTRACT if mock is None else mock
    if use_mock:
        return {}
    try:
        from deepseek_client import deepseek_chat_json
        system = (
            "You are a children's picture-dictionary writer. For EACH given word, write ONE "
            f"very simple, kid-friendly definition suitable for a Level {level} young learner. "
            "Rules: American English; 4-12 words; lowercase; NO ending period; describe the "
            "MEANING without repeating the word itself; never output 'meaning of ...' or "
            "'definition of ...'. Output ONLY a JSON object: "
            '{"defs": {"word": "its simple definition", ...}} with one entry per input word.'
        )
        user = f"Story context (for sense):\n{(story or '')[:1500]}\n\nWords: {', '.join(seen)}"
        data = deepseek_chat_json(system=system, user=user,
                                  temperature=0.2, max_tokens=900, fallback=None)
        defs = (data or {}).get("defs") if isinstance(data, dict) else None
        out: dict[str, str] = {}
        for k, v in (defs or {}).items():
            kw = str(k or "").strip().lower()
            dv = str(v or "").strip().rstrip(".")
            low = dv.lower()
            if not kw or not dv:
                continue
            if low.startswith("meaning of ") or low.startswith("definition of "):
                continue
            out[kw] = dv
        return out
    except Exception as e:  # noqa: BLE001
        print(f"[ai_extractor] ai_define_words 失败：{e}")
        return {}


def generate_one_worksheet_question(
    qtype: str,
    raw_story: str,
    title: str,
    level: str,
    cefr: str = "",
    theme: str = "",
    *,
    mock: bool | None = None,
) -> dict:
    """为单个题型重新生成一道紧扣绘本内容、难度匹配 Level 的 worksheet 题。

    返回 {type, title, instruction, items, answer_key, extra}。
    用于网页里「逐题预览 → AI 重出这道题」的过程性出题。
    """
    level_key = _level_key(level)
    qtype = (qtype or "").strip().lower()

    use_mock = MOCK_AI_EXTRACT if mock is None else mock
    if use_mock:
        return _mock_one_worksheet_question(qtype, raw_story, level_key)
    try:
        return _ai_one_worksheet_question(qtype, raw_story, title, level, cefr, theme)
    except Exception as e:  # noqa: BLE001
        print(f"[ai_extractor] 单题生成失败 ({e})，回退 mock")
        return _mock_one_worksheet_question(qtype, raw_story, level_key)


def _ai_one_worksheet_question(
    qtype: str, raw_story: str, title: str, level: str, cefr: str, theme: str,
) -> dict:
    from deepseek_client import deepseek_chat

    try:
        from worksheet_question_types import get_type
        qt = get_type(qtype)
    except Exception:
        qt = None

    schema = qt.ai_items_schema if qt else ""
    en_instr = (qt.en_instr if qt else "") or QUESTION_INSTRUCTIONS.get(qtype, "")
    stars = qt.stars if qt else 2
    category = qt.category if qt else "reading"
    needs_image = bool(qt and qt.needs_image)
    needs_audio = bool(qt and qt.needs_audio)

    system_prompt = f"""You are a VIPKID Dino Reading Club worksheet item writer.
Generate ONE worksheet activity of type `{qtype}` (category: {category}, difficulty: {'⭐' * stars}).
The activity MUST test specific content from the given picture-book story and match Level {level} difficulty.

English instruction to use (verbatim): "{en_instr}"
items JSON schema for this type: {schema or '[{...}]'}

## Output ONLY this JSON object (no markdown, no explanation):
{{"items": [ ... 3-4 items following the schema above ... ], "extra": "<optional word bank / prompt, else empty>", "answer_key": null}}

## Hard formatting rules (American English)
- American spelling only (color, favorite, neighbor, recognize).
- A single item = ONE clear task. No compound questions.
- Vocabulary answers: lowercase, NO period, NO capital (e.g. "lock", not "Lock.").
- Full-sentence answers / statements / questions: capitalize first letter; questions end with "?"; statements end with ".".
- Use straight quotes only. Never output placeholders like "Option A" / "Question 1" / "sentence N".
- Difficulty must fit Level {level}: lower levels → shorter, more concrete, picture/recall; higher levels → inference, reasoning, writing.
{"- This is a picture-based item: every item must include image_hint = a story page index 2-8 to reuse the book illustration." if needs_image else ""}
{"- This is a listen-based item: phrase it so the teacher can read the target aloud in class (no audio file)." if needs_audio else ""}
严格要求：只输出一个 JSON 对象。"""

    user_prompt = (
        f"Title: {title}\nLevel: {level}\nCEFR: {cefr or 'auto'}\nTheme: {theme or 'auto'}\n\n"
        f"Picture-book story (use real facts/words from it):\n{raw_story}\n\n"
        f"Now write ONE `{qtype}` activity with 3-4 items."
    )

    raw = deepseek_chat(
        system=system_prompt,
        user=user_prompt,
        model=EXTRACT_MODEL,  # 单题重出也用更快的 Sonnet
        max_tokens=2000,
        json_mode=True,
        timeout=120,
    )
    data = _loads_robust(raw)
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        items = []
    extra = str((data.get("extra") if isinstance(data, dict) else "") or "").strip()
    return {
        "type": qtype,
        "title": QUESTION_TITLES.get(qtype, qtype.replace("_", " ").title()),
        "instruction": en_instr or QUESTION_INSTRUCTIONS.get(qtype, ""),
        "items": items,
        "answer_key": None,
        "extra": extra,
    }


def _mock_one_worksheet_question(qtype: str, raw_story: str, level_key: str) -> dict:
    """无 API key 时的单题兜底：复用 _mock_worksheet 的规则。"""
    sentences = _split_sentences(raw_story)
    pages = [{"index": i + 1, "text": s} for i, s in enumerate(sentences[:7])]
    words = _extract_content_words(raw_story)
    # 临时把该题型塞进 pool 头部，复用 _mock_worksheet 逻辑取第一条
    saved = QUESTION_POOL.get(level_key)
    try:
        QUESTION_POOL[level_key] = [qtype]
        built = _mock_worksheet(pages, words, level_key)
    finally:
        if saved is not None:
            QUESTION_POOL[level_key] = saved
        else:
            QUESTION_POOL.pop(level_key, None)
    if built:
        return built[0]
    return {
        "type": qtype,
        "title": QUESTION_TITLES.get(qtype, qtype.replace("_", " ").title()),
        "instruction": QUESTION_INSTRUCTIONS.get(qtype, ""),
        "items": [],
        "answer_key": None,
        "extra": "",
    }


def _loads_robust(raw: str) -> dict:
    """健壮解析模型返回的 JSON：先标准 json.loads，失败则用 json_repair 修复常见错误
    （缺逗号、未转义引号/换行、尾逗号等），杜绝偶发 JSON 错误导致整本抽取失败/静默回退 mock。"""
    block = _extract_json_block(raw)
    try:
        return json.loads(block)
    except Exception:
        pass
    try:
        from json_repair import repair_json
        fixed = repair_json(block)
        data = json.loads(fixed)
        if isinstance(data, dict):
            print("[ai_extractor] JSON 已用 json_repair 自动修复")
            return data
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"模型返回的 JSON 无法解析且修复失败: {e}") from e
    raise ValueError("模型返回的 JSON 修复后不是对象")


def _extract_json_block(raw: str) -> str:
    """从模型回复里抠出 JSON（容错 markdown ```json 包裹 / 前后多余文字）。"""
    s = (raw or "").strip()
    if s.startswith("```"):
        # 去掉 ```json ... ``` 包裹
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    s = s.strip()
    # 取第一个 { 到最后一个 }
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end != -1 and end > start:
        return s[start:end + 1]
    return s or "{}"


def _build_system_prompt(level_key: str, is_dual: bool, rr_dist: list[int], pool: list[str]) -> str:
    pool_str = ", ".join(pool)
    rr_count = len(rr_dist)
    star_pattern = " + ".join(f"{rr_dist.count(s)}×{'⭐' * s}" for s in sorted(set(rr_dist)))
    # worksheet 阅读页专用题量：L0-4 一个阅读页 → 4-6 题；L5-6 两个阅读页 → 8 题
    rd_count = 8 if level_key in ("5", "6") else 6

    # v2.1: 注入 VIPKID 标准 31 题型库推荐
    try:
        from worksheet_question_types import render_recommendation_for_prompt
        qtype_recommendation = render_recommendation_for_prompt(level_key)
    except Exception:
        qtype_recommendation = ""
    if is_dual:
        vocab_rule = "L0/L1/L2 双行词表：mastery 3-4 词 + exposure 3-4 词，全部 lemma 原型 + 小写 + 无标点"
    else:
        vocab_rule = "L3-L6 单行词表：vocabulary 字段必须 4 个词，全部 lemma 原型 + 小写 + 无标点"
    is_morph = level_key in ("5", "6")
    phonics_label = "morphology" if is_morph else "phonics"
    phonics_hint = (
        'suffix/prefix rule with examples, e.g., \'suffix -ous (= having/full of quality): nervous, famous\''
        if is_morph else
        'phonics rule with examples from the story, e.g., \'ee → /iː/: sheep, green, cheeky\''
    )
    return f"""You are a VIPKID Dino Reading Club curriculum specialist who turns raw teacher input into structured picture-book teaching content. Output ONLY valid JSON.

## Output schema (strict)
{{
  "pages": [
    {{
      "index": 1,
      "text": "<English page text 5-30 words>",
      "scene": "<2-3 sentence English visual scene description, no quoted text>",
      "scene_cn": "<一段连贯中文画面描述，120-220字，包含：主体（人物，只用名字）+ 动作 + 环境物品 + 本页 hook 趣味细节 + 光照氛围，写得越具体越好，不分段不列点>",
      "expression": "<one-word emotion>",
      "shot": "medium",
      "camera_angle": "<eye | high | low | birdseye | over_shoulder，按本页剧情选最有表现力的机位，不要全用 eye>",
      "focus": "<本页的'高潮/焦点动作'——本页最具视觉张力、最关键或最有趣的那一下，一句中文，必须是主角正在做的动作，将作为画面居中的主体动作（如'Tommy 俯身张开双手扑向桌下逃窜的小仓鼠'）>",
      "hook": "<本页一个有趣的画面彩蛋/细节，一句中文，如'桌子下面卡着橡皮的小仓鼠探出半个身子'，没有就给一个能强化剧情趣味的小细节>"
    }},
    ... 7 entries total, indices 1..7
  ],
  "mastery": ["word1", "word2", ...],
  "exposure": ["word1", "word2", ...],
  "vocabulary": ["word1", "word2", "word3", "word4"],
  "grammar_focus": "<grammar pattern in Chinese, e.g., '一般过去时态' / '一般现在时态' / 'There was/were 句型'>",
  "{phonics_label}": "<{phonics_hint}>",
  "reader_type": "<one of: Concept & Knowledge-Building Readers / Patterned Narrative & Informational Readers / Early Independent Genre-Exposure Readers / Fiction / Informational Text>",
  "word_count": <total word count int>,
  "rr_questions": [
    {{"q": "<English question, NO embedded (P#) in question text>", "stars": 1, "page": 2, "answer": "<short model answer in English, for the sample-answer version>"}},
    ... {rr_count} entries with stars distribution {star_pattern}
  ],
  "worksheet_questions": [
    {{"type": "<one of: {pool_str}>", "items": [...], "answer_key": [...], "extra": "<optional context>"}},
    ... 6 entries, one of each type from the pool
  ],
  "reading_questions": [
    {{"kind": "mc", "q": "<comprehension question>", "options": ["...", "...", "..."], "correct": 0, "page": 2}},
    {{"kind": "tf", "q": "<statement about the story>", "answer": "T", "page": 3}},
    {{"kind": "short", "q": "<open comprehension question>", "answer": "<model answer>", "page": 5}},
    ... {rd_count} entries total (see reading_questions rules below)
  ]
}}

## CRITICAL #0: 理解文本是第一步 · 忠实故事 · 严禁自我发挥（老师硬要求 2026-06-08）
在写 scene_cn 之前，先**逐字读懂本页文字**：搞清"谁是谁、代词指谁、发生了什么、在哪里"。然后：
  - **只画本页文字里真实出现的人/物/地点/动作**。文本没写的人物、道具、地点、剧情、情绪一律**不得自行新增/脑补/加戏**。
  - 画面里的**每一个元素都必须能在本页（或前文已建立的）文字里找到出处**；找不到出处的元素必须删掉。
  - 不要把别页/别的故事/常见套路的画面搬过来；不要为了"好看"或"凑系列 IP"而添加文本之外的角色或情节。
  - 取舍顺序：官方故事文本 > 系列铁律 > 模型补全。只有文本确实没交代、又必须补全画面时才可极少量补全（且只补环境氛围，不补角色/剧情）。

## CRITICAL: pages[].scene_cn (used by the image model to draw — MUST be high quality)
Write ONE continuous Chinese paragraph (**简洁干净，控制在约 90-150 字**；用词朴素精确、不堆砌形容词、不写空话套话，一句话能说清就不绕)，描述 ONLY action + environment + atmosphere。It MUST contain:
  1. WHO — refer to each character BY THEIR EXACT NAME as written in the story (e.g. the lead's own name / Mia / Tommy / 一个男孩 ...).
     **NEVER describe any appearance** — no hair, hairstyle, clothes, colors, glasses, age-look, face/features.
     Appearance is 100% locked by the IP reference images downstream; if you write it here you create a WRONG/conflicting character. This is the #1 rule.
     **#1b NEVER RENAME / NEVER SUBSTITUTE (critical — caused real bugs)**:
       - Copy every proper name EXACTLY as the story spells it. If the story says "Anny", write "Anny" — do NOT "correct" it to "Anna" or any series character name. Do NOT swap a story character for a series IP (Mia/Tommy/Anna).
       - **If the protagonist is an ANIMAL or non-human (an ant named Anny, a llama named Lina, a fox, a robot ...), it IS that animal — describe it as that animal/creature, NEVER as a human child, NEVER mapped to Mia/Tommy.** "She/he" for an animal lead stays that animal.
       - Identify the TRUE protagonist(s) of THIS story from the title + text (could be an animal, or Mia + a named friend like Lucia) and keep them consistent across pages — do not invent or drop characters to fit the series.
     **Pronoun resolution (CRITICAL — read the context, do NOT blindly map to Tommy/Mia)**:
     Resolve every "she/her/he/him/it/they/I" to its ACTUAL antecedent in THIS page + previous pages by READING the story.
      - A pronoun may refer to a NON-CHILD subject: a talking object (e.g. the gingerbread man / a toy), an ANIMAL (the fox, the cow, the bear), or an ADULT (dad / mom / grandma / a mechanic). In "He runs past the cow ... says the gingerbread man", "He" = the GINGERBREAD MAN (a cookie), NOT a boy. In a family story "He fixed the car" may = Dad; "She cooked" may = Mom. Resolve to the TRUE subject — never auto-substitute Tommy/Mia.
      - **ANIMAL pronouns carry the ANIMAL's gender, NOT a child mapping (老师强调)**: when "she/he" refers to a small animal (an ant, a llama, a rabbit, a hen ...), it is THAT animal and its gender is the animal's gender — "she" = a female animal (render as a girl/mother animal of that species), "he" = a male animal. NEVER turn "she→Mia" or "he→Tommy" just from the pronoun. Express the gender through that animal (e.g. 一只母羊驼 / 一只小公兔), never by drawing a human child.
      - **FAMILY-ROLE words are SUPPORTING adults, NEVER the protagonist IP (老师强调)**: grandma/grandpa/外婆/奶奶/爷爷/姥姥/mom/妈妈/dad/爸爸/aunt/uncle 等永远画成对应年龄的大人（老人就是老人、妈妈就是成年女性），**绝不映射成 Mia/Tommy 的脸或当主角**。即使系列铁律要求"出现家人→搭配的孩子是 Mia&Tommy"，那也只是说同框的小孩是 Mia/Tommy，**家人本身仍是家人本人**，不能把 grandma 画成 Mia/Tommy。
      - Map a pronoun to Mia/Tommy ONLY when its antecedent is genuinely an UNNAMED human CHILD (a girl→Mia, a boy→Tommy); keep that identity for later pronouns about them.
       - If the sentence is about Anna, then "she/her" = Anna — do NOT pull in Mia or Tommy.
       - "I"/"We" with no name: only treat as Tommy/Mia if the speaker is clearly a child in the story; if the speaker is the gingerbread man/an animal/an adult, use that subject instead.
     **Classic fairy tales** (The Gingerbread Man, Goldilocks, The Three Little Pigs, Little Red Riding Hood ...): the tale's own lead (the gingerbread man, Goldilocks, the pigs, the fox/wolf) is ITS OWN character — render it as itself, NOT as Tommy/Mia. Tommy & Mia appear only if the source frames them as readers/observers (e.g. on the cover). Such fable scenes may legitimately contain NO Tommy/Mia.
     **Child-safe**: any animal or "villain" (fox, wolf, bear ...) must be friendly, cute, gentle-faced — never fangs, never fierce/menacing/scary/ugly.
     Series principle: Tommy (boy) and Mia (girl) are the FIXED protagonists of this whole picture-book SERIES (a SET of books), but ONLY when the story actually features children — do not force them into a pure fable scene.
     Do NOT add any character who is not actually present in this page's sentence; supporting characters max 2, background only.
     **CHARACTER WHITELIST (老师强调 · 防批量串名)**: The ONLY humans you may name are (a) names spelled in THIS story's text, and (b) Mia/Tommy — and Mia/Tommy ONLY as stand-ins for UNNAMED human children per the rules above. You must NOT introduce any other series/registered character (Anna, Ali, Cate, Lucia, Ravi, ...) unless that exact name appears in the story text. If a name is not in the story, it does not exist in these scenes.
  2. WHAT (concrete action verb + body posture + interaction) — e.g. "蹲下伸手指" not just "看着"
  3. WHERE (environment objects you can SEE: desk shape/color, blackboard, books, light source) — cozy and tidy, NOT empty/blank
  4. ATMOSPHERE (warm soft light direction, soft watercolor mood)
Do NOT just translate the English sentence — REWRITE it as a visual scene a painter could draw, but with ZERO appearance words.
Example for "Lily felt nervous on her first day in the new class. Her hands shook as she sat down at a small wooden desk.":
  scene_cn: "教室靠窗的一角，Lily 独自在一张浅色小课桌后坐下，双手紧握放在桌面、微微颤抖，肩膀微微缩起，眉头轻蹙，眼神紧张地望向前方；桌上摊开一本练习本和一支削好的铅笔；背景是干净的暖米白空墙面（无黑板）、亮光浅米瓷砖地面，柔和的早晨阳光从右侧单侧窗户斜射进来，背景极简留白，温暖治愈的薄透水彩氛围。"
  （注意：① 示例名"Lily"仅作演示——真实出图请【逐字照搬故事里的名字】，绝不改名/换成 Mia/Tommy/Anna；② 示例里只有动作、表情、环境、光线——没有任何发型/眼镜/衣服/颜色/长相词。这是必须遵守的写法。）

## CRITICAL: camera_angle（机位角度 — 绝不能全本平视）
- 这是绘本，画面要随剧情变化、有镜头语言。**禁止 7 页全部 eye（平视）**——至少 3-4 页换用非平视机位。
- 按本页内容选最有表现力的机位：
  - eye（平视）：人物对话、情感交流、面部表情为主的页；**也是"孩子在场景里走动/寻找/探访"类剧情页的默认机位**。
  - high（轻俯视）：展示桌面/地面物件、整体场景布局；轻微俯角即可，不要拉成航拍。
  - birdseye（鸟瞰/正俯视）：**仅用于地图、地理、地形、大场景全貌的科普展示**（如海洋/河流/地形俯瞰）。**严禁**把它用在"孩子在社区/公园/街道里走访、找东西、和人对话"这类贴地剧情页——那样不符合孩子视角的代入逻辑。
  - low（仰视）：高大物体（城堡、大树、高楼）、表现宏伟/敬畏/角色被仰望。
  - over_shoulder（越肩/主角视角）：跟随主角看向某物，代入主角视角去观察发现——"孩子在社区里寻找/指认/发现"优先用它或 eye。
- 机位判据：**fiction 里"人物贴地行动/探索/寻找/对话"→ eye 或 over_shoulder（必要时 low）；birdseye/大俯视只给地图/大场景科普。** 把机位与 scene_cn 描述对应起来。

## CRITICAL: focus（每页的"高潮/焦点动作" — 画面的主体，让孩子一翻就被抓住）
- 每页先想清楚："如果只能画一个瞬间，最该画哪一下？" —— 找出本页**最具视觉张力、最关键或最有趣**的那个动作。
- focus 必须是**主角正在做的一个具体动作**（动态、有张力），它将成为画面**居中的视觉主体**：
  - 例："Tommy 俯身张开双手扑向桌下逃窜的小仓鼠"、"Anna 踮脚把书举高递给够不到的同学"、"Mia 猛地推开门、惊喜地张大嘴"。
- focus 与 hook 的区别：focus 是**画面主角的核心动作（占据画面中心、最大）**；hook 是角落/远景的小彩蛋（次要、不抢焦点）。
- focus 必须紧扣本页文字、符合剧情逻辑；scene_cn 要把这个 focus 动作写成画面的主体（居中、动态姿态、表情到位）。
- 【图文必须高度贴合·用户硬要求 2026-06-06】每页画面必须忠实表达**本页文字的具体内容/动作**，
  让读者一看画面就能对应到这页文字。**严禁用空泛、笼统、套路化的画面**（如"几个孩子站在一起把手叠在一起""大家微笑合影"）去敷衍任何一页——尤其是**结尾页**：
  结尾若写"烤饼干带给全班""交到很多朋友并有了计划"，就要画出**这个具体场景/动作**（如 Anna 在厨房端着一盘饼干、或把饼干分给围拢的同学），而不是泛泛的合影/叠手。
- 科普非虚构页：focus = "双主角小探索家正在观察/指认/探向本页科普对象的那一下"（如"Mia 蹲在岸边伸手指向跃出水面的小鱼"）。

## CRITICAL: hook（每页一个趣味彩蛋 — 让绘本"好看、抓人"）
- 每页提炼 1 个有趣的小细节/彩蛋，写一句中文放进 "hook" 字段，并自然融进 scene_cn。
- hook 必须紧扣本页文字、符合剧情逻辑，是"会让小读者会心一笑或想多看一眼"的细节：
  - 例：一只小仓鼠从桌下探头、窗台上打盹的猫、地上滚落的彩色铅笔、墙上歪掉的画、口袋里露出的小纸条。
- hook 要可爱、温馨、安全，绝不喧宾夺主（远景/角落/小道具即可），不与主角抢视觉焦点。
- 科普非虚构页：hook 可以是"双主角小探索家发现的有趣现象"（如水面跃起的小鱼、岸边的小螃蟹）。

## CRITICAL: worksheet content quality (NO placeholder text)
- For match_definition: items=[{{"word": "nervous", "def": "feeling worried about something that will happen"}}, ...]
  → "def" MUST be a real kid-friendly dictionary definition (NOT "meaning of X" or "definition of X")
- For fill_blank/fill_blank_advanced: items=[{{"sentence": "Anna ____ on her first day.", "answer": "felt nervous"}}, ...]
  → sentences MUST be drawn from or paraphrase the actual story
- For inference: items=[{{"q": "Why did Anna help the girl pick up books?", "options": ["She wanted to be kind.", "The teacher told her to.", "She wanted the books for herself."], "correct": 0}}, ...]
  → Each item MUST include "options" (3 strings) and "correct" (int 0/1/2). NO "Question 1?" placeholders.
- For true_false: items=[{{"statement": "Anna shared pencils with a quiet boy.", "answer": "T"}}, ...] (statements from real story facts)
- For all types: NEVER output literal "Option A", "Question N", "sentence N" — these are placeholders, write real content.

## CRITICAL #0 — PAGINATION (LOCKED · non-negotiable · highest priority)
- The book is ALWAYS 8 pages = 1 cover + EXACTLY 7 story pages (every story page has text). You output the 7 story pages, indices 1..7.
- The 7 story pages TOGETHER MUST tell the WHOLE story, from the FIRST event to the ENDING. Page 1 = the very beginning; Page 7 = the ending (the LAST part of the input). NEVER drop the ending. NEVER cover only the first half of the story.
- IF the teacher's input already has explicit page markers (e.g. "Page 1: ...", "P1", numbered lines) → FOLLOW that grouping exactly, one marked block = one page, in order. If they marked more/fewer than 7, merge or split adjacent blocks minimally to land on exactly 7 while respecting their boundaries.
- IF the input is plain prose with NO markers → re-segment the ENTIRE story into 7 BALANCED pages by scene / visual beat. Distribute evenly: roughly (total sentences ÷ 7) sentences per page across the whole arc.
- HARD BANS: do NOT go one-sentence-per-page; do NOT just take the first 7 sentences and ignore the rest; do NOT cram everything into the early pages leaving the later pages empty/thin; do NOT truncate the story.
- Each page = one coherent visual moment a painter could draw. Rewrite into clean book sentences but KEEP the meaning and EVERY key event. Page N+1 must read as the next beat after page N. Whatever story the teacher gives, the 7 pages must finish telling it.

## CRITICAL: vocabulary selection (content words only — NEVER proper nouns)
- Vocabulary = IMPORTANT content words from the story: common NOUNS / VERBS / ADJECTIVES / adverbs that carry meaning and are worth teaching.
- NEVER pick proper nouns: character names (Anna, Mia, Tommy, ...), place names (Scotland, ...), brand names, days, titles. NEVER pick function words (the, a, on, her, was, first/second as ordinals, ...).
- Prefer words that recur or are central to the theme. Each word must actually appear (or its lemma appears) in the story text.

## CRITICAL: DIFFICULTY SPLIT by purpose (teacher-driven · applies to RR vs Worksheet)
There are TWO assessments with DIFFERENT purposes — calibrate difficulty accordingly (keep counts/format unchanged):
- rr_questions = READING REPORT = an ON-SITE quick check the child answers in class on the spot.
  → Make these the SIMPLER set: mostly LITERAL recall the child can locate fast and answer in a few words.
    Short, concrete, single-step; NO multi-step reasoning. The one ⭐⭐⭐ is a LIGHT personal/opinion reflection, not heavy analysis.
    Goal: a child can answer quickly and confidently right after reading.
- worksheet_questions + reading_questions = WORKSHEET = HOME practice homework.
  → Make these a notch HARDER: more inference, cause/effect, application, sentence transformation, and short PRODUCTION/writing.
    The child has time at home, so push one level up in cognitive demand vs the Reading Report — while still age/level appropriate and doable.

## CRITICAL: reading_questions (worksheet Reading page — comprehension tied to the FULL passage)
- Produce EXACTLY {rd_count} questions that test understanding of the story passage (NOT vocabulary, NOT grammar).
- "kind" must be one of: "mc" (3 options A/B/C + correct index 0/1/2), "tf" (a statement + answer "T"/"F"), "short" (open question + model "answer").
- UNIFORM TYPE (HARD): the worksheet Reading page shows ONE single question type. So AT LEAST 4 of the {rd_count} questions MUST share the SAME "kind" (the dominant kind). Do NOT split evenly across kinds.
- Level guidance for the dominant kind: L0-2 → "tf" (≥4 tf); L3-4 → "mc" (≥4 mc); L5-6 → "mc" (≥4 mc; any extra may be "short").
- Cover different layers: literal detail, sequence, cause/effect, inference, main idea. Order easiest → hardest.
- Every question MUST be answerable from the passage. Real content only — NEVER "Question 1?" / "Option A" placeholders.
- "page" = story page the answer is on (2-8); P1 is the cover, never use P1.

## Critical rules
- Vocabulary MUST be in lemma form: 'walk' not 'walks/walking', 'friend' not 'friends'. Lowercase. No punctuation.
- {vocab_rule}
- pages[].scene: NO quoted text/words/sentences (the image generator may render quoted text as visible letters). Describe only visuals.
- pages[].text: keep style consistent with input. Allow fragments, repetition, simple sentence frames for early levels (Style Guide).
- rr_questions: must have exactly {rr_count} questions with star distribution {star_pattern}.
  - Stars 1-2 questions are factual recall and MUST include "page" int **2-8** (P1 = cover, NEVER use P1; story pages are P2-P8).
  - Do NOT embed "(Page X)" or "(P X)" inside the question text — page goes in the "page" field only.
  - The single ⭐⭐⭐ question is the LAST one; it is open-ended/personal/PBL and has page=null.
  - Each question text must end with a question mark.
- worksheet_questions: produce exactly 6 entries, one per type from the pool in order. Each must test specific story content.
  - For unscramble: items=[{{"scrambled": "k l c o", "answer": "lock"}}, ...]
  - For rewrite_tense/rewrite_voice: items=[{{"prompt": "I walk.", "answer": "I walked."}}, ...]
  - For emotion_fill: items=[{{"sentence": "Anna ___ to make friends.", "answer": "wanted"}}, ...], extra="excited, amazed, glad, worried"
  - For story_sequence/word_order/word_order_simple: items=[{{"event": "...", "order": 1}}, ...]
  - For plot_chart/plot_chart_pbl: items=[{{"label": "Setting", "answer": "..."}}, ...], extra="<reflection question>"
  - For draw_favorite/personal_simple/personal_write/open_ended_pbl/essay_short/research_pbl: items=[], extra="<one paragraph prompt>"
  - For color_match/circle_match/word_to_pic: items=[{{"word": "..."}}, ...]
  - For compare_contrast: items=[{{"side_a": "...", "side_b": "...", "topic": "..."}}], extra="<prompt>"
- All English text uses straight quotes only (no curly/smart quotes).

## v2.1 VIPKID 标准题型库（参考用，给学生看的英文 instruction 必须从这套挑）

老师对每页 worksheet 的英文 instruction（副标题）有教学标准要求。请你出的 6 道题，
尽量挑下面这套推荐题型；items 的字段命名要与给出的 schema 匹配，
**worksheet 的标题文字必须用英文短指令**（不要中文），优先用下方 en_instr 原文。

{qtype_recommendation}

注意：
- 听类题型（标 📢）说明纸面没有音频，请生成的题目支持「老师课堂口述」
- 配图题（标 🖼️）需要在 items 里给出 image_hint（page idx 2-8，复用绘本图）
- 即使你用上方 pool 里的旧 type 名（如 fill_blank/inference）兜底，也要确保 items 字段完整可用"""


def _build_user_prompt(raw_story: str, title: str, level: str, cefr: str, theme: str) -> str:
    info = _analyze_pagination(raw_story)
    if info["has_explicit"]:
        page_rule = (
            "PAGINATION (LOCKED): The teacher HAS explicitly marked pages (Page 1 / Page 2 ...). "
            "Follow that exact grouping — one marked block = one page, in order — and output EXACTLY 7 story pages. "
            "If they marked more/fewer than 7, merge or split adjacent blocks minimally to land on 7 while keeping their boundaries. "
            "The 7 pages must still cover the WHOLE story through to the ending."
        )
    else:
        page_rule = (
            "PAGINATION (LOCKED): No explicit page markers. Divide the WHOLE story into EXACTLY 7 BALANCED story pages. "
            f"The input has ~{info['n_sentences']} sentences → aim for about {info['per_page']} sentence(s) per page, spread evenly across the entire arc. "
            "Page 1 = the very beginning; Page 7 = the ENDING (the last part of the input). "
            "Do NOT go one-sentence-per-page, do NOT stop after the first few sentences — the 7 pages TOGETHER must tell the complete story from start to finish, dropping nothing."
        )
    parts = [
        f"Title: {title}",
        f"Level: {level}",
        f"CEFR: {cefr or 'auto'}",
        f"Theme: {theme or 'auto'}",
        "",
        page_rule,
        "",
        "Raw story input from teacher (rewrite into clean book sentences keeping the meaning; obey the PAGINATION rule above):",
        raw_story,
    ]
    return "\n".join(parts)


def _parse_doubao_payload(
    data: dict, level_key: str, is_dual: bool, rr_dist: list[int], raw_story: str,
    *, pool: list[str] | None = None,
) -> ExtractedContent:
    pages = data.get("pages") or []
    pages = [_normalize_page(p, i + 1) for i, p in enumerate(pages[:7])]
    while len(pages) < 7:
        pages.append({"index": len(pages) + 1, "text": "", "scene": "", "expression": "",
                      "shot": "medium", "camera_angle": "", "focus": "", "hook": ""})

    proper = _proper_nouns_from_story(raw_story)
    mastery = _clean_words(data.get("mastery"), proper)
    exposure = _clean_words(data.get("exposure"), proper)
    vocab = _clean_words(data.get("vocabulary"), proper)

    if is_dual:
        if not mastery and vocab:
            mastery = vocab[:4]
        mastery = mastery[:4]
        exposure = exposure[:4]
    else:
        if not vocab:
            vocab = (mastery or exposure)[:4]
        vocab = vocab[:4]
        if len(vocab) < 4:  # 用故事里的真实内容词补足，绝不用 "word" 占位
            for w in _content_word_candidates(raw_story, proper):
                if w not in vocab:
                    vocab.append(w)
                if len(vocab) >= 4:
                    break

    rr_questions = _normalize_rr(data.get("rr_questions"), rr_dist)
    ws_questions = _normalize_ws(data.get("worksheet_questions"), level_key, pool=pool)
    reading_questions = _normalize_reading_questions(data.get("reading_questions"))

    return ExtractedContent(
        pages=pages,
        mastery=mastery,
        exposure=exposure,
        vocabulary=vocab,
        grammar_focus=str(data.get("grammar_focus", "")).strip(),
        phonics=str(data.get("phonics") or data.get("morphology") or "").strip(),
        reader_type=str(data.get("reader_type", "")).strip(),
        word_count=int(data.get("word_count") or _count_words(raw_story)),
        rr_questions=rr_questions,
        worksheet_questions=ws_questions,
        reading_questions=reading_questions,
    )


def _normalize_page(p: dict, default_index: int) -> dict:
    return {
        "index": int(p.get("index") or default_index),
        "text": str(p.get("text") or "").strip(),
        "scene": str(p.get("scene") or "").strip(),
        "scene_cn": str(p.get("scene_cn") or "").strip(),
        "expression": str(p.get("expression") or "").strip(),
        "shot": (str(p.get("shot") or "medium").strip().lower() or "medium"),
        "camera_angle": str(p.get("camera_angle") or "").strip().lower(),
        "focus": str(p.get("focus") or "").strip(),
        "hook": str(p.get("hook") or "").strip(),
    }


def _normalize_rr(items: Any, dist: list[int]) -> list[dict]:
    """规整 AI 抽取的 RR 题目。
    v1.8.3：
      - 题干里把 `(Page X)` / `(P X)` / `（Page X）` 等抽到 page 字段，并从题干删除（避免重复显示）
      - page 强制 ≥ 2（P1 = cover，不应作为答案出处）
      - page 强制 ≤ 1 + 故事页数 (7) = 8，超出则 clamp
    """
    import re as _re
    raw = items if isinstance(items, list) else []
    out: list[dict] = []
    for i, target_stars in enumerate(dist):
        item = raw[i] if i < len(raw) else {}
        q = str(item.get("q") or item.get("question") or f"Question {i + 1}").strip()

        # 抽出题干里的 (Page X) / (P X)，赋给 page 并清洗题干
        embed_page = None
        m = _re.search(r"[\(（]\s*(?:p|page)\s*[:：]?\s*(\d+)\s*[\)）]", q, _re.IGNORECASE)
        if m:
            try:
                embed_page = int(m.group(1))
            except Exception:
                embed_page = None
            q = _re.sub(r"[\(（]\s*(?:p|page)\s*[:：]?\s*\d+\s*[\)）]", "", q, flags=_re.IGNORECASE).strip()
            q = _re.sub(r"\s+", " ", q).strip().rstrip(".?!") + "?"
        if not q.endswith("?"):
            q = q.rstrip(".") + "?"

        stars = int(item.get("stars") or target_stars)
        if stars not in (1, 2, 3):
            stars = target_stars

        if target_stars == 3:
            page = None  # 3⭐ 开放题，不带 P#
        else:
            page = item.get("page") or embed_page
            try:
                page = int(page) if page is not None else (i + 2)
            except Exception:
                page = i + 2
            # P1 是封面 → 至少 P2；最多 P8
            page = max(2, min(8, page))
        answer = str(item.get("answer") or item.get("sample") or "").strip()
        out.append({"q": q, "stars": target_stars, "page": page, "answer": answer})
    return out


def _normalize_reading_questions(items: Any) -> list[dict]:
    """规整 worksheet 阅读理解题。统一成 {kind, q, options, correct, answer, page}。
    丢弃明显占位（'Question N?' / 空题干 / mc 选项不足）。"""
    raw = items if isinstance(items, list) else []
    out: list[dict] = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        q = str(it.get("q") or it.get("question") or "").strip()
        if not q or re.fullmatch(r"question\s*\d*\??", q.lower()):
            continue
        kind = str(it.get("kind") or "").strip().lower()
        opts = [str(o).strip() for o in (it.get("options") or []) if str(o).strip()]
        if not kind:
            kind = "mc" if len(opts) >= 2 else ("tf" if it.get("answer") in ("T", "F", "t", "f") else "short")
        page = it.get("page")
        try:
            page = int(page) if page is not None else None
        except (TypeError, ValueError):
            page = None
        if page is not None and page < 2:
            page = None
        rec: dict = {"kind": kind, "q": q, "page": page}
        if kind == "mc":
            if len(opts) < 2:
                continue
            rec["options"] = opts[:3]
            try:
                rec["correct"] = max(0, min(len(rec["options"]) - 1, int(it.get("correct", 0))))
            except (TypeError, ValueError):
                rec["correct"] = 0
            rec["answer"] = rec["options"][rec["correct"]]
        elif kind == "tf":
            rec["answer"] = "T" if str(it.get("answer", "T")).strip().upper().startswith("T") else "F"
        else:  # short
            rec["kind"] = "short"
            rec["answer"] = str(it.get("answer", "")).strip()
        out.append(rec)
    return out


def _normalize_ws(items: Any, level_key: str, *, pool: list[str] | None = None) -> list[dict]:
    pool = pool or QUESTION_POOL.get(level_key, QUESTION_POOL["4"])
    raw = items if isinstance(items, list) else []
    out: list[dict] = []
    for i in range(6):
        target_type = pool[i] if i < len(pool) else pool[-1]
        src = raw[i] if i < len(raw) else {}
        qtype = str(src.get("type") or target_type).strip().lower() or target_type
        out.append({
            "type": qtype,
            "title": QUESTION_TITLES.get(qtype, qtype.replace("_", " ").title()),
            "instruction": QUESTION_INSTRUCTIONS.get(qtype, ""),
            "items": src.get("items") or [],
            "answer_key": src.get("answer_key"),
            "extra": str(src.get("extra") or "").strip(),
        })
    return out


# 永远不当作词汇的固定 IP 人名 / 常见专有名词种子
_KNOWN_PROPER = {
    "mia", "tommy", "anna", "winnie", "dino", "kim", "ms", "mr", "mrs",
}
# 常以大写出现但不是专有名词的功能词/代词，避免被误判
_NOT_PROPER = {"i", "i'm", "i'll", "i've", "i'd"}


def _proper_nouns_from_story(raw_story: str) -> set[str]:
    """从原文里推断专有名词：出现在句中（非句首）且首字母大写、且全文从未以小写出现过的词。
    叠加固定 IP 人名种子。用于把人名/地名从词汇表里剔除。"""
    proper = set(_KNOWN_PROPER)
    if not raw_story:
        return proper
    cap_mid: set[str] = set()
    seen_lower: set[str] = set()
    # 句首：字符串开头、换行、或 .!?: 之后
    at_start = True
    for m in re.finditer(r"([.!?:\n]+\s*)|([A-Za-z][A-Za-z'’-]*)", raw_story):
        if m.group(1) is not None:
            at_start = True
            continue
        w = m.group(2)
        lw = w.lower().replace("’", "'")
        if lw in _NOT_PROPER:
            at_start = False
            continue
        if w[0].isupper():
            if not at_start:
                cap_mid.add(lw)
        else:
            seen_lower.add(lw)
        at_start = False
    for lw in cap_mid:
        if lw not in seen_lower:
            proper.add(lw)
    return proper


# 高频功能词，做内容词候选时排除
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "so", "to", "of", "in", "on", "at", "for",
    "with", "by", "from", "up", "out", "as", "is", "am", "are", "was", "were", "be",
    "been", "being", "do", "does", "did", "have", "has", "had", "will", "would",
    "shall", "should", "can", "could", "may", "might", "must", "i", "you", "he",
    "she", "it", "we", "they", "me", "him", "her", "us", "them", "my", "your", "his",
    "its", "our", "their", "this", "that", "these", "those", "there", "here", "who",
    "what", "when", "where", "why", "how", "not", "no", "yes", "all", "some", "each",
    "every", "very", "too", "then", "than", "if", "because", "about", "into", "over",
    "under", "again", "one", "two", "first", "next", "now", "day", "said",
}


def _content_word_candidates(raw_story: str, proper: set[str]) -> list[str]:
    """从原文按词频取重要内容词（去停用词/专有名词），用于词表兜底。"""
    counts: dict[str, int] = {}
    for w in re.findall(r"[A-Za-z][A-Za-z'-]*", raw_story or ""):
        lw = w.lower().replace("’", "'")
        if len(lw) < 3 or lw in _STOPWORDS or lw in proper:
            continue
        counts[lw] = counts.get(lw, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def _clean_words(raw: Any, proper: set[str] | None = None) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for w in raw:
        s = str(w).strip().lower().replace("’", "'")
        s = re.sub(r"[^\w\s'-]", "", s)
        s = s.strip()
        if not s or s in out:
            continue
        if proper and s in proper:  # 跳过人名/地名等专有名词
            continue
        out.append(s)
    return out


def _count_words(s: str) -> int:
    return len(re.findall(r"\b\w+\b", s))


def _level_key(level: str) -> str:
    s = str(level).strip().lower()
    if "smart" in s:
        return "smart"
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits or "1"


# ---------- Mock 模式（无 API key 时基于规则回退） ----------
def _mock_extract(
    raw_story: str, title: str, level: str, cefr: str, theme: str,
) -> ExtractedContent:
    sentences = _split_sentences(raw_story)
    pages = []
    for i in range(7):
        idx = i + 1
        if i < len(sentences):
            text = sentences[i].strip()
        else:
            text = ""
        pages.append({
            "index": idx,
            "text": text,
            "scene": _mock_scene(text, idx, theme),
            "expression": _mock_expression(text),
            "shot": "medium",
            "camera_angle": "",
            "focus": "",
            "hook": "",
        })

    level_key = _level_key(level)
    is_dual = level_key in ("smart", "0", "1", "2")
    proper = _proper_nouns_from_story(raw_story)
    words = [w for w in _extract_content_words(raw_story) if w not in proper]
    mastery = words[:4] if is_dual else []
    exposure = words[4:8] if is_dual else []
    vocab = words[:4] if not is_dual else []

    rr_dist = rr_question_distribution(level)
    rr_questions = _mock_rr(pages, rr_dist, words)
    ws_questions = _mock_worksheet(pages, words, level_key, pool=select_question_pool(level_key, _pool_seed(title, level)))
    reading_questions = _mock_reading_questions(pages, level_key)

    return ExtractedContent(
        pages=pages,
        mastery=mastery,
        exposure=exposure,
        vocabulary=vocab,
        reading_questions=reading_questions,
        grammar_focus="一般现在时态" if is_dual else "一般过去时态",
        phonics=(
            f"suffix -ly (= in a way): {', '.join(words[:3])}" if level_key in ("5", "6")
            else f"short vowel pattern: {', '.join(words[:3])}"
        ) if words else "",
        reader_type="Patterned Narrative & Informational Readers" if is_dual else "Fiction",
        word_count=_count_words(raw_story),
        rr_questions=rr_questions,
        worksheet_questions=ws_questions,
    )


def _mock_reading_questions(pages: list[dict], level_key: str) -> list[dict]:
    """mock 阅读理解题：从故事页造 tf / short（无 API key 时兜底）。"""
    story = [p for p in pages if p.get("text")]
    is_low = level_key in ("smart", "0", "1", "2")
    n = 8 if level_key in ("5", "6") else 6
    out: list[dict] = []
    for i, p in enumerate(story):
        if len(out) >= n:
            break
        text = (p.get("text") or "").strip()
        first = text.split(".")[0].strip()
        if not first:
            continue
        page_no = p.get("index", i + 1) + 1  # 故事页 idx1→P2
        if is_low or i % 2 == 0:
            out.append({"kind": "tf", "q": first + ".", "answer": "T", "page": page_no})
        else:
            out.append({"kind": "short", "q": f"What happens here: \"{first}\"?",
                        "answer": first, "page": page_no})
    return out


def _split_sentences(s: str) -> list[str]:
    s = s.replace("\n", " ")
    sents = re.split(r"(?<=[.!?])\s+", s.strip())
    return [x for x in sents if x]


# 显式分页标记：Page 1 / P1 / 第1页 / 1. / 1)  等
_PAGE_MARKER_RE = re.compile(
    r"^\s*(?:page|p|第)\s*\d+\s*[页:：.、)\-]?|^\s*\d+\s*[.):、]\s+", re.IGNORECASE
)


def _analyze_pagination(raw_story: str) -> dict:
    """判断老师的输入是否已显式分页 + 估算均分句数，供 user_prompt 注入锁定规则。"""
    lines = [ln.strip() for ln in (raw_story or "").splitlines() if ln.strip()]
    marked = [ln for ln in lines if _PAGE_MARKER_RE.match(ln)]
    has_explicit = len(marked) >= 3  # 至少 3 处页标记才认定为“老师已显式分页”
    n_sent = len(_split_sentences(raw_story))
    per_page = max(1, round(n_sent / 7)) if n_sent else 1
    return {"has_explicit": has_explicit, "n_sentences": n_sent, "per_page": per_page}


def _mock_scene(text: str, idx: int, theme: str) -> str:
    base = f"Mia and Tommy in a clear children's book scene for page {idx}."
    if text:
        snippet = " ".join(text.split()[:14])
        return f"{base} Visual hints: {snippet}. Soft watercolor, warm tones, ample text whitespace."
    return base


def _mock_expression(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["happy", "smile", "glad", "love", "fun"]):
        return "happy"
    if any(w in t for w in ["worried", "sad", "afraid", "shake"]):
        return "worried"
    if any(w in t for w in ["amazed", "excited", "surprise"]):
        return "excited"
    return "friendly"


def _extract_content_words(s: str) -> list[str]:
    stop = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "of", "for", "with",
        "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does",
        "did", "will", "would", "shall", "should", "can", "could", "may", "might", "must",
        "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", "them",
        "my", "your", "his", "its", "our", "their", "this", "that", "these", "those",
        "all", "any", "some", "no", "not", "from", "by", "as", "if", "than", "then",
        "so", "very", "just", "up", "down", "out", "over", "off",
    }
    words = re.findall(r"\b[a-zA-Z]{3,}\b", s.lower())
    seen: list[str] = []
    for w in words:
        if w not in stop and w not in seen:
            seen.append(w)
    return seen


def _mock_rr(pages: list[dict], dist: list[int], keywords: list[str]) -> list[dict]:
    """mock RR：page 范围 2-8（P1=cover 不当答案出处）。"""
    out: list[dict] = []
    for i, stars in enumerate(dist):
        page_idx = min(i + 2, 8) if stars != 3 else None
        if stars == 1:
            q = "What is the first thing that happens in the story?"
        elif stars == 2:
            kw = keywords[(i + 1) % max(1, len(keywords))] if len(keywords) > 1 else "story"
            q = f"What does the passage say about {kw}?"
        else:
            q = "What is your favorite part of this story, and why?"
        out.append({"q": q, "stars": stars, "page": page_idx})
    return out


def _mock_worksheet(pages: list[dict], words: list[str], level_key: str, *, pool: list[str] | None = None) -> list[dict]:
    pool = pool or QUESTION_POOL.get(level_key, QUESTION_POOL["4"])
    out: list[dict] = []
    for qtype in pool:
        items: list[dict] = []
        extra = ""
        if qtype in ("match_definition",):
            for w in words[:5]:
                items.append({"word": w, "def": f"meaning of {w}"})
        elif qtype in ("fill_blank", "fill_blank_simple", "fill_blank_advanced"):
            for i, p in enumerate(pages[:4]):
                t = p.get("text", "")
                w = words[i] if i < len(words) else "word"
                if w in t.lower():
                    blanked = re.sub(re.escape(w), "____", t, count=1, flags=re.I)
                else:
                    blanked = t.replace(t.split()[0], "____", 1) if t.split() else "____"
                items.append({"sentence": blanked, "answer": w})
        elif qtype in ("true_false", "true_false_simple"):
            for p in pages[:4]:
                if p.get("text"):
                    items.append({"statement": p["text"], "answer": "T"})
        elif qtype == "unscramble":
            for w in words[:4]:
                scrambled = " ".join(sorted(w))
                items.append({"scrambled": scrambled, "answer": w})
        elif qtype in ("rewrite_tense", "rewrite_voice"):
            for p in pages[:4]:
                if p.get("text"):
                    items.append({"prompt": p["text"], "answer": p["text"]})
        elif qtype == "emotion_fill":
            extra = "excited, amazed, glad, worried"
            for p in pages[:4]:
                if p.get("text"):
                    items.append({"sentence": re.sub(r"\b(excited|amazed|glad|worried)\b", "____", p["text"], count=1, flags=re.I), "answer": "excited"})
        elif qtype in ("plot_chart", "plot_chart_pbl"):
            items = [
                {"label": "Setting", "answer": pages[0].get("text", "")},
                {"label": "Problem", "answer": pages[3].get("text", "")},
                {"label": "Solution", "answer": pages[5].get("text", "")},
                {"label": "Lesson", "answer": pages[6].get("text", "")},
            ]
            extra = "Why did the characters act this way? What did they learn?"
        elif qtype in ("draw_favorite", "personal_simple", "personal_write",
                       "open_ended_pbl", "essay_short", "research_pbl"):
            extra = "Draw or write about your favorite part of the book and why."
        elif qtype in ("color_match", "circle_match", "word_to_pic"):
            for w in words[:4]:
                items.append({"word": w})
        elif qtype == "compare_contrast":
            items = [{"side_a": "Story start", "side_b": "Story end", "topic": "the main characters"}]
            extra = "How did the characters change?"
        elif qtype == "inference":
            for i, p in enumerate(pages[:4]):
                items.append({"q": f"What can we infer from page {i + 2}?", "page": i + 2})
        elif qtype in ("word_order", "word_order_simple", "story_sequence"):
            for i, p in enumerate(pages[:4]):
                if p.get("text"):
                    items.append({"event": p["text"], "order": i + 1})
        out.append({
            "type": qtype,
            "title": QUESTION_TITLES.get(qtype, qtype.replace("_", " ").title()),
            "instruction": QUESTION_INSTRUCTIONS.get(qtype, ""),
            "items": items,
            "answer_key": None,
            "extra": extra,
        })
    return out


# ---------- 工具：把 ExtractedContent 套到 BookOutline ----------
def apply_extracted_to_outline(outline, ec: ExtractedContent) -> None:
    """把抽取结果填入已有的 BookOutline（in-place）。"""
    from parser import PageSpec  # avoid circular at import time

    if outline.is_dual_vocab_level:
        if ec.mastery:
            outline.vocabulary_mastery = ec.mastery
        if ec.exposure:
            outline.vocabulary_exposure = ec.exposure
    else:
        if ec.vocabulary:
            outline.vocabulary_simple = ec.vocabulary

    if ec.phonics:
        outline.phonics = ec.phonics
    if ec.grammar_focus:
        outline.grammar_focus = ec.grammar_focus
    if ec.reader_type:
        outline.reader_type = ec.reader_type
    if ec.word_count and not outline.word_count_override:
        outline.word_count_override = str(ec.word_count)
    if ec.reading_questions:
        setattr(outline, "_reading_questions", ec.reading_questions)

    for p in ec.pages:
        idx = int(p.get("index") or 0)
        if 1 <= idx <= 7 and idx < len(outline.pages):
            page = outline.pages[idx]
            if p.get("text"):
                page.text = p["text"]
            if p.get("scene"):
                page.scene = p["scene"]
            if p.get("scene_cn"):
                page.scene_cn = p["scene_cn"]
            if p.get("expression"):
                page.expression = p["expression"]
            if p.get("shot"):
                page.shot = p["shot"]
            if p.get("camera_angle"):
                page.camera_angle = p["camera_angle"]
            if p.get("focus"):
                page.focus = p["focus"]
            if p.get("hook"):
                page.hook = p["hook"]
