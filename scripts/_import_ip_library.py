"""一次性脚本：把 VIPKID 官方 IP 库导入到项目 assets/ip_library/，并生成 manifest。"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

SRC = Path(r"C:\Users\Jered\下载\VIPKID\01.水彩2D人物")
DST = Path(r"C:\Users\Jered\picturebook-auto\assets\ip_library")
DST.mkdir(parents=True, exist_ok=True)

# (源相对路径, 项目 key, 显示名, 类别, 性别, 年龄档, 默认描述)
LIB = [
    # ---------- 主角 ----------
    ("L3-6主角/Mia10.png",   "mia_10",   "Mia (10y)",   "protagonist", "girl", 10,
     "亚洲女孩，棕色长发扎单束高马尾+齐刘海，淡紫色长袖polo+白色长裤+白色低帮运动鞋"),
    ("L3-6主角/Mia12.png",   "mia_12",   "Mia (12y)",   "protagonist", "girl", 12,
     "亚洲女孩，棕色长发扎单束高马尾+齐刘海，淡紫色长袖polo+白色长裤+白色低帮运动鞋"),
    ("L3-6主角/Tommy10.png", "tommy_10", "Tommy (10y)", "protagonist", "boy", 10,
     "亚洲男孩，棕色蓬松短发清爽，蓝色短袖polo+蓝色牛仔裤+白色低帮运动鞋"),
    ("L3-6主角/Tommy12.png", "tommy_12", "Tommy (12y)", "protagonist", "boy", 12,
     "亚洲男孩，棕色蓬松短发清爽，蓝色短袖polo+蓝色牛仔裤+白色低帮运动鞋"),
    # ---------- 朋友 ----------
    ("朋友/Ali6.png",   "ali_6",   "Ali (6y)",   "supporting", "boy",  6,
     "深肤色小男孩，黑色卷短发，亮黄色短袖T恤+橙色短裤"),
    ("朋友/Cate8.png",  "cate_8",  "Cate (8y)",  "supporting", "girl", 8,
     "亚洲女孩，棕色齐肩波浪长发自然散开，粉色长袖+米色裙子"),
    ("朋友/Cate10.png", "cate_10", "Cate (10y)", "supporting", "girl", 10,
     "亚洲女孩，棕色齐肩波浪长发自然散开，粉色长袖+米色裙子"),
    # ---------- 黑人朋友 ----------
    ("朋友/黑人女孩/黑人女孩 12岁.jpg",   "black_girl_12", "黑人女孩 (12y)", "supporting", "girl", 12,
     "非洲裔黑人女孩，黑色卷曲长发，亮色T恤+牛仔裤"),
    ("朋友/黑人女孩/黑人小女孩 10岁.jpg", "black_girl_10", "黑人女孩 (10y)", "supporting", "girl", 10,
     "非洲裔黑人小女孩，黑色双扎卷发，亮色T恤+短裤"),
    ("朋友/黑人女孩/黑人小女孩 8岁.jpg",  "black_girl_8",  "黑人女孩 (8y)",  "supporting", "girl", 8,
     "非洲裔黑人小女孩，黑色蓬松短卷发，亮色T恤+短裤"),
    ("朋友/黑人男孩/黑人男孩 12岁.jpg",  "black_boy_12",  "黑人男孩 (12y)", "supporting", "boy",  12,
     "非洲裔黑人男孩，黑色短卷发，T恤+长裤"),
    ("朋友/黑人男孩/黑人男孩 10岁.jpg",  "black_boy_10",  "黑人男孩 (10y)", "supporting", "boy",  10,
     "非洲裔黑人男孩，黑色短卷发，T恤+短裤"),
    ("朋友/黑人男孩/黑人男孩 8岁.jpg",   "black_boy_8",   "黑人男孩 (8y)",  "supporting", "boy",  8,
     "非洲裔黑人小男孩，黑色短卷发，T恤+短裤"),
    # ---------- 家人 ----------
    ("绘本角色爸爸妈妈4.8版本/妈妈.png", "mom",     "妈妈", "family", "woman", 35,
     "亚洲妈妈，棕色长卷发，温柔微笑，米白色长袖+深色长裤"),
    ("绘本角色爸爸妈妈4.8版本/爸爸.png", "dad",     "爸爸", "family", "man",   38,
     "亚洲爸爸，棕色短发，温和眼镜，深蓝色长袖衬衫+卡其裤"),
    ("绘本角色爷爷奶奶4.8/Grandma奶奶.png", "grandma", "奶奶", "family", "woman", 65,
     "亚洲奶奶，白色短卷发，慈祥微笑，淡蓝色开衫+深色长裙"),
    ("绘本角色爷爷奶奶4.8/Grandpa爷爷.png", "grandpa", "爷爷", "family", "man",   68,
     "亚洲爷爷，白色短发，慈祥微笑，米色毛衣+深色长裤"),
    # ---------- 老师 / Dino / Cat ----------
    ("Teacher.png", "teacher", "Teacher Kim", "adult", "woman", 28,
     "亚洲女老师，棕色齐肩短发，亲切微笑，浅色长袖+深色长裙"),
    ("Cat.png",     "cat",     "Cat",         "pet",   "",       0, "橘色卡通水彩猫"),
    ("Dino/Dino1.png", "dino",  "Dino",       "brand", "",       0,
     "黄色卡通小恐龙IP，VIPKID Dino Reading Club 品牌形象"),
]

EXTRA = [
    # Anna (已在项目内，作为 L5 What Makes a Good Friend 专书主角)
    (Path(r"C:\Users\Jered\picturebook-auto\assets\characters\anna_age12.png"),
     "anna_12", "Anna (12y)", "protagonist", "girl", 12,
     "亚洲女孩，黑色头发扎两条低马尾(耳下)+中分轻刘海，"
     "芥末黄色圆领针织毛衣+卡其色直筒长裤+白色低帮运动鞋，"
     "不戴眼镜不戴发箍，大眼睛圆脸小鼻子腮粉，温和微笑"),
]


def main() -> None:
    manifest: list[dict] = []

    for rel, key, name, kind, gender, age, desc in LIB:
        src = SRC / rel
        if not src.exists():
            print(f"SKIP missing: {rel}")
            continue
        ext = src.suffix.lower()
        dst = DST / f"{key}{ext}"
        shutil.copy(src, dst)
        manifest.append({
            "key": key, "name": name, "kind": kind, "gender": gender,
            "age": age, "desc": desc,
            "image": f"assets/ip_library/{dst.name}",
            "size_kb": dst.stat().st_size // 1024,
        })

    for src, key, name, kind, gender, age, desc in EXTRA:
        if not src.exists():
            print(f"SKIP missing extra: {src}")
            continue
        dst = DST / f"{key}{src.suffix.lower()}"
        shutil.copy(src, dst)
        manifest.append({
            "key": key, "name": name, "kind": kind, "gender": gender,
            "age": age, "desc": desc,
            "image": f"assets/ip_library/{dst.name}",
            "size_kb": dst.stat().st_size // 1024,
        })

    manifest_path = DST / "_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"OK Imported {len(manifest)} IPs")
    by_kind: dict[str, list[str]] = {}
    for m in manifest:
        by_kind.setdefault(m["kind"], []).append(m["key"])
    for kind, keys in sorted(by_kind.items()):
        print(f"  [{kind:11}] {len(keys):>2} : {', '.join(keys)}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
