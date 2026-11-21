"""Оцінка стану показників і тренду."""

import pytest

from greenhouse.analyzer import (
    Trend,
    build_message,
    detect_trend,
    evaluate,
    linear_slope,
    trend_tolerance,
)
from greenhouse.models import SensorType, Status, Threshold

TEMP = SensorType(1, "temperature", "Температура повітря", "°C", -40, 80)
NORM = Threshold(18, 28)  # ширина 10, критичний запас 1 градус


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (18, Status.OK),
        (23, Status.OK),
        (28, Status.OK),
        (17.5, Status.WARNING),
        (17, Status.WARNING),  # рівно на межі запасу ще WARNING
        (16.99, Status.CRITICAL),
        (29, Status.WARNING),
        (29.01, Status.CRITICAL),
        (-40, Status.CRITICAL),
    ],
)
def test_evaluate(value, expected):
    assert evaluate(value, NORM) is expected


def test_evaluate_without_threshold_is_ok():
    assert evaluate(1000, None) is Status.OK


def test_evaluate_zero_margin():
    assert evaluate(28.01, NORM, critical_margin=0) is Status.CRITICAL


def test_evaluate_negative_margin():
    with pytest.raises(ValueError):
        evaluate(20, NORM, critical_margin=-0.1)


def test_build_message():
    low = build_message("T1", TEMP, 12.5, NORM, Status.CRITICAL)
    assert low.startswith("КРИТИЧНО")
    assert "нижче" in low and "12.5 °C" in low and "[18; 28]" in low
    high = build_message("T1", TEMP, 28.5, NORM, Status.WARNING)
    assert high.startswith("Увага") and "вище" in high


def test_build_message_keeps_abbreviations():
    co2 = SensorType(5, "co2", "Концентрація CO2", "ppm", 0, 10000)
    message = build_message("C1", co2, 300, Threshold(400, 1200), Status.CRITICAL)
    assert "концентрація CO2" in message


@pytest.mark.parametrize(
    ("values", "slope"),
    [([], 0.0), ([5], 0.0), ([1, 2, 3], 1.0), ([3, 2, 1], -1.0), ([4, 4, 4, 4], 0.0)],
)
def test_linear_slope(values, slope):
    assert linear_slope(values) == pytest.approx(slope)


@pytest.mark.parametrize(
    ("values", "trend"),
    [
        ([20, 21], Trend.UNKNOWN),
        ([20, 21, 22, 23], Trend.RISING),
        ([23, 22, 21], Trend.FALLING),
        ([20, 20.1, 19.9, 20], Trend.STABLE),
    ],
)
def test_detect_trend(values, trend):
    assert detect_trend(values, tolerance=0.24) is trend


def test_trend_tolerance():
    assert trend_tolerance(TEMP) == pytest.approx(0.24)
