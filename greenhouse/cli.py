"""Інтерфейс командного рядка (етап 1, до появи REST API та веб-інтерфейсу)."""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path

from greenhouse import __version__, config
from greenhouse.db import connect, init_schema
from greenhouse.logging_setup import LOGGER_NAME, configure_logging
from greenhouse.models import DuplicateError, NotFoundError, Status, Threshold, ValidationError
from greenhouse.repository import Repository
from greenhouse.service import MonitoringService
from greenhouse.simulator import SensorSimulator

logger = logging.getLogger(LOGGER_NAME)

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_USER_ERROR = 2

STATUS_LABELS = {Status.OK: "норма", Status.WARNING: "УВАГА", Status.CRITICAL: "КРИТИЧНО"}
TREND_LABELS = {"rising": "↑ росте", "falling": "↓ падає", "stable": "→ стабільно", "unknown": "?"}


def _cmd_sensor_types(service: MonitoringService, _args: argparse.Namespace) -> None:
    for item in service.repo.list_sensor_types():
        limits = f"[{item.min_valid:g}; {item.max_valid:g}]"
        print(f"{item.code:<14} {item.name:<22} {item.unit:<4} {limits}")


def _cmd_list_greenhouses(service: MonitoringService, _args: argparse.Namespace) -> None:
    greenhouses = service.repo.list_greenhouses()
    if not greenhouses:
        print("Теплиць ще немає. Створіть демо: python -m greenhouse demo")
        return
    for item in greenhouses:
        print(f"#{item.id:<3} {item.name:<25} {item.location or '-':<15} {item.created_at}")


def _cmd_add_greenhouse(service: MonitoringService, args: argparse.Namespace) -> None:
    item = service.repo.add_greenhouse(args.name, args.location)
    print(f"Створено теплицю #{item.id} '{item.name}'")


def _cmd_add_sensor(service: MonitoringService, args: argparse.Namespace) -> None:
    sensor = service.repo.add_sensor(args.greenhouse_id, args.type, args.name)
    print(f"Додано датчик #{sensor.id} '{sensor.name}' ({sensor.sensor_type.name})")


def _cmd_set_threshold(service: MonitoringService, args: argparse.Namespace) -> None:
    threshold = Threshold(args.min, args.max)
    service.repo.set_threshold(args.greenhouse_id, args.type, threshold)
    print(f"Норма для '{args.type}': [{threshold.min_value:g}; {threshold.max_value:g}]")


def _cmd_demo(service: MonitoringService, args: argparse.Namespace) -> None:
    item = service.create_demo_greenhouse(args.name)
    print(f"Створено демо-теплицю #{item.id} '{item.name}' з 5 датчиками та нормами")
    print(f"Далі: python -m greenhouse simulate {item.id}")


def _cmd_record(service: MonitoringService, args: argparse.Namespace) -> None:
    result = service.record_reading(args.sensor_id, args.value, args.at)
    print(
        f"Вимір #{result.reading.id}: {result.reading.value:g} {result.sensor.sensor_type.unit} "
        f"-> {STATUS_LABELS[result.status]}"
    )
    if result.alert:
        print(result.alert.message)


def _cmd_simulate(service: MonitoringService, args: argparse.Namespace) -> None:
    simulator = SensorSimulator(seed=args.seed, anomaly_rate=args.anomaly_rate)
    results = service.simulate(
        args.greenhouse_id, simulator, args.steps, interval=timedelta(minutes=args.interval)
    )
    alerts = [r for r in results if r.alert]
    print(f"Записано вимірів: {len(results)}, сповіщень: {len(alerts)}")
    for result in alerts[-10:]:
        print(f"  {result.reading.recorded_at}  {result.alert.message}")


def _cmd_status(service: MonitoringService, args: argparse.Namespace) -> None:
    greenhouse = service.repo.get_greenhouse(args.greenhouse_id)
    print(f"Теплиця #{greenhouse.id} '{greenhouse.name}'")
    rows = service.greenhouse_status(args.greenhouse_id)
    if not rows:
        print("  датчиків немає")
        return
    for row in rows:
        unit = row.sensor.sensor_type.unit
        value = f"{row.latest.value:g} {unit}" if row.latest else "немає даних"
        norm = (
            f"[{row.threshold.min_value:g}; {row.threshold.max_value:g}]"
            if row.threshold
            else "норма не задана"
        )
        print(
            f"  {row.sensor.name:<14} {value:<14} {norm:<16} "
            f"{STATUS_LABELS[row.status]:<9} {TREND_LABELS[row.trend.value]}"
        )


