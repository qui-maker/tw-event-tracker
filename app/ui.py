"""網站共用的設計規範、格式與圖表元件。

設計規範（所有頁面共用）：
- 版面：白色底；區塊用「區塊標題」分隔，資訊卡用淺灰底或細邊框，不讓每個區塊都變成白色方框。
- 顏色：深藍（ACCENT）是主要資訊色；台股慣例上漲紅、下跌綠、持平灰。顏色之外一律搭配 ▲▼■ 與正負號。
- 字級：頁面標題 1.75rem、區塊標題 1.2rem、卡片標題 1.05rem、內文 0.95rem、註記 0.8rem。
- 數字：千分位、固定小數位、等寬數字；利率類變化用「個百分點」。
- 每個數字與圖表都標出資料來源與資料日期。
"""
from __future__ import annotations

import html
import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ─── 顏色 ───
UP, DOWN, FLAT = "#d1343a", "#13894a", "#7a8089"
INK, MUTED, GRID = "#18202b", "#5f6b7a", "#e6e8ec"
BORDER, SURFACE = "#e3e7ed", "#f6f8fa"
ACCENT = "#1f4e8c"
WARN = "#b7791f"
# 類別色依固定順序使用（參考 dataviz 驗證過的色盤）；比較圖最多 3 條線（前三色兩兩可區分）
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"]
FONT = "system-ui, -apple-system, 'PingFang TC', 'Noto Sans TC', 'Microsoft JhengHei', sans-serif"

