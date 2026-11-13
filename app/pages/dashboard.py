"""頁面一：首頁 Dashboard"""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import data
import ui
from grading_view import grade_text

ui.setup_page("台股每日變化與世界重大事件")
if data.backend() == "none":
    ui.no_backend_notice()

last = data.latest_trade_date()
runs = data.runs(5)
status = []
if last:
    status.append(f"最新台股收盤資料：{last:%Y-%m-%d}")
if not runs.empty:
    r = runs.iloc[0]
    status.append(f"最近一次自動更新：{r['started_at']:%m/%d %H:%M}（{r['job']}，{ {'success': '成功', 'partial': '部分成功', 'failed': '失敗', 'running': '執行中'}.get(r['status'], r['status'])}）")
st.caption("｜".join(status) or "資料庫目前沒有資料")

if not last:
    ui.empty_state("還沒有任何台股資料。系統完成第一次回補後，這裡就會出現內容。")
    st.stop()

# ─── 1. 今日台股市場概況 ───
st.subheader(f"台股市場概況　{last:%Y/%m/%d}")
tx = data.index_series("TAIEX", last - timedelta(days=200))
today_row = tx.iloc[-1]
tpex = data.index_series("TPEX", last - timedelta(days=10))
br = data.breadth(last - timedelta(days=10))
fl = data.flows(last - timedelta(days=10))

c = st.columns(5)
with c[0]:
    ui.metric("加權指數（點）", today_row["close"], today_row["change"], today_row["change_pct"])
with c[1]:
    st.markdown("**幅度等級**")
    st.markdown(grade_text(tx, len(tx) - 1), unsafe_allow_html=True)
with c[2]:
    ui.metric("成交金額（億元）", (today_row["trade_value"] or 0) / 1e8 if ui.is_num(today_row["trade_value"]) else None)
with c[3]:
    b = br[br["trade_date"].dt.date == last] if not br.empty else pd.DataFrame()
    st.markdown("**上漲／下跌／持平家數**")
    st.markdown("—" if b.empty else
                f"<span style='color:{ui.UP}'>▲ {int(b.iloc[0]['advances'])}</span>　"
                f"<span style='color:{ui.DOWN}'>▼ {int(b.iloc[0]['declines'])}</span>　■ {int(b.iloc[0]['unchanged'] or 0)}",
                unsafe_allow_html=True)
with c[4]:
    f = fl[(fl["trade_date"].dt.date == last) & fl["investor"].str.contains("外資及陸資", na=False)] if not fl.empty else pd.DataFrame()
    ui.metric("外資買賣超（億元）", None if f.empty else f["net"].sum() / 1e8, None)
st.markdown(ui.source_line(today_row["source"], today_row["trade_date"]), unsafe_allow_html=True)
if not tpex.empty:
    t = tpex.iloc[-1]
    st.caption(f"櫃買指數 {ui.fmt(t['close'])}（{ui.arrow(t['change_pct'])} {ui.fmt(t['change_pct'], 2, True)}%，{t['trade_date']:%m/%d}，{t['source']}）")

# ─── 2. 國際市場概況 ───
st.subheader("國際市場與經濟變項")
raw_lv = data.latest_variables()
lv = raw_lv.set_index("code") if not raw_lv.empty else pd.DataFrame()
show = ["SPX", "NASDAQ", "SOX", "TSM_ADR", "US10Y", "DXY", "WTI", "GOLD", "USDTWD", "FED_RATE"]
if lv.empty:
    ui.empty_state("還沒有國際變項資料。")
else:
    cols = st.columns(5)
    for i, code in enumerate([s for s in show if s in lv.index]):
        v = lv.loc[code]
        with cols[i % 5]:
            ui.metric(f"{v['name']}", v["value"], None, v["change_pct"], help=f"單位：{v['unit']}")
            st.markdown(ui.source_line(v["source"], v["date"], unofficial=not bool(v.get("is_official", True))),
                        unsafe_allow_html=True)

# ─── 3 & 4. 事件與 AI 分析 ───
left, right = st.columns([3, 2], gap="large")
with left:
    st.subheader("今日國際重大事件 TOP 5")
    ev = data.events(date.today() - timedelta(days=3))
    if ev.empty:
        ui.empty_state("近三天沒有 AI 辨識出的重大事件。")
    else:
        latest_day = ev["analysis_date"].max()
        top = ev[ev["analysis_date"] == latest_day].sort_values(["importance", "id"], ascending=[False, True]).head(5)
        st.caption(f"分析日期：{latest_day:%Y-%m-%d}")
        varnames = dict(zip(lv.index, lv["name"])) if not lv.empty else {}
        for _, e in top.iterrows():
            tags = ui.tag(e["event_type"]) + ui.direction_tag(e["direction"]) + ui.tag(f"重要程度 {ui.stars(e['importance'])}")
            affected = "、".join(varnames.get(v, v) for v in (e["affected_variables"] or [])) or "—"
            industries = "、".join(e["affected_industries"] or []) or "—"
            occurred = "不明" if pd.isna(e["occurred_date"]) else f"{e['occurred_date']:%Y-%m-%d}"
            st.markdown(f"""<div class="card"><b>{e['name']}</b>　<span class="src">{e['id']}｜發生日期：{occurred}</span><br>
{tags}<br>{e['summary'] or ''}<br><span class="src">可能影響的變項：{affected}｜產業：{industries}</span></div>""",
                        unsafe_allow_html=True)
            if st.button("查看詳細分析", key=f"ev_{e['id']}"):
                st.session_state["event_id"] = e["id"]
                st.switch_page("pages/events.py")

