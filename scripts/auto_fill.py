"""v1.8.2 自动补全工具（让网页端必填项最小化）。

输入只需要 **故事原文 + 级别**，其余字段全部自动：
  - lexile_for_level(level)           → 蓝思值字符串
  - cefr_for_level(level)             → CEFR 等级
  - infer_fiction_type(story_text)    → "fiction" / "non-fiction"
  - infer_theme(story_text, title)    → 主题关键词
  - count_story_words(story_text)     → 故事正文字数
  - detect_characters_in_story(text)  → 故事里出现的已注册 IP 列表
  - auto_book_number()                → "01" 默认值

UI 端只需调用 `auto_summary(level, story_text, title)` 拿到 dict，把它当只读"AI 推断卡片"展示，
让用户能一眼看到、并允许覆盖任意一项。
"""
from __future__ import annotations

import re
from typing import Optional

from character_registry import REGISTRY, get_character


# ============================================================
#  级别 → CEFR / Lexile / 词汇难度
# ============================================================

# CEFR 按 VIPKID Dino Reading Club 内部标准
_CEFR_MAP = {
    "smart": "Pre-A1",
    "0": "Pre-A1",
    "1": "Pre-A1",
    "2": "A1",
    "3": "A1+",
    "4": "A2",
    "5": "B1",
    "6": "B1+",
}

# 蓝思 Lexile 按 VIPKID Dino 内部口径（区间值，便于和 CEFR 对应）
# 参考 MetaMetrics CEFR↔Lexile：
#   Pre-A1: BR (Beginning Reader, < 0L)
#   A1:     50L - 250L
#   A2:     300L - 500L
#   B1:     550L - 800L
#   B1+:    800L - 1000L
_LEXILE_MAP = {
    "smart": "BR",
    "0": "BR-100L",
    "1": "100L-200L",
    "2": "200L-300L",
    "3": "300L-450L",
    "4": "450L-600L",
    "5": "600L-750L",
    "6": "750L-900L",
}


def _level_key(level: str) -> str:
    key = str(level or "").strip().lower()
    if "smart" in key:
        return "smart"
    digits = "".join(ch for ch in key if ch.isdigit())
    return digits if digits else "1"


def cefr_for_level(level: str) -> str:
    """按级别返回 CEFR 等级（不带 'CEFR' 前缀）。"""
    return _CEFR_MAP.get(_level_key(level), "A1")


def lexile_for_level(level: str) -> str:
    """按级别返回蓝思 Lexile 区间字符串。"""
    return _LEXILE_MAP.get(_level_key(level), "100L-200L")


# ============================================================
#  故事正文字数 / 故事类型 / 主题推断
# ============================================================

def count_story_words(story_text: str) -> int:
    """统计故事正文 word count（拉丁字符词数，忽略中文）。"""
    if not story_text:
        return 0
    words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", story_text)
    return len(words)


# 非小说常见关键词（事实陈述 / 知识类）
_NONFIC_KEYWORDS = {
    "are", "is", "have", "has", "live", "lives", "eat", "eats",
    "many", "some", "most", "every", "all", "they",
    "kinds of", "types of", "facts", "fact", "called",
    "around the world", "for example",
    "consist", "consists",
    "weighs", "measures",
}

# 小说常见关键词（叙事 / 人物对话）
_FIC_KEYWORDS = {
    "said", "asked", "shouted", "whispered", "smiled", "laughed",
    "felt", "thought", "wondered", "shook", "ran", "went",
    "yesterday", "one day", "then", "later", "suddenly",
    "happily ever after", "long ago",
}


def infer_fiction_type(story_text: str) -> str:
    """按文本启发式判断 fiction vs non-fiction。

    返回 'fiction' 或 'non-fiction'。
    判定规则：
      1) 含已知人名（registry 里的 protagonist/supporting key/alias）→ fiction
      2) 含 said/asked/shouted/... 等叙事词 ≥ 2 个 → fiction
      3) 第一人称 (I/we) + 过去时 → fiction
      4) 含 NONFIC_KEYWORDS ≥ 3 → non-fiction
      5) 默认 fiction（绘本绝大多数是 fiction）
    """
    if not story_text:
        return "fiction"
    text = story_text.lower()

    # 1) 人名 hit
    proto_names = set()
    for key, char in REGISTRY.items():
        if char.get("kind") in ("protagonist", "supporting", "adult", "family"):
            proto_names.add(key)
            for alias in char.get("aliases", []):
                proto_names.add(alias.lower())
    name_hits = sum(1 for name in proto_names if re.search(rf"\b{name}\b", text))
    if name_hits >= 1:
        return "fiction"

    # 2) 叙事词
    fic_hits = sum(1 for kw in _FIC_KEYWORDS if kw in text)
    if fic_hits >= 2:
        return "fiction"

    # 3) NONFIC 关键词
    nonfic_hits = sum(1 for kw in _NONFIC_KEYWORDS if kw in text)
    if nonfic_hits >= 3 and fic_hits == 0:
        return "non-fiction"

    return "fiction"


# 主题候选词典（按高频主题）
_THEME_KEYWORDS = {
    "friendship": {"friend", "friends", "share", "kind", "help"},
    "family": {"mom", "dad", "mother", "father", "family", "sister", "brother", "grandma", "grandpa"},
    "school": {"school", "class", "teacher", "classroom", "recess", "lesson"},
    "animals": {"dog", "cat", "rabbit", "hamster", "bird", "pet", "zoo", "animal"},
    "travel": {"travel", "trip", "journey", "visit", "country", "city"},
    "nature": {"tree", "flower", "river", "mountain", "forest", "sun", "moon"},
    "food": {"food", "eat", "cook", "lunch", "dinner", "breakfast", "cake", "cookie"},
    "feelings": {"happy", "sad", "angry", "nervous", "excited", "scared", "proud"},
    "growing up": {"first", "new", "learn", "try", "brave", "grow"},
    "sports": {"play", "game", "ball", "run", "swim", "team", "win"},
}


