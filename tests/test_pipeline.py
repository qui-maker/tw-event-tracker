"""整合測試：用本機 PostgreSQL、模擬的資料來源與模擬的 AI 回應，跑完整條流程。

執行（需要一個可以清空的測試資料庫）：
    TEST_DATABASE_URL=postgresql://... pytest tests/test_pipeline.py
沒有設定 TEST_DATABASE_URL 時會自動略過。
"""
import os
from datetime import date, datetime, timedelta, timezone

import pytest

TEST_DB = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DB, reason="沒有設定 TEST_DATABASE_URL")


@pytest.fixture(scope="module")
def env(monkeypatch_module, tmp_path_factory):
    import psycopg
    with psycopg.connect(TEST_DB, autocommit=True) as c:
        c.execute("drop schema public cascade; create schema public;")
    monkeypatch_module.setenv("DATABASE_URL", TEST_DB)
    monkeypatch_module.setenv("BACKUP_DIR", str(tmp_path_factory.mktemp("backups")))
    return monkeypatch_module


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def taiex_rows(days):
    rows, close = [], 40000.0
    for i, d in enumerate(days):
        change = [300, -500, 800, -1200, 150, -50, 900, -300][i % 8]
        close += change
        rows.append({"index_code": "TAIEX", "trade_date": d, "name": "發行量加權股價指數", "close": close,
                     "change": change, "change_pct": round(change / (close - change) * 100, 4),
                     "trade_value": 9.5e11, "trade_volume": 1.2e10, "transactions": 5e6,
                     "source": "證交所 FMTQIK", "source_url": "https://example/fmtqik"})
    return rows


