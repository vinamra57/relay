import os

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

# In-memory DB and no API keys for tests
os.environ["OPENAI_API_KEY"] = ""
os.environ["ELEVENLABS_API_KEY"] = ""
os.environ["DATABASE_PATH"] = ":memory:"
os.environ["SEED_DEMO_CASES"] = "false"

from app.database import close_db, get_db, init_db
from app.main import app


@pytest_asyncio.fixture
async def db():
    """Provide a fresh in-memory database for each test."""
    # Reset the global db connection
    import app.database as db_mod

    db_mod._db = None
    os.environ["DATABASE_PATH"] = ":memory:"

    # Re-import config to pick up the new path
    import importlib

    import app.config as config_mod

    importlib.reload(config_mod)
    importlib.reload(db_mod)

    await init_db()
    database = await get_db()
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
