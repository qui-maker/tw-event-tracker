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
from tracker.db import RunLog, connect, insert_ignore, step, upsert
from tracker.utils import today_taipei


def save_stocks(conn, log, rows: list[dict], market: str):
    if not rows:
        return
    upsert(conn, "stocks", [{"code": r["code"], "name": r["name"], "market": market} for r in rows],
           key="code", update_cols=["name", "market"])
    daily = [{k: v for k, v in r.items() if k != "name"} for r in rows]
    log.add(f"stock_daily({market})", insert_ignore(conn, "stock_daily", daily, conflict="code, trade_date"))


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    args = parser.parse_args()
    d = args.date or today_taipei()
    conn = connect()
    with RunLog(conn, "evening") as log:
        with step(log, conn, "加權指數 FMTQIK"):
            rows = twse.fmtqik_month(d) if args.date else twse.fmtqik_latest()
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
            reports.build_daily(conn, log, d)


if __name__ == "__main__":
    main()
