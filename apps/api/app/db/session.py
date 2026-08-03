from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings


class Base(DeclarativeBase):
    pass


database_url = settings.database_url
if database_url.startswith("sqlite:///./"):
    database_path = settings.resolve(Path(database_url.removeprefix("sqlite:///./")))
    database_path.parent.mkdir(parents=True, exist_ok=True)
    database_url = f"sqlite:///{database_path.as_posix()}"
elif database_url.startswith("postgresql://"):
    # Vercel Marketplace provides a standard PostgreSQL URL. Explicitly select
    # psycopg 3 so SQLAlchemy does not look for the legacy psycopg2 package.
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine_options = {"connect_args": connect_args}
if database_url == "sqlite://":
    engine_options["poolclass"] = StaticPool
engine = create_engine(database_url, **engine_options)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def init_db() -> None:
    from app.models.entities import Base as ModelBase

    if engine.dialect.name == "postgresql":
        # Multiple Vercel cold starts can initialize the same Neon database at
        # once. Serialize schema creation so concurrent workers cannot race on
        # CREATE TABLE / CREATE SEQUENCE statements.
        with engine.begin() as connection:
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": 20262027},
            )
            ModelBase.metadata.create_all(bind=connection)
        return

    ModelBase.metadata.create_all(bind=engine)
