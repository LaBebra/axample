"""Аналіз показників: оцінка стану відносно норми та визначення тренду."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from greenhouse.models import SensorType, Status, Threshold

# Частка ширини оптимального діапазону, за якою відхилення стає критичним.
DEFAULT_CRITICAL_MARGIN = 0.1
# Мінімальна кількість точок для оцінки тренду.
MIN_TREND_POINTS = 3


class Trend(StrEnum):
    """Напрям зміни показника."""

    RISING = "rising"
    FALLING = "falling"
    STABLE = "stable"
    UNKNOWN = "unknown"


def evaluate(
    value: float,
    threshold: Threshold | None,
    critical_margin: float = DEFAULT_CRITICAL_MARGIN,
) -> Status:
    """Оцінює значення відносно оптимального діапазону.

    * у межах діапазону (включно) -> OK;
    * поза діапазоном, але не далі ніж margin * ширина -> WARNING;
    * ще далі -> CRITICAL.
    Якщо поріг не задано, показник вважається нормальним.
    """
    if critical_margin < 0:
        raise ValueError("critical_margin не може бути від'ємним")
    if threshold is None or threshold.contains(value):
        return Status.OK
    margin = threshold.width * critical_margin
    if value < threshold.min_value - margin or value > threshold.max_value + margin:
        return Status.CRITICAL
    return Status.WARNING


def build_message(
    sensor_name: str,
    sensor_type: SensorType,
    value: float,
    threshold: Threshold,
    status: Status,
) -> str:
    """Текст сповіщення українською."""
    direction = "нижче" if value < threshold.min_value else "вище"
    level = "КРИТИЧНО" if status is Status.CRITICAL else "Увага"
    # Знижуємо регістр лише першої літери, щоб не зіпсувати абревіатури (CO2).
    title = sensor_type.name[:1].lower() + sensor_type.name[1:]
    return (
        f"{level}: {title} ({sensor_name}) = {value:g} {sensor_type.unit}, "
        f"{direction} норми [{threshold.min_value:g}; {threshold.max_value:g}]"
    )


def linear_slope(values: Sequence[float]) -> float:
    """Нахил прямої методом найменших квадратів (x = 0, 1, 2, ...)."""
    count = len(values)
    if count < 2:
        return 0.0
    mean_x = (count - 1) / 2
    mean_y = sum(values) / count
    numerator = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(values))
    denominator = sum((i - mean_x) ** 2 for i in range(count))
    return numerator / denominator


def detect_trend(values: Sequence[float], tolerance: float) -> Trend:
    """Тренд за нахилом: |нахил| <= tolerance вважається стабільним."""
    if len(values) < MIN_TREND_POINTS:
        return Trend.UNKNOWN
    slope = linear_slope(values)
    if slope > tolerance:
        return Trend.RISING
    if slope < -tolerance:
        return Trend.FALLING
    return Trend.STABLE


def trend_tolerance(sensor_type: SensorType, fraction: float = 0.002) -> float:
    """Поріг чутливості тренду як частка фізичного діапазону датчика."""
    return (sensor_type.max_valid - sensor_type.min_valid) * fraction
