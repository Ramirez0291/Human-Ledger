"""开发辅助：打印当前数据库的表结构与行数概览。

用法：backend/.venv/Scripts/python.exe scripts/inspect_db.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import engine  # noqa: E402


def main() -> None:
    print(f"数据库：{settings.resolved_database_url}\n")
    insp = inspect(engine)
    tables = sorted(insp.get_table_names())
    with engine.connect() as conn:
        for t in tables:
            cols = insp.get_columns(t)
            n = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            print(f"{t:24} {len(cols):>3} 列  {n:>5} 行")
    print(f"\n共 {len(tables)} 张表")


if __name__ == "__main__":
    main()
