"""Налаштування застосунку (шляхи до БД і лог-файлу)."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_DIR / "data" / "greenhouse.db"
DEFAULT_LOG_PATH = PROJECT_DIR / "logs" / "greenhouse.log"


def get_db_path() -> Path:
    """Шлях до БД: змінна середовища GREENHOUSE_DB або значення за замовчуванням."""
    return Path(os.environ.get("GREENHOUSE_DB", str(DEFAULT_DB_PATH)))


def get_log_path() -> Path:
    """Шлях до лог-файлу: змінна середовища GREENHOUSE_LOG або значення за замовчуванням."""
    return Path(os.environ.get("GREENHOUSE_LOG", str(DEFAULT_LOG_PATH)))
