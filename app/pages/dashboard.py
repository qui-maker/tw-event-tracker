"""頁面一：首頁 Dashboard

版面順序（資訊層級由上到下）：
1. 台股市場概況（關鍵數字）＋ 事前判斷
2. AI 今日市場分析（全寬，分成五塊）
3. 今日國際重大事件 TOP 5
4. 值得持續追蹤
5. 市場數據圖表：加權指數 → 產業排行 → 國際經濟變項（分五類）→ 變項趨勢比較
所有數字都來自資料庫的真實資料；沒有資料時顯示「資料尚未取得」。
"""
from collections import Counter, defaultdict
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import data
import ui
from grading_view import abs_label, rel_label, z_value
from groups import NOT_COLLECTED, PERIODS, VARIABLE_GROUPS, digits_for

try:  # 證交所類股清單（與排程程式共用同一份設定）
    from tracker.config import INDUSTRIES, normalize_industry
except Exception:  # noqa: BLE001
    INDUSTRIES, normalize_industry = {}, (lambda name: None)

ui.setup_page("台股每日變化與世界重大事件")
if data.backend() == "none":
    ui.no_backend_notice()

STATUS = {"success": "成功", "partial": "部分成功", "failed": "失敗", "running": "執行中"}
last = data.latest_trade_date()
runs = data.runs(5)
status = []
if last:
    status.append(f"最新台股收盤：{last:%Y-%m-%d}")
if not runs.empty:
    r0 = runs.iloc[0]
    status.append(f"最近一次自動更新：{r0['started_at']:%m/%d %H:%M}（{r0['job']}，{STATUS.get(r0['status'], r0['status'])}）")
st.caption("｜".join(status) or "資料庫目前沒有資料")

if not last:
    ui.empty_state("還沒有任何台股資料。系統完成第一次回補後，這裡就會出現內容。")
    st.stop()

tx_all = data.index_series("TAIEX", last - timedelta(days=1100))
today_row = tx_all.iloc[-1]
raw_lv = data.latest_variables()
lv = raw_lv.set_index("code") if not raw_lv.empty else pd.DataFrame()
varname = dict(zip(lv.index, lv["name"])) if not lv.empty else {}


def var_note(code: str) -> str:
    if lv.empty or code not in lv.index:
        return ""
    v = lv.loc[code]
    note = f"{v['source']}・{ui.date_str(v['date'])}"
    return note + ("・非官方" if not bool(v.get("is_official", True)) else "")


# ═══════════════════════════ 1. 台股市場概況 ═══════════════════════════
ui.section("台股市場概況", f"{last:%Y/%m/%d}（{'一二三四五六日'[last.weekday()]}）收盤")
tpex = data.index_series("TPEX", last - timedelta(days=10))
br = data.breadth(last - timedelta(days=10))
fl = data.flows(last - timedelta(days=10))
z = z_value(tx_all["change_pct"], len(tx_all) - 1)
pct = today_row["change_pct"]
kind = "up" if ui.is_num(pct) and pct > 0 else "down" if ui.is_num(pct) and pct < 0 else "flat"
b = br[br["trade_date"].dt.date == last] if not br.empty else pd.DataFrame()
f = fl[(fl["trade_date"].dt.date == last) & fl["investor"].str.contains("外資及陸資", na=False)] if not fl.empty else pd.DataFrame()
t = tpex[tpex["trade_date"].dt.date == last] if not tpex.empty else pd.DataFrame()
tx_note = f"{today_row['source']}・{last:%Y-%m-%d}"
tiles = [
    ui.kpi("加權指數", today_row["close"], "點", 2, today_row["change"], pct, tx_note),
    ui.kpi("漲跌幅度等級", None, value_text=ui.tag(abs_label(pct), kind),
           note=f"相對近 20 日：{rel_label(z)}" + ("" if z is None else f"（{z:+.1f} 個標準差）") + "・依決策紀錄 v1"),
    ui.kpi("成交金額", today_row["trade_value"] / 1e8 if ui.is_num(today_row["trade_value"]) else None, "億元", 0, note=tx_note),
    ui.kpi("上漲／下跌／持平", None, value_text=ui.missing() if b.empty else
           f'<span style="font-size:1.2rem"><span style="color:{ui.UP}">{int(b.iloc[0]["advances"])}</span>／'
           f'<span style="color:{ui.DOWN}">{int(b.iloc[0]["declines"])}</span>／{int(b.iloc[0]["unchanged"] or 0)}</span>',
           note="上市股票家數" + ("" if b.empty else f"・{b.iloc[0]['source']}")),
    ui.kpi("外資買賣超", None if f.empty else f["net"].sum() / 1e8, "億元", 2,
           value_text=ui.missing() if f.empty else None, note="" if f.empty else f"{f.iloc[0]['source']}・{last:%Y-%m-%d}"),
    ui.kpi("櫃買指數", None if t.empty else t.iloc[0]["close"], "點", 2,
           None, None if t.empty else t.iloc[0]["change_pct"], "" if t.empty else f"{t.iloc[0]['source']}・{last:%Y-%m-%d}",
           value_text=ui.missing() if t.empty else None),
]
ui.kpi_grid(tiles)

