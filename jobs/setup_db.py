"""建立／更新資料表，並寫入變項定義與證交所休市日。可以重複執行，不會刪除既有資料。

執行：python -m jobs.setup_db
"""
from pathlib import Path

from dotenv import load_dotenv

from tracker.collectors import twse
from tracker.collectors.macro import variable_definitions
from tracker.db import RunLog, connect, insert_ignore, step, upsert


def main():
    load_dotenv()
    conn = connect()
    schema = (Path(__file__).resolve().parent.parent / "db" / "schema.sql").read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(schema)
    conn.commit()
    print("✓ 資料表建立完成")
    with RunLog(conn, "setup_db") as log:
        with step(log, conn, "變項定義"):
            defs = variable_definitions()
            upsert(conn, "variables", defs, key="code",
                   update_cols=["name", "category", "unit", "frequency", "source", "source_series", "is_official", "display_order"])
            log.add("variables", len(defs))
        with step(log, conn, "證交所休市日"):
            log.add("trading_calendar", insert_ignore(conn, "trading_calendar", twse.holidays(), conflict="date"))


if __name__ == "__main__":
    main()
