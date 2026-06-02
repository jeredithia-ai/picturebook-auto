"""IP 库统一访问层。

读取 assets/ip_library/_manifest.json，提供按 key/kind/age 查询接口。
对接 web_app 的「📚 故事人物库」面板和 cn_prompt_builder 的参考图选择。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IP_DIR = PROJECT_ROOT / "assets" / "ip_library"
MANIFEST_PATH = IP_DIR / "_manifest.json"


@dataclass
class IPEntry:
    key: str           # mia_12 / tommy_10 / anna_12 / mom / dino ...
    name: str          # 显示名 "Mia (12y)"
    kind: str          # protagonist / supporting / family / adult / pet / brand
    gender: str        # girl / boy / woman / man / ''
    age: int           # 0 = N/A (Dino/Cat 等)
    desc: str          # 中文形象描述
    image_path: Path   # 绝对路径

    @property
    def name_base(self) -> str:
        """去掉 (12y) 后缀的纯名字，如 'Mia'。"""
        return self.name.split(" (")[0].strip()


@lru_cache(maxsize=1)
def load_library() -> list[IPEntry]:
    if not MANIFEST_PATH.exists():
        return []
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    out: list[IPEntry] = []
    for d in data:
        img = PROJECT_ROOT / d["image"]
        if not img.exists():
            continue
        out.append(IPEntry(
            key=d["key"], name=d["name"], kind=d["kind"],
            gender=d.get("gender", ""), age=int(d.get("age", 0)),
            desc=d.get("desc", ""), image_path=img,
        ))
    return out


def get_ip(key: str) -> IPEntry | None:
    for e in load_library():
        if e.key == key:
            return e
    return None


def list_by_kind() -> dict[str, list[IPEntry]]:
    """按 kind 分组（保持 manifest 顺序）。"""
    out: dict[str, list[IPEntry]] = {}
    for e in load_library():
        out.setdefault(e.kind, []).append(e)
    return out


# ---------- 角色名 → IP key 自动匹配（用于"主角识别"）----------
_NAME_ALIAS: dict[str, str] = {
    # 主角
    "mia": "mia", "tommy": "tommy", "anna": "anna",
    # 朋友
    "ali": "ali", "cate": "cate",
    # 家人
    "mom": "mom", "mommy": "mom", "mother": "mom", "妈妈": "mom",
    "dad": "dad", "daddy": "dad", "father": "dad", "爸爸": "dad",
    "grandma": "grandma", "granny": "grandma", "奶奶": "grandma",
    "grandpa": "grandpa", "grandfather": "grandpa", "爷爷": "grandpa",
    # 老师 / 宠物
    "teacher": "teacher", "ms. kim": "teacher", "mrs. kim": "teacher", "kim": "teacher",
    "cat": "cat", "kitty": "cat", "kitten": "cat",
    "dino": "dino",
}


def resolve_name_to_ip(name: str, age: int) -> IPEntry | None:
    """根据人物名 + 故事级别推断年龄，返回最匹配的 IP entry。

    例：('Mia', 12) → mia_12; ('Tommy', 10) → tommy_10; ('Mom', 35) → mom
    """
    if not name:
        return None
    base = name.strip().lower()
    # 直接 alias 命中
    base_key = _NAME_ALIAS.get(base)
    if not base_key:
        # 部分匹配（如 "Teacher Kim" → kim）
        for alias, k in _NAME_ALIAS.items():
            if alias in base:
                base_key = k
                break
    if not base_key:
        return None

    # 在 manifest 里找 base_key 对应的 age 档（最接近的）
    lib = load_library()
    candidates = [e for e in lib if e.key.startswith(base_key + "_") or e.key == base_key]
    if not candidates:
        return None

    # 年龄 0（family/pet/brand）直接返回第一个
    if candidates[0].age == 0:
        return candidates[0]

    # 选与 age 最接近的
    return min(candidates, key=lambda e: abs(e.age - age))


def resolve_generic_role(role: str, age: int) -> IPEntry | None:
    """无名角色（"a girl" / "a boy" / "a woman" / "an old man" / "a cat"）→ 默认 IP。

    映射规则（可被 web_app session_state 的 generic_overrides 覆盖）：
      girl  → mia (按 age 档)
      boy   → tommy (按 age 档)
      woman → mom (家人) / teacher (学校场景)
      man   → dad
      cat/kitty → cat
    """
    r = role.strip().lower()
    default_map = {
        "girl": "mia", "boy": "tommy",
        "woman": "mom", "man": "dad",
        "old woman": "grandma", "old man": "grandpa",
        "cat": "cat", "kitty": "cat", "kitten": "cat",
    }
    base = default_map.get(r)
    if not base:
        return None
    lib = load_library()
    candidates = [e for e in lib if e.key.startswith(base + "_") or e.key == base]
    if not candidates:
        return None
    if candidates[0].age == 0:
        return candidates[0]
    return min(candidates, key=lambda e: abs(e.age - age))