# 事前判斷（目標交易日的 AI 與對照規則）
pr = data.predictions()
with st.container(key="panel-pred"):
    pcols = st.columns([1, 3])
    pcols[0].markdown('<div class="overline">事前判斷</div><div class="subhead">開盤前寫下的方向</div>', unsafe_allow_html=True)
    with pcols[1]:
        nxt = pr[pr["target_trading_day"].dt.date >= last].sort_values("target_trading_day") if not pr.empty else pr
        if nxt.empty:
            # 最新交易日沒有事前判斷時要明白標示是缺口（例如 11/19 早班被取消，決策紀錄 #47），不是還沒到時間
            had_today = (not pr.empty) and (pr["target_trading_day"].dt.date == last).any()
            gap = "" if had_today else (f"<b>{last:%Y-%m-%d} 沒有事前判斷</b>（當天開盤前的自動排程沒有完成，"
                                        "09:00 之後補寫不算事前判斷，所以不補做；詳見決策紀錄）。<br>")
            st.markdown(f'<div class="card-body">{gap}目前沒有待驗證的事前判斷。AI 與對照規則會在<b>交易日早上 09:00 開盤前</b>'
                        '寫下當天大盤方向，收盤後自動比對。</div>', unsafe_allow_html=True)
        else:
            tday = nxt["target_trading_day"].max()
            parts = []
            for _, p in nxt[nxt["target_trading_day"] == tday].iterrows():
                who = "AI" if p["kind"] == "ai" else "對照規則（費半方向）"
                res = p.get("result") if isinstance(p.get("result"), str) else "待評估"
                parts.append(f"<b>{who}</b> {ui.direction_tag(p['direction'])}"
                             + (f"<span class='src'>信心 {p['confidence']}・</span>" if isinstance(p["confidence"], str) else "")
                             + f"<span class='src'>{res}</span>")
            st.markdown(f"<div class='card-body'>目標交易日 <b>{tday:%Y-%m-%d}</b>（加權指數收盤相對前一交易日）<br>"
                        + "　　".join(parts) + "</div>", unsafe_allow_html=True)
        st.page_link("pages/relations.py", label="全部判斷與命中率 →")

# ═══════════════════════════ 2. AI 今日市場分析 ═══════════════════════════
reps = data.reports("daily")
if reps.empty:
    ui.section("AI 今日市場分析")
    ui.empty_state("還沒有日報。晚班（約台北 18:30～19:30）完成後會產生。")
    rep, sec_ai, rep_day = None, {}, None
else:
    rep = reps.iloc[0]
    sec_ai = rep["sections"] or {}
    rep_day = pd.to_datetime(rep["period_key"]).date()
    ui.section("AI 今日市場分析",
               f"{ui.esc(rep['title'])}｜產生於 {rep['generated_at']:%m/%d %H:%M}｜模型：{ui.esc(rep['model'] or '—')}"
               "｜AI 只使用本系統蒐集的資料，事實、推論、未確認分開標示")

