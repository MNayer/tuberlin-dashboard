import os
import sqlite3
from datetime import datetime, timezone

import pandas as pd
from flask import g

DB_PATH = os.environ.get('DB_PATH', '/app/data/app.db')
CSV_SEED_PATH = os.environ.get('CSV_SEED_PATH', '/app/data/status.csv')


SCHEMA = """
CREATE TABLE IF NOT EXISTS buildings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kuerzel TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    adresse TEXT,
    campus TEXT,
    status TEXT NOT NULL DEFAULT 'healthy',
    is_major INTEGER NOT NULL DEFAULT 0,
    news_link TEXT,
    workplaces INTEGER,
    size_sqm REAL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS magic_links (
    token TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS building_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    building_id INTEGER,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    message TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    reviewed_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (building_id) REFERENCES buildings(id)
);

CREATE TABLE IF NOT EXISTS reisekosten (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    destination TEXT NOT NULL,
    purpose TEXT,
    antrag_date TEXT NOT NULL,
    travel_start_date TEXT,
    travel_end_date TEXT,
    estimated_amount REAL,
    advance_amount REAL,
    abrechnung_date TEXT,
    final_amount REAL,
    settlement_date TEXT,
    status TEXT NOT NULL DEFAULT 'antrag_submitted',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""


def _to_bool(v):
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes", "ja")


def get_db():
    if 'db' not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(_exc=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _seed_buildings_if_empty(conn)
    finally:
        conn.close()


def _seed_buildings_if_empty(conn):
    count = conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0]
    if count > 0:
        return
    if not os.path.exists(CSV_SEED_PATH):
        print(f"[db] no seed CSV at {CSV_SEED_PATH}, skipping seed")
        return

    df = pd.read_csv(CSV_SEED_PATH)
    df['is_major'] = df['is_major'].apply(_to_bool)
    df['news_link'] = df['news_link'].fillna('')

    rows = []
    for _, r in df.iterrows():
        rows.append((
            r['Kuerzel'], r['Name'], r['Adresse'], r['Campus'],
            r['status'], 1 if r['is_major'] else 0, r['news_link'] or None,
        ))
    conn.executemany(
        """
        INSERT OR IGNORE INTO buildings
            (kuerzel, name, adresse, campus, status, is_major, news_link)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    print(f"[db] seeded {len(rows)} buildings from {CSV_SEED_PATH}")
