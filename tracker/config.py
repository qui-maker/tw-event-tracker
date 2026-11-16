"""全專案共用的設定：時區、變項清單、新聞查詢主題、指數代碼。

要新增追蹤的經濟變項，只要在 VARIABLES 加一列，下次排程就會自動開始蒐集。
"""
import re
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")

# 提示詞與評估規則的版本號（改規則時一定要改版本號，舊結果會保留）
PROMPT_VERSION = "p3"  # p2：產業只能從證交所類股清單選（11/14）；p3：加入美股與台股收盤時間順序規則（11/16）
EVAL_METHOD_VERSION = "v1"

# ─────────────────────────────────────────────
# 經濟與市場變項
#   source = "FRED"：官方資料（聖路易聯邦準備銀行）
#   source = "Yahoo"：非官方（yfinance），只當備援，網站會標示
# ─────────────────────────────────────────────
VARIABLES = [
    # code,        name,                    category,       unit,              freq, source,  series,      official
    ("FED_RATE",  "聯邦基金利率目標上限",     "利率",          "%",               "日", "FRED",  "DFEDTARU",  True),
    ("EFFR",      "有效聯邦基金利率",         "利率",          "%",               "日", "FRED",  "DFF",       True),
    ("US2Y",      "美國 2 年期公債殖利率",    "利率",          "%",               "日", "FRED",  "DGS2",      True),
    ("US10Y",     "美國 10 年期公債殖利率",   "利率",          "%",               "日", "FRED",  "DGS10",     True),
    ("US_CPI",    "美國消費者物價指數",       "美國經濟數據",   "指數（1982-84=100）", "月", "FRED", "CPIAUCSL", True),
    ("US_UNRATE", "美國失業率",              "美國經濟數據",   "%",               "月", "FRED",  "UNRATE",    True),
    ("US_NFP",    "美國非農就業人數",         "美國經濟數據",   "千人",             "月", "FRED",  "PAYEMS",    True),
    ("USD_BROAD", "廣義美元指數",            "匯率",          "指數（2006-01=100）", "日", "FRED", "DTWEXBGS", True),
    ("USDTWD",    "新台幣兌美元",            "匯率",          "新台幣／美元",      "日", "FRED",  "DEXTAUS",   True),
    ("WTI",       "WTI 原油",               "原物料",        "美元／桶",          "日", "FRED",  "DCOILWTICO", True),
    ("BRENT",     "Brent 原油",             "原物料",        "美元／桶",          "日", "FRED",  "DCOILBRENTEU", True),
    ("SPX",       "S&P 500 指數",           "國際股市",       "點",               "日", "FRED",  "SP500",     True),
    ("NASDAQ",    "Nasdaq 綜合指數",         "國際股市",       "點",               "日", "FRED",  "NASDAQCOM", True),
    ("SOX",       "費城半導體指數",           "國際股市",       "點",               "日", "Yahoo", "^SOX",      False),
    ("TSM_ADR",   "台積電 ADR",              "國際股市",       "美元",             "日", "Yahoo", "TSM",       False),
    ("NIKKEI",    "日經 225 指數",           "國際股市",       "點",               "日", "Yahoo", "^N225",     False),
    ("VIX",       "VIX 波動率指數",          "國際股市",       "點",               "日", "Yahoo", "^VIX",      False),
    ("DXY",       "美元指數 DXY",            "匯率",          "點",               "日", "Yahoo", "DX-Y.NYB",  False),
    ("GOLD",      "黃金期貨",                "原物料",        "美元／盎司",        "日", "Yahoo", "GC=F",      False),
]
VARIABLE_CODES = [v[0] for v in VARIABLES]

# 早班預測時提供給 AI 參考的隔夜變項
OVERNIGHT_VARIABLES = ["SPX", "NASDAQ", "SOX", "TSM_ADR", "VIX", "US10Y", "US2Y", "DXY", "USD_BROAD", "WTI", "BRENT", "GOLD", "USDTWD"]

# ─────────────────────────────────────────────
# GDELT 新聞查詢（英文查詢；GDELT 會把 65 種語言的新聞翻譯後一起搜尋）
# ─────────────────────────────────────────────
GDELT_QUERIES = {
    "貨幣政策": '("Federal Reserve" OR "interest rates" OR "central bank" OR inflation) sourcelang:english',
    "國際貿易": '(tariff OR tariffs OR "trade war" OR "export controls" OR sanctions) sourcelang:english',
    "地緣政治": '(war OR military OR missile OR ceasefire OR "Taiwan Strait") sourcelang:english',
    "科技與半導體": '(semiconductor OR chipmaker OR TSMC OR Nvidia OR "artificial intelligence") sourcelang:english',
    "能源與原物料": '("oil prices" OR OPEC OR crude OR "natural gas") sourcelang:english',
    "主要經濟體": '("China economy" OR "European Central Bank" OR "Bank of Japan" OR yuan OR "Treasury yields") sourcelang:english',
    "台灣": '(Taiwan OR TAIEX OR "Taiwan stocks") sourcelang:english',
}
GDELT_MAX_RECORDS = 75

