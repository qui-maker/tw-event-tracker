-- ============================================================
-- 台股每日變化與世界重大事件追蹤器：資料庫結構
-- 執行方式：python -m jobs.setup_db（可重複執行，不會刪除既有資料）
-- ============================================================
-- 設計原則
-- 1. 每筆資料都保留來源（source / source_url）與取得時間（fetched_at）。
-- 2. 市場數據用「主鍵＋已存在就跳過」防止重複寫入。
-- 3. AI 的事件分析、事前預測與報告是研究紀錄：寫入後禁止修改或刪除（觸發器強制）。
-- 4. 網站只能讀取：開啟 RLS，只給 anon／authenticated 角色 SELECT 權限。
-- ============================================================

-- ---------- 交易日曆 ----------
create table if not exists trading_calendar (
    date            date primary key,
    is_trading_day  boolean not null,
    note            text,
    source          text,
    updated_at      timestamptz not null default now()
);
comment on table trading_calendar is '台股交易日曆。休市日來自證交所休市公告；交易日來自實際成交資料。';

-- ---------- 指數日資料（加權、櫃買、類股） ----------
create table if not exists index_daily (
    index_code    text not null,          -- TAIEX、TPEX、IDX_ 開頭為類股指數
    trade_date    date not null,
    name          text,
    close         numeric,
    change        numeric,                -- 漲跌點數
    change_pct    numeric,                -- 漲跌幅（%）
    trade_value   numeric,                -- 成交金額（新台幣元；加權指數以證交所 FMTQIK 為唯一口徑）
    trade_volume  numeric,                -- 成交股數
    transactions  numeric,                -- 成交筆數
    source        text not null,
    source_url    text,
    fetched_at    timestamptz not null default now(),
    primary key (index_code, trade_date)
);
create index if not exists index_daily_date_idx on index_daily (trade_date desc);

-- ---------- 市場寬度（上漲、下跌家數） ----------
create table if not exists market_breadth (
    trade_date   date not null,
    market       text not null,           -- TWSE（上市）
    advances     integer,
    declines     integer,
    unchanged    integer,
    limit_up     integer,
    limit_down   integer,
    source       text not null,
    source_url   text,
    fetched_at   timestamptz not null default now(),
    primary key (trade_date, market)
);

-- ---------- 三大法人買賣超 ----------
create table if not exists institutional_flows (
    trade_date  date not null,
    investor    text not null,            -- 外資及陸資、投信、自營商、合計 …（照證交所原始名稱）
    buy         numeric,                  -- 新台幣元
    sell        numeric,
    net         numeric,
    source      text not null,
    source_url  text,
    fetched_at  timestamptz not null default now(),
    primary key (trade_date, investor)
);

-- ---------- 股票基本資料與日行情 ----------
create table if not exists stocks (
    code          text primary key,
    name          text,
    market        text,                   -- TWSE（上市）／TPEX（上櫃）
    industry      text,
    is_watchlist  boolean not null default false,
    updated_at    timestamptz not null default now()
);

create table if not exists stock_daily (
    code          text not null,
    trade_date    date not null,
    open          numeric,
    high          numeric,
    low           numeric,
    close         numeric,
    change        numeric,
    change_pct    numeric,
    volume        numeric,                -- 成交股數
    value         numeric,                -- 成交金額（元）
    transactions  numeric,
    source        text not null,
    fetched_at    timestamptz not null default now(),
    primary key (code, trade_date)
);
create index if not exists stock_daily_date_idx on stock_daily (trade_date desc);

-- ---------- 公司重大訊息 ----------
create table if not exists announcements (
    id             bigserial primary key,
    code           text,
    name           text,
    announce_date  date,
    announce_time  text,
    subject        text not null,
    content        text,
    market         text,
    source         text not null,
    source_url     text,
    fetched_at     timestamptz not null default now(),
    unique (code, announce_date, subject)
);
create index if not exists announcements_date_idx on announcements (announce_date desc);

-- ---------- 經濟與市場變項 ----------
create table if not exists variables (
    code           text primary key,      -- 例如 US10Y、SOX
    name           text not null,
    category       text not null,         -- 利率、匯率、原物料、美國經濟數據、國際股市
    unit           text,
    frequency      text,                  -- 日、週、月
    source         text not null,         -- FRED／Yahoo Finance（非官方）
    source_series  text,                  -- 來源端的代碼，例如 FRED 的 DGS10
    is_official    boolean not null default true,
    description    text,
    display_order  integer
);

create table if not exists variable_values (
    variable_code  text not null references variables(code),
    obs_date       date not null,
    value          numeric not null,
    source         text not null,
    source_url     text,
    fetched_at     timestamptz not null default now(),
    primary key (variable_code, obs_date)
);
create index if not exists variable_values_date_idx on variable_values (obs_date desc);

-- ---------- 新聞（原始資料） ----------
create table if not exists news (
    id                 bigserial primary key,
    url                text not null unique,      -- 以網址去重
    title              text not null,
    source_name        text,                      -- 媒體網域或名稱
    language           text,
    country            text,
    published_at       timestamptz,
    fetched_at         timestamptz not null default now(),
    topic              text,                      -- 蒐集時使用的主題
    collector          text not null,             -- GDELT／Fed RSS
    title_fingerprint  text                        -- 標題正規化後的指紋，用來找出不同網址的相同新聞
);
create index if not exists news_published_idx on news (published_at desc);
create index if not exists news_fingerprint_idx on news (title_fingerprint);

