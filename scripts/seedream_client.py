"""gpt-image-2（imarouter 托管）图片生成客户端 + 占位图。

2026-06-02 迁移：从火山 Seedream（同步）换到 imarouter gpt-image-2（异步任务制）。

生成链路：
  1. POST {base}/images/generations  →  返回 task_id
  2. 轮询 GET {base}/images/generations/{task_id}  →  data.status == "succeeded"
  3. 下载 data.url（阿里云 OSS 临时直链）写入 dest

参考图（锁 IP 形象 / 图生图）：
  - gpt-image-2 只接受 **单个 image URL**（base64 / 多图都不支持）
  - 本地参考图需先托管成公网 URL（临时图床即可，生成时只拉取一次）
  - 已是 URL 的参考（如上一轮输出 OSS url，做链式图生图）直接用
"""
from __future__ import annotations

import base64
import json
import re
import threading
import time
from pathlib import Path
from typing import Iterable

import requests
from PIL import Image, ImageDraw, ImageFilter

from config import (
    ARK_API_KEY,
    ARK_BASE_URL,
    enforce_prompt_budget as _enforce_prompt_budget,
    GPT_CLEAN_STYLE_DIRECTIVE,
    GPT_CLEAN_STYLE_ECHO,
    IMAGE_DELIVER_PRINT,
    IMAGE_HOST_PROVIDER,
    IMAGE_POLL_INTERVAL,
    IMAGE_POLL_MAX_TRIES,
    IMAGE_SELF_REVIEW,
    IMAGE_SIZE,
    IMAGE_QUALITY,
    IMAGE_TARGET_PRINT,
    IMAGE_TARGET_RATIO,
    IMAGE_UPSCALE_METHOD,
    IMAGE_USM_PERCENT,
    IMAGE_USM_RADIUS,
    IMAGE_USM_THRESHOLD,
    IMAGE_USM_EDGE_ONLY,
    IMAGE_USM_EDGE_GAIN,
    IMAGE_FLAT_DENOISE,
    IMAGE_FLAT_DENOISE_RADIUS,
    IMAGE_PRINT_DPI,
    IMAGE_PRINT_DELIVER_PX,
    IMAGE_DELIVER_CMYK,
    IMAGE_DELIVER_TIFF,
    IMAGE_DELIVER_PDF,
    IMAGE_CMYK_PROFILE,
    IMAGE_PRINT_UNSHARP,
    IMAGE_WATERMARK,
    JIMENG_API_KEY,
    JIMENG_BASE_URL,
    JIMENG_MODEL,
    JIMENG_SEEDREAM_MODEL,
    JIMENG_SEEDREAM_SIZE,
    L02_PIPELINE,
    REQUEST_RETRIES,
    REQUEST_TIMEOUT,
    VISION_REVIEW_MODEL,
    resolve_image_backend,
)

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) picturebook-auto/1.0"}


# ============================================================
#  后处理：3:2 直出 → 居中裁 4:3 → 放大到精细印刷 2000×1500（方案A）
# ============================================================
def crop_to_ratio(img: "Image.Image", ratio: tuple[int, int] = IMAGE_TARGET_RATIO) -> "Image.Image":
    """居中裁切到目标宽高比（默认 4:3）。3:2(1536x1024) → 4:3(1365x1024)。"""
    rw, rh = ratio
    w, h = img.size
    target_ar = rw / rh
    cur_ar = w / h
    if abs(cur_ar - target_ar) < 1e-3:
        return img
    if cur_ar > target_ar:
        # 太宽 → 裁左右
        new_w = int(round(h * target_ar))
        left = (w - new_w) // 2
        return img.crop((left, 0, left + new_w, h))
    # 太高 → 裁上下
    new_h = int(round(w / target_ar))
    top = (h - new_h) // 2
    return img.crop((0, top, w, top + new_h))


def _upscale_esrgan(img: "Image.Image", target: tuple[int, int]) -> "Image.Image | None":
    """尝试用 Real-ESRGAN 超分；未安装/失败则返回 None 让调用方回退 Lanczos。

    依次探测两个常见 Real-ESRGAN Python 绑定：
      - realesrgan_ncnn_py（NCNN，CPU/GPU 通吃，无需 torch）
      - realesrgan（基于 torch 的官方实现）
    任一可用即用其超分（自带高质量细节恢复，无需再叠 USM）；都不可用则 None。
    """
    src = img.convert("RGB")
    # 绑定一：realesrgan_ncnn_py
    try:
        from realesrgan_ncnn_py import Realesrgan  # type: ignore

        engine = Realesrgan(gpuid=0)
        out = engine.process_pil(src)
        return out.resize(target, Image.LANCZOS) if out.size != target else out
    except Exception:
        pass
    # 绑定二：realesrgan（torch）
    try:
        import numpy as np  # type: ignore
        from realesrgan import RealESRGANer  # type: ignore
        from basicsr.archs.rrdbnet_arch import RRDBNet  # type: ignore

        model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64,
                        num_block=23, num_grow_ch=32, scale=4)
        up = RealESRGANer(scale=4, model_path=None, model=model, half=False)
        arr, _ = up.enhance(np.array(src), outscale=4)
        out = Image.fromarray(arr)
        return out.resize(target, Image.LANCZOS) if out.size != target else out
    except Exception:
        return None


def _edge_mask(im: "Image.Image", gain: float) -> "Image.Image":
    """生成柔和的【边缘掩膜】(L 模式)：边缘处≈白(255)、平滑/渐变区≈黑(0)。

    用于把锐化/降噪【分区】：仅在边缘锐化、仅在平滑区降噪——避免 USM 把水彩底颗粒
    在大片渐变区放大成斑驳色斑。
    """
    gray = im.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    # 轻微膨胀 + 模糊，得到平滑过渡的掩膜，避免硬边
    edges = edges.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(1.2))
    g = max(0.5, gain)
    return edges.point(lambda v: 255 if v * g >= 255 else int(v * g))


