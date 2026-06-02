"""DeepSeek 客户端（火山方舟托管，OpenAI 兼容协议）。

用法：
    from deepseek_client import deepseek_chat
    reply = deepseek_chat(
        system="你是儿童绘本视觉描述专家",
        user="给我写一个 200 字的画面描述：教室里 12 岁女孩 Anna 紧张地坐在课桌前",
        temperature=0.3,
    )

特性：
- 完全 OpenAI 兼容（火山方舟的 /chat/completions 接口）
- 自动重试 + 指数退避
- JSON mode 支持（response_format={"type": "json_object"}）
- 缺 key 时抛 RuntimeError（让调用方决定 fallback）
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

import requests

from config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    REQUEST_RETRIES,
    REQUEST_TIMEOUT,
)


class DeepSeekError(RuntimeError):
    """DeepSeek API 调用失败（用于区分一般异常）。"""


# 记忆每个模型不支持的参数，避免每次都「400→剔除→重试」浪费一次请求
_MODEL_UNSUPPORTED: dict[str, set[str]] = {}


def is_deepseek_available() -> bool:
    """供 UI / fallback 判断 DeepSeek 是否可用。"""
    return bool(DEEPSEEK_API_KEY)


def deepseek_chat(
    *,
    system: str = "",
    user: str = "",
    messages: Optional[list[dict]] = None,
    temperature: Optional[float] = None,
    max_tokens: int = 1500,
    json_mode: bool = False,
    model: Optional[str] = None,
    timeout: int = REQUEST_TIMEOUT,
) -> str:
    """调用 DeepSeek chat completions，返回 assistant 文本。

    Args:
        system / user: 简单二元对话。如果用 messages 则忽略这两个。
        messages: 完整 messages list（[{role, content}, ...]）。
        temperature: 0-2，画面描述类用 0.3-0.6 比较稳。
        max_tokens: 返回 token 上限。
        json_mode: 是否让 DeepSeek 返回严格 JSON（要求 system 里说明 JSON 结构）。

    Raises:
        DeepSeekError: API 调用失败（key 缺、模型未激活、网络、限流等）。
    """
    if not DEEPSEEK_API_KEY:
        raise DeepSeekError("DEEPSEEK_API_KEY 未配置（请检查 .env）")

    if messages is None:
        msgs: list[dict] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": user})
    else:
        msgs = messages

    url = f"{DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    model_id = model or DEEPSEEK_MODEL
    blocked = _MODEL_UNSUPPORTED.get(model_id, set())
    payload: dict[str, Any] = {
        "model": model_id,
        "messages": msgs,
        "max_tokens": max_tokens,
    }
    # 部分模型（如 Claude Opus via Bedrock）不支持 temperature，按需才发，
    # 并在 400「不支持/已弃用」时自动剔除重试（且记忆下来下次不发）。
    if temperature is not None and "temperature" not in blocked:
        payload["temperature"] = temperature
    if json_mode and "response_format" not in blocked:
        payload["response_format"] = {"type": "json_object"}

    last_err: Optional[Exception] = None
    for attempt in range(REQUEST_RETRIES + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code == 429:
                # 限流：指数退避后再试
                wait = 4 * (attempt + 1)
                time.sleep(wait)
                continue
            if resp.status_code >= 400:
                body = resp.text[:600]
                # 自动剔除模型不支持的参数后立即重试（不计入退避次数），并记忆
                if resp.status_code == 400 and _strip_unsupported_param(payload, body, model_id):
                    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
                    if resp.status_code >= 400:
                        raise DeepSeekError(f"HTTP {resp.status_code}: {resp.text[:600]}")
                else:
                    raise DeepSeekError(f"HTTP {resp.status_code}: {body}")
            data = resp.json()
            choices = data.get("choices") or []
            if not choices:
                raise DeepSeekError(f"响应无 choices：{json.dumps(data)[:400]}")
            content = (choices[0].get("message") or {}).get("content", "")
            return content.strip()
        except Exception as e:
            last_err = e
            if attempt < REQUEST_RETRIES:
                time.sleep(3 * (attempt + 1))

    raise DeepSeekError(f"DeepSeek 调用失败（已重试）: {last_err}")


def _strip_unsupported_param(payload: dict, error_body: str, model_id: str) -> bool:
    """若 400 错误体提示某参数不支持/已弃用，从 payload 删掉它并记忆。返回是否删了。"""
    low = error_body.lower()
    if not any(k in low for k in ("deprecated", "not supported", "unsupported", "unrecognized")):
        return False
    removed = False
    for param in ("temperature", "top_p", "frequency_penalty", "presence_penalty",
                  "response_format", "max_tokens"):
        if param in low and param in payload:
            payload.pop(param, None)
            _MODEL_UNSUPPORTED.setdefault(model_id, set()).add(param)
            removed = True
    return removed


def deepseek_chat_json(
    *,
    system: str,
    user: str,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    fallback: Any = None,
) -> Any:
    """便利方法：调用 DeepSeek 并解析为 dict/list。失败返回 fallback。"""
    try:
        raw = deepseek_chat(
            system=system, user=user,
            temperature=temperature, max_tokens=max_tokens,
            json_mode=True,
        )
        return json.loads(raw)
    except (DeepSeekError, json.JSONDecodeError) as e:
        # 调用方应该判断 fallback is None 决定怎么处理
        print(f"[deepseek_chat_json] failed: {e}")
        return fallback
