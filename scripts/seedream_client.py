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

import json
import time
from pathlib import Path
from typing import Iterable

import requests
from PIL import Image, ImageDraw

from config import (
    IMAGE_HOST_PROVIDER,
    IMAGE_POLL_INTERVAL,
    IMAGE_POLL_MAX_TRIES,
    IMAGE_SIZE,
    JIMENG_API_KEY,
    JIMENG_BASE_URL,
    JIMENG_MODEL,
    REQUEST_RETRIES,
    REQUEST_TIMEOUT,
)

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) picturebook-auto/1.0"}


# ============================================================
#  图片托管：本地图 → 公网 URL（gpt-image-2 参考图只收 URL）
# ============================================================
def host_image_to_url(path: Path) -> str | None:
    """把本地图片上传到临时图床，返回公网直链。失败返回 None。

    参考图只需在生成的几秒内可访问，临时图床（tmpfiles 24h）足够。
    """
    path = Path(path)
    if not path.exists():
        return None

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
    payload: dict = {
        "model": JIMENG_MODEL,
        "prompt": prompt[:4000],
        "size": img_size,
        "n": 1,
    }
    if ref_url:
        payload["image"] = ref_url

    last_err: Exception | None = None
    for attempt in range(REQUEST_RETRIES + 1):
        try:
            task_id = _submit_task(url, headers, payload)
            img_url = _poll_task(task_id, headers)
            img_bytes = requests.get(img_url, timeout=REQUEST_TIMEOUT).content
            dest.write_bytes(img_bytes)
            return dest
        except Exception as e:
            last_err = e
            if attempt < REQUEST_RETRIES:
                time.sleep(3 * (attempt + 1))
            else:
                break

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


# ---------- 占位图（无 API / mock 时） ----------
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
