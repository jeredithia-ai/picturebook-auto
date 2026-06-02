"""官方角色注册表 v1.0 — 4 件套共用的唯一权威。

任何角色（主角 / 老师 / 宠物 / 配角 / 家庭）的形象描述、参考图、年龄档
都在这里登记。prompt_builder / web_app / ai_extractor 全部从这里读，
避免分散描述导致跨页跑帧。

字段：
  - description_by_age: {age: 长描述（用于场景 prompt）}
  - reference_by_age:   {age: 参考图文件名（相对 assets/characters/）}
  - kind:               "protagonist" / "supporting" / "adult" / "pet" / "family" / "brand"
  - gender:             "girl" / "boy" / "woman" / "man" / "pet" / "brand"
  - aliases:            可被识别为该角色的其他名字（小写）
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from config import CHARACTERS_DIR

# 通用反例
NO_ACCESSORY = (
    "NO watch, NO bracelet, NO necklace, NO earrings, NO glasses, NO hat"
)


# ============================================================
#  主角（年龄分档 8 / 10 / 12，对应 L0-3 / L4 / L5-6）
# ============================================================

MIA = {
    "kind": "protagonist",
    "gender": "girl",
    "aliases": [],
    "reference_by_age": {
        8: "mia_age12.png",  # TODO: age8 暂用 12 兜底（待补 age8 设定图）
        10: "mia_age10.png",
        12: "mia_age12.png",
    },
    "description_by_age": {
        8: (
            "Mia: 8y GIRL, long brown hair in a SINGLE soft PONYTAIL tied at back-middle "
            "of head, ponytail tail flows past shoulders, soft face-framing strands. "
            "lavender purple SHORT-SLEEVE tee, denim jeans, white sneakers, bare wrists, "
            + NO_ACCESSORY
        ),
        10: (
            "Mia: 10y GIRL, long brown hair in a SINGLE soft PONYTAIL tied at back-middle "
            "of head, soft face-framing strands. "
            "lavender purple LONG-SLEEVE sweatshirt, light gray sweatpants, white sneakers, "
            "bare wrists, " + NO_ACCESSORY
        ),
        12: (
            "Mia: 12y GIRL — HAIR LOCK: long brown hair tied UP into a HIGH PONYTAIL at the "
            "back-top of the head with a small white scrunchie, ponytail flows down behind shoulders. "
            "From FRONT/3-quarter: short fringe bangs + a few thin face-framing strands; the LONG part "
            "is GATHERED UP behind (NEVER cascading loose on both sides). "
            "lavender purple LONG-SLEEVE polo-collar pullover, white wide-leg trousers, white sneakers, "
            "bare wrists, " + NO_ACCESSORY
        ),
    },
}

TOMMY = {
    "kind": "protagonist",
    "gender": "boy",
    "aliases": [],
    "reference_by_age": {
        8: "tommy_age12.png",  # TODO: age8 暂用 12 兜底
        10: "tommy_age10.png",
        12: "tommy_age12.png",
    },
    "description_by_age": {
        8: (
            "Tommy: 8y BOY (NOT a girl, NO ponytail, NO long hair), short tidy brown hair, "
            "blue-and-white striped SHORT-SLEEVE tee, denim jeans, white sneakers, "
            "bare wrists, " + NO_ACCESSORY
        ),
        10: (
            "Tommy: 10y BOY (NOT a girl, NO ponytail, NO long hair), short messy brown hair, "
            "light blue LONG-SLEEVE sweatshirt, khaki straight pants, white sneakers, "
            "bare wrists, " + NO_ACCESSORY
        ),
        12: (
            "Tommy: 12y BOY (NOT a girl, NO ponytail, NO long hair), short messy brown hair, "
            "navy SHORT-SLEEVE polo shirt with V-collar, blue denim straight-cut jeans, "
            "white sneakers, bare wrists, " + NO_ACCESSORY
        ),
    },
}


# ============================================================
#  老师（成人 IP）
# ============================================================

TEACHER_KIM = {
    "kind": "adult",
    "gender": "woman",
    "aliases": ["ms. kim", "ms kim", "kim", "teacher"],
    "reference_by_age": {"adult": "teacher_kim.png"},
    "description_by_age": {
        "adult": (
            "Teacher Kim: adult woman, late 20s, warm and playful authority (Ms. Frizzle vibe), "
            "shoulder-length GOLDEN BLOND WAVY HAIR, blue-green eyes, gentle freckles, "
            "ORANGE SHORT-SLEEVE button-up polo, BLUE wide-leg JEANS (high-waist, loose flare), "
            "white sneakers, friendly confident smile, bare wrists, " + NO_ACCESSORY
        ),
    },
}


# ============================================================
#  宠物（常驻 IP）
# ============================================================

WINNIE = {
    "kind": "pet",
    "gender": "pet",
    "aliases": ["winnie", "the cat", "kitty", "kitten"],
    "reference_by_age": {"pet": "winnie_cat.png"},
    "description_by_age": {
        "pet": (
            "Winnie: small grey tabby kitten, white belly and paws, large amber-brown eyes, "
            "pink nose, thin tabby stripes on gray fur, fluffy short tail. "
            "Watercolor children's book style, cute and soft, NOT photorealistic"
        ),
    },
}


# ============================================================
#  品牌（不可修改）
# ============================================================

DINO = {
    "kind": "brand",
    "gender": "brand",
    "aliases": ["dino", "vipkid dino"],
    "reference_by_age": {"brand": "dino_official.png"},
    "description_by_age": {
        "brand": (
            "Dino: VIPKID official mascot — small friendly orange dinosaur character. "
            "STRICTLY use official appearance (do NOT redesign shape, color, or proportions). "
            "ONLY use as logo / corner sticker, do NOT make Dino a story character"
        ),
    },
}


# ============================================================
#  预设配角（已有图片资源的友伴）
# ============================================================

ALI = {
    "kind": "supporting",
    "gender": "boy",
    "aliases": [],
    "reference_by_age": {6: "ali_age6.png"},
    "description_by_age": {
        6: (
            "Ali: 6y BOY (NOT Tommy), short curly black hair, warm brown skin, "
            "yellow cotton t-shirt, brown shorts, white sneakers, cheerful smile"
        ),
    },
}

CATE = {
    "kind": "supporting",
    "gender": "girl",
    "aliases": [],
    "reference_by_age": {
        8: "cate_age8.png",
        10: "cate_age10.png",
        12: "cate_age10.png",  # 兜底
    },
    "description_by_age": {
        8: (
            "Cate: 8y GIRL (NOT Mia), shoulder-length wavy auburn hair (NOT ponytail), "
            "rosy cheeks, soft pink cardigan over white tee, blue skirt, white sneakers"
        ),
        10: (
            "Cate: 10y GIRL (NOT Mia), shoulder-length wavy auburn hair (NOT ponytail), "
            "rosy cheeks, soft pink cardigan over white tee, denim skirt, white sneakers"
        ),
        12: (
            "Cate: 12y GIRL (NOT Mia), shoulder-length wavy auburn hair (NOT ponytail), "
            "rosy cheeks, soft pink cardigan over white tee, denim skirt, white sneakers"
        ),
    },
}

# 多元化配角（黑人女孩/男孩，三档年龄）
BLACK_GIRL = {
    "kind": "supporting",
    "gender": "girl",
    "aliases": [],
    "reference_by_age": {
        8: "black_girl_age8.jpg",
        10: "black_girl_age10.jpg",
        12: "black_girl_age12.jpg",
    },
    "description_by_age": {
        age: (
            f"a young Black girl ({age}y, NOT Mia, NOT Anna), warm dark brown skin, "
            "natural curly Afro hair in two puff buns, large bright eyes, "
            "colorful patterned dress, white sneakers, friendly smile"
        )
        for age in (8, 10, 12)
    },
}

BLACK_BOY = {
    "kind": "supporting",
    "gender": "boy",
    "aliases": [],
    "reference_by_age": {
        8: "black_boy_age8.jpg",
        10: "black_boy_age10.jpg",
        12: "black_boy_age12.jpg",
    },
    "description_by_age": {
        age: (
            f"a young Black boy ({age}y, NOT Tommy), warm dark brown skin, "
            "short curly black hair, large bright eyes, "
            "colorful t-shirt, denim shorts, white sneakers, cheerful smile"
        )
        for age in (8, 10, 12)
    },
}


# ============================================================
#  家庭
# ============================================================

MOM = {
    "kind": "family",
    "gender": "woman",
    "aliases": ["mother", "mum"],
    "reference_by_age": {"adult": "mom.png"},
    "description_by_age": {
        "adult": (
            "Mom: adult woman, long brown wavy hair, gentle warm face, "
            "cream LONG-SLEEVE top, blue jeans, gentle smile, bare wrists"
        ),
    },
}

DAD = {
    "kind": "family",
    "gender": "man",
    "aliases": ["father"],
    "reference_by_age": {"adult": "dad.png"},
    "description_by_age": {
        "adult": (
            "Dad: adult man, short tidy brown hair, gray LONG-SLEEVE shirt, "
            "khaki trousers, warm fatherly smile, bare wrists"
        ),
    },
}

GRANDMA = {
    "kind": "family",
    "gender": "woman",
    "aliases": ["grandmother", "granny"],
    "reference_by_age": {"adult": "grandma.png"},
    "description_by_age": {
        "adult": (
            "Grandma: elderly woman, soft gray bun, gentle wrinkles, kind smile, "
            "lavender cardigan over cream blouse, comfortable trousers"
        ),
    },
}

GRANDPA = {
    "kind": "family",
    "gender": "man",
    "aliases": ["grandfather"],
    "reference_by_age": {"adult": "grandpa.png"},
    "description_by_age": {
        "adult": (
            "Grandpa: elderly man, short white hair, friendly weathered face, "
            "round glasses, brown cardigan, dark trousers"
        ),
    },
}


# ============================================================
#  总注册表
# ============================================================

# ============================================================
#  专书新主角（沉淀自具体绘本，下次复用）
# ============================================================

# Anna — 出场绘本：L5 "What Makes a Good Friend?"
# v3.0 修正 (2026-06-02): 官方库无 Anna 干净设定图，旧 anna_age12.png(裁图) 与
# 旧文字描述(波波头+白发箍+草绿)严重打架 → Anna 一直跳帧的根因。
# 现以官方裁图(黑双低马尾+黄毛衣)为准，重新生成干净多视图定妆图 anna_age12.png，
# 并把文字描述对齐定妆图，彻底锁死。
#
# Anna 锁定形象（与 anna_age12.png 定妆图完全一致）：
#   - 黑色头发，扎「两条低马尾」(low pigtails，耳下)，中分 + 轻刘海 —— 永远如此
#   - 芥末黄色圆领针织毛衣（plain，颜色稳定）
#   - 卡其/驼色长裤 + 白色低帮运动鞋
#   - 圆脸 + 腮粉 + 棕色大眼 + 小鼻子 + 温和微笑，亚洲女孩
#   - 绝不：波波头 / 单马尾 / 麻花辫 / 发箍 / 眼镜
ANNA = {
    "kind": "protagonist",
    "gender": "girl",
    "aliases": [],
    "reference_by_age": {
        12: "anna_age12.png",      # 多视图定妆图（黑双低马尾+黄毛衣+卡其裤）
        10: "anna_age12.png",      # 暂用同图（10/12 都按 12 岁定妆）
        8: "anna_age12.png",
    },
    "description_by_age": {
        12: (
            "Anna: 12y Asian GIRL (a NEW character, NOT Mia, NOT Cate, NOT Tommy). "
            "HAIR LOCK: shiny BLACK hair always tied in TWO LOW PIGTAILS just below the ears, "
            "with a soft middle-part and light front bangs. "
            "NEVER a bob, NEVER a single ponytail, NEVER braids, NEVER a headband, NEVER glasses. "
            "OUTFIT LOCK: plain warm MUSTARD-YELLOW crew-neck knit sweater, "
            "KHAKI / camel-tan straight-leg long trousers (NOT a skirt), white low-top sneakers. "
            "FACE: large round warm-brown eyes, tiny dot nose, soft rosy cheeks, light Asian skin tone, "
            "round face with gentle smile. "
            "EXPRESSION DEFAULT: kind observant smile; when nervous a small worried frown but eyes stay soft. "
            + NO_ACCESSORY
        ),
        10: (
            "Anna: 10y Asian GIRL. "
            "BLACK hair in TWO LOW PIGTAILS below the ears, middle-part with light bangs (always). "
            "Plain mustard-yellow crew-neck knit sweater, khaki straight-leg trousers, white sneakers. "
            "No glasses, no headband. Large brown eyes, small nose, rosy cheeks, light Asian skin, gentle smile"
        ),
        8: (
            "Anna: 8y Asian GIRL. "
            "BLACK hair in TWO LOW PIGTAILS below the ears, middle-part with light bangs (always). "
            "Plain mustard-yellow crew-neck knit sweater, khaki trousers, white sneakers. "
            "No glasses, no headband. Round face, large eyes, gentle smile"
        ),
    },
}


REGISTRY: dict[str, dict] = {
    "mia": MIA,
    "tommy": TOMMY,
    "anna": ANNA,
    "teacher_kim": TEACHER_KIM,
    "winnie": WINNIE,
    "dino": DINO,
    "ali": ALI,
    "cate": CATE,
    "black_girl": BLACK_GIRL,
    "black_boy": BLACK_BOY,
    "mom": MOM,
    "dad": DAD,
    "grandma": GRANDMA,
    "grandpa": GRANDPA,
}


def get_character(key: str) -> Optional[dict]:
    """按 key 查角色定义。"""
    return REGISTRY.get(key.lower())


def get_description(key: str, age) -> Optional[str]:
    """按 key + age 取形象描述（age 可为 int 8/10/12 或 'adult'/'pet'/'brand'）。"""
    char = get_character(key)
    if not char:
        return None
    desc_map = char.get("description_by_age", {})
    if age in desc_map:
        return desc_map[age]
    # 退化策略：对人类角色取最接近年龄；对成人/宠物/品牌取第一个
    if isinstance(age, int):
        ages = sorted(k for k in desc_map.keys() if isinstance(k, int))
        if ages:
            closest = min(ages, key=lambda a: abs(a - age))
            return desc_map[closest]
    return next(iter(desc_map.values()), None) if desc_map else None


def get_reference_path(key: str, age) -> Optional[Path]:
    """按 key + age 取参考图绝对路径。"""
    char = get_character(key)
    if not char:
        return None
    ref_map = char.get("reference_by_age", {})
    filename = ref_map.get(age)
    if not filename and isinstance(age, int):
        ages = sorted(k for k in ref_map.keys() if isinstance(k, int))
        if ages:
            closest = min(ages, key=lambda a: abs(a - age))
            filename = ref_map[closest]
    if not filename:
        # 取第一个非 int 的（adult/pet/brand）
        for v in ref_map.values():
            if v:
                filename = v
                break
    if not filename:
        return None
    p = CHARACTERS_DIR / filename
    return p if p.exists() else None


def list_available() -> list[dict]:
    """列出所有可用角色（供 UI 显示）。"""
    out: list[dict] = []
    for key, char in REGISTRY.items():
        ref_any = next(
            (CHARACTERS_DIR / fn for fn in char.get("reference_by_age", {}).values() if fn),
            None,
        )
        out.append({
            "key": key,
            "kind": char.get("kind"),
            "gender": char.get("gender"),
            "aliases": char.get("aliases", []),
            "age_options": list(char.get("reference_by_age", {}).keys()),
            "reference_exists": bool(ref_any and ref_any.exists()),
            "sample_reference": str(ref_any) if ref_any else None,
        })
    return out


def resolve_name(name: str) -> Optional[str]:
    """把任意叫法（含别名）解析为 registry key。

    例如 'Mom' -> 'mom', 'Ms. Kim' -> 'teacher_kim'。
    """
    if not name:
        return None
    n = name.strip().lower()
    if n in REGISTRY:
        return n
    for key, char in REGISTRY.items():
        for alias in char.get("aliases", []):
            if alias.lower() == n:
                return key
    return None
