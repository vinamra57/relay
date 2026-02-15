from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Iterable, Sequence
from urllib.parse import urlparse

import aiosqlite

from app.config import DATABASE_MAX_CONNECTIONS, DATABASE_PATH, DATABASE_URL, SEED_DEMO_CASES
from app.models.nemsis import NEMSISRecord

try:  # Optional: only required when DATABASE_URL is set (Cloud SQL / Postgres)
    import asyncpg  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    asyncpg = None

logger = logging.getLogger(__name__)


class DatabaseAdapter:
    engine: str

    async def execute(self, query: str, params: Sequence | None = None) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    async def executemany(self, query: str, seq_params: Iterable[Sequence]) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    async def fetch_one(self, query: str, params: Sequence | None = None):  # pragma: no cover - interface
        raise NotImplementedError

    async def fetch_all(self, query: str, params: Sequence | None = None):  # pragma: no cover - interface
        raise NotImplementedError

    async def commit(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    async def close(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    async def executescript(self, script: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass
class SQLiteAdapter(DatabaseAdapter):
    conn: aiosqlite.Connection
    engine: str = "sqlite"

    async def execute(self, query: str, params: Sequence | None = None) -> None:
        await self.conn.execute(query, params or ())

    async def executemany(self, query: str, seq_params: Iterable[Sequence]) -> None:
        await self.conn.executemany(query, seq_params)

    async def fetch_one(self, query: str, params: Sequence | None = None):
        cursor = await self.conn.execute(query, params or ())
        return await cursor.fetchone()

    async def fetch_all(self, query: str, params: Sequence | None = None):
        cursor = await self.conn.execute(query, params or ())
        return await cursor.fetchall()

    async def commit(self) -> None:
        await self.conn.commit()

    async def close(self) -> None:
        await self.conn.close()

    async def executescript(self, script: str) -> None:
        await self.conn.executescript(script)


@dataclass
class PostgresAdapter(DatabaseAdapter):
    pool: "asyncpg.Pool"  # type: ignore[name-defined]
    engine: str = "postgres"

    @staticmethod
    def _translate_query(query: str) -> str:
        # Convert SQLite-style ? placeholders to asyncpg-style $1, $2, ...
        if "$1" in query:
            return query
        idx = 1
        out = []
        for ch in query:
            if ch == "?":
                out.append(f"${idx}")
                idx += 1
            else:
                out.append(ch)
        return "".join(out)

    async def execute(self, query: str, params: Sequence | None = None) -> None:
        q = self._translate_query(query)
        async with self.pool.acquire() as conn:
            await conn.execute(q, *(params or ()))

    async def executemany(self, query: str, seq_params: Iterable[Sequence]) -> None:
        q = self._translate_query(query)
        async with self.pool.acquire() as conn:
            await conn.executemany(q, seq_params)

    async def fetch_one(self, query: str, params: Sequence | None = None):
        q = self._translate_query(query)
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(q, *(params or ()))

    async def fetch_all(self, query: str, params: Sequence | None = None):
        q = self._translate_query(query)
        async with self.pool.acquire() as conn:
            return await conn.fetch(q, *(params or ()))

    async def commit(self) -> None:
        # asyncpg autocommits per statement unless an explicit transaction is used.
        return

    async def close(self) -> None:
        await self.pool.close()

    async def executescript(self, script: str) -> None:
        # Not supported for Postgres; callers should split statements.
        raise NotImplementedError


_db: DatabaseAdapter | None = None


async def get_db() -> DatabaseAdapter:
    global _db
    if _db is None:
        if DATABASE_URL:
            if DATABASE_URL.startswith("sqlite"):
                sqlite_path = _sqlite_path_from_url(DATABASE_URL) or DATABASE_PATH
                conn = await aiosqlite.connect(sqlite_path)
                conn.row_factory = aiosqlite.Row
                _db = SQLiteAdapter(conn)
                logger.info("Connected to SQLite database at %s", sqlite_path)
            else:
                if asyncpg is None:
                    raise RuntimeError(
                        "DATABASE_URL is set but asyncpg is not installed. "
                        "Install asyncpg or unset DATABASE_URL."
                    )
                pool = await asyncpg.create_pool(
                    dsn=DATABASE_URL,
                    min_size=1,
                    max_size=DATABASE_MAX_CONNECTIONS,
                )
                _db = PostgresAdapter(pool)
                logger.info("Connected to Postgres database")
        else:
            conn = await aiosqlite.connect(DATABASE_PATH)
            conn.row_factory = aiosqlite.Row
            _db = SQLiteAdapter(conn)
            logger.info("Connected to SQLite database at %s", DATABASE_PATH)
    return _db


def _sqlite_path_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or ""
    if not path or path == "/":
        return ""
    # sqlite:////absolute/path.db -> keep absolute path
    if url.startswith("sqlite:////"):
        return path
    # sqlite:///relative.db -> strip leading slash
    if path.startswith("/"):
        return path[1:]
    return path


SQLITE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS cases (
        id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        full_transcript TEXT DEFAULT '',
        nemsis_data TEXT DEFAULT '{}',
        core_info_complete INTEGER DEFAULT 0,
        patient_name TEXT,
        patient_address TEXT,
        patient_age TEXT,
        patient_gender TEXT,
        gp_response TEXT,
        medical_db_response TEXT,
        clinical_insights TEXT,
        summary TEXT,
        updated_at TEXT
    );

    CREATE TABLE IF NOT EXISTS transcripts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id TEXT NOT NULL,
        segment_text TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        segment_type TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (case_id) REFERENCES cases(id)
    );

    CREATE TABLE IF NOT EXISTS gp_call_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id TEXT NOT NULL,
        call_time TEXT NOT NULL,
        phone_number TEXT NOT NULL,
        patient_name TEXT,
        patient_dob TEXT,
        outcome TEXT NOT NULL,
        call_sid TEXT,
        conversation_id TEXT,
        transcript TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (case_id) REFERENCES cases(id)
    );
"""

POSTGRES_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS cases (
        id TEXT PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        full_transcript TEXT DEFAULT '',
        nemsis_data TEXT DEFAULT '{}',
        core_info_complete INTEGER DEFAULT 0,
        patient_name TEXT,
        patient_address TEXT,
        patient_age TEXT,
        patient_gender TEXT,
        gp_response TEXT,
        medical_db_response TEXT,
        clinical_insights TEXT,
        summary TEXT,
        updated_at TIMESTAMPTZ
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS transcripts (
        id BIGSERIAL PRIMARY KEY,
        case_id TEXT NOT NULL REFERENCES cases(id),
        segment_text TEXT NOT NULL,
        timestamp TIMESTAMPTZ NOT NULL,
        segment_type TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS gp_call_audit (
        id BIGSERIAL PRIMARY KEY,
        case_id TEXT NOT NULL REFERENCES cases(id),
        call_time TIMESTAMPTZ NOT NULL,
        phone_number TEXT NOT NULL,
        patient_name TEXT,
        patient_dob TEXT,
        outcome TEXT NOT NULL,
        call_sid TEXT,
        conversation_id TEXT,
        transcript TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """,
]


