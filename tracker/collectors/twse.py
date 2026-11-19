"""證交所資料蒐集器（免金鑰）。

兩種來源：
- OpenAPI（openapi.twse.com.tw）：只有「最新」資料，格式穩定。
- 網站資料端點（www.twse.com.tw/rwd）：可以指定日期，用來抓當天收盤與回補歷史。
回傳的都是可以直接寫進資料庫的 dict 列表。
"""
from __future__ import annotations

import time

import re
from datetime import date

from tracker.config import INDEX_CODES
from tracker.utils import http_get, roc_to_date, sign_from_html, to_number

OPENAPI = "https://openapi.twse.com.tw/v1"
RWD = "https://www.twse.com.tw/rwd/zh"
SOURCE = "證交所"


def _pct(change, close):
    """由收盤與漲跌點數算漲跌幅（%）。前一日收盤 = 收盤 − 漲跌。"""
    if change is None or close is None or close - change == 0:
        return None
    return round(change / (close - change) * 100, 4)


def _tables(payload: dict) -> list[tuple[str, list, list]]:
    """證交所網站資料有新舊兩種格式，統一轉成 [(標題, 欄位, 資料列)]。"""
    out = []
    for t in payload.get("tables") or []:
        out.append((t.get("title") or "", t.get("fields") or [], t.get("data") or []))
    if payload.get("fields") and payload.get("data"):
        out.append((payload.get("title") or "", payload["fields"], payload["data"]))
    for i in range(1, 12):  # 舊格式 fields1/data1 …
        if payload.get(f"fields{i}") and payload.get(f"data{i}"):
            out.append((payload.get(f"subtitle{i}") or "", payload[f"fields{i}"], payload[f"data{i}"]))
    return out


def _nocache() -> str:
    """加在網址後面的時間戳記，避免拿到快取的舊回應（證交所網站自己的查詢頁面也會加 _=時間戳記）。
    11/19 實測：瀏覽器在 15:03 已查得到當天三大法人，GitHub 主機在 15:06 用同一個網址仍拿到「沒有資料」，
    因為 14:52 那次查詢時的「沒有資料」回應被快取了（決策紀錄 #50）。"""
    return str(int(time.time() * 1000))


def _col(fields: list, *keywords) -> int | None:
    """找出欄位名稱包含所有關鍵字的欄位位置。"""
    for i, f in enumerate(fields):
        if all(k in str(f) for k in keywords):
            return i
    return None


# ─────────────────────────────────────────────
# 加權指數與成交金額（FMTQIK）
# ─────────────────────────────────────────────
def _fmtqik_row(d: date, volume, value, trans, close, change, url: str) -> dict:
    close, change = to_number(close), to_number(change)
    return {
        "index_code": "TAIEX", "trade_date": d, "name": "發行量加權股價指數",
        "close": close, "change": change, "change_pct": _pct(change, close),
        "trade_value": to_number(value), "trade_volume": to_number(volume), "transactions": to_number(trans),
        "source": f"{SOURCE} FMTQIK", "source_url": url,
    }


def fmtqik_latest() -> list[dict]:
    """OpenAPI：本月每個交易日的加權指數與成交金額。"""
    url = f"{OPENAPI}/exchangeReport/FMTQIK"
    resp = http_get(url)
    resp.raise_for_status()
    rows = []
    for r in resp.json():
        d = roc_to_date(r.get("Date"))
        if d:
            rows.append(_fmtqik_row(d, r.get("TradeVolume"), r.get("TradeValue"), r.get("Transaction"),
                                    r.get("TAIEX"), r.get("Change"), url))
    return rows


