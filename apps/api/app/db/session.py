from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
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

    ModelBase.metadata.create_all(bind=engine)
