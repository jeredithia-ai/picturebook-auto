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

import json
import re
from dataclasses import dataclass, field
from typing import Any

from config import (
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
    try:
        return _doubao_extract(raw_story, title, level, cefr, theme)
    except Exception as e:
        print(f"[ai_extractor] Doubao 调用失败 ({e})，回退 mock 模式")
        return _mock_extract(raw_story, title, level, cefr, theme)


# ---------- 真实调用（2026-06-02 已切到 imarouter Claude/GPT，走 deepseek_chat 健壮封装）----------
def _doubao_extract(
    raw_story: str, title: str, level: str, cefr: str, theme: str,
) -> ExtractedContent:
    from deepseek_client import deepseek_chat

    level_key = _level_key(level)
    is_dual = level_key in ("smart", "0", "1", "2")
    rr_dist = rr_question_distribution(level)
    pool = QUESTION_POOL.get(level_key, QUESTION_POOL["4"])

    system_prompt = _build_system_prompt(level_key, is_dual, rr_dist, pool)
    user_prompt = _build_user_prompt(raw_story, title, level, cefr, theme)
    # 追加：Claude 不一定支持 response_format，强制要求纯 JSON 输出
    system_prompt += "\n\n严格要求：只输出一个 JSON 对象，不要任何解释、不要 markdown 代码块包裹。"

    raw = deepseek_chat(
        system=system_prompt,
        user=user_prompt,
        max_tokens=16000,  # 抽取 JSON 较大（pages+scene_cn+题目），防截断
        json_mode=True,  # 不支持时 deepseek_chat 会自动剔除 response_format 重试
        timeout=240,
    )
    data = json.loads(_extract_json_block(raw))
    return _parse_doubao_payload(data, level_key, is_dual, rr_dist, raw_story)


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
        max_tokens=2000,
        json_mode=True,
        timeout=120,
    )
    data = json.loads(_extract_json_block(raw))
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
      "scene_cn": "<一段连贯中文画面描述，120-220字，包含：主体（人物+具体外观锁定）+ 动作 + 环境物品 + 光照氛围，写得越具体越好，不分段不列点>",
      "expression": "<one-word emotion>",
      "shot": "medium"
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
    {{"q": "<English question, NO embedded (P#) in question text>", "stars": 1, "page": 2}},
    ... {rr_count} entries with stars distribution {star_pattern}
  ],
  "worksheet_questions": [
    {{"type": "<one of: {pool_str}>", "items": [...], "answer_key": [...], "extra": "<optional context>"}},
    ... 6 entries, one of each type from the pool
  ]
}}

## CRITICAL: pages[].scene_cn (used by Doubao Seedream 4.5 to draw images — MUST be high quality)
Write ONE continuous Chinese paragraph (120-220 字) that contains ALL of:
  1. WHO (with explicit appearance lock: hair/clothes/age/glasses if any) — names from story, OR generic "girl/boy" as fallback to Mia/Tommy
  2. WHAT (concrete action verb + body posture + interaction) — e.g. "蹲下伸手指" not just "看着"
  3. WHERE (environment objects you can SEE: desk shape/color, blackboard, hamster, books, light source)
  4. ATMOSPHERE (warm morning light from right window, soft watercolor)
Do NOT just translate the English story sentence — REWRITE it as a visual scene a painter could draw.
Example for "Anna felt nervous on her first day in the new class. Her hands shook as she sat down at a small wooden desk.":
  scene_cn: "教室一角，12 岁亚洲女孩 Anna 戴琥珀色细框眼镜、黑色长发扎两条低马尾分别垂在两肩前、穿芥末黄色长袖针织开衫和灰色及膝裙、坐在一张浅棕色木质小课桌后，双手紧握放在桌面微微颤抖，眼神紧张地看向左前方；桌上摊开一本练习本和一支削好的铅笔；背景是浅米色墙面，可见一块淡绿色黑板和几张同样的木课桌，柔和的早晨阳光从右侧窗户斜射入，温暖治愈的水彩氛围。"

## CRITICAL: worksheet content quality (NO placeholder text)
- For match_definition: items=[{{"word": "nervous", "def": "feeling worried about something that will happen"}}, ...]
  → "def" MUST be a real kid-friendly dictionary definition (NOT "meaning of X" or "definition of X")
