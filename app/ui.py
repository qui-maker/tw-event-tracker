"""網站共用的格式、顏色與圖表元件。

台股慣例：上漲用紅色、下跌用綠色。顏色之外一律搭配 ▲▼ 符號與正負號，不只靠顏色辨識。
"""
from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

UP, DOWN, FLAT = "#d1343a", "#13894a", "#7a8089"
INK, MUTED, GRID = "#18202b", "#6b7380", "#e6e8ec"
ACCENT = "#1f4e8c"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"]

CSS = """
<style>
.block-container {padding-top: 1.2rem; max-width: 1280px;}
h1, h2, h3 {letter-spacing: .01em; text-wrap: balance;}
.tag {display:inline-block; padding:1px 8px; border-radius:10px; font-size:.78rem; margin:0 4px 4px 0;
      border:1px solid rgba(0,0,0,.12); background: rgba(31,78,140,.07); color: inherit; white-space: nowrap;}
.tag.up {background: rgba(209,52,58,.10); border-color: rgba(209,52,58,.35);}
.tag.down {background: rgba(19,137,74,.10); border-color: rgba(19,137,74,.35);}
.tag.warn {background: rgba(237,161,0,.14); border-color: rgba(237,161,0,.45);}
.src {color: #6b7380; font-size: .78rem;}
.card {border:1px solid rgba(0,0,0,.10); border-radius:10px; padding:12px 14px; margin-bottom:10px;}
.kfact {border-left:3px solid #1f4e8c; padding-left:8px; margin:3px 0;}
.kinfer {border-left:3px solid #6250d6; padding-left:8px; margin:3px 0;}
.kunconf {border-left:3px solid #eda100; padding-left:8px; margin:3px 0;}
[data-testid="stMetricValue"] {font-variant-numeric: tabular-nums;}
</style>
"""


def setup_page(title: str, caption: str | None = None):
    st.markdown(CSS, unsafe_allow_html=True)
    st.title(title)
    if caption:
        st.caption(caption)


def is_num(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


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


def tag(text: str, kind: str = "") -> str:
    return f'<span class="tag {kind}">{text}</span>'


def direction_tag(direction: str | None) -> str:
    kind = {"正面": "up", "上漲": "up", "負面": "down", "下跌": "down", "不確定": "warn"}.get(direction or "", "")
    return tag(direction or "未標示", kind)


def stars(n) -> str:
    n = int(n) if is_num(n) else 0
    return "●" * n + "○" * (5 - n)


def source_line(source: str | None, when=None, unofficial: bool = False) -> str:
    parts = [f"來源：{source or '—'}"]
    if when is not None and not (isinstance(when, float)):
        parts.append(f"日期：{pd.to_datetime(when).strftime('%Y-%m-%d')}")
    if unofficial:
        parts.append("非官方資料，僅供參考")
    return f'<div class="src">{"｜".join(parts)}</div>'


def sources_of(df: pd.DataFrame, col: str = "source") -> str:
    """列出資料表中實際出現的來源（照資料庫紀錄，不寫死）。"""
    if df is None or df.empty or col not in df.columns:
        return "—"
    return "、".join(dict.fromkeys(str(x) for x in df[col].dropna()))


def var_metric(label: str, v, help: str | None = None):
    """經濟變項的指標卡：單位是 % 的（利率、殖利率、失業率）變化用「個百分點」，其他用變化率。"""
    if str(v.get("unit") or "").startswith("%"):
        d = v.get("change")
        metric(label, v["value"], help=help, delta_text=None if not is_num(d) else f"{d:+.2f} 個百分點")
    else:
        metric(label, v["value"], None, v.get("change_pct"), help=help)


def metric(label: str, value, delta=None, delta_pct=None, unit: str = "", digits: int = 2, help: str | None = None,
           delta_text: str | None = None):
    """台股慣例：漲紅跌綠（Streamlit 的 inverse 模式剛好是正值紅、負值綠）。"""
    if delta_text is not None:
        st.metric(label, fmt(value, digits) + (f" {unit}" if unit and is_num(value) else ""), delta_text,
                  delta_color="inverse", help=help)
        return
    delta_text = None
    if is_num(delta) or is_num(delta_pct):
        delta_text = " ".join(x for x in [fmt(delta, digits, signed=True) if is_num(delta) else "",
                                          f"({fmt(delta_pct, 2, signed=True)}%)" if is_num(delta_pct) else ""] if x)
    st.metric(label, fmt(value, digits) + (f" {unit}" if unit and is_num(value) else ""), delta_text,
              delta_color="inverse", help=help)


def base_layout(fig: go.Figure, height: int = 320, title: str | None = None) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=40 if title else 10, b=10),
        title=dict(text=title, font=dict(size=14)) if title else None,
        font=dict(family="system-ui, -apple-system, 'Noto Sans TC', 'PingFang TC', sans-serif", size=12),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0), showlegend=True,
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


def line_chart(df: pd.DataFrame, x: str, y: str, name: str, height: int = 320, title: str | None = None,
               markers: pd.DataFrame | None = None, y_title: str | None = None) -> go.Figure:
    """單一序列折線圖，最後一點加強標示；markers（x、y、text）用來標出事件。"""
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df[x], y=df[y], mode="lines", name=name, line=dict(color=ACCENT, width=2),
                             fill="tozeroy" if False else None))
    if not df.empty:
        fig.add_trace(go.Scatter(x=[df[x].iloc[-1]], y=[df[y].iloc[-1]], mode="markers", name="最新",
                                 marker=dict(color=ACCENT, size=8), showlegend=False,
                                 hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.2f}<extra>最新</extra>"))
    if markers is not None and not markers.empty:
        fig.add_trace(go.Scatter(x=markers["x"], y=markers["y"], mode="markers", name="重大事件",
                                 marker=dict(symbol="diamond", size=10, color="#eb6834", line=dict(color="white", width=1.5)),
                                 text=markers["text"], hovertemplate="%{x|%Y-%m-%d}<br>%{text}<extra>事件</extra>"))
    base_layout(fig, height, title)
    if y_title:
        fig.update_yaxes(title=y_title)
    return fig


def change_bars(df: pd.DataFrame, x: str, y: str, name: str, height: int = 220, title: str | None = None,
                horizontal: bool = False) -> go.Figure:
    colors = [color(v) for v in df[y]]
    if horizontal:
        fig = go.Figure(go.Bar(y=df[x], x=df[y], orientation="h", marker_color=colors, name=name,
                               text=[f"{arrow(v)} {fmt(v, 2, signed=True)}%" for v in df[y]], textposition="outside",
                               hovertemplate="%{y}：%{x:+.2f}%<extra></extra>"))
        fig = base_layout(fig, height, title)
        fig.update_layout(hovermode="closest", showlegend=False)
        fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)")
        fig.update_xaxes(gridcolor=GRID, ticksuffix="%")
        return fig
    fig = go.Figure(go.Bar(x=df[x], y=df[y], marker_color=colors, name=name,
                           hovertemplate="%{x|%Y-%m-%d}：%{y:+.2f}%<extra></extra>"))
    fig = base_layout(fig, height, title)
    fig.update_layout(showlegend=False)
    fig.update_yaxes(ticksuffix="%")
    return fig


def empty_state(message: str):
    st.info(message, icon="ℹ️")


def no_backend_notice():
    st.error("網站沒有設定資料庫連線。請在 Streamlit 的 Secrets 設定 SUPABASE_URL 與 SUPABASE_ANON_KEY。")
    st.stop()
