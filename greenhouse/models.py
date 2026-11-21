"""Доменні моделі, винятки та валідація вхідних даних."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

MAX_NAME_LENGTH = 100
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class ValidationError(ValueError):
    """Некоректні вхідні дані."""


class NotFoundError(LookupError):
    """Запитаний об'єкт не існує."""


class DuplicateError(ValueError):
    """Порушено унікальність (наприклад, дві теплиці з однаковою назвою)."""


class Status(StrEnum):
    """Стан показника відносно оптимального діапазону."""

    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class SensorType:
    """Тип датчика з фізично допустимим діапазоном значень."""

    id: int
    code: str
    name: str
    unit: str
    min_valid: float
    max_valid: float


@dataclass(frozen=True)
class Greenhouse:
    """Теплиця."""

    id: int
    name: str
    location: str | None
    created_at: str


@dataclass(frozen=True)
class Sensor:
    """Датчик, встановлений у теплиці."""

    id: int
    greenhouse_id: int
    sensor_type: SensorType
    name: str
    is_active: bool


@dataclass(frozen=True)
class Threshold:
    """Оптимальний діапазон показника [min_value; max_value]."""

    min_value: float
    max_value: float

    def __post_init__(self) -> None:
        low = validate_number(self.min_value, "min_value")
        high = validate_number(self.max_value, "max_value")
        if low >= high:
            raise ValidationError(
                f"Нижня межа ({low}) має бути меншою за верхню ({high})"
            )
        object.__setattr__(self, "min_value", low)
        object.__setattr__(self, "max_value", high)

    def contains(self, value: float) -> bool:
        """Чи потрапляє значення в діапазон (межі включно)."""
        return self.min_value <= value <= self.max_value

    @property
    def width(self) -> float:
        """Ширина діапазону."""
        return self.max_value - self.min_value


@dataclass(frozen=True)
class Reading:
    """Один вимір датчика."""

    id: int
    sensor_id: int
    value: float
    recorded_at: str


@dataclass(frozen=True)
class Alert:
    """Сповіщення про вихід показника за норму."""

    id: int
    reading_id: int
    level: Status
    message: str
    acknowledged: bool


@dataclass(frozen=True)
class AlertView:
    """Сповіщення разом з контекстом для відображення."""

    id: int
    level: Status
    message: str
    acknowledged: bool
    recorded_at: str
    sensor_name: str
    greenhouse_name: str


def validate_name(value: object, field: str = "name") -> str:
    """Перевіряє назву: рядок, не порожній після обрізання пробілів, до 100 символів."""
    if not isinstance(value, str):
        raise ValidationError(f"Поле '{field}' має бути рядком")
    cleaned = value.strip()
    if not cleaned:
        raise ValidationError(f"Поле '{field}' не може бути порожнім")
    if len(cleaned) > MAX_NAME_LENGTH:
        raise ValidationError(
            f"Поле '{field}' задовге: {len(cleaned)} > {MAX_NAME_LENGTH} символів"
        )
    return cleaned


def validate_number(value: object, field: str = "value") -> float:
    """Перетворює значення на скінченне число або піднімає ValidationError."""
    if value is None or isinstance(value, bool):
        raise ValidationError(f"Поле '{field}' має бути числом")
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip().replace(",", "."))
        except ValueError as exc:
            raise ValidationError(f"Поле '{field}' має бути числом, отримано '{value}'") from exc
    else:
        raise ValidationError(f"Поле '{field}' має бути числом")
    if not math.isfinite(number):
        raise ValidationError(f"Поле '{field}' має бути скінченним числом")
    return number


def validate_reading_value(value: object, sensor_type: SensorType) -> float:
    """Перевіряє, що вимір є числом у фізично можливому діапазоні типу датчика."""
    number = validate_number(value, "value")
    if not sensor_type.min_valid <= number <= sensor_type.max_valid:
        raise ValidationError(
            f"Значення {number} {sensor_type.unit} поза фізичним діапазоном датчика "
            f"'{sensor_type.name}' [{sensor_type.min_valid}; {sensor_type.max_valid}]"
        )
    return number


def normalize_timestamp(value: datetime | str | None) -> str:
    """Приводить час до UTC у форматі YYYY-MM-DDTHH:MM:SSZ.

    None означає поточний момент; час без часового поясу вважається UTC.
    """
    if value is None:
        moment = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            moment = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValidationError(f"Некоректний формат часу: '{value}'") from exc
    else:
        raise ValidationError("Час має бути datetime або рядком ISO 8601")

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime(TIMESTAMP_FORMAT)


def parse_timestamp(value: str) -> datetime:
    """Зворотне до normalize_timestamp: рядок з БД у datetime з UTC."""
    return datetime.strptime(value, TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
