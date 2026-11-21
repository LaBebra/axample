"""Підключення до SQLite, ініціалізація схеми та транзакції."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

MEMORY = ":memory:"


def connect(db_path: str | Path = MEMORY) -> sqlite3.Connection:
    """Відкриває з'єднання з увімкненими зовнішніми ключами.

    isolation_level=None вимикає неявні транзакції модуля sqlite3,
    тому транзакціями керуємо явно через transaction().
    """
    if str(db_path) != MEMORY:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Створює таблиці та довідники, якщо їх ще немає (ідемпотентно)."""
    sql = resources.files("greenhouse").joinpath("schema.sql").read_text(encoding="utf-8")
    conn.executescript(sql)


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Атомарний блок: COMMIT при успіху, ROLLBACK при будь-якому винятку.

    Якщо транзакція вже відкрита, вкладений блок приєднується до неї.
    """
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