def _upscale_to(im: "Image.Image", target: tuple[int, int]) -> "Image.Image":
    """把图升到目标像素：优先 Real-ESRGAN（高质量，无需 USM）；不可用则
    Lanczos + 【弱化·边缘限定】USM + 平滑区轻度降噪（治色斑/磕碎感）。

    可调参数见 config：IMAGE_USM_*（弱化的 USM）、IMAGE_USM_EDGE_ONLY（仅边缘锐化）、
    IMAGE_FLAT_DENOISE（平滑区降噪）。把 IMAGE_UPSCALE_METHOD=lanczos 可跳过 ESRGAN 探测。
    """
    method = (IMAGE_UPSCALE_METHOD or "").lower()
    # 默认（非显式 lanczos）都先探测 Real-ESRGAN；探到即用，自带细节恢复、无需 USM。
    if method != "lanczos":
        out = _upscale_esrgan(im, target)
        if out is not None:
            return out

    out = im.resize(target, Image.LANCZOS)
    if not IMAGE_PRINT_UNSHARP:
        return out

    # 弱化版 USM：旧式 percent=45/threshold=3 会把渐变区颗粒放大成色斑；
    # 这里降到 percent≈22/threshold≈6，并默认【仅作用于边缘】。
    sharp = out.filter(ImageFilter.UnsharpMask(
        radius=IMAGE_USM_RADIUS, percent=IMAGE_USM_PERCENT, threshold=IMAGE_USM_THRESHOLD))

    if IMAGE_USM_EDGE_ONLY:
        mask = _edge_mask(out, IMAGE_USM_EDGE_GAIN)
        # 边缘用锐化结果、平滑区保留未锐化原图 → 平滑区不再被放大成色斑
        out = Image.composite(sharp, out, mask)
        if IMAGE_FLAT_DENOISE:
            # 仅平滑区(非边缘)做极轻高斯降噪，抹掉斑驳色斑/磕碎感、保留均匀细纸纹
            from PIL import ImageChops
            flat_mask = ImageChops.invert(mask)
            denoised = out.filter(ImageFilter.GaussianBlur(IMAGE_FLAT_DENOISE_RADIUS))
            out = Image.composite(denoised, out, flat_mask)
    else:
        out = sharp
    return out


def postprocess_4k(path: Path) -> Path:
    """对已落地的图做 方案A 后处理：居中裁 4:3 → 放大到工作图尺寸（进 PPT），并写入 DPI。原地覆盖。"""
    if not IMAGE_DELIVER_PRINT:
        return path
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            im = crop_to_ratio(im, IMAGE_TARGET_RATIO)
            out = _upscale_to(im, IMAGE_TARGET_PRINT)
            out.save(path, dpi=(IMAGE_PRINT_DPI, IMAGE_PRINT_DPI))
    except Exception as e:
        # 后处理失败不影响主流程：保留原图
        print(f"[postprocess_4k] 跳过放大（保留原图）: {e}")
    return path


# ============================================================
#  A5 印刷交付：高分辨率 + 300DPI + CMYK + TIFF / PDF
# ============================================================
_CMYK_PROFILES_CACHE: dict | None = None


def _load_cmyk_transform():
    """返回 (srgb_profile, cmyk_profile) ImageCms 句柄；无可用 CMYK ICC 时返回 None。"""
    global _CMYK_PROFILES_CACHE
    if _CMYK_PROFILES_CACHE is not None:
        return _CMYK_PROFILES_CACHE
    result = None
    try:
        from PIL import ImageCms  # type: ignore
        cmyk_path = ""
        # 1) 用户显式指定的 ICC
        if IMAGE_CMYK_PROFILE and Path(IMAGE_CMYK_PROFILE).exists():
            cmyk_path = IMAGE_CMYK_PROFILE
        else:
            # 2) 仓库内自带 / 常见系统位置
            candidates = [
                Path(__file__).resolve().parent.parent / "assets" / "icc" / "USWebCoatedSWOP.icc",
                Path("C:/Windows/System32/spool/drivers/color/USWebCoatedSWOP.icc"),
                Path("C:/Windows/System32/spool/drivers/color/JapanColor2001Coated.icc"),
            ]
            for c in candidates:
                if c.exists():
                    cmyk_path = str(c)
                    break
        if cmyk_path:
            srgb = ImageCms.createProfile("sRGB")
            cmyk = ImageCms.getOpenProfile(cmyk_path)
            result = {"cms": ImageCms, "srgb": srgb, "cmyk": cmyk, "path": cmyk_path}
    except Exception as e:
        print(f"[cmyk] ICC 加载失败，改用 Pillow 内置转换: {e}")
        result = None
    _CMYK_PROFILES_CACHE = result or {}
    return _CMYK_PROFILES_CACHE


def _to_cmyk(im: "Image.Image") -> "Image.Image":
    """RGB → CMYK：优先走 ICC 色彩转换（准确），否则用 Pillow 内置转换（近似）。"""
    prof = _load_cmyk_transform()
    if prof:
        try:
            cms = prof["cms"]
            return cms.profileToProfile(
                im.convert("RGB"), prof["srgb"], prof["cmyk"],
                renderingIntent=0, outputMode="CMYK",
            )
        except Exception as e:
            print(f"[cmyk] ICC 转换失败，回退内置: {e}")
    return im.convert("CMYK")


def deliver_print_assets(
    src: Path,
    out_dir: Path,
    base_name: str,
    *,
    target_px: tuple[int, int] | None = None,
    dpi: int | None = None,
) -> dict[str, Path]:
    """生成印刷交付件：高分辨率 + 300DPI + CMYK 的 TIFF / PDF。

    Returns: {"tiff": Path, "pdf": Path}（按开关产出，失败项跳过）。
    """
    src = Path(src)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target_px = target_px or IMAGE_PRINT_DELIVER_PX
    dpi = dpi or IMAGE_PRINT_DPI
    produced: dict[str, Path] = {}
    try:
        with Image.open(src) as im:
            im = im.convert("RGB")
            im = crop_to_ratio(im, IMAGE_TARGET_RATIO)
            hi = _upscale_to(im, target_px)
            cmyk = _to_cmyk(hi) if IMAGE_DELIVER_CMYK else hi

            if IMAGE_DELIVER_TIFF:
                tiff_path = out_dir / f"{base_name}.tif"
                # LZW 无损压缩；写入 300DPI；CMYK（或 RGB 回退）
                cmyk.save(tiff_path, format="TIFF", dpi=(dpi, dpi), compression="tiff_lzw")
                produced["tiff"] = tiff_path

            if IMAGE_DELIVER_PDF:
                pdf_path = out_dir / f"{base_name}.pdf"
                # Pillow 可把 CMYK 图写进 PDF（CMYK 300DPI）；
                # 严格 PDF/X-1a 需 Ghostscript，此处产出印刷可用的 CMYK PDF。
                save_img = cmyk if cmyk.mode in ("CMYK", "RGB", "L") else cmyk.convert("CMYK")
                save_img.save(pdf_path, format="PDF", resolution=float(dpi))
                produced["pdf"] = pdf_path
    except Exception as e:
        print(f"[deliver_print_assets] 失败（跳过）{src.name}: {e}")
    return produced


# ============================================================
#  图片托管：本地图 → 公网 URL（gpt-image-2 参考图只收 URL）
# ============================================================
# 参考图上传缓存：同一本书 8 张常用同一张定妆合集参考图，避免每张都重传图床。
# key = (绝对路径, 文件大小, mtime_ns) → 公网直链；带锁防并发重复上传（并发生图时）。
_REF_URL_CACHE: dict[str, str] = {}
_REF_LOCK = threading.Lock()


