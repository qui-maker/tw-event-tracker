"""給 AI 的指示與回傳格式。改提示詞時記得把 config.PROMPT_VERSION 加一版。"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

COMMON_RULES = """你是「台股每日變化與世界重大事件追蹤器」的研究助理，任務是整理國際事件與台股大盤之間「可能的」關聯，不是投資建議。
必須遵守：
1. 只能使用提供給你的資料。不得捏造新聞、數字、日期、人名或歷史事件。
2. 區分三種資訊：
   - 事實：提供的新聞標題或數據直接寫出的內容，並附上對應的新聞編號。
   - 推論：你的分析判斷，要寫出理由。
   - 未確認：傳聞、只有單一來源、或標題語氣不確定（例如 reportedly、may、plans）。
3. 相關不等於因果。描述市場反應時用「同期」「伴隨」「可能」，不要寫成確定的因果。
4. 全部使用台灣慣用的繁體中文（例如「聯準會」「殖利率」「半導體」），不可出現簡體字。
5. 資料不足時要直接寫出缺少什麼，不要硬下結論。
6. 注意時間順序：美股、費半、台積電 ADR、VIX 等標示為某一天的收盤，發生在台灣同一天收盤「之後」（台北時間隔天清晨），
   只可能影響台股「下一個交易日」。不要用同一日期的美國市場變化解釋台股當天的漲跌，也不要寫「同日」；要寫明是哪一天的美股收盤。
7. 事件的發生時間以「首則新聞發布時間」或新聞內容為準，不是分析日期。開盤前寫判斷時，當天的日本、韓國等亞洲股市都還沒開盤，
   新聞裡的亞股漲跌是前一個交易日的結果。"""


# ─────────────────────────────────────────────
# 1. 事件辨識與影響分析（早班）
# ─────────────────────────────────────────────
class Fact(BaseModel):
    text: str = Field(description="事實陳述（繁體中文）")
    news_ids: list[int] = Field(description="支持這條事實的新聞編號，至少一個")


class EventOut(BaseModel):
    name: str = Field(description="事件名稱，20 字以內")
    event_type: str = Field(description="只能是：貨幣政策、財政政策、國際貿易、地緣政治、科技發展、產業供需、能源及原物料、國際金融市場、其他")
    occurred_date: Optional[str] = Field(None, description="事件發生日期 YYYY-MM-DD；標題無法判斷就填 null")
    countries: list[str] = Field(description="涉及的國家或地區（繁體中文）")
    actors: list[str] = Field(description="涉及的企業、組織或人物")
    importance: int = Field(description="對台股大盤的重要程度 1～5")
    importance_reason: str
    summary: str = Field(description="事件摘要，100 字以內，只寫標題能支持的內容")
    facts: list[Fact]
    inferences: list[str] = Field(description="推論，每條都要寫理由")
    unconfirmed: list[str]
    data_gaps: list[str] = Field(description="判斷這個事件時缺少的資料")
    affected_variables: list[str] = Field(description="可能受影響的變項代碼，只能從提供的清單選")
    affected_industries: list[str] = Field(description="可能受影響的台灣產業，只能從提供的「證交所類股清單」選，最多 5 個")
    direction: str = Field(description="對台股大盤的可能方向：正面、負面、中性、不確定")
    pathway: list[str] = Field(description="傳導路徑 3～5 個節點，第一個是事件，最後一個是「台股加權指數」")
    news_ids: list[int] = Field(description="與此事件有關的全部新聞編號")
    status: str = Field(description="new（新事件）或 update（近期事件的後續發展）")
    related_event_id: Optional[str] = Field(None, description="若 status 為 update，填近期事件編號")


class EventsOut(BaseModel):
    events: list[EventOut]


EVENTS_TASK = """以下是過去約 24 小時蒐集到的新聞標題（JSON，每行一則；id 是新聞編號）。
請挑出對「台股加權指數」最可能有影響的 5 到 8 個重大事件：
- 不同媒體報導同一件事要合併成一個事件。
- 和「近期已記錄事件」是同一件事的後續發展時，status 填 update，並填 related_event_id；完全重複且沒有新進展的就不要列。
- 地方新聞、體育娛樂、與經濟市場無關的新聞不要列。
- facts 每一條都必須附上新聞編號；標題沒有直接寫出的內容放到 inferences 或 unconfirmed。
- importance 評分：5＝可能明顯影響全球市場；3＝影響特定產業或地區；1＝影響很小。

可用的變項代碼：
{variables}

證交所類股清單（affected_industries 只能從這裡選）：
{industries}

近期已記錄事件：
{recent}

今天（台北時間）：{today}

新聞：
{news}
"""


# ─────────────────────────────────────────────
# 2. 加權指數事前預測（早班）
# ─────────────────────────────────────────────
class Driver(BaseModel):
    source: str = Field(description="事件編號（EV-…）或變項代碼")
    effect: str = Field(description="正面、負面或中性")
    reason: str


class PredictionOut(BaseModel):
    direction: str = Field(description="只能是「上漲」或「下跌」")
    confidence: str = Field(description="低、中、高")
    rationale: str = Field(description="判斷理由，200 字以內")
    drivers: list[Driver]
    pathways: list[list[str]] = Field(description="主要傳導路徑，每條 3～5 個節點，最後一個節點是「台股加權指數」")
    counterpoints: list[str] = Field(description="可能讓判斷錯誤的反向因素")
    data_gaps: list[str]


PREDICTION_TASK = """請判斷「台股加權指數」在 {target} 的收盤，相對前一個交易日收盤是上漲還是下跌。
規則：
- 只能回答「上漲」或「下跌」，不能回答持平；不確定時用 confidence＝低 表達。
- 這是在市場反應之前寫下的判斷，寫入後不能修改，之後會和實際結果比較。
- 單日漲跌同時受很多因素影響，請在 counterpoints 寫出反向因素。

今日事件：
{events}

隔夜國際市場與經濟變項（最新值；「非官方」表示來自 Yahoo Finance）：
{variables}

台股加權指數最近 5 個交易日：
{taiex}
"""


# ─────────────────────────────────────────────
# 3. 日報、週報、月報的文字段落
# ─────────────────────────────────────────────
class ReportOut(BaseModel):
    summary: str = Field(description="3～5 句今日重點")
    market_overview: str = Field(description="台股市場概況，150 字以內")
    international: str = Field(description="國際局勢摘要，150 字以內")
    key_factors: list[str] = Field(description="可能影響台股的主要因素，每條開頭標【事實】【推論】或【未確認】")
    watch_items: list[str] = Field(description="值得持續觀察的事件或數據，若有已知日期要寫出")
    data_gaps: list[str] = Field(description="資料不足或仍不確定的部分")


REPORT_TASK = """請根據下列資料撰寫《{title}》的文字段落。只能使用這些資料，不要加入外部資訊或預測股價。

{context}
"""
