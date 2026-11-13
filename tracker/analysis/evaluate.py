"""事後評估：用固定規則比對事前判斷與實際收盤（不經過 AI）。"""
from __future__ import annotations

from datetime import date, timedelta

from tracker.analysis.grading import abs_grade, direction, rel_label, z_score
from tracker.config import EVAL_METHOD_VERSION, REL_WINDOW
from tracker.db import fetch_all, insert_ignore


def run(conn, log, today: date) -> int:
    pending = fetch_all(conn, """
        select p.id, p.direction, p.target_trading_day, p.is_ex_ante
        from predictions p
        where p.target_trading_day <= %s
          and not exists (select 1 from evaluations e where e.prediction_id = p.id and e.method_version = %s)
        order by p.target_trading_day""", (today, EVAL_METHOD_VERSION))
    rows = []
    for p in pending:
        target = p["target_trading_day"]
        actual = fetch_all(conn, "select change_pct from index_daily where index_code = 'TAIEX' and trade_date = %s", (target,))
        if not actual or actual[0]["change_pct"] is None:
            if target < today - timedelta(days=5):
                rows.append(_row(p["id"], None, None, None, None, "資料不足", "無法判定",
                                 "目標交易日沒有加權指數收盤資料（可能是休市或資料缺漏）"))
            continue  # 資料可能還沒公布，下次再評
        pct = float(actual[0]["change_pct"])
        prev = fetch_all(conn, "select change_pct from index_daily where index_code = 'TAIEX' and trade_date < %s "
                               "and change_pct is not null order by trade_date desc limit %s", (target, REL_WINDOW))
        z = z_score(pct, [float(r["change_pct"]) for r in reversed(prev)])
        grade, label = abs_grade(pct)
        act = direction(pct)
        if act == "平盤":
            result, note = "無法判定", "收盤平盤"
        else:
            result, note = ("命中" if act == p["direction"] else "未命中"), None
        if not p["is_ex_ante"]:
            note = ((note + "；") if note else "") + "此判斷在開盤後才寫入，不列入事前判斷統計"
        rows.append(_row(p["id"], pct, act, grade, label, rel_label(z), result, note, z))
    n = insert_ignore(conn, "evaluations", rows, conflict="prediction_id, method_version")
    conn.commit()
    log.add("evaluations", n)
    return n


def _row(pid, pct, act, grade, label, rel, result, note, z=None) -> dict:
    return {"prediction_id": pid, "method_version": EVAL_METHOD_VERSION, "actual_change_pct": pct,
            "actual_direction": act, "abs_grade": grade, "abs_grade_label": label, "z_score": z,
            "rel_grade_label": rel, "result": result, "note": note}
