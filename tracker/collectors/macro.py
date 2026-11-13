"""國際經濟與市場變項：FRED（官方，需金鑰）與 Yahoo Finance（非官方備援）。"""
from __future__ import annotations

import logging
import os
import time
from datetime import date

from tracker.config import VARIABLES
from tracker.utils import http_get

logging.getLogger("yfinance").setLevel(logging.CRITICAL)
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"


def variable_definitions() -> list[dict]:
    return [{"code": c, "name": n, "category": cat, "unit": u, "frequency": f, "source": s,
             "source_series": sid, "is_official": off, "description": None, "display_order": i}
            for i, (c, n, cat, u, f, s, sid, off) in enumerate(VARIABLES)]


def fred(code: str, series_id: str, start: date) -> list[dict]:
    key = os.environ.get("FRED_API_KEY")
    if not key:
        raise RuntimeError("沒有設定 FRED_API_KEY")
    resp = http_get(FRED_URL, params={"series_id": series_id, "api_key": key, "file_type": "json",
                                      "observation_start": start.isoformat()})
    if resp.status_code != 200:
        raise RuntimeError(f"FRED {series_id} HTTP {resp.status_code}: {resp.text[:200]}")
    rows = []
    for o in resp.json().get("observations", []):
        if o.get("value") in (".", "", None):  # FRED 用「.」表示當天沒有資料
            continue
        rows.append({"variable_code": code, "obs_date": date.fromisoformat(o["date"]), "value": float(o["value"]),
                     "source": "FRED", "source_url": f"https://fred.stlouisfed.org/series/{series_id}"})
    return rows


def yahoo(code: str, ticker: str, start: date) -> list[dict]:
    import yfinance as yf
    hist = yf.Ticker(ticker).history(start=start.isoformat(), auto_adjust=False)
    rows = []
    for ts, row in hist.iterrows():
        val = row.get("Close")
        if val is None or val != val:  # NaN
            continue
        rows.append({"variable_code": code, "obs_date": ts.date(), "value": round(float(val), 4),
                     "source": "Yahoo Finance（非官方）",
                     "source_url": f"https://finance.yahoo.com/quote/{ticker}"})
    return rows


def collect_all(start: date, log=None) -> list[dict]:
    """抓全部變項。單一變項失敗只記錄錯誤，不影響其他變項。"""
    rows = []
    for code, _n, _c, _u, _f, source, series, _o in VARIABLES:
        try:
            got = fred(code, series, start) if source == "FRED" else yahoo(code, series, start)
            rows += got
        except Exception as e:  # noqa: BLE001
            if log:
                log.error(f"變項 {code}", f"{type(e).__name__}: {e}")
        time.sleep(0.6 if source == "FRED" else 1.0)
    return rows