def host_image_to_url(path: Path) -> str | None:
    """把本地图片上传到临时图床，返回公网直链。失败返回 None。

    参考图只需在生成的几秒内可访问，临时图床（tmpfiles 24h）足够。
    同一文件（按 路径+大小+mtime 判定）只上传一次，结果缓存复用。
    """
    path = Path(path)
    if not path.exists():
        return None

    try:
        stt = path.stat()
        cache_key = f"{path.resolve()}|{stt.st_size}|{stt.st_mtime_ns}"
    except OSError:
        cache_key = str(path)

    # 已缓存直接返回（命中即省去一次图床往返）
    cached = _REF_URL_CACHE.get(cache_key)
    if cached:
        return cached

    # 加锁：并发生图时，同一参考图只让一个线程真正上传，其余等待后命中缓存
    with _REF_LOCK:
        cached = _REF_URL_CACHE.get(cache_key)
        if cached:
            return cached
        url = _do_host_upload(path)
        if url:
            _REF_URL_CACHE[cache_key] = url
        return url


def _do_host_upload(path: Path) -> str | None:
    """真正执行图床上传（无缓存）。"""
    provider = IMAGE_HOST_PROVIDER.lower()

    if provider in ("tmpfiles", "auto"):
        try:
            with path.open("rb") as f:
                r = requests.post(
                    "https://tmpfiles.org/api/v1/upload",
                    headers=_UA, files={"file": (path.name, f)}, timeout=120,
                )
            if r.status_code == 200:
                u = r.json().get("data", {}).get("url", "")
                if u:
                    # 直链：tmpfiles.org/xxx → tmpfiles.org/dl/xxx
                    return u.replace("tmpfiles.org/", "tmpfiles.org/dl/")
        except Exception:
            pass

    # 兜底：litterbox（catbox 临时版，72h）
    try:
        with path.open("rb") as f:
            r = requests.post(
                "https://litterbox.catbox.moe/resources/internals/api.php",
                data={"reqtype": "fileupload", "time": "72h"},
                files={"fileToUpload": (path.name, f)},
                headers=_UA, timeout=120,
            )
        if r.status_code == 200 and r.text.startswith("http"):
            return r.text.strip()
    except Exception:
        pass

    return None


def _resolve_reference_url(references: Iterable[Path | str]) -> str | None:
    """从参考列表里取第一个可用的 URL。

    - 元素是 http(s) URL → 直接用（链式图生图：上一轮输出）
    - 元素是本地 Path → 托管成 URL
    gpt-image-2 只能用一张参考图。
    """
    for ref in references:
        if not ref:
            continue
        s = str(ref)
        if s.startswith("http://") or s.startswith("https://"):
            return s
        p = Path(s)
        if p.exists():
            url = host_image_to_url(p)
            if url:
                return url
    return None


# ============================================================
#  合成「定妆参考图」（解决 gpt-image-2 单参考图 → 多角色页崩形）
# ============================================================
#  gpt-image-2 只能吃 1 张参考图，多角色页若只发主角那张，其余角色会被模型瞎编。
#  这里把本页所有角色的固定定妆图横向拼成 1 张「定妆合集」白底图，作为唯一参考发出去，
#  一张图里同时锁住每个人的长相/发型/服装，配合 prompt 里的姓名即可稳定还原。
def build_reference_sheet(
    refs: list[Path | str],
    dest: Path,
    labels: list[str] | None = None,
    *,
    panel_h: int = 768,
    gap: int = 32,
    pad: int = 40,
    label_h: int = 64,
) -> Path | None:
    """把多张角色定妆图横向拼成一张白底「定妆合集」图。

    Args:
        refs: 角色定妆图路径列表（本地文件；URL 会被跳过——拼图需要本地像素）。
        dest: 输出路径。
        labels: 与 refs 对应的名字标签（英文名渲染良好；缺失/失败则不画标签）。
    Returns:
        拼好的图路径；可用本地图不足 2 张时返回 None（调用方应回退到原单图逻辑）。
    """
    imgs: list[Image.Image] = []
    used_labels: list[str] = []
    for i, r in enumerate(refs):
        if not r:
            continue
        s = str(r)
        if s.startswith("http://") or s.startswith("https://"):
            continue  # 拼图需要本地像素
        p = Path(s)
        if not p.exists():
            continue
        try:
            im = Image.open(p).convert("RGBA")
        except Exception:
            continue
        # 贴到白底，去透明
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im).convert("RGB")
        # 统一高度
        w, h = im.size
        new_w = max(1, int(w * panel_h / h))
        im = im.resize((new_w, panel_h), Image.LANCZOS)
        imgs.append(im)
        used_labels.append((labels[i] if labels and i < len(labels) else "") or "")

    if len(imgs) < 2:
        return None  # 不足两张本地图，没必要拼，回退原逻辑

    total_w = pad * 2 + sum(im.width for im in imgs) + gap * (len(imgs) - 1)
    has_labels = any(used_labels)
    total_h = pad * 2 + panel_h + (label_h if has_labels else 0)
    sheet = Image.new("RGB", (total_w, total_h), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)

    font = None
    if has_labels:
        try:
            from PIL import ImageFont
            font = ImageFont.truetype("arial.ttf", 36)
        except Exception:
            try:
                from PIL import ImageFont
                font = ImageFont.load_default()
            except Exception:
                font = None

    x = pad
    for im, lab in zip(imgs, used_labels):
        sheet.paste(im, (x, pad))
        if has_labels and lab and font is not None:
            try:
                tb = draw.textbbox((0, 0), lab, font=font)
                tw = tb[2] - tb[0]
            except Exception:
                tw = len(lab) * 18
            tx = x + max(0, (im.width - tw) // 2)
            ty = pad + panel_h + (label_h - 40) // 2
            draw.text((tx, ty), lab, fill=(40, 40, 40), font=font)
        x += im.width + gap

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest, "PNG")
    return dest


# ============================================================
#  单角色「裁切定妆参考」（替代拼图）——降低配角崩形 + 提供最强单锚
# ============================================================
#  gpt-image-2 只吃 1 张参考图：与其拼一张多角色合集（模型会照搬白底并排排版、
#  把注意力摊薄导致配角崩形），不如给一张「干净、贴身裁切」的单角色定妆图作为最强单锚，
#  其余角色交给正向 prompt 的形象锁文字。本函数把定妆图去白边、贴身裁切、补一点留白，
#  得到一张干净的单角色锚图。
def crop_character_portrait(
    src: Path | str,
    dest: Path,
    *,
    pad_ratio: float = 0.06,
    white_thresh: int = 245,
) -> Path | None:
    """把单张角色定妆图去白边、贴身裁切成干净的单角色锚图。

    Args:
        src: 角色定妆图（本地文件）。
        dest: 输出路径。
        pad_ratio: 裁切后四周补的留白比例（相对短边）。
        white_thresh: 判定为"白底"的灰度阈值（>= 视为白）。
    Returns:
        裁好的图路径；失败（文件缺失/全白等）时返回 None，调用方应回退原图。
    """
    try:
        from PIL import ImageChops
        s = str(src)
        if s.startswith("http://") or s.startswith("https://"):
            return None
        p = Path(s)
        if not p.exists():
            return None
        im = Image.open(p).convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im).convert("RGB")

        # 用"与纯白底的差异"求主体外接框
        white = Image.new("RGB", im.size, (255, 255, 255))
        diff = ImageChops.difference(im, white).convert("L")
        mask = diff.point(lambda v: 255 if v > (255 - white_thresh) else 0)
        bbox = mask.getbbox()
        if not bbox:
            return None  # 整张近白，无主体可裁
        l, t, r, b = bbox
        w, h = im.size
        pad = int(min(w, h) * max(0.0, pad_ratio))
        l = max(0, l - pad); t = max(0, t - pad)
        r = min(w, r + pad); b = min(h, b + pad)
        if r - l < 8 or b - t < 8:
            return None
        crop = im.crop((l, t, r, b))

        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        crop.save(dest, "PNG")
        return dest
    except Exception:
        return None


