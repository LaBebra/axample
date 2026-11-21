"""Валідація вхідних даних і доменних моделей."""

from datetime import datetime, timedelta, timezone

import pytest

from greenhouse.models import (
    MAX_NAME_LENGTH,
    SensorType,
    Threshold,
    ValidationError,
    normalize_timestamp,
    parse_timestamp,
    validate_name,
    validate_number,
    validate_reading_value,
)

HUMIDITY = SensorType(1, "air_humidity", "Вологість повітря", "%", 0, 100)


class TestValidateName:
    def test_strips_spaces(self):
        assert validate_name("  Теплиця 1 ") == "Теплиця 1"

    @pytest.mark.parametrize("value", ["", "   ", "\t\n"])
    def test_rejects_empty(self, value):
        with pytest.raises(ValidationError, match="порожнім"):
            validate_name(value)

    def test_rejects_non_string(self):
        with pytest.raises(ValidationError, match="рядком"):
            validate_name(42)

    def test_length_boundary(self):
        assert validate_name("a" * MAX_NAME_LENGTH) == "a" * MAX_NAME_LENGTH
        with pytest.raises(ValidationError, match="задовге"):
            validate_name("a" * (MAX_NAME_LENGTH + 1))


class TestValidateNumber:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [(5, 5.0), (2.5, 2.5), ("3.5", 3.5), (" 7,25 ", 7.25), ("-1", -1.0)],
    )
    def test_accepts_numbers(self, value, expected):
        assert validate_number(value) == expected

    @pytest.mark.parametrize("value", [None, True, False, [], {}, object()])
    def test_rejects_wrong_types(self, value):
        with pytest.raises(ValidationError):
            validate_number(value)

    @pytest.mark.parametrize("value", ["abc", "", "1.2.3"])
    def test_rejects_bad_strings(self, value):
        with pytest.raises(ValidationError, match="числом"):
            validate_number(value)

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "nan"])
    def test_rejects_non_finite(self, value):
        with pytest.raises(ValidationError, match="скінченним"):
            validate_number(value)


class TestValidateReadingValue:
    @pytest.mark.parametrize("value", [0, 100, 55.5])
    def test_inside_physical_range_including_bounds(self, value):
        assert validate_reading_value(value, HUMIDITY) == float(value)

    @pytest.mark.parametrize("value", [-0.01, 100.01, 1e9])
    def test_outside_physical_range(self, value):
        with pytest.raises(ValidationError, match="фізичним діапазоном"):
            validate_reading_value(value, HUMIDITY)


class TestThreshold:
    def test_valid(self):
        threshold = Threshold("18", 27)
        assert threshold.min_value == 18.0
        assert threshold.width == 9.0
        assert threshold.contains(18) and threshold.contains(27)
        assert not threshold.contains(27.01)

    @pytest.mark.parametrize(("low", "high"), [(10, 10), (20, 10)])
    def test_min_must_be_less_than_max(self, low, high):
        with pytest.raises(ValidationError, match="меншою"):
            Threshold(low, high)

    def test_rejects_nan(self):
        with pytest.raises(ValidationError):
            Threshold(float("nan"), 10)


class TestTimestamps:
    def test_none_means_now(self):
        before = datetime.now(timezone.utc).replace(microsecond=0)
        result = parse_timestamp(normalize_timestamp(None))
        assert before <= result <= before + timedelta(seconds=2)

    def test_naive_datetime_is_utc(self):
        assert normalize_timestamp(datetime(2026, 5, 1, 12, 0)) == "2026-05-01T12:00:00Z"

    def test_converts_timezone_to_utc(self):
        kyiv = timezone(timedelta(hours=3))
        moment = datetime(2026, 5, 1, 15, 0, tzinfo=kyiv)
        assert normalize_timestamp(moment) == "2026-05-01T12:00:00Z"

    @pytest.mark.parametrize(
        "text", ["2026-05-01T12:00:00Z", "2026-05-01T12:00:00+00:00", "2026-05-01 12:00"]
    )
    def test_parses_iso_strings(self, text):
        assert normalize_timestamp(text) == "2026-05-01T12:00:00Z"

    @pytest.mark.parametrize("value", ["вчора", "2026-13-01", 12345])
    def test_rejects_invalid(self, value):
        with pytest.raises(ValidationError):
            normalize_timestamp(value)

    def test_roundtrip(self):
        text = "2026-01-02T03:04:05Z"
        assert normalize_timestamp(parse_timestamp(text)) == text