if rep is not None:
    rep_events = data.events(rep_day, rep_day)
    if not sec_ai:
        st.warning("這份日報的 AI 段落沒有成功產生（多半是 AI 服務忙碌），下方產業與變項仍依當天事件列出。")

    # 2-1 今日市場概況 ＋ 關鍵數字
    a1, a2 = st.columns([3, 2], gap="large")
    with a1:
        with st.container(border=True, key="card-ai-overview"):
            st.markdown('<div class="overline">① 今日市場概況</div>', unsafe_allow_html=True)
            if sec_ai.get("market_overview") or sec_ai.get("international"):
                st.markdown(f"<div class='card-body'><b>台股</b>　{ui.esc(sec_ai.get('market_overview', ''))}</div>",
                            unsafe_allow_html=True)
                st.markdown(f"<div class='card-body' style='margin-top:8px'><b>國際</b>　{ui.esc(sec_ai.get('international', ''))}</div>",
                            unsafe_allow_html=True)
            elif sec_ai.get("summary"):
                st.markdown(f"<div class='card-body'>{ui.esc(sec_ai['summary'])}</div>", unsafe_allow_html=True)
            else:
                st.markdown(ui.missing("AI 概況"), unsafe_allow_html=True)
    with a2:
        rep_tx = tx_all[tx_all["trade_date"].dt.date == rep_day]
        items = []
        if not rep_tx.empty:
            rr = rep_tx.iloc[0]
            items.append(ui.kpi("加權指數", rr["close"], "點", 2, rr["change"], rr["change_pct"], f"{rr['source']}・{rep_day:%m/%d}"))
        for code in ["SOX", "TSM_ADR", "US10Y"]:
            if not lv.empty and code in lv.index:
                v = lv.loc[code]
                pts = str(v["unit"]).startswith("%")
                items.append(ui.kpi(v["name"], v["value"], v["unit"], digits_for(v["value"]),
                                    v["change"] if pts else None, None if pts else v["change_pct"], var_note(code),
                                    unit_points="個百分點" if pts else None))
        if items:
            ui.kpi_grid(items, compact=True)

    # 2-2 主要影響因素 ｜ 2-3 可能受影響的產業
    b1, b2 = st.columns(2, gap="large")
    with b1:
        with st.container(border=True, key="card-ai-factors"):
            st.markdown('<div class="overline">② 今日主要影響因素</div>', unsafe_allow_html=True)
            factors = sec_ai.get("key_factors") or []
            if not factors:
                st.markdown(ui.missing("AI 影響因素"), unsafe_allow_html=True)
            else:
                st.markdown("<ul class='items'>" + "".join(
                    f"<li><span class='rank'>{i + 1}</span>{ui.labelled(x)}</li>" for i, x in enumerate(factors[:3])) + "</ul>",
                    unsafe_allow_html=True)
                if len(factors) > 3:
                    with st.expander(f"其他 {len(factors) - 3} 項因素"):
                        st.markdown("<ul class='items'>" + "".join(f"<li>{ui.labelled(x)}</li>" for x in factors[3:]) + "</ul>",
                                    unsafe_allow_html=True)
    with b2:
        with st.container(border=True, key="card-ai-industries"):
            st.markdown('<div class="overline">③ 可能受到影響的產業</div>', unsafe_allow_html=True)
            ind_events: dict[str, list] = defaultdict(list)
            unmatched = 0
            for _, e in rep_events.iterrows():
                for raw in e["affected_industries"] or []:
                    n = normalize_industry(raw)
                    if n:
                        if e["id"] not in [x[0] for x in ind_events[n]]:
                            ind_events[n].append((e["id"], e["name"], e["direction"]))
                    else:
                        unmatched += 1
            if not ind_events:
                st.markdown(ui.missing("產業判斷"), unsafe_allow_html=True)
            else:
                secs = data.indices_on(rep_day)
                actual = dict(zip(secs["index_code"], secs["change_pct"])) if not secs.empty else {}
                rows = []
                for name, evs in sorted(ind_events.items(), key=lambda kv: -len(kv[1]))[:6]:
                    act = actual.get(INDUSTRIES.get(name))
                    act_html = ui.change_html(None, act) if ui.is_num(act) else ui.missing("類股資料")
                    dirs = Counter(d for _, _, d in evs)
                    reason = "；".join(f"{ui.esc(nm)}" for _, nm, _ in evs[:2]) + (f" 等 {len(evs)} 則" if len(evs) > 2 else "")
                    dir_html = "".join(ui.direction_tag(k) + (f"<span class='src'>×{v}</span> " if v > 1 else " ") for k, v in dirs.items())
                    rows.append(f"<li><div class='ind'><b>{ui.esc(name)}</b><span class='src'>{rep_day:%m/%d} 類股實際 {act_html}</span></div>"
                                f"<div><span class='src'>AI 判斷：</span>{dir_html}</div>"
                                f"<div class='src'>依據事件：{reason}</div></li>")
                st.markdown("<ul class='items'>" + "".join(rows) + "</ul>", unsafe_allow_html=True)
                st.markdown("<div class='src'>AI 判斷屬於【推論】；類股實際漲跌來自證交所 MI_INDEX，同日變化不代表因果。"
                            + (f"另有 {unmatched} 項早期寫法無法對應證交所類股，未列出。" if unmatched else "") + "</div>",
                            unsafe_allow_html=True)

    # 2-4 值得觀察的經濟變項 ｜ 2-5 不確定因素
    c1, c2 = st.columns(2, gap="large")
    with c1:
        with st.container(border=True, key="card-ai-variables"):
            st.markdown('<div class="overline">④ 值得觀察的經濟變項</div>', unsafe_allow_html=True)
            cnt = Counter(v for vs in rep_events["affected_variables"] for v in (vs or [])) if not rep_events.empty else Counter()
            if not cnt or lv.empty:
                st.markdown(ui.missing("相關變項"), unsafe_allow_html=True)
            else:
                rows = []
                for code, n in cnt.most_common(6):
                    if code not in lv.index:
                        rows.append(f"<li><b>{ui.esc(code)}</b>　{ui.missing()}</li>")
                        continue
                    v = lv.loc[code]
                    rows.append(f"<li><b>{ui.esc(v['name'])}</b>　{ui.fmt(v['value'], digits_for(v['value']))} "
                                f"<span class='src'>{ui.esc(v['unit'])}</span>　{ui.var_change_html(v)}"
                                f"<br><span class='src'>{var_note(code)}｜{n} 則事件提到</span></li>")
                st.markdown("<ul class='items'>" + "".join(rows) + "</ul>", unsafe_allow_html=True)
                st.page_link("pages/variables.py", label="全部經濟變項 →")
    with c2:
        with st.container(border=True, key="card-ai-uncertain"):
            st.markdown('<div class="overline">⑤ 不確定因素與分析限制</div>', unsafe_allow_html=True)
            gaps = list(sec_ai.get("data_gaps") or [])
            unconf = [f"【未確認】{x}" for xs in rep_events["unconfirmed"] for x in (xs or [])][:3] if not rep_events.empty else []
            rows = [f"<li>{ui.labelled('【資料不足】' + x)}</li>" for x in gaps[:3]] + [f"<li>{ui.labelled(x)}</li>" for x in unconf]
            rows.append("<li class='src'>分析限制：AI 只讀得到新聞標題，不是全文；單日漲跌同時受許多因素影響，"
                        "同期變化不代表因果。</li>")
            st.markdown("<ul class='items'>" + "".join(rows) + "</ul>", unsafe_allow_html=True)
    st.page_link("pages/history.py", label="閱讀完整日報 →")