# ============================================================
#  发送前敏感词清洗（避免 Azure 图像安全审核误判 safety_violations）
# ============================================================
#  说明：最终 prompt = 正向 + 负向 拼成一整段文本。Azure 的内容安全审核只看“词本身”，
#  不区分“禁止出现 XX”这种否定语境，因此即使我们是在负向里禁止它，也会被判定违规拦截。
#  这里在真正发送前，把这些高危词整体抹掉/替换为中性表达，保证安全意图不靠“写出敏感词”实现。
_MODERATION_BLOCKLIST: tuple[str, ...] = (
    "裸露", "性感", "暴露着装", "紧身暴露", "暴露",
    "血腥", "暴力", "惊悚", "恐怖", "怪兽",
    "持刀", "利器", "玩火", "成人隐喻", "成人化妆", "成人内容",
    "宗教符号", "政治",
    "nude", "naked", "nsfw", "sexy", "sexual", "violence", "blood", "gore",
)


def _sanitize_prompt_for_moderation(text: str) -> str:
    """剔除发送给 gpt-image-2 的高危敏感词（不区分大小写）。

    这些词通常出现在“请勿出现 XX”的负向里，但 Azure 审核只看词本身会误判。
    抹掉后留下的孤立分隔符（、；,）会被收敛，避免产生空洞标点。
    """
    if not text:
        return text
    out = text
    for w in _MODERATION_BLOCKLIST:
        if not w:
            continue
        # 大小写不敏感替换
        low = out.lower()
        token = w.lower()
        if token in low:
            start = 0
            pieces = []
            while True:
                i = low.find(token, start)
                if i < 0:
                    pieces.append(out[start:])
                    break
                pieces.append(out[start:i])
                start = i + len(token)
            out = "".join(pieces)
            low = out.lower()
    # 收敛被掏空后残留的标点/空白
    for sep in ("、、", "；；", "，，", ";;", ",,", "//", "  "):
        while sep in out:
            out = out.replace(sep, sep[0])
    out = out.replace("、；", "；").replace("，；", "；").replace("；、", "；")
    return out.strip(" 、，；,;\n")