def fmtqik_month(month: date, exact_day: bool = False) -> list[dict]:
    """網站資料：指定月份的加權指數與成交金額。
    exact_day=True 時用當天日期查詢（回傳的仍是整個月）：11/19 實測，晚班用「月初日期」查詢時拿到的是
    還沒有當天資料的舊回應，同一時間用當天日期查詢已經有資料，推測是快取，所以晚班改用當天日期。"""
    url = f"{RWD}/afterTrading/FMTQIK"
    query = month.strftime("%Y%m%d" if exact_day else "%Y%m01")
    resp = http_get(url, params={"date": query, "response": "json", "_": _nocache()})
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("stat") not in ("OK", None):
        return []
    rows = []
    for _, fields, data in _tables(payload):
        i_date, i_vol, i_val = _col(fields, "日期"), _col(fields, "成交股數"), _col(fields, "成交金額")
        i_trans, i_close, i_chg = _col(fields, "成交筆數"), _col(fields, "加權股價指數"), _col(fields, "漲跌點數")
        if None in (i_date, i_close):
            continue
        for r in data:
            d = roc_to_date(r[i_date])
            if d:
                rows.append(_fmtqik_row(d, r[i_vol] if i_vol is not None else None,
                                        r[i_val] if i_val is not None else None,
                                        r[i_trans] if i_trans is not None else None,
                                        r[i_close], r[i_chg] if i_chg is not None else None,
                                        f"{url}?date={query}"))
    return rows


