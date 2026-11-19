"""網站入口。執行：streamlit run app/streamlit_app.py"""
import sys
from pathlib import Path

import streamlit as st

# 讓網站可以讀取 tracker/config.py 的共用設定（例如證交所類股清單）；網站不會執行任何寫入程式
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

st.set_page_config(page_title="台股與世界重大事件追蹤器", page_icon="📈", layout="wide")

pages = [
    st.Page("pages/dashboard.py", title="首頁", icon="🏠", url_path="dashboard", default=True),
    st.Page("pages/events.py", title="國際重大事件", icon="🌐", url_path="events"),
    st.Page("pages/market.py", title="台股市場追蹤", icon="📊", url_path="market"),
    st.Page("pages/variables.py", title="國際經濟變項", icon="💹", url_path="variables"),
    st.Page("pages/relations.py", title="事件關聯分析", icon="🔗", url_path="relations"),
    st.Page("pages/history.py", title="歷史資料與報告", icon="🗂️", url_path="history"),
    st.Page("pages/ask.py", title="AI 問答", icon="💬", url_path="ask"),
]
nav = st.navigation(pages, position="top")

with st.sidebar:
    st.markdown("### 台股與世界重大事件追蹤器")
    st.caption("研究與資料分析工具，不是投資建議。AI 的判斷是事前推論，相關不等於因果。")
    # AI 問答放在側邊欄，每一頁都可以隨時發問；在全頁問答頁時不重複顯示
    if nav.url_path != "ask":
        st.divider()
        import ai_chat
        ai_chat.render("sidebar")
    st.divider()
    st.caption("資料每天自動更新：台北時間約 06:00～07:30（國際新聞與 AI 開盤前判斷）、15:40～16:40（台股收盤與日報），18:30 前後再補抓一次較晚公布的資料。實際時間依 GitHub 排程而定。")

nav.run()
