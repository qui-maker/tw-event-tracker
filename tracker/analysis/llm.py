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


def _pick_gemini_model(client) -> str:
    """自動挑選可用的 Flash 系列模型（優先正式版、非 lite）。可用 GEMINI_MODEL 指定。"""
    if os.getenv("GEMINI_MODEL"):
        return os.environ["GEMINI_MODEL"]
    if "gemini" in _model_cache:
        return _model_cache["gemini"]
    skip = ("image", "tts", "audio", "live", "embedding", "veo", "imagen", "thinking-exp", "computer")
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
    _model_cache["gemini"] = sorted(names, key=rank)[-1]
    return _model_cache["gemini"]


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
    model = _pick_gemini_model(client)
    config = types.GenerateContentConfig(system_instruction=system, temperature=temperature,
                                         response_mime_type="application/json", response_schema=schema)
    last = None
    for attempt in range(4):
        try:
            resp = client.models.generate_content(model=model, contents=prompt, config=config)
            parsed = resp.parsed if isinstance(resp.parsed, schema) else schema.model_validate_json(_strip(resp.text))
            return parsed, model
        except Exception as e:  # noqa: BLE001
            last = e
            msg = str(e)
            if any(k in msg for k in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "500")) and attempt < 3:
                time.sleep(20 * (attempt + 1))  # 免費額度限流時等一下再試
                continue
            if "validation" in msg.lower() and attempt < 1:
                continue
            break
    raise LLMError(f"Gemini 呼叫失敗：{type(last).__name__}: {str(last)[:500]}")


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
