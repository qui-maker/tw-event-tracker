"""日報、週報、月報：表格由資料庫數據組成，文字段落由 AI 根據同一批數據撰寫。"""
from __future__ import annotations

import json
from collections import Counter
from datetime import date, timedelta

from psycopg.types.json import Jsonb

from tracker.analysis.grading import abs_grade, rel_label, z_score
from tracker.analysis.llm import generate_json
from tracker.calendar import is_trading_day
from tracker.analysis.predict import latest_variables
from tracker.analysis.prompts import COMMON_RULES, REPORT_TASK, ReportOut
from tracker.config import OVERNIGHT_VARIABLES, REL_WINDOW
from tracker.db import fetch_all, fetch_one, insert_ignore

DISCLAIMER = "> 本報告為研究紀錄，非投資建議。AI 判斷為事前推論，不代表事件與市場反應之間有因果關係。"


def _fmt(v, digits=2, signed=False):
    if v is None:
        return "—"
    v = float(v)
    return f"{v:+,.{digits}f}" if signed else f"{v:,.{digits}f}"


def _taiex_with_grades(conn, d: date) -> dict | None:
    row = fetch_one(conn, "select * from index_daily where index_code = 'TAIEX' and trade_date = %s", (d,))
    if not row:
        return None
    prev = fetch_all(conn, "select change_pct from index_daily where index_code='TAIEX' and trade_date < %s "
                           "and change_pct is not null order by trade_date desc limit %s", (d, REL_WINDOW))
    pct = float(row["change_pct"]) if row["change_pct"] is not None else None
    z = z_score(pct, [float(r["change_pct"]) for r in reversed(prev)])
    row["grade_label"] = abs_grade(pct)[1]
    row["z"] = z
    row["rel_label"] = rel_label(z)
    return row


def _hit_rates(conn, since: date | None = None) -> dict:
    sql = """select p.kind, e.result, e.abs_grade from evaluations e join predictions p on p.id = e.prediction_id
             where p.is_ex_ante and e.result in ('命中','未命中')"""
    params = ()
    if since:
        sql += " and p.target_trading_day >= %s"
        params = (since,)
    out = {}
    for kind in ("ai", "baseline"):
        rows = [r for r in fetch_all(conn, sql, params) if r["kind"] == kind]
        big = [r for r in rows if (r["abs_grade"] or 0) >= 3]
        hit = lambda rs: sum(r["result"] == "命中" for r in rs)  # noqa: E731
        out[kind] = {"n": len(rows), "hits": hit(rows), "n_big": len(big), "hits_big": hit(big)}
    return out


def _rate(h, n):
    return "—（尚無樣本）" if not n else f"{h}/{n}（{h / n:.0%}）"


def _next_version(conn, kind, key) -> int:
    row = fetch_one(conn, "select max(version) as v from reports where kind = %s and period_key = %s", (kind, key))
    return (row["v"] or 0) + 1 if row else 1


