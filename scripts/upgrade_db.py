"""给**已存在**的 SQLite 数据库补 M4 新增列。

为什么需要这个脚本：`Base.metadata.create_all()` 只建"不存在的表"，不会给已有表加列。
线上/本地已有 app.db 时直接跑新代码会报 `no such column: documents.text`。
（真上生产应该用 Alembic；这里一个幂等的小脚本就够，也避免为 2 个列引一整套迁移框架。）

用法：
    python3 scripts/upgrade_db.py            # 默认 sqlite:///./app.db
    python3 scripts/upgrade_db.py path/to/app.db
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# 允许 `python3 scripts/upgrade_db.py` 直接跑（脚本所在目录不在 sys.path 里）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 表 -> {列名: SQL 类型}
NEW_COLUMNS: dict[str, dict[str, str]] = {
    "documents": {"text": "TEXT", "error_message": "VARCHAR(255)"},
}


def _sqlite_path(database_url: str) -> str:
    if not database_url.startswith("sqlite"):
        raise SystemExit(f"只支持 sqlite，当前 DATABASE_URL={database_url}")
    return database_url.split("///")[-1]


def upgrade(db_path: str) -> list[str]:
    path = Path(db_path)
    if not path.exists():
        return [f"跳过：{db_path} 不存在（新库直接 create_all 建全即可）"]

    applied: list[str] = []
    connection = sqlite3.connect(path)
    try:
        for table, columns in NEW_COLUMNS.items():
            existing = {
                row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if not existing:
                applied.append(f"跳过：表 {table} 不存在")
                continue
            for name, sql_type in columns.items():
                if name in existing:
                    continue
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
                applied.append(f"已添加 {table}.{name} {sql_type}")
        connection.commit()
    finally:
        connection.close()
    return applied


def main() -> None:
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        from app.core.config import settings

        db_path = _sqlite_path(settings.database_url)

    for line in upgrade(db_path):
        print(line)
    print(f"完成：{db_path}")


if __name__ == "__main__":
    main()
