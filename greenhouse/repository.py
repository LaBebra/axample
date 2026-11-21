"""Шар доступу до даних. Усі SQL-запити параметризовані (захист від ін'єкцій)."""

from __future__ import annotations

import sqlite3

from greenhouse.models import (
    Alert,
    AlertView,
    DuplicateError,
    Greenhouse,
    NotFoundError,
    Reading,
    Sensor,
    SensorType,
    Status,
    Threshold,
    validate_name,
)

_SENSOR_SELECT = """
    SELECT s.id, s.greenhouse_id, s.name, s.is_active,
           t.id AS type_id, t.code, t.name AS type_name, t.unit, t.min_valid, t.max_valid
    FROM sensor AS s
    JOIN sensor_type AS t ON t.id = s.sensor_type_id
"""


def _sensor_type_from_row(row: sqlite3.Row, prefix: str = "") -> SensorType:
    return SensorType(
        id=row[f"{prefix}id"],
        code=row["code"],
        name=row[f"{prefix}name"],
        unit=row["unit"],
        min_valid=row["min_valid"],
        max_valid=row["max_valid"],
    )


def _sensor_from_row(row: sqlite3.Row) -> Sensor:
    return Sensor(
        id=row["id"],
        greenhouse_id=row["greenhouse_id"],
        sensor_type=_sensor_type_from_row(row, prefix="type_"),
        name=row["name"],
        is_active=bool(row["is_active"]),
    )


def _greenhouse_from_row(row: sqlite3.Row) -> Greenhouse:
    return Greenhouse(
        id=row["id"], name=row["name"], location=row["location"], created_at=row["created_at"]
    )