-- ---------- 重大事件（AI 分析，研究紀錄） ----------
create table if not exists events (
    id                  text primary key,          -- EV-YYYYMMDD-NN
    analysis_date       date not null,             -- 台北時間的分析日期
    name                text not null,
    event_type          text not null check (event_type in
                          ('貨幣政策','財政政策','國際貿易','地緣政治','科技發展',
                           '產業供需','能源及原物料','國際金融市場','其他')),
    occurred_date       date,                      -- 事件發生日期（可能不明）
    first_published_at  timestamptz,               -- 相關新聞中最早的發布時間
    countries           text[] not null default '{}',
    actors              text[] not null default '{}',
    importance          smallint check (importance between 1 and 5),
    importance_reason   text,
    summary             text,
    direction           text check (direction in ('正面','負面','中性','不確定')),   -- 對台股大盤的可能方向
    status              text not null default 'new' check (status in ('new','update')),
    related_event_id    text references events(id),
    facts               jsonb not null default '[]',  -- [{text, news_ids}]，每一條都要對應到新聞
    inferences          jsonb not null default '[]',
    unconfirmed         jsonb not null default '[]',
    data_gaps           jsonb not null default '[]',
    affected_variables  text[] not null default '{}',
    affected_industries text[] not null default '{}',
    affected_stocks     text[] not null default '{}',
    pathway             jsonb not null default '[]',  -- 傳導路徑節點，例如 ["事件","美國利率","金融業","加權指數"]
    model               text,
    prompt_version      text,
    created_at          timestamptz not null default now()
);
create index if not exists events_date_idx on events (analysis_date desc);

create table if not exists event_news (
    event_id  text not null references events(id),
    news_id   bigint not null references news(id),
    primary key (event_id, news_id)
);

-- ---------- 事前預測（研究紀錄） ----------
create table if not exists predictions (
    id                  text primary key,          -- PR-YYYYMMDD-AI / PR-YYYYMMDD-BASE
    kind                text not null check (kind in ('ai','baseline')),
    target_code         text not null default 'TAIEX',
    target_trading_day  date not null,
    direction           text not null check (direction in ('上漲','下跌')),
    confidence          text check (confidence in ('低','中','高')),
    rationale           text,
    drivers             jsonb not null default '[]',   -- [{source, effect, reason}]
    pathways            jsonb not null default '[]',   -- [[節點, 節點, …], …]
    counterpoints       jsonb not null default '[]',
    event_ids           text[] not null default '{}',
    inputs              jsonb not null default '{}',   -- 做判斷時看到的數據（含日期與來源）
    is_ex_ante          boolean not null,              -- 是否在目標交易日 09:00 前寫入
    model               text,
    prompt_version      text,
    created_at          timestamptz not null default now(),
    unique (kind, target_code, target_trading_day)
);

-- ---------- 事後評估 ----------
create table if not exists evaluations (
    prediction_id      text not null references predictions(id),
    method_version     text not null,               -- 評估規則版本（v1 見決策紀錄）
    actual_change_pct  numeric,
    actual_direction   text,
    abs_grade          smallint,
    abs_grade_label    text,
    z_score            numeric,
    rel_grade_label    text,
    result             text not null check (result in ('命中','未命中','無法判定')),
    note               text,
    evaluated_at       timestamptz not null default now(),
    primary key (prediction_id, method_version)
);

-- ---------- 報告（研究紀錄） ----------
create table if not exists reports (
    id            bigserial primary key,
    kind          text not null check (kind in ('daily','weekly','monthly')),
    period_key    text not null,                 -- 2026-11-13 ／ 2026-W46 ／ 2026-11
    version       integer not null default 1,    -- 同一期重跑時另存新版本
    title         text not null,
    summary       text,
    content_md    text not null,
    sections      jsonb not null default '{}',
    model         text,
    generated_at  timestamptz not null default now(),
    unique (kind, period_key, version)
);

-- ---------- 執行紀錄 ----------
create table if not exists pipeline_runs (
    id            bigserial primary key,
    job           text not null,
    started_at    timestamptz not null default now(),
    finished_at   timestamptz,
    status        text not null default 'running' check (status in ('running','success','partial','failed')),
    rows_written  jsonb not null default '{}',
    errors        jsonb not null default '[]',
    environment   text,
    git_sha       text
);
create index if not exists pipeline_runs_started_idx on pipeline_runs (started_at desc);

-- ============================================================
-- 研究紀錄不可修改：events、predictions、reports 禁止 UPDATE 與 DELETE
-- ============================================================
create or replace function forbid_research_record_change() returns trigger
language plpgsql as $$
begin
    raise exception '研究紀錄不可修改或刪除（資料表：%）。若要更正，請新增一筆並說明更正哪一筆。', tg_table_name;
end;
$$;

do $$
declare t text;
begin
    foreach t in array array['events','predictions','reports','event_news'] loop
        execute format('drop trigger if exists %I_immutable on %I', t, t);
        execute format('create trigger %I_immutable before update or delete on %I
                        for each row execute function forbid_research_record_change()', t, t);
    end loop;
end $$;

-- ============================================================
-- 網站唯讀權限（Supabase 的 anon／authenticated 角色）
-- ============================================================
do $$
declare t text;
begin
    for t in select tablename from pg_tables where schemaname = 'public' loop
        execute format('alter table %I enable row level security', t);
        execute format('drop policy if exists public_read on %I', t);
        execute format('create policy public_read on %I for select to anon, authenticated using (true)', t);
    end loop;
end $$;

grant usage on schema public to anon, authenticated;
grant select on all tables in schema public to anon, authenticated;
revoke insert, update, delete, truncate on all tables in schema public from anon, authenticated;
