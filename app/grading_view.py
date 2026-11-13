"""網站顯示用的漲跌分級（與排程程式使用相同規則：決策紀錄 v1）。"""
import statistics

import pandas as pd

import ui

THRESHOLDS = [0.5, 1.0, 2.0, 3.0]
NAMES = {1: ("微漲", "微跌"), 2: ("小漲", "小跌"), 3: ("明顯上漲", "明顯下跌"), 4: ("大漲", "大跌"), 5: ("暴漲", "重挫")}


def abs_label(pct) -> str:
    if not ui.is_num(pct):
        return "—"
    if pct == 0:
        return "平盤"
    g = 1 + sum(abs(pct) >= t for t in THRESHOLDS)
    return NAMES[g][0 if pct > 0 else 1]


def z_value(series: pd.Series, i: int):
    prev = [p for p in series.iloc[max(0, i - 20):i].tolist() if ui.is_num(p)]
    cur = series.iloc[i]
    if len(prev) < 20 or not ui.is_num(cur):
        return None
    sd = statistics.stdev(prev)
    return cur / sd if sd else None


def rel_label(z) -> str:
    if z is None:
        return "資料不足"
    a = abs(z)
    return "正常" if a < 1 else "偏大" if a < 2 else "異常" if a < 2.5 else "極端"


def grade_text(df: pd.DataFrame, i: int) -> str:
    pct = df["change_pct"].iloc[i]
    z = z_value(df["change_pct"], i)
    kind = "up" if ui.is_num(pct) and pct > 0 else "down" if ui.is_num(pct) and pct < 0 else ""
    ztxt = "" if z is None else f"（{z:+.1f} 個標準差）"
    return f"{ui.tag(abs_label(pct), kind)}<br><span class='src'>相對近 20 日：{rel_label(z)}{ztxt}</span>"
