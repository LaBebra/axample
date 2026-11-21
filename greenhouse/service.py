"""Бізнес-логіка моніторингу: прийом вимірів, сповіщення, стан теплиці."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from greenhouse import analyzer
from greenhouse.analyzer import Trend
from greenhouse.db import transaction
from greenhouse.logging_setup import LOGGER_NAME
from greenhouse.models import (
    Alert,
    Greenhouse,
    Reading,
    Sensor,
    Status,
    Threshold,
    ValidationError,
    normalize_timestamp,
    parse_timestamp,
    validate_reading_value,
)
from greenhouse.repository import Repository
from greenhouse.simulator import SensorSimulator

logger = logging.getLogger(LOGGER_NAME)

MAX_SIMULATION_STEPS = 10_000

# Рекомендовані діапазони для томатів (демо-дані).
DEMO_SENSORS: tuple[tuple[str, str], ...] = (
    ("temperature", "Термометр-1"),
    ("air_humidity", "Гігрометр-1"),
    ("soil_moisture", "Ґрунт-1"),
    ("light", "Люксметр-1"),
    ("co2", "CO2-1"),
)
DEMO_THRESHOLDS: dict[str, Threshold] = {
    "temperature": Threshold(18, 27),
    "air_humidity": Threshold(60, 80),
    "soil_moisture": Threshold(45, 70),
    "co2": Threshold(400, 1200),
}


@dataclass(frozen=True)
class RecordResult:
    """Результат прийому одного виміру."""

    sensor: Sensor
    reading: Reading
    status: Status
    alert: Alert | None


@dataclass(frozen=True)
class SensorStatus:
    """Поточний стан датчика для зведення по теплиці."""

    sensor: Sensor
    latest: Reading | None
    threshold: Threshold | None
    status: Status
    trend: Trend


class MonitoringService:
    """Фасад над репозиторієм та аналізатором."""

    def __init__(
        self,
        repo: Repository,
        critical_margin: float = analyzer.DEFAULT_CRITICAL_MARGIN,
    ) -> None:
        self.repo = repo
        self.critical_margin = critical_margin

    def record_reading(
        self,
        sensor_id: int,
        value: object,
        recorded_at: datetime | str | None = None,
    ) -> RecordResult:
        """Валідує та зберігає вимір; при відхиленні від норми створює сповіщення.

        Вимір і сповіщення записуються в одній транзакції: або обидва, або жоден.
        """
        sensor = self.repo.get_sensor(sensor_id)
        if not sensor.is_active:
            raise ValidationError(f"Датчик '{sensor.name}' вимкнено, вимір не прийнято")
        number = validate_reading_value(value, sensor.sensor_type)
        timestamp = normalize_timestamp(recorded_at)
        threshold = self.repo.get_threshold(sensor.greenhouse_id, sensor.sensor_type.code)
        status = analyzer.evaluate(number, threshold, self.critical_margin)

        alert = None
        with transaction(self.repo.conn):
            reading = self.repo.insert_reading(sensor.id, number, timestamp)
            if status is not Status.OK and threshold is not None:
                message = analyzer.build_message(
                    sensor.name, sensor.sensor_type, number, threshold, status
                )
                alert = self.repo.insert_alert(reading.id, status, message)
                logger.warning("Сповіщення #%s: %s", alert.id, message)
        return RecordResult(sensor, reading, status, alert)

    def simulate(
        self,
        greenhouse_id: int,
        simulator: SensorSimulator,
        steps: int,
        start: datetime | None = None,
        interval: timedelta = timedelta(minutes=30),
    ) -> list[RecordResult]:
        """Генерує steps вимірів для кожного активного датчика теплиці."""
        if not 1 <= steps <= MAX_SIMULATION_STEPS:
            raise ValidationError(f"Кількість кроків має бути від 1 до {MAX_SIMULATION_STEPS}")
        if interval <= timedelta(0):
            raise ValidationError("Інтервал між вимірами має бути додатним")
        sensors = self.repo.list_sensors(greenhouse_id, only_active=True)
        if not sensors:
            raise ValidationError("У теплиці немає активних датчиків")

        moment = start or datetime.now(timezone.utc) - interval * (steps - 1)
        results: list[RecordResult] = []
        for _ in range(steps):
            for sensor in sensors:
                value = simulator.generate(sensor.sensor_type, moment)
                results.append(self.record_reading(sensor.id, value, moment))
            moment += interval
        logger.info(
            "Симуляція: теплиця id=%s, %s кроків, %s вимірів", greenhouse_id, steps, len(results)
        )
        return results

    def greenhouse_status(self, greenhouse_id: int, history: int = 10) -> list[SensorStatus]:
        """Зведення: останнє значення, стан і тренд по кожному датчику теплиці."""
        self.repo.get_greenhouse(greenhouse_id)
        summary = []
        for sensor in self.repo.list_sensors(greenhouse_id):
            readings = self.repo.latest_readings(sensor.id, history)
            threshold = self.repo.get_threshold(greenhouse_id, sensor.sensor_type.code)
            latest = readings[-1] if readings else None
            status = (
                analyzer.evaluate(latest.value, threshold, self.critical_margin)
                if latest
                else Status.OK
            )
            trend = analyzer.detect_trend(
                [r.value for r in readings], analyzer.trend_tolerance(sensor.sensor_type)
            )
            summary.append(SensorStatus(sensor, latest, threshold, status, trend))
        return summary

    def create_demo_greenhouse(self, name: str = "Демо-теплиця") -> Greenhouse:
        """Створює теплицю з п'ятьма датчиками та рекомендованими порогами (атомарно)."""
        with transaction(self.repo.conn):
            greenhouse = self.repo.add_greenhouse(name, "Київ")
            for type_code, sensor_name in DEMO_SENSORS:
                self.repo.add_sensor(greenhouse.id, type_code, sensor_name)
            for type_code, threshold in DEMO_THRESHOLDS.items():
                self.repo.set_threshold(greenhouse.id, type_code, threshold)
        logger.info("Створено демо-теплицю id=%s", greenhouse.id)
        return greenhouse


def latest_age(reading: Reading, now: datetime | None = None) -> timedelta:
    """Скільки часу минуло від виміру (для виявлення 'мовчазних' датчиків)."""
    current = now or datetime.now(timezone.utc)
    return current - parse_timestamp(reading.recorded_at)