def build_daily(conn, log, d: date) -> int | None:
    title = f"《{d:%Y/%m/%d} 台股與世界重大事件日報》"
    tx = _taiex_with_grades(conn, d)
    # 休市日（週末、國定假日）要明白寫「休市」，不是「缺資料」（11/22 週日日報寫成「缺乏台股數據」）
    closed = tx is None and not is_trading_day(conn, d)
    last_tx = None if not closed else fetch_one(
        conn, "select trade_date, close, change_pct from index_daily where index_code = 'TAIEX' and trade_date < %s "
              "order by trade_date desc limit 1", (d,))
    tpex = fetch_one(conn, "select * from index_daily where index_code='TPEX' and trade_date=%s", (d,))
    breadth = fetch_one(conn, "select * from market_breadth where trade_date=%s and market='TWSE'", (d,))
    flows = fetch_all(conn, "select investor, net from institutional_flows where trade_date=%s", (d,))
    sectors = fetch_all(conn, "select name, change_pct from index_daily where trade_date=%s and index_code like 'IDX_%%' "
                              "and change_pct is not null order by change_pct desc", (d,))
    events = fetch_all(conn, "select * from events where analysis_date=%s order by importance desc, id", (d,))
    variables = latest_variables(conn, OVERNIGHT_VARIABLES)
    preds = fetch_all(conn, """select p.*, e.result, e.actual_change_pct, e.abs_grade_label, e.rel_grade_label
                               from predictions p left join evaluations e on e.prediction_id = p.id
                               where p.target_trading_day = %s order by p.kind""", (d,))
    next_preds = fetch_all(conn, "select * from predictions where target_trading_day > %s order by target_trading_day, kind limit 2", (d,))
    rates = _hit_rates(conn)

    md = [title, "", f"報告日期：{d.isoformat()}（台北時間）", ""]

    # 1. 台股市場概況
    md += ["## 1. 今日台股市場概況", ""]
    if tx:
        md += ["| 項目 | 數值 | 來源 |", "|---|---|---|",
               f"| 加權指數收盤 | {_fmt(tx['close'])} 點 | {tx['source']} |",
               f"| 漲跌 | {_fmt(tx['change'], signed=True)} 點（{_fmt(tx['change_pct'], signed=True)}%） | 同上 |",
               f"| 幅度等級 | {tx['grade_label']}；相對近 20 日波動：{tx['rel_label']}"
               f"{'' if tx['z'] is None else f'（{tx['z']:+.2f} 個標準差）'} | 本系統依決策紀錄 v1 計算 |",
               f"| 成交金額 | {_fmt((tx['trade_value'] or 0) / 1e8)} 億元 | {tx['source']} |"]
        if tpex:
            md.append(f"| 櫃買指數 | {_fmt(tpex['close'])} 點（{_fmt(tpex['change_pct'], signed=True)}%） | {tpex['source']} |")
        if breadth:
            md.append(f"| 上市上漲／下跌／持平家數 | {breadth['advances']}／{breadth['declines']}／{breadth['unchanged']} | {breadth['source']} |")
        for f in flows:
            if f["net"] is not None and any(k in f["investor"] for k in ("外資及陸資", "投信", "合計")):
                md.append(f"| 三大法人：{f['investor']} | {_fmt(float(f['net']) / 1e8, signed=True)} 億元 | 證交所 BFI82U |")
        if sectors:
            top = "、".join(f"{s['name']} {_fmt(s['change_pct'], signed=True)}%" for s in sectors[:3])
            bottom = "、".join(f"{s['name']} {_fmt(s['change_pct'], signed=True)}%" for s in sectors[-3:])
            md += ["", f"- 類股表現最強：{top}", f"- 類股表現最弱：{bottom}"]
    else:
        if closed:
            md.append(f"今天休市（非交易日），沒有台股交易。"
                      + ("" if not last_tx else f"最近一個交易日 {last_tx['trade_date']} 加權指數收盤 {_fmt(last_tx['close'])} 點"
                                                f"（{_fmt(last_tx['change_pct'], signed=True)}%）。"))
        else:
            md.append("今天沒有加權指數收盤資料（證交所資料尚未公布或無法取得）。")
    md.append("")

    # 2. 國際重大事件 TOP 5
    md += ["## 2. 今日國際重大事件 TOP 5", ""]
    if events:
        md += ["| 編號 | 事件 | 類型 | 重要程度 | 對大盤可能方向 |", "|---|---|---|---|---|"]
        md += [f"| {e['id']} | {e['name']} | {e['event_type']} | {e['importance']} | {e['direction']} |" for e in events[:5]]
    else:
        md.append("今天沒有辨識出的重大事件（可能是新聞蒐集或 AI 分析失敗，見執行紀錄）。")
    md.append("")

    # 3. 經濟變項
    md += ["## 3. 今日重要經濟變項變化", "", "| 變項 | 最新值 | 日期 | 較前一筆 | 來源 |", "|---|---|---|---|---|"]
    for v in variables:
        md.append(f"| {v['name']} | {_fmt(v['value'])} {v['unit']} | {v['date']} | "
                  f"{v['change_text']} | {v['source']} |")
    md.append("")

    # 4、5. 產業與公司
    industries = Counter(i for e in events for i in (e["affected_industries"] or []))
    md += ["## 4. 可能受到影響的台灣產業", ""]
    md += [f"- {name}（相關事件 {n} 則）【推論】" for name, n in industries.most_common(10)] or ["- 無"]
    md += ["", "## 5. 可能受到影響的台股公司", "", "第一版研究範圍是大盤，暫不分析個股。", ""]

    # 6. AI 事件影響分析
    md += ["## 6. AI 事件影響分析", ""]
    for e in events[:5]:
        md += [f"### {e['id']} {e['name']}", "", f"- 傳導路徑：{' → '.join(e['pathway'] or [])}"]
        md += [f"- 【事實】{f['text']}（新聞 {', '.join(str(i) for i in f['news_ids'])}）" for f in e["facts"]]
        md += [f"- 【推論】{x}" for x in e["inferences"]]
        md += [f"- 【未確認】{x}" for x in e["unconfirmed"]]
        md += [f"- 資料不足：{x}" for x in e["data_gaps"]]
        md.append("")

    # 7. 預期與實際
    md += ["## 7. 預期影響與實際市場反應", "", "| 判斷 | 目標交易日 | 預測方向 | 信心 | 實際 | 結果 |", "|---|---|---|---|---|---|"]
    for p in preds + next_preds:
        who = "AI" if p["kind"] == "ai" else "對照規則（費半方向）"
        actual = "尚未收盤" if p.get("result") is None else f"{_fmt(p['actual_change_pct'], signed=True)}%（{p['abs_grade_label']}）"
        md.append(f"| {who} | {p['target_trading_day']} | {p['direction']} | {p['confidence'] or '—'} | {actual} | {p.get('result') or '待評估'} |")
    md += ["", f"- 累計方向命中率（只計事前判斷）：AI {_rate(rates['ai']['hits'], rates['ai']['n'])}；"
               f"對照規則 {_rate(rates['baseline']['hits'], rates['baseline']['n'])}",
           f"- 只看「明顯」以上波動的日子：AI {_rate(rates['ai']['hits_big'], rates['ai']['n_big'])}；"
           f"對照規則 {_rate(rates['baseline']['hits_big'], rates['baseline']['n_big'])}",
           "- 單日漲跌同時受多個事件影響，命中不代表因果成立；樣本累積數個月後才有參考價值。", ""]

    # AI 文字段落
    context = json.dumps({
        "台股": ("今天休市（非交易日），沒有台股交易；不要寫成缺少資料"
                 + ("" if not last_tx else f"。最近一個交易日 {last_tx['trade_date']} 收盤 {float(last_tx['close'])}"
                                           f"（{float(last_tx['change_pct']):+.2f}%）")) if closed else
                None if not tx else {"收盤": float(tx["close"]), "漲跌幅%": round(float(tx["change_pct"]), 2), "等級": tx["grade_label"],
                                     "成交金額(億元)": None if tx.get("trade_value") is None else round(float(tx["trade_value"]) / 1e8, 2),
                                     "相對波動": tx["rel_label"]},
        "上漲下跌家數": None if not breadth else {"上漲": breadth["advances"], "下跌": breadth["declines"]},
        "三大法人淨額(億元)": {f["investor"]: round(float(f["net"]) / 1e8, 2) for f in flows if f["net"] is not None},
        "類股": [{s["name"]: float(s["change_pct"])} for s in sectors[:5] + sectors[-5:]],
        "事件": [{"編號": e["id"], "名稱": e["name"], "類型": e["event_type"], "重要程度": e["importance"],
                  "摘要": e["summary"], "方向": e["direction"]} for e in events],
        "經濟變項": [{v["name"]: v["value"], "日期": v["date"], "較前一筆": v["change_text"]} for v in variables],
        "事前判斷": [{"判斷者": p["kind"], "目標日": str(p["target_trading_day"]), "方向": p["direction"],
                      "結果": p.get("result")} for p in preds + next_preds],
    }, ensure_ascii=False, default=str)
    sections, model = {}, None
    try:
        out, model = generate_json(REPORT_TASK.format(title=title, context=context), ReportOut, COMMON_RULES)
        sections = out.model_dump()
    except Exception as e:  # noqa: BLE001
        log.error("日報 AI 段落", str(e))
    md += ["## 8. 後續值得觀察的事件", ""]
    md += [f"- {x}" for x in sections.get("watch_items", [])] or ["- （AI 段落未產生）"]
    md += ["", "## AI 今日市場分析", "", sections.get("market_overview", "（未產生）"), "",
           sections.get("international", ""), "", "**可能影響台股的主要因素**", ""]
    md += [f"- {x}" for x in sections.get("key_factors", [])]
    md += ["", "**資料不足或仍不確定的部分**", ""] + [f"- {x}" for x in sections.get("data_gaps", [])]
    md += ["", DISCLAIMER]

    version = _next_version(conn, "daily", d.isoformat())
    insert_ignore(conn, "reports", [{"kind": "daily", "period_key": d.isoformat(), "version": version, "title": title,
                                     "summary": sections.get("summary"), "content_md": "\n".join(md),
                                     "sections": Jsonb(sections), "model": model}])
    conn.commit()
    log.add("reports(daily)", 1)
    return version