# ─────────────────────────────────────────────
# 指定日期的完整收盤資料（類股指數、漲跌家數、全部個股）
# ─────────────────────────────────────────────
def daily_close(d: date) -> dict:
    """網站資料 MI_INDEX（type=ALLBUT0999）：一次取得指定日期的類股指數、漲跌家數與上市個股收盤。
    回傳 {"indices": [...], "breadth": {...} 或 None, "stocks": [...], "stat": str}。"""
    url = f"{RWD}/afterTrading/MI_INDEX"
    resp = http_get(url, params={"date": d.strftime("%Y%m%d"), "type": "ALLBUT0999", "response": "json", "_": _nocache()},
                    timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    src_url = f"{url}?date={d:%Y%m%d}&type=ALLBUT0999"
    result = {"indices": [], "breadth": None, "stocks": [], "stat": payload.get("stat")}
    if payload.get("stat") != "OK":
        return result

    for title, fields, data in _tables(payload):
        # 1. 價格指數表
        i_name, i_close = _col(fields, "指數"), _col(fields, "收盤指數")
        if i_name is not None and i_close is not None:
            i_sign, i_pts, i_pct = _col(fields, "漲跌", "+/-"), _col(fields, "漲跌點數"), _col(fields, "漲跌百分比")
            for r in data:
                name = re.sub(r"<[^>]+>", "", str(r[i_name])).strip()
                code = INDEX_CODES.get(name)
                if not code:
                    continue
                sign = sign_from_html(r[i_sign]) if i_sign is not None else 0
                pts = to_number(r[i_pts]) if i_pts is not None else None
                pct = to_number(r[i_pct]) if i_pct is not None else None
                close = to_number(r[i_close])
                change = None if pts is None else (abs(pts) * sign if sign else pts)
                if pct is not None and sign and pct > 0:
                    pct = pct * sign
                result["indices"].append({
                    "index_code": code, "trade_date": d, "name": name, "close": close,
                    "change": change, "change_pct": pct if pct is not None else _pct(change, close),
                    "trade_value": None, "trade_volume": None, "transactions": None,
                    "source": f"{SOURCE} MI_INDEX", "source_url": src_url,
                })
            continue

        # 2. 漲跌證券數合計表
        if "漲跌證券數" in title or (_col(fields, "類型") is not None and _col(fields, "股票") is not None):
            i_type, i_stock = _col(fields, "類型"), _col(fields, "股票")
            if i_type is None or i_stock is None:
                continue
            b = {"trade_date": d, "market": "TWSE", "source": f"{SOURCE} MI_INDEX", "source_url": src_url}
            for r in data:
                label, cell = str(r[i_type]), str(r[i_stock])
                m = re.match(r"\s*([\d,]+)\s*(?:\(([\d,]+)\))?", cell)
                if not m:
                    continue
                n = int(m.group(1).replace(",", ""))
                lim = int(m.group(2).replace(",", "")) if m.group(2) else None
                if "上漲" in label:
                    b["advances"], b["limit_up"] = n, lim
                elif "下跌" in label:
                    b["declines"], b["limit_down"] = n, lim
                elif "持平" in label:
                    b["unchanged"] = n
            if "advances" in b:
                for k in ("advances", "declines", "unchanged", "limit_up", "limit_down"):
                    b.setdefault(k, None)
                result["breadth"] = b
            continue

        # 3. 每日收盤行情（個股）
        i_code, i_cl = _col(fields, "證券代號"), _col(fields, "收盤價")
        if i_code is not None and i_cl is not None:
            i_nm = _col(fields, "證券名稱")
            i_vol, i_tr, i_val = _col(fields, "成交股數"), _col(fields, "成交筆數"), _col(fields, "成交金額")
            i_op, i_hi, i_lo = _col(fields, "開盤價"), _col(fields, "最高價"), _col(fields, "最低價")
            i_sign, i_diff = _col(fields, "漲跌", "+/-"), _col(fields, "漲跌價差")
            for r in data:
                code = str(r[i_code]).strip()
                if not re.fullmatch(r"\d{4}", code):  # 只保留 4 碼普通股與 ETF
                    continue
                close = to_number(r[i_cl])
                diff = to_number(r[i_diff]) if i_diff is not None else None
                sign = sign_from_html(r[i_sign]) if i_sign is not None else 0
                change = None if diff is None else abs(diff) * sign if sign else diff
                get = lambda i: to_number(r[i]) if i is not None else None  # noqa: E731
                result["stocks"].append({
                    "code": code, "name": str(r[i_nm]).strip() if i_nm is not None else None,
                    "trade_date": d, "open": get(i_op), "high": get(i_hi), "low": get(i_lo), "close": close,
                    "change": change, "change_pct": _pct(change, close),
                    "volume": get(i_vol), "value": get(i_val), "transactions": get(i_tr),
                    "source": f"{SOURCE} MI_INDEX",
                })
    return result


def indices_openapi_latest() -> list[dict]:
    """OpenAPI 的大盤與類股指數（備援；實測發現常晚一天更新，所以只在網站資料失敗時使用）。"""
    url = f"{OPENAPI}/exchangeReport/MI_INDEX"
    resp = http_get(url)
    resp.raise_for_status()
    rows = []
    for r in resp.json():
        keys = list(r.keys())
        k_date = next((k for k in keys if "日期" in k or k == "Date"), None)
        k_name = next((k for k in keys if k in ("指數", "Index") or k.endswith("指數") and "收盤" not in k), None)
        k_close = next((k for k in keys if "收盤" in k), None)
        k_pts = next((k for k in keys if "漲跌點數" in k), None)
        k_pct = next((k for k in keys if "百分比" in k), None)
        k_sign = next((k for k in keys if k in ("漲跌", "漲跌(+/-)")), None)
        if not (k_date and k_name and k_close):
            continue
        name = str(r[k_name]).strip()
        code = INDEX_CODES.get(name)
        d = roc_to_date(r[k_date])
        if not code or not d:
            continue
        sign = sign_from_html(r.get(k_sign)) if k_sign else 0
        pts = to_number(r.get(k_pts)) if k_pts else None
        pct = to_number(r.get(k_pct)) if k_pct else None
        close = to_number(r[k_close])
        change = None if pts is None else (abs(pts) * sign if sign else pts)
        if pct is not None and sign and pct > 0:
            pct *= sign
        rows.append({"index_code": code, "trade_date": d, "name": name, "close": close, "change": change,
                     "change_pct": pct if pct is not None else _pct(change, close),
                     "trade_value": None, "trade_volume": None, "transactions": None,
                     "source": f"{SOURCE} OpenAPI MI_INDEX", "source_url": url})
    return rows


# ─────────────────────────────────────────────
# 三大法人（BFI82U）
# ─────────────────────────────────────────────
def institutional(d: date) -> list[dict]:
    url = f"{RWD}/fund/BFI82U"
    resp = http_get(url, params={"type": "day", "dayDate": d.strftime("%Y%m%d"), "response": "json", "_": _nocache()})
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("stat") != "OK":
        return []
    rows = []
    for _, fields, data in _tables(payload):
        i_name, i_buy, i_sell, i_net = _col(fields, "單位名稱"), _col(fields, "買進"), _col(fields, "賣出"), _col(fields, "差額")
        if i_name is None:
            continue
        for r in data:
            rows.append({"trade_date": d, "investor": str(r[i_name]).strip(),
                         "buy": to_number(r[i_buy]) if i_buy is not None else None,
                         "sell": to_number(r[i_sell]) if i_sell is not None else None,
                         "net": to_number(r[i_net]) if i_net is not None else None,
                         "source": f"{SOURCE} BFI82U",
                         "source_url": f"{url}?type=day&dayDate={d:%Y%m%d}"})
    return rows


# ─────────────────────────────────────────────
# 上市個股（OpenAPI 備援）、重大訊息、休市日
# ─────────────────────────────────────────────
def stock_day_all() -> list[dict]:
    url = f"{OPENAPI}/exchangeReport/STOCK_DAY_ALL"
    resp = http_get(url, timeout=60)
    resp.raise_for_status()
    rows = []
    for r in resp.json():
        code = str(r.get("Code", "")).strip()
        d = roc_to_date(r.get("Date"))
        if not re.fullmatch(r"\d{4}", code) or not d:
            continue
        close, change = to_number(r.get("ClosingPrice")), to_number(r.get("Change"))
        rows.append({"code": code, "name": r.get("Name"), "trade_date": d,
                     "open": to_number(r.get("OpeningPrice")), "high": to_number(r.get("HighestPrice")),
                     "low": to_number(r.get("LowestPrice")), "close": close, "change": change,
                     "change_pct": _pct(change, close), "volume": to_number(r.get("TradeVolume")),
                     "value": to_number(r.get("TradeValue")), "transactions": to_number(r.get("Transaction")),
                     "source": f"{SOURCE} OpenAPI STOCK_DAY_ALL"})
    return rows


def announcements() -> list[dict]:
    """上市公司每日重大訊息（公開資訊觀測站資料的官方 API 出口）。"""
    url = f"{OPENAPI}/opendata/t187ap04_L"
    resp = http_get(url, timeout=60)
    resp.raise_for_status()
    rows = []
    for r in resp.json():
        pick = lambda *ws: next((r[k] for k in r if all(w in k for w in ws)), None)  # noqa: E731
        subject = pick("主旨")
        if not subject:
            continue
        rows.append({"code": (pick("公司代號") or "").strip() or None, "name": (pick("公司名稱") or "").strip() or None,
                     "announce_date": roc_to_date(pick("發言日期") or pick("出表日期")),
                     "announce_time": pick("發言時間"), "subject": str(subject).strip()[:500],
                     "content": (pick("說明") or "")[:4000], "market": "TWSE",
                     "source": f"{SOURCE} OpenAPI t187ap04_L", "source_url": url})
    return rows


def holidays() -> list[dict]:
    """證交所公告的休市日（含春節前最後交易日等說明列，名稱含「交易」者視為交易日）。"""
    url = f"{OPENAPI}/holidaySchedule/holidaySchedule"
    resp = http_get(url)
    resp.raise_for_status()
    rows = []
    for r in resp.json():
        d = roc_to_date(r.get("Date"))
        name = str(r.get("Name") or "")
        desc = str(r.get("Description") or "")
        if not d:
            continue
        trading = "交易" in name and ("最後交易" in name or "開始交易" in name)
        rows.append({"date": d, "is_trading_day": trading, "note": (name + " " + desc).strip()[:300],
                     "source": f"{SOURCE} 休市公告"})
    return rows
