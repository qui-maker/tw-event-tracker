"""
資料來源實測程式（第一階段）
================================

用途：
    逐一連線本專案規劃要用的資料來源，確認「能不能連上、拿到的資料日期對不對、
    欄位長什麼樣子」。這支程式只讀取資料，不會寫入任何資料庫。

執行方式（在專案資料夾、已啟用虛擬環境的終端機中）：
    python check_sources.py

執行結果：
    1. 終端機會逐項顯示 ✅（成功）、⚠️（連得上但有問題）、❌（失敗）、⏭️（略過）。
    2. 同一個資料夾會產生 source_check_report.md，請把這個檔案傳給 Claude。

需要的金鑰（放在 .env 檔，沒有設定的項目會自動略過，不會出錯）：
    FRED_API_KEY     FRED 經濟數據
    GEMINI_API_KEY   Google Gemini AI

同一支程式之後也會放到 GitHub Actions 上執行，用來測試「從海外主機能不能連到台灣的資料來源」。
"""

from __future__ import annotations

import json
import logging
import os
import platform
import sys
import time
from pathlib import Path
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

# ──────────────────────────────────────────────────────────────
# 基本設定
# ──────────────────────────────────────────────────────────────
load_dotenv()  # 讀取 .env 檔中的金鑰
logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # 關掉 yfinance 的雜訊訊息

TAIPEI = ZoneInfo("Asia/Taipei")
TIMEOUT = 25  # 每個連線最多等 25 秒
REPORT_FILE = "source_check_report.md"

session = requests.Session()
session.headers.update({"User-Agent": "tw-event-tracker/0.1 (personal research project)"})


@dataclass
class Result:
    """一個測試項目的結果。"""
    group: str                 # 分類，例如「台股官方資料」
    name: str                  # 項目名稱
    status: str = "❌"         # ✅ ⚠️ ❌ ⏭️
    latest_date: str = ""      # 取得資料中最新的日期
    summary: str = ""          # 一行重點
    details: list[str] = field(default_factory=list)  # 詳細內容（寫進報告）
    seconds: float = 0.0       # 花了幾秒


results: list[Result] = []


# ──────────────────────────────────────────────────────────────
# 共用小工具
# ──────────────────────────────────────────────────────────────
def get(url: str, params: dict | None = None) -> requests.Response:
    """發出 GET 請求；連線錯誤或伺服器錯誤（5xx）時等 3 秒重試一次。"""
    for attempt in range(2):
        try:
            resp = session.get(url, params=params, timeout=TIMEOUT)
            if resp.status_code >= 500 and attempt == 0:
                time.sleep(3)
                continue
            return resp
        except requests.RequestException:
            if attempt == 0:
                time.sleep(3)
                continue
            raise
    return resp  # 理論上不會到這裡


def roc_to_date(text: str) -> str:
    """民國年日期轉西元：'1151112' 或 '115/11/12' → '2026-11-12'。看不懂就原樣回傳。"""
    s = str(text).strip().replace("/", "").replace("-", "")
    if s.isdigit() and len(s) == 7:
        return f"{int(s[:3]) + 1911}-{s[3:5]}-{s[5:7]}"
    if s.isdigit() and len(s) == 8:  # 已經是西元 YYYYMMDD
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return str(text)


def short(obj, limit: int = 300) -> str:
    """把資料轉成一行短字串，方便放進報告。"""
    text = json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj
    return text if len(text) <= limit else text[:limit] + "…"


def run_check(group: str, name: str, func) -> None:
    """執行一個測試項目，並記錄結果；測試本身出錯也不會讓整支程式停下來。"""
    r = Result(group=group, name=name)
    start = time.time()
    try:
        func(r)
    except Exception as e:  # noqa: BLE001  這裡刻意接住所有錯誤，記錄後繼續下一項
        r.status = "❌"
        r.summary = f"{type(e).__name__}: {short(str(e), 200)}"
    r.seconds = round(time.time() - start, 1)
    results.append(r)
    print(f"{r.status} [{group}] {name}：{r.summary}" + (f"（最新日期 {r.latest_date}）" if r.latest_date else ""))


# ──────────────────────────────────────────────────────────────
# 一、證交所 OpenAPI（免金鑰）
# ──────────────────────────────────────────────────────────────
TWSE_API = "https://openapi.twse.com.tw/v1"


