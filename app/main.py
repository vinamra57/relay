import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import close_db, init_db
from app.routers import cases, hospital, stream

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Aria Health...")
    await init_db()
    logger.info("Database initialized")
    yield
    await close_db()
    logger.info("Aria Health shut down")


app = FastAPI(
    title="Aria Health",
    description="AI Emergency Response System - Automated ePCR for Paramedics",
    version="0.1.0",
    lifespan=lifespan,
)

# Include routers
app.include_router(stream.router)
app.include_router(cases.router)
app.include_router(hospital.router)

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def serve_paramedic_ui():
    return FileResponse("static/index.html")


@app.get("/demo")
async def serve_enhanced_ui():
    """Enhanced UI showing multi-source patient data aggregation complexity."""
    return FileResponse("static/index_enhanced.html")


@app.get("/hospital")
async def serve_hospital_ui():
    return FileResponse("static/hospital.html")
