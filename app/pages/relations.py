"""頁面五：事件關聯分析（傳導鏈、事前判斷與實際結果、事件前後、歷史比較、長期走勢）"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import data
import ui
from grading_view import abs_label

ui.setup_page("事件關聯分析",
              "這一頁保留 AI 在市場反應「之前」寫下的判斷，並與之後的實際數據比較。所有關聯都是同期觀察，不代表因果。")
if data.backend() == "none":
    ui.no_backend_notice()

rng = st.date_input("分析期間", (date.today() - timedelta(days=30), date.today()), key="rel_range")
start, end = (rng if isinstance(rng, (list, tuple)) and len(rng) == 2 else (rng[0], rng[0]))
ev = data.events(start, end)
pr = data.predictions()
tx = data.index_series("TAIEX", start - timedelta(days=400))

t1, t2, t3, t4, t5 = st.tabs(["傳導鏈", "事前判斷 vs 實際", "事件前後", "歷史事件比較", "變項與大盤長期走勢"])

# ─── 1. 傳導鏈 ───
with t1:
    if ev.empty:
        ui.empty_state("這段期間沒有事件。")
    else:
        min_imp = st.slider("只看重要程度至少", 1, 5, 3)
        sub = ev[ev["importance"] >= min_imp]
        links, nodes = {}, {}

        def node(label, layer):
            key = (label, layer)
            if key not in nodes:
                nodes[key] = len(nodes)
            return nodes[key]

        for _, e in sub.iterrows():
            path = list(e["pathway"] or [])
            if len(path) < 2:
                continue
            path[0] = e["name"]
            for i in range(len(path) - 1):
                a = node(path[i][:24], i)
                b = node(path[i + 1][:24], i + 1 if i + 1 < len(path) - 1 else 9)
                links[(a, b)] = links.get((a, b), 0) + 1
        if not links:
            ui.empty_state("沒有足夠的傳導路徑資料。")
        else:
            labels = [k[0] for k in sorted(nodes, key=nodes.get)]
            layer_color = {0: "#eb6834", 1: "#2a78d6", 2: "#1baf7a", 3: "#6250d6", 9: "#1f4e8c"}
            colors = [layer_color.get(k[1], "#6250d6") for k in sorted(nodes, key=nodes.get)]
            fig = go.Figure(go.Sankey(
                node=dict(label=labels, color=colors, pad=14, thickness=14),
                link=dict(source=[a for a, _ in links], target=[b for _, b in links], value=list(links.values()),
                          color="rgba(31,78,140,0.18)")))
            fig = ui.base_layout(fig, max(380, 26 * len(labels)), "國際事件 → 經濟變項 → 產業 → 台股加權指數（AI 推論的傳導路徑）")
            st.plotly_chart(fig, width="stretch")
            st.caption("橙色＝事件；藍、綠、紫＝中間的變項或產業；深藍＝台股加權指數。線越粗代表越多事件經過同一條路徑。")

        st.markdown("#### 經濟變項與產業的共同出現次數")
        defs = data.variables()
        names = dict(zip(defs["code"], defs["name"])) if not defs.empty else {}
        pairs = [(names.get(v, v), i) for _, e in sub.iterrows() for v in (e["affected_variables"] or []) for i in (e["affected_industries"] or [])]
        if pairs:
            m = pd.DataFrame(pairs, columns=["變項", "產業"]).value_counts().unstack(fill_value=0)
            fig = go.Figure(go.Heatmap(z=m.values, x=m.columns, y=m.index, colorscale="Blues",
                                       hovertemplate="%{y} × %{x}：%{z} 次<extra></extra>"))
            fig = ui.base_layout(fig, max(260, 28 * len(m.index)))
            fig.update_layout(showlegend=False, hovermode="closest")
            st.plotly_chart(fig, width="stretch")
            st.caption("同一個事件同時被 AI 標示「影響某變項」與「影響某產業」時記一次；只代表 AI 推論的關聯。")

# ─── 2. 事前判斷 vs 實際 ───
with t2:
    if pr.empty:
        ui.empty_state("還沒有事前判斷。")
    else:
        done = pr[pr["result"].isin(["命中", "未命中"]) & pr["is_ex_ante"]] if "result" in pr else pd.DataFrame()

        def rate(df, kind, big=False):
            d = df[df["kind"] == kind]
            if big:
                d = d[d["abs_grade"] >= 3]
            return (d["result"] == "命中").sum(), len(d)

        k = st.columns(4)
        for i, (label, kind, big) in enumerate([("AI 方向命中率", "ai", False), ("對照規則命中率", "baseline", False),
                                               ("AI（明顯以上波動日）", "ai", True), ("對照規則（明顯以上波動日）", "baseline", True)]):
            h, n = rate(done, kind, big) if not done.empty else (0, 0)
            k[i].metric(label, "—" if not n else f"{h / n:.0%}", f"{h}/{n} 筆" if n else "尚無樣本", delta_color="off")
        st.caption("只計算在開盤前寫入的事前判斷。對照規則＝費城半導體指數前一晚漲就猜漲、跌就猜跌。"
                   "樣本少時命中率波動很大，同一天的判斷也都受同一個大盤走勢影響，至少累積數個月再解讀。")

        if not done.empty:
            curve = []
            for kind, g in done.sort_values("target_trading_day").groupby("kind"):
                g = g.assign(hit=(g["result"] == "命中").astype(int))
                g["rate"] = g["hit"].cumsum().to_numpy() / np.arange(1, len(g) + 1) * 100
                curve.append((kind, g))
            fig = go.Figure()
            for kind, g in curve:
                fig.add_trace(go.Scatter(x=g["target_trading_day"], y=g["rate"], mode="lines+markers",
                                         name="AI" if kind == "ai" else "對照規則",
                                         line=dict(width=2, color=ui.ACCENT if kind == "ai" else "#eb6834")))
            fig.add_hline(y=50, line_dash="dot", line_color=ui.MUTED, annotation_text="50%")
            fig = ui.base_layout(fig, 280, "累計方向命中率（%）")
            fig.update_yaxes(range=[0, 100], ticksuffix="%")
            st.plotly_chart(fig, width="stretch")

        st.markdown("#### 每一筆判斷")
        view = pr.sort_values(["target_trading_day", "kind"], ascending=[False, True])
        table = pd.DataFrame({
            "目標交易日": view["target_trading_day"].dt.strftime("%Y-%m-%d"),
            "判斷者": view["kind"].map({"ai": "AI", "baseline": "對照規則"}),
            "預測方向": view["direction"], "信心": view["confidence"].fillna("—"),
            "寫入時間": view["created_at"].dt.strftime("%m/%d %H:%M"),
            "事前": view["is_ex_ante"].map({True: "是", False: "否"}),
            "實際漲跌幅": view.get("actual_change_pct", pd.Series(dtype=float)).map(lambda v: "—" if not ui.is_num(v) else f"{v:+.2f}%"),
            "幅度等級": view.get("abs_grade_label", pd.Series(dtype=str)).fillna("—"),
            "相對波動": view.get("rel_grade_label", pd.Series(dtype=str)).fillna("—"),
            "結果": view.get("result", pd.Series(dtype=str)).fillna("待評估"),
        })
        st.dataframe(table, hide_index=True, width="stretch")

        ai = view[view["kind"] == "ai"]
        if not ai.empty:
            pick = st.selectbox("看 AI 判斷的理由與傳導路徑", ai["id"].tolist(),
                                format_func=lambda i: f"{ai.set_index('id').loc[i, 'target_trading_day']:%Y-%m-%d}｜{ai.set_index('id').loc[i, 'direction']}")
            p = ai.set_index("id").loc[pick]
            st.markdown(f"**理由**：{p['rationale']}")
            st.markdown("**主要因素**")
            for d in p["drivers"] or []:
                st.markdown(f"- {d.get('source')}｜{d.get('effect')}｜{d.get('reason')}")
            st.markdown("**傳導路徑**")
            for path in p["pathways"] or []:
                st.markdown("- " + " → ".join(path))
            st.markdown("**反向因素與資料不足**")
            for x in p["counterpoints"] or []:
                st.markdown(f"- {x}")
            st.caption(f"模型：{p['model'] or '—'}｜提示詞版本：{p['prompt_version']}")

# ─── 3. 事件前後 ───
with t3:
    if ev.empty or tx.empty:
        ui.empty_state("需要事件與加權指數資料。")
    else:
        pick = st.selectbox("選擇事件", ev["id"].tolist(),
                            format_func=lambda i: f"{ev.set_index('id').loc[i, 'analysis_date']:%m/%d}｜{ev.set_index('id').loc[i, 'name']}")
        e = ev.set_index("id").loc[pick]
        anchor = pd.Timestamp(e["analysis_date"])
        series = tx.set_index("trade_date")["close"]
        after = series[series.index >= anchor]
        if after.empty:
            ui.empty_state("事件之後還沒有交易日資料。")
        else:
            t0 = after.index[0]
            pos = series.index.get_loc(t0)
            window = series.iloc[max(0, pos - 10): pos + 11]
            base = series.iloc[pos - 1] if pos > 0 else series.iloc[pos]
            norm = (window / base - 1) * 100
            offsets = [series.index.get_loc(d) - pos for d in window.index]
            fig = go.Figure(go.Scatter(x=offsets, y=norm.values, mode="lines+markers", line=dict(color=ui.ACCENT, width=2),
                                       text=[d.strftime("%Y-%m-%d") for d in window.index],
                                       hovertemplate="T%{x:+d}（%{text}）：%{y:+.2f}%<extra></extra>", name="加權指數"))
            fig.add_vline(x=0, line_dash="dot", line_color="#eb6834", annotation_text="事件後第一個交易日")
            fig = ui.base_layout(fig, 300, "加權指數相對事件前一交易日收盤的累計變動（%）")
            fig.update_xaxes(title="交易日（T＝事件後第一個交易日）", dtick=1)
            fig.update_yaxes(ticksuffix="%")
            st.plotly_chart(fig, width="stretch")
            rows = []
            for lag in (0, 1, 5):
                if pos + lag < len(series):
                    rows.append({"區間": f"T 到 T+{lag}" if lag else "T 當日",
                                 "累計漲跌幅": f"{(series.iloc[pos + lag] / base - 1) * 100:+.2f}%"})
            st.dataframe(pd.DataFrame(rows), hide_index=True)
            st.caption("同一段期間通常還有其他事件，這裡只呈現同期變化，不能據此認定是這個事件造成的。")

# ─── 4. 歷史事件比較 ───
with t4:
    all_ev = data.events(date.today() - timedelta(days=3650))
    if all_ev.empty or tx.empty:
        ui.empty_state("需要事件與加權指數資料。")
    else:
        typ = st.selectbox("事件類型", sorted(all_ev["event_type"].unique()))
        sub = all_ev[(all_ev["event_type"] == typ) & (all_ev["importance"] >= 3)].copy()
        series = tx.set_index("trade_date")["close"]
        out = []
        for _, e in sub.iterrows():
            after = series[series.index >= pd.Timestamp(e["analysis_date"])]
            if after.empty:
                continue
            pos = series.index.get_loc(after.index[0])
            base = series.iloc[pos - 1] if pos > 0 else None
            if base is None:
                continue
            t1v = (series.iloc[pos] / base - 1) * 100
            t5v = (series.iloc[min(pos + 4, len(series) - 1)] / base - 1) * 100 if pos + 4 < len(series) else None
            out.append({"日期": e["analysis_date"].strftime("%Y-%m-%d"), "事件": e["name"], "重要程度": e["importance"],
                        "AI 方向": e["direction"], "T 當日": t1v, "T 到 T+4（5 個交易日）": t5v})
        if not out:
            ui.empty_state("這個類型還沒有足夠的事件。")
        else:
            df = pd.DataFrame(out)
            st.dataframe(df.style.format({"T 當日": "{:+.2f}%", "T 到 T+4（5 個交易日）": lambda v: "—" if pd.isna(v) else f"{v:+.2f}%"}),
                         hide_index=True, width="stretch")
            st.caption(f"共 {len(df)} 則（重要程度 3 以上）。T 當日平均 {df['T 當日'].mean():+.2f}%。"
                       "樣本少時平均值很不穩定；不同事件的背景也不同，請當作描述性統計。")

# ─── 5. 變項與大盤長期走勢 ───
with t5:
    defs = data.variables()
    if defs.empty or tx.empty:
        ui.empty_state("需要變項與加權指數資料。")
    else:
        code = st.selectbox("比較的變項", defs["code"].tolist(),
                            format_func=lambda c: defs.set_index("code").loc[c, "name"], index=list(defs["code"]).index("US10Y") if "US10Y" in list(defs["code"]) else 0)
        years = st.radio("期間", ["1 年", "3 年"], horizontal=True)
        since = date.today() - timedelta(days=366 if years == "1 年" else 1100)
        vs = data.variable_series(code, since)
        tl = data.index_series("TAIEX", since)
        name = defs.set_index("code").loc[code, "name"]
        st.plotly_chart(ui.line_chart(tl, "trade_date", "close", "加權指數", 240, "加權指數（點）"), width="stretch")
        st.plotly_chart(ui.line_chart(vs, "obs_date", "value", name, 240, name), width="stretch")
        if len(vs) > 30 and len(tl) > 30:
            a = tl.set_index("trade_date")["close"].pct_change()
            b = vs.set_index("obs_date")["value"].pct_change()
            joined = pd.concat([a, b], axis=1, join="inner").dropna()
            if len(joined) > 30:
                corr = joined.corr().iloc[0, 1]
                st.metric("同一天變動率的相關係數", f"{corr:+.2f}", f"樣本 {len(joined)} 天", delta_color="off")
                st.caption("相關係數介於 −1 到 +1，只描述兩者是否同向變動，不代表因果；美股與台股收盤時間不同，同一天的數據並非同時發生。")
