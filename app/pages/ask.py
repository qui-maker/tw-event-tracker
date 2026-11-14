"""頁面七：AI 問答（全頁）。與側邊欄共用同一段對話。"""
import streamlit as st

import ai_chat
import data
import ui

ui.setup_page("AI 問答", "根據本系統資料庫的資料回答：國際重大事件、新聞標題、台股與類股、國際經濟變項、日報與事前判斷。"
                         "資料沒有的不會亂補；回答是研究參考，不是投資建議。對話只存在你目前的瀏覽視窗，不會被儲存。")
if data.backend() == "none":
    ui.no_backend_notice()

# 首頁的範例問題會用 ?q= 帶過來
q = st.query_params.get("q")
if q and st.session_state.get("qa_q_done") != q:
    st.session_state["qa_q_done"] = q
    st.session_state["qa_pending"] = q
    st.query_params.pop("q", None)

with st.expander("AI 會參考哪些資料？", expanded=False):
    st.markdown("""
- **台股**：加權指數最近 15 個交易日（證交所 FMTQIK）、上市漲跌家數、三大法人、類股指數、櫃買指數
- **國際經濟變項**：19 個變項的最新數值、資料日期與來源（FRED、Yahoo Finance 非官方）
- **國際重大事件**：近 14 天本系統 AI 整理的事件（含傳導路徑、可能影響的變項與產業）
- **新聞**：最近 3 天蒐集的新聞標題（只有標題，不是全文）
- **日報**：最近 3 份日報的 AI 段落
- **事前判斷**：最近 20 筆判斷與評估結果
- 問題提到**日期**（例如 11/13）或**股票代號、公司名稱**時，會再補上那一天或那檔股票的資料
""")
    st.caption(f"每位觀看者每小時最多 {ai_chat.PER_SESSION_PER_HOUR} 題；整個網站每天有總次數上限，保護免費的 AI 額度。")

ai_chat.render("page")