CSS = f"""
<style>
.block-container {{padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1240px;}}
html, body, .stApp, .stMarkdown, .stText, button, input, textarea, select {{font-family: {FONT};}}
[data-testid="stIconMaterial"], .material-symbols-rounded {{font-family: "Material Symbols Rounded" !important;}}
h1 {{font-size: 1.75rem !important; font-weight: 700 !important; letter-spacing: .01em;}}
h3 {{font-size: 1.2rem !important; font-weight: 700 !important; color: {INK};}}
p, li {{font-size: .95rem; line-height: 1.65;}}
[data-testid="stMetricValue"] {{font-variant-numeric: tabular-nums;}}

/* 區塊標題 */
.sec {{margin: 2.2rem 0 .9rem; padding-left: 12px; border-left: 4px solid {ACCENT};}}
.sec .t {{font-size: 1.2rem; font-weight: 700; color: {INK}; line-height: 1.35;}}
.sec .s {{font-size: .85rem; color: {MUTED}; margin-top: 2px;}}
.subhead {{font-size: 1.05rem; font-weight: 700; color: {INK}; margin: 1.6rem 0 .5rem;}}
.overline + .subhead {{margin-top: .1rem;}}
.gap-after {{height: 18px;}}
.overline {{font-size: .75rem; font-weight: 600; letter-spacing: .06em; color: {MUTED}; text-transform: uppercase;}}

/* 標籤 */
.tag {{display:inline-block; padding:2px 9px; border-radius:999px; font-size:.75rem; line-height:1.5; margin:0 4px 4px 0;
      border:1px solid {BORDER}; background:#fff; color:{INK}; white-space:nowrap; vertical-align:middle;}}
.tag.up {{background: rgba(209,52,58,.08); border-color: rgba(209,52,58,.35); color:#a3262b;}}
.tag.down {{background: rgba(19,137,74,.08); border-color: rgba(19,137,74,.35); color:#0e6b3a;}}
.tag.warn {{background: rgba(237,161,0,.10); border-color: rgba(183,121,31,.40); color:#8a5a12;}}
.tag.flat {{background: {SURFACE}; color:{MUTED};}}
.tag.imp {{background: rgba(31,78,140,.08); border-color: rgba(31,78,140,.30); color:{ACCENT}; font-weight:600;}}
.tag.imp5, .tag.imp4 {{background:{ACCENT}; border-color:{ACCENT}; color:#fff;}}
.lbl {{display:inline-block; font-size:.72rem; font-weight:700; padding:0 6px; border-radius:4px; margin-right:6px;
      vertical-align:1px;}}
.lbl.fact {{background: rgba(31,78,140,.10); color:{ACCENT};}}
.lbl.infer {{background: rgba(98,80,214,.10); color:#4b3bb5;}}
.lbl.unconf {{background: rgba(237,161,0,.14); color:#8a5a12;}}
.lbl.gap {{background: {SURFACE}; color:{MUTED}; border:1px solid {BORDER};}}
.ind {{display:flex; justify-content:space-between; align-items:baseline; gap:8px;}}
.ind b {{font-size:.98rem;}}

/* 註記與來源 */
.src {{color:{MUTED}; font-size:.8rem; line-height:1.5;}}
.src a {{color:{MUTED};}}
.muted {{color:{MUTED};}}

/* 指標卡（CSS grid：寬螢幕多欄、手機自動變兩欄或一欄） */
.kpis {{display:grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap:10px; margin:.2rem 0 .4rem;}}
.kpi {{background:{SURFACE}; border-radius:10px; padding:12px 14px; min-width:0;}}
.kpi .l {{font-size:.8rem; color:{MUTED}; margin-bottom:2px;}}
.kpi .v {{font-size:1.45rem; font-weight:700; color:{INK}; font-variant-numeric: tabular-nums; line-height:1.3;
         white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}}
.kpi .v small {{font-size:.8rem; font-weight:500; color:{MUTED}; margin-left:3px;}}
.kpi .d {{font-size:.85rem; font-weight:600; font-variant-numeric: tabular-nums;}}
.kpi .n {{font-size:.75rem; color:{MUTED}; margin-top:4px; line-height:1.4;}}

/* 卡片：st.container(border=True, key="card-...") 會帶 st-key-card-... 這個 class */
[class*="st-key-card"] {{border-color:{BORDER} !important; border-radius:12px !important; background:#fff;}}
[class*="st-key-panel"] {{background:{SURFACE}; border:none !important; border-radius:12px !important; padding:14px 18px;}}
.card-title {{font-size:1.05rem; font-weight:700; color:{INK}; line-height:1.45; margin:2px 0 6px;}}
.card-meta {{font-size:.8rem; color:{MUTED}; margin:2px 0 8px;}}
.card-body {{font-size:.93rem; line-height:1.65; color:{INK};}}
.kv {{font-size:.85rem; line-height:1.6; margin:6px 0 0;}}
.kv b {{color:{MUTED}; font-weight:600; margin-right:4px;}}
.rank {{display:inline-flex; align-items:center; justify-content:center; width:26px; height:26px; border-radius:50%;
       background:{ACCENT}; color:#fff; font-weight:700; font-size:.85rem; margin-right:8px; vertical-align:2px;}}

/* 清單（主要因素、不確定因素） */
.items {{margin:0; padding:0; list-style:none;}}
.items li {{padding:7px 0; border-bottom:1px solid {BORDER}; font-size:.92rem; line-height:1.6;}}
.items li:last-child {{border-bottom:none;}}

/* 圖表標頭 */
.chart-h {{display:flex; flex-wrap:wrap; align-items:baseline; gap:4px 10px; margin:.2rem 0 .1rem;}}
.chart-h .t {{font-size:.98rem; font-weight:700; color:{INK};}}
.chart-h .v {{font-size:.95rem; font-weight:600; font-variant-numeric: tabular-nums;}}
.chart-h .u {{font-size:.8rem; color:{MUTED};}}

/* 舊版樣式（其他頁面仍在使用） */
.card {{border:1px solid {BORDER}; border-radius:12px; padding:14px 16px; margin-bottom:12px; background:#fff;}}
.kfact {{border-left:3px solid {ACCENT}; padding-left:8px; margin:4px 0;}}
.kinfer {{border-left:3px solid #6250d6; padding-left:8px; margin:4px 0;}}
.kunconf {{border-left:3px solid #eda100; padding-left:8px; margin:4px 0;}}

@media (max-width: 640px) {{
  .block-container {{padding-left: .9rem; padding-right: .9rem;}}
  h1 {{font-size: 1.45rem !important;}}
  .kpis {{grid-template-columns: repeat(2, minmax(0, 1fr));}}
  .kpi .v {{font-size: 1.2rem;}}
  .sec {{margin-top: 1.6rem;}}
}}
</style>
"""


def setup_page(title: str, caption: str | None = None):
    st.markdown(CSS, unsafe_allow_html=True)
    st.title(title)
    if caption:
        st.caption(caption)


# ─── 數字格式 ───
def is_num(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v)) and not (v is pd.NaT)


def fmt(v, digits: int = 2, signed: bool = False, suffix: str = "") -> str:
    if not is_num(v):
        return "—"
    return (f"{float(v):+,.{digits}f}" if signed else f"{float(v):,.{digits}f}") + suffix


def arrow(v) -> str:
    if not is_num(v) or float(v) == 0:
        return "■"
    return "▲" if float(v) > 0 else "▼"