- For fill_blank/fill_blank_advanced: items=[{{"sentence": "Anna ____ on her first day.", "answer": "felt nervous"}}, ...]
  → sentences MUST be drawn from or paraphrase the actual story
- For inference: items=[{{"q": "Why did Anna help the girl pick up books?", "options": ["She wanted to be kind.", "The teacher told her to.", "She wanted the books for herself."], "correct": 0}}, ...]
  → Each item MUST include "options" (3 strings) and "correct" (int 0/1/2). NO "Question 1?" placeholders.
- For true_false: items=[{{"statement": "Anna shared pencils with a quiet boy.", "answer": "T"}}, ...] (statements from real story facts)
- For all types: NEVER output literal "Option A", "Question N", "sentence N" — these are placeholders, write real content.

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
    parts = [
        f"Title: {title}",
        f"Level: {level}",
        f"CEFR: {cefr or 'auto'}",
        f"Theme: {theme or 'auto'}",
        "",
        "Raw story input from teacher (split into 7 pages, rewrite into clean book sentences keeping the meaning):",
        raw_story,
    ]
    return "\n".join(parts)


def _parse_doubao_payload(
    data: dict, level_key: str, is_dual: bool, rr_dist: list[int], raw_story: str,
) -> ExtractedContent:
    pages = data.get("pages") or []
    pages = [_normalize_page(p, i + 1) for i, p in enumerate(pages[:7])]
    while len(pages) < 7:
        pages.append({"index": len(pages) + 1, "text": "", "scene": "", "expression": "", "shot": "medium"})

    mastery = _clean_words(data.get("mastery"))
    exposure = _clean_words(data.get("exposure"))
    vocab = _clean_words(data.get("vocabulary"))

    if is_dual:
        if not mastery and vocab:
            mastery = vocab[:4]
        mastery = mastery[:4]
        exposure = exposure[:4]
    else:
        if not vocab:
            vocab = (mastery or exposure)[:4]
        vocab = vocab[:4]
        while len(vocab) < 4:
            vocab.append("word")

    rr_questions = _normalize_rr(data.get("rr_questions"), rr_dist)
    ws_questions = _normalize_ws(data.get("worksheet_questions"), level_key)

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
    )


def _normalize_page(p: dict, default_index: int) -> dict:
    return {
        "index": int(p.get("index") or default_index),
        "text": str(p.get("text") or "").strip(),
        "scene": str(p.get("scene") or "").strip(),
        "scene_cn": str(p.get("scene_cn") or "").strip(),
        "expression": str(p.get("expression") or "").strip(),
        "shot": (str(p.get("shot") or "medium").strip().lower() or "medium"),
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
        out.append({"q": q, "stars": target_stars, "page": page})
    return out


def _normalize_ws(items: Any, level_key: str) -> list[dict]:
    pool = QUESTION_POOL.get(level_key, QUESTION_POOL["4"])
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


def _clean_words(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for w in raw:
        s = str(w).strip().lower()
        s = re.sub(r"[^\w\s'-]", "", s)
        s = s.strip()
        if s and s not in out:
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
        })

    level_key = _level_key(level)
    is_dual = level_key in ("smart", "0", "1", "2")
    words = _extract_content_words(raw_story)
    mastery = words[:4] if is_dual else []
    exposure = words[4:8] if is_dual else []
    vocab = words[:4] if not is_dual else []

    rr_dist = rr_question_distribution(level)
    rr_questions = _mock_rr(pages, rr_dist, words)
    ws_questions = _mock_worksheet(pages, words, level_key)

    return ExtractedContent(
        pages=pages,
        mastery=mastery,
        exposure=exposure,
        vocabulary=vocab,
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


def _split_sentences(s: str) -> list[str]:
    s = s.replace("\n", " ")
    sents = re.split(r"(?<=[.!?])\s+", s.strip())
    return [x for x in sents if x]


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


def _mock_worksheet(pages: list[dict], words: list[str], level_key: str) -> list[dict]:
    pool = QUESTION_POOL.get(level_key, QUESTION_POOL["4"])
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
