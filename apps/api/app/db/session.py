from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine_options = {"connect_args": connect_args}
if settings.database_url == "sqlite://":
    engine_options["poolclass"] = StaticPool
engine = create_engine(settings.database_url, **engine_options)


if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def init_db() -> None:
    from app.models.entities import Base as ModelBase

    # Ephemeral sqlite:// is used only by tests. Persistent databases are
    # upgraded by Alembic before the application starts.
    if settings.database_url == "sqlite://":
        ModelBase.metadata.create_all(bind=engine)
        return
    from alembic import command
    from alembic.config import Config

    config = Config(str(settings.project_root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")
    # env.py commits the Alembic revision alongside migration DML. Never
    # manually stamp head during startup; upgrade must prove it was reached.