def color(v) -> str:
    if not is_num(v) or float(v) == 0:
        return FLAT
    return UP if float(v) > 0 else DOWN


def esc(text) -> str:
    return html.escape(str(text)) if text is not None else ""


def date_str(d, fmt_: str = "%Y-%m-%d") -> str:
    if d is None or (isinstance(d, float) and math.isnan(d)) or d is pd.NaT:
        return "不明"
    try:
        return pd.to_datetime(d).strftime(fmt_)
    except (ValueError, TypeError):
        return "不明"


def change_html(delta=None, pct=None, digits: int = 2, unit_points: str | None = None) -> str:
    """漲跌文字：▲ +583.25（+1.35%），上漲紅、下跌綠。unit_points 用在利率類（例如「個百分點」）。"""
    ref = pct if is_num(pct) else delta
    if not is_num(ref):
        return f'<span style="color:{FLAT}">—</span>'
    parts = []
    if is_num(delta):
        parts.append(fmt(delta, digits, signed=True) + (f" {unit_points}" if unit_points else ""))
    if is_num(pct):
        parts.append(f"（{fmt(pct, 2, signed=True)}%）" if parts else f"{fmt(pct, 2, signed=True)}%")
    return f'<span style="color:{color(ref)}">{arrow(ref)} {"".join(parts)}</span>'


# ─── 標籤 ───
def tag(text: str, kind: str = "") -> str:
    return f'<span class="tag {kind}">{esc(text)}</span>'


def direction_tag(direction: str | None) -> str:
    kind = {"正面": "up", "上漲": "up", "負面": "down", "下跌": "down", "不確定": "warn", "中性": "flat"}.get(direction or "", "")
    prefix = {"正面": "▲ ", "上漲": "▲ ", "負面": "▼ ", "下跌": "▼ ", "中性": "■ "}.get(direction or "", "")
    return tag(f"{prefix}{direction or '未標示'}", kind)


def importance_tag(n) -> str:
    n = int(n) if is_num(n) else 0
    return f'<span class="tag imp imp{n}">重要程度 {n}／5</span>'


def stars(n) -> str:
    n = int(n) if is_num(n) else 0
    return "●" * n + "○" * (5 - n)


def labelled(text: str) -> str:
    """把 AI 文字開頭的【事實】【推論】【未確認】換成統一的小標籤。"""
    t = esc(text or "")
    for key, cls in (("【事實】", "fact"), ("【推論】", "infer"), ("【未確認】", "unconf"), ("【資料不足】", "gap")):
        if t.startswith(key):
            return f'<span class="lbl {cls}">{key.strip("【】")}</span>{t[len(key):]}'
    return t


# ─── 版面元件 ───
def section(title: str, subtitle: str | None = None):
    st.markdown(f'<div class="sec"><div class="t">{esc(title)}</div>'
                + (f'<div class="s">{subtitle}</div>' if subtitle else "") + "</div>", unsafe_allow_html=True)


def subhead(text: str):
    st.markdown(f'<div class="subhead">{esc(text)}</div>', unsafe_allow_html=True)


def kpi(label: str, value, unit: str = "", digits: int = 2, delta=None, pct=None, note: str = "",
        unit_points: str | None = None, value_text: str | None = None) -> str:
    v = value_text if value_text is not None else fmt(value, digits)
    d = "" if (delta is None and pct is None) else f'<div class="d">{change_html(delta, pct, digits, unit_points)}</div>'
    u = f"<small>{esc(unit)}</small>" if unit and (value_text is not None or is_num(value)) else ""
    return (f'<div class="kpi"><div class="l">{esc(label)}</div><div class="v">{v}{u}</div>{d}'
            + (f'<div class="n">{note}</div>' if note else "") + "</div>")


def kpi_grid(items: list[str]):
    st.markdown(f'<div class="kpis">{"".join(items)}</div>', unsafe_allow_html=True)


def source_line(source: str | None, when=None, unofficial: bool = False) -> str:
    parts = [f"來源：{esc(source) if source else '—'}"]
    if when is not None and not (isinstance(when, float)):
        parts.append(f"資料日期：{date_str(when)}")
    if unofficial:
        parts.append("非官方資料，僅供參考")
    return f'<div class="src">{"｜".join(parts)}</div>'


def sources_of(df: pd.DataFrame, col: str = "source") -> str:
    """列出資料表中實際出現的來源（照資料庫紀錄，不寫死）。"""
    if df is None or df.empty or col not in df.columns:
        return "—"
    return "、".join(dict.fromkeys(str(x) for x in df[col].dropna()))


