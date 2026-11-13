"""漲跌幅分級 v1（規則說明見 docs/決策紀錄.md）。純計算，不經過 AI。"""
from __future__ import annotations

import statistics

from tracker.config import ABS_GRADE_NAMES, ABS_GRADE_THRESHOLDS, REL_GRADE_THRESHOLDS, REL_WINDOW


def direction(pct: float | None) -> str | None:
    """方向：不設中性區，任何非零變動都算上漲或下跌。"""
    if pct is None:
        return None
    if pct > 0:
        return "上漲"
    if pct < 0:
        return "下跌"
    return "平盤"


def abs_grade(pct: float | None) -> tuple[int | None, str | None]:
    """絕對幅度等級 1～5 與名稱，例如 (5, '重挫')。"""
    if pct is None:
        return None, None
    if pct == 0:
        return 0, "平盤"
    a = abs(pct)
    grade = 1 + sum(a >= t for t in ABS_GRADE_THRESHOLDS)
    up, down = ABS_GRADE_NAMES[grade]
    return grade, (up if pct > 0 else down)


def z_score(pct: float | None, previous: list[float]) -> float | None:
    """當天漲跌幅 ÷ 前 20 個交易日漲跌幅的標準差（不含當天）。資料不足回傳 None。"""
    prev = [p for p in previous if p is not None][-REL_WINDOW:]
    if pct is None or len(prev) < REL_WINDOW:
        return None
    sd = statistics.stdev(prev)
    return round(pct / sd, 3) if sd > 0 else None


def rel_label(z: float | None) -> str:
    if z is None:
        return "資料不足"
    a = abs(z)
    for limit, name in REL_GRADE_THRESHOLDS:
        if a < limit:
            return name
    return "極端"
