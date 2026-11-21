"""Схема БД: обмеження цілісності, індекси, транзакції, захист від ін'єкцій."""

import sqlite3

import pytest

from greenhouse.db import connect, init_schema, transaction


def test_schema_is_idempotent(conn):
    init_schema(conn)
    count = conn.execute("SELECT COUNT(*) FROM sensor_type").fetchone()[0]
    assert count == 5


def test_file_database_creates_parent_dir(tmp_path):
    db_file = tmp_path / "nested" / "dir" / "test.db"
    connection = connect(db_file)
    init_schema(connection)
    connection.close()
    assert db_file.exists()


def test_foreign_keys_enabled(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_foreign_key_violation_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO sensor (greenhouse_id, sensor_type_id, name) VALUES (999, 1, 'x')"
        )


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO greenhouse (name) VALUES ('   ')",
        "INSERT INTO sensor_type (code, name, unit, min_valid, max_valid) VALUES ('x','x','x',5,5)",
        "INSERT INTO alert (reading_id, level, message) VALUES (1, 'fatal', 'x')",
    ],
)
def test_check_constraints(conn, sql):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql)


def test_indexes_exist(conn):
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {
        "idx_sensor_greenhouse",
        "idx_sensor_type",
        "idx_reading_sensor_time",
        "idx_alert_acknowledged",
    } <= names


def test_reading_query_uses_index(conn):
    plan = conn.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM reading WHERE sensor_id = ? ORDER BY recorded_at DESC",
        (1,),
    ).fetchall()
    assert any("idx_reading_sensor_time" in row[3] for row in plan)


def test_transaction_commits(conn):
    with transaction(conn):
        conn.execute("INSERT INTO greenhouse (name) VALUES ('A')")
    assert conn.execute("SELECT COUNT(*) FROM greenhouse").fetchone()[0] == 1


def test_transaction_rolls_back_on_error(conn):
    with pytest.raises(RuntimeError):
        with transaction(conn):
            conn.execute("INSERT INTO greenhouse (name) VALUES ('A')")
            raise RuntimeError("збій посеред транзакції")
    assert conn.execute("SELECT COUNT(*) FROM greenhouse").fetchone()[0] == 0
    assert not conn.in_transaction


def test_nested_transaction_joins_outer(conn):
    with pytest.raises(RuntimeError):
        with transaction(conn):
            with transaction(conn):
                conn.execute("INSERT INTO greenhouse (name) VALUES ('A')")
            raise RuntimeError("збій у зовнішній транзакції")
    assert conn.execute("SELECT COUNT(*) FROM greenhouse").fetchone()[0] == 0


def test_cascade_delete(repo, service):
    item = service.create_demo_greenhouse()
    sensor = repo.list_sensors(item.id)[0]
    service.record_reading(sensor.id, 22)
    repo.delete_greenhouse(item.id)
    for table in ("sensor", "threshold", "reading"):
        assert repo.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_sql_injection_is_stored_as_text(repo):
    payload = "x'); DROP TABLE greenhouse; --"
    item = repo.add_greenhouse(payload)
    assert repo.get_greenhouse(item.id).name == payload
    assert repo.find_greenhouse_by_name(payload) is not None
    assert len(repo.list_greenhouses()) == 1