def chart_header(title: str, value_html: str = "", unit: str = ""):
    st.markdown(f'<div class="chart-h"><span class="t">{esc(title)}</span>'
                + (f'<span class="v">{value_html}</span>' if value_html else "")
                + (f'<span class="u">{esc(unit)}</span>' if unit else "") + "</div>", unsafe_allow_html=True)


def var_metric(label: str, v, help: str | None = None):
    """經濟變項的指標卡：單位是 % 的（利率、殖利率、失業率）變化用「個百分點」，其他用變化率。"""
    if str(v.get("unit") or "").startswith("%"):
        d = v.get("change")
        metric(label, v["value"], help=help, delta_text=None if not is_num(d) else f"{d:+.2f} 個百分點")
    else:
        metric(label, v["value"], None, v.get("change_pct"), help=help)


def var_change_html(v) -> str:
    if str(v.get("unit") or "").startswith("%"):
        return change_html(v.get("change"), None, 2, "個百分點")
    return change_html(None, v.get("change_pct"))


def metric(label: str, value, delta=None, delta_pct=None, unit: str = "", digits: int = 2, help: str | None = None,
           delta_text: str | None = None):
    """台股慣例：漲紅跌綠（Streamlit 的 inverse 模式剛好是正值紅、負值綠）。"""
    if delta_text is None and (is_num(delta) or is_num(delta_pct)):
        delta_text = " ".join(x for x in [fmt(delta, digits, signed=True) if is_num(delta) else "",
                                          f"({fmt(delta_pct, 2, signed=True)}%)" if is_num(delta_pct) else ""] if x)
    st.metric(label, fmt(value, digits) + (f" {unit}" if unit and is_num(value) else ""), delta_text,
              delta_color="inverse", help=help)


# ─── 圖表 ───
DATE_TICKS = [  # 依可見範圍自動切換日期格式，避免 X 軸文字過密
    dict(dtickrange=[None, 86400000 * 20], value="%m/%d"),
    dict(dtickrange=[86400000 * 20, 86400000 * 200], value="%Y/%m"),
    dict(dtickrange=[86400000 * 200, None], value="%Y"),
]


def base_layout(fig: go.Figure, height: int = 320, title: str | None = None) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=8, r=12, t=36 if title else 8, b=8),
        title=dict(text=title, font=dict(size=14, color=INK), x=0, xanchor="left", y=0.98, yanchor="top") if title else None,
        font=dict(family=FONT, size=12, color=INK),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", hovermode="x unified",
        hoverlabel=dict(font=dict(family=FONT, size=12), bgcolor="white", bordercolor=BORDER),
        legend=dict(orientation="h", yanchor="top", y=-0.12, x=0, font=dict(size=11)), showlegend=True,
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID, ticks="outside", tickcolor=GRID, nticks=7)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, tickformat=",~r", nticks=6)
    return fig


def _date_axis(fig: go.Figure):
    fig.update_xaxes(type="date", tickformatstops=DATE_TICKS, hoverformat="%Y-%m-%d")


def line_chart(df: pd.DataFrame, x: str, y: str, name: str, height: int = 320, title: str | None = None,
               markers: pd.DataFrame | None = None, y_title: str | None = None, unit: str = "",
               digits: int = 2) -> go.Figure:
    """單一序列折線圖，最後一點加強標示；markers（x、y、text）用來標出事件。"""
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df[x], y=df[y], mode="lines", name=name, line=dict(color=ACCENT, width=2),
                             hovertemplate=f"%{{y:,.{digits}f}} {unit}<extra>{esc(name)}</extra>"))
    if not df.empty:
        fig.add_trace(go.Scatter(x=[df[x].iloc[-1]], y=[df[y].iloc[-1]], mode="markers", name="最新",
                                 marker=dict(color=ACCENT, size=8, line=dict(color="white", width=2)), showlegend=False,
                                 hoverinfo="skip"))
    has_markers = markers is not None and not markers.empty
    if has_markers:
        fig.add_trace(go.Scatter(x=markers["x"], y=markers["y"], mode="markers", name="重大事件（重要程度 4 以上）",
                                 marker=dict(symbol="diamond", size=10, color="#eb6834", line=dict(color="white", width=1.5)),
                                 text=markers["text"], hovertemplate="%{text}<extra>事件</extra>"))
    base_layout(fig, height, title)
    fig.update_layout(showlegend=has_markers)
    _date_axis(fig)
    if y_title or unit:
        fig.update_yaxes(title=dict(text=y_title or unit, font=dict(size=11, color=MUTED)))
    return fig