def _cmd_alerts(service: MonitoringService, args: argparse.Namespace) -> None:
    alerts = service.repo.list_alerts(args.greenhouse, args.unread, args.limit)
    if not alerts:
        print("Сповіщень немає")
        return
    for item in alerts:
        mark = " " if item.acknowledged else "*"
        print(f"{mark} #{item.id:<5} {item.recorded_at}  [{item.greenhouse_name}] {item.message}")


def _cmd_ack(service: MonitoringService, args: argparse.Namespace) -> None:
    service.repo.acknowledge_alert(args.alert_id)
    print(f"Сповіщення #{args.alert_id} позначено прочитаним")


Handler = Callable[[MonitoringService, argparse.Namespace], None]


def build_parser() -> argparse.ArgumentParser:
    """Опис команд CLI."""
    parser = argparse.ArgumentParser(
        prog="greenhouse", description="Інтелектуальна система моніторингу теплиці"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--db", type=Path, default=None, help="шлях до файлу БД SQLite")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, handler: Handler, help_text: str) -> argparse.ArgumentParser:
        command = sub.add_parser(name, help=help_text)
        command.set_defaults(handler=handler)
        return command

    add("sensor-types", _cmd_sensor_types, "довідник типів датчиків")
    add("list", _cmd_list_greenhouses, "список теплиць")

    cmd = add("add-greenhouse", _cmd_add_greenhouse, "створити теплицю")
    cmd.add_argument("name")
    cmd.add_argument("--location")

    cmd = add("add-sensor", _cmd_add_sensor, "додати датчик")
    cmd.add_argument("greenhouse_id", type=int)
    cmd.add_argument("type", help="код типу (див. sensor-types)")
    cmd.add_argument("name")

    cmd = add("set-threshold", _cmd_set_threshold, "задати норму показника")
    cmd.add_argument("greenhouse_id", type=int)
    cmd.add_argument("type")
    cmd.add_argument("min", type=float)
    cmd.add_argument("max", type=float)

    cmd = add("demo", _cmd_demo, "створити демо-теплицю з датчиками")
    cmd.add_argument("--name", default="Демо-теплиця")

    cmd = add("record", _cmd_record, "записати вимір вручну")
    cmd.add_argument("sensor_id", type=int)
    cmd.add_argument("value", help="значення (число)")
    cmd.add_argument("--at", default=None, help="час ISO 8601, за замовчуванням зараз")

    cmd = add("simulate", _cmd_simulate, "згенерувати виміри імітатором")
    cmd.add_argument("greenhouse_id", type=int)
    cmd.add_argument("--steps", type=int, default=12)
    cmd.add_argument("--interval", type=int, default=30, help="хвилин між вимірами")
    cmd.add_argument("--seed", type=int, default=None)
    cmd.add_argument("--anomaly-rate", type=float, default=0.05)

    cmd = add("status", _cmd_status, "поточний стан теплиці")
    cmd.add_argument("greenhouse_id", type=int)

    cmd = add("alerts", _cmd_alerts, "список сповіщень")
    cmd.add_argument("--greenhouse", type=int, default=None)
    cmd.add_argument("--unread", action="store_true", help="лише непрочитані")
    cmd.add_argument("--limit", type=int, default=20)

    cmd = add("ack", _cmd_ack, "позначити сповіщення прочитаним")
    cmd.add_argument("alert_id", type=int)
    return parser


def _use_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входу. Повертає код завершення, не пропускаючи винятки назовні."""
    _use_utf8_output()
    args = build_parser().parse_args(argv)
    configure_logging(config.get_log_path())
    db_path = args.db or config.get_db_path()

    conn: sqlite3.Connection | None = None
    try:
        conn = connect(db_path)
        init_schema(conn)
        args.handler(MonitoringService(Repository(conn)), args)
        return EXIT_OK
    except (ValidationError, NotFoundError, DuplicateError, ValueError) as exc:
        logger.warning("Помилка користувача у команді '%s': %s", args.command, exc)
        print(f"Помилка: {exc}", file=sys.stderr)
        return EXIT_USER_ERROR
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("Непередбачена помилка у команді '%s'", args.command)
        print("Непередбачена помилка, подробиці в лог-файлі", file=sys.stderr)
        return EXIT_UNEXPECTED
    finally:
        if conn is not None:
            conn.close()
