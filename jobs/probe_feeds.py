"""新聞來源實測（只讀取，不寫入資料庫）：確認候選的公開 RSS 能不能從 GitHub Actions 連上、有幾則、最新一則是什麼時間。

執行：python -m jobs.probe_feeds
"""
import time
from datetime import datetime, timezone

import feedparser
import requests

FEEDS = {
    "CNBC 頭條": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "CNBC 國際": "https://www.cnbc.com/id/100727362/device/rss/rss.html",
    "CNBC 經濟": "https://www.cnbc.com/id/20910258/device/rss/rss.html",
    "CNBC 科技": "https://www.cnbc.com/id/19854910/device/rss/rss.html",
    "BBC 商業": "https://feeds.bbci.co.uk/news/business/rss.xml",
    "BBC 亞洲": "https://feeds.bbci.co.uk/news/world/asia/rss.xml",
    "MarketWatch 頭條": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "Nikkei Asia": "https://asia.nikkei.com/rss/feed/nar",
    "Taipei Times 商業": "https://www.taipeitimes.com/xml/biz.rss",
    "Focus Taiwan 商業": "https://focustaiwan.tw/rss/business",
    "Yahoo Finance": "https://finance.yahoo.com/news/rssindex",
    "Google News 搜尋": "https://news.google.com/rss/search?q=Taiwan%20stocks%20when%3A1d&hl=en-US&gl=US&ceid=US%3Aen",
}

session = requests.Session()
session.headers.update({"User-Agent": "tw-event-tracker/0.1 (personal research project; https://github.com/qui-maker/tw-event-tracker)"})


def main():
    now = datetime.now(timezone.utc)
    for name, url in FEEDS.items():
        try:
            r = session.get(url, timeout=25)
            feed = feedparser.parse(r.content)
            dates = [datetime(*e.published_parsed[:6], tzinfo=timezone.utc) for e in feed.entries if e.get("published_parsed")]
            fresh = sum(1 for d in dates if (now - d).total_seconds() < 86400)
            newest = max(dates).isoformat() if dates else "無日期"
            first = feed.entries[0].get("title", "")[:70] if feed.entries else ""
            link = feed.entries[0].get("link", "")[:90] if feed.entries else ""
            print(f"{'OK ' if feed.entries else 'NG '} {name}｜HTTP {r.status_code}｜{len(feed.entries)} 則｜24 小時內 {fresh} 則｜最新 {newest}｜{first}｜{link}")
        except Exception as e:  # noqa: BLE001
            print(f"ERR {name}｜{type(e).__name__}: {str(e)[:150]}")
        time.sleep(1)

    # GDELT：單一合併查詢，間隔 60 秒試兩次
    q = '("Federal Reserve" OR tariff OR semiconductor OR Taiwan OR "oil prices") sourcelang:english'
    for i in range(2):
        try:
            r = session.get("https://api.gdeltproject.org/api/v2/doc/doc", timeout=30,
                            params={"query": q, "mode": "artlist", "format": "json", "maxrecords": 250, "timespan": "1d"})
            try:
                n = len(r.json().get("articles", []))
                print(f"GDELT 合併查詢 第 {i + 1} 次｜HTTP {r.status_code}｜{n} 則")
            except ValueError:
                print(f"GDELT 合併查詢 第 {i + 1} 次｜HTTP {r.status_code}｜不是 JSON：{r.text[:120]}")
        except Exception as e:  # noqa: BLE001
            print(f"GDELT 合併查詢 第 {i + 1} 次｜{type(e).__name__}: {str(e)[:120]}")
        time.sleep(60)


if __name__ == "__main__":
    main()
