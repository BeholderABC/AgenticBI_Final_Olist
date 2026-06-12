from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from utils.settings import get_settings


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


class DeepSeekClient:
    """
    DeepSeek OpenAI-compatible Chat Completions client.
    Docs: https://api-docs.deepseek.com/zh-cn/
    """

    def __init__(self) -> None:
        s = get_settings()
        if not s.deepseek_api_key:
            raise RuntimeError(
                "Missing DEEPSEEK_API_KEY. Put it in .env or environment variables."
            )
        self.api_key = s.deepseek_api_key
        self.base_url = s.deepseek_base_url.rstrip("/")
        self.model = s.deepseek_model

    def chat(self, messages: list[ChatMessage], *, temperature: float = 0.2) -> str:
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "top_p": 1.0,
            "max_tokens": 4096,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        timeout = httpx.Timeout(120.0, connect=10.0)
        max_retries = 2
        with httpx.Client(timeout=timeout) as client:
            for attempt in range(max_retries + 1):
                try:
                    resp = client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    try:
                        data = resp.json()
                    except ValueError as e:
                        raise RuntimeError(
                            f"DeepSeek returned non-JSON response: {resp.text}"
                        ) from e
                    break
                except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.TimeoutException) as e:
                    if attempt == max_retries:
                        raise RuntimeError(
                            "DeepSeek request timed out after multiple attempts."
                        ) from e
                    continue
        

        try:
            return data["choices"][0]["message"]["content"]
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"Unexpected DeepSeek response shape: {data}") from e

