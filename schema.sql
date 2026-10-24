-- SQLite Schema for PC Power Monitor & Electricity Cost Analyzer
-- Stores monitoring sessions and continuous per-second telemetry records

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    start_time TEXT NOT NULL,
    end_time TEXT,
    duration_seconds REAL DEFAULT 0,
    total_energy_wh REAL DEFAULT 0,
    total_energy_kwh REAL DEFAULT 0,
    total_cost_lkr REAL DEFAULT 0,
    avg_power_watts REAL DEFAULT 0,
    peak_power_watts REAL DEFAULT 0,
    min_power_watts REAL DEFAULT 0,
    tariff_rate_lkr REAL NOT NULL,
    highest_consumer TEXT,
    data_quality TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp_iso TEXT NOT NULL,
    elapsed_seconds REAL NOT NULL,
    total_system_watts REAL NOT NULL,
    measured_watts REAL NOT NULL,
    estimated_watts REAL NOT NULL,
    data_quality TEXT NOT NULL,
    highest_consumer TEXT,
    cpu_watts REAL,
    gpu_watts REAL,
    ram_watts REAL,
    storage_watts REAL,
    fans_watts REAL,
    motherboard_watts REAL,
    cumulative_wh REAL NOT NULL,
    cumulative_kwh REAL NOT NULL,
    cost_lkr REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_measurements_session ON measurements(session_id);
CREATE INDEX IF NOT EXISTS idx_measurements_timestamp ON measurements(timestamp_iso);
