from contextlib import contextmanager
from datetime import datetime, timezone
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "monitoring.db")


@contextmanager
def get_db_connection():
    """Context manager for SQLite database connection that guarantees closing."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """Creates the SQLite database file and tables on first run, applying column migrations."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL,
                patient_id TEXT,
                anesthetist_id TEXT,
                or_room TEXT
            );
        """)
        # Fallback migration check for existing monitoring.db files
        cursor.execute("PRAGMA table_info(cases);")
        existing_cols = {row["name"] for row in cursor.fetchall()}
        for col_name in ["patient_id", "anesthetist_id", "or_room"]:
            if col_name not in existing_cols:
                cursor.execute(f"ALTER TABLE cases ADD COLUMN {col_name} TEXT;")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                heart_rate REAL,
                spo2 REAL,
                bp_systolic REAL,
                bp_diastolic REAL,
                etco2 REAL,
                FOREIGN KEY (case_id) REFERENCES cases(case_id)
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ground_truth (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT,
                field TEXT NOT NULL,
                value REAL NOT NULL,
                timestamp TEXT NOT NULL
            );
        """)
        conn.commit()


def create_case(
    patient_id: Optional[str] = None,
    anesthetist_id: Optional[str] = None,
    or_room: Optional[str] = None
) -> str:
    """Creates a new case record with status 'active' and optional metadata."""
    now_iso = datetime.now(timezone.utc).isoformat()
    case_id = f"case_{int(time.time() * 1000)}"
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO cases (case_id, started_at, ended_at, status, patient_id, anesthetist_id, or_room) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (case_id, now_iso, None, "active", patient_id, anesthetist_id, or_room)
        )
        conn.commit()
    return case_id


def save_reading(
    case_id: str,
    heart_rate: Optional[float] = None,
    spo2: Optional[float] = None,
    bp_systolic: Optional[float] = None,
    bp_diastolic: Optional[float] = None,
    etco2: Optional[float] = None
):
    """Saves a vital signs reading for a case."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO readings 
            (case_id, timestamp, heart_rate, spo2, bp_systolic, bp_diastolic, etco2)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (case_id, now_iso, heart_rate, spo2, bp_systolic, bp_diastolic, etco2)
        )
        conn.commit()


def end_case(case_id: str):
    """Marks a case as ended with the current ISO timestamp."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE cases SET status = ?, ended_at = ? WHERE case_id = ?",
            ("ended", now_iso, case_id)
        )
        conn.commit()


def get_case_readings(case_id: str) -> List[Dict[str, Any]]:
    """Returns all readings for a case ordered by timestamp."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, case_id, timestamp, heart_rate, spo2, bp_systolic, bp_diastolic, etco2 FROM readings WHERE case_id = ? ORDER BY timestamp ASC",
            (case_id,)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_active_case() -> Optional[str]:
    """Returns the currently active case_id if one exists, else None."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT case_id FROM cases WHERE status = 'active' ORDER BY started_at DESC LIMIT 1"
        )
        row = cursor.fetchone()
        return row["case_id"] if row else None


def get_latest_case() -> Optional[str]:
    """Returns the most recent case_id created in the database."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT case_id FROM cases ORDER BY started_at DESC LIMIT 1"
        )
        row = cursor.fetchone()
        return row["case_id"] if row else None


def get_case(case_id: str) -> Optional[Dict[str, Any]]:
    """Returns metadata for a specific case_id."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT case_id, started_at, ended_at, status, patient_id, anesthetist_id, or_room FROM cases WHERE case_id = ?",
            (case_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def save_ground_truth_db(field: str, value: Any, timestamp: str, case_id: Optional[str] = None):
    """Saves a ground truth entry in SQLite database."""
    init_db()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO ground_truth (case_id, field, value, timestamp) VALUES (?, ?, ?, ?)",
            (case_id, field, float(value) if value is not None else 0.0, timestamp)
        )
        conn.commit()


def get_ground_truth_db(case_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns all ground truth entries from SQLite database."""
    init_db()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if case_id:
            cursor.execute("SELECT field, value, timestamp FROM ground_truth WHERE case_id = ? ORDER BY timestamp ASC", (case_id,))
        else:
            cursor.execute("SELECT field, value, timestamp FROM ground_truth ORDER BY timestamp ASC")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


# Initialize database schema on module load
init_db()

