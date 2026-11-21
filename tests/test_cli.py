"""Наскрізні сценарії через командний рядок (окрема БД і лог для кожного тесту)."""
# pylint: disable=redefined-outer-name  # pytest-фікстури передаються як аргументи

import runpy
import sys
from unittest.mock import patch

import pytest

from greenhouse import cli


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GREENHOUSE_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("GREENHOUSE_LOG", str(tmp_path / "test.log"))

    def _run(*args):
        code = cli.main(list(args))
        out, err = capsys.readouterr()
        return code, out, err

    return _run


def test_full_scenario(run):
    assert run("list")[1].startswith("Теплиць ще немає")
    code, out, _ = run("demo")
    assert code == 0 and "#1" in out

    code, out, _ = run("simulate", "1", "--steps", "3", "--seed", "1", "--anomaly-rate", "1")
    assert code == 0 and "Записано вимірів: 15" in out

    code, out, _ = run("status", "1")
    assert code == 0 and "Термометр-1" in out and "норма не задана" in out

    code, out, _ = run("alerts", "--unread")
    assert code == 0 and out.startswith("*")
    alert_id = out.split()[1].lstrip("#")
    assert run("ack", alert_id)[0] == 0
    assert run("alerts", "--greenhouse", "999")[1].startswith("Сповіщень немає")


def test_manual_setup(run):
    assert run("add-greenhouse", "Моя", "--location", "Одеса")[0] == 0
    assert "Моя" in run("list")[1]
    assert run("status", "1")[1].strip().endswith("датчиків немає")
    assert run("add-sensor", "1", "soil_moisture", "Ґрунт")[0] == 0
    assert run("set-threshold", "1", "soil_moisture", "40", "70")[0] == 0
    code, out, _ = run("record", "1", "30", "--at", "2026-06-01T10:00:00Z")
    assert code == 0 and "УВАГА" not in out and "КРИТИЧНО" in out
    assert "-> норма" in run("record", "1", "50")[1]
    assert "soil_moisture" in run("sensor-types")[1]


@pytest.mark.parametrize(
    "args",
    [
        ("record", "1", "abc"),
        ("status", "42"),
        ("set-threshold", "1", "co2", "10", "5"),
        ("add-sensor", "1", "radiation", "X"),
    ],
)
def test_user_errors_return_code_2(run, args):
    run("add-greenhouse", "А")
    run("add-sensor", "1", "temperature", "T")
    code, _, err = run(*args)
    assert code == cli.EXIT_USER_ERROR
    assert err.startswith("Помилка:")


def test_duplicate_greenhouse(run):
    run("add-greenhouse", "А")
    assert run("add-greenhouse", "А")[0] == cli.EXIT_USER_ERROR


def test_unexpected_error_is_logged_not_raised(run, tmp_path):
    with patch.object(cli, "init_schema", side_effect=RuntimeError("збій БД")):
        code, _, err = run("list")
    assert code == cli.EXIT_UNEXPECTED
    assert "лог-файлі" in err
    assert "збій БД" in (tmp_path / "test.log").read_text(encoding="utf-8")


def test_db_option(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GREENHOUSE_LOG", str(tmp_path / "test.log"))
    db_file = tmp_path / "custom.db"
    assert cli.main(["--db", str(db_file), "demo"]) == 0
    capsys.readouterr()
    assert db_file.exists()


def test_module_entry_point(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GREENHOUSE_DB", str(tmp_path / "m.db"))
    monkeypatch.setenv("GREENHOUSE_LOG", str(tmp_path / "m.log"))
    monkeypatch.setattr(sys, "argv", ["greenhouse", "sensor-types"])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("greenhouse", run_name="__main__")
    assert exc_info.value.code == 0
    assert "temperature" in capsys.readouterr().out
