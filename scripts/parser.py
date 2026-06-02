"""解析 9 页绘本大纲（Markdown）。

支持的字段：
  Title / Level / Book / CEFR / Lexile / Word_count / IP_Age
  Vocabulary  或  Vocabulary_Mastery + Vocabulary_Exposure
  # Cover  + Scene:
  # Page 1..7  + Text: + Scene:  + Text_Position: (可选)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PageSpec:
    index: int               # 0 = 封面，1-7 = 故事页
    page_type: str           # "cover" | "story"
    text: str = ""           # 英文台词
    scene: str = ""          # 场景描述（英文，AI 抽取的简短 visual hint）
    scene_cn: str = ""       # v1.9 新增：中文画面描述（120-220 字，主体+动作+环境+氛围），喂给 Doubao Seedream
    text_corner: str = ""    # "top-left" | "top-right" | "bottom-left" | "bottom-right"
    expression: str = ""     # 该页人物情绪（如 "excited" / "worried" / "amazed"）
    shot: str = ""           # "close" | "medium" | "full" | "wide"，留空走默认 medium

    @property
    def label(self) -> str:
        return "Cover" if self.page_type == "cover" else f"Page {self.index}"

    @property
    def word_count(self) -> int:
        return len(re.findall(r"\b\w+\b", self.text))


@dataclass
class BookOutline:
    title: str
    pages: list[PageSpec] = field(default_factory=list)
    level: str = ""
    book_number: str = ""
    cefr: str = ""
    lexile: str = ""
    word_count_override: str = ""
    ip_age: int | None = None

    vocabulary_mastery: list[str] = field(default_factory=list)
    vocabulary_exposure: list[str] = field(default_factory=list)
    vocabulary_simple: list[str] = field(default_factory=list)  # 单行模式

    # v1.4 新增：教学元信息
    phonics: str = ""              # 自然拼读规则（如 'consonant blend "fr" (friendship)'）
    grammar_focus: str = ""        # 主语法点（如 "一般现在时态" / "Simple past tense"）
    reader_type: str = ""          # 读者类型（覆盖 _default_reader_type 推断）
    fiction_type: str = ""         # v1.8：L3-L6 用，取值 "fiction" / "non-fiction"
    lesson_time: str = "60 mins"   # 默认 60 分钟
    theme: str = ""                # 主题（如 "friendship"）

    # 角色别名映射（如 {"anna": "mia", "kevin": "tommy"}）
    aliases: dict[str, str] = field(default_factory=dict)

    # 自定义独立角色（v1.3.2）
    custom_characters: dict[str, str] = field(default_factory=dict)

    @property
    def slug(self) -> str:
        safe = re.sub(r"[^\w\s-]", "", self.title, flags=re.UNICODE)
        safe = re.sub(r"\s+", "_", safe.strip()) or "picturebook"
        return safe[:80]

    @property
    def total_words(self) -> int:
        if self.word_count_override:
            try:
                return int(self.word_count_override)
            except ValueError:
                pass
        return sum(p.word_count for p in self.pages if p.page_type == "story")

    @property
    def has_double_vocab(self) -> bool:
        return bool(self.vocabulary_mastery or self.vocabulary_exposure)

    @property
    def vocabulary_for_display(self) -> list[str]:
        if self.vocabulary_simple:
            return self.vocabulary_simple
        return self.vocabulary_mastery + self.vocabulary_exposure

    @property
    def level_key(self) -> str:
        """返回 'smart' / '0' / '1' / ... / '6' 用于查表。"""
        s = (self.level or "").strip().lower()
        if "smart" in s:
            return "smart"
        digits = "".join(ch for ch in s if ch.isdigit())
        return digits or "1"

    @property
    def is_dual_vocab_level(self) -> bool:
        """L0/L1/L2 用双行 Mastery+Exposure；L3-L6 用单行 Vocabulary 4 词。"""
        return self.level_key in ("smart", "0", "1", "2")

    @property
    def story_text(self) -> str:
        return " ".join(p.text for p in self.pages if p.page_type == "story" and p.text).strip()

    def validate(self) -> None:
        if not self.title.strip():
            raise ValueError("大纲缺少 Title")
        if len(self.pages) != 8:
            raise ValueError(
                f"需要 1 封面 + 7 故事 = 8 个页面节点，当前 {len(self.pages)} 个"
            )


# ---------- 解析入口 ----------
def parse_outline_file(path: Path) -> BookOutline:
    return parse_outline_text(path.read_text(encoding="utf-8"))


def parse_outline_text(text: str) -> BookOutline:
    lines = text.replace("\r\n", "\n").split("\n")

    meta: dict[str, str] = {}
    pages_raw: list[dict] = []

    current: dict | None = None

    def flush() -> None:
        nonlocal current
        if current is not None:
            current["text"] = " ".join(
                s.strip() for s in current.get("_text_lines", []) if s.strip()
            )
            current.pop("_text_lines", None)
            pages_raw.append(current)
            current = None

    field_re = re.compile(
        r"^(Title|Level|Book|CEFR|Lexile|Word_?count|IP_?Age|Theme|"
        r"Phonics|Grammar(?:_?Focus)?|Reader_?Type|Lesson_?Time|"
        r"Vocabulary_?Mastery|Vocabulary_?Exposure|Vocabulary|Aliases|Custom_\w+)\s*:\s*(.*)$",
        re.I,
    )
    page_header_re = re.compile(
        r"^#+\s*(Cover|封面|Page\s*(\d+)|第\s*(\d+)\s*页)\s*$", re.I
    )
    text_re = re.compile(r"^Text\s*:\s*(.*)$", re.I)
    scene_re = re.compile(r"^Scene\s*:\s*(.*)$", re.I)
    pos_re = re.compile(r"^Text_?Position\s*:\s*(.*)$", re.I)
    expr_re = re.compile(r"^Expression\s*:\s*(.*)$", re.I)
    shot_re = re.compile(r"^Shot\s*:\s*(.*)$", re.I)

    for raw in lines:
        line = raw.rstrip()
        s = line.strip()
        if not s and current is None:
            continue

        m_header = page_header_re.match(s)
        if m_header:
            flush()
            name = (m_header.group(1) or "").lower()
            if name in ("cover", "封面"):
                current = {"kind": "cover", "_text_lines": []}
            else:
                num = m_header.group(2) or m_header.group(3)
                current = {"kind": "story", "index": int(num), "_text_lines": []}
            continue

        if current is None:
            m_field = field_re.match(s)
            if m_field:
                raw_key = m_field.group(1)
                # Custom_<Name> 保留下划线（之后特殊处理）
                if raw_key.lower().startswith("custom_"):
                    key = raw_key.lower()
                else:
                    key = raw_key.replace("_", "").lower()
                meta[key] = m_field.group(2).strip()
                continue
            # markdown 一级标题作书名
            if s.startswith("# "):
                meta.setdefault("title", s[2:].strip())
            continue

        # 在 page 块内
        m_text = text_re.match(s)
        if m_text:
            current["_text_lines"].append(m_text.group(1))
            continue
        m_scene = scene_re.match(s)
        if m_scene:
            current["scene"] = m_scene.group(1).strip()
            continue
        m_pos = pos_re.match(s)
        if m_pos:
            current["text_corner"] = m_pos.group(1).strip().lower()
            continue
        m_expr = expr_re.match(s)
        if m_expr:
            current["expression"] = m_expr.group(1).strip()
            continue
        m_shot = shot_re.match(s)
        if m_shot:
            current["shot"] = m_shot.group(1).strip().lower()
            continue
        # 其它行：拼到 text
        if s:
            current["_text_lines"].append(s)

    flush()

    title = meta.get("title", "").strip() or "Picture Book"
    level = meta.get("level", "").strip()
    book_number = meta.get("book", "").strip()
    cefr = meta.get("cefr", "").strip()
    lexile = meta.get("lexile", "").strip()
    word_count_override = meta.get("wordcount", "").strip()
    ip_age_raw = meta.get("ipage", "").strip()
    ip_age = int(ip_age_raw) if ip_age_raw.isdigit() else None

    voc_simple = _split_words(meta.get("vocabulary", ""))
    voc_mastery = _split_words(meta.get("vocabularymastery", ""))
    voc_exposure = _split_words(meta.get("vocabularyexposure", ""))

    phonics = meta.get("phonics", "").strip()
    grammar_focus = (
        meta.get("grammarfocus", "").strip() or meta.get("grammar", "").strip()
    )
    reader_type = meta.get("readertype", "").strip()
    lesson_time = meta.get("lessontime", "").strip() or "60 mins"
    theme = meta.get("theme", "").strip()

    # 角色别名：解析 "anna=mia, kevin=tommy" 形式
    aliases = _parse_aliases(meta.get("aliases", ""))

    # 自定义独立角色：解析所有 custom_<name> 字段
    custom_characters: dict[str, str] = {}
    for k, v in meta.items():
        if k.startswith("custom_") and v.strip():
            name = k[len("custom_"):]  # "anna"
            custom_characters[name] = v.strip()

    # 整理 pages：始终 1 cover + 7 story
    pages = _normalize_pages(pages_raw, title)

    book = BookOutline(
        title=title,
        pages=pages,
        level=level,
        book_number=book_number,
        cefr=cefr,
        lexile=lexile,
        word_count_override=word_count_override,
        ip_age=ip_age,
        vocabulary_mastery=voc_mastery,
        vocabulary_exposure=voc_exposure,
        vocabulary_simple=voc_simple,
        phonics=phonics,
        grammar_focus=grammar_focus,
        reader_type=reader_type,
        lesson_time=lesson_time,
        theme=theme,
        aliases=aliases,
        custom_characters=custom_characters,
    )
    book.validate()
    return book


def _split_words(s: str) -> list[str]:
    if not s:
        return []
    parts = re.split(r"[,，、;；/]+", s)
    return [p.strip() for p in parts if p.strip()]


def _parse_aliases(s: str) -> dict[str, str]:
    """解析 'anna=mia, kevin=tommy' 形式的别名映射。
    只接受 mia/tommy 作为目标 IP。"""
    if not s:
        return {}
    out: dict[str, str] = {}
    for pair in re.split(r"[,，;；]+", s):
        pair = pair.strip()
        if "=" not in pair:
            continue
        alias, target = pair.split("=", 1)
        alias = alias.strip().lower()
        target = target.strip().lower()
        if alias and target in ("mia", "tommy"):
            out[alias] = target
    return out


_DEFAULT_CORNERS = [
    "top-left", "bottom-right", "top-right", "top-right",
    "top-right", "top-left", "top-right",
]


def _normalize_pages(raw: list[dict], title: str) -> list[PageSpec]:
    cover_scene = ""
    cover_text = title
    cover_shot = ""
    story: list[dict] = []

    for blk in raw:
        if blk["kind"] == "cover":
            cover_text = blk.get("text") or title
            cover_scene = blk.get("scene") or "Mia and Tommy on cover, friendly cover composition"
            cover_shot = (blk.get("shot") or "").strip().lower()
            if cover_shot not in ("close", "medium", "full", "wide", ""):
                cover_shot = ""
        else:
            story.append(blk)

    story.sort(key=lambda b: b.get("index", 0))
    if len(story) > 7:
        story = story[:7]
    while len(story) < 7:
        story.append({"kind": "story", "index": len(story) + 1, "text": "", "scene": ""})

    pages: list[PageSpec] = [
        PageSpec(
            index=0, page_type="cover", text=cover_text, scene=cover_scene, shot=cover_shot
        ),
    ]
    for i, blk in enumerate(story, start=1):
        corner = (blk.get("text_corner") or _DEFAULT_CORNERS[i - 1]).strip()
        if corner not in ("top-left", "top-right", "bottom-left", "bottom-right"):
            corner = _DEFAULT_CORNERS[i - 1]
        shot_raw = (blk.get("shot") or "").strip().lower()
        if shot_raw not in ("close", "medium", "full", "wide", ""):
            shot_raw = ""
        pages.append(
            PageSpec(
                index=i,
                page_type="story",
                text=blk.get("text", "").strip(),
                scene=blk.get("scene", "").strip() or blk.get("text", "")[:120],
                text_corner=corner,
                expression=blk.get("expression", "").strip(),
                shot=shot_raw,
            )
        )
    return pages