async def init_db() -> None:
    db = await get_db()

    if db.engine == "sqlite":
        await db.executescript(SQLITE_SCHEMA)
        # Add GP columns to cases if they don't exist (migration-safe)
        for stmt in (
            "ALTER TABLE cases ADD COLUMN gp_call_status TEXT",
            "ALTER TABLE cases ADD COLUMN gp_call_transcript TEXT",
            "ALTER TABLE cases ADD COLUMN clinical_insights TEXT",
        ):
            try:
                await db.execute(stmt)
            except Exception:  # noqa: S110
                pass
    else:
        for stmt in POSTGRES_SCHEMA:
            await db.execute(stmt)
        for stmt in (
            "ALTER TABLE cases ADD COLUMN IF NOT EXISTS gp_call_status TEXT",
            "ALTER TABLE cases ADD COLUMN IF NOT EXISTS gp_call_transcript TEXT",
            "ALTER TABLE cases ADD COLUMN IF NOT EXISTS clinical_insights TEXT",
        ):
            await db.execute(stmt)

    await db.commit()

    if SEED_DEMO_CASES:
        await _seed_demo_cases(db)


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


async def _seed_demo_cases(db: DatabaseAdapter) -> None:
    """Seed demo cases for UI previews when running in dummy mode."""
    now = datetime.now(UTC)

    demo_cases = []

    # Case 1: STEMI
    c1 = NEMSISRecord()
    c1.patient.patient_name_first = "John David"
    c1.patient.patient_name_last = "Smith"
    c1.patient.patient_age = "45"
    c1.patient.patient_gender = "Male"
    c1.patient.patient_address = "742 Evergreen Terrace"
    c1.patient.patient_city = "Springfield"
    c1.patient.patient_state = "Illinois"
    c1.vitals.systolic_bp = 160
    c1.vitals.diastolic_bp = 95
    c1.vitals.heart_rate = 110
    c1.vitals.respiratory_rate = 22
    c1.vitals.spo2 = 94
    c1.vitals.blood_glucose = 145
    c1.vitals.gcs_total = 15
    c1.situation.chief_complaint = "Chest pain radiating to left arm"
    c1.situation.primary_impression = "STEMI"
    c1.situation.secondary_impression = "ST elevation in leads V1-V4"
    c1.situation.complaint_duration = "30 minutes"
    c1.procedures.procedures = ["IV access - right antecubital", "12-lead ECG"]
    c1.medications.medications = ["Aspirin 324mg PO", "Nitroglycerin 0.4mg SL"]
    c1.history.medical_history = ["Hypertension", "Diabetes mellitus type 2"]
    c1.history.allergies = ["NKDA"]
    c1.disposition.destination_facility = "Springfield General Hospital"
    c1.disposition.transport_mode = "Ground"
    demo_cases.append((
        "demo-stemi",
        now.isoformat(),
        "active",
        "",
        c1.model_dump_json(),
        1,
        "John David Smith",
        c1.patient.patient_address,
        c1.patient.patient_age,
        c1.patient.patient_gender,
        "GP transmission: patient followed at Greenfield Medical Center. Last ECG documented.",
        "Medical DB: hx of HTN, T2DM; no known allergies.",
        now.isoformat(),
    ))

    # Case 2: Stroke
    c2 = NEMSISRecord()
    c2.patient.patient_name_first = "Maria"
    c2.patient.patient_name_last = "Lopez"
    c2.patient.patient_age = "68"
    c2.patient.patient_gender = "Female"
    c2.patient.patient_address = "229 Lakeview Drive"
    c2.patient.patient_city = "Oakridge"
    c2.patient.patient_state = "Illinois"
    c2.vitals.systolic_bp = 178
    c2.vitals.diastolic_bp = 98
    c2.vitals.heart_rate = 92
    c2.vitals.respiratory_rate = 18
    c2.vitals.spo2 = 96
    c2.vitals.gcs_total = 13
    c2.situation.chief_complaint = "Slurred speech, right arm weakness"
    c2.situation.primary_impression = "Stroke"
    c2.situation.complaint_duration = "20 minutes"
    c2.history.medical_history = ["Atrial fibrillation", "Hypertension"]
    c2.history.allergies = ["Penicillin"]
    c2.disposition.destination_facility = "Oakridge Stroke Center"
    c2.disposition.transport_mode = "Ground"
    demo_cases.append((
        "demo-stroke",
        (now - timedelta(minutes=6)).isoformat(),
        "active",
        "",
        c2.model_dump_json(),
        1,
        "Maria Lopez",
        c2.patient.patient_address,
        c2.patient.patient_age,
        c2.patient.patient_gender,
        "GP transmission: known AFib, on anticoagulant per family.",
        "Medical DB: prior stroke 2019; allergies to penicillin.",
        (now - timedelta(minutes=2)).isoformat(),
    ))

    # Case 3: Trauma
    c3 = NEMSISRecord()
    c3.patient.patient_name_first = "Ethan"
    c3.patient.patient_name_last = "Brooks"
    c3.patient.patient_age = "24"
    c3.patient.patient_gender = "Male"
    c3.patient.patient_address = "91 Riverbend Ave"
    c3.patient.patient_city = "Lakeview"
    c3.patient.patient_state = "Illinois"
    c3.vitals.systolic_bp = 90
    c3.vitals.diastolic_bp = 60
    c3.vitals.heart_rate = 132
    c3.vitals.respiratory_rate = 26
    c3.vitals.spo2 = 92
    c3.vitals.gcs_total = 14
    c3.vitals.pain_scale = 9
    c3.situation.chief_complaint = "MVC with abdominal pain"
    c3.situation.primary_impression = "Trauma"
    c3.situation.complaint_duration = "15 minutes"
    c3.procedures.procedures = ["C-spine stabilization", "IV access - left antecubital"]
    c3.history.medical_history = ["No known conditions"]
    c3.history.allergies = ["NKDA"]
    c3.disposition.destination_facility = "Lakeview Trauma Center"
    c3.disposition.transport_mode = "Ground"
    demo_cases.append((
        "demo-trauma",
        (now - timedelta(minutes=12)).isoformat(),
        "active",
        "",
        c3.model_dump_json(),
        1,
        "Ethan Brooks",
        c3.patient.patient_address,
        c3.patient.patient_age,
        c3.patient.patient_gender,
        "GP transmission: none available, family en route.",
        "Medical DB: no records found.",
        (now - timedelta(minutes=4)).isoformat(),
    ))

    existing_rows = await db.fetch_all(
        "SELECT id FROM cases WHERE id IN ('demo-stemi', 'demo-stroke', 'demo-trauma')"
    )
    existing = {row["id"] for row in existing_rows}
    demo_cases = [case for case in demo_cases if case[0] not in existing]
    if not demo_cases:
        return

    await db.executemany(
        """INSERT INTO cases (
            id, created_at, status, full_transcript, nemsis_data, core_info_complete,
            patient_name, patient_address, patient_age, patient_gender,
            gp_response, medical_db_response, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        demo_cases,
    )
    await db.commit()


async def ensure_demo_cases(db: DatabaseAdapter) -> None:
    """Ensure demo cases exist when seeding is enabled."""
    if not SEED_DEMO_CASES:
        return
    result = await db.fetch_one(
        "SELECT COUNT(*) as count FROM cases WHERE status = 'active'"
    )
    count = result["count"] if result else 0
    if count == 0:
        await _seed_demo_cases(db)
