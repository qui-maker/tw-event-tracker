"""AI 服務介面：預設 Google Gemini，可切換成 Claude。

切換方式：在 GitHub Secrets 新增 AI_PROVIDER=claude 與 ANTHROPIC_API_KEY（目前只實測過 Gemini）。
所有呼叫都要求 AI 依固定的 JSON 格式回傳，程式會再用 pydantic 檢查格式。
"""
from __future__ import annotations

import json
import os
import re
import time

from pydantic import BaseModel

from tracker.utils import http_get  # noqa: F401  (保留給其他模組共用)


class LLMError(RuntimeError):
    pass


_model_cache: dict[str, str] = {}


def gemini_candidates(client) -> list[str]:
    """可用的 Gemini Flash 系列模型，依偏好排序（正式版優先、非 lite 優先、版本新的優先）。
    設定 GEMINI_MODEL 時只用指定的模型。實測：最新的模型常因需求過高回 503，所以要能依序改用下一個。"""
    if os.getenv("GEMINI_MODEL"):
        return [os.environ["GEMINI_MODEL"]]
    if "gemini" in _model_cache:
        return _model_cache["gemini"]
    skip = ("image", "tts", "audio", "live", "embedding", "veo", "imagen", "thinking-exp", "computer", "omni")
    names = []
    for m in client.models.list():
        name = (m.name or "").replace("models/", "")
        if "generateContent" in (m.supported_actions or []) and "flash" in name and not any(s in name for s in skip):
            names.append(name)
    if not names:
        raise LLMError("找不到可用的 Gemini Flash 模型")

    def rank(n: str):
        nums = [int(x) for x in re.findall(r"\d+", n.split("-flash")[0])] or [0]
        return ("preview" not in n and "exp" not in n, "lite" not in n, nums, n)
    _model_cache["gemini"] = sorted(names, key=rank, reverse=True)
    return _model_cache["gemini"]


def _is_overloaded(msg: str) -> bool:
    return any(k in msg for k in ("503", "UNAVAILABLE", "500", "INTERNAL", "overloaded", "high demand"))


def _is_quota(msg: str) -> bool:
    return any(k in msg for k in ("429", "RESOURCE_EXHAUSTED"))


def generate_json(prompt: str, schema: type[BaseModel], system: str, temperature: float = 0.2) -> tuple[BaseModel, str]:
    """送出提示詞，回傳（符合 schema 的物件, 使用的模型名稱）。"""
    provider = os.getenv("AI_PROVIDER", "gemini").lower()
    if provider == "claude":
        return _claude(prompt, schema, system, temperature)
    return _gemini(prompt, schema, system, temperature)


def _gemini(prompt, schema, system, temperature):
    from google import genai
    from google.genai import types

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise LLMError("沒有設定 GEMINI_API_KEY")
    client = genai.Client(api_key=key)
    config = types.GenerateContentConfig(system_instruction=system, temperature=temperature,
                                         response_mime_type="application/json", response_schema=schema)
    tried = []
    for model in gemini_candidates(client)[:5]:
        last = None
        for attempt in range(3):
            try:
                resp = client.models.generate_content(model=model, contents=prompt, config=config)
                parsed = resp.parsed if isinstance(resp.parsed, schema) else schema.model_validate_json(_strip(resp.text))
                if tried:  # 換過模型就記下來，讓研究紀錄看得出這次用的不是首選模型
                    print(f"  首選模型無法使用，改用 {model}（失敗：{'；'.join(tried)}）")
                return parsed, model
            except Exception as e:  # noqa: BLE001
                last, msg = e, str(e)
                if "limit: 0" in msg or "not found" in msg.lower() or "NOT_FOUND" in msg:
                    break  # 這個模型不在免費額度或不存在：直接換下一個
                if (_is_overloaded(msg) or _is_quota(msg)) and attempt < 2:
                    time.sleep(15 * (attempt + 1))
                    continue
                if "validation" in msg.lower() and attempt < 1:
                    continue
                if _is_overloaded(msg) or _is_quota(msg):
                    break  # 重試後仍忙碌或額度用完：換下一個模型
                raise LLMError(f"Gemini（{model}）呼叫失敗：{type(e).__name__}: {msg[:500]}") from e
        tried.append(f"{model}：{type(last).__name__}: {str(last)[:120]}")
    raise LLMError("所有 Gemini 模型都無法使用：" + "；".join(tried))


def _claude(prompt, schema, system, temperature):
    import requests

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("沒有設定 ANTHROPIC_API_KEY")
    model = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")
    schema_text = json.dumps(schema.model_json_schema(), ensure_ascii=False)
    body = {"model": model, "max_tokens": 8000, "temperature": temperature,
            "system": system + "\n\n只輸出符合以下 JSON Schema 的 JSON，不要任何其他文字：\n" + schema_text,
            "messages": [{"role": "user", "content": prompt}]}
    resp = requests.post("https://api.anthropic.com/v1/messages", json=body, timeout=180,
                         headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
    if resp.status_code != 200:
        raise LLMError(f"Claude 呼叫失敗：HTTP {resp.status_code} {resp.text[:300]}")
    text = "".join(b.get("text", "") for b in resp.json().get("content", []))
    return schema.model_validate_json(_strip(text)), model


def _strip(text: str) -> str:
    """去掉 AI 有時會加的 ```json 標記。"""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    return t
