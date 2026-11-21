"""CRUD-операції репозиторію."""

import pytest

from greenhouse.models import DuplicateError, NotFoundError, Status, Threshold, ValidationError


def test_sensor_types(repo):
    codes = [item.code for item in repo.list_sensor_types()]
    assert codes == ["temperature", "air_humidity", "soil_moisture", "light", "co2"]
    assert repo.get_sensor_type("co2").unit == "ppm"
    with pytest.raises(NotFoundError):
        repo.get_sensor_type("radiation")


class TestGreenhouse:
    def test_add_and_get(self, repo):
        item = repo.add_greenhouse(" Північна ", " Львів ")
        assert item.name == "Північна"
        assert item.location == "Львів"
        assert item.created_at.endswith("Z")
        assert repo.get_greenhouse(item.id) == item

    def test_without_location(self, repo):
        assert repo.add_greenhouse("Б").location is None

    def test_duplicate_name(self, repo):
        repo.add_greenhouse("А")
        with pytest.raises(DuplicateError):
            repo.add_greenhouse(" А ")

    def test_empty_name(self, repo):
        with pytest.raises(ValidationError):
            repo.add_greenhouse("  ")

    def test_list_and_find(self, repo):
        repo.add_greenhouse("А")
        repo.add_greenhouse("Б")
        assert [g.name for g in repo.list_greenhouses()] == ["А", "Б"]
        assert repo.find_greenhouse_by_name("Б").name == "Б"
        assert repo.find_greenhouse_by_name("В") is None

    def test_missing(self, repo):
        with pytest.raises(NotFoundError):
            repo.get_greenhouse(404)
        with pytest.raises(NotFoundError):
            repo.delete_greenhouse(404)


class TestSensor:
    def test_add_and_list(self, repo, greenhouse):
        sensor = repo.add_sensor(greenhouse.id, "temperature", "T1")
        assert sensor.sensor_type.code == "temperature"
        assert sensor.is_active
        assert repo.list_sensors(greenhouse.id) == [sensor]

    def test_duplicate_in_same_greenhouse(self, repo, greenhouse):
        repo.add_sensor(greenhouse.id, "temperature", "T1")
        with pytest.raises(DuplicateError):
            repo.add_sensor(greenhouse.id, "co2", "T1")

    def test_same_name_in_other_greenhouse_allowed(self, repo, greenhouse):
        other = repo.add_greenhouse("Інша")
        repo.add_sensor(greenhouse.id, "temperature", "T1")
        assert repo.add_sensor(other.id, "temperature", "T1").greenhouse_id == other.id

    def test_unknown_type_or_greenhouse(self, repo, greenhouse):
        with pytest.raises(NotFoundError):
            repo.add_sensor(greenhouse.id, "radiation", "R")
        with pytest.raises(NotFoundError):
            repo.add_sensor(999, "temperature", "T")

    def test_deactivate(self, repo, greenhouse):
        sensor = repo.add_sensor(greenhouse.id, "temperature", "T1")
        repo.set_sensor_active(sensor.id, False)
        assert not repo.get_sensor(sensor.id).is_active
        assert repo.list_sensors(greenhouse.id, only_active=True) == []
        with pytest.raises(NotFoundError):
            repo.set_sensor_active(999, True)

    def test_missing(self, repo):
        with pytest.raises(NotFoundError):
            repo.get_sensor(999)


class TestThreshold:
    def test_upsert(self, repo, greenhouse):
        assert repo.get_threshold(greenhouse.id, "co2") is None
        repo.set_threshold(greenhouse.id, "co2", Threshold(400, 1000))
        repo.set_threshold(greenhouse.id, "co2", Threshold(500, 1200))
        assert repo.get_threshold(greenhouse.id, "co2") == Threshold(500, 1200)
        count = repo.conn.execute("SELECT COUNT(*) FROM threshold").fetchone()[0]
        assert count == 2  # temperature з фікстури + co2

    def test_missing_greenhouse(self, repo):
        with pytest.raises(NotFoundError):
            repo.set_threshold(999, "co2", Threshold(1, 2))


class TestReadingsAndAlerts:
    def test_latest_readings_order_and_limit(self, repo, greenhouse):
        sensor = repo.add_sensor(greenhouse.id, "temperature", "T1")
        for hour, value in enumerate([20, 21, 22, 23]):
            repo.insert_reading(sensor.id, value, f"2026-05-01T0{hour}:00:00Z")
        latest = repo.latest_readings(sensor.id, limit=3)
        assert [r.value for r in latest] == [21, 22, 23]
        assert repo.count_readings(sensor.id) == 4

    def test_alerts_filter_and_ack(self, repo, greenhouse):
        sensor = repo.add_sensor(greenhouse.id, "temperature", "T1")
        first = repo.insert_reading(sensor.id, 35, "2026-05-01T10:00:00Z")
        second = repo.insert_reading(sensor.id, 10, "2026-05-01T11:00:00Z")
        alert1 = repo.insert_alert(first.id, Status.CRITICAL, "гаряче")
        repo.insert_alert(second.id, Status.WARNING, "холодно")

        all_alerts = repo.list_alerts()
        assert [a.message for a in all_alerts] == ["холодно", "гаряче"]
        assert all_alerts[0].greenhouse_name == "Тестова"

        repo.acknowledge_alert(alert1.id)
        unread = repo.list_alerts(greenhouse.id, only_unacknowledged=True)
        assert [a.message for a in unread] == ["холодно"]
        assert repo.list_alerts(greenhouse_id=999) == []
        with pytest.raises(NotFoundError):
            repo.acknowledge_alert(999)