# 問 AI 入口
with st.container(key="panel-ask"):
    st.markdown('<div class="overline">💬 AI 問答</div><div class="subhead">對今天的分析有疑問？直接問 AI</div>'
                '<div class="src">左側欄每一頁都可以發問（手機請點左上角 » 打開側邊欄），也可以點下面的問題到全頁問答。'
                'AI 只根據本系統的資料回答。</div>', unsafe_allow_html=True)
    qcols = st.columns(3)
    for i, q in enumerate(["最近一個交易日台股為什麼這樣漲跌？", "最近最重要的國際事件可能影響哪些台灣產業？", "AI 的事前判斷目前準確嗎？"]):
        qcols[i].page_link("pages/ask.py", label=q, query_params={"q": q})

# ═══════════════════════════ 3. 今日國際重大事件 TOP 5 ═══════════════════════════
ev = data.events(date.today() - timedelta(days=3))
if ev.empty:
    ui.section("今日國際重大事件 TOP 5")
    ui.empty_state("近三天沒有 AI 辨識出的重大事件。")
    top = pd.DataFrame()
else:
    latest_day = ev["analysis_date"].max()
    top = ev[ev["analysis_date"] == latest_day].sort_values(["importance", "id"], ascending=[False, True]).head(5)
    ui.section("今日國際重大事件 TOP 5",
               f"分析日期 {latest_day:%Y-%m-%d}｜AI 每天早上從過去約 24 小時的國際新聞辨識，依重要程度排序")
    ev_news = data.news_for_events(tuple(top["id"]))


