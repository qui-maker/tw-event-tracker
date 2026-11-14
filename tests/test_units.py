"""不需要網路與資料庫的單元測試。執行：pytest tests/test_units.py"""
from datetime import date

from tracker.analysis.grading import abs_grade, direction, rel_label, z_score
from tracker.utils import roc_to_date, sign_from_html, title_fingerprint, to_number


def test_dates():
    assert roc_to_date("1151112") == date(2026, 11, 12)
    assert roc_to_date("115/11/12") == date(2026, 11, 12)
    assert roc_to_date("2026-11-12") == date(2026, 11, 12)
    assert roc_to_date("20261112") == date(2026, 11, 12)
    assert roc_to_date("abc") is None


def test_numbers():
    assert to_number("1,056,842,457,091") == 1056842457091
    assert to_number("-1,165.28") == -1165.28
    assert to_number("--") is None
    assert to_number("<p>12.5</p>") == 12.5
    assert sign_from_html("<p style ='color:green'>-</p>") == -1
    assert sign_from_html("<p style= color:red>+</p>") == 1
    assert sign_from_html(" ") == 0


def test_fingerprint_ignores_punctuation_and_case():
    assert title_fingerprint("Fed Holds Rates!") == title_fingerprint("fed holds rates")


def test_grades_follow_decision_log_v1():
    assert direction(0.01) == "上漲" and direction(-0.01) == "下跌" and direction(0) == "平盤"
    assert abs_grade(0.04) == (1, "微漲")
    assert abs_grade(-0.65) == (2, "小跌")
    assert abs_grade(1.0) == (3, "明顯上漲")
    assert abs_grade(-2.63) == (4, "大跌")
    assert abs_grade(-4.51) == (5, "重挫")
    assert abs_grade(None) == (None, None)


def test_relative_grade():
    prev = [1.0, -1.0] * 10        # 標準差約 1.03
    assert z_score(2.0, prev[:19]) is None   # 不足 20 天
    z = z_score(2.0, prev)
    assert 1.9 < z < 2.0
    assert rel_label(z) == "偏大"
    assert rel_label(2.6) == "極端" and rel_label(0.3) == "正常" and rel_label(None) == "資料不足"


def test_gemini_falls_back_when_model_overloaded(monkeypatch):
    """最新模型回 503 時，要自動改用下一個模型，並回報實際使用的模型。"""
    import types as pytypes
    from pydantic import BaseModel
    from tracker.analysis import llm

    class Out(BaseModel):
        ok: bool

    calls = []

    class FakeModels:
        def list(self):
            return [pytypes.SimpleNamespace(name=f"models/{n}", supported_actions=["generateContent"])
                    for n in ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.8-flash-lite", "gemini-omni-flash-preview"]]

        def generate_content(self, model, contents, config=None):
            calls.append(model)
            if model == "gemini-3.8-flash":
                raise RuntimeError("503 UNAVAILABLE. This model is currently experiencing high demand.")
            return pytypes.SimpleNamespace(parsed=Out(ok=True), text='{"ok": true}')

    class FakeClient:
        def __init__(self, api_key):
            self.models = FakeModels()

    import google.genai
    monkeypatch.setattr(google.genai, "Client", FakeClient)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    llm._model_cache.clear()
    obj, model = llm.generate_json("x", Out, "sys")
    assert obj.ok and model == "gemini-3.7-flash"
    assert calls == ["gemini-3.8-flash"] * 2 + ["gemini-3.7-flash"]
    assert llm.gemini_candidates(None)[:3] == ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.8-flash-lite"]


def test_industry_names_follow_twse_sectors():
    from tracker.config import INDUSTRIES, normalize_industry
    assert "半導體" in INDUSTRIES and INDUSTRIES["半導體"] == "IDX_SEMI"
    assert normalize_industry("晶圓代工") == "半導體"
    assert normalize_industry("金融保險業") == "金融保險"
    assert normalize_industry("航運類") == "航運"
    assert normalize_industry("太空旅遊") is None


def test_change_text_uses_points_for_rates():
    from tracker.utils import change_text
    assert change_text(5.10, 4.98, "%") == "+0.12 個百分點"
    assert change_text(110, 100, "點") == "+10.00%"
    assert change_text(1, None, "%") == "—"