# ============================================================
#  gpt-image-2 异步生图
# ============================================================
def generate_image(
    *,
    prompt: str,
    dest: Path,
    references: Iterable[Path | str] = (),
    mock: bool = False,
    label: str = "",
    seed: int | None = None,  # gpt-image-2 不支持 seed，签名保留兼容
    size: str | None = None,
    reference_url: str | None = None,
    deliver_print: bool | None = None,  # None=按配置；False=审图阶段跳过4K放大（更快）
) -> Path:
    """生成单张图写入 dest。失败抛异常。

    Args:
        references: 参考图列表（本地 Path 或 URL），仅用第一个（gpt-image-2 单图）。
        reference_url: 直接指定参考 URL（优先于 references），链式图生图用。
        size: 覆盖默认 IMAGE_SIZE（如封面想用别的比例）。
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if mock or not JIMENG_API_KEY:
        _save_mock_image(dest, prompt, label)
        return dest

    img_size = size or IMAGE_SIZE
    ref_url = reference_url or _resolve_reference_url(references)

    url = f"{JIMENG_BASE_URL.rstrip('/')}/images/generations"
    headers = {
        "Authorization": f"Bearer {JIMENG_API_KEY}",
        "Content-Type": "application/json",
    }
    safe_prompt = _sanitize_prompt_for_moderation(prompt)
    payload: dict = {
        "model": JIMENG_MODEL,
        "prompt": safe_prompt[:4000],
        "size": img_size,
        "n": 1,
    }
    # 清晰度参数（用户拍板 2026-06-09）：gpt-image 支持 quality=high，此前漏设导致画面偏软。
    if IMAGE_QUALITY:
        payload["quality"] = IMAGE_QUALITY
    if ref_url:
        payload["image"] = ref_url

    do_print = IMAGE_DELIVER_PRINT if deliver_print is None else deliver_print

    # 退避重试：限流(429/rate limit)用更长退避 + 抖动，避免并发线程同步重试再次撞限流。
    import random as _rnd
    max_attempts = REQUEST_RETRIES + 2  # 比原来多 1 次，给限流更多机会
    last_err: Exception | None = None
    for attempt in range(max_attempts):
        try:
            task_id = _submit_task(url, headers, payload)
            img_url = _poll_task(task_id, headers)
            img_bytes = requests.get(img_url, timeout=REQUEST_TIMEOUT).content
            dest.write_bytes(img_bytes)
            if do_print:
                postprocess_4k(dest)   # 方案A：居中裁 4:3 → 升 4K（审图阶段会跳过）
            return dest
        except Exception as e:
            last_err = e
            if attempt >= max_attempts - 1:
                break
            msg = str(e).lower()
            is_rate = ("429" in msg or "rate" in msg or "limit" in msg
                       or "too many" in msg or "quota" in msg)
            # 连接闪断/代理/超时/任务超时：也给更久退避（供应商反馈 gpt-image-2 偶发）
            is_conn = ("timed out" in msg or "timeout" in msg or "proxy" in msg
                       or "reset" in msg or "closed connection" in msg
                       or "max retries" in msg or "connection" in msg)
            base = 12 if (is_rate or is_conn) else 3
            time.sleep(base * (attempt + 1) + _rnd.uniform(0, 3))

    raise RuntimeError(f"gpt-image-2 生图失败（已重试）: {last_err}")


def _submit_task(url: str, headers: dict, payload: dict) -> str:
    resp = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
    if resp.status_code >= 400:
        raise RuntimeError(f"提交任务 HTTP {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    task_id = data.get("task_id") or data.get("id")
    if not task_id:
        raise RuntimeError(f"提交任务无 task_id: {json.dumps(data)[:400]}")
    return task_id


def _poll_task(task_id: str, headers: dict) -> str:
    """轮询任务直到 succeeded，返回图片 URL。"""
    poll_url = f"{JIMENG_BASE_URL.rstrip('/')}/images/generations/{task_id}"
    running = {"queued", "running", "processing", "pending", "in_progress", ""}
    for _ in range(IMAGE_POLL_MAX_TRIES):
        r = requests.get(poll_url, headers=headers, timeout=REQUEST_TIMEOUT)
        if r.status_code >= 400:
            raise RuntimeError(f"轮询 HTTP {r.status_code}: {r.text[:300]}")
        data = r.json().get("data", {})
        status = data.get("status")
        if status == "succeeded":
            img_url = data.get("url")
            if img_url:
                return img_url
            raise RuntimeError(f"任务成功但无 url: {json.dumps(data)[:300]}")
        if status and status not in running:
            raise RuntimeError(f"任务失败 status={status} err={data.get('error')}")
        time.sleep(IMAGE_POLL_INTERVAL)
    raise RuntimeError(f"任务轮询超时（{IMAGE_POLL_MAX_TRIES}×{IMAGE_POLL_INTERVAL}s）")


# ============================================================
#  火山方舟 Ark 直连：即梦/Seedream 同步生图（L0-2 双段第一段）
#  2026-06-08：与 gpt-image-2(imarouter, 异步) 并存。即梦支持多张 base64 参考图 + 4:3 直出。
# ============================================================
def _encode_image_b64(path: Path) -> str:
    """本地图 → data URI（火山即梦接受 base64 参考图，可多张锁 IP）。"""
    data = Path(path).read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    ext = Path(path).suffix.lower().lstrip(".")
    mime = "jpeg" if ext in ("jpg", "jpeg") else "png"
    return f"data:image/{mime};base64,{b64}"


def _ark_extract_url(data: dict) -> str | None:
    if isinstance(data.get("data"), list) and data["data"]:
        item = data["data"][0]
        if isinstance(item, dict) and item.get("url"):
            return item["url"]
    return data.get("url")


def _ark_extract_b64(data: dict) -> str | None:
    if isinstance(data.get("data"), list) and data["data"]:
        item = data["data"][0]
        if isinstance(item, dict) and item.get("b64_json"):
            return item["b64_json"]
    return None


def generate_image_jimeng(
    *,
    prompt: str,
    dest: Path,
    references: Iterable[Path | str] = (),
    size: str | None = None,
    mock: bool = False,
    label: str = "",
    deliver_print: bool = False,
) -> Path:
    """火山方舟 Ark 即梦/Seedream 同步生图（写入 dest）。失败抛异常。

    - 同步响应：data[0].url 或 data[0].b64_json
    - 参考图：多张 base64（锁 IP 形象，图生图）
    - 默认 4:3 直出（JIMENG_SEEDREAM_SIZE），通常不需后裁；deliver_print=True 时才走 4K 后处理。
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if mock or not ARK_API_KEY:
        _save_mock_image(dest, prompt, label or "jimeng")
        return dest

    url = f"{ARK_BASE_URL.rstrip('/')}/images/generations"
    headers = {
        "Authorization": f"Bearer {ARK_API_KEY}",
        "Content-Type": "application/json",
    }
    safe_prompt = _sanitize_prompt_for_moderation(prompt)
    payload: dict = {
        "model": JIMENG_SEEDREAM_MODEL,
        "prompt": safe_prompt[:1800],
        "size": size or JIMENG_SEEDREAM_SIZE,
        "response_format": "url",
        "watermark": IMAGE_WATERMARK,
        "sequential_image_generation": "disabled",
    }
    refs = [Path(p) for p in references if p and Path(str(p)).exists()]
    if refs:
        encoded = [_encode_image_b64(p) for p in refs[:4]]
        payload["image"] = encoded[0] if len(encoded) == 1 else encoded

    import random as _rnd
    max_attempts = REQUEST_RETRIES + 2
    last_err: Exception | None = None
    for attempt in range(max_attempts):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
            if resp.status_code >= 400:
                raise RuntimeError(f"Ark HTTP {resp.status_code}: {resp.text[:500]}")
            data = resp.json()
            img_url = _ark_extract_url(data)
            if img_url:
                dest.write_bytes(requests.get(img_url, timeout=REQUEST_TIMEOUT).content)
            else:
                b64 = _ark_extract_b64(data)
                if not b64:
                    raise RuntimeError(f"Ark 响应无 url/b64_json: {json.dumps(data)[:400]}")
                dest.write_bytes(base64.b64decode(b64))
            if deliver_print:
                postprocess_4k(dest)
            return dest
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt >= max_attempts - 1:
                break
            msg = str(e).lower()
            is_rate = ("429" in msg or "rate" in msg or "limit" in msg or "quota" in msg)
            is_conn = ("timed out" in msg or "timeout" in msg or "proxy" in msg
                       or "reset" in msg or "closed connection" in msg
                       or "max retries" in msg or "connection" in msg)
            time.sleep((12 if (is_rate or is_conn) else 3) * (attempt + 1) + _rnd.uniform(0, 3))
    raise RuntimeError(f"即梦(Ark)生图失败（已重试）: {last_err}")