def twse_fmtqik(r: Result) -> None:
    """每日市場成交資訊：加權指數、成交金額（本專案成交金額的唯一口徑）。"""
    resp = get(f"{TWSE_API}/exchangeReport/FMTQIK")
    resp.raise_for_status()
    rows = resp.json()
    last = rows[-1]
    r.latest_date = roc_to_date(last.get("Date", ""))
    r.status = "✅"
    r.summary = f"{len(rows)} 個交易日；最新收盤 {last.get('TAIEX')}，漲跌 {last.get('Change')}"
    r.details.append(f"最新一列：{short(last)}")


def twse_mi_index(r: Result) -> None:
    """大盤與類股指數。試跑時發現這個 API 會晚一天更新，要特別看日期。"""
    resp = get(f"{TWSE_API}/exchangeReport/MI_INDEX")
    resp.raise_for_status()
    rows = resp.json()
    first = rows[0] if rows else {}
    date_keys = [k for k in first if "日期" in k or "Date" in k]
    if date_keys:
        r.latest_date = roc_to_date(first[date_keys[0]])
    picks = [row for row in rows if any(w in short(row) for w in ("發行量加權", "半導體", "金融保險", "航運"))]
    r.status = "✅" if rows else "⚠️"
    r.summary = f"{len(rows)} 列；欄位：{', '.join(first.keys())}"
    r.details += [f"範例：{short(p)}" for p in picks[:4]]


def twse_stock_day_all(r: Result) -> None:
    """上市個股當日行情。以台積電（2330）當範例。"""
    resp = get(f"{TWSE_API}/exchangeReport/STOCK_DAY_ALL")
    resp.raise_for_status()
    rows = resp.json()
    tsmc = next((row for row in rows if "2330" in row.values()), None)
    if tsmc:
        date_keys = [k for k in tsmc if "Date" in k or "日期" in k]
        if date_keys:
            r.latest_date = roc_to_date(tsmc[date_keys[0]])
    r.status = "✅" if tsmc else "⚠️"
    r.summary = f"{len(rows)} 檔個股" + ("" if tsmc else "；找不到 2330")
    if tsmc:
        r.details.append(f"2330：{short(tsmc)}")


def twse_announcements(r: Result) -> None:
    """上市公司每日重大訊息（公開資訊觀測站資料的官方 API 出口）。"""
    resp = get(f"{TWSE_API}/opendata/t187ap04_L")
    resp.raise_for_status()
    rows = resp.json()
    r.status = "✅" if rows else "⚠️"
    r.summary = f"{len(rows)} 則" + (f"；欄位：{', '.join(rows[0].keys())}" if rows else "；今天沒有資料")
    if rows:
        r.details.append(f"第一則：{short(rows[0])}")


def twse_history(r: Result) -> None:
    """證交所網站的歷史月資料（之後要用來回補過去一年的加權指數）。"""
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
    resp = get(url, params={"date": "20251001", "response": "json"})
    resp.raise_for_status()
    data = resp.json()
    rows = data.get("data") or []
    r.status = "✅" if data.get("stat") == "OK" and rows else "⚠️"
    r.summary = f"2025 年 10 月共 {len(rows)} 列；stat={data.get('stat')}"
    if rows:
        r.latest_date = roc_to_date(rows[-1][0])
        r.details.append(f"欄位：{data.get('fields')}")
        r.details.append(f"最後一列：{short(rows[-1])}")


# ──────────────────────────────────────────────────────────────
# 二、從 API 說明文件（swagger）找出還不知道名稱的端點
# ──────────────────────────────────────────────────────────────
def find_endpoints(swagger: dict, keywords: list[str]) -> list[tuple[str, str]]:
    """在 swagger 文件中，找出摘要含有關鍵字的 GET 端點。回傳 [(路徑, 摘要)]。"""
    found = []
    for path, methods in swagger.get("paths", {}).items():
        op = methods.get("get") or {}
        text = f"{op.get('summary', '')} {op.get('description', '')}"
        if any(k in text for k in keywords):
            found.append((path, op.get("summary", "")))
    return found


