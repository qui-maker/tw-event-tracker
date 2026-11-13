"""早班：從新聞標題辨識重大事件，並寫入資料庫（寫入後不可修改）。"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date

from psycopg.types.json import Jsonb

from tracker.analysis.llm import generate_json
from tracker.analysis.prompts import COMMON_RULES, EVENTS_TASK, EventsOut
from tracker.config import DIRECTIONS, EVENT_TYPES, PROMPT_VERSION, TAIPEI, VARIABLES
from tracker.db import fetch_all, fetch_one, insert_ignore

MAX_NEWS = 180


def candidate_news(conn) -> list[dict]:
    """近 30 小時、還沒被歸到任何事件的新聞。各主題輪流挑，避免單一主題佔滿。"""
    rows = fetch_all(conn, """
        select id, title, source_name, country, published_at, topic, collector
        from news
        where fetched_at > now() - interval '30 hours'
          and id not in (select news_id from event_news)
        order by (collector = 'Fed RSS') desc, published_at desc nulls last
        limit 600""")
    by_topic: dict[str, list] = defaultdict(list)
    for r in rows:
        by_topic[r["topic"] or "其他"].append(r)
    picked, i = [], 0
    while len(picked) < MAX_NEWS and any(i < len(v) for v in by_topic.values()):
        for v in by_topic.values():
            if i < len(v) and len(picked) < MAX_NEWS:
                picked.append(v[i])
        i += 1
    return picked


def _news_line(r: dict) -> str:
    published = r["published_at"].astimezone(TAIPEI).strftime("%m/%d %H:%M") if r["published_at"] else "未知"
    return json.dumps({"id": r["id"], "標題": r["title"], "媒體": r["source_name"], "國家": r["country"],
                       "台北時間": published, "主題": r["topic"]}, ensure_ascii=False)


def analyze(conn, log, today: date) -> list[str]:
    news = candidate_news(conn)
    if len(news) < 5:
        log.error("事件分析", f"可用新聞只有 {len(news)} 則，略過 AI 分析")
        return []
    recent = fetch_all(conn, "select id, name, analysis_date from events where analysis_date >= %s - 5 order by analysis_date desc, id",
                       (today,))
    variables = "\n".join(f"{c}：{n}" for c, n, *_ in VARIABLES)
    recent_text = "\n".join(f"{e['id']}（{e['analysis_date']}）{e['name']}" for e in recent) or "（無）"
    prompt = EVENTS_TASK.format(variables=variables, recent=recent_text, today=today.isoformat(),
                                news="\n".join(_news_line(r) for r in news))
    out, model = generate_json(prompt, EventsOut, COMMON_RULES)

    valid_news = {r["id"]: r for r in news}
    recent_ids = {e["id"] for e in recent}
    codes = {v[0] for v in VARIABLES}
    start = (fetch_one(conn, "select count(*) as n from events where analysis_date = %s", (today,)) or {"n": 0})["n"]
    created = []
    for k, ev in enumerate(sorted(out.events, key=lambda e: -max(1, min(5, int(e.importance))))[:8], start=start + 1):
        facts, unconfirmed = [], list(ev.unconfirmed)
        for f in ev.facts:  # 事實一定要對得到新聞，否則降級為「未確認」
            ids = [i for i in f.news_ids if i in valid_news]
            if ids:
                facts.append({"text": f.text, "news_ids": ids})
            else:
                unconfirmed.append(f"{f.text}（找不到對應新聞，改列未確認）")
        news_ids = sorted({i for i in ev.news_ids if i in valid_news} | {i for f in facts for i in f["news_ids"]})
        if not news_ids:
            log.error("事件分析", f"事件「{ev.name}」沒有任何對應新聞，已捨棄")
            continue
        published = [valid_news[i]["published_at"] for i in news_ids if valid_news[i]["published_at"]]
        try:
            occurred = date.fromisoformat(ev.occurred_date) if ev.occurred_date else None
        except ValueError:
            occurred = None
        related = ev.related_event_id if ev.related_event_id in recent_ids else None
        event_id = f"EV-{today:%Y%m%d}-{k:02d}"
        row = {
            "id": event_id, "analysis_date": today, "name": ev.name[:200],
            "event_type": ev.event_type if ev.event_type in EVENT_TYPES else "其他",
            "occurred_date": occurred, "first_published_at": min(published) if published else None,
            "countries": [c for c in ev.countries if c][:10], "actors": [a for a in ev.actors if a][:15],
            "importance": max(1, min(5, int(ev.importance))), "importance_reason": ev.importance_reason,
            "summary": ev.summary, "direction": ev.direction if ev.direction in DIRECTIONS else "不確定",
            "status": "update" if (ev.status == "update" and related) else "new", "related_event_id": related,
            "facts": Jsonb(facts), "inferences": Jsonb(ev.inferences), "unconfirmed": Jsonb(unconfirmed),
            "data_gaps": Jsonb(ev.data_gaps),
            "affected_variables": [v for v in ev.affected_variables if v in codes],
            "affected_industries": [i for i in ev.affected_industries if i][:10],
            "affected_stocks": [],  # 第一版研究範圍是大盤，不做個股
            "pathway": Jsonb(ev.pathway[:6]), "model": model, "prompt_version": PROMPT_VERSION,
        }
        insert_ignore(conn, "events", [row], conflict="id")
        insert_ignore(conn, "event_news", [{"event_id": event_id, "news_id": i} for i in news_ids])
        created.append(event_id)
    conn.commit()
    log.add("events", len(created))
    return created