def _loads_review_json(raw: str) -> dict | None:
    """稳健解析自审 JSON：去掉 ```json 围栏 / 提取第一个 {...} 对象。"""
    if not raw:
        return None
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def _review_image(image_path: Path, *, page_text: str = "", scene_cn: str = "",
                  story_lock: str = "",
                  cast_names: Iterable[str] = (), ip_age: int | None = None) -> dict:
    """GPT 视觉自审（用户拍板 2026-06-08）：看即梦出的图，只判定"有没有硬伤"。

    返回 {"ok": bool, "issues": [str], "fix": str}。审核失败/不可用时返回 ok=True（不强行修图）。
    检查项：① IP 是否统一(同一角色形象一致)；② 明显错误(多指/缺指/畸形肢体/五官错乱)；
            ③ 图文是否匹配(画面是否忠实本页文字，不该出现文中没有的东西)；④ 是否分身(同一角色出现多次)；
            ⑦【剧情/场景匹配】画面是否画对本页规定的关键道具/动作/场景、是否讲对本页故事（2026-06-10 新增）。
    """
    if not IMAGE_SELF_REVIEW:
        return {"ok": True, "issues": [], "fix": ""}
    try:
        from deepseek_client import deepseek_chat
        names = "、".join(n for n in cast_names if n) or "（按画面）"
        sys_p = (
            "你是儿童绘本质检员。只看图判断有没有【必须修】的硬伤，宽松对待风格偏好。"
            "只输出 JSON：{\"ok\": true/false, \"issues\": [\"...\"], \"fix\": \"一句话中文定向修图指令\"}。"
        )
        usr_text = (
            f"本页应出现的角色：{names}" + (f"（年龄约 {ip_age} 岁）" if ip_age else "") + "。\n"
            f"本页英文文字：{(page_text or '').strip()[:400]}\n"
            f"本页画面意图(中文·必须画对)：{(scene_cn or '').strip()[:500]}\n"
            + (f"本页【关键动作/道具/场景·必演锁】：{(story_lock or '').strip()[:400]}\n" if story_lock else "")
            + "判定下面几类硬伤，任一存在则 ok=false 并在 issues 写明、在 fix 给一句定向修图指令"
            "（只修该处，不要重画风格）：\n"
            "① 同一角色形象前后不一致 / IP 不统一（含【配色错】：Mia 上衣必须是紫色系，若画成黄/绿/其他色＝错；"
            "Tommy 上衣必须是蓝色系）；\n"
            "② 明显解剖错误：多指/少指、畸形手脚、五官错乱、肢体扭曲；\n"
            "③ 图文不匹配：画面出现文字里没有的关键物/人，或漏掉文字的关键动作（如文字说狗丢了却画出狗）；\n"
            "④ 分身/超员：同一个角色出现两次以上（两个 Mia/两个 Tommy/复制人）；"
            "或画面里的【儿童】超过本页应出场名单——本系列主角只有 Mia(女孩) 与 Tommy(男孩) 两个孩子，"
            "正常一页里女孩最多 1 个(Mia)、男孩最多 1 个(Tommy)，若出现第 2 个男孩或第 2 个女孩、"
            "或冒出名单之外的陌生小孩，都属于多余角色/分身，必须删掉多余的那个；\n"
            "⑤ 家具/物件比例明显失真：桌椅床门相对孩子身高过大或过小（孩子像小人国或像巨人）；\n"
            "⑥ 角色年龄/身高错位：主角 Mia/Tommy 应是同龄、身高相近的儿童"
            + (f"（约 {ip_age} 岁）" if ip_age else "")
            + "，不能一个画成幼儿、一个画成青少年或成年人；"
            "若画面里有爸爸/妈妈，必须是成熟成年人（绝不能画成小孩或青少年/teenager），"
            "若有爷爷/奶奶必须是白发老人；成年人身高必须明显高于孩子，绝不能大人小孩同高同龄。\n"
            "⑦【剧情/场景匹配·重点】对照上面的【本页画面意图】与【关键动作/道具/场景·必演锁】判断："
            "画面是否真的把本页规定的【关键动作/道具/场景】画了出来、讲对了本页故事，且主角是【亲手参与的实施者】？"
            "若出现下列任一即 ok=false：(a) 主角只是在空旷或与本页无关的室内/背景里单纯站立、并排摆拍或闲聊，"
            "缺少本页规定的关键道具/动作/场景；(b) 画面跳题或漏掉本页关键情节/关键道具（如本页应出现展柜/书架/垃圾/扫帚/狗/手机照片等却没有）；"
            "(c) 非虚构主题页缺少该主题的标志性道具/场景，退化成空泛无主题室内；"
            "(d) 主角 Mia/Tommy 被晾在画面边缘/远景当背景路人，完全脱离本页这件事，既没有专注参与本页这一刻、"
            "也没有与本页关键道具/场景发生任何关联（本系列要求双主角作为故事主角全程在场、专注参与本页活动；"
            "但要贴合本页实际——本页本就是观看/参观/听讲性质时，主角专注地看、俯身细看或指认眼前事物也算参与，"
            "不必硬做“亲手操作”，更不要因为“没动手”就误判为硬伤）；"
            "(e) 画面里出现了与本页剧情无关、本页文字也没点名的【多余陌生路人/围观人群/凑数配角】（默认画面就只有 Mia 和 Tommy；除非本页确需 1 位必要的成年人/具名角色，否则多出来的陌生人都应删掉）；"
            "fix 里要具体点明【缺了什么关键道具/动作/场景、主角该怎样亲手参与、要删掉哪些多余路人、应补成什么样】。\n"
            "若以上都没有，输出 {\"ok\": true, \"issues\": [], \"fix\": \"\"}。"
        )
        data_uri = _encode_image_b64(image_path)
        messages = [
            {"role": "system", "content": sys_p},
            {"role": "user", "content": [
                {"type": "text", "text": usr_text},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ]},
        ]
        raw = deepseek_chat(messages=messages, model=VISION_REVIEW_MODEL,
                            max_tokens=500, json_mode=True, timeout=120)
        verdict = _loads_review_json(raw)
        if not isinstance(verdict, dict):
            return {"ok": True, "issues": [], "fix": ""}
        verdict.setdefault("ok", True)
        verdict.setdefault("issues", [])
        verdict.setdefault("fix", "")
        return verdict
    except Exception as e:  # noqa: BLE001
        print(f"[review] 视觉自审跳过（不强行修图）：{e}")
        return {"ok": True, "issues": [], "fix": ""}


def _fix_prompt(issues: list[str], fix: str, cast_lock: list[str] | None = None) -> str:
    """定向修图（图生图）prompt：只修审出的硬伤，完全保留即梦的构图/画风/身份/内容。

    cast_lock：本页出场角色的【精确 IP 锁】（服装颜色/发型，按本书年龄）。因 gpt-image-2 修图
    只吃 1 张参考（草图），补人/改色全靠文字 → 必须把精确锁写死，杜绝补出藏青上衣/黑发路人。
    """
    issue_txt = "；".join(str(i) for i in issues if i) or fix
    lock_block = ""
    if cast_lock:
        lock_block = (
            "⑥【本页角色精确 IP 锁·按此还原，补人或改色都必须严格照此画】：\n"
            + "\n".join(f"   - {d}" for d in cast_lock if d) + "\n"
            "   关键：Tommy 上衣是【浅天蓝 pale sky-blue #5FA8D6~#8EC0ED】绝不是深蓝/藏青 navy/polo/牛仔；Tommy 是【棕色蓬乱短发】不是黑发长发；"
            "Mia 是【紫色长袖卫衣】+【后脑中高位马尾、用紫色发圈束发、中长波浪辫垂至肩/上背(绝不丸子头/发髻/half-up/颅顶超高马尾)】；严格对齐上面每个角色的服装与发型。\n"
        )
    else:
        lock_block = "⑥ Mia 上衣保持紫色、Tommy 上衣保持【浅蓝(不是藏青/深蓝)】；主角 Mia/Tommy 是同龄、身高相近的儿童；\n"
    out = (
        "【图生图·定向修瑕】所附参考图是本页最终画面，整体画风/构图/人物身份/场景内容【全部保留、不要重画】。"
        "仅修正以下被指出的硬伤，改动范围尽量小：\n"
        f"- 需修正：{issue_txt}\n"
        + (f"- 修图指令：{fix}\n" if fix else "")
        + "硬约束：① 不改变画风（保持即梦原画的治愈水彩观感与色调）；② 不改人物长相/身份、不新增或删减角色（除非上面明确要求补出缺失角色）；"
        "③ 同一角色只能出现一次（若有分身请删掉多余的那个）；④ 每只手 5 指、肢体五官自然；"
        "⑤ 保持原构图与镜头不变；⑦【全图无文字锁】不要新增/保留任何可辨认文字、字母、单词、数字、书名、标题、招牌字样、水印（如原画有英文招牌/横幅文字，请改成无文字的抽象图案色块）；\n"
        + lock_block
        + "若画面有爸爸/妈妈须是明显高于孩子的成熟成年人（不是青少年），爷爷/奶奶须是白发老人。"
    )
    # 与正向 prompt 同一截断/精简策略：去重精简、超软上限告警（防下游 4000 截断）。
    return _enforce_prompt_budget(out, label="定向修图")