def base_url(swagger: dict, site: str, fallback: str) -> str:
    """從 swagger 文件判斷 API 的網址開頭（兼容新舊兩種格式）。"""
    servers = swagger.get("servers") or []
    if servers and servers[0].get("url"):
        url = servers[0]["url"]
        return url if url.startswith("http") else site + url
    if swagger.get("host"):
        return f"https://{swagger['host']}{swagger.get('basePath', '')}"
    return fallback


def twse_swagger(r: Result) -> None:
    """找出三大法人、漲跌家數等端點的正確名稱。"""
    resp = get(f"{TWSE_API}/swagger.json")
    resp.raise_for_status()
    sw = resp.json()
    hits = find_endpoints(sw, ["法人", "漲跌", "休", "指數", "外資", "大盤"])
    r.status = "✅"
    r.summary = f"共 {len(sw.get('paths', {}))} 個端點；關鍵字相符 {len(hits)} 個"
    r.details += [f"`{p}`：{s}" for p, s in hits[:40]]


def tpex_check(r: Result) -> None:
    """櫃買中心 OpenAPI：讀說明文件、找出上櫃指數與收盤行情端點，並試抓前三個。"""
    site = "https://www.tpex.org.tw"
    resp = get(f"{site}/openapi/swagger.json")
    resp.raise_for_status()
    sw = resp.json()
    base = base_url(sw, site, f"{site}/openapi/v1")
    hits = find_endpoints(sw, ["指數", "收盤行情", "重大訊息"])
    r.details.append(f"API 網址開頭：{base}")
    r.details += [f"`{p}`：{s}" for p, s in hits[:30]]
    ok = 0
    for path, summary in hits[:3]:
        try:
            data = get(base + path).json()
            n = len(data) if isinstance(data, list) else 1
            sample = data[0] if isinstance(data, list) and data else data
            r.details.append(f"試抓 `{path}`（{summary}）：{n} 列，範例 {short(sample, 200)}")
            ok += 1
        except Exception as e:  # noqa: BLE001
            r.details.append(f"試抓 `{path}` 失敗：{type(e).__name__}")
    r.status = "✅" if ok else "⚠️"
    r.summary = f"共 {len(sw.get('paths', {}))} 個端點；相符 {len(hits)} 個；試抓成功 {ok} 個"


# ──────────────────────────────────────────────────────────────
# 三、FRED 美國經濟數據（需要 FRED_API_KEY）
# ──────────────────────────────────────────────────────────────
FRED_SERIES = {
    "DFEDTARU": "聯邦基金利率目標區間上限",
    "DFF": "有效聯邦基金利率",
    "CPIAUCSL": "消費者物價指數 CPI",
    "UNRATE": "失業率",
    "PAYEMS": "非農就業人數",
    "DGS10": "10 年期公債殖利率",
    "DGS2": "2 年期公債殖利率",
    "DCOILWTICO": "WTI 原油",
    "DCOILBRENTEU": "Brent 原油",
    "DTWEXBGS": "廣義美元指數（不是 DXY）",
    "SP500": "S&P 500",
    "NASDAQCOM": "Nasdaq 綜合指數",
    "DEXTAUS": "新台幣兌美元",
    "GOLDAMGBD228NLBM": "倫敦金價（測試是否仍有更新）",
}


def fred_check(r: Result) -> None:
    key = os.getenv("FRED_API_KEY")
    if not key:
        r.status, r.summary = "⏭️", "沒有設定 FRED_API_KEY，略過"
        return
    ok = 0
    newest = ""
    for sid, label in FRED_SERIES.items():
        try:
            resp = get("https://api.stlouisfed.org/fred/series/observations", params={
                "series_id": sid, "api_key": key, "file_type": "json",
                "sort_order": "desc", "limit": 10,
            })
            if resp.status_code != 200:
                r.details.append(f"{sid} {label}：HTTP {resp.status_code} {short(resp.text, 120)}")
                continue
            obs = [o for o in resp.json().get("observations", []) if o.get("value") not in (".", "")]
            if obs:
                ok += 1
                newest = max(newest, obs[0]["date"])
                r.details.append(f"{sid} {label}：{obs[0]['date']} = {obs[0]['value']}")
            else:
                r.details.append(f"{sid} {label}：最近 10 筆都沒有數值")
        except Exception as e:  # noqa: BLE001
            r.details.append(f"{sid} {label}：{type(e).__name__}")
        time.sleep(0.6)  # 保持在每分鐘 120 次以下
    r.latest_date = newest
    r.status = "✅" if ok == len(FRED_SERIES) else ("⚠️" if ok else "❌")
    r.summary = f"{ok}/{len(FRED_SERIES)} 個序列取得數值"