def event_card(rank: int, e: pd.Series):
    with st.container(border=True, key=f"card-ev-{e['id']}"):
        # 第一層：標題、重要程度、影響方向
        st.markdown(f"<div class='card-title'><span class='rank'>{rank}</span>{ui.esc(e['name'])}</div>"
                    f"{ui.importance_tag(e['importance'])}{ui.direction_tag(e['direction'])}"
                    f"<span class='src'>對台股大盤的可能方向（AI 推論）</span>", unsafe_allow_html=True)
        # 第二層：分類、日期、編號
        first = ui.date_str(e["first_published_at"], "%Y-%m-%d %H:%M") if ui.is_num(e["first_published_at"]) else "不明"
        chain = f"・延續自 {e['related_event_id']}" if isinstance(e.get("related_event_id"), str) else ""
        st.markdown(f"<div class='card-meta'>{ui.tag(e['event_type'])} 事件發生：{ui.date_str(e['occurred_date'])}"
                    f"・首則新聞發布：{first}・{e['id']}{chain}</div>", unsafe_allow_html=True)
        # 第三層：摘要
        st.markdown(f"<div class='card-body'>{ui.esc(e['summary'] or '')}</div>", unsafe_allow_html=True)
        # 第四層：變項與產業
        variables = "、".join(varname.get(v, v) for v in (e["affected_variables"] or [])) or "—"
        industries = "、".join(e["affected_industries"] or []) or "—"
        st.markdown(f"<div class='kv'><b>可能影響的變項</b>{ui.esc(variables)}</div>"
                    f"<div class='kv'><b>可能影響的產業</b>{ui.esc(industries)}</div>", unsafe_allow_html=True)
        # 第五層：原始新聞與完整分析
        nw = ev_news[ev_news["event_id"] == e["id"]] if not ev_news.empty else pd.DataFrame()
        if nw.empty:
            st.markdown("<div class='src' style='margin-top:8px'>原始新聞：資料尚未取得</div>", unsafe_allow_html=True)
        else:
            links = "、".join(f"<a href='{ui.esc(n['url'])}' target='_blank' rel='noopener'>{ui.esc(n['source_name'] or '新聞')}</a>"
                              for _, n in nw.head(3).iterrows())
            st.markdown(f"<div class='src' style='margin-top:8px'>原始新聞（{len(nw)} 則）：{links}"
                        + ("…" if len(nw) > 3 else "") + "</div>", unsafe_allow_html=True)
        with st.expander("查看完整分析"):
            for x in e["facts"] or []:
                ids = "、".join(str(i) for i in x.get("news_ids", []))
                st.markdown(f"<div class='card-body'>{ui.labelled('【事實】' + x.get('text', ''))}"
                            f"<span class='src'>　新聞 {ids}</span></div>", unsafe_allow_html=True)
            for x in e["inferences"] or []:
                st.markdown(f"<div class='card-body'>{ui.labelled('【推論】' + x)}</div>", unsafe_allow_html=True)
            for x in e["unconfirmed"] or []:
                st.markdown(f"<div class='card-body'>{ui.labelled('【未確認】' + x)}</div>", unsafe_allow_html=True)
            if e["pathway"]:
                st.markdown(f"<div class='kv'><b>傳導路徑</b>{' → '.join(ui.esc(p) for p in e['pathway'])}</div>",
                            unsafe_allow_html=True)
            if e["data_gaps"]:
                st.markdown(f"<div class='kv'><b>資料不足</b>{'；'.join(ui.esc(x) for x in e['data_gaps'])}</div>",
                            unsafe_allow_html=True)
            if not nw.empty:
                st.markdown("<div class='kv'><b>全部原始新聞</b></div>" + "".join(
                    f"<div class='src'>#{int(n['news_id'])}　<a href='{ui.esc(n['url'])}' target='_blank' rel='noopener'>"
                    f"{ui.esc(n['title'])}</a>　{ui.esc(n['source_name'] or '')}・{ui.date_str(n['published_at'], '%m/%d %H:%M')}</div>"
                    for _, n in nw.iterrows()), unsafe_allow_html=True)
            st.page_link("pages/events.py", label="開啟事件詳細頁 →", query_params={"event": e["id"]})