with right:
    st.subheader("AI 今日市場分析")
    reps = data.reports("daily")
    if reps.empty:
        ui.empty_state("還沒有日報。晚班（約 18:20）完成後會產生。")
    else:
        r = reps.iloc[0]
        s = r["sections"] or {}
        st.caption(f"{r['title']}｜產生於 {r['generated_at']:%m/%d %H:%M}｜模型：{r['model'] or '—'}")
        if s:
            st.markdown(s.get("summary", ""))
            st.markdown("**可能影響台股的主要因素**")
            for x in s.get("key_factors", []):
                st.markdown(f"- {x}")
            st.markdown("**值得持續觀察**")
            for x in s.get("watch_items", []):
                st.markdown(f"- {x}")
            with st.expander("資料不足或仍不確定的部分"):
                for x in s.get("data_gaps", []):
                    st.markdown(f"- {x}")
        else:
            st.warning("這份日報的 AI 段落沒有成功產生，請看完整日報的數據表格。")

    st.subheader("事前判斷")
    pr = data.predictions()
    if pr.empty:
        ui.empty_state("還沒有事前判斷。")
    else:
        nxt = pr[pr["target_trading_day"].dt.date >= last].sort_values("target_trading_day")
        if not nxt.empty:
            tday = nxt["target_trading_day"].max()
            st.caption(f"目標交易日：{tday:%Y-%m-%d}（加權指數收盤相對前一交易日）")
            for _, p in nxt[nxt["target_trading_day"] == tday].iterrows():
                who = "AI" if p["kind"] == "ai" else "對照規則（費半方向）"
                result = p.get("result") if isinstance(p.get("result"), str) else "待評估"
                st.markdown(f"{who}：{ui.direction_tag(p['direction'])} 信心 {p['confidence'] or '—'}｜{result}",
                            unsafe_allow_html=True)
        st.page_link("pages/relations.py", label="看全部判斷與命中率 →")

# ─── 5. 市場數據圖表 ───
st.subheader("市場數據圖表")
g1, g2 = st.columns([3, 2], gap="large")
with g1:
    ev90 = data.events(last - timedelta(days=180))
    markers = None
    if not ev90.empty:
        big = ev90[ev90["importance"] >= 4].copy()
        big["d"] = big["analysis_date"].dt.normalize()
        m = big.groupby("d")["name"].apply(lambda s: "<br>".join(s.head(4))).reset_index()
        m = m.merge(tx[["trade_date", "close"]], left_on="d", right_on="trade_date", how="inner")
        markers = pd.DataFrame({"x": m["d"], "y": m["close"], "text": m["name"]})
    st.plotly_chart(ui.line_chart(tx.tail(130), "trade_date", "close", "加權指數", 340, "加權指數近半年（◆＝重要程度 4 以上的事件）",
                                  markers), width="stretch")
    st.markdown(ui.source_line(ui.sources_of(tx.tail(130)), last), unsafe_allow_html=True)
with g2:
    sec = data.indices_on(last)
    sec = sec[sec["index_code"].str.startswith("IDX_")].dropna(subset=["change_pct"]).sort_values("change_pct", ascending=False)
    if sec.empty:
        ui.empty_state("這一天沒有類股指數資料。")
    else:
        pick = pd.concat([sec.head(6), sec.tail(6)]).drop_duplicates("index_code")
        pick["label"] = pick["name"].str.replace("類指數", "")
        st.plotly_chart(ui.change_bars(pick, "label", "change_pct", "類股", 340, f"主要產業表現（{last:%m/%d}，最強與最弱各 6）",
                                       horizontal=True), width="stretch")
        st.markdown(ui.source_line(ui.sources_of(pick), last), unsafe_allow_html=True)

st.markdown("**國際變項近三個月走勢**")
mc = st.columns(4)
for i, code in enumerate(["US10Y", "SOX", "WTI", "DXY"]):
    s = data.variable_series(code, date.today() - timedelta(days=92))
    if s.empty:
        continue
    name = lv.loc[code]["name"] if (not lv.empty and code in lv.index) else code
    with mc[i]:
        st.plotly_chart(ui.line_chart(s, "obs_date", "value", name, 180, name), width="stretch")

# ─── 6. 最新新聞 ───
with st.expander("最新新聞（原始標題）"):
    nw = data.news(date.today() - timedelta(days=2), limit=30)
    for _, n in nw.iterrows():
        when = "" if pd.isna(n["published_at"]) else f"{n['published_at']:%m/%d %H:%M}"
        st.markdown(f"- [{n['title']}]({n['url']})　<span class='src'>{n['source_name'] or ''}｜{when}｜{n['collector']}</span>",
                    unsafe_allow_html=True)