# ──────────────────────────────────────────────────────────────
# 四、新聞來源
# ──────────────────────────────────────────────────────────────
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def gdelt_query(r: Result, query: str) -> int:
    resp = get(GDELT_URL, params={
        "query": query, "mode": "artlist", "maxrecords": 5,
        "format": "json", "timespan": "1d", "sort": "datedesc",
    })
    try:
        articles = resp.json().get("articles", [])
    except ValueError:  # 被限流時回傳的是純文字，不是 JSON
        r.details.append(f"查詢 `{query}`：回應不是 JSON：{short(resp.text, 150)}")
        return 0
    r.details.append(f"查詢 `{query}`：{len(articles)} 則")
    for a in articles[:5]:
        r.details.append(f"　- {a.get('seendate')}｜{a.get('sourcecountry')}｜{a.get('domain')}｜{a.get('title')}")
        r.latest_date = max(r.latest_date, str(a.get("seendate", ""))[:8])
    return len(articles)


def gdelt_check(r: Result) -> None:
    """GDELT 國際新聞（免金鑰，每 5 秒最多 1 次）。"""
    n1 = gdelt_query(r, '("Federal Reserve" OR tariff OR semiconductor) sourcelang:english')
    time.sleep(6)
    n2 = gdelt_query(r, "Taiwan sourcecountry:taiwan")
    r.latest_date = roc_to_date(r.latest_date) if r.latest_date else ""
    r.status = "✅" if n1 and n2 else ("⚠️" if n1 or n2 else "❌")
    r.summary = f"國際查詢 {n1} 則、台灣媒體查詢 {n2} 則"


def fed_rss(r: Result) -> None:
    """聯準會新聞稿 RSS。"""
    import feedparser
    resp = get("https://www.federalreserve.gov/feeds/press_all.xml")
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    entries = feed.entries
    r.status = "✅" if entries else "⚠️"
    r.summary = f"{len(entries)} 則新聞稿"
    for e in entries[:3]:
        r.details.append(f"{e.get('published', '')}｜{e.get('title', '')}")
    if entries and entries[0].get("published_parsed"):
        p = entries[0].published_parsed
        r.latest_date = f"{p.tm_year}-{p.tm_mon:02d}-{p.tm_mday:02d}"


# ──────────────────────────────────────────────────────────────
# 五、非官方來源（只當備援）：yfinance
# ──────────────────────────────────────────────────────────────
def yfinance_check(r: Result) -> None:
    import yfinance as yf
    tickers = {"^SOX": "費城半導體指數", "TSM": "台積電 ADR", "^N225": "日經 225"}
    ok = 0
    for t, label in tickers.items():
        try:
            hist = yf.Ticker(t).history(period="5d")
            if len(hist):
                ok += 1
                d = hist.index[-1].date().isoformat()
                r.latest_date = max(r.latest_date, d)
                r.details.append(f"{t} {label}：{d} 收盤 {round(float(hist['Close'].iloc[-1]), 2)}")
            else:
                r.details.append(f"{t} {label}：沒有資料")
        except Exception as e:  # noqa: BLE001
            r.details.append(f"{t} {label}：{type(e).__name__}")
        time.sleep(1)
    r.status = "✅" if ok == len(tickers) else ("⚠️" if ok else "❌")
    r.summary = f"{ok}/{len(tickers)} 個代號取得資料（非官方來源，只當備援）"


