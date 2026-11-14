"""網站顯示用的國際經濟變項分類（只影響畫面分組，不改資料庫）。"""

VARIABLE_GROUPS: dict[str, list[str]] = {
    "利率與債券": ["US2Y", "US10Y", "FED_RATE", "EFFR"],
    "國際股市與科技指數": ["SPX", "NASDAQ", "SOX", "TSM_ADR", "NIKKEI", "VIX"],
    "匯率與美元": ["DXY", "USDTWD", "USD_BROAD"],
    "能源與原物料": ["WTI", "BRENT", "GOLD"],
    "美國經濟數據": ["US_CPI", "US_UNRATE", "US_NFP"],
}

# 尚未蒐集、但研究上常用的指標：畫面上標示「尚未納入」，不補造數據
NOT_COLLECTED: dict[str, list[str]] = {
    "美國經濟數據": ["PCE 物價指數"],
}

PERIODS = {"1 個月": 31, "3 個月": 92, "6 個月": 183, "1 年": 366, "3 年": 1096}


def group_of(code: str) -> str:
    for g, codes in VARIABLE_GROUPS.items():
        if code in codes:
            return g
    return "其他"


def digits_for(value) -> int:
    """大數字（例如非農就業人數、股價指數）不顯示小數，其餘兩位。"""
    try:
        return 0 if abs(float(value)) >= 10000 else 2
    except (TypeError, ValueError):
        return 2
