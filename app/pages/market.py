"""頁面三：台股市場追蹤（大盤、產業、個股）"""
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import data
import ui
from grading_view import abs_label, rel_label, z_value

ui.setup_page("台股市場追蹤", "加權指數與成交金額來自證交所 FMTQIK（唯一口徑）；類股、漲跌家數與個股來自證交所 MI_INDEX；上櫃來自櫃買中心 OpenAPI。")
if data.backend() == "none":
    ui.no_backend_notice()
last = data.latest_trade_date()
if not last:
    ui.empty_state("還沒有台股資料。")
    st.stop()

RANGES = {"1 個月": 31, "3 個月": 92, "6 個月": 183, "1 年": 366, "3 年": 1100}
tab1, tab2, tab3 = st.tabs(["大盤", "產業", "個股"])

with tab1:
    pick = st.radio("期間", list(RANGES), index=2, horizontal=True, key="mk_range")
    start = last - timedelta(days=RANGES[pick])
    full = data.index_series("TAIEX", start - timedelta(days=40))
    full["z"] = [z_value(full["change_pct"], i) for i in range(len(full))]
    tx = full[full["trade_date"].dt.date >= start].copy()
    st.plotly_chart(ui.line_chart(tx, "trade_date", "close", "加權指數", 330, "發行量加權股價指數（點）"), width="stretch")
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(ui.change_bars(tx, "trade_date", "change_pct", "漲跌幅", 240, "每日漲跌幅（%）"), width="stretch")
    with c2:
        fig = go.Figure(go.Bar(x=tx["trade_date"], y=tx["trade_value"] / 1e8, marker_color=ui.ACCENT, name="成交金額",
                               hovertemplate="%{x|%Y-%m-%d}：%{y:,.0f} 億元<extra></extra>"))
        fig = ui.base_layout(fig, 240, "成交金額（億元）")
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig, width="stretch")
    st.markdown(ui.source_line(ui.sources_of(tx), last), unsafe_allow_html=True)

    st.markdown("#### 最近 10 個交易日")
    recent = tx.tail(10).iloc[::-1].copy()
    br = data.breadth(last - timedelta(days=20))
    fl = data.flows(last - timedelta(days=20))
    table = pd.DataFrame({
        "日期": recent["trade_date"].dt.strftime("%Y-%m-%d"),
        "收盤": recent["close"].map(lambda v: ui.fmt(v)),
        "漲跌": recent["change"].map(lambda v: ui.fmt(v, 2, True)),
        "漲跌幅": recent["change_pct"].map(lambda v: f"{ui.arrow(v)} {ui.fmt(v, 2, True)}%"),
        "幅度等級": recent["change_pct"].map(abs_label),
        "相對近 20 日": recent["z"].map(rel_label),
        "成交金額（億元）": (recent["trade_value"] / 1e8).map(lambda v: ui.fmt(v, 0)),
    })
    if not br.empty:
        b = br.assign(日期=br["trade_date"].dt.strftime("%Y-%m-%d"))[["日期", "advances", "declines"]]
        table = table.merge(b.rename(columns={"advances": "上漲家數", "declines": "下跌家數"}), on="日期", how="left")
    if not fl.empty:
        fx = fl[fl["investor"].str.contains("外資及陸資", na=False)].groupby("trade_date")["net"].sum().reset_index()
        fx["日期"] = fx["trade_date"].dt.strftime("%Y-%m-%d")
        fx["外資買賣超（億元）"] = (fx["net"] / 1e8).map(lambda v: ui.fmt(v, 2, True))
        table = table.merge(fx[["日期", "外資買賣超（億元）"]], on="日期", how="left")
    st.dataframe(table, hide_index=True, width="stretch")
    st.caption("幅度等級與相對波動依「決策紀錄 v1」計算：絕對幅度分五級；相對波動＝當日漲跌幅 ÷ 前 20 個交易日標準差。")

    tp = data.index_series("TPEX", start)
    st.markdown("#### 上櫃市場（櫃買指數）")
    if tp.empty:
        ui.empty_state("還沒有櫃買指數資料（櫃買中心 API 只提供最新一天，會從系統上線後開始累積）。")
    else:
        st.plotly_chart(ui.line_chart(tp, "trade_date", "close", "櫃買指數", 260, "櫃買指數（點）"), width="stretch")
        st.markdown(ui.source_line(tp.iloc[-1]["source"], tp.iloc[-1]["trade_date"]), unsafe_allow_html=True)