def infer_theme(story_text: str, title: str = "") -> str:
    """按故事文本启发式推断主题。返回 1-2 个主题词逗号分隔。"""
    text = (story_text + " " + title).lower()
    scored = []
    for theme, words in _THEME_KEYWORDS.items():
        hit = sum(1 for w in words if re.search(rf"\b{w}\b", text))
        if hit > 0:
            scored.append((hit, theme))
    if not scored:
        return ""
    scored.sort(reverse=True)
    # 取前 2 个主题
    return ", ".join(t for _, t in scored[:2])


# ============================================================
#  角色识别（透明化展示给用户）
# ============================================================

def _build_alias_index() -> dict[str, str]:
    """构建 alias→key 反向索引，便于扫描时快速识别。"""
    index: dict[str, str] = {}
    for key, char in REGISTRY.items():
        index[key.lower()] = key
        for alias in char.get("aliases", []):
            a = alias.strip().lower()
            if a:
                index[a] = key
    return index


_ALIAS_INDEX = _build_alias_index()


def detect_characters_in_story(story_text: str, level: str = "5") -> list[dict]:
    """扫描故事里出现的已注册角色，返回详细匹配清单。

    Args:
        story_text: 故事正文（所有页拼接）
        level: 用于 age 推断（Smart/0-3=8, 4=10, 5-6=12）

    Returns:
        每个元素：
          {
            "name_in_story": str,        # 故事里出现的原名
            "matched_key": str,           # registry 的 key
            "kind": str,                  # protagonist/...
            "gender": str,
            "age": int,                   # 按 level 推断
            "reference_exists": bool,
            "reference_path": str | None,
            "description": str,
            "first_mention_idx": int,     # 首次出现位置（用于排序）
          }
    """
    if not story_text:
        return []
    text = story_text
    from config import resolve_ip_age
    age = resolve_ip_age(level)

    matches: dict[str, dict] = {}  # key → match info
    for alias_low, reg_key in _ALIAS_INDEX.items():
        # 用 word boundary 匹配；name 必须以词边界包围
        pattern = re.compile(rf"\b{re.escape(alias_low)}\b", re.IGNORECASE)
        m = pattern.search(text)
        if not m:
            continue
        # 取原文里的形态作为 name_in_story
        name_in_story = text[m.start():m.end()]
        # 已匹配过同一个 registry key，跳过（保留最早出现的）
        if reg_key in matches and matches[reg_key]["first_mention_idx"] < m.start():
            continue

        char = get_character(reg_key)
        if not char:
            continue
        from character_registry import get_reference_path, get_description
        ref = get_reference_path(reg_key, age)
        desc = get_description(reg_key, age) or ""
        matches[reg_key] = {
            "name_in_story": name_in_story,
            "matched_key": reg_key,
            "kind": char.get("kind", ""),
            "gender": char.get("gender", ""),
            "age": age,
            "reference_exists": ref is not None,
            "reference_path": str(ref) if ref else None,
            "description": desc[:140] + ("..." if len(desc) > 140 else ""),
            "first_mention_idx": m.start(),
        }

    out = sorted(matches.values(), key=lambda x: x["first_mention_idx"])
    return out


def detect_generic_roles(story_text: str) -> list[dict]:
    """检测故事里出现的 "the girl / a boy / a woman / mom" 等没具名的角色，
    返回类型 + 默认建议（用哪个 registry key 顶替）。
    """
    if not story_text:
        return []
    text = story_text.lower()
    rules = [
        (r"\b(?:a |an |the )?girl(?:s)?\b", "girl", "mia",
         "未命名 girl 角色 → 默认用 Mia 形象"),
        (r"\b(?:a |an |the )?boy(?:s)?\b", "boy", "tommy",
         "未命名 boy 角色 → 默认用 Tommy 形象"),
        (r"\b(?:a |an |the )?woman\b", "woman", "teacher_kim",
         "未命名 woman 角色 → 默认用 Teacher Kim 形象"),
        (r"\b(?:a |an |the )?man\b", "man", "",
         "未命名 man 角色 → 暂未注册成年男性 IP（请上传参考图或在 prompt 中描述）"),
        (r"\b(?:cat|kitten)\b", "cat", "winnie",
         "出现 cat → 默认用 Winnie 形象"),
    ]
    seen = set()
    out = []
    for pattern, role, key, note in rules:
        if re.search(pattern, text) and role not in seen:
            seen.add(role)
            out.append({"role": role, "default_key": key, "note": note})
    return out


# ============================================================
#  汇总：给 UI 一个 dict
# ============================================================

def auto_summary(level: str, story_text: str, title: str = "") -> dict:
    """一次性返回所有可自动推断的字段，UI 一调即用。"""
    return {
        "cefr": cefr_for_level(level),
        "lexile": lexile_for_level(level),
        "fiction_type": infer_fiction_type(story_text),
        "theme": infer_theme(story_text, title),
        "word_count": count_story_words(story_text),
        "characters": detect_characters_in_story(story_text, level),
        "generic_roles": detect_generic_roles(story_text),
    }