# ─────────────────────────────────────────────
# 證交所指數名稱 → 本專案代碼（沒列到的類股指數會自動用「IDX:名稱」）
# ─────────────────────────────────────────────
INDEX_CODES = {
    "發行量加權股價指數": "TAIEX",
    "未含金融指數": "IDX_EXFIN",
    "未含電子指數": "IDX_EXELEC",
    "電子工業類指數": "IDX_ELEC",
    "半導體類指數": "IDX_SEMI",
    "電腦及週邊設備類指數": "IDX_COMP",
    "光電類指數": "IDX_OPTO",
    "通信網路類指數": "IDX_COMM",
    "電子零組件類指數": "IDX_ECOMP",
    "電子通路類指數": "IDX_EDIST",
    "資訊服務類指數": "IDX_ITSVC",
    "其他電子類指數": "IDX_OELEC",
    "金融保險類指數": "IDX_FIN",
    "航運類指數": "IDX_SHIP",
    "塑膠類指數": "IDX_PLASTIC",
    "鋼鐵類指數": "IDX_STEEL",
    "油電燃氣類指數": "IDX_OIL",
    "汽車類指數": "IDX_AUTO",
    "建材營造類指數": "IDX_CONST",
    "食品類指數": "IDX_FOOD",
    "紡織纖維類指數": "IDX_TEXT",
    "水泥類指數": "IDX_CEMENT",
    "化學類指數": "IDX_CHEM",
    "生技醫療類指數": "IDX_BIO",
    "觀光餐旅類指數": "IDX_TOUR",
    "貿易百貨類指數": "IDX_TRADE",
    "電機機械類指數": "IDX_MACH",
    "電器電纜類指數": "IDX_CABLE",
    "玻璃陶瓷類指數": "IDX_GLASS",
    "造紙類指數": "IDX_PAPER",
    "橡膠類指數": "IDX_RUBBER",
    "綠能環保類指數": "IDX_GREEN",
    "數位雲端類指數": "IDX_CLOUD",
    "運動休閒類指數": "IDX_SPORT",
    "居家生活類指數": "IDX_HOME",
    "其他類指數": "IDX_OTHER",
}

EVENT_TYPES = ["貨幣政策", "財政政策", "國際貿易", "地緣政治", "科技發展", "產業供需", "能源及原物料", "國際金融市場", "其他"]
DIRECTIONS = ["正面", "負面", "中性", "不確定"]

# 漲跌幅分級 v1（見 docs/決策紀錄.md）
ABS_GRADE_THRESHOLDS = [0.5, 1.0, 2.0, 3.0]          # 單位 %
ABS_GRADE_NAMES = {
    1: ("微漲", "微跌"), 2: ("小漲", "小跌"), 3: ("明顯上漲", "明顯下跌"),
    4: ("大漲", "大跌"), 5: ("暴漲", "重挫"),
}
REL_GRADE_THRESHOLDS = [(1.0, "正常"), (2.0, "偏大"), (2.5, "異常")]   # 以上皆非則為「極端」
REL_WINDOW = 20


# AI 標示「可能受影響的產業」時只能從這份清單選：名稱與證交所類股指數一致，
# 之後可以直接用該類股指數的實際漲跌，檢驗 AI 對產業的判斷（決策紀錄 #26）
INDUSTRIES = {name.replace("類指數", ""): code for name, code in INDEX_CODES.items()
              if code.startswith("IDX_") and code not in ("IDX_EXFIN", "IDX_EXELEC", "IDX_ELEC")}
# AI 常用的別名 → 官方類股名稱
INDUSTRY_ALIASES = {
    "晶圓代工": "半導體", "IC設計": "半導體", "半導體業": "半導體", "半導體封裝測試": "半導體", "封測": "半導體",
    "記憶體": "半導體", "AI伺服器": "電腦及週邊設備", "伺服器": "電腦及週邊設備", "伺服器代工": "電腦及週邊設備",
    "雲端伺服器": "電腦及週邊設備", "電腦及週邊設備業": "電腦及週邊設備", "電子零組件業": "電子零組件",
    "被動元件": "電子零組件", "PCB": "電子零組件", "通路代理商": "電子通路", "電子通路業": "電子通路",
    "面板": "光電", "光電業": "光電", "網通": "通信網路", "通信網路業": "通信網路", "電信": "通信網路",
    "金融": "金融保險", "金融保險業": "金融保險", "銀行": "金融保險", "壽險": "金融保險",
    "航運業": "航運", "貨櫃航運": "航運", "航空": "航運", "散裝航運": "航運",
    "塑化": "塑膠", "塑膠工業": "塑膠", "石化": "塑膠", "鋼鐵工業": "鋼鐵", "能源": "油電燃氣", "油電燃氣業": "油電燃氣",
    "汽車工業": "汽車", "建材營造業": "建材營造", "營建": "建材營造", "食品工業": "食品", "紡織": "紡織纖維",
    "水泥工業": "水泥", "化學工業": "化學", "生技": "生技醫療", "生技醫療業": "生技醫療", "觀光": "觀光餐旅",
    "觀光餐旅業": "觀光餐旅", "零售": "貿易百貨", "貿易百貨業": "貿易百貨", "電機": "電機機械", "電機機械業": "電機機械",
    "綠能": "綠能環保", "軟體": "資訊服務", "資訊服務業": "資訊服務",
}


def normalize_industry(name: str) -> str | None:
    """把 AI 寫的產業名稱轉成證交所類股名稱；對不上就回傳 None（不寫入）。"""
    n = (name or "").strip().replace(" ", "")
    if n in INDUSTRIES:
        return n
    if n in INDUSTRY_ALIASES:
        return INDUSTRY_ALIASES[n]
    n2 = re.sub(r"(類|業|工業|產業)$", "", n)
    return n2 if n2 in INDUSTRIES else INDUSTRY_ALIASES.get(n2)