def build_period(conn, log, kind: str, start: date, end: date, key: str, title: str) -> None:
    """週報、月報：期間內的指數變化、事件統計、命中率與 AI 摘要。"""
    tx = fetch_all(conn, "select trade_date, close, change_pct from index_daily where index_code='TAIEX' "
                         "and trade_date between %s and %s order by trade_date", (start, end))
    prev = fetch_one(conn, "select close from index_daily where index_code='TAIEX' and trade_date < %s "
                           "order by trade_date desc limit 1", (start,))
    events = fetch_all(conn, "select id, name, event_type, importance, direction, analysis_date from events "
                             "where analysis_date between %s and %s order by importance desc, analysis_date", (start, end))
    rates = _hit_rates(conn, since=start)
    md = [title, "", f"期間：{start} ～ {end}（台北時間）", "", "## 加權指數", ""]
    if tx and prev:
        chg = (float(tx[-1]["close"]) / float(prev["close"]) - 1) * 100
        big = [t for t in tx if t["change_pct"] is not None and abs(float(t["change_pct"])) >= 2]
        md += [f"- 期間漲跌：{_fmt(chg, signed=True)}%（{prev['close']} → {tx[-1]['close']}）",
               f"- 交易日 {len(tx)} 天；單日漲跌 2% 以上 {len(big)} 天", ""]
    else:
        md += ["- 期間資料不足", ""]
    md += ["## 重大事件", "", "| 日期 | 事件 | 類型 | 重要程度 | 方向 |", "|---|---|---|---|---|"]
    md += [f"| {e['analysis_date']} | {e['name']} | {e['event_type']} | {e['importance']} | {e['direction']} |" for e in events[:15]]
    types = Counter(e["event_type"] for e in events)
    md += ["", "事件類型次數：" + ("、".join(f"{t} {n}" for t, n in types.most_common()) or "無"), "",
           "## 事前判斷命中率（本期）", "",
           f"- AI：{_rate(rates['ai']['hits'], rates['ai']['n'])}；對照規則：{_rate(rates['baseline']['hits'], rates['baseline']['n'])}", ""]
    context = json.dumps({"加權指數": [{str(t["trade_date"]): float(t["change_pct"] or 0)} for t in tx],
                          "事件": [{"名稱": e["name"], "類型": e["event_type"], "重要程度": e["importance"]} for e in events[:30]],
                          "命中率": rates}, ensure_ascii=False, default=str)
    sections, model = {}, None
    try:
        out, model = generate_json(REPORT_TASK.format(title=title, context=context), ReportOut, COMMON_RULES)
        sections = out.model_dump()
        md += ["## 本期摘要", "", sections["summary"], "", "**主要因素**", ""] + [f"- {x}" for x in sections["key_factors"]]
        md += ["", "**後續觀察**", ""] + [f"- {x}" for x in sections["watch_items"]]
    except Exception as e:  # noqa: BLE001
        log.error(f"{kind} AI 段落", str(e))
    md += ["", DISCLAIMER]
    version = _next_version(conn, kind, key)
    insert_ignore(conn, "reports", [{"kind": kind, "period_key": key, "version": version, "title": title,
                                     "summary": sections.get("summary"), "content_md": "\n".join(md),
                                     "sections": Jsonb(sections), "model": model}])
    conn.commit()
    log.add(f"reports({kind})", 1)
