"""網站畫面測試用的「測試資料」。

⚠️ 這裡的數字全部是程式隨機產生的測試資料，不是真實市場數據。
只會寫進本機或 GitHub Actions 的暫時測試資料庫，絕不會寫進正式的 Supabase。
每一筆的來源欄位都標成「TEST 測試資料」。
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from psycopg.types.json import Jsonb

from tracker.collectors import macro
from tracker.db import insert_ignore

SRC = "TEST 測試資料（非真實）"
URL = "https://example.invalid/test"
TZ = timezone(timedelta(hours=8))


def business_days(start: date, end: date) -> list[date]:
    d, out = start, []
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def seed(conn, today: date | None = None) -> dict:
    rnd = random.Random(42)
    today = today or date.today()
    days = business_days(today - timedelta(days=560), today)

    # 加權指數與類股指數
    rows, close = [], 22000.0
    for d in days:
        pct = rnd.gauss(0.05, 1.2)
        change = close * pct / 100
        close += change
        rows.append({"index_code": "TAIEX", "trade_date": d, "name": "發行量加權股價指數", "close": round(close, 2),
                     "change": round(change, 2), "change_pct": round(pct, 4), "trade_value": rnd.uniform(3e11, 9e11),
                     "trade_volume": rnd.uniform(5e9, 1.2e10), "transactions": rnd.uniform(3e6, 6e6),
                     "source": SRC, "source_url": URL})
    insert_ignore(conn, "index_daily", rows)
    sector = []
    for code, name in [("IDX_SEMI", "半導體類指數"), ("IDX_FIN", "金融保險類指數"), ("IDX_SHIP", "航運類指數"), ("TPEX", "櫃買指數")]:
        c = 500.0
        for d in days[-80:]:
            pct = rnd.gauss(0, 1.5)
            ch = c * pct / 100
            c += ch
            sector.append({"index_code": code, "trade_date": d, "name": name, "close": round(c, 2), "change": round(ch, 2),
                           "change_pct": round(pct, 4), "source": SRC, "source_url": URL})
    insert_ignore(conn, "index_daily", sector)

    insert_ignore(conn, "market_breadth", [
        {"trade_date": d, "market": "TWSE", "advances": rnd.randint(200, 700), "declines": rnd.randint(200, 700),
         "unchanged": rnd.randint(50, 150), "limit_up": rnd.randint(0, 20), "limit_down": rnd.randint(0, 10),
         "source": SRC, "source_url": URL} for d in days[-40:]])
    insert_ignore(conn, "institutional_flows", [
        {"trade_date": d, "investor": inv, "buy": 1e10, "sell": 1e10 + rnd.gauss(0, 5e9), "net": rnd.gauss(0, 5e9),
         "source": SRC, "source_url": URL} for d in days[-40:] for inv in ["外資及陸資(不含外資自營商)", "投信", "合計"]])

    # 個股
    insert_ignore(conn, "stocks", [{"code": "2330", "name": "台積電（測試）", "market": "TWSE", "industry": "半導體業"},
                                   {"code": "2317", "name": "鴻海（測試）", "market": "TWSE", "industry": "其他電子業"}])
    srows = []
    for code, p in [("2330", 1000.0), ("2317", 200.0)]:
        for d in days[-80:]:
            pct = rnd.gauss(0, 1.8)
            ch = p * pct / 100
            p += ch
            srows.append({"code": code, "trade_date": d, "open": p - ch, "high": p * 1.01, "low": p * 0.99, "close": round(p, 2),
                          "change": round(ch, 2), "change_pct": round(pct, 4), "volume": rnd.uniform(1e7, 5e7),
                          "value": rnd.uniform(1e9, 5e10), "transactions": 50000, "source": SRC})
    insert_ignore(conn, "stock_daily", srows)
    insert_ignore(conn, "announcements", [
        {"code": "2330", "name": "台積電（測試）", "announce_date": days[-2], "announce_time": "17:30:00",
         "subject": "測試公告：董事會決議事項", "content": "測試內容", "market": "TWSE", "source": SRC, "source_url": URL}])

    # 國際變項
    insert_ignore(conn, "variables", macro.variable_definitions())
    vrows = []
    for code, _name, _cat, _unit, freq, *_ in __import__("tracker.config", fromlist=["VARIABLES"]).VARIABLES:
        v = rnd.uniform(1, 500)
        obs = days if freq != "月" else [d for d in days if d.day <= 3 and d.weekday() == 0] or days[::21]
        for d in obs:
            v *= 1 + rnd.gauss(0, 0.01)
            vrows.append({"variable_code": code, "obs_date": d, "value": round(v, 4), "source": SRC, "source_url": URL})
    insert_ignore(conn, "variable_values", vrows)

    # 新聞
    topics = ["semiconductor", "fed", "geopolitics", "energy", "trade"]
    news = [{"url": f"{URL}/news/{i}", "title": f"TEST headline {i}: chip demand and Federal Reserve outlook", "source_name": "test.invalid",
             "language": "English", "country": "United States",
             "published_at": datetime.combine(today - timedelta(days=i % 20), datetime.min.time(), TZ) + timedelta(hours=8),
             "topic": topics[i % 5], "collector": "TEST"} for i in range(60)]
    insert_ignore(conn, "news", news)
    news_ids = [r[0] for r in conn.execute("select id from news where collector = 'TEST' order by id").fetchall()]

    # 事件
    from tracker.config import EVENT_TYPES as types
    paths = [["事件", "美國10年期公債殖利率", "金融保險", "台股加權指數"],
             ["事件", "費城半導體指數", "半導體", "台股加權指數"],
             ["事件", "國際油價", "航運", "台股加權指數"]]
    ev_rows, links = [], []
    for i in range(18):
        d = days[-1 - (i // 2)]
        eid = f"EV-{d:%Y%m%d}-{i % 2 + 1:02d}"
        nid = news_ids[i % len(news_ids)]
        ev_rows.append({
            "id": eid, "analysis_date": d, "name": f"測試事件 {i + 1}", "event_type": types[i % len(types)],
            "occurred_date": d, "first_published_at": datetime.combine(d, datetime.min.time(), TZ),
            "countries": ["美國", "台灣"][: 1 + i % 2], "actors": ["測試機構"], "importance": 1 + i % 5,
            "importance_reason": "測試資料", "summary": "這是畫面測試用的事件，不是真實事件。",
            "direction": ["正面", "負面", "中性", "不確定"][i % 4], "status": "new",
            "facts": Jsonb([{"text": "測試事實", "news_ids": [nid]}]), "inferences": Jsonb(["測試推論：可能影響殖利率"]),
            "unconfirmed": Jsonb([]), "data_gaps": Jsonb(["測試：缺少官方數據"]),
            "affected_variables": [["US10Y", "SOX", "WTI"][i % 3]], "affected_industries": [["金融保險", "半導體", "航運"][i % 3]],
            "affected_stocks": [], "pathway": Jsonb(paths[i % 3]), "model": "test", "prompt_version": "test"})
        links.append({"event_id": eid, "news_id": nid})
    insert_ignore(conn, "events", ev_rows)
    insert_ignore(conn, "event_news", links)

    # 事前判斷與評估
    pr_rows, ev_rows2 = [], []
    tx = {r["trade_date"]: r for r in rows if r["index_code"] == "TAIEX"}
    for d in days[-25:]:
        for kind in ("ai", "baseline"):
            pid = f"PR-{d:%Y%m%d}-{'AI' if kind == 'ai' else 'BASE'}"
            direction = rnd.choice(["上漲", "下跌"])
            pr_rows.append({"id": pid, "kind": kind, "target_trading_day": d, "direction": direction,
                            "confidence": "中" if kind == "ai" else None, "rationale": "測試理由",
                            "drivers": Jsonb([{"source": "SOX", "effect": "正面", "reason": "測試"}]),
                            "pathways": Jsonb([["費半上漲", "半導體", "台股加權指數"]]), "counterpoints": Jsonb(["測試反向因素"]),
                            "event_ids": [], "inputs": Jsonb({}), "is_ex_ante": True,
                            "model": "test" if kind == "ai" else "rule", "prompt_version": "test",
                            "created_at": datetime.combine(d, datetime.min.time(), TZ) + timedelta(hours=7)})
            pct = tx[d]["change_pct"]
            actual = "上漲" if pct > 0 else "下跌"
            ev_rows2.append({"prediction_id": pid, "method_version": "v1", "actual_change_pct": pct, "actual_direction": actual,
                             "abs_grade": min(5, sum(abs(pct) >= t for t in [0.5, 1, 2, 3]) + 1), "abs_grade_label": "測試",
                             "z_score": pct / 1.2, "rel_grade_label": "正常", "result": "命中" if actual == direction else "未命中"})
    insert_ignore(conn, "predictions", pr_rows)
    insert_ignore(conn, "evaluations", ev_rows2)

    # 報告與執行紀錄
    insert_ignore(conn, "reports", [
        {"kind": "daily", "period_key": f"{d:%Y-%m-%d}", "version": 1, "title": f"{d:%Y-%m-%d} 測試日報",
         "summary": "測試", "content_md": f"# {d:%Y-%m-%d} 測試日報\n\n這是測試資料。", "sections": Jsonb({"data_gaps": ["測試"]}),
         "model": "test"} for d in days[-5:]] +
        [{"kind": "weekly", "period_key": "TEST-W", "version": 1, "title": "測試週報", "summary": "測試", "content_md": "# 測試週報",
          "sections": Jsonb({}), "model": "test"}])
    now = datetime.now(TZ)
    conn.execute("insert into pipeline_runs (job, started_at, finished_at, status, rows_written, errors, environment) values "
                 "('evening', %s, %s, 'success', %s, %s, 'test'), ('morning', %s, %s, 'partial', %s, %s, 'test')",
                 (now - timedelta(hours=2), now - timedelta(hours=2) + timedelta(seconds=40), Jsonb({"index_daily": 30}), Jsonb([]),
                  now - timedelta(hours=12), now - timedelta(hours=12) + timedelta(seconds=90), Jsonb({"news": 120}),
                  Jsonb([{"step": "gdelt", "message": "測試錯誤訊息"}])))
    conn.commit()
    return {"events": [e["id"] for e in ev_rows]}
