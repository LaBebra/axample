-- Схема БД інтелектуальної системи моніторингу теплиці.
-- Нормалізовано до 3НФ: кожна таблиця описує одну сутність,
-- неключові атрибути залежать лише від первинного ключа.

PRAGMA foreign_keys = ON;

-- Теплиця
CREATE TABLE IF NOT EXISTS greenhouse (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE CHECK (length(trim(name)) > 0),
    location    TEXT,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Довідник типів датчиків (фізичний діапазон, у межах якого значення взагалі можливе)
CREATE TABLE IF NOT EXISTS sensor_type (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    unit       TEXT NOT NULL,
    min_valid  REAL NOT NULL,
    max_valid  REAL NOT NULL,
    CHECK (min_valid < max_valid)
);

-- Конкретний датчик у теплиці
CREATE TABLE IF NOT EXISTS sensor (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    greenhouse_id   INTEGER NOT NULL REFERENCES greenhouse (id) ON DELETE CASCADE,
    sensor_type_id  INTEGER NOT NULL REFERENCES sensor_type (id) ON DELETE RESTRICT,
    name            TEXT    NOT NULL CHECK (length(trim(name)) > 0),
    is_active       INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    UNIQUE (greenhouse_id, name)
);
CREATE INDEX IF NOT EXISTS idx_sensor_greenhouse ON sensor (greenhouse_id);
CREATE INDEX IF NOT EXISTS idx_sensor_type ON sensor (sensor_type_id);

-- Оптимальний діапазон показника для конкретної теплиці (агрономічні пороги)
CREATE TABLE IF NOT EXISTS threshold (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    greenhouse_id   INTEGER NOT NULL REFERENCES greenhouse (id) ON DELETE CASCADE,
    sensor_type_id  INTEGER NOT NULL REFERENCES sensor_type (id) ON DELETE RESTRICT,
    min_value       REAL    NOT NULL,
    max_value       REAL    NOT NULL,
    CHECK (min_value < max_value),
    UNIQUE (greenhouse_id, sensor_type_id)
);

-- Виміри датчиків
CREATE TABLE IF NOT EXISTS reading (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id    INTEGER NOT NULL REFERENCES sensor (id) ON DELETE CASCADE,
    value        REAL    NOT NULL,
    recorded_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reading_sensor_time ON reading (sensor_id, recorded_at);

-- Сповіщення про вихід показника за межі норми.
-- Час сповіщення не дублюється: він береться з reading.recorded_at (3НФ).
CREATE TABLE IF NOT EXISTS alert (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    reading_id    INTEGER NOT NULL UNIQUE REFERENCES reading (id) ON DELETE CASCADE,
    level         TEXT    NOT NULL CHECK (level IN ('warning', 'critical')),
    message       TEXT    NOT NULL,
    acknowledged  INTEGER NOT NULL DEFAULT 0 CHECK (acknowledged IN (0, 1))
);
CREATE INDEX IF NOT EXISTS idx_alert_acknowledged ON alert (acknowledged);

-- Початкові дані довідника
INSERT OR IGNORE INTO sensor_type (code, name, unit, min_valid, max_valid) VALUES
    ('temperature',   'Температура повітря', '°C',  -40, 80),
    ('air_humidity',  'Вологість повітря',   '%',     0, 100),
    ('soil_moisture', 'Вологість ґрунту',    '%',     0, 100),
    ('light',         'Освітленість',        'lx',    0, 200000),
    ('co2',           'Концентрація CO2',    'ppm',   0, 10000);
