"""AI 問答測試：用假的 Gemini 回應（不連網、不花額度），確認
1. 側邊欄每一頁都有問答、全頁問答可以使用；
2. 給 AI 的參考資料來自資料庫（測試資料），並包含問題提到的日期；
3. 沒有金鑰時顯示「尚未啟用」；超過額度時擋下來；AI 忙碌時會換下一個模型。
"""
import os
import sys
import types as pytypes

import pytest

from tests.test_app import ROOT, TEST_DB, errors, run_page, seeded  # noqa: F401  (seeded 是共用的測試資料)

pytestmark = pytest.mark.skipif(not TEST_DB, reason="沒有設定 TEST_DATABASE_URL")


class FakeModels:
    def __init__(self, calls, fail_first=False):
        self.calls, self.fail_first = calls, fail_first

    def list(self):
        return [pytypes.SimpleNamespace(name=f"models/{n}", supported_actions=["generateContent"])
                for n in ["gemini-3.8-flash", "gemini-3.7-flash"]]

    def generate_content_stream(self, model, contents, config=None):
        self.calls.append({"model": model, "system": config.system_instruction, "contents": contents,
                           "thinking": config.thinking_config})
        if self.fail_first and model == "gemini-3.8-flash":
            raise RuntimeError("503 UNAVAILABLE. This model is currently experiencing high demand.")
        if model == "gemini-3.7-flash" and str(config.thinking_config.thinking_level).endswith("MINIMAL"):
            raise RuntimeError("400 INVALID_ARGUMENT. Thinking level MINIMAL is not supported for this model.")
        for piece in ["【事實】測試回答：", "加權指數上漲。"]:
            yield pytypes.SimpleNamespace(text=piece)


@pytest.fixture
def fake_gemini(monkeypatch):
    import google.genai
    calls = {"list": [], "fail_first": False}

    class FakeClient:
        def __init__(self, api_key, http_options=None):
            self.models = FakeModels(calls["list"], calls["fail_first"])

    monkeypatch.setattr(google.genai, "Client", FakeClient)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    return calls


def test_sidebar_chat(seeded, fake_gemini):
    # 側邊欄寫在入口程式（streamlit_app.py），每一頁都會執行；AppTest 切換頁面後讀不到入口程式的側邊欄，
    # 所以這裡只測首頁，其他頁面在正式網站上實測。
    # AppTest 在 st.navigation 的 App 重新執行後，會讀不到入口程式的側邊欄（正式網站不會），
    # 所以用「待回答的問題」在第一次執行時送出。
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    st.cache_data.clear()
    st.cache_resource.clear()
    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=60)
    at.session_state["qa_pending"] = "最近台股怎麼了？"
    at.run()
    assert not errors(at), errors(at)
    assert "qa_input_sidebar" in [c.key for c in at.sidebar.chat_input]
    assert any("測試回答" in m.value for m in at.sidebar.markdown), "側邊欄沒有顯示 AI 回答"
    assert fake_gemini["list"][-1]["contents"][-1]["parts"][0]["text"] == "最近台股怎麼了？"


def test_ask_page_answers_from_database(seeded, fake_gemini):
    at = run_page("pages/ask.py")
    assert not errors(at), errors(at)
    assert not [c for c in at.sidebar.chat_input], "全頁問答時側邊欄不應重複出現輸入框"
    at.chat_input(key="qa_input_page").set_value("11/13 台股為什麼上漲？").run()
    assert not errors(at), errors(at)
    texts = [m.value for m in at.markdown]
    assert any("測試回答" in t for t in texts), "沒有顯示 AI 回答"
    call = fake_gemini["list"][-1]
    assert "測試事件" in call["system"], "參考資料應包含資料庫中的事件"
    assert "台股加權指數" in call["system"] and "國際經濟變項" in call["system"]
    assert "問題提到的日期" in call["system"], "問題提到的日期應補上當天資料"
    assert call["contents"][-1]["parts"][0]["text"] == "11/13 台股為什麼上漲？"
    assert call["thinking"] is not None and str(call["thinking"].thinking_level).endswith("MINIMAL"), "問答要把思考程度設為最低"
    assert "時間順序" in call["system"], "要提醒 AI 美股收盤在台股之後"


def test_follow_up_keeps_history_and_falls_back_on_busy_model(seeded, fake_gemini):
    fake_gemini["fail_first"] = True  # 3.8 忙碌 → 3.7 不支援 MINIMAL → 3.7 用 LOW 成功
    at = run_page("pages/ask.py")
    at.chat_input(key="qa_input_page").set_value("第一題").run()
    at.chat_input(key="qa_input_page").set_value("第二題").run()
    assert not errors(at), errors(at)
    models = [c["model"] for c in fake_gemini["list"]]
    assert "gemini-3.7-flash" in models, "最新模型忙碌時要改用下一個"
    levels = [str(c["thinking"].thinking_level) for c in fake_gemini["list"] if c["model"] == "gemini-3.7-flash"]
    assert any(lv.endswith("LOW") for lv in levels), "不支援 MINIMAL 時要改用 LOW"
    assert any("測試回答" in m.value for m in at.markdown)
    last = fake_gemini["list"][-1]["contents"]
    assert [c["parts"][0]["text"] for c in last if c["role"] == "user"][-2:] == ["第一題", "第二題"]


def test_not_enabled_without_key(seeded, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    at = run_page("pages/ask.py")
    assert not errors(at), errors(at)
    assert any("尚未啟用" in i.value for i in at.info)


def test_session_limit(seeded, fake_gemini, monkeypatch):
    sys.path.insert(0, str(ROOT / "app"))
    import ai_chat
    monkeypatch.setattr(ai_chat, "PER_SESSION_PER_HOUR", 1)
    at = run_page("pages/ask.py")
    at.chat_input(key="qa_input_page").set_value("第一題").run()
    at.chat_input(key="qa_input_page").set_value("第二題").run()
    assert any("每小時最多問" in w.value for w in at.warning)
    assert len(fake_gemini["list"]) == 1, "超過上限的問題不能送給 AI"