def change_bars(df: pd.DataFrame, x: str, y: str, name: str, height: int = 220, title: str | None = None,
                horizontal: bool = False) -> go.Figure:
    colors = [color(v) for v in df[y]]
    if horizontal:
        return sector_bars(df, x, y, height, title)
    fig = go.Figure(go.Bar(x=df[x], y=df[y], marker_color=colors, name=name, marker_line_width=0,
                           hovertemplate="%{x|%Y-%m-%d}：%{y:+.2f}%<extra></extra>"))
    fig = base_layout(fig, height, title)
    fig.update_layout(showlegend=False, bargap=0.25)
    fig.update_yaxes(ticksuffix="%", tickformat="+.0f", zeroline=True, zerolinecolor="#c9ced6")
    _date_axis(fig)
    return fig


def sector_bars(df: pd.DataFrame, label: str, value: str, height: int | None = None, title: str | None = None) -> go.Figure:
    """產業排行：水平長條、由高到低、標示 ▲▼ 與漲跌幅。"""
    d = df.sort_values(value, ascending=False)
    vals = d[value].astype(float)
    span = max(abs(vals.min()), abs(vals.max()), 0.5)
    fig = go.Figure(go.Bar(
        y=d[label], x=vals, orientation="h", marker_color=[color(v) for v in vals], marker_line_width=0,
        text=[f"{arrow(v)} {fmt(v, 2, signed=True)}%" for v in vals], textposition="outside", cliponaxis=False,
        textfont=dict(size=11, color=INK), hovertemplate="%{y}：%{x:+.2f}%<extra></extra>"))
    fig = base_layout(fig, height or max(260, 26 * len(d) + 60), title)
    fig.update_layout(hovermode="closest", showlegend=False, bargap=0.28, margin=dict(l=8, r=40, t=36 if title else 8, b=8))
    fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)", tickfont=dict(size=12), automargin=True,
                     tickmode="array", tickvals=list(d[label]), ticktext=list(d[label]))  # 每個產業名稱都要顯示
    fig.update_xaxes(gridcolor=GRID, ticksuffix="%", tickformat="+.1f", zeroline=True, zerolinecolor="#9aa3ae",
                     range=[-span * 1.35 if vals.min() < 0 else -span * 0.08, span * 1.35 if vals.max() > 0 else span * 0.08])
    return fig


def compare_chart(series: list[tuple[str, pd.DataFrame]], height: int = 360) -> go.Figure:
    """多個變項比較：全部換算成「期初＝100」的指數，放在同一個軸上（不同單位不能直接比）。"""
    fig = go.Figure()
    for i, (name, s) in enumerate(series):
        if s.empty:
            continue
        base = s["value"].iloc[0]
        idx = s["value"] / base * 100 if base else s["value"] * float("nan")
        c = SERIES[i % len(SERIES)]
        fig.add_trace(go.Scatter(x=s["obs_date"], y=idx, mode="lines", name=name, line=dict(color=c, width=2),
                                 customdata=s["value"],
                                 hovertemplate="%{y:.1f}（原始值 %{customdata:,.2f}）<extra>" + esc(name) + "</extra>"))
        fig.add_annotation(x=s["obs_date"].iloc[-1], y=idx.iloc[-1], text=f"{idx.iloc[-1]:.1f}", showarrow=False,
                           xanchor="left", xshift=6, font=dict(size=11, color=c))
    fig.add_hline(y=100, line_dash="dot", line_color="#9aa3ae", line_width=1)
    base_layout(fig, height)
    _date_axis(fig)
    fig.update_yaxes(title=dict(text="期初＝100", font=dict(size=11, color=MUTED)), tickformat=".0f")
    fig.update_layout(margin=dict(l=8, r=40, t=8, b=8))
    return fig


def plot(fig: go.Figure, key: str | None = None):
    """統一的圖表輸出：關閉 Plotly 工具列中不常用的按鈕，保留滑鼠移動顯示數值。"""
    st.plotly_chart(fig, width="stretch", key=key,
                    config={"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"]})


# ─── 狀態訊息 ───
def empty_state(message: str):
    st.info(message, icon="ℹ️")


def missing(what: str = "資料") -> str:
    return f'<span class="muted">{esc(what)}尚未取得</span>'


def no_backend_notice():
    st.error("網站沒有設定資料庫連線。請在 Streamlit 的 Secrets 設定 SUPABASE_URL 與 SUPABASE_ANON_KEY。")
    st.stop()
