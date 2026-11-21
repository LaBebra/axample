"""Імітатор датчиків."""

from datetime import datetime, timezone

import pytest

from greenhouse.models import SensorType
from greenhouse.simulator import SensorSimulator

TEMP = SensorType(1, "temperature", "Температура", "°C", -40, 80)
LIGHT = SensorType(4, "light", "Освітленість", "lx", 0, 200000)
UNKNOWN = SensorType(9, "ph", "Кислотність", "pH", 0, 14)
NOON = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
MIDNIGHT = datetime(2026, 6, 1, 2, 0, tzinfo=timezone.utc)


def test_same_seed_same_values():
    first = SensorSimulator(seed=1).generate(TEMP, NOON)
    second = SensorSimulator(seed=1).generate(TEMP, NOON)
    assert first == second


def test_daily_cycle():
    sim = SensorSimulator(seed=7)
    day = [sim.generate(TEMP, NOON) for _ in range(20)]
    night = [sim.generate(TEMP, MIDNIGHT) for _ in range(20)]
    assert min(day) > max(night)


def test_light_is_zero_at_night():
    assert SensorSimulator(seed=3).generate(LIGHT, MIDNIGHT) == 0


def test_values_stay_in_physical_range_with_anomalies():
    sim = SensorSimulator(seed=11, anomaly_rate=1.0, anomaly_scale=1000)
    for _ in range(50):
        assert TEMP.min_valid <= sim.generate(TEMP, NOON) <= TEMP.max_valid


def test_anomalies_change_values():
    normal = SensorSimulator(seed=5).generate(TEMP, NOON)
    spiked = SensorSimulator(seed=5, anomaly_rate=1.0).generate(TEMP, NOON)
    assert abs(spiked - normal) > 5


def test_unknown_type_uses_fallback():
    value = SensorSimulator(seed=2).generate(UNKNOWN, NOON)
    assert 5 < value < 9


@pytest.mark.parametrize(("rate", "scale"), [(-0.1, 1), (1.5, 1), (0.5, -1)])
def test_invalid_parameters(rate, scale):
    with pytest.raises(ValueError):
        SensorSimulator(anomaly_rate=rate, anomaly_scale=scale)
