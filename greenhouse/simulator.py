"""Імітатор датчиків: добовий цикл + шум + випадкові аномалії.

Потрібен, поки немає реального обладнання (Arduino/ESP32). Пізніше
його можна замінити на джерело даних з MQTT або HTTP без зміни сервісу.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime

from greenhouse.models import SensorType


@dataclass(frozen=True)
class Profile:
    """Параметри добового коливання показника.

    value = base + amplitude * cos(2π (година - peak_hour) / 24) + шум
    Від'ємна амплітуда означає мінімум у peak_hour (наприклад, вологість вдень).
    """

    base: float
    amplitude: float
    noise: float
    peak_hour: float = 14.0


PROFILES: dict[str, Profile] = {
    "temperature": Profile(base=22.0, amplitude=5.0, noise=0.4),
    "air_humidity": Profile(base=70.0, amplitude=-10.0, noise=1.5),
    "soil_moisture": Profile(base=55.0, amplitude=-4.0, noise=0.8),
    "light": Profile(base=20000.0, amplitude=30000.0, noise=1500.0, peak_hour=13.0),
    "co2": Profile(base=800.0, amplitude=-200.0, noise=25.0),
}


class SensorSimulator:
    """Генерує правдоподібні значення для типу датчика у заданий момент часу."""

    def __init__(
        self,
        seed: int | None = None,
        anomaly_rate: float = 0.0,
        anomaly_scale: float = 3.0,
    ) -> None:
        if not 0.0 <= anomaly_rate <= 1.0:
            raise ValueError("anomaly_rate має бути в межах [0; 1]")
        if anomaly_scale < 0:
            raise ValueError("anomaly_scale не може бути від'ємним")
        self._rng = random.Random(seed)
        self.anomaly_rate = anomaly_rate
        self.anomaly_scale = anomaly_scale

    def generate(self, sensor_type: SensorType, moment: datetime) -> float:
        """Значення датчика в момент moment, обмежене фізичним діапазоном."""
        profile = PROFILES.get(sensor_type.code) or self._fallback_profile(sensor_type)
        hours = moment.hour + moment.minute / 60
        cycle = math.cos(2 * math.pi * (hours - profile.peak_hour) / 24)
        value = profile.base + profile.amplitude * cycle + self._rng.gauss(0, profile.noise)

        if self.anomaly_rate and self._rng.random() < self.anomaly_rate:
            spike = max(abs(profile.amplitude), profile.noise, 1.0) * self.anomaly_scale
            value += self._rng.choice((-1, 1)) * spike

        value = min(max(value, sensor_type.min_valid), sensor_type.max_valid)
        return round(value, 2)

    @staticmethod
    def _fallback_profile(sensor_type: SensorType) -> Profile:
        """Профіль для невідомого типу: середина діапазону з невеликим шумом."""
        span = sensor_type.max_valid - sensor_type.min_valid
        middle = sensor_type.min_valid + span / 2
        return Profile(base=middle, amplitude=span * 0.05, noise=span * 0.01)
