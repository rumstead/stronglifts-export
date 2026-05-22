CREATE TABLE IF NOT EXISTS sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_date TEXT NOT NULL,
    workout_name TEXT NOT NULL,
    duration_seconds INTEGER,
    exercise_name TEXT NOT NULL,
    set_order INTEGER NOT NULL,
    weight REAL,
    reps INTEGER,
    distance REAL,
    seconds REAL,
    rpe REAL,
    volume REAL,
    estimated_1rm REAL,
    source_file TEXT NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE,
    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sets_exercise_date ON sets (exercise_name, workout_date);
CREATE INDEX IF NOT EXISTS idx_sets_workout_date ON sets (workout_date);

CREATE TABLE IF NOT EXISTS email_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL,
    sender_email TEXT NOT NULL,
    subject TEXT,
    attachment_name TEXT NOT NULL,
    attachment_hash TEXT NOT NULL UNIQUE,
    source_mailbox TEXT NOT NULL,
    inserted_sets INTEGER NOT NULL DEFAULT 0,
    skipped_sets INTEGER NOT NULL DEFAULT 0,
    processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(message_id, attachment_name)
);

CREATE INDEX IF NOT EXISTS idx_email_imports_message ON email_imports (message_id);
