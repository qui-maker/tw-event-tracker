"""共用小工具：網路連線、日期轉換、數字解析。"""
from __future__ import annotations

import hashlib
import re
import time
from datetime import date, datetime, timedelta

import requests

from tracker.config import TAIPEI

USER_AGENT = "tw-event-tracker/1.0 (personal research project; https://github.com)"

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*"})


def http_get(url: str, params: dict | None = None, timeout: int = 30, retries: int = 2,
             wait: float = 3.0) -> requests.Response:
    """GET 請求。連線錯誤或 5xx 時重試；4xx 直接回傳讓呼叫端判斷。"""
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = _session.get(url, params=params, timeout=timeout)
            if resp.status_code >= 500 and attempt < retries:
                time.sleep(wait * (attempt + 1))
                continue
            return resp
        except requests.RequestException as e:
            last_error = e
            if attempt < retries:
                time.sleep(wait * (attempt + 1))
    raise last_error  # type: ignore[misc]


def now_taipei() -> datetime:
    return datetime.now(TAIPEI)


def today_taipei() -> date:
    return now_taipei().date()


def roc_to_date(text) -> date | None:
    """民國或西元日期字串轉 date。
    支援 '1151112'、'115/11/12'、'115-11-12'、'20261112'、'2026-11-12'、'2026/11/12'。"""
    if text is None:
        return None
    s = str(text).strip()
    m = re.match(r"^(\d{2,4})[/-](\d{1,2})[/-](\d{1,2})$", s)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        if y < 1911:
            y += 1911
        return date(y, mo, d)
    digits = re.sub(r"\D", "", s)
    if len(digits) == 7:
        return date(int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:7]))
    if len(digits) == 8:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    return None


def to_number(value) -> float | None:
    """'1,234.56'、'+12.3'、'-0.5%'、'--'、'' 轉成數字；無法辨識回傳 None。
    也會去掉證交所欄位裡的 HTML 標籤。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = re.sub(r"<[^>]+>", "", str(value)).strip().replace(",", "").replace("%", "")
    if s in ("", "-", "--", "---", "X", "x", "N/A", "除息", "除權"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def sign_from_html(value) -> int:
    """證交所漲跌欄位常是 '<p style=color:red>+</p>' 或 '<p style=color:green>-</p>'，取出正負號。"""
    s = str(value or "")
    text = re.sub(r"<[^>]+>", "", s).strip()
    if text.startswith("-") or "green" in s:
        return -1
    if text.startswith("+") or "red" in s:
        return 1
    return 0


def title_fingerprint(title: str) -> str:
    """把標題正規化（小寫、去標點與空白）後取雜湊，用來辨識不同網址的同一則新聞。"""
    norm = re.sub(r"[\W_]+", "", (title or "").lower())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def month_starts(start: date, end: date):
    """產生 start 到 end 之間每個月的第一天。"""
    d = date(start.year, start.month, 1)
    while d <= end:
        yield d
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def change_text(value, prev, unit: str | None) -> str:
    """變項的「較前一筆」：單位是 % 的（利率、殖利率、失業率）用個百分點，其他用變化率。"""
    if value is None or prev is None:
        return "—"
    value, prev = float(value), float(prev)
    if unit and unit.strip().startswith("%"):
        return f"{value - prev:+.2f} 個百分點"
    return "—" if prev == 0 else f"{(value / prev - 1) * 100:+.2f}%"