if not top.empty:
    rows = list(top.iterrows())
    event_card(1, rows[0][1])
    for i in range(1, len(rows), 2):
        cols = st.columns(2, gap="medium")
        for j, col in enumerate(cols):
            if i + j < len(rows):
                with col:
                    event_card(i + j + 1, rows[i + j][1])
    st.page_link("pages/events.py", label="全部事件、篩選與時間軸 →")

# ═══════════════════════════ 4. 值得持續追蹤 ═══════════════════════════
ui.section("值得持續追蹤", "AI 建議觀察的事項，以及近一週持續有後續發展的事件")
d1, d2 = st.columns(2, gap="large")
with d1:
    with st.container(border=True, key="card-watch"):
        st.markdown('<div class="overline">AI 建議觀察</div>', unsafe_allow_html=True)
        watch = sec_ai.get("watch_items") or []
        st.markdown(("<ul class='items'>" + "".join(f"<li>{ui.labelled(x)}</li>" for x in watch) + "</ul>") if watch
                    else ui.missing("觀察事項"), unsafe_allow_html=True)
with d2:
    with st.container(border=True, key="card-chain"):
        st.markdown('<div class="overline">延續中的事件</div>', unsafe_allow_html=True)
        week = data.events(date.today() - timedelta(days=7))
        chains = week[week["related_event_id"].notna()] if not week.empty else week
        if chains.empty:
            st.markdown("<div class='card-body muted'>近一週沒有被 AI 標示為「後續發展」的事件。</div>", unsafe_allow_html=True)
        else:
            names = dict(zip(week["id"], week["name"]))
            st.markdown("<ul class='items'>" + "".join(
                f"<li><b>{ui.esc(c['name'])}</b>　{ui.direction_tag(c['direction'])}<br><span class='src'>{c['analysis_date']:%m/%d}・{c['id']}"
                f"　延續自 {c['related_event_id']}「{ui.esc(names.get(c['related_event_id'], ''))}」</span></li>"
                for _, c in chains.head(6).iterrows()) + "</ul>", unsafe_allow_html=True)

# ═══════════════════════════ 5. 市場數據圖表 ═══════════════════════════
ui.section("市場數據圖表", "滑鼠移到圖上可看每天的數值；所有圖表都標示資料來源與日期")

