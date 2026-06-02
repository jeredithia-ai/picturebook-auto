"""组装 What Makes a Good Friend 完整交付：绘本PPT + Worksheet + RR + TG + zip。

复用 outputs/Friends_v2/images 的 8 张图。
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from parser import BookOutline, PageSpec
from ai_extractor import extract_all, apply_extracted_to_outline
from reading_report_builder import attach_rr_questions, build_reading_report
from worksheet_builder import attach_worksheet_questions, build_worksheet
from ppt_builder import build_picturebook_pptx
from teacher_guide_builder import build_teacher_guide

TITLE = "What Makes a Good Friend?"
LEVEL = "5"
BOOK_NO = "01"
STORY = """Page 1: Anna felt nervous on her first day in the new class. Her hands shook as she sat down at a small wooden desk.
Page 2: At recess she saw a girl drop a pile of books on the floor. Anna helped pick up the books and smiled at the girl.
Page 3: Later she shared pencils and glue with a quiet boy at his table. The boy looked up and said thank you to her softly.
Page 4: A class hamster grabbed Anna's eraser and ran under a chair. The hamster looked like a tiny thief and everyone laughed together.
Page 5: Anna listened when classmates told stories about pets and games. She said, 'Tell me more,' and asked each person kind questions.
Page 6: Her classmates all liked her because she cared about them and helped them. Anna felt glad she had been kind from the very first day.
Page 7: By the week's end Anna had many new friends and a plan. The next week she would bake cookies and bring them for everyone in the class."""

IMG_DIR = Path("outputs/Friends_v2/images")
OUT = Path("outputs/Friends_v2")


def name_prefix() -> str:
    title = re.sub(r'[\\/:*?"<>|]', "_", TITLE)
    title = re.sub(r"_+", "_", title).strip("_ ")
    return f"Level {LEVEL}_Book{BOOK_NO}_{title}"


def main() -> None:
    print("1) AI 抽取完整内容（词表/题目/拼读/语法）...")
    ec = extract_all(STORY, TITLE, LEVEL, cefr="B1", theme="friendship", mock=False)

    print("2) 构建 outline + 套用抽取内容...")
    pages = [PageSpec(index=0, page_type="cover", text="")]
    for i, line in enumerate([l.split(":", 1)[1].strip() for l in STORY.splitlines()], start=1):
        pages.append(PageSpec(index=i, page_type="story", text=line))
    outline = BookOutline(title=TITLE, pages=pages, level=LEVEL, book_number=BOOK_NO,
                          cefr="B1", ip_age=12, theme="friendship")
    apply_extracted_to_outline(outline, ec)
    attach_rr_questions(outline, ec.rr_questions)
    attach_worksheet_questions(outline, ec.worksheet_questions, reading_q_count=4)

    image_paths = [IMG_DIR / f"page_{p.index:02d}.png" for p in outline.pages]
    missing = [str(p) for p in image_paths if not p.exists()]
    if missing:
        raise SystemExit("缺图: " + ", ".join(missing))

    pre = name_prefix()
    print("3) 组装绘本 PPT...")
    pb = OUT / f"{pre}_绘本.pptx"
    build_picturebook_pptx(outline, image_paths, pb)

    print("4) 组装 Worksheet...")
    ws = OUT / f"{pre}_练习册.pptx"
    build_worksheet(outline, ws, image_paths=image_paths)

    print("5) 组装 Reading Report...")
    rr = OUT / f"{pre}_阅读报告.docx"
    build_reading_report(outline, rr)

    print("6) 组装 Teacher's Guide...")
    tg = OUT / f"{pre}_教师指南.docx"
    build_teacher_guide(outline, tg)

    print("7) 打包 zip...")
    zp = OUT / f"{pre}_全套.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in [pb, ws, rr, tg]:
            z.write(f, arcname=f.name)
        for img in image_paths:
            z.write(img, arcname=f"images/{img.name}")

    print("\n完成 ->", OUT)
    for f in [pb, ws, rr, tg, zp]:
        print("  ", f.name, f"{f.stat().st_size//1024}KB")


if __name__ == "__main__":
    main()
