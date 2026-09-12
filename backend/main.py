"""
App entrypoint. Run with: uvicorn main:app --reload
"""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from logging_config import setup_logging
from config import settings
from database.session import init_db, engine
from api import investigation, evidence, verification, reports

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dev convenience: auto-create tables on startup.
    # In production, use `alembic upgrade head` instead and remove this call.
    environment = settings.environment.lower()
    if environment in ("development", "dev", "local", "test"):
        await init_db()
        logger.info("Dev mode (%s): tables ensured via create_all().", environment)
    else:
        logger.info(
            "Environment=%s: skipping create_all(); run `alembic upgrade head` "
            "before starting the app in production.",
            settings.environment,
        )
    yield


app = FastAPI(title="Study Abroad Safety Assistant", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=False,
)

app.include_router(investigation.router)
app.include_router(evidence.router)
app.include_router(verification.router)
app.include_router(reports.router)


@app.get("/health")
async def health():
    """
    Liveness/readiness probe. Actually pings the database (the one
    dependency every request needs) and reports whether each external
    provider is configured, without spending quota on a live call to paid
    APIs on every health check.

    A separate deep check against the free/keyless Hipo API is included
    since it costs nothing and proves outbound network access works.
    """
    checks: dict[str, dict] = {}
    healthy = True

    start = time.perf_counter()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = {
            "status": "ok",
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
        }
    except Exception as exc:
        healthy = False
        logger.error("Health check: database ping failed: %s", exc)
        checks["database"] = {"status": "error", "detail": str(exc)}

    checks["providers_configured"] = {
        "gemini": bool(settings.gemini_api_key),
        "groq": bool(settings.groq_api_key),
        "tavily": bool(settings.tavily_api_key),
        "opensanctions": bool(settings.opensanctions_api_key),
    }

    try:
        from research.hipo import search_university

        hipo_start = time.perf_counter()
        result = await search_university("Test", None)
        checks["hipo_reachable"] = {
            "status": "error" if result.get("error") else "ok",
            "latency_ms": round((time.perf_counter() - hipo_start) * 1000, 1),
            "detail": result.get("error"),
        }
    except Exception as exc:
        logger.warning("Health check: Hipo reachability probe failed: %s", exc)
        checks["hipo_reachable"] = {"status": "error", "detail": str(exc)}

    checks["status"] = "ok" if healthy else "degraded"
    return JSONResponse(status_code=200 if healthy else 503, content=checks)