# ──────────────────────────────────────────────────────────────
# 六、AI 服務：Google Gemini（需要 GEMINI_API_KEY）
# ──────────────────────────────────────────────────────────────
def gemini_check(r: Result) -> None:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        r.status, r.summary = "⏭️", "沒有設定 GEMINI_API_KEY，略過"
        return
    from google import genai
    client = genai.Client(api_key=key)

    # 1. 列出可用的 Flash 系列模型（與正式流程用同一個排序：正式版、非 lite、版本新的優先）
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tracker.analysis.llm import gemini_candidates
    names = gemini_candidates(client)
    r.details.append(f"可用的 Flash 系列模型（依偏好排序）：{', '.join(names) or '（沒有）'}")
    if not names:
        r.status, r.summary = "⚠️", "金鑰有效，但找不到可用的 Flash 模型"
        return

    # 2. 依序試，直到有一個成功（最新的模型常因需求過高回 503）
    prompt = '請只回傳 JSON，不要加任何說明文字：{"語言": "繁體中文", "測試": "成功", "今天星期幾": "<用繁體中文回答>"}'
    ok_models = []
    for model in names[:6]:
        try:
            text = (client.models.generate_content(model=model, contents=prompt).text or "").strip()
            r.details.append(f"✅ {model}：{short(text, 120)}")
            ok_models.append(model)
            if len(ok_models) >= 2:
                break
        except Exception as e:  # noqa: BLE001
            r.details.append(f"❌ {model}：{type(e).__name__}: {short(str(e), 160)}")
        time.sleep(2)
    if ok_models:
        r.status = "✅"
        r.summary = f"金鑰有效；可用模型：{', '.join(ok_models)}（正式流程會從排序第一個開始試）"
    else:
        r.status, r.summary = "❌", "金鑰有效，但測試的模型都暫時無法使用（多半是 503 需求過高，稍後再試）"


# ──────────────────────────────────────────────────────────────
# 七、格式探測與系統設定檢查（第二階段新增）
# ──────────────────────────────────────────────────────────────
def _last_weekday() -> date:
    d = datetime.now(TAIPEI).date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _describe_tables(payload: dict, r: Result) -> None:
    tables = list(payload.get("tables") or [])
    if payload.get("fields"):
        tables.append({"title": payload.get("title"), "fields": payload.get("fields"), "data": payload.get("data")})
    for t in tables:
        data = t.get("data") or []
        r.details.append(f"表格「{t.get('title')}」：{len(data)} 列；欄位 {t.get('fields')}")
        if data:
            r.details.append(f"　第一列：{short(data[0], 250)}")


def twse_daily_close_probe(r: Result) -> None:
    """記錄證交所 MI_INDEX（指定日期、全部資料）的實際格式，供程式核對。"""
    d = _last_weekday()
    resp = get("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
               params={"date": d.strftime("%Y%m%d"), "type": "ALLBUT0999", "response": "json"})
    resp.raise_for_status()
    payload = resp.json()
    r.latest_date = d.isoformat()
    _describe_tables(payload, r)
    r.status = "✅" if payload.get("stat") == "OK" else "⚠️"
    r.summary = f"{d} stat={payload.get('stat')}；表格 {len(payload.get('tables') or [])} 個"


def twse_bfi82u_probe(r: Result) -> None:
    d = _last_weekday()
    resp = get("https://www.twse.com.tw/rwd/zh/fund/BFI82U",
               params={"type": "day", "dayDate": d.strftime("%Y%m%d"), "response": "json"})
    resp.raise_for_status()
    payload = resp.json()
    r.latest_date = d.isoformat()
    _describe_tables(payload, r)
    r.status = "✅" if payload.get("stat") == "OK" else "⚠️"
    r.summary = f"{d} stat={payload.get('stat')}"


def twse_holiday_probe(r: Result) -> None:
    resp = get(f"{TWSE_API}/holidaySchedule/holidaySchedule")
    resp.raise_for_status()
    rows = resp.json()
    r.details += [short(x, 200) for x in rows[:8]]
    r.status = "✅" if rows else "⚠️"
    r.summary = f"{len(rows)} 列"


def database_check(r: Result) -> None:
    url = os.getenv("DATABASE_URL")
    if not url:
        r.status, r.summary = "⏭️", "沒有設定 DATABASE_URL，略過"
        return
    import psycopg
    with psycopg.connect(url, connect_timeout=20, prepare_threshold=None) as conn:
        version = conn.execute("select version()").fetchone()[0]
        tables = conn.execute("select count(*) from pg_tables where schemaname = 'public'").fetchone()[0]
    r.status = "✅"
    r.summary = f"連線成功；public 資料表 {tables} 個"
    r.details.append(version)


