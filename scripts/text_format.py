"""v1.8 文本规整工具（worksheet / reading report 共用）。

提供三组函数：
  - _to_us_spelling(text)  : BrE → AmE 拼写替换（colour→color, favourite→favorite 等）
  - format_word_answer(w)  : 单词类答案：小写、无标点
  - format_sentence_answer(s): 句子类答案：首字母大写、句末加句号、smart-quote → straight
  - is_sentence_like(text)  : 判断文本是不是句子（含动词/超过 3 词/含逗号空格等）
"""
from __future__ import annotations

import re

# ----------------------------------------------------------------------------
# 英 → 美 拼写常见词表（不区分大小写）
# 仅放高频差异，避免误伤
# ----------------------------------------------------------------------------
_BRE_AME = {
    # -our → -or
    "colour": "color",
    "colours": "colors",
    "coloured": "colored",
    "colouring": "coloring",
    "favourite": "favorite",
    "favourites": "favorites",
    "favour": "favor",
    "favours": "favors",
    "neighbour": "neighbor",
    "neighbours": "neighbors",
    "neighbourhood": "neighborhood",
    "behaviour": "behavior",
    "honour": "honor",
    "humour": "humor",
    "labour": "labor",
    "harbour": "harbor",
    # -re → -er
    "centre": "center",
    "centres": "centers",
    "theatre": "theater",
    "theatres": "theaters",
    "metre": "meter",
    "metres": "meters",
    "litre": "liter",
    "litres": "liters",
    "fibre": "fiber",
    "fibres": "fibers",
    # -ise → -ize
    "realise": "realize",
    "realised": "realized",
    "organise": "organize",
    "organised": "organized",
    "recognise": "recognize",
    "recognised": "recognized",
    "apologise": "apologize",
    "apologised": "apologized",
    # -ll → -l
    "travelled": "traveled",
    "travelling": "traveling",
    "traveller": "traveler",
    "cancelled": "canceled",
    "cancelling": "canceling",
    "modelled": "modeled",
    "modelling": "modeling",
    # 其他高频
    "grey": "gray",
    "greys": "grays",
    "mum": "mom",
    "mummy": "mommy",
    "aluminium": "aluminum",
    "tyre": "tire",
    "tyres": "tires",
    "kerb": "curb",
    "kerbs": "curbs",
    "practise": "practice",  # 动词（美式与名词同形）
    "practising": "practicing",
    "practised": "practiced",
    "plough": "plow",
    "ploughs": "plows",
    "draught": "draft",
    "draughts": "drafts",
    "judgement": "judgment",
    "acknowledgement": "acknowledgment",
}


def _to_us_spelling(text: str) -> str:
    """把文本里的英式拼写整体替换为美式拼写（保留原大小写形态）。"""
    if not text:
        return text

    def _repl(match: re.Match) -> str:
        word = match.group(0)
        low = word.lower()
        if low not in _BRE_AME:
            return word
        us = _BRE_AME[low]
        # 还原大小写：全大写 / 首字母大写 / 全小写
        if word.isupper():
            return us.upper()
        if word[:1].isupper():
            return us[:1].upper() + us[1:]
        return us

    # 用 \b...\b 整词匹配
    pattern = r"\b(" + "|".join(re.escape(k) for k in _BRE_AME.keys()) + r")\b"
    return re.sub(pattern, _repl, text, flags=re.IGNORECASE)


# ----------------------------------------------------------------------------
# 答案格式
# ----------------------------------------------------------------------------
def _strip_quotes(s: str) -> str:
    """去掉首尾的引号/空白。"""
    return s.strip().strip('"\u201c\u201d\u2018\u2019\'').strip()


def is_sentence_like(text: str) -> bool:
    """简单判断 text 是不是一个句子（用于决定大小写策略）。

    规则（任一满足即视作句子）：
      - 含空格 + 词数 >= 3
      - 含动词模式（is/are/was/were/has/have/do/does/did/go/went/see/saw/...）
      - 含逗号/分号
    """
    if not text:
        return False
    s = text.strip().strip(".!?")
    if "," in s or ";" in s:
        return True
    words = s.split()
    if len(words) >= 3:
        return True
    return False


def format_word_answer(text: str) -> str:
    """单词类答案：去引号、小写、去句号、美式拼写。

    例：'Red.' → 'red'   '"Apple"' → 'apple'
    保留连字符 / 撇号（don't, ice-cream）。
    """
    if text is None:
        return ""
    t = _strip_quotes(str(text))
    t = t.rstrip(".!?,;:").strip()
    t = t.lower()
    t = _to_us_spelling(t)
    return t


def format_sentence_answer(text: str) -> str:
    """句子类答案：去引号、首字母大写、末尾加句号（若没有 .!?）、美式拼写。

    v1.8.1：额外把所有独立 'i' 单词大写为 'I'（包括 i'm/i've/i'll/i'd → I'm 等）。

    例：'red is a color' → 'Red is a color.'
        'i feel sad'     → 'I feel sad.'
        "i'm happy"      → "I'm happy."
    """
    if text is None:
        return ""
    t = _strip_quotes(str(text))
    # smart-quote → straight quote
    t = (t.replace("\u201c", '"').replace("\u201d", '"')
           .replace("\u2018", "'").replace("\u2019", "'"))
    # 美式拼写
    t = _to_us_spelling(t)
    # 独立 i / i'xx 单词强制大写 I
    t = re.sub(r"\bi\b", "I", t)
    t = re.sub(r"\bi(['\u2019])", r"I\1", t)
    # 首字母大写
    if t:
        t = t[0].upper() + t[1:]
    # 末尾标点
    if t and t[-1] not in ".!?":
        t += "."
    return t


def smart_format_answer(text: str) -> str:
    """根据 is_sentence_like 自动决定走哪种格式。"""
    if is_sentence_like(text):
        return format_sentence_answer(text)
    return format_word_answer(text)