with tab2:
    sec = data.indices_on(last)
    sec = sec[sec["index_code"].str.startswith("IDX_")].dropna(subset=["change_pct"]).sort_values("change_pct", ascending=False)
    if sec.empty:
        ui.empty_state("這一天沒有類股指數資料。")
    else:
        sec["label"] = sec["name"].str.replace("類指數", "")
        st.plotly_chart(ui.change_bars(sec, "label", "change_pct", "類股", max(320, 22 * len(sec)), f"類股指數漲跌幅（{last:%Y-%m-%d}）",
                                       horizontal=True), width="stretch")
        st.markdown(ui.source_line(ui.sources_of(sec), last), unsafe_allow_html=True)
        name = st.selectbox("看單一類股的歷史走勢", sec["name"].tolist())
        code = sec[sec["name"] == name].iloc[0]["index_code"]
        hist = data.index_series(code, last - timedelta(days=366))
        if len(hist) < 5:
            st.caption("類股指數從系統上線後才開始逐日累積，目前資料天數還不多。")
        st.plotly_chart(ui.line_chart(hist, "trade_date", "close", name, 280, name), width="stretch")

with tab3:
    stk = data.stocks()
    if stk.empty:
        ui.empty_state("還沒有個股資料（晚班執行後會出現）。")
        st.stop()
    st.info("第一版研究範圍是大盤：個股頁提供行情、重大訊息與相關新聞查詢；個股層級的 AI 影響分析尚未完成。")
    q = st.text_input("搜尋股票代號或名稱", "2330")
    hits = stk[stk["code"].str.contains(q, na=False) | stk["name"].str.contains(q, na=False)] if q else stk.head(50)
    if hits.empty:
        st.warning("找不到符合的股票。")
        st.stop()
    choice = st.selectbox("選擇股票", hits["code"].tolist(),
                          format_func=lambda c: f"{c} {hits.set_index('code').loc[c, 'name']}（{hits.set_index('code').loc[c, 'market']}）")
    info = stk.set_index("code").loc[choice]
    s = data.stock_series(choice)
    st.markdown(f"### {choice} {info['name']}")
    st.caption(f"市場：{'上市' if info['market'] == 'TWSE' else '上櫃' if info['market'] == 'TPEX' else info['market']}｜所屬產業：{info['industry'] or '尚未建立產業分類'}")
    if s.empty:
        ui.empty_state("沒有這檔股票的行情資料。")
    else:
        lr = s.iloc[-1]
        k = st.columns(4)
        with k[0]:
            ui.metric("收盤價（元）", lr["close"], lr["change"], lr["change_pct"])
        with k[1]:
            ui.metric("成交股數（張）", (lr["volume"] or 0) / 1000 if ui.is_num(lr["volume"]) else None, digits=0)
        with k[2]:
            ui.metric("成交金額（億元）", (lr["value"] or 0) / 1e8 if ui.is_num(lr["value"]) else None)
        with k[3]:
            st.markdown(f"**資料日期**<br>{lr['trade_date']:%Y-%m-%d}<br><span class='src'>{lr['source']}</span>", unsafe_allow_html=True)
        st.plotly_chart(ui.line_chart(s, "trade_date", "close", "收盤價", 280, "歷史收盤價（元）"), width="stretch")
        fig = go.Figure(go.Bar(x=s["trade_date"], y=s["volume"] / 1000, marker_color=ui.ACCENT,
                               hovertemplate="%{x|%Y-%m-%d}：%{y:,.0f} 張<extra></extra>"))
        fig = ui.base_layout(fig, 200, "成交量（張）")
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig, width="stretch")
        st.caption("個股行情從系統上線後逐日累積。")
    st.markdown("#### 公司重大訊息")
    an = data.announcements(choice)
    if an.empty:
        st.caption("沒有重大訊息紀錄（目前只蒐集上市公司）。")
    else:
        st.dataframe(an[["announce_date", "announce_time", "subject"]].rename(columns={"announce_date": "日期", "announce_time": "時間", "subject": "主旨"}),
                     hide_index=True, width="stretch")
    st.markdown("#### 相關新聞（標題含公司名稱）")
    nw = data.news(date.today() - timedelta(days=30), keyword=str(info["name"]), limit=30)
    if nw.empty:
        st.caption("近 30 天沒有標題含公司名稱的新聞。國際新聞多為英文標題，可改用英文名稱在「歷史資料」頁搜尋。")
    else:
        for _, n in nw.iterrows():
            st.markdown(f"- [{n['title']}]({n['url']})　<span class='src'>{n['source_name'] or ''}</span>", unsafe_allow_html=True)
    st.markdown("#### 相關國際事件")
    st.caption("尚未完成：第一版的事件分析只到大盤與產業層級。")
