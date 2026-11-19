"""新聞蒐集：媒體官方 RSS、Google News 搜尋 RSS、GDELT（全球新聞，免金鑰）與聯準會新聞稿 RSS（官方）。

只保存標題、網址、媒體、發布時間等資訊，不轉存新聞全文。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import feedparser

from urllib.parse import quote_plus

from tracker.config import (GDELT_MAX_RECORDS, GDELT_QUERIES, GOOGLE_NEWS_QUERIES, RSS_FEEDS, RSS_MAX_AGE_HOURS,
                            RSS_MAX_PER_FEED)
from tracker.utils import http_get, title_fingerprint

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
FED_RSS = "https://www.federalreserve.gov/feeds/press_all.xml"


def _gdelt_time(s: str):
    try:
        return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


GDELT_BUDGET_S = 240  # 全部主題合計最多花 4 分鐘；GDELT 限流或沒回應時不能拖垮整個早班（決策紀錄 #46）


def gdelt(timespan: str = "1d", log=None, budget_s: float = GDELT_BUDGET_S) -> list[dict]:
    rows, seen = [], set()
    deadline = time.monotonic() + budget_s
    for i, (topic, query) in enumerate(GDELT_QUERIES.items()):
        def time_left() -> float:
            return deadline - time.monotonic()

        if i and time_left() > 15 + 30:
            time.sleep(15)  # GDELT 規定每 5 秒最多 1 次；GitHub 主機的 IP 與他人共用，實測 8 秒仍常被擋
        articles, last_msg = None, ""
        for attempt in range(3):
            if time_left() < 30:
                last_msg = last_msg or f"超過 GDELT 時間上限 {budget_s:.0f} 秒，略過"
                break
            try:
                resp = http_get(GDELT_URL, params={"query": query, "mode": "artlist", "format": "json",
                                                   "maxrecords": GDELT_MAX_RECORDS, "timespan": timespan,
                                                   "sort": "hybridrel"}, timeout=30, retries=0)
                articles = resp.json().get("articles", [])
                break
            except ValueError:  # 被限流時 GDELT 回傳純文字說明，不是 JSON
                last_msg = f"回應不是 JSON：{resp.text[:150]}"
            except Exception as e:  # noqa: BLE001
                last_msg = f"{type(e).__name__}: {e}"
            if attempt < 2 and time_left() > 25 + 30:
                time.sleep(25)
        if articles is None:
            if log:
                log.error(f"GDELT {topic}", last_msg)
            continue
        for a in articles:
            url, title = a.get("url"), (a.get("title") or "").strip()
            if not url or not title or url in seen:
                continue
            seen.add(url)
            rows.append({"url": url, "title": title[:500], "source_name": a.get("domain"),
                         "language": a.get("language"), "country": a.get("sourcecountry"),
                         "published_at": _gdelt_time(a.get("seendate")), "topic": topic,
                         "collector": "GDELT", "title_fingerprint": title_fingerprint(title)})
    return rows


def fed_press(days: int = 3) -> list[dict]:
    resp = http_get(FED_RSS)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = []
    for e in feed.entries:
        p = e.get("published_parsed")
        published = datetime(*p[:6], tzinfo=timezone.utc) if p else None
        if published and published < cutoff:
            continue
        title = (e.get("title") or "").strip()
        rows.append({"url": e.get("link"), "title": title[:500], "source_name": "federalreserve.gov",
                     "language": "English", "country": "United States", "published_at": published,
                     "topic": "貨幣政策", "collector": "Fed RSS", "title_fingerprint": title_fingerprint(title)})
    return [r for r in rows if r["url"]]


GOOGLE_NEWS_URL = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def _rss_rows(content: bytes, topic: str, collector: str, source_name: str | None, country: str | None) -> list[dict]:
    """解析 RSS；沒有發布時間或超過 RSS_MAX_AGE_HOURS 的新聞不收（所有資料都要有日期時間）。"""
    feed = feedparser.parse(content)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RSS_MAX_AGE_HOURS)
    rows = []
    for e in feed.entries:
        p = e.get("published_parsed") or e.get("updated_parsed")
        if not p:
            continue
        published = datetime(*p[:6], tzinfo=timezone.utc)
        title, url = (e.get("title") or "").strip(), e.get("link")
        if published < cutoff or not title or not url:
            continue
        src = source_name
        if collector == "Google News RSS":
            src = (e.get("source") or {}).get("title") or "Google News"
            suffix = f" - {src}"
            if title.endswith(suffix):  # Google News 會在標題後面加「 - 媒體名稱」
                title = title[: -len(suffix)].strip()
        rows.append({"url": url, "title": title[:500], "source_name": src, "language": "English", "country": country,
                     "published_at": published, "topic": topic, "collector": collector,
                     "title_fingerprint": title_fingerprint(title)})
        if len(rows) >= RSS_MAX_PER_FEED:
            break
    return rows


def rss_feeds(log=None) -> list[dict]:
    """媒體官方 RSS 與 Google News 搜尋 RSS。單一來源失敗只記錄錯誤，不影響其他來源。"""
    rows = []
    jobs = [(name, url, topic, src, country, "媒體 RSS") for name, (url, topic, src, country) in RSS_FEEDS.items()]
    jobs += [(f"Google News {topic}", GOOGLE_NEWS_URL.format(q=quote_plus(q + " when:1d")), topic, None, None,
              "Google News RSS") for topic, q in GOOGLE_NEWS_QUERIES.items()]
    for name, url, topic, src, country, collector in jobs:
        try:
            resp = http_get(url, timeout=25, retries=1)
            resp.raise_for_status()
            got = _rss_rows(resp.content, topic, collector, src, country)
            if not got and log:
                log.error(f"RSS {name}", "沒有 36 小時內的新聞")
            rows += got
        except Exception as e:  # noqa: BLE001
            if log:
                log.error(f"RSS {name}", f"{type(e).__name__}: {str(e)[:150]}")
        time.sleep(1)
    return rows
