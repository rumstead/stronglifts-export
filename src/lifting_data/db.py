from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    schema_sql = resources.files("lifting_data").joinpath("schema.sql").read_text(encoding="utf-8")
    connection.executescript(schema_sql)
    set_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(sets)").fetchall()
    }
    if "set_type" not in set_columns:
        connection.execute(
            "ALTER TABLE sets ADD COLUMN set_type TEXT NOT NULL DEFAULT 'normal'"
        )
    connection.commit()
