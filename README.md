# Інтелектуальна система моніторингу теплиці

STEM-проєкт з дисципліни "Мультиплатформне програмування".

Система збирає показники датчиків теплиці (температура, вологість повітря і ґрунту,
освітленість, CO2), перевіряє їх на коректність, порівнює з агрономічною нормою,
створює сповіщення з рівнем критичності та визначає тренд кожного показника.

Автор: Марчук Михайло, ІПЗ-33, ФІТ КНУ імені Тараса Шевченка.

## Стан розробки

| Етап | Зміст | Стан |
|------|-------|------|
| 1 | Схема БД, валідація, аналізатор, імітатор датчиків, CLI, тести, CI | готово |
| 2 | REST API (FastAPI) | заплановано |
| 3 | Веб-дашборд з графіками | заплановано |
| 4 | Прогнозування та рекомендації (керування поливом/провітрюванням) | заплановано |
| 5 | Звіти, експорт, підготовка до захисту | заплановано |

## Вимоги

- Python 3.11 або новіший (Windows, Linux, macOS)
- Git

Етап 1 використовує лише стандартну бібліотеку Python. Пакети з `requirements-dev.txt`
потрібні тільки для тестів і статичного аналізу.

## Встановлення

```bash
git clone <адреса репозиторію>
cd mpp
python -m venv .venv
```

Активація віртуального середовища:

| ОС | Команда |
|----|---------|
| Windows (PowerShell) | `.venv\Scripts\Activate.ps1` |
| Windows (cmd) | `.venv\Scripts\activate.bat` |
| Linux / macOS | `source .venv/bin/activate` |

```bash
pip install -r requirements-dev.txt
```

> Якщо PowerShell забороняє запуск скриптів, виконайте один раз
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Швидкий старт

```bash
python -m greenhouse demo                       # теплиця з 5 датчиками і нормами для томатів
python -m greenhouse simulate 1 --steps 24      # 24 виміри кожного датчика з кроком 30 хв
python -m greenhouse status 1                   # поточний стан і тренди
python -m greenhouse alerts --unread            # непрочитані сповіщення
```

Приклад виводу `status`:

```
Теплиця #1 'Демо-теплиця'
  Термометр-1    25.14 °C       [18; 27]         норма     → стабільно
  Гігрометр-1    65.66 %        [60; 80]         норма     ↑ росте
  Ґрунт-1        40.16 %        [45; 70]         КРИТИЧНО  ↓ падає
  Люксметр-1     29986.5 lx     норма не задана  норма     ↓ падає
  CO2-1          692.95 ppm     [400; 1200]      норма     → стабільно
```

## Усі команди

| Команда | Опис |
|---------|------|
| `sensor-types` | довідник типів датчиків і їх фізичних діапазонів |
| `list` | список теплиць |
| `add-greenhouse НАЗВА [--location МІСТО]` | створити теплицю |
| `add-sensor ID_ТЕПЛИЦІ ТИП НАЗВА` | додати датчик (`ТИП` з `sensor-types`) |
| `set-threshold ID_ТЕПЛИЦІ ТИП MIN MAX` | задати норму показника |
| `demo [--name НАЗВА]` | створити демо-теплицю |
| `record ID_ДАТЧИКА ЗНАЧЕННЯ [--at ЧАС]` | записати вимір вручну |
| `simulate ID_ТЕПЛИЦІ [--steps N] [--interval ХВ] [--seed S] [--anomaly-rate P]` | згенерувати виміри |
| `status ID_ТЕПЛИЦІ` | стан, норма і тренд кожного датчика |
| `alerts [--greenhouse ID] [--unread] [--limit N]` | сповіщення (`*` означає непрочитане) |
| `ack ID_СПОВІЩЕННЯ` | позначити сповіщення прочитаним |

Глобальний параметр `--db ШЛЯХ` задає файл БД (за замовчуванням `data/greenhouse.db`).
Також можна використати змінні середовища `GREENHOUSE_DB` і `GREENHOUSE_LOG`.

Коди завершення: `0` успіх, `2` помилка введення, `1` непередбачена помилка (деталі в `logs/greenhouse.log`).

## Тести і статичний аналіз

```bash
pytest --cov                 # тести + звіт покриття (поріг 80 %)
pytest --cov --cov-report=html   # HTML-звіт у htmlcov/index.html
pylint greenhouse tests      # статичний аналіз
```

CI (GitHub Actions, `.github/workflows/ci.yml`) на кожен push і pull request запускає
pylint та тести на Ubuntu, Windows і macOS з Python 3.11 і 3.12.

## Архітектура

```
greenhouse/
  schema.sql        схема БД (3НФ, PK/FK, CHECK, індекси)
  db.py             підключення, ініціалізація схеми, транзакції
  models.py         доменні моделі, винятки, валідація
  repository.py     доступ до даних (лише параметризовані запити)
  analyzer.py       оцінка стану (OK/WARNING/CRITICAL) і тренду
  simulator.py      імітатор датчиків
  service.py        бізнес-логіка: прийом вимірів, сповіщення, зведення
  cli.py            командний рядок
tests/              автотести pytest
docs/DECISIONS.md   лог архітектурних рішень
```

Шари залежать лише "вниз": `cli → service → repository/analyzer → models/db`.

### Схема БД

```
greenhouse (id PK, name UNIQUE, location, created_at)
sensor_type (id PK, code UNIQUE, name, unit, min_valid, max_valid)
sensor (id PK, greenhouse_id FK, sensor_type_id FK, name, is_active)   UNIQUE(greenhouse_id, name)
threshold (id PK, greenhouse_id FK, sensor_type_id FK, min_value, max_value)   UNIQUE(greenhouse_id, sensor_type_id)
reading (id PK, sensor_id FK, value, recorded_at)   INDEX(sensor_id, recorded_at)
alert (id PK, reading_id FK UNIQUE, level, message, acknowledged)
```

Видалення теплиці каскадно видаляє її датчики, норми, виміри та сповіщення.
