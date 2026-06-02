"""Worksheet 题型库（按 VIPKID 教研标准 + 教师评估优化）。

3 大类 × 难度分级，共 30 个题型：
- Vocabulary 词汇类：11 个
- Sentences 句型类：9 个
- Reading 阅读类：10 个

每个题型：
  id            内部唯一 key
  category      vocab/sentence/reading
  en_title      worksheet 大标题用（如 Vocabulary/Sentence/Reading）
  en_instr      worksheet 副标题用（英文 instruction，给学生看）
  stars         1/2/3 难度
  needs_audio   是否需要老师口述（True → worksheet 加 📢 Teacher reads aloud）
  needs_image   是否需要配图（True → worksheet 在题项旁画/占位图）
  format        提示 builder 的版式：match_2col / fill_blank / mcq / 
                tick_word / scrambled_letters / missing_letters / sort_cards / 
                connect_lines / write_open / etc.
  ai_items_schema  AI 抽取时 items 的字段结构（给 ai_extractor prompt 用）

按 level 自动挑选 6 道题（3 大类各 2 道）的策略：
- L0/L1/Smart: 4⭐ + 1⭐⭐ + 1⭐⭐⭐
- L2/L3:       2⭐ + 3⭐⭐ + 1⭐⭐⭐
- L4:          1⭐ + 3⭐⭐ + 2⭐⭐⭐
- L5/L6:       1⭐ + 2⭐⭐ + 3⭐⭐⭐
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class QuestionType:
    id: str
    category: str          # vocab / sentence / reading
    en_title: str          # 大标题（Worksheet 页面顶部）
    en_instr: str          # 副标题（instruction，给学生看）
    stars: int             # 1 / 2 / 3
    needs_audio: bool = False
    needs_image: bool = False
    format: str = "mcq"
    ai_items_schema: str = ""


# ============================================================
# Vocabulary 11 个
# ============================================================
_VOCAB: list[QuestionType] = [
    QuestionType(
        id="vocab_tick_word",
        category="vocab", en_title="Vocabulary",
        en_instr="Look at the picture and tick the correct word.",
        stars=1, needs_image=True, format="tick_word",
        ai_items_schema='[{"image_hint":"<page idx 2-8 to reuse>","options":["...","..."],"correct":0}, ...]',
    ),
    QuestionType(
        id="vocab_listen_circle",
        category="vocab", en_title="Vocabulary",
        en_instr="Listen and circle the word you hear.",
        stars=1, needs_audio=True, format="circle_word",
        ai_items_schema='[{"target":"nervous","distractors":["near","never"]}, ...]',
    ),
    QuestionType(
        id="vocab_match_picture",
        category="vocab", en_title="Vocabulary",
        en_instr="Match the picture with the word.",
        stars=1, needs_image=True, format="connect_lines",
        ai_items_schema='[{"word":"hamster","image_hint":"<page idx>"}, ...]',
    ),
    QuestionType(
        id="vocab_rearrange_letters",
        category="vocab", en_title="Vocabulary",
        en_instr="Rearrange the letters to spell the word.",
        stars=2, format="scrambled_letters",
        ai_items_schema='[{"scrambled":"k l c o","answer":"lock"}, ...]',
    ),
    QuestionType(
        id="vocab_missing_letters",
        category="vocab", en_title="Vocabulary",
        en_instr="Fill in the missing letters to complete the word.",
        stars=2, format="missing_letters",
        ai_items_schema='[{"masked":"n_rv__s","answer":"nervous"}, ...]',
    ),
    QuestionType(
        id="vocab_judge_match",
        category="vocab", en_title="Vocabulary",
        en_instr="Judge if the word matches the picture.",
        stars=2, needs_image=True, format="true_false",
        ai_items_schema='[{"image_hint":"<page idx>","word":"hamster","answer":"T"}, ...]',
    ),
    QuestionType(
        id="vocab_phonics",
        category="vocab", en_title="Vocabulary",
        en_instr="Circle the word with the same sound.",
        stars=2, format="circle_word",
        ai_items_schema='[{"target_sound":"-ous","words":["nervous","family","famous"],"correct":[0,2]}, ...]',
    ),
    QuestionType(
        id="vocab_fill_blank",
        category="vocab", en_title="Vocabulary",
        en_instr="Use the words to fill each blank.",
        stars=3, format="fill_blank",
        ai_items_schema='[{"sentence":"Anna felt ____ on her first day.","answer":"nervous"}, ...]',
    ),
    QuestionType(
        id="vocab_sort_categories",
        category="vocab", en_title="Vocabulary",
        en_instr="Sort the words into the correct categories.",
        stars=3, format="sort_cards",
        ai_items_schema='{"categories":["Feelings","Actions"],"words":[{"word":"nervous","cat":0}, ...]}',
    ),
    QuestionType(
        id="vocab_spelling_dictation",
        category="vocab", en_title="Vocabulary",
        en_instr="Listen and write the word.",
        stars=3, needs_audio=True, format="write_word",
        ai_items_schema='[{"target":"nervous"}, ...]',
    ),
    # 补充：词↔定义匹配（用户题型库缺，但是 L3+ 核心训练）
    QuestionType(
        id="vocab_match_definition",
        category="vocab", en_title="Vocabulary",
        en_instr="Match the words to their definitions.",
        stars=3, format="match_2col",
        ai_items_schema='[{"word":"nervous","def":"feeling worried and not calm"}, ...]',
    ),
]


# ============================================================
# Sentences 9 个
# ============================================================
_SENTENCE: list[QuestionType] = [
    QuestionType(
        id="sent_tick_sentence",
        category="sentence", en_title="Sentence",
        en_instr="Look at the picture and tick the correct sentence.",
        stars=1, needs_image=True, format="tick_sentence",
        ai_items_schema='[{"image_hint":"<page idx>","options":["...","..."],"correct":0}, ...]',
    ),
    QuestionType(
        id="sent_match_picture",
        category="sentence", en_title="Sentence",
        en_instr="Match the sentence with the picture.",
        stars=1, needs_image=True, format="connect_lines",
        ai_items_schema='[{"sentence":"...","image_hint":"<page idx>"}, ...]',
    ),
    QuestionType(
        id="sent_true_false",
        category="sentence", en_title="Sentence",
        en_instr="Read the sentences and write T (True) or F (False).",
        stars=2, format="true_false",
        ai_items_schema='[{"statement":"Anna shared pencils.","answer":"T"}, ...]',
    ),
    QuestionType(
        id="sent_fill_blank",
        category="sentence", en_title="Sentence",
        en_instr="Choose the correct words to complete the sentences.",
        stars=2, format="fill_blank",
        ai_items_schema='[{"sentence":"Anna ____ pencils with a boy.","answer":"shared"}, ...]',
    ),
    QuestionType(
        id="sent_put_in_order",
        category="sentence", en_title="Sentence",
        en_instr="Put the sentences in the correct order.",
        stars=2, format="sequence",
        ai_items_schema='[{"text":"Anna sat down at a wooden desk.","order":1}, ...]',
    ),
    QuestionType(
        id="sent_q_a_match",
        category="sentence", en_title="Sentence",
        en_instr="Match the questions with the correct answers.",
        stars=3, format="match_2col",
        ai_items_schema='[{"q":"How did Anna feel?","a":"Nervous."}, ...]',
    ),
    QuestionType(
        id="sent_write_from_picture",
        category="sentence", en_title="Sentence",
        en_instr="Write a sentence about each picture.",
        stars=3, needs_image=True, format="write_open",
        ai_items_schema='[{"image_hint":"<page idx>","hint":"Anna feels ___."}, ...]',
    ),
    QuestionType(
        id="sent_rewrite",
        category="sentence", en_title="Sentence",
        en_instr="Rewrite each sentence following the example.",
        stars=3, format="rewrite",
        ai_items_schema='{"example":{"from":"...","to":"..."},"items":[{"prompt":"...","answer":"..."}, ...]}',
    ),
    QuestionType(
        id="sent_correct_grammar",
        category="sentence", en_title="Sentence",
        en_instr="Find and correct the grammar mistake in each sentence.",
        stars=3, format="rewrite",
        ai_items_schema='[{"wrong":"Anna feel nervous.","correct":"Anna feels nervous."}, ...]',
    ),
]


# ============================================================
# Reading 9 个
# ============================================================
_READING: list[QuestionType] = [
    QuestionType(
        id="read_words_with_picture",
        category="reading", en_title="Reading",
        en_instr="Read the words and point to the matching picture.",
        stars=1, needs_image=True, format="connect_lines",
        ai_items_schema='[{"word":"hamster","image_hint":"<page idx>"}, ...]',
    ),
    QuestionType(
        id="read_listen_point",
        category="reading", en_title="Reading",
        en_instr="Listen and point to the sentence you hear.",
        stars=1, needs_audio=True, needs_image=True, format="tick_sentence",
        ai_items_schema='[{"audio_hint":"...","image_hint":"<page idx>"}, ...]',
    ),
    QuestionType(
        id="read_short_qa",
        category="reading", en_title="Reading",
        en_instr="Read the sentences and answer the questions.",
        stars=2, format="short_answer",
        ai_items_schema='[{"q":"What did Anna do at recess?","answer":"She helped pick up books."}, ...]',
    ),
    QuestionType(
        id="read_match_story",
        category="reading", en_title="Reading",
        en_instr="Match the pictures with the story content.",
        stars=2, needs_image=True, format="connect_lines",
        ai_items_schema='[{"image_hint":"<page idx>","summary":"Anna helps a girl pick up books."}, ...]',
    ),
    QuestionType(
        id="read_true_false_story",
        category="reading", en_title="Reading",
        en_instr="Read the story and write T (True) or F (False).",
        stars=2, format="true_false",
        ai_items_schema='[{"statement":"Anna shared pencils with a girl.","answer":"F"}, ...]',
    ),
    QuestionType(
        id="read_mc_questions",
        category="reading", en_title="Reading",
        en_instr="Choose the correct answer for each question.",
        stars=3, format="mcq",
        ai_items_schema='[{"q":"What did the hamster grab?","options":["A pencil","An eraser","A book"],"correct":1}, ...]',
    ),
    QuestionType(
        id="read_sequence_events",
        category="reading", en_title="Reading",
        en_instr="Put the events in the correct order.",
        stars=3, format="sequence",
        ai_items_schema='[{"event":"Anna helped pick up the books.","order":1}, ...]',
    ),
    QuestionType(
        id="read_summarize",
        category="reading", en_title="Reading",
        en_instr="Write 3-5 sentences to summarize the story.",
        stars=3, format="write_open",
        ai_items_schema='{"hint":"Use these words: nervous, share, kind, friends"}',
    ),
    QuestionType(
        id="read_extended_qa",
        category="reading", en_title="Reading",
        en_instr="Answer the extended questions about the story.",
        stars=3, format="short_answer",
        ai_items_schema='[{"q":"What would you do on your first day?","hint":"Open-ended; encourage 2-3 sentences."}, ...]',
    ),
]


# 全部
ALL_TYPES: list[QuestionType] = _VOCAB + _SENTENCE + _READING


def get_type(qid: str) -> Optional[QuestionType]:
    for t in ALL_TYPES:
        if t.id == qid:
            return t
    return None


def list_by_category(category: str) -> list[QuestionType]:
    """category in (vocab, sentence, reading)。"""
    return [t for t in ALL_TYPES if t.category == category]


def list_by_stars(stars: int) -> list[QuestionType]:
    return [t for t in ALL_TYPES if t.stars == stars]


# ============================================================
# 按 level 推荐 6 道题（3 大类各 2 道，难度按 level 分布）
# ============================================================
_DIFFICULTY_PROFILE: dict[str, tuple[int, int, int]] = {
    # level → (n_star1, n_star2, n_star3) 总和必须 = 6
    "smart": (4, 1, 1),
    "0":     (4, 1, 1),
    "1":     (4, 1, 1),
    "2":     (2, 3, 1),
    "3":     (2, 3, 1),
    "4":     (1, 3, 2),
    "5":     (1, 2, 3),
    "6":     (1, 2, 3),
}


def recommend_question_set(level: str) -> list[QuestionType]:
    """按 level 返回推荐的 6 道题型（3 大类各 2 道 + 难度分布匹配）。

    返回顺序：[vocab1, vocab2, sentence1, sentence2, reading1, reading2]
    """
    key = str(level or "5").strip().lower().lstrip("l").strip()
    if "smart" in str(level).lower():
        key = "smart"
    if key not in _DIFFICULTY_PROFILE:
        key = "5"

    n1, n2, n3 = _DIFFICULTY_PROFILE[key]

    # 在每个 category 里挑 2 道，按 level 分布
    out: list[QuestionType] = []
    for cat in ("vocab", "sentence", "reading"):
        cat_types = list_by_category(cat)
        # 按 star 分组
        by_star = {s: [t for t in cat_types if t.stars == s] for s in (1, 2, 3)}
        # 在这个 category 里挑 2 个题型 — 优先按 level 难度分布的星级
        # 简化策略：按 n1>n2>n3 排序优先级，取前 2 星级最多的
        star_order = sorted((1, 2, 3), key=lambda s: -[n1, n2, n3][s - 1])
        picked: list[QuestionType] = []
        for s in star_order:
            for t in by_star.get(s, []):
                picked.append(t)
                if len(picked) >= 2:
                    break
            if len(picked) >= 2:
                break
        out.extend(picked[:2])

    return out


# ============================================================
# 给 AI prompt 用：题型推荐表的人类可读描述
# ============================================================
def render_recommendation_for_prompt(level: str) -> str:
    """生成给 ai_extractor 用的 6 道题型清单 markdown。"""
    types = recommend_question_set(level)
    lines = [f"## Recommended worksheet 6 questions for Level {level}", ""]
    for i, t in enumerate(types, 1):
        audio = " 📢" if t.needs_audio else ""
        image = " 🖼️" if t.needs_image else ""
        lines.append(
            f"{i}. **[{t.category}]** *{t.en_title}* — {t.en_instr} "
            f"({'⭐' * t.stars}{audio}{image})  \n"
            f"   format={t.format}; items schema: `{t.ai_items_schema}`"
        )
    return "\n".join(lines)
