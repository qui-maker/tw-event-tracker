"""早班（台北時間約 07:15，美股收盤後、台股開盤前）

1. 蒐集國際新聞（媒體 RSS、Google News、GDELT、聯準會新聞稿）並去重
2. 更新國際經濟與市場變項（FRED、Yahoo）
3. AI 辨識重大事件與傳導路徑
4. 寫下今天（或下一個交易日）加權指數的事前判斷：AI 一筆、對照規則一筆
5. 補做之前還沒評估的判斷

執行：python -m jobs.morning
      python -m jobs.morning --if-missing   # 備援排程（台北 07:17）：主排程已完成就什麼都不做（決策紀錄 #53）
"""
import argparse
from datetime import timedelta

from dotenv import load_dotenv

from tracker.analysis import evaluate, events, predict
from tracker.calendar import prediction_target
from tracker.collectors import macro, news
from tracker.db import RunLog, connect, fetch_all, fetch_one, insert_ignore, step
from tracker.utils import now_taipei


def store_news(conn, rows: list[dict]) -> int:
    """以網址去重；不同網址但標題相同（轉載）的新聞也略過。"""
    known = {r["title_fingerprint"] for r in fetch_all(
        conn, "select title_fingerprint from news where fetched_at > now() - interval '4 days'")}
    fresh, seen = [], set()
    for r in rows:
        fp = r["title_fingerprint"]
        if fp in known or fp in seen:
            continue
        seen.add(fp)
        fresh.append(r)
    return insert_ignore(conn, "news", fresh, conflict="url")


def done_today(conn, today, target) -> tuple[bool, bool]:
    """（今天的事件已分析？, 今天該做的事前判斷都已寫入？）"""
    events_done = fetch_one(conn, "select 1 as x from events where analysis_date = %s", (today,)) is not None
    if target != today:
        return events_done, True
    n = fetch_one(conn, "select count(*) as n from predictions where target_trading_day = %s", (today,))["n"]
    return events_done, n >= 2


def main(argv=None):
    load_dotenv()
    parser = argparse.ArgumentParser(description="早班")
    parser.add_argument("--if-missing", action="store_true",
                        help="備援排程用：今天的事件與事前判斷都已完成就直接結束；事件已完成就不重做事件分析")
    args = parser.parse_args(argv)
    now = now_taipei()
    today = now.date()
    conn = connect()
    skip_events = False
    if args.if_missing:
        events_done, preds_done = done_today(conn, today, prediction_target(conn, now))
        if events_done and preds_done:
            print(f"  {today} 的早班已經完成（事件與事前判斷都有），備援排程不重複執行")
            return
        skip_events = events_done
        print(f"  備援排程：主排程沒有完成（事件{'已' if events_done else '未'}完成、事前判斷"
              f"{'已' if preds_done else '未'}完成），補做缺少的部分")
    with RunLog(conn, "morning") as log:
        with step(log, conn, "RSS 新聞"):
            log.add("news(RSS)", store_news(conn, news.rss_feeds(log)))
        with step(log, conn, "GDELT 新聞"):
            log.add("news(GDELT)", store_news(conn, news.gdelt("1d", log)))
        with step(log, conn, "聯準會新聞稿"):
            log.add("news(Fed)", store_news(conn, news.fed_press()))
        with step(log, conn, "經濟變項"):
            rows = macro.collect_all(today - timedelta(days=21), log)
            log.add("variable_values", insert_ignore(conn, "variable_values", rows, conflict="variable_code, obs_date"))

        event_ids = []
        if skip_events:
            print("  今天的事件已經分析過，不重做（避免重複事件）")
        else:
            with step(log, conn, "AI 事件分析"):
                event_ids = events.analyze(conn, log, today)

        target = prediction_target(conn, now)
        if target == today:
            print(f"  事前判斷目標交易日：{target}")
            with step(log, conn, "對照規則預測"):
                predict.baseline(conn, log, target, now)
            with step(log, conn, "AI 事前預測"):
                predict.ai_prediction(conn, log, target, now, event_ids)
        else:
            # 只在目標交易日當天開盤前做判斷，才能納入週末與前一晚的最新資訊（決策紀錄 #23）
            print(f"  今天不是交易日或已過 09:00 開盤，事前判斷留到 {target} 當天早上再做")
        with step(log, conn, "補做評估"):
            evaluate.run(conn, log, today - timedelta(days=1))


if __name__ == "__main__":
    main()
