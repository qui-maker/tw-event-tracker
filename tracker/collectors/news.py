"""新聞蒐集：GDELT（全球新聞，免金鑰）與聯準會新聞稿 RSS（官方）。

只保存標題、網址、媒體、發布時間等資訊，不轉存新聞全文。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import feedparser

from tracker.config import GDELT_MAX_RECORDS, GDELT_QUERIES
from tracker.utils import http_get, title_fingerprint

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
FED_RSS = "https://www.federalreserve.gov/feeds/press_all.xml"


def _gdelt_time(s: str):
    try:
        return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


GDELT_BUDGET_S = 420  # 全部主題合計最多花 7 分鐘；GDELT 限流或沒回應時不能拖垮整個早班（決策紀錄 #46）


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
