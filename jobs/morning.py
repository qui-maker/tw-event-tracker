"""早班（台北時間約 07:15，美股收盤後、台股開盤前）

1. 蒐集國際新聞（GDELT、聯準會新聞稿）並去重
2. 更新國際經濟與市場變項（FRED、Yahoo）
3. AI 辨識重大事件與傳導路徑
4. 寫下今天（或下一個交易日）加權指數的事前判斷：AI 一筆、對照規則一筆
5. 補做之前還沒評估的判斷

執行：python -m jobs.morning
"""
from datetime import timedelta

from dotenv import load_dotenv

from tracker.analysis import evaluate, events, predict
from tracker.calendar import prediction_target
from tracker.collectors import macro, news
from tracker.db import RunLog, connect, fetch_all, insert_ignore, step
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


def main():
    load_dotenv()
    now = now_taipei()
    today = now.date()
    conn = connect()
    with RunLog(conn, "morning") as log:
        with step(log, conn, "GDELT 新聞"):
            log.add("news(GDELT)", store_news(conn, news.gdelt("1d", log)))
        with step(log, conn, "聯準會新聞稿"):
            log.add("news(Fed)", store_news(conn, news.fed_press()))
        with step(log, conn, "經濟變項"):
            rows = macro.collect_all(today - timedelta(days=21), log)
            log.add("variable_values", insert_ignore(conn, "variable_values", rows, conflict="variable_code, obs_date"))

        event_ids = []
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
