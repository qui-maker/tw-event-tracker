"""資料庫存取（排程程式使用；網站改用 Supabase 唯讀金鑰，見 app/data.py）。

連線字串放在環境變數 DATABASE_URL（GitHub Secrets／本機 .env），程式碼裡不寫任何密碼。
"""
from __future__ import annotations

import json
import os
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg.types.numeric import FloatLoader
from psycopg.types.json import Jsonb


def connect() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("沒有設定 DATABASE_URL（請在 .env 或 GitHub Secrets 設定）")
    # prepare_threshold=None：關閉預備語句，讓 Supabase 的連線池（pooler）也能正常使用
    conn = psycopg.connect(url, autocommit=False, prepare_threshold=None, connect_timeout=20)
    conn.adapters.register_loader("numeric", FloatLoader)  # 數字一律用一般小數，方便計算
    return conn


def insert_ignore(conn, table: str, rows: list[dict], conflict: str | None = None) -> int:
    """批次寫入，已存在（主鍵或唯一鍵衝突）的資料直接跳過，不覆蓋。回傳實際新增筆數。"""
    if not rows:
        return 0
    cols = list(rows[0].keys())
    placeholders = ", ".join(["%s"] * len(cols))
    target = f"({conflict})" if conflict else ""
    sql = (f"insert into {table} ({', '.join(cols)}) values ({placeholders}) "
           f"on conflict {target} do nothing")
    # executemany 會用 pipeline 模式一次送出多筆，避免每筆都等一次網路往返
    # （GitHub 主機在美國、資料庫在東京，逐筆寫入上萬筆會花半小時以上）
    with conn.cursor() as cur:
        cur.executemany(sql, [[adapt(row[c]) for c in cols] for row in rows])
        return max(cur.rowcount, 0)


def upsert(conn, table: str, rows: list[dict], key: str, update_cols: list[str]) -> int:
    """只用在「非研究紀錄」的參考資料（例如股票名稱、變項定義），有就更新、沒有就新增。"""
    if not rows:
        return 0
    cols = list(rows[0].keys())
    placeholders = ", ".join(["%s"] * len(cols))
    sets = ", ".join(f"{c} = excluded.{c}" for c in update_cols)
    sql = (f"insert into {table} ({', '.join(cols)}) values ({placeholders}) "
           f"on conflict ({key}) do update set {sets}")
    with conn.cursor() as cur:
        cur.executemany(sql, [[adapt(row[c]) for c in cols] for row in rows])
    return len(rows)


def adapt(value):
    """dict／list（非字串陣列）轉成 JSONB；字串陣列維持 Postgres 陣列。"""
    if isinstance(value, dict):
        return Jsonb(value)
    if isinstance(value, list) and value and not all(isinstance(v, str) for v in value):
        return Jsonb(value)
    return value


def fetch_all(conn, sql: str, params=None) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fetch_one(conn, sql: str, params=None) -> dict | None:
    rows = fetch_all(conn, sql, params)
    return rows[0] if rows else None


# ─────────────────────────────────────────────
# 執行紀錄
# ─────────────────────────────────────────────
class RunLog:
    """記錄一次排程的開始、結束、寫入筆數與錯誤。

    用法：
        with RunLog(conn, "evening") as log:
            log.add("index_daily", 12)
            log.error("TPEx", "連線逾時")
    """

    def __init__(self, conn, job: str):
        self.conn, self.job = conn, job
        self.rows: dict[str, int] = {}
        self.errors: list[dict] = []
        self.id = None

    def __enter__(self):
        env = "GitHub Actions" if os.getenv("GITHUB_ACTIONS") == "true" else "本機"
        sha = os.getenv("GITHUB_SHA") or _git_sha()
        row = fetch_one(self.conn, "insert into pipeline_runs (job, environment, git_sha) values (%s, %s, %s) returning id",
                        (self.job, env, sha))
        self.conn.commit()
        self.id = row["id"]
        print(f"▶ 開始 {self.job}（執行紀錄 #{self.id}）")
        return self

    def add(self, key: str, n: int):
        self.rows[key] = self.rows.get(key, 0) + int(n or 0)
        print(f"  ✓ {key}：+{n}")

    def error(self, step: str, message: str):
        self.errors.append({"step": step, "message": str(message)[:1000],
                            "at": datetime.now(timezone.utc).isoformat()})
        print(f"  ✗ {step}：{str(message)[:300]}")

    def __exit__(self, exc_type, exc, tb):
        if exc is not None:
            self.conn.rollback()
            self.error("未預期的錯誤", f"{exc_type.__name__}: {exc}")
        status = "failed" if exc is not None else ("partial" if self.errors else "success")
        with self.conn.cursor() as cur:
            cur.execute("update pipeline_runs set finished_at = now(), status = %s, rows_written = %s, errors = %s "
                        "where id = %s", (status, Jsonb(self.rows), Jsonb(self.errors), self.id))
        self.conn.commit()
        print(f"■ 結束 {self.job}：{status}；寫入 {json.dumps(self.rows, ensure_ascii=False)}；錯誤 {len(self.errors)} 個")
        return False  # 讓例外照常往外拋，GitHub Actions 才會顯示失敗


@contextmanager
def step(log: RunLog, conn, name: str):
    """包住一個步驟：失敗時記錄錯誤並回滾這一步，但不中斷整個排程。"""
    try:
        yield
        conn.commit()
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        log.error(name, f"{type(e).__name__}: {e}")


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:  # noqa: BLE001
        return None
