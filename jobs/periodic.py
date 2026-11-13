"""週報（每週日）、月報（每月 1 日）與每週資料備份。

執行：python -m jobs.periodic --kind weekly
      python -m jobs.periodic --kind monthly
      python -m jobs.periodic --kind backup
"""
import argparse
import csv
from datetime import date, timedelta
import os
from pathlib import Path

from dotenv import load_dotenv

from tracker import reports
from tracker.db import RunLog, connect, fetch_all, step
from tracker.utils import today_taipei

BACKUP_TABLES = ["events", "event_news", "predictions", "evaluations", "reports", "index_daily", "market_breadth",
                 "institutional_flows", "variables", "variable_values", "trading_calendar", "news", "pipeline_runs"]


def backup(conn, log):
    """把研究資料匯出成 CSV，存在 repo 的 backups/ 資料夾（Supabase 免費方案沒有自動備份）。"""
    out = Path(os.getenv("BACKUP_DIR") or Path(__file__).resolve().parent.parent / "backups")
    out.mkdir(parents=True, exist_ok=True)
    for t in BACKUP_TABLES:
        rows = fetch_all(conn, f"select * from {t}")
        with open(out / f"{t}.csv", "w", newline="", encoding="utf-8") as f:
            if rows:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
        log.add(f"backup({t})", len(rows))


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=["weekly", "monthly", "backup"], required=True)
    args = parser.parse_args()
    today = today_taipei()
    conn = connect()
    with RunLog(conn, args.kind) as log:
        if args.kind == "weekly":
            end = today
            start = end - timedelta(days=6)
            iso = end.isocalendar()
            with step(log, conn, "週報"):
                reports.build_period(conn, log, "weekly", start, end, f"{iso.year}-W{iso.week:02d}",
                                     f"《{iso.year} 年第 {iso.week} 週 台股與世界重大事件週報》")
            with step(log, conn, "備份"):
                backup(conn, log)
        elif args.kind == "monthly":
            end = today.replace(day=1) - timedelta(days=1)  # 上個月最後一天
            start = end.replace(day=1)
            with step(log, conn, "月報"):
                reports.build_period(conn, log, "monthly", start, end, f"{end:%Y-%m}",
                                     f"《{end.year} 年 {end.month} 月 國際經濟與台股關聯月報》")
        else:
            with step(log, conn, "備份"):
                backup(conn, log)


if __name__ == "__main__":
    main()
