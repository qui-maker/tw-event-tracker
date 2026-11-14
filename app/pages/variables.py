"""頁面四：國際經濟變項追蹤（總覽與每個變項的獨立頁面）"""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import data
import ui
from groups import NOT_COLLECTED, VARIABLE_GROUPS, digits_for

ui.setup_page("國際經濟變項", "官方數據來自聯準會經濟資料庫 FRED；費半、台積電 ADR、日經、VIX、DXY、黃金來自 Yahoo Finance（非官方，可能缺漏）。")
if data.backend() == "none":
    ui.no_backend_notice()

lv = data.latest_variables()
if lv.empty:
    ui.empty_state("還沒有變項資料。")
    st.stop()

codes = lv["code"].tolist()
qp = st.query_params.get("var", "").upper().replace("-", "_")
sel = st.selectbox("選擇變項看獨立頁面", ["（總覽）"] + codes, index=(codes.index(qp) + 1) if qp in codes else 0,
                   format_func=lambda c: c if c == "（總覽）" else f"{lv.set_index('code').loc[c, 'name']}（{c}）")

if sel == "（總覽）":
    st.query_params.pop("var", None)
    # 與首頁相同的五個分類；指標卡用統一的設計（數值、變化、來源、資料日期）
    by_code = lv.set_index("code")
    for group, gcodes in VARIABLE_GROUPS.items():
        ui.section(group)
        tiles = []
        for code in gcodes:
            if code not in by_code.index:
                tiles.append(ui.kpi(code, None, value_text=ui.missing()))
                continue
            v = by_code.loc[code]
            pts = str(v["unit"]).startswith("%")
            note = f"{v['source']}・{ui.date_str(v['date'])}・{v['frequency']}資料" + ("・非官方" if not bool(v["is_official"]) else "")
            tiles.append(ui.kpi(v["name"], v["value"], v["unit"], digits_for(v["value"]), v["change"] if pts else None,
                                None if pts else v["change_pct"], note, unit_points="個百分點" if pts else None))
        tiles += [ui.kpi(name, None, value_text=ui.missing(), note="尚未納入蒐集") for name in NOT_COLLECTED.get(group, [])]
        ui.kpi_grid(tiles)
    st.stop()

st.query_params["var"] = sel
v = lv.set_index("code").loc[sel]
st.markdown(f"### {v['name']}")
st.markdown(ui.tag(v["category"]) + ui.tag(f"頻率：{v['frequency']}") + ui.tag(f"單位：{v['unit']}")
            + ("" if v["is_official"] else ui.tag("非官方資料", "warn")), unsafe_allow_html=True)

k = st.columns(3)
with k[0]:
    ui.var_metric("最新數據", v)
with k[1]:
    st.markdown(f"**數據日期**<br>{v['date']:%Y-%m-%d}", unsafe_allow_html=True)
with k[2]:
    st.markdown(f"**資料更新時間**<br>{v['fetched_at']:%Y-%m-%d %H:%M}", unsafe_allow_html=True)
st.markdown(f"資料來源：[{v['source']}]({v['source_url']})（{v['source_series']}）")

rng = st.radio("期間", ["3 個月", "1 年", "3 年"], index=1, horizontal=True)
days = {"3 個月": 92, "1 年": 366, "3 年": 1100}[rng]
s = data.variable_series(sel, date.today() - timedelta(days=days + 400))
shown = s[s["obs_date"] >= pd.Timestamp(date.today() - timedelta(days=days))]
st.plotly_chart(ui.line_chart(shown, "obs_date", "value", v["name"], 320, f"{v['name']}（{v['unit']}）"), width="stretch")
if sel == "US_CPI" and len(s) > 13:
    s = s.set_index("obs_date")["value"]
    yoy = (s / s.shift(12) - 1) * 100
    yoy = yoy.dropna().reset_index()
    yoy.columns = ["obs_date", "yoy"]
    yoy = yoy[yoy["obs_date"] >= pd.Timestamp(date.today() - timedelta(days=days))]
    st.plotly_chart(ui.line_chart(yoy, "obs_date", "yoy", "年增率", 240, "美國 CPI 年增率（%，本系統由指數計算）"), width="stretch")

st.markdown("#### 近期相關事件（AI 判斷可能影響此變項）")
ev = data.events(date.today() - timedelta(days=90))
rel = ev[ev["affected_variables"].apply(lambda xs: sel in (xs or []))] if not ev.empty else pd.DataFrame()
if rel.empty:
    st.caption("近 90 天沒有 AI 標示會影響這個變項的事件。")
else:
    for _, e in rel.head(15).iterrows():
        st.markdown(f"- {e['analysis_date']:%m/%d}　[{e['name']}](events?event={e['id']})　{ui.direction_tag(e['direction'])}",
                    unsafe_allow_html=True)
    inds = pd.Series([i for xs in rel["affected_industries"] for i in (xs or [])]).value_counts()
    st.markdown("#### 可能受到影響的產業")
    st.markdown("、".join(f"{k}（{n}）" for k, n in inds.head(12).items()) or "—")
    st.markdown("#### AI 對變項變化的分析（摘自相關事件的推論）")
    for _, e in rel.head(5).iterrows():
        for x in (e["inferences"] or [])[:2]:
            st.markdown(f"<div class='kinfer'>【推論】{x}　<span class='src'>{e['id']}</span></div>", unsafe_allow_html=True)
st.markdown("#### 可能相關的台股公司")
st.caption("第一版研究範圍是大盤，尚未分析個股。")

st.markdown("#### 最新相關新聞")
keyword = {"US10Y": "Treasury", "US2Y": "Treasury", "FED_RATE": "Federal Reserve", "EFFR": "Federal Reserve",
           "US_CPI": "inflation", "US_UNRATE": "jobs", "US_NFP": "payrolls", "WTI": "oil", "BRENT": "oil",
           "SOX": "chip", "TSM_ADR": "TSMC", "GOLD": "gold", "DXY": "dollar", "USD_BROAD": "dollar",
           "USDTWD": "Taiwan dollar", "SPX": "S&P 500", "NASDAQ": "Nasdaq", "NIKKEI": "Nikkei", "VIX": "volatility"}.get(sel)
if keyword:
    nw = data.news(date.today() - timedelta(days=14), keyword=keyword, limit=12)
    for _, n in nw.iterrows():
        st.markdown(f"- [{n['title']}]({n['url']})　<span class='src'>{n['source_name'] or ''}</span>", unsafe_allow_html=True)
    st.caption(f"以標題關鍵字「{keyword}」搜尋近 14 天新聞。")
