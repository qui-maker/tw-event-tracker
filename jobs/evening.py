"""晚班（台北時間約 18:15，台股收盤、證交所盤後資料公布後）

1. 抓今天的台股收盤：加權指數與成交金額、類股指數、漲跌家數、三大法人、上市櫃個股、重大訊息
2. 更新國際變項
3. 用固定規則評估目標日是今天的事前判斷
4. 產生《YYYY/MM/DD 台股與世界重大事件日報》

執行：python -m jobs.evening            （今天）
      python -m jobs.evening --date 2026-11-12   （補跑指定日期）
"""
import argparse
from datetime import date, timedelta

from dotenv import load_dotenv

from tracker import reports
from tracker.analysis import evaluate
from tracker.calendar import mark_trading_days
from tracker.collectors import macro, tpex, twse
from tracker.db import fetch_one, RunLog, connect, insert_ignore, step, upsert
from tracker.utils import now_taipei, today_taipei


def save_stocks(conn, log, rows: list[dict], market: str):
    if not rows:
        return
    upsert(conn, "stocks", [{"code": r["code"], "name": r["name"], "market": market} for r in rows],
           key="code", update_cols=["name", "market"])
    daily = [{k: v for k, v in r.items() if k != "name"} for r in rows]
    log.add(f"stock_daily({market})", insert_ignore(conn, "stock_daily", daily, conflict="code, trade_date"))


LAST_RUN_HOUR = 18  # 最後一次晚班排程（台北 18:17）之後，資料未齊也照樣產生日報


def missing_inputs(conn, d: date) -> list[str]:
    """日報需要的當天資料還缺哪些。休市日三項都會缺，此時由 18:17 那次排程照常產生（內容會標示休市）。"""
    checks = {
        "加權指數": "select 1 as x from index_daily where index_code = 'TAIEX' and trade_date = %s",
        "類股指數": "select 1 as x from index_daily where index_code like 'IDX_%%' and trade_date = %s",
        "三大法人": "select 1 as x from institutional_flows where trade_date = %s",
    }
    return [name for name, sql in checks.items() if not fetch_one(conn, sql, (d,))]


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    args = parser.parse_args()
    d = args.date or today_taipei()
    conn = connect()
    with RunLog(conn, "evening") as log:
        with step(log, conn, "加權指數 FMTQIK"):
            # 網站版（rwd）當天收盤後就更新；OpenAPI 版會晚一天（11/13 實測：晚上 7 點仍沒有當天資料）
            try:
                rows = twse.fmtqik_month(d, exact_day=True)
            except Exception as e:  # noqa: BLE001
                print(f"  網站版 FMTQIK 失敗，改用 OpenAPI：{e}")
                rows = twse.fmtqik_latest()
            if not any(r["trade_date"] == d for r in rows):
                print(f"  FMTQIK 還沒有 {d} 的資料（休市或尚未公布）")
            log.add("index_daily(TAIEX)", insert_ignore(conn, "index_daily", rows, conflict="index_code, trade_date"))
            mark_trading_days(conn, [r["trade_date"] for r in rows], "證交所 FMTQIK 成交資料")

        traded = False
        with step(log, conn, "類股指數、漲跌家數、上市個股"):
            res = twse.daily_close(d)
            if res["stat"] != "OK":
                print(f"  證交所回應：{res['stat']}（今天可能休市或資料尚未公布）")
            else:
                traded = True
                # 加權指數一律以 FMTQIK 為準（決策紀錄），這裡只寫入類股與其他指數
                sectors = [r for r in res["indices"] if r["index_code"] != "TAIEX"]
                log.add("index_daily(類股)", insert_ignore(conn, "index_daily", sectors, conflict="index_code, trade_date"))
                if res["breadth"]:
                    log.add("market_breadth", insert_ignore(conn, "market_breadth", [res["breadth"]], conflict="trade_date, market"))
                save_stocks(conn, log, res["stocks"], "TWSE")
        if not traded:
            with step(log, conn, "類股指數（OpenAPI 備援）"):
                rows = [r for r in twse.indices_openapi_latest() if r["trade_date"] == d and r["index_code"] != "TAIEX"]
                log.add("index_daily(類股備援)", insert_ignore(conn, "index_daily", rows, conflict="index_code, trade_date"))
        with step(log, conn, "三大法人"):
            log.add("institutional_flows", insert_ignore(conn, "institutional_flows", twse.institutional(d),
                                                         conflict="trade_date, investor"))
        if not args.date:  # 下面這些 API 只有最新一天的資料
            with step(log, conn, "櫃買指數"):
                log.add("index_daily(TPEX)", insert_ignore(conn, "index_daily", tpex.index_latest(), conflict="index_code, trade_date"))
            with step(log, conn, "上櫃個股"):
                save_stocks(conn, log, tpex.stock_quotes(), "TPEX")
            with step(log, conn, "重大訊息"):
                log.add("announcements", insert_ignore(conn, "announcements", twse.announcements(),
                                                       conflict="code, announce_date, subject"))
            with step(log, conn, "經濟變項"):
                rows = macro.collect_all(d - timedelta(days=21), log)
                log.add("variable_values", insert_ignore(conn, "variable_values", rows, conflict="variable_code, obs_date"))

        with step(log, conn, "評估事前判斷"):
            evaluate.run(conn, log, d)
        with step(log, conn, "日報"):
            # 排程執行時，如果當天已經手動提早跑過、日報已存在，就不重複產生新版本（手動指定 --date 時仍會產生新版本）
            exists = fetch_one(conn, "select 1 as x from reports where kind = 'daily' and period_key = %s", (d.isoformat(),))
            missing = missing_inputs(conn, d)
            if exists and not args.date:
                print(f"  {d} 的日報已經存在，排程不重複產生")
            elif missing and not args.date and now_taipei().hour < LAST_RUN_HOUR:
                # 證交所類股指數與三大法人約 14:30～15:30 才公布；太早產生的日報會缺資料，且之後的排程不會再重做
                # 所以資料未齊時先不產生，留給下一次排程（18:17 那次無論如何都會產生，缺的部分在日報中標示）
                print(f"  {d} 尚缺：{'、'.join(missing)}，日報留給下一次排程產生")
            else:
                reports.build_daily(conn, log, d)


if __name__ == "__main__":
    main()
