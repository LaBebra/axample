"""Сервіс моніторингу: прийом вимірів, сповіщення, симуляція, зведення."""
# pylint: disable=redefined-outer-name  # pytest-фікстури передаються як аргументи

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from greenhouse.analyzer import Trend
from greenhouse.models import DuplicateError, NotFoundError, Reading, Status, ValidationError
from greenhouse.service import MAX_SIMULATION_STEPS, latest_age
from greenhouse.simulator import SensorSimulator

START = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def sensor(repo, greenhouse):
    return repo.add_sensor(greenhouse.id, "temperature", "T1")


class TestRecordReading:
    def test_normal_value_has_no_alert(self, service, sensor):
        result = service.record_reading(sensor.id, "22.5", START)
        assert result.status is Status.OK
        assert result.alert is None
        assert result.reading.recorded_at == "2026-06-01T08:00:00Z"

    def test_out_of_norm_creates_alert(self, service, repo, sensor):
        result = service.record_reading(sensor.id, 35)
        assert result.status is Status.CRITICAL
        assert result.alert is not None
        assert repo.list_alerts()[0].id == result.alert.id

    def test_no_threshold_no_alert(self, service, repo, greenhouse):
        co2 = repo.add_sensor(greenhouse.id, "co2", "C1")
        assert service.record_reading(co2.id, 5000).alert is None

    @pytest.mark.parametrize("value", [None, "", "abc", float("nan"), 81, -41])
    def test_invalid_value_is_rejected_and_not_saved(self, service, repo, sensor, value):
        with pytest.raises(ValidationError):
            service.record_reading(sensor.id, value)
        assert repo.count_readings(sensor.id) == 0

    def test_inactive_sensor(self, service, repo, sensor):
        repo.set_sensor_active(sensor.id, False)
        with pytest.raises(ValidationError, match="вимкнено"):
            service.record_reading(sensor.id, 22)

    def test_unknown_sensor(self, service):
        with pytest.raises(NotFoundError):
            service.record_reading(999, 22)

    def test_alert_failure_rolls_back_reading(self, service, repo, sensor):
        with patch.object(repo, "insert_alert", side_effect=RuntimeError("диск заповнено")):
            with pytest.raises(RuntimeError):
                service.record_reading(sensor.id, 40)
        assert repo.count_readings(sensor.id) == 0


class TestSimulate:
    def test_generates_readings_for_every_active_sensor(self, service, repo):
        item = service.create_demo_greenhouse()
        sensors = repo.list_sensors(item.id)
        repo.set_sensor_active(sensors[-1].id, False)
        results = service.simulate(
            item.id, SensorSimulator(seed=1), steps=4, start=START, interval=timedelta(hours=1)
        )
        assert len(results) == 4 * (len(sensors) - 1)
        assert results[-1].reading.recorded_at == "2026-06-01T11:00:00Z"

    def test_default_start_ends_now(self, service):
        item = service.create_demo_greenhouse()
        results = service.simulate(item.id, SensorSimulator(seed=1), steps=2)
        assert latest_age(results[-1].reading) < timedelta(minutes=1)

    def test_anomalies_produce_alerts(self, service):
        item = service.create_demo_greenhouse()
        results = service.simulate(item.id, SensorSimulator(seed=2, anomaly_rate=1.0), 3, START)
        assert any(r.alert for r in results)

    @pytest.mark.usefixtures("sensor")
    @pytest.mark.parametrize("steps", [0, -1, MAX_SIMULATION_STEPS + 1])
    def test_invalid_steps(self, service, greenhouse, steps):
        with pytest.raises(ValidationError):
            service.simulate(greenhouse.id, SensorSimulator(), steps)

    @pytest.mark.usefixtures("sensor")
    def test_invalid_interval(self, service, greenhouse):
        with pytest.raises(ValidationError):
            service.simulate(greenhouse.id, SensorSimulator(), 1, interval=timedelta(0))

    def test_no_sensors(self, service, greenhouse):
        with pytest.raises(ValidationError, match="немає активних"):
            service.simulate(greenhouse.id, SensorSimulator(), 1)


class TestStatus:
    def test_summary(self, service, repo, greenhouse, sensor):
        repo.add_sensor(greenhouse.id, "co2", "C1")
        for hour, value in enumerate([20, 22, 24, 30]):
            service.record_reading(sensor.id, value, START + timedelta(hours=hour))
        temp_row, co2_row = service.greenhouse_status(greenhouse.id)
        assert temp_row.latest.value == 30
        assert temp_row.status is Status.CRITICAL
        assert temp_row.trend is Trend.RISING
        assert co2_row.latest is None
        assert co2_row.status is Status.OK
        assert co2_row.trend is Trend.UNKNOWN

    def test_missing_greenhouse(self, service):
        with pytest.raises(NotFoundError):
            service.greenhouse_status(999)


def test_demo_is_atomic(service, repo):
    service.create_demo_greenhouse("Одна")
    with pytest.raises(DuplicateError):
        service.create_demo_greenhouse("Одна")
    assert len(repo.list_greenhouses()) == 1
    assert repo.conn.execute("SELECT COUNT(*) FROM sensor").fetchone()[0] == 5


def test_latest_age():
    reading = Reading(1, 1, 20, "2026-06-01T08:00:00Z")
    assert latest_age(reading, START + timedelta(minutes=5)) == timedelta(minutes=5)
