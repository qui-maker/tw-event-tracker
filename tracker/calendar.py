"""台股交易日曆。

判斷順序：資料庫裡有紀錄就用紀錄（休市公告、實際成交資料）；沒有紀錄時，週一到週五視為交易日。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from tracker.config import TAIPEI
from tracker.db import fetch_one, insert_ignore


def is_trading_day(conn, d: date) -> bool:
    row = fetch_one(conn, "select is_trading_day from trading_calendar where date = %s", (d,))
    if row is not None:
        return bool(row["is_trading_day"])
    return d.weekday() < 5


def next_trading_day(conn, d: date) -> date:
    n = d + timedelta(days=1)
    while not is_trading_day(conn, n):
        n += timedelta(days=1)
    return n


def prediction_target(conn, now: datetime) -> date:
    """事前預測的目標交易日：今天是交易日且還沒 09:00 開盤 → 今天；否則 → 下一個交易日。"""
    today = now.date()
    if is_trading_day(conn, today) and now.time() < time(9, 0):
        return today
    return next_trading_day(conn, today)


def market_open(d: date) -> datetime:
    return datetime.combine(d, time(9, 0), tzinfo=TAIPEI)


def mark_trading_days(conn, dates, source: str) -> int:
    rows = [{"date": d, "is_trading_day": True, "note": None, "source": source} for d in sorted(set(dates))]
    return insert_ignore(conn, "trading_calendar", rows, conflict="date")
