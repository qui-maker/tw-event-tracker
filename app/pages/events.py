"""頁面二：國際重大事件（每日事件、篩選、事件詳細資訊）"""
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import data
import ui

ui.setup_page("國際重大事件", "AI 每天早上從新聞標題辨識出的重大事件。事實都附上原始新聞；推論與未確認資訊分開標示。")
if data.backend() == "none":
    ui.no_backend_notice()

# ─── 篩選條件 ───
f1, f2, f3, f4 = st.columns([2, 2, 2, 1])
with f1:
    rng = st.date_input("分析日期區間", (date.today() - timedelta(days=14), date.today()), key="ev_range")
start, end = (rng if isinstance(rng, (list, tuple)) and len(rng) == 2 else (rng[0], rng[0]) if isinstance(rng, (list, tuple)) else (rng, rng))
ev = data.events(start, end)
if ev.empty:
    ui.empty_state("這段期間沒有事件紀錄。")
    st.stop()
all_countries = sorted({c for cs in ev["countries"] for c in (cs or [])})
with f2:
    countries = st.multiselect("國家／地區", all_countries)
with f3:
    types = st.multiselect("事件類型", sorted(ev["event_type"].unique()))
with f4:
    min_imp = st.selectbox("最低重要程度", [1, 2, 3, 4, 5], index=0)
keyword = st.text_input("關鍵字（事件名稱或摘要）", "")

view = ev[ev["importance"] >= min_imp]
if countries:
    view = view[view["countries"].apply(lambda cs: bool(set(cs or []) & set(countries)))]
if types:
    view = view[view["event_type"].isin(types)]
if keyword:
    view = view[view["name"].str.contains(keyword, case=False, na=False) | view["summary"].str.contains(keyword, case=False, na=False)]

# ─── 統計圖 ───
c1, c2 = st.columns(2)
with c1:
    cnt = view["event_type"].value_counts().reset_index()
    cnt.columns = ["type", "n"]
    fig = go.Figure(go.Bar(x=cnt["n"], y=cnt["type"], orientation="h", marker_color=ui.ACCENT,
                           text=cnt["n"], textposition="outside", hovertemplate="%{y}：%{x} 則<extra></extra>"))
    fig = ui.base_layout(fig, 280, "事件類型次數")
    fig.update_layout(showlegend=False, hovermode="closest")
    fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, width="stretch")
with c2:
    fig = go.Figure()
    for i, (t, g) in enumerate(view.groupby("event_type")):
        fig.add_trace(go.Scatter(x=g["analysis_date"], y=g["importance"], mode="markers", name=t,
                                 marker=dict(size=10, color=ui.SERIES[i % len(ui.SERIES)], line=dict(color="white", width=1)),
                                 text=g["name"], hovertemplate="%{x|%m/%d}｜重要程度 %{y}<br>%{text}<extra></extra>"))
    fig = ui.base_layout(fig, 280, "事件時間軸")
    fig.update_layout(hovermode="closest")
    fig.update_yaxes(range=[0.5, 5.5], dtick=1, title="重要程度")
    st.plotly_chart(fig, width="stretch")

st.caption(f"共 {len(view)} 則事件（{start} ～ {end}）")

# ─── 事件列表與詳細資訊 ───
defs = data.variables()
varnames = dict(zip(defs["code"], defs["name"])) if not defs.empty else {}
qp_id = st.query_params.get("event") or st.session_state.pop("event_id", None)
ids = view["id"].tolist()
if qp_id and qp_id not in ids:
    extra = data.events(date(2000, 1, 1))
    extra = extra[extra["id"] == qp_id]
    if not extra.empty:
        view = pd.concat([extra, view])
        ids = view["id"].tolist()
labels = {r["id"]: f"{r['analysis_date']:%m/%d}｜{r['name']}（{r['event_type']}，重要程度 {r['importance']}）" for _, r in view.iterrows()}
sel = st.selectbox("選擇事件看詳細資訊", ids, index=ids.index(qp_id) if qp_id in ids else 0, format_func=lambda i: labels[i])
st.query_params["event"] = sel
e = view[view["id"] == sel].iloc[0]