class Repository:
    """CRUD-операції над сутностями теплиці."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ---------- Типи датчиків ----------

    def list_sensor_types(self) -> list[SensorType]:
        """Усі типи датчиків з довідника."""
        rows = self.conn.execute(
            "SELECT id, code, name, unit, min_valid, max_valid FROM sensor_type ORDER BY id"
        ).fetchall()
        return [_sensor_type_from_row(row) for row in rows]

    def get_sensor_type(self, code: str) -> SensorType:
        """Тип датчика за кодом."""
        row = self.conn.execute(
            "SELECT id, code, name, unit, min_valid, max_valid FROM sensor_type WHERE code = ?",
            (code,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"Невідомий тип датчика: '{code}'")
        return _sensor_type_from_row(row)

    # ---------- Теплиці ----------

    def add_greenhouse(self, name: str, location: str | None = None) -> Greenhouse:
        """Створює теплицю з унікальною назвою."""
        clean_name = validate_name(name)
        clean_location = validate_name(location, "location") if location else None
        try:
            cursor = self.conn.execute(
                "INSERT INTO greenhouse (name, location) VALUES (?, ?)",
                (clean_name, clean_location),
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(f"Теплиця '{clean_name}' вже існує") from exc
        return self.get_greenhouse(int(cursor.lastrowid))

    def get_greenhouse(self, greenhouse_id: int) -> Greenhouse:
        """Теплиця за ідентифікатором."""
        row = self.conn.execute(
            "SELECT id, name, location, created_at FROM greenhouse WHERE id = ?",
            (greenhouse_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"Теплицю з id={greenhouse_id} не знайдено")
        return _greenhouse_from_row(row)

    def find_greenhouse_by_name(self, name: str) -> Greenhouse | None:
        """Теплиця за назвою або None."""
        row = self.conn.execute(
            "SELECT id, name, location, created_at FROM greenhouse WHERE name = ?",
            (name.strip(),),
        ).fetchone()
        return _greenhouse_from_row(row) if row else None

    def list_greenhouses(self) -> list[Greenhouse]:
        """Усі теплиці."""
        rows = self.conn.execute(
            "SELECT id, name, location, created_at FROM greenhouse ORDER BY id"
        ).fetchall()
        return [_greenhouse_from_row(row) for row in rows]

    def delete_greenhouse(self, greenhouse_id: int) -> None:
        """Видаляє теплицю разом з датчиками, порогами, вимірами (ON DELETE CASCADE)."""
        cursor = self.conn.execute("DELETE FROM greenhouse WHERE id = ?", (greenhouse_id,))
        if cursor.rowcount == 0:
            raise NotFoundError(f"Теплицю з id={greenhouse_id} не знайдено")

    # ---------- Датчики ----------

    def add_sensor(self, greenhouse_id: int, type_code: str, name: str) -> Sensor:
        """Додає датчик заданого типу в теплицю."""
        clean_name = validate_name(name)
        self.get_greenhouse(greenhouse_id)
        sensor_type = self.get_sensor_type(type_code)
        try:
            cursor = self.conn.execute(
                "INSERT INTO sensor (greenhouse_id, sensor_type_id, name) VALUES (?, ?, ?)",
                (greenhouse_id, sensor_type.id, clean_name),
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(
                f"Датчик '{clean_name}' вже існує в теплиці id={greenhouse_id}"
            ) from exc
        return self.get_sensor(int(cursor.lastrowid))

    def get_sensor(self, sensor_id: int) -> Sensor:
        """Датчик за ідентифікатором."""
        row = self.conn.execute(_SENSOR_SELECT + " WHERE s.id = ?", (sensor_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Датчик з id={sensor_id} не знайдено")
        return _sensor_from_row(row)

    def list_sensors(self, greenhouse_id: int, only_active: bool = False) -> list[Sensor]:
        """Датчики теплиці."""
        query = _SENSOR_SELECT + " WHERE s.greenhouse_id = ?"
        if only_active:
            query += " AND s.is_active = 1"
        rows = self.conn.execute(query + " ORDER BY s.id", (greenhouse_id,)).fetchall()
        return [_sensor_from_row(row) for row in rows]

    def set_sensor_active(self, sensor_id: int, active: bool) -> None:
        """Вмикає або вимикає датчик."""
        cursor = self.conn.execute(
            "UPDATE sensor SET is_active = ? WHERE id = ?", (int(active), sensor_id)
        )
        if cursor.rowcount == 0:
            raise NotFoundError(f"Датчик з id={sensor_id} не знайдено")

    # ---------- Пороги ----------

    def set_threshold(self, greenhouse_id: int, type_code: str, threshold: Threshold) -> None:
        """Встановлює або оновлює оптимальний діапазон показника для теплиці."""
        self.get_greenhouse(greenhouse_id)
        sensor_type = self.get_sensor_type(type_code)
        self.conn.execute(
            """
            INSERT INTO threshold (greenhouse_id, sensor_type_id, min_value, max_value)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (greenhouse_id, sensor_type_id)
            DO UPDATE SET min_value = excluded.min_value, max_value = excluded.max_value
            """,
            (greenhouse_id, sensor_type.id, threshold.min_value, threshold.max_value),
        )

    def get_threshold(self, greenhouse_id: int, type_code: str) -> Threshold | None:
        """Оптимальний діапазон або None, якщо його не задано."""
        row = self.conn.execute(
            """
            SELECT th.min_value, th.max_value
            FROM threshold AS th
            JOIN sensor_type AS t ON t.id = th.sensor_type_id
            WHERE th.greenhouse_id = ? AND t.code = ?
            """,
            (greenhouse_id, type_code),
        ).fetchone()
        if row is None:
            return None
        return Threshold(row["min_value"], row["max_value"])

    # ---------- Виміри ----------

    def insert_reading(self, sensor_id: int, value: float, recorded_at: str) -> Reading:
        """Зберігає вимір (значення вже має бути провалідоване сервісом)."""
        cursor = self.conn.execute(
            "INSERT INTO reading (sensor_id, value, recorded_at) VALUES (?, ?, ?)",
            (sensor_id, value, recorded_at),
        )
        return Reading(int(cursor.lastrowid), sensor_id, value, recorded_at)

    def latest_readings(self, sensor_id: int, limit: int = 10) -> list[Reading]:
        """Останні виміри датчика, від найстарішого до найновішого."""
        rows = self.conn.execute(
            """
            SELECT id, sensor_id, value, recorded_at FROM reading
            WHERE sensor_id = ?
            ORDER BY recorded_at DESC, id DESC
            LIMIT ?
            """,
            (sensor_id, limit),
        ).fetchall()
        return [
            Reading(row["id"], row["sensor_id"], row["value"], row["recorded_at"])
            for row in reversed(rows)
        ]

    def count_readings(self, sensor_id: int) -> int:
        """Кількість вимірів датчика."""
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM reading WHERE sensor_id = ?", (sensor_id,)
        ).fetchone()
        return int(row["n"])

    # ---------- Сповіщення ----------

    def insert_alert(self, reading_id: int, level: Status, message: str) -> Alert:
        """Створює сповіщення для виміру."""
        cursor = self.conn.execute(
            "INSERT INTO alert (reading_id, level, message) VALUES (?, ?, ?)",
            (reading_id, level.value, message),
        )
        return Alert(int(cursor.lastrowid), reading_id, level, message, False)

    def list_alerts(
        self,
        greenhouse_id: int | None = None,
        only_unacknowledged: bool = False,
        limit: int = 50,
    ) -> list[AlertView]:
        """Сповіщення з назвою датчика і теплиці, від найновіших."""
        conditions = []
        params: list[object] = []
        if greenhouse_id is not None:
            conditions.append("g.id = ?")
            params.append(greenhouse_id)
        if only_unacknowledged:
            conditions.append("a.acknowledged = 0")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        rows = self.conn.execute(
            f"""
            SELECT a.id, a.level, a.message, a.acknowledged, r.recorded_at,
                   s.name AS sensor_name, g.name AS greenhouse_name
            FROM alert AS a
            JOIN reading AS r ON r.id = a.reading_id
            JOIN sensor AS s ON s.id = r.sensor_id
            JOIN greenhouse AS g ON g.id = s.greenhouse_id
            {where}
            ORDER BY r.recorded_at DESC, a.id DESC
            LIMIT ?
            """,  # nosec B608 - where збирається з констант, значення йдуть параметрами
            params,
        ).fetchall()
        return [
            AlertView(
                id=row["id"],
                level=Status(row["level"]),
                message=row["message"],
                acknowledged=bool(row["acknowledged"]),
                recorded_at=row["recorded_at"],
                sensor_name=row["sensor_name"],
                greenhouse_name=row["greenhouse_name"],
            )
            for row in rows
        ]

    def acknowledge_alert(self, alert_id: int) -> None:
        """Позначає сповіщення як прочитане."""
        cursor = self.conn.execute(
            "UPDATE alert SET acknowledged = 1 WHERE id = ?", (alert_id,)
        )
        if cursor.rowcount == 0:
            raise NotFoundError(f"Сповіщення з id={alert_id} не знайдено")
