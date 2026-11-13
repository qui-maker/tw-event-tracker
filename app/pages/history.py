"""頁面六：歷史資料與研究報告"""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import data
import ui
from grading_view import abs_label

ui.setup_page("歷史資料與研究報告", "所有資料都可以查詢與下載。研究紀錄（事件、事前判斷、報告）寫入後不會被修改。")
if data.backend() == "none":
    ui.no_backend_notice()

tabs = st.tabs(["研究報告", "新聞", "事件", "台股數據", "變項數據", "日期比較", "執行紀錄"])


def date_range(key: str, days: int = 30):
    r = st.date_input("期間", (date.today() - timedelta(days=days), date.today()), key=key)
    return r if isinstance(r, (list, tuple)) and len(r) == 2 else (r[0], r[0])


def download(df: pd.DataFrame, name: str):
    st.download_button("下載 CSV", df.to_csv(index=False).encode("utf-8-sig"), f"{name}.csv", "text/csv", key=f"dl_{name}")


with tabs[0]:
    kind = st.radio("報告類型", ["daily", "weekly", "monthly"], horizontal=True,
                    format_func={"daily": "日報", "weekly": "週報", "monthly": "月報"}.get)
    reps = data.reports(kind)
    if reps.empty:
        ui.empty_state("還沒有這類報告。日報在每天晚班後產生；週報在週日；月報在每月 1 日。")
    else:
        rid = st.selectbox("選擇報告", reps["id"].tolist(),
                           format_func=lambda i: f"{reps.set_index('id').loc[i, 'title']}　v{reps.set_index('id').loc[i, 'version']}")
        md = data.report_content(rid)
        st.download_button("下載這份報告（Markdown）", md.encode("utf-8"), f"report_{rid}.md", "text/markdown")
        st.markdown(md)

with tabs[1]:
    s, e = date_range("news_range", 7)
    kw = st.text_input("標題關鍵字（新聞多為英文標題）", "")
    nw = data.news(s, kw or None, limit=5000)
    if not nw.empty:
        nw = nw[nw["published_at"].dt.date <= e]
        show = nw[["published_at", "title", "source_name", "country", "topic", "collector", "url"]].rename(columns={
            "published_at": "發布時間（台北）", "title": "標題", "source_name": "媒體", "country": "國家", "topic": "蒐集主題",
            "collector": "來源", "url": "網址"})
        st.dataframe(show, hide_index=True, width="stretch", column_config={"網址": st.column_config.LinkColumn()})
        st.caption(f"{len(show)} 則")
        download(show, "news")
    else:
        ui.empty_state("沒有符合的新聞。")

with tabs[2]:
    s, e = date_range("hist_ev_range", 60)
    kw = st.text_input("事件關鍵字", "", key="hist_ev_kw")
    ev = data.events(s, e)
    if not ev.empty and kw:
        ev = ev[ev["name"].str.contains(kw, na=False) | ev["summary"].str.contains(kw, na=False)]
    if ev.empty:
        ui.empty_state("沒有符合的事件。")
    else:
        show = pd.DataFrame({"分析日期": ev["analysis_date"].dt.strftime("%Y-%m-%d"), "編號": ev["id"], "事件": ev["name"],
                             "類型": ev["event_type"], "重要程度": ev["importance"], "方向": ev["direction"],
                             "國家": ev["countries"].map(lambda x: "、".join(x or [])), "摘要": ev["summary"]})
        st.dataframe(show, hide_index=True, width="stretch")
        download(show, "events")

with tabs[3]:
    s, e = date_range("hist_tx_range", 365)
    tx = data.index_series("TAIEX", s)
    if not tx.empty:
        tx = tx[tx["trade_date"].dt.date <= e]
    if tx.empty:
        ui.empty_state("沒有資料。")
    else:
        show = pd.DataFrame({"日期": tx["trade_date"].dt.strftime("%Y-%m-%d"), "收盤": tx["close"], "漲跌": tx["change"],
                             "漲跌幅(%)": tx["change_pct"], "幅度等級": tx["change_pct"].map(abs_label),
                             "成交金額(元)": tx["trade_value"], "來源": tx["source"]})
        st.dataframe(show.iloc[::-1], hide_index=True, width="stretch")
        download(show, "taiex")

with tabs[4]:
    defs = data.variables()
    if defs.empty:
        ui.empty_state("沒有變項資料。")
    else:
        code = st.selectbox("變項", defs["code"].tolist(), format_func=lambda c: defs.set_index("code").loc[c, "name"], key="hist_var")
        s, e = date_range("hist_var_range", 365)
        vs = data.variable_series(code, s)
        if vs.empty:
            ui.empty_state("這段期間沒有數據。")
        else:
            vs = vs[vs["obs_date"].dt.date <= e]
            show = vs[["obs_date", "value", "source", "source_url", "fetched_at"]].rename(columns={
                "obs_date": "日期", "value": "數值", "source": "來源", "source_url": "來源網址", "fetched_at": "取得時間"})
            st.dataframe(show.iloc[::-1], hide_index=True, width="stretch")
            download(show, f"variable_{code}")

with tabs[5]:
    last = data.latest_trade_date() or date.today()
    c = st.columns(2)
    picks = [c[0].date_input("日期 A", last - timedelta(days=7), key="cmp_a"), c[1].date_input("日期 B", last, key="cmp_b")]
    tx = data.index_series("TAIEX", min(picks) - timedelta(days=5))
    for col, d in zip(c, picks):
        with col:
            row = tx[tx["trade_date"].dt.date == d] if not tx.empty else tx
            st.markdown(f"#### {d:%Y-%m-%d}（{'一二三四五六日'[d.weekday()]}）")
            if row.empty:
                st.caption("這天沒有台股收盤資料（可能休市）。")
            else:
                r = row.iloc[0]
                ui.metric("加權指數", r["close"], r["change"], r["change_pct"])
                st.markdown(ui.tag(abs_label(r["change_pct"])), unsafe_allow_html=True)
            evd = data.events(d, d)
            st.markdown("**當天事件**")
            for _, ev_row in evd.head(6).iterrows():
                st.markdown(f"- {ev_row['name']}（{ev_row['event_type']}，{ev_row['importance']}）")
            if evd.empty:
                st.caption("沒有事件紀錄。")

with tabs[6]:
    rn = data.runs(200)
    if rn.empty:
        ui.empty_state("還沒有執行紀錄。")
    else:
        show = pd.DataFrame({
            "開始時間": rn["started_at"].dt.strftime("%Y-%m-%d %H:%M"), "工作": rn["job"],
            "狀態": rn["status"].map({"success": "✅ 成功", "partial": "⚠️ 部分成功", "failed": "❌ 失敗", "running": "執行中"}),
            "耗時（秒）": ((rn["finished_at"] - rn["started_at"]).dt.total_seconds()).round(0),
            "寫入筆數": rn["rows_written"].map(lambda d: "、".join(f"{k} {v}" for k, v in (d or {}).items())),
            "錯誤": rn["errors"].map(lambda es: "；".join(f"{x['step']}：{x['message'][:120]}" for x in (es or []))),
            "環境": rn["environment"],
        })
        st.dataframe(show, hide_index=True, width="stretch")
