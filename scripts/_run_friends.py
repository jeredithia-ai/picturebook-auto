"""跑 What Makes a Good Friend?（L5, Anna 主角）—— 新管线验证。

cn_prompt_builder(v3) + scene_cn(Claude) + gpt-image-2 + Anna 定妆图。
Anna=主角(锁定定妆图)，girl->Mia，boy->Tommy。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from parser import BookOutline, PageSpec
from cn_prompt_builder import build_cn_page_prompt
from character_registry import get_description as reg_desc
from seedream_client import generate_image
from ip_library import get_ip
import scene_cn_writer

ANNA_REF = get_ip("anna_12").image_path  # 主角定妆图，故事页恒为首位参考

TITLE = "What Makes a Good Friend?"
LEVEL = "5"
IP_AGE = 12
PAGES = [
    "Anna felt nervous on her first day in the new class. Her hands shook as she sat down at a small wooden desk.",
    "At recess she saw a girl drop a pile of books on the floor. Anna helped pick up the books and smiled at the girl.",
    "Later she shared pencils and glue with a quiet boy at his table. The boy looked up and said thank you to her softly.",
    "A class hamster grabbed Anna's eraser and ran under a chair. The hamster looked like a tiny thief and everyone laughed together.",
    "Anna listened when classmates told stories about pets and games. She said, 'Tell me more,' and asked each person kind questions.",
    "Her classmates all liked her because she cared about them and helped them. Anna felt glad she had been kind from the very first day.",
    "By the week's end Anna had many new friends and a plan. The next week she would bake cookies and bring them for everyone in the class.",
]

CAST_POOL = ["anna_12", "mia_12", "tommy_12"]   # manifest key
OVERRIDES = {"girl": "mia_12", "boy": "tommy_12"}
OUT = Path("outputs/Friends_v2/images")


def build_outline() -> BookOutline:
    pages = [PageSpec(index=0, page_type="cover", text="")]
    for i, t in enumerate(PAGES, start=1):
        pages.append(PageSpec(index=i, page_type="story", text=t))
    return BookOutline(title=TITLE, pages=pages, level=LEVEL, cefr="B1",
                       ip_age=IP_AGE, theme="friendship")


def cast_for(text: str) -> list[str]:
    keys = ["anna"]
    low = text.lower()
    if "girl" in low:
        keys.append("mia")
    if "boy" in low:
        keys.append("tommy")
    return [reg_desc(k, IP_AGE) or "" for k in keys]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    outline = build_outline()
    prev = ""
    for page in outline.pages:
        t0 = time.time()
        # 1) Claude 写中文画面描述（故事页）
        if page.page_type == "story":
            try:
                page.scene_cn = scene_cn_writer.write_scene_cn(
                    story_sentence=page.text, page_idx=page.index,
                    book_title=TITLE, level=LEVEL, ip_age=IP_AGE,
                    cast_descriptions=cast_for(page.text),
                    style_summary="温暖治愈水彩童书风，柔和莫兰迪色，校园场景",
                    previous_pages_summary=prev,
                )
                prev += f"P{page.index}: {page.text[:50]}; "
            except Exception as e:
                print(f"  scene_cn 跳过(P{page.index}): {e}")

        # 2) v3 中文 prompt + 参考图
        built = build_cn_page_prompt(
            page, outline, IP_AGE,
            cast_pool=CAST_POOL, generic_overrides=OVERRIDES,
        )
        # Anna 是全书主角 → 故事页恒为首位参考（即便本句用 she 没点名）
        ref_list = list(built.references)
        if page.page_type == "story" and ANNA_REF not in ref_list:
            ref_list.insert(0, ANNA_REF)
        elif page.page_type == "story" and ref_list and ref_list[0] != ANNA_REF:
            ref_list.remove(ANNA_REF)
            ref_list.insert(0, ANNA_REF)
        refs = [r.name for r in ref_list]

        # 3) 生图
        dest = OUT / f"page_{page.index:02d}.png"
        try:
            generate_image(prompt=built.prompt, dest=dest,
                           references=ref_list, label=f"P{page.index}")
            ok = f"{dest.stat().st_size // 1024}KB"
        except Exception as e:
            ok = f"FAIL {e}"
        print(f"[P{page.index}] refs={refs} -> {ok}  ({time.time()-t0:.0f}s)")

    print("\n完成 ->", OUT)


if __name__ == "__main__":
    main()
