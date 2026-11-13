"""回補歷史資料：加權指數（證交所月資料）與全部經濟變項。可重複執行，已存在的資料會跳過。

執行：python -m jobs.backfill --years 3
"""
import argparse
import time
from datetime import timedelta

from dotenv import load_dotenv

from tracker.calendar import mark_trading_days
from tracker.collectors import macro, twse
from tracker.db import RunLog, connect, insert_ignore, step
from tracker.utils import month_starts, today_taipei


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=float, default=3)
    args = parser.parse_args()
    today = today_taipei()
    start = today - timedelta(days=int(365 * args.years))
    conn = connect()
    with RunLog(conn, "backfill") as log:
        months = list(month_starts(start, today))
        for i, m in enumerate(months):
            with step(log, conn, f"加權指數 {m:%Y-%m}"):
                rows = twse.fmtqik_month(m)
                log.add("index_daily(TAIEX)", insert_ignore(conn, "index_daily", rows, conflict="index_code, trade_date"))
                mark_trading_days(conn, [r["trade_date"] for r in rows], "證交所 FMTQIK 成交資料")
            if i < len(months) - 1:
                time.sleep(3)  # 對證交所網站保持禮貌的間隔
        with step(log, conn, "經濟變項"):
            rows = macro.collect_all(start, log)
            log.add("variable_values", insert_ignore(conn, "variable_values", rows, conflict="variable_code, obs_date"))


if __name__ == "__main__":
    main()
