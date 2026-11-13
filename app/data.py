"""網站的資料讀取層（只讀不寫）。

正式網站：用 Supabase 的唯讀金鑰（SUPABASE_URL、SUPABASE_ANON_KEY）透過 HTTPS 讀取。
本機開發與自動測試：如果沒有 Supabase 設定，就改用 DATABASE_URL 直接連資料庫。
所有查詢結果快取 10 分鐘，減少資料庫負擔。
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd
import streamlit as st

CACHE_TTL = 600
MAX_ROWS = 20000


def _setting(name: str) -> str | None:
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:  # noqa: BLE001  沒有 secrets.toml 時會丟例外
        pass
    return os.getenv(name)


def backend() -> str:
    if _setting("SUPABASE_URL") and _setting("SUPABASE_ANON_KEY"):
        return "supabase"
    if _setting("DATABASE_URL"):
        return "postgres"
    return "none"


@st.cache_resource
def _supabase():
    from supabase import create_client
    return create_client(_setting("SUPABASE_URL"), _setting("SUPABASE_ANON_KEY"))


@st.cache_resource
def _pg():
    import psycopg
    from psycopg.types.numeric import FloatLoader
    conn = psycopg.connect(_setting("DATABASE_URL"), autocommit=True, prepare_threshold=None)
    conn.adapters.register_loader("numeric", FloatLoader)
    return conn


def select(table: str, columns: str = "*", filters: tuple = (), order: str | None = None,
           desc: bool = False, limit: int | None = None) -> pd.DataFrame:
    """通用查詢。filters 是 (欄位, 運算, 值) 的 tuple：eq、neq、gte、lte、in、cs（陣列包含）、ilike。"""
    limit = limit or MAX_ROWS
    if backend() == "supabase":
        rows, start, page = [], 0, 1000
        while start < limit:
            q = _supabase().table(table).select(columns)
            for col, op, val in filters:
                q = {"eq": q.eq, "neq": q.neq, "gte": q.gte, "lte": q.lte, "in": q.in_, "cs": q.contains,
                     "ilike": q.ilike}[op](col, val)
            if order:
                q = q.order(order, desc=desc)
            end = min(start + page, limit) - 1
            got = q.range(start, end).execute().data or []
            rows += got
            if len(got) < end - start + 1:
                break
            start = end + 1
        return pd.DataFrame(rows)
    if backend() == "postgres":
        from psycopg import sql
        from psycopg.rows import dict_row
        cols = sql.SQL("*") if columns == "*" else sql.SQL(", ").join(sql.Identifier(c.strip()) for c in columns.split(","))
        where, params = [], []
        ops = {"eq": "=", "neq": "<>", "gte": ">=", "lte": "<=", "ilike": "ilike"}
        for col, op, val in filters:
            if op == "in":
                where.append(sql.SQL("{} = any(%s)").format(sql.Identifier(col)))
                params.append(list(val))
            elif op == "cs":
                where.append(sql.SQL("{} @> %s").format(sql.Identifier(col)))
                params.append(list(val))
            else:
                where.append(sql.SQL("{} " + ops[op] + " %s").format(sql.Identifier(col)))
                params.append(val)
        q = sql.SQL("select {} from {}").format(cols, sql.Identifier(table))
        if where:
            q += sql.SQL(" where ") + sql.SQL(" and ").join(where)
        if order:
            q += sql.SQL(" order by {} " + ("desc" if desc else "asc")).format(sql.Identifier(order))
        q += sql.SQL(" limit %s")
        params.append(limit)
        with _pg().cursor(row_factory=dict_row) as cur:
            cur.execute(q, params)
            return pd.DataFrame(cur.fetchall())
    return pd.DataFrame()


def _dates(df: pd.DataFrame, *cols) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce", utc=c.endswith("_at"))
            if c.endswith("_at"):
                df[c] = df[c].dt.tz_convert("Asia/Taipei")
    return df


# ─────────────────────────────────────────────
# 台股
# ─────────────────────────────────────────────
@st.cache_data(ttl=CACHE_TTL)
def index_series(code: str, start: date) -> pd.DataFrame:
    df = select("index_daily", filters=(("index_code", "eq", code), ("trade_date", "gte", start.isoformat())),
                order="trade_date")
    return _dates(df, "trade_date", "fetched_at")


@st.cache_data(ttl=CACHE_TTL)
def latest_trade_date() -> date | None:
    df = select("index_daily", "trade_date", (("index_code", "eq", "TAIEX"),), order="trade_date", desc=True, limit=1)
    return None if df.empty else pd.to_datetime(df.iloc[0]["trade_date"]).date()


@st.cache_data(ttl=CACHE_TTL)
def indices_on(d: date) -> pd.DataFrame:
    return select("index_daily", filters=(("trade_date", "eq", d.isoformat()),))


@st.cache_data(ttl=CACHE_TTL)
def breadth(start: date) -> pd.DataFrame:
    return _dates(select("market_breadth", filters=(("trade_date", "gte", start.isoformat()),), order="trade_date"), "trade_date")


@st.cache_data(ttl=CACHE_TTL)
def flows(start: date) -> pd.DataFrame:
    return _dates(select("institutional_flows", filters=(("trade_date", "gte", start.isoformat()),), order="trade_date"),
                  "trade_date")


@st.cache_data(ttl=CACHE_TTL)
def stocks() -> pd.DataFrame:
    return select("stocks", "code, name, market, industry", order="code")


@st.cache_data(ttl=CACHE_TTL)
def stock_series(code: str) -> pd.DataFrame:
    return _dates(select("stock_daily", filters=(("code", "eq", code),), order="trade_date"), "trade_date")


@st.cache_data(ttl=CACHE_TTL)
def announcements(code: str | None = None, start: date | None = None) -> pd.DataFrame:
    f = []
    if code:
        f.append(("code", "eq", code))
    if start:
        f.append(("announce_date", "gte", start.isoformat()))
    return _dates(select("announcements", filters=tuple(f), order="announce_date", desc=True, limit=500), "announce_date")


# ─────────────────────────────────────────────
# 國際變項
# ─────────────────────────────────────────────
@st.cache_data(ttl=CACHE_TTL)
def variables() -> pd.DataFrame:
    return select("variables", order="display_order")


@st.cache_data(ttl=CACHE_TTL)
def variable_series(code: str, start: date) -> pd.DataFrame:
    df = select("variable_values", filters=(("variable_code", "eq", code), ("obs_date", "gte", start.isoformat())),
                order="obs_date")
    return _dates(df, "obs_date", "fetched_at")


@st.cache_data(ttl=CACHE_TTL)
def latest_variables() -> pd.DataFrame:
    """每個變項最新與前一筆數值。月資料要往前多抓，所以取近 120 天。"""
    df = select("variable_values", filters=(("obs_date", "gte", (date.today() - timedelta(days=120)).isoformat()),),
                order="obs_date")
    if df.empty:
        return df
    df = _dates(df, "obs_date", "fetched_at").sort_values("obs_date")
    out = []
    for code, g in df.groupby("variable_code"):
        cur = g.iloc[-1]
        prev = g.iloc[-2] if len(g) > 1 else None
        out.append({"code": code, "date": cur["obs_date"], "value": cur["value"], "source": cur["source"],
                    "source_url": cur["source_url"], "fetched_at": cur["fetched_at"],
                    "prev_value": None if prev is None else prev["value"],
                    "change_pct": None if prev is None or not prev["value"] else (cur["value"] / prev["value"] - 1) * 100})
    defs = variables()
    res = pd.DataFrame(out)
    if defs.empty:
        return res
    # 來源以每一筆數值自己記錄的來源為準
    return res.merge(defs.drop(columns=["source"], errors="ignore"), on="code", how="left")


# ─────────────────────────────────────────────
# 事件、新聞、預測
# ─────────────────────────────────────────────
@st.cache_data(ttl=CACHE_TTL)
def events(start: date, end: date | None = None) -> pd.DataFrame:
    f = [("analysis_date", "gte", start.isoformat())]
    if end:
        f.append(("analysis_date", "lte", end.isoformat()))
    return _dates(select("events", filters=tuple(f), order="analysis_date", desc=True),
                  "analysis_date", "occurred_date", "first_published_at", "created_at")


@st.cache_data(ttl=CACHE_TTL)
def event_news(event_id: str) -> pd.DataFrame:
    links = select("event_news", "news_id", (("event_id", "eq", event_id),))
    if links.empty:
        return pd.DataFrame()
    return _dates(select("news", filters=(("id", "in", [int(i) for i in links["news_id"]]),), order="published_at"),
                  "published_at", "fetched_at")


@st.cache_data(ttl=CACHE_TTL)
def news(start: date, keyword: str | None = None, limit: int = 2000) -> pd.DataFrame:
    f = [("published_at", "gte", start.isoformat())]
    if keyword:
        f.append(("title", "ilike", f"%{keyword}%"))
    return _dates(select("news", filters=tuple(f), order="published_at", desc=True, limit=limit), "published_at", "fetched_at")


@st.cache_data(ttl=CACHE_TTL)
def predictions() -> pd.DataFrame:
    p = select("predictions", order="target_trading_day", desc=True, limit=3000)
    if p.empty:
        return p
    e = select("evaluations", limit=6000)
    p = _dates(p, "target_trading_day", "created_at")
    if not e.empty:
        p = p.merge(e, left_on="id", right_on="prediction_id", how="left")
    return p


# ─────────────────────────────────────────────
# 報告與執行紀錄
# ─────────────────────────────────────────────
@st.cache_data(ttl=CACHE_TTL)
def reports(kind: str | None = None) -> pd.DataFrame:
    f = (("kind", "eq", kind),) if kind else ()
    return _dates(select("reports", "id, kind, period_key, version, title, summary, sections, model, generated_at",
                         f, order="generated_at", desc=True, limit=2000), "generated_at")


@st.cache_data(ttl=CACHE_TTL)
def report_content(report_id: int) -> str:
    df = select("reports", "content_md", (("id", "eq", int(report_id)),), limit=1)
    return "" if df.empty else df.iloc[0]["content_md"]


@st.cache_data(ttl=CACHE_TTL)
def runs(limit: int = 100) -> pd.DataFrame:
    return _dates(select("pipeline_runs", order="started_at", desc=True, limit=limit), "started_at", "finished_at")
