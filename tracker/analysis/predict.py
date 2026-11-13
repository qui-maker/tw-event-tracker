"""早班：在台股開盤前寫下對加權指數的事前判斷（AI 與對照規則各一筆，寫入後不可修改）。"""
from __future__ import annotations

from datetime import date, datetime

from psycopg.types.json import Jsonb

from tracker.analysis.grading import abs_grade
from tracker.analysis.llm import generate_json
from tracker.analysis.prompts import COMMON_RULES, PREDICTION_TASK, PredictionOut
from tracker.calendar import market_open
from tracker.config import OVERNIGHT_VARIABLES, PROMPT_VERSION
from tracker.db import fetch_all, fetch_one, insert_ignore


def latest_variables(conn, codes: list[str]) -> list[dict]:
    """每個變項最新兩筆觀測值與變化率。"""
    out = []
    for code in codes:
        rows = fetch_all(conn, """
            select v.obs_date, v.value, d.name, d.unit, d.is_official, v.source
            from variable_values v join variables d on d.code = v.variable_code
            where v.variable_code = %s order by v.obs_date desc limit 2""", (code,))
        if not rows:
            continue
        cur = rows[0]
        prev = rows[1] if len(rows) > 1 else None
        chg = (float(cur["value"]) / float(prev["value"]) - 1) * 100 if prev and float(prev["value"]) else None
        out.append({"code": code, "name": cur["name"], "date": cur["obs_date"].isoformat(), "value": float(cur["value"]),
                    "unit": cur["unit"], "prev_date": prev["obs_date"].isoformat() if prev else None,
                    "change_pct": round(chg, 3) if chg is not None else None,
                    "official": bool(cur["is_official"]), "source": cur["source"]})
    return out


def taiex_recent(conn, n: int = 5) -> list[dict]:
    rows = fetch_all(conn, "select trade_date, close, change_pct from index_daily where index_code = 'TAIEX' "
                           "order by trade_date desc limit %s", (n,))
    return [{"date": r["trade_date"].isoformat(), "close": float(r["close"]) if r["close"] is not None else None,
             "change_pct": float(r["change_pct"]) if r["change_pct"] is not None else None,
             "grade": abs_grade(float(r["change_pct"]))[1] if r["change_pct"] is not None else None}
            for r in reversed(rows)]


def _exists(conn, kind: str, target: date) -> bool:
    return fetch_one(conn, "select 1 from predictions where kind = %s and target_code = 'TAIEX' and target_trading_day = %s",
                     (kind, target)) is not None


def baseline(conn, log, target: date, now: datetime) -> bool:
    """對照規則：費城半導體指數（SOX）最近一次收盤上漲 → 預測加權指數上漲；下跌 → 預測下跌。"""
    if _exists(conn, "baseline", target):
        return False
    sox = latest_variables(conn, ["SOX"])
    if not sox or sox[0]["change_pct"] in (None, 0):
        log.error("對照規則", "沒有可用的費城半導體指數資料，無法產生對照預測")
        return False
    s = sox[0]
    row = {"id": f"PR-{target:%Y%m%d}-BASE", "kind": "baseline", "target_code": "TAIEX", "target_trading_day": target,
           "direction": "上漲" if s["change_pct"] > 0 else "下跌", "confidence": None,
           "rationale": f"費城半導體指數 {s['date']} 收盤變動 {s['change_pct']:+.2f}%（{s['source']}）",
           "drivers": Jsonb([]), "pathways": Jsonb([]), "counterpoints": Jsonb([]), "event_ids": [],
           "inputs": Jsonb({"SOX": s}), "is_ex_ante": now < market_open(target), "model": None,
           "prompt_version": "baseline-sox-v1"}
    insert_ignore(conn, "predictions", [row], conflict="id")
    conn.commit()
    log.add("predictions(baseline)", 1)
    return True


def ai_prediction(conn, log, target: date, now: datetime, event_ids: list[str]) -> bool:
    if _exists(conn, "ai", target):
        return False
    events = fetch_all(conn, "select id, name, event_type, importance, direction, summary, pathway from events "
                             "where analysis_date = %s order by importance desc", (now.date(),))
    variables = latest_variables(conn, OVERNIGHT_VARIABLES)
    taiex = taiex_recent(conn)
    ev_text = "\n".join(f"{e['id']}｜{e['event_type']}｜重要程度 {e['importance']}｜對大盤可能方向：{e['direction']}｜"
                        f"{e['name']}｜{e['summary']}｜路徑：{' → '.join(e['pathway'] or [])}" for e in events) or "（今天沒有辨識出重大事件）"
    var_text = "\n".join(f"{v['code']} {v['name']}：{v['value']} {v['unit']}（{v['date']}），較前一筆 "
                         f"{'—' if v['change_pct'] is None else f'{v['change_pct']:+.2f}%'}"
                         f"{'' if v['official'] else '（非官方）'}" for v in variables) or "（無資料）"
    tx_text = "\n".join(f"{t['date']}：{t['close']}（{'—' if t['change_pct'] is None else f'{t['change_pct']:+.2f}%'}，{t['grade'] or ''}）"
                        for t in taiex) or "（無資料）"
    prompt = PREDICTION_TASK.format(target=target.isoformat(), events=ev_text, variables=var_text, taiex=tx_text)
    out, model = generate_json(prompt, PredictionOut, COMMON_RULES)
    direction = out.direction if out.direction in ("上漲", "下跌") else None
    if not direction:
        log.error("AI 預測", f"AI 回傳的方向不合規則：{out.direction}")
        return False
    row = {"id": f"PR-{target:%Y%m%d}-AI", "kind": "ai", "target_code": "TAIEX", "target_trading_day": target,
           "direction": direction, "confidence": out.confidence if out.confidence in ("低", "中", "高") else "低",
           "rationale": out.rationale, "drivers": Jsonb([d.model_dump() for d in out.drivers]),
           "pathways": Jsonb([p[:6] for p in out.pathways][:5]),
           "counterpoints": Jsonb(out.counterpoints + [f"資料不足：{g}" for g in out.data_gaps]),
           "event_ids": [e["id"] for e in events],
           "inputs": Jsonb({"variables": variables, "taiex": taiex}),
           "is_ex_ante": now < market_open(target), "model": model, "prompt_version": PROMPT_VERSION}
    insert_ignore(conn, "predictions", [row], conflict="id")
    conn.commit()
    log.add("predictions(ai)", 1)
    return True