# 5-1 台股加權指數（完整寬度）
ui.subhead("台股加權指數")
tv = today_row["trade_value"] / 1e8 if ui.is_num(today_row["trade_value"]) else None
st.markdown(f"<div class='chart-h'><span class='v' style='font-size:1.3rem'>{ui.fmt(today_row['close'])}</span>"
            f"<span class='u'>點</span><span class='v'>{ui.change_html(today_row['change'], today_row['change_pct'])}</span>"
            f"<span class='u'>成交金額 {ui.fmt(tv, 0)} 億元・觀察日期 {last:%Y-%m-%d}</span></div>", unsafe_allow_html=True)
period = st.segmented_control("觀察期間", list(PERIODS), default="6 個月", key="tx_period")
days = PERIODS.get(period or "6 個月", 183)
tx = tx_all[tx_all["trade_date"] >= pd.Timestamp(last - timedelta(days=days))]
evm = data.events(last - timedelta(days=days))
markers = None
if not evm.empty:
    big = evm[evm["importance"] >= 4].copy()
    big["d"] = big["analysis_date"].dt.normalize()
    m = big.groupby("d")["name"].apply(lambda s: "<br>".join(s.head(4))).reset_index()
    m = pd.merge_asof(m.sort_values("d"), tx[["trade_date", "close"]].sort_values("trade_date"),
                      left_on="d", right_on="trade_date", direction="backward").dropna(subset=["close"])
    markers = pd.DataFrame({"x": m["trade_date"], "y": m["close"], "text": m["name"]})
ui.plot(ui.line_chart(tx, "trade_date", "close", "加權指數", 420, None, markers, unit="點"), key="tx_main")
ui.plot(ui.change_bars(tx, "trade_date", "change_pct", "每日漲跌幅", 150), key="tx_bars")
st.markdown(ui.source_line(ui.sources_of(tx), last) +
            "<div class='src'>上圖為收盤指數（◆＝重要程度 4 以上的事件，標在事件分析日或之前最近的交易日）；下圖為每日漲跌幅（%）。</div>",
            unsafe_allow_html=True)

# 5-2 產業表現排行
ui.subhead("產業表現排行")
sdates = data.sector_dates(last - timedelta(days=120))
if not sdates:
    st.markdown(ui.missing("類股指數資料"), unsafe_allow_html=True)
else:
    s1, s2 = st.columns([2, 3], vertical_alignment="bottom")
    with s1:
        sday = st.selectbox("交易日期", sdates, format_func=lambda d: f"{d:%Y-%m-%d}（{'一二三四五六日'[d.weekday()]}）", key="sec_day")
    with s2:
        show_all = st.toggle("顯示全部類股", value=False, key="sec_all")
    secs = data.indices_on(sday)
    if not secs.empty:  # 只列證交所產業類股（排除「未含金融」「電子工業」這類綜合指數）
        secs = secs[secs["index_code"].isin(set(INDUSTRIES.values()))] if INDUSTRIES else secs[secs["index_code"].str.startswith("IDX_")]
    secs = secs.dropna(subset=["change_pct"]).sort_values("change_pct", ascending=False)
    if secs.empty:
        st.markdown(ui.missing("這一天的類股資料"), unsafe_allow_html=True)
    else:
        secs = secs.assign(label=secs["name"].str.replace("類指數", "", regex=False))
        n_up, n_down = int((secs["change_pct"] > 0).sum()), int((secs["change_pct"] < 0).sum())
        pick = secs if (show_all or len(secs) <= 16) else pd.concat([secs.head(8), secs.tail(8)])
        note = "全部" if len(pick) == len(secs) else "最強 8 類與最弱 8 類"
        st.markdown(f"<div class='src'>共 {len(secs)} 類：<span style='color:{ui.UP}'>▲ 上漲 {n_up}</span>、"
                    f"<span style='color:{ui.DOWN}'>▼ 下跌 {n_down}</span>；目前顯示{note}。類股資料從系統上線日（2026-11-12）開始累積。</div>",
                    unsafe_allow_html=True)
        ui.plot(ui.sector_bars(pick, "label", "change_pct"), key="sec_bars")
        st.markdown(ui.source_line(ui.sources_of(pick), sday), unsafe_allow_html=True)