st.markdown("---")
st.markdown(f"### {e['name']}")
st.markdown(ui.tag(e["event_type"]) + ui.direction_tag(e["direction"]) + ui.tag(f"重要程度 {ui.stars(e['importance'])}")
            + (ui.tag("後續發展", "warn") if e["status"] == "update" else ""), unsafe_allow_html=True)
m = st.columns(4)
m[0].markdown(f"**事件編號**<br>{e['id']}", unsafe_allow_html=True)
m[1].markdown(f"**事件發生日期**<br>{'不明' if pd.isna(e['occurred_date']) else e['occurred_date'].strftime('%Y-%m-%d')}", unsafe_allow_html=True)
m[2].markdown(f"**首則新聞發布（台北）**<br>{'—' if pd.isna(e['first_published_at']) else e['first_published_at'].strftime('%Y-%m-%d %H:%M')}", unsafe_allow_html=True)
m[3].markdown(f"**AI 分析時間**<br>{e['created_at']:%Y-%m-%d %H:%M}", unsafe_allow_html=True)
st.markdown(f"**國家／地區**：{'、'.join(e['countries'] or []) or '—'}　｜　**涉及企業或組織**：{'、'.join(e['actors'] or []) or '—'}")
if e["related_event_id"]:
    st.markdown(f"**延續自**：[{e['related_event_id']}](?event={e['related_event_id']})")
st.markdown(f"**摘要**：{e['summary'] or '—'}")
st.markdown(f"**重要程度理由**：{e['importance_reason'] or '—'}")

a, b = st.columns(2, gap="large")
with a:
    st.markdown("#### AI 分析結果")
    st.markdown("**已確認事實**（附新聞編號）")
    for f in e["facts"] or []:
        st.markdown(f"<div class='kfact'>【事實】{f['text']}　<span class='src'>新聞 {', '.join(map(str, f['news_ids']))}</span></div>", unsafe_allow_html=True)
    st.markdown("**合理推論**")
    for x in e["inferences"] or ["—"]:
        st.markdown(f"<div class='kinfer'>【推論】{x}</div>", unsafe_allow_html=True)
    st.markdown("**尚未確認的資訊**")
    for x in e["unconfirmed"] or ["—"]:
        st.markdown(f"<div class='kunconf'>【未確認】{x}</div>", unsafe_allow_html=True)
    st.markdown("**資料不足的地方**")
    for x in e["data_gaps"] or ["—"]:
        st.markdown(f"- {x}")
with b:
    st.markdown("#### 可能的影響")
    st.markdown(f"**對台股大盤的可能方向**：{ui.direction_tag(e['direction'])}", unsafe_allow_html=True)
    st.markdown("**傳導路徑（AI 推論）**")
    st.markdown(" → ".join(f"`{n}`" for n in (e["pathway"] or [])) or "—")
    st.markdown("**可能影響的經濟變項**：" + ("、".join(f"[{varnames.get(v, v)}](variables?var={v})" for v in e["affected_variables"] or []) or "—"))
    st.markdown("**可能影響的產業**：" + ("、".join(e["affected_industries"] or []) or "—"))
    st.markdown("**可能相關的台股公司**：第一版研究範圍是大盤，尚未分析個股。")
    st.caption("不確定性：以上方向與路徑是 AI 在市場反應前的推論，可能錯誤；請對照「事件關聯分析」頁的事後結果。")

st.markdown("#### 原始新聞來源")
nw = data.event_news(sel)
if nw.empty:
    st.caption("沒有對應的新聞紀錄。")
else:
    for _, n in nw.iterrows():
        when = "時間不明" if pd.isna(n["published_at"]) else n["published_at"].strftime("%Y-%m-%d %H:%M")
        st.markdown(f"- 〔{n['id']}〕[{n['title']}]({n['url']})　<span class='src'>{n['source_name'] or ''}｜{n['country'] or ''}｜發布 {when}｜{n['collector']}</span>",
                    unsafe_allow_html=True)
st.caption(f"AI 模型：{e['model'] or '—'}｜提示詞版本：{e['prompt_version'] or '—'}")