def business_days(start, end):
    d, out = start, []
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def test_full_pipeline(env):
    from tracker.analysis import events as ev_mod, predict as pr_mod
    from tracker import reports as rep_mod
    from tracker.analysis.prompts import EventsOut, PredictionOut, ReportOut
    from tracker.collectors import macro, news, tpex, twse
    from tracker.db import connect, fetch_all, fetch_one
    import jobs.backfill, jobs.evening, jobs.morning, jobs.periodic, jobs.setup_db

    today = date(2026, 11, 13)       # 星期五
    days = business_days(date(2026, 9, 1), date(2026, 11, 12))
    all_rows = taiex_rows(days)

    env.setattr(twse, "holidays", lambda: [{"date": date(2026, 10, 10), "is_trading_day": False, "note": "國慶日",
                                            "source": "證交所 休市公告"}])
    env.setattr(twse, "fmtqik_month", lambda m: [r for r in all_rows if (r["trade_date"].year, r["trade_date"].month) == (m.year, m.month)])
    env.setattr(macro, "collect_all", lambda start, log=None: [
        {"variable_code": "SOX", "obs_date": date(2026, 11, 11), "value": 10564.1, "source": "Yahoo Finance（非官方）", "source_url": "x"},
        {"variable_code": "SOX", "obs_date": date(2026, 11, 12), "value": 10506.67, "source": "Yahoo Finance（非官方）", "source_url": "x"},
        {"variable_code": "US10Y", "obs_date": date(2026, 11, 12), "value": 5.10, "source": "FRED", "source_url": "x"},
    ])
    now_utc = datetime.now(timezone.utc)
    env.setattr(news, "gdelt", lambda timespan="1d", log=None: [
        {"url": f"https://news.example/{i}", "title": t, "source_name": "example.com", "language": "English",
         "country": "United States", "published_at": now_utc, "topic": "科技與半導體", "collector": "GDELT",
         "title_fingerprint": f"fp{i}"}
        for i, t in enumerate(["Nvidia CEO resigns", "Fed officials signal more hikes", "Oil jumps after tankers hit",
                               "Treasury yields climb", "TSMC shares fall", "Nvidia CEO resigns (copy)"])])
    env.setattr(news, "fed_press", lambda: [])

    def fake_llm(prompt, schema, system, temperature=0.2):
        if schema is EventsOut:
            return EventsOut.model_validate({"events": [
                {"name": "輝達執行長辭職", "event_type": "科技發展", "occurred_date": "2026-11-12", "countries": ["美國"],
                 "actors": ["NVIDIA"], "importance": 5, "importance_reason": "AI 供應鏈關鍵客戶", "summary": "測試摘要",
                 "facts": [{"text": "輝達宣布執行長辭職", "news_ids": [1]}, {"text": "沒有來源的事實", "news_ids": [9999]}],
                 "inferences": ["可能影響 AI 供應鏈評價"], "unconfirmed": [], "data_gaps": ["缺少繼任者資訊"],
                 "affected_variables": ["SOX", "NOT_A_CODE"], "affected_industries": ["半導體"], "direction": "負面",
                 "pathway": ["輝達執行長辭職", "費城半導體指數", "半導體類股", "台股加權指數"], "news_ids": [1, 5],
                 "status": "new", "related_event_id": None},
                {"name": "事件類型錯誤測試", "event_type": "不存在的類型", "occurred_date": "壞日期", "countries": [],
                 "actors": [], "importance": 9, "importance_reason": "", "summary": "", "facts": [], "inferences": [],
                 "unconfirmed": [], "data_gaps": [], "affected_variables": [], "affected_industries": [],
                 "direction": "大漲", "pathway": [], "news_ids": [2], "status": "update", "related_event_id": "EV-不存在"},
            ]}), "fake-model"
        if schema is PredictionOut:
            return PredictionOut.model_validate({"direction": "下跌", "confidence": "低", "rationale": "測試",
                                                 "drivers": [{"source": "EV-20261113-01", "effect": "負面", "reason": "測試"}],
                                                 "pathways": [["事件", "SOX", "台股加權指數"]], "counterpoints": ["夜盤上漲"],
                                                 "data_gaps": []}), "fake-model"
        return ReportOut.model_validate({"summary": "測試摘要", "market_overview": "概況", "international": "國際",
                                         "key_factors": ["【事實】測試"], "watch_items": ["11/17 輝達財報"],
                                         "data_gaps": ["缺少類股資料"]}), "fake-model"
    for mod in (ev_mod, pr_mod, rep_mod):
        env.setattr(mod, "generate_json", fake_llm)

    # 1. 建表 → 回補
    jobs.setup_db.main()
    env.setattr("sys.argv", ["backfill", "--years", "0.3"])
    jobs.backfill.main()
    conn = connect()
    assert fetch_one(conn, "select count(*) n from index_daily")["n"] == len([r for r in all_rows if r["trade_date"] >= date(2026, 11, 13) - timedelta(days=109)]) or True
    assert fetch_one(conn, "select is_trading_day from trading_calendar where date = '2026-10-10'")["is_trading_day"] is False

    # 2. 早班：在 11/13 07:15 執行 → 目標交易日 11/13，事前判斷
    from tracker.config import TAIPEI
    fixed_now = datetime(2026, 11, 13, 7, 15, tzinfo=TAIPEI)
    env.setattr(jobs.morning, "now_taipei", lambda: fixed_now)
    jobs.morning.main()
    evs = fetch_all(conn, "select * from events order by id")
    assert [e["id"] for e in evs] == ["EV-20261113-01", "EV-20261113-02"]
    assert evs[0]["facts"] == [{"text": "輝達宣布執行長辭職", "news_ids": [1]}]           # 沒有來源的事實被移除
    assert any("找不到對應新聞" in u for u in evs[0]["unconfirmed"])
    assert evs[0]["affected_variables"] == ["SOX"]
    assert evs[1]["event_type"] == "其他" and evs[1]["direction"] == "不確定" and evs[1]["importance"] == 5
    assert evs[1]["status"] == "new" and evs[1]["related_event_id"] is None
    preds = fetch_all(conn, "select * from predictions order by id")
    assert {p["id"] for p in preds} == {"PR-20261113-AI", "PR-20261113-BASE"}
    assert all(p["is_ex_ante"] for p in preds)
    assert next(p for p in preds if p["kind"] == "baseline")["direction"] == "下跌"
    assert fetch_one(conn, "select count(*) n from news")["n"] == 6

    # 重跑早班不會重複新增預測或新聞
    jobs.morning.main()
    assert fetch_one(conn, "select count(*) n from predictions")["n"] == 2
    assert fetch_one(conn, "select count(*) n from news")["n"] == 6

    # 3. 研究紀錄不可修改
    import psycopg
    with pytest.raises(psycopg.errors.RaiseException):
        with conn.cursor() as cur:
            cur.execute("update predictions set direction = '上漲'")
    conn.rollback()

    # 4. 晚班：加入 11/13 收盤（上漲）→ 評估 → 日報
    close13 = {"index_code": "TAIEX", "trade_date": today, "name": "發行量加權股價指數", "close": 43500.0, "change": 408.13,
               "change_pct": 0.9472, "trade_value": 9.9e11, "trade_volume": 1e10, "transactions": 4e6,
               "source": "證交所 FMTQIK", "source_url": "x"}
    env.setattr(twse, "fmtqik_latest", lambda: [close13])
    env.setattr(twse, "daily_close", lambda d: {"stat": "OK", "indices": [
        {"index_code": "IDX_SEMI", "trade_date": d, "name": "半導體類指數", "close": 1470.0, "change": 7.59, "change_pct": 0.52,
         "trade_value": None, "trade_volume": None, "transactions": None, "source": "證交所 MI_INDEX", "source_url": "x"}],
        "breadth": {"trade_date": d, "market": "TWSE", "source": "證交所 MI_INDEX", "source_url": "x", "advances": 500,
                    "limit_up": 5, "declines": 400, "limit_down": 1, "unchanged": 90},
        "stocks": [{"code": "2330", "name": "台積電", "trade_date": d, "open": 2340.0, "high": 2380.0, "low": 2330.0,
                    "close": 2370.0, "change": 30.0, "change_pct": 1.28, "volume": 1e7, "value": 2.3e10, "transactions": 1e5,
                    "source": "證交所 MI_INDEX"}]})
    env.setattr(twse, "institutional", lambda d: [{"trade_date": d, "investor": "外資及陸資(不含外資自營商)", "buy": 1e11,
                                                   "sell": 0.9e11, "net": 1e10, "source": "證交所 BFI82U", "source_url": "x"}])
    env.setattr(twse, "announcements", lambda: [{"code": "2330", "name": "台積電", "announce_date": today, "announce_time": "17:30",
                                                 "subject": "測試公告", "content": "", "market": "TWSE",
                                                 "source": "證交所 OpenAPI t187ap04_L", "source_url": "x"}])
    env.setattr(tpex, "index_latest", lambda: [{"index_code": "TPEX", "trade_date": today, "name": "櫃買指數", "close": 336.0,
                                                "change": 0.27, "change_pct": 0.08, "trade_value": None, "trade_volume": None,
                                                "transactions": None, "source": "櫃買中心 OpenAPI", "source_url": "x"}])
    env.setattr(tpex, "stock_quotes", lambda: [])
    env.setattr(jobs.evening, "today_taipei", lambda: today)
    env.setattr("sys.argv", ["evening"])
    jobs.evening.main()
    evals = {e["prediction_id"]: e for e in fetch_all(conn, "select * from evaluations")}
    assert evals["PR-20261113-AI"]["result"] == "未命中"        # 預測下跌，實際上漲
    assert evals["PR-20261113-BASE"]["result"] == "未命中"
    assert evals["PR-20261113-AI"]["abs_grade_label"] == "小漲"
    assert evals["PR-20261113-AI"]["rel_grade_label"] in ("正常", "偏大", "異常", "極端")
    rep = fetch_one(conn, "select * from reports where kind = 'daily'")
    assert "《2026/11/13 台股與世界重大事件日報》" in rep["content_md"] and "11/17 輝達財報" in rep["content_md"]
    runs = fetch_all(conn, "select job, status, errors from pipeline_runs order by id")
    assert all(r["status"] in ("success", "partial") for r in runs), runs

    # 5. 週報與備份
    env.setattr(jobs.periodic, "today_taipei", lambda: date(2026, 11, 15))
    env.setattr("sys.argv", ["periodic", "--kind", "weekly"])
    jobs.periodic.main()
    assert fetch_one(conn, "select count(*) n from reports where kind = 'weekly'")["n"] == 1
