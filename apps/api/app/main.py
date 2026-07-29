from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import settings
from app.db.session import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.resolve(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    settings.resolve(settings.export_dir).mkdir(parents=True, exist_ok=True)
    settings.resolve(settings.project_root / "storage/database").mkdir(parents=True, exist_ok=True)
    init_db()
    yield


app = FastAPI(
    title="HUCE Teaching Assignment API",
    version="0.1.0",
    description="Excel ingestion, constraint management, CP-SAT optimization, and timetable export.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/")
def root() -> dict:
    return {"name": "HUCE Teaching Assignment API", "docs": "/docs", "health": "/api/v1/health"}
