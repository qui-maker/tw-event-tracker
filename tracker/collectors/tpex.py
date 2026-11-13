"""櫃買中心 OpenAPI（免金鑰）。端點名稱由 API 說明文件（swagger）自動找出，櫃買中心改名時不必改程式。"""
from __future__ import annotations

import re

from tracker.utils import http_get, roc_to_date, to_number

SITE = "https://www.tpex.org.tw"
SOURCE = "櫃買中心"
_cache: dict = {}


def _swagger() -> tuple[str, dict]:
    if "sw" not in _cache:
        resp = http_get(f"{SITE}/openapi/swagger.json")
        resp.raise_for_status()
        sw = resp.json()
        servers = sw.get("servers") or []
        base = servers[0].get("url", "") if servers else ""
        if not base.startswith("http"):
            base = SITE + (base or "/openapi/v1")
        _cache["sw"] = (base, sw)
    return _cache["sw"]


def find_endpoint(*keywords: str, exclude: tuple[str, ...] = ()) -> str | None:
    base, sw = _swagger()
    for path, ops in sw.get("paths", {}).items():
        op = ops.get("get") or {}
        text = f"{op.get('summary', '')}{op.get('description', '')}"
        if all(k in text for k in keywords) and not any(x in text for x in exclude):
            return base + path
    return None


def _pick(row: dict, *candidates: str):
    for c in candidates:
        for k in row:
            if c.lower() in k.lower():
                return row[k]
    return None


def stock_quotes() -> list[dict]:
    """上櫃股票每日收盤行情（最新一個交易日）。"""
    url = find_endpoint("上櫃股票", "收盤行情", exclude=("權證", "債", "興櫃", "零股", "盤後定價")) \
        or find_endpoint("收盤行情", exclude=("權證", "債", "興櫃", "零股"))
    if not url:
        raise RuntimeError("在櫃買中心 API 說明文件中找不到上櫃收盤行情端點")
    resp = http_get(url, timeout=60)
    resp.raise_for_status()
    rows = []
    for r in resp.json():
        code = str(_pick(r, "SecuritiesCompanyCode", "代號") or "").strip()
        d = roc_to_date(_pick(r, "Date", "日期"))
        if not re.fullmatch(r"\d{4}", code) or not d:
            continue
        close, change = to_number(_pick(r, "Close", "收盤")), to_number(_pick(r, "Change", "漲跌"))
        prev = None if close is None or change is None else close - change
        rows.append({"code": code, "name": _pick(r, "CompanyName", "名稱"), "trade_date": d,
                     "open": to_number(_pick(r, "Open", "開盤")), "high": to_number(_pick(r, "High", "最高")),
                     "low": to_number(_pick(r, "Low", "最低")), "close": close, "change": change,
                     "change_pct": round(change / prev * 100, 4) if prev else None,
                     "volume": to_number(_pick(r, "TradingShares", "成交股數")),
                     "value": to_number(_pick(r, "TransactionAmount", "成交金額")),
                     "transactions": to_number(_pick(r, "TransactionNumber", "成交筆數")),
                     "source": f"{SOURCE} OpenAPI"})
    return rows


def index_latest() -> list[dict]:
    """櫃買指數（最新資料）。"""
    url = find_endpoint("櫃買指數", exclude=("報酬", "權證", "債")) or find_endpoint("指數", "收盤", exclude=("報酬", "權證", "債"))
    if not url:
        raise RuntimeError("在櫃買中心 API 說明文件中找不到櫃買指數端點")
    resp = http_get(url)
    resp.raise_for_status()
    data = resp.json()
    data = data if isinstance(data, list) else [data]
    rows = []
    for r in data:
        d = roc_to_date(_pick(r, "Date", "日期"))
        close = to_number(_pick(r, "Close", "收盤", "指數"))
        change = to_number(_pick(r, "Change", "漲跌"))
        if not d or close is None:
            continue
        prev = None if change is None else close - change
        rows.append({"index_code": "TPEX", "trade_date": d, "name": "櫃買指數", "close": close, "change": change,
                     "change_pct": round(change / prev * 100, 4) if prev else None,
                     "trade_value": None, "trade_volume": None, "transactions": None,
                     "source": f"{SOURCE} OpenAPI", "source_url": url})
    return rows
