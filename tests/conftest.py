"""Спільні фікстури: кожен тест працює з окремою БД у пам'яті."""
# pylint: disable=redefined-outer-name  # pytest-фікстури передаються як аргументи

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from greenhouse.db import connect, init_schema
from greenhouse.models import Greenhouse, Threshold
from greenhouse.repository import Repository
from greenhouse.service import MonitoringService


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = connect()
    init_schema(connection)
    yield connection
    connection.close()


@pytest.fixture
def repo(conn: sqlite3.Connection) -> Repository:
    return Repository(conn)


@pytest.fixture
def service(repo: Repository) -> MonitoringService:
    return MonitoringService(repo)


@pytest.fixture
def greenhouse(repo: Repository) -> Greenhouse:
    item = repo.add_greenhouse("Тестова", "Київ")
    repo.set_threshold(item.id, "temperature", Threshold(18, 28))
    return item
