import aiosqlite
from app.config import DATABASE_PATH

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DATABASE_PATH)
        _db.row_factory = aiosqlite.Row
    return _db


async def init_db():
    db = await get_db()
    await db.executescript("""
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
    """)
    await db.commit()


async def close_db():
    global _db
    if _db is not None:
        await _db.close()
        _db = None