def _self_review_and_fix(dest: Path, *, prompt: str, review_meta: dict | None,
                         label: str, deliver_print: bool | None, do_print: bool) -> Path:
    """对已生成的 dest 跑 GPT 视觉自审；仅当审出硬伤才【定向修图】(图生图，保留原画风/构图)。

    L0-2(即梦) 与 L3-6(gpt-image-2) 共用（用户拍板 2026-06-08：自动审图扩到全级别）。
    任一异常都回退到已出的原图，绝不阻断出图。
    """
    if not IMAGE_SELF_REVIEW:
        if do_print:
            postprocess_4k(dest)
        return dest
    meta = review_meta or {}
    try:
        verdict = _review_image(
            dest,
            page_text=meta.get("page_text", ""),
            scene_cn=meta.get("scene_cn", "") or prompt,
            story_lock=meta.get("story_lock", ""),
            cast_names=meta.get("cast_names", ()),
            ip_age=meta.get("ip_age"),
        )
    except Exception as e:  # noqa: BLE001
        print(f"[review] {label} 自审异常，原样交付：{e}")
        if do_print:
            postprocess_4k(dest)
        return dest
    if verdict.get("ok", True):
        if do_print:
            postprocess_4k(dest)
        return dest
    issues = verdict.get("issues") or []
    fix = verdict.get("fix") or ""
    print(f"[review] {label} 审出问题 -> 定向修图：{issues}")
    draft = dest.with_name(dest.stem + "_draft.png")
    try:
        dest.replace(draft)  # 原图留作图生图参考与回退
    except Exception:
        draft = dest
    draft_url = host_image_to_url(draft)
    if not draft_url:
        if draft != dest:
            draft.replace(dest)
        if do_print:
            postprocess_4k(dest)
        return dest
    try:
        generate_image(prompt=_fix_prompt(issues, fix, meta.get("cast_lock")), dest=dest,
                       reference_url=draft_url, mock=False,
                       label=f"{label} 定向修图", deliver_print=deliver_print)
        return dest
    except Exception as e:  # noqa: BLE001
        print(f"[review] 定向修图失败，回退原图：{e}")
        if draft != dest and draft.exists():
            draft.replace(dest)
        if do_print:
            postprocess_4k(dest)
        return dest


def generate_image_two_stage(
    *,
    prompt: str,
    dest: Path,
    references: Iterable[Path | str] = (),
    mock: bool = False,
    label: str = "",
    deliver_print: bool | None = None,
    review_meta: dict | None = None,
) -> Path:
    """L0-2 出图（用户拍板 2026-06-08 语义）：
       ① 即梦(Ark) 全程出图(带 IP 定妆 base64 参考锁脸) = 最终画风；
       ② GPT 视觉自审（IP/多指/图文匹配/分身）→ 仅当审出硬伤才【定向修图】，无问题原样交付即梦图。

    任一段异常都回退到"已出的即梦图"或纯 gpt-image-2，保证不阻断出图。
    review_meta: 可选 {"page_text","scene_cn","cast_names","ip_age"}，供自审判图文匹配。
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if mock or not ARK_API_KEY:
        # 无 Ark key 时直接走 gpt 单段（mock 也由它处理占位图）
        return generate_image(prompt=prompt, dest=dest, references=references,
                              mock=mock, label=label, deliver_print=deliver_print)
    do_print = IMAGE_DELIVER_PRINT if deliver_print is None else deliver_print
    try:
        # ① 即梦全程出图（最终画风）。直接出到 dest。
        generate_image_jimeng(prompt=prompt, dest=dest, references=references,
                              mock=False, label=f"{label} 即梦出图", deliver_print=False)
        # ② GPT 视觉自审 → 仅当有硬伤才定向修图（共用 helper）
        return _self_review_and_fix(dest, prompt=prompt, review_meta=review_meta,
                                    label=label, deliver_print=deliver_print, do_print=do_print)
    except Exception as e:  # noqa: BLE001
        print(f"[two_stage] 即梦出图失败，回退纯 gpt-image-2: {e}")
        return generate_image(prompt=prompt, dest=dest, references=references,
                              mock=False, label=label, deliver_print=deliver_print)


def _jimeng_restyle_prompt(orig_prompt: str) -> str:
    """即梦【只换画风·不改内容】图生图 prompt：保留 gpt 底图的全部内容，只重绘成治愈水彩。"""
    return (
        "【图生图 · 只换画风，绝不改内容】所附参考图是本页【最终内容稿】：人物数量、每个人的身份/长相/"
        "发型/服装与配色、站位构图、动作姿势、视线、场景与道具——全部 1:1 保留，"
        "绝不增删或复制任何人物（尤其绝不多出小孩）、绝不改人数、绝不改任何人的身份/年龄/身高/衣服颜色/位置。"
        "你唯一要做的是把它【重绘成治愈系儿童绘本水彩画风】："
        "通透柔和的水彩晕染、暖米低饱和主调 + 柔和莫兰迪点缀、明亮柔光、阴影浅淡干净、"
        "精致清晰的细墨线、前中后景空间层次与景深、画面干净细腻高级，像高品质精印实体绘本内页；"
        "不要塑料 3D 感、不要厚重油画、不要强烈硬光影。"
    )


def generate_image_gpt_base_jimeng_style(
    *,
    prompt: str,
    dest: Path,
    references: Iterable[Path | str] = (),
    mock: bool = False,
    label: str = "",
    deliver_print: bool | None = None,
    review_meta: dict | None = None,
) -> Path:
    """L0-2 新流程（用户拍板 2026-06-08）：
       ① gpt-image-2 出底图（内容/人物/构图遵循度高，按参考图锁 IP，少多人/乱入）；
       ② 即梦(Seedream) 图生图【只换皮】→ 把底图重绘成治愈水彩（保留构图/人物/数量/身份/动作）；
       ③ GPT 视觉自审 → 仅硬伤定向修图。
    任一段失败都优雅回退，绝不阻断出图。"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    do_print = IMAGE_DELIVER_PRINT if deliver_print is None else deliver_print
    if mock or not ARK_API_KEY:
        # 无 Ark：退回纯 gpt-image-2（mock 也由它处理占位图）
        return generate_image(prompt=prompt, dest=dest, references=references,
                              mock=mock, label=label, deliver_print=deliver_print)
    # ① gpt-image-2 底图（内容主导）
    gpt_base = dest.with_name(dest.stem + "_gptbase.png")
    try:
        generate_image(prompt=prompt, dest=gpt_base, references=references,
                       mock=False, label=f"{label} gpt底图", deliver_print=False)
    except Exception as e:  # noqa: BLE001
        print(f"[gpt->即梦] gpt底图失败，回退即梦直出：{e}")
        return generate_image_two_stage(prompt=prompt, dest=dest, references=references,
                                        mock=False, label=label, deliver_print=deliver_print,
                                        review_meta=review_meta)
    # ② 即梦换皮（img2img，参考=gpt底图，只改画风）
    try:
        generate_image_jimeng(prompt=_jimeng_restyle_prompt(prompt), dest=dest,
                              references=[gpt_base], mock=False,
                              label=f"{label} 即梦换皮", deliver_print=False)
    except Exception as e:  # noqa: BLE001
        print(f"[gpt->即梦] 即梦换皮失败，用 gpt 底图交付：{e}")
        try:
            gpt_base.replace(dest)
        except Exception:
            # replace 失败（跨盘/占用）→ 字节级拷贝兜底，绝不让自审拿到半成品/旧图
            try:
                dest.write_bytes(gpt_base.read_bytes())
            except Exception as e2:  # noqa: BLE001
                print(f"[gpt->即梦] gpt 底图回退也失败，跳过自审直接交付底图：{e2}")
                return gpt_base if gpt_base.exists() else dest
    # ③ GPT 视觉自审（共用 helper）
    return _self_review_and_fix(dest, prompt=prompt, review_meta=review_meta,
                                label=label, deliver_print=deliver_print, do_print=do_print)