# 5-3 國際經濟變項（分類、每列最多兩張）
ui.subhead("國際經濟變項")
g1, g2 = st.columns([3, 1], vertical_alignment="bottom")
with g1:
    group = st.segmented_control("分類", list(VARIABLE_GROUPS), default="利率與債券", key="var_group",
                                 label_visibility="collapsed")
with g2:
    vperiod = st.selectbox("觀察期間", list(PERIODS)[:4], index=1, key="var_period")
group = group or "利率與債券"
vstart = date.today() - timedelta(days=PERIODS[vperiod])
st.markdown(f"<div class='overline' style='margin-top:.4rem'>{ui.esc(group)}</div>", unsafe_allow_html=True)
codes = VARIABLE_GROUPS[group]
for i in range(0, len(codes), 2):
    cols = st.columns(2, gap="large")
    for j, col in enumerate(cols):
        if i + j >= len(codes):
            continue
        code = codes[i + j]
        with col:
            if lv.empty or code not in lv.index:
                ui.chart_header(code)
                st.markdown(ui.missing(), unsafe_allow_html=True)
                continue
            v = lv.loc[code]
            dg = digits_for(v["value"])
            s = data.variable_series(code, vstart - timedelta(days=40 if v["frequency"] == "月" else 0))
            ui.chart_header(v["name"], f"{ui.fmt(v['value'], dg)} {ui.var_change_html(v)}", v["unit"])
            if s.empty:
                st.markdown(ui.missing(), unsafe_allow_html=True)
            else:
                ui.plot(ui.line_chart(s, "obs_date", "value", v["name"], 240, None, unit=str(v["unit"]), digits=dg),
                        key=f"var_{code}")
            st.markdown(ui.source_line(v["source"], v["date"], unofficial=not bool(v.get("is_official", True)))
                        + "<div class='gap-after'></div>", unsafe_allow_html=True)
if group in NOT_COLLECTED:
    st.markdown(f"<div class='src'>尚未納入蒐集：{'、'.join(NOT_COLLECTED[group])}（資料尚未取得，不顯示）。"
                "月資料（CPI、失業率、非農）每月更新一次，圖上每一點是一個月。</div>", unsafe_allow_html=True)

# 5-4 變項趨勢比較
ui.subhead("變項趨勢比較")
all_codes = [c for g in VARIABLE_GROUPS.values() for c in g if not lv.empty and c in lv.index]
picks = st.multiselect("選擇最多 3 個變項", all_codes, default=[c for c in ["SOX", "TSM_ADR", "US10Y"] if c in all_codes],
                       max_selections=3, format_func=lambda c: varname.get(c, c), key="cmp_vars")
if picks:
    series = [(varname.get(c, c), data.variable_series(c, vstart)) for c in picks]
    ui.plot(ui.compare_chart(series), key="cmp_chart")
    st.markdown(f"<div class='src'>不同單位的指標不能直接放在同一個軸上，這裡把每個變項換算成「{vstart:%Y-%m-%d} 之後第一筆＝100」再比較；"
                "滑鼠移到線上可看原始數值。期間與上方「觀察期間」相同。來源："
                + "、".join(f"{varname.get(c, c)}－{lv.loc[c]['source']}" for c in picks) + "</div>", unsafe_allow_html=True)

# ═══════════════════════════ 6. 最新新聞 ═══════════════════════════
with st.expander("最新新聞（原始標題）"):
    nw = data.news(date.today() - timedelta(days=2), limit=30)
    for _, n in nw.iterrows():
        when = "" if pd.isna(n["published_at"]) else f"{n['published_at']:%m/%d %H:%M}"
        st.markdown(f"- [{n['title']}]({n['url']})　<span class='src'>{n['source_name'] or ''}｜{when}｜{n['collector']}</span>",
                    unsafe_allow_html=True)