def supabase_read_check(r: Result) -> None:
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        r.status, r.summary = "⏭️", "沒有設定 SUPABASE_URL 或 SUPABASE_ANON_KEY，略過"
        return
    resp = session.get(f"{url.rstrip('/')}/rest/v1/variables", params={"select": "code", "limit": 3},
                       headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=TIMEOUT)
    r.details.append(f"HTTP {resp.status_code}：{short(resp.text, 200)}")
    if resp.status_code == 200:
        r.status, r.summary = "✅", "網站唯讀金鑰可以讀取資料庫"
    elif resp.status_code == 404 or "does not exist" in resp.text:
        r.status, r.summary = "⚠️", "金鑰有效，但資料表還沒建立（建表後再測一次）"
    else:
        r.status, r.summary = "❌", f"HTTP {resp.status_code}"


# ──────────────────────────────────────────────────────────────
# 產生報告
# ──────────────────────────────────────────────────────────────
def write_report(started: datetime) -> None:
    in_actions = os.getenv("GITHUB_ACTIONS") == "true"
    lines = [
        "# 資料來源實測報告",
        "",
        f"- 執行時間（台北）：{started:%Y-%m-%d %H:%M}",
        f"- 執行環境：{'GitHub Actions（海外主機）' if in_actions else '本機'}｜{platform.system()} {platform.machine()}｜Python {sys.version.split()[0]}",
        f"- 結果：✅ {sum(r.status == '✅' for r in results)}　⚠️ {sum(r.status == '⚠️' for r in results)}"
        f"　❌ {sum(r.status == '❌' for r in results)}　⏭️ {sum(r.status == '⏭️' for r in results)}",
        "",
        "| 狀態 | 分類 | 項目 | 最新資料日期 | 摘要 | 秒數 |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        summary = r.summary.replace("|", "／")
        lines.append(f"| {r.status} | {r.group} | {r.name} | {r.latest_date} | {summary} | {r.seconds} |")
    lines += ["", "## 詳細內容", ""]
    for r in results:
        lines.append(f"### {r.status} {r.name}")
        lines += [f"- {d}" for d in r.details] or ["- （無）"]
        lines.append("")
    lines.append("> 這份報告不含任何金鑰。請把整個檔案傳給 Claude。")
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:  # 在 GitHub Actions 的執行頁面直接顯示報告
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))


def main() -> None:
    started = datetime.now(TAIPEI)
    print(f"開始實測（台北時間 {started:%Y-%m-%d %H:%M}）\n")

    run_check("台股官方資料", "證交所 FMTQIK 每日成交資訊", twse_fmtqik)
    run_check("台股官方資料", "證交所 MI_INDEX 大盤與類股指數", twse_mi_index)
    run_check("台股官方資料", "證交所 STOCK_DAY_ALL 上市個股", twse_stock_day_all)
    run_check("台股官方資料", "證交所 t187ap04_L 重大訊息", twse_announcements)
    run_check("台股官方資料", "證交所歷史月資料（回補用）", twse_history)
    run_check("台股官方資料", "證交所 API 說明文件（找端點）", twse_swagger)
    run_check("台股官方資料", "櫃買中心 OpenAPI", tpex_check)
    run_check("國際經濟數據", "FRED", fred_check)
    run_check("新聞", "GDELT 國際新聞", gdelt_check)
    run_check("新聞", "聯準會新聞稿 RSS", fed_rss)
    run_check("備援來源", "yfinance（非官方）", yfinance_check)
    run_check("AI 服務", "Google Gemini", gemini_check)
    run_check("格式探測", "證交所指定日期收盤（MI_INDEX 全部）", twse_daily_close_probe)
    run_check("格式探測", "證交所三大法人（BFI82U）", twse_bfi82u_probe)
    run_check("格式探測", "證交所休市日", twse_holiday_probe)
    run_check("系統設定", "資料庫連線（DATABASE_URL）", database_check)
    run_check("系統設定", "網站唯讀金鑰（Supabase）", supabase_read_check)

    write_report(started)
    print(f"\n完成。報告已存成 {REPORT_FILE}，請把這個檔案傳給 Claude。")


if __name__ == "__main__":
    main()
