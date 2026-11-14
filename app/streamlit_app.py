"""網站入口。執行：streamlit run app/streamlit_app.py"""
import streamlit as st

st.set_page_config(page_title="台股與世界重大事件追蹤器", page_icon="📈", layout="wide")

pages = [
    st.Page("pages/dashboard.py", title="首頁", icon="🏠", url_path="dashboard", default=True),
    st.Page("pages/events.py", title="國際重大事件", icon="🌐", url_path="events"),
    st.Page("pages/market.py", title="台股市場追蹤", icon="📊", url_path="market"),
    st.Page("pages/variables.py", title="國際經濟變項", icon="💹", url_path="variables"),
    st.Page("pages/relations.py", title="事件關聯分析", icon="🔗", url_path="relations"),
    st.Page("pages/history.py", title="歷史資料與報告", icon="🗂️", url_path="history"),
]
nav = st.navigation(pages, position="top")

with st.sidebar:
    st.markdown("### 台股與世界重大事件追蹤器")
    st.caption("研究與資料分析工具，不是投資建議。AI 的判斷是事前推論，相關不等於因果。")
    st.caption("資料每天自動更新兩次：台北時間約 06:00～07:00（國際新聞與 AI 開盤前判斷）、18:30～19:30（台股收盤）。實際時間依 GitHub 排程而定。")

nav.run()
