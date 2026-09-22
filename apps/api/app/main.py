from contextlib import asynccontextmanager
from pathlib import Path
from secrets import compare_digest

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.engine import make_url

from app.api.routes import router
from app.api.source_routes import router as source_router
from app.api.lecturer_routes import router as lecturer_router
from app.core.config import settings
from app.db.session import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.storage_backend == "local":
        settings.resolve(settings.upload_dir).mkdir(parents=True, exist_ok=True)
        settings.resolve(settings.export_dir).mkdir(parents=True, exist_ok=True)
    if settings.database_url.startswith("sqlite") and settings.database_url != "sqlite://":
        database_path = make_url(settings.database_url).database
        if database_path and database_path != ":memory:":
            settings.resolve(Path(database_path)).parent.mkdir(parents=True, exist_ok=True)
    if settings.should_run_migrations_on_startup:
        init_db()
    yield


app = FastAPI(
    title="HUCE Teaching Assignment API",
    version="0.1.0",
    description="Excel ingestion, constraint management, CP-SAT optimization, and timetable export.",
    lifespan=lifespan,
    debug=False,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def protect_internal_api(request: Request, call_next):
    if (
        settings.environment != "development"
        and request.method != "OPTIONS"
        and request.url.path != "/api/v1/health"
    ):
        provided = request.headers.get("x-internal-api-key", "")
        expected = settings.internal_api_token or ""
        if not provided or not expected or not compare_digest(provided, expected):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


app.include_router(router)
app.include_router(source_router)
app.include_router(lecturer_router)


@app.get("/")
def root() -> dict:
    return {"name": "HUCE Teaching Assignment API", "docs": "/docs", "health": "/api/v1/health"}
