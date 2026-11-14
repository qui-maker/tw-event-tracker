"""網站畫面測試：把測試資料寫進暫時資料庫，逐頁執行六個頁面，確認沒有程式錯誤。

執行：TEST_DATABASE_URL=postgresql://... pytest tests/test_app.py
（會清空該資料庫，只能指向測試用資料庫。）
"""
import os
import sys
from pathlib import Path

import pytest

TEST_DB = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DB, reason="沒有設定 TEST_DATABASE_URL")
ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app" / "streamlit_app.py"
PAGES = ["pages/dashboard.py", "pages/events.py", "pages/market.py", "pages/variables.py", "pages/relations.py",
         "pages/history.py"]


@pytest.fixture(scope="module")
def seeded():
    import psycopg
    with psycopg.connect(TEST_DB, autocommit=True) as c:
        c.execute("drop schema public cascade; create schema public;")
        c.execute((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
    mp = pytest.MonkeyPatch()
    mp.setenv("DATABASE_URL", TEST_DB)
    mp.delenv("SUPABASE_URL", raising=False)
    mp.delenv("SUPABASE_ANON_KEY", raising=False)
    sys.path.insert(0, str(ROOT / "app"))
    from tests.ui_fixture import seed
    from tracker.db import connect
    with connect() as conn:
        info = seed(conn)
    yield info
    mp.undo()


def run_page(page: str, query: dict | None = None):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    st.cache_data.clear()  # 快取不分資料庫，切換測試資料庫時要清掉
    st.cache_resource.clear()
    at = AppTest.from_file(str(APP), default_timeout=60)
    if query:
        at.query_params.update(query)
    at.run()
    if page != PAGES[0]:
        at.switch_page(page).run()
    return at


def errors(at) -> list[str]:
    return [e.value for e in at.exception] + [e.body for e in at.error]


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(seeded, page):
    at = run_page(page)
    assert not errors(at), errors(at)
    assert at.title, "頁面沒有標題"


def test_event_detail(seeded):
    at = run_page("pages/events.py", {"event": seeded["events"][0]})
    assert not errors(at), errors(at)


def test_variable_detail(seeded):
    for code in ["US10Y", "US_CPI", "SOX"]:
        at = run_page("pages/variables.py", {"var": code})
        assert not errors(at), (code, errors(at))


def test_history_tabs_with_report(seeded):
    at = run_page("pages/history.py")
    assert not errors(at), errors(at)
    md = [m.value for m in at.markdown]
    assert any("測試日報" in m for m in md), "報告內容沒有顯示"


def test_empty_database_shows_guidance(seeded):
    """資料庫是空的時候，每一頁都要顯示提示而不是錯誤。"""
    import psycopg
    with psycopg.connect(TEST_DB, autocommit=True) as c:
        c.execute("create schema if not exists empty_test")
        c.execute("drop schema empty_test cascade; create schema empty_test;")
        c.execute("set search_path to empty_test")
        c.execute("create role anon nologin" if not c.execute("select 1 from pg_roles where rolname='anon'").fetchone() else "select 1")
    url = TEST_DB + ("&" if "?" in TEST_DB else "?") + "options=-csearch_path%3Dempty_test"
    with psycopg.connect(url, autocommit=True) as c:
        c.execute((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
    mp = pytest.MonkeyPatch()
    mp.setenv("DATABASE_URL", url)
    try:
        for page in PAGES:
            at = run_page(page)
            assert not errors(at), (page, errors(at))
    finally:
        mp.undo()


def test_dashboard_sections_and_cards(seeded):
    """首頁改版後的五個區塊、AI 分析五塊與事件卡片都要出現，而且用的是資料庫裡的資料。"""
    at = run_page("pages/dashboard.py")
    assert not errors(at), errors(at)
    html = "\n".join(m.value for m in at.markdown)
    for title in ["台股市場概況", "AI 今日市場分析", "今日國際重大事件 TOP 5", "值得持續追蹤", "市場數據圖表",
                  "① 今日市場概況", "② 今日主要影響因素", "③ 可能受到影響的產業", "④ 值得觀察的經濟變項",
                  "⑤ 不確定因素與分析限制", "產業表現排行", "國際經濟變項", "變項趨勢比較"]:
        assert title in html, f"首頁缺少：{title}"
    assert "測試事件" in html                      # 事件卡片來自資料庫
    assert "查看完整分析" in [e.label for e in at.expander]
    assert len(at.get("plotly_chart")) >= 5        # 加權指數、漲跌幅、類股、變項、比較


def test_dashboard_controls(seeded):
    """觀察期間、變項分類、類股全部顯示、比較變項都可以操作，而且不會出錯。"""
    at = run_page("pages/dashboard.py")
    at.toggle(key="sec_all").set_value(True).run()
    assert not errors(at), errors(at)
    at.selectbox(key="var_period").set_value("1 年").run()
    assert not errors(at), errors(at)
    at.multiselect(key="cmp_vars").set_value(["SOX", "WTI"]).run()
    assert not errors(at), errors(at)
