"""Tests for database initialization and operations."""

import json


async def test_init_creates_tables(db):
    """Test that init_db creates the expected tables."""
    rows = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [row[0] for row in rows]
    assert "cases" in tables
    assert "transcripts" in tables


async def test_insert_case(db):
    """Test inserting a case record."""
    await db.execute(
        "INSERT INTO cases (id, created_at, status) VALUES (?, ?, ?)",
        ("test-case-1", "2026-01-01T00:00:00Z", "active"),
    )
    await db.commit()

    row = await db.fetch_one("SELECT * FROM cases WHERE id = ?", ("test-case-1",))
    assert row is not None
    assert row["id"] == "test-case-1"
    assert row["status"] == "active"


async def test_insert_transcript(db):
    """Test inserting a transcript segment."""
    # First create a case
    await db.execute(
        "INSERT INTO cases (id, created_at, status) VALUES (?, ?, ?)",
        ("test-case-2", "2026-01-01T00:00:00Z", "active"),
    )
    await db.commit()

    await db.execute(
        "INSERT INTO transcripts (case_id, segment_text, timestamp, segment_type) VALUES (?, ?, ?, ?)",
        ("test-case-2", "Patient has chest pain", "2026-01-01T00:00:01Z", "committed"),
    )
    await db.commit()

    row = await db.fetch_one(
        "SELECT * FROM transcripts WHERE case_id = ?", ("test-case-2",)
    )
    assert row is not None
    assert row["segment_text"] == "Patient has chest pain"
    assert row["segment_type"] == "committed"


async def test_update_nemsis_data(db):
    """Test updating NEMSIS JSON data on a case."""
    nemsis = {"patient": {"patient_name_first": "John"}}
    await db.execute(
        "INSERT INTO cases (id, created_at, status, nemsis_data) VALUES (?, ?, ?, ?)",
        ("test-case-3", "2026-01-01T00:00:00Z", "active", json.dumps(nemsis)),
    )
    await db.commit()

    row = await db.fetch_one(
        "SELECT nemsis_data FROM cases WHERE id = ?", ("test-case-3",)
    )
    data = json.loads(row["nemsis_data"])
    assert data["patient"]["patient_name_first"] == "John"


async def test_case_defaults(db):
    """Test that default values are applied."""
    await db.execute(
        "INSERT INTO cases (id, created_at, status) VALUES (?, ?, ?)",
        ("test-case-4", "2026-01-01T00:00:00Z", "active"),
    )
    await db.commit()

    row = await db.fetch_one("SELECT * FROM cases WHERE id = ?", ("test-case-4",))
    assert row["full_transcript"] == ""
    assert row["nemsis_data"] == "{}"
    assert row["core_info_complete"] == 0


async def test_multiple_transcript_segments(db):
    """Test inserting and retrieving multiple transcript segments."""
    await db.execute(
        "INSERT INTO cases (id, created_at, status) VALUES (?, ?, ?)",
        ("test-case-5", "2026-01-01T00:00:00Z", "active"),
    )

    for i in range(5):
        await db.execute(
            "INSERT INTO transcripts (case_id, segment_text, timestamp, segment_type) VALUES (?, ?, ?, ?)",
            (
                "test-case-5",
                f"Segment {i}",
                f"2026-01-01T00:00:0{i}Z",
                "committed",
            ),
        )
    await db.commit()

    row = await db.fetch_one(
        "SELECT COUNT(*) as cnt FROM transcripts WHERE case_id = ?", ("test-case-5",)
    )
    assert row["cnt"] == 5
