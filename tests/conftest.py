import os

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

# In-memory DB and no external API keys for tests
os.environ["OPENAI_API_KEY"] = ""
os.environ["ELEVENLABS_API_KEY"] = ""
os.environ["PERPLEXITY_API_KEY"] = ""
os.environ["DATABASE_PATH"] = ":memory:"
os.environ["DATABASE_URL"] = ""
os.environ["SEED_DEMO_CASES"] = "false"

from app.database import close_db, init_db
from app.main import app

# Disable external service calls — tests use synthetic dummy data
import app.services.fhir_client as _fhir_mod
import app.services.gp_lookup as _gp_lookup_mod

_fhir_mod.FHIR_SERVERS = []
_gp_lookup_mod.PERPLEXITY_API_KEY = ""


@pytest_asyncio.fixture
async def db():
    """Provide a fresh in-memory database for each test."""
    import app.database as db_mod

    # Close any existing connection
    if db_mod._db is not None:
        try:
            await db_mod._db.close()
        except Exception:
            pass
    db_mod._db = None

    # Override module-level config directly (avoids fragile importlib.reload)
    db_mod.DATABASE_PATH = ":memory:"
    db_mod.DATABASE_URL = ""
    db_mod.SEED_DEMO_CASES = False

    await init_db()
    database = await db_mod.get_db()
    yield database
    await close_db()


@pytest.fixture
def client(db):
    """Provide a synchronous TestClient for HTTP endpoint tests."""
    return TestClient(app)


@pytest_asyncio.fixture
async def async_client(db):
    """Provide an async httpx client for async HTTP tests."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