def generate_image_for_level(
    level: str,
    *,
    prompt: str,
    dest: Path,
    references: Iterable[Path | str] = (),
    mock: bool = False,
    label: str = "",
    deliver_print: bool | None = None,
    review_meta: dict | None = None,
) -> Path:
    """按 level 选出图后端：L0-2 双段（gpt底图→即梦换皮 或 即梦直出→GPT修），L3-6 单段(gpt-image-2)。"""
    backend = resolve_image_backend(level)
    if backend == "jimeng_refine":
        if L02_PIPELINE == "gpt_then_jimeng":
            return generate_image_gpt_base_jimeng_style(
                prompt=prompt, dest=dest, references=references,
                mock=mock, label=label, deliver_print=deliver_print, review_meta=review_meta)
        return generate_image_two_stage(prompt=prompt, dest=dest, references=references,
                                        mock=mock, label=label, deliver_print=deliver_print,
                                        review_meta=review_meta)
    # L3-6：纯 gpt-image-2 出图 → GPT 视觉自审 → 仅有硬伤才定向修图（块3·扩到全级别）
    # 用户拍板 2026-06-08：L3-6 走 GPT 时，画风英文指令【首尾双置】（治色斑/碎纹理）。
    #   - 前置：最高优先级前缀；- 末尾：简短回声。
    # 因 generate_image 内部会把 prompt 截到 4000 字符（会切掉末尾），这里预留尾部空间后再拼，
    # 保证截断后画风回声仍稳稳落在文末。
    do_print = IMAGE_DELIVER_PRINT if deliver_print is None else deliver_print
    _MAX_PROMPT = 4000  # 与 generate_image 内 safe_prompt[:4000] 对齐
    _head_body = GPT_CLEAN_STYLE_DIRECTIVE + prompt
    _reserve = max(0, _MAX_PROMPT - len(GPT_CLEAN_STYLE_ECHO))
    gpt_prompt = _head_body[:_reserve].rstrip() + GPT_CLEAN_STYLE_ECHO
    generate_image(prompt=gpt_prompt, dest=dest, references=references,
                   mock=mock, label=label, deliver_print=False)
    if mock or not IMAGE_SELF_REVIEW:
        if do_print and not mock:
            postprocess_4k(dest)
        return Path(dest)
    return _self_review_and_fix(dest, prompt=prompt, review_meta=review_meta,
                                label=label, deliver_print=deliver_print, do_print=do_print)


def generate_image_candidates(
    *,
    prompt: str,
    dest_dir: Path,
    base_name: str,
    n: int = 3,
    references: Iterable[Path | str] = (),
    mock: bool = False,
    label: str = "",
    seeds: list[int] | None = None,
    reference_url: str | None = None,
    size: str | None = None,
) -> list[Path]:
    """单页 N 候选生图（串行调用 generate_image）。

    gpt-image-2 无 seed，多样性来自模型自身随机性。失败容错：至少返回 1 张。
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    n = max(1, min(n, 5))

    # 参考图只需托管一次，复用给所有候选
    ref_url = reference_url or _resolve_reference_url(references)

    results: list[Path] = []
    errors: list[str] = []
    for i in range(1, n + 1):
        dest = dest_dir / f"{base_name}_cand{i}.png"
        try:
            generate_image(
                prompt=prompt, dest=dest, mock=mock,
                label=f"{label} cand{i}", reference_url=ref_url, size=size,
            )
            results.append(dest)
        except Exception as e:
            errors.append(f"cand{i}: {e}")

    if not results:
        raise RuntimeError(f"全部 {n} 张候选图都失败：{' | '.join(errors)}")
    return results


# ---------- 占位图（无 API / mock / 出图失败兜底） ----------
PLACEHOLDER_MAX_BYTES = 60 * 1024  # 真实页图通常 >100KB；过小视为失败占位


def is_placeholder_image(path: Path | str) -> bool:
    """判定是否为 mock/失败兜底占位图（含 [MOCK] 标记或异常小 PNG）。"""
    p = Path(path)
    if not p.is_file() or p.stat().st_size == 0:
        return True
    try:
        raw = p.read_bytes()
    except OSError:
        return True
    if b"[MOCK]" in raw:
        return True
    if p.suffix.lower() == ".png" and p.stat().st_size < PLACEHOLDER_MAX_BYTES:
        return True
    return False


def scan_placeholder_pages(img_dir: Path, pattern: str = "page_*.png") -> list[int]:
    """扫描目录内分页图，返回占位页 index 列表（page_03.png → 3）。"""
    found: list[int] = []
    if not img_dir.is_dir():
        return found
    for fp in sorted(img_dir.glob(pattern)):
        if not is_placeholder_image(fp):
            continue
        m = re.match(r"page_(\d+)", fp.stem)
        if m:
            found.append(int(m.group(1)))
    return sorted(found)


def _save_mock_image(dest: Path, prompt: str, label: str) -> None:
    w, h = 1536, 1024
    img = Image.new("RGB", (w, h), (244, 240, 232))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        v = int(232 + (y / h) * 16)
        draw.line([(0, y), (w, y)], fill=(v, v - 4, v - 12))
    draw.text((80, 80), f"[MOCK] {label}", fill=(80, 70, 60))
    y = 200
    for line in _wrap(prompt[:280], 60)[:7]:
        draw.text((80, y), line, fill=(40, 40, 40))
        y += 56
    draw.text((80, h - 100),
              "Set IMAROUTER_API_KEY in .env to render real images.",
              fill=(120, 110, 100))
    img.save(dest, "PNG")


def _wrap(s: str, width: int) -> list[str]:
    words, lines, cur = s.split(), [], []
    for w_ in words:
        if len(" ".join(cur + [w_])) > width and cur:
            lines.append(" ".join(cur))
            cur = [w_]
        else:
            cur.append(w_)
    if cur:
        lines.append(" ".join(cur))
    return lines or [s[:width]]
