from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    project_root: Path = Path(__file__).resolve().parents[4]
    environment: Literal["development", "staging", "production"] = "development"
    database_url: str = "sqlite:///./storage/database/huce.db"
    upload_dir: Path = Path("./storage/uploads")
    export_dir: Path = Path("./storage/exports")
    source_dir: Path = Path("./data/local/source")
    allowed_origins: str = Field(
        "http://127.0.0.1:3000,http://localhost:3000,"
        "http://127.0.0.1:3010,http://localhost:3010",
        validation_alias=AliasChoices("ALLOWED_ORIGINS", "CORS_ORIGINS"),
    )
    storage_backend: Literal["local", "s3"] = "local"
    max_upload_bytes: int = 20 * 1024 * 1024
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    internal_api_token: str | None = None
    run_migrations_on_startup: bool | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("database_url", mode="before")
    @classmethod
    def select_psycopg_driver(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value.removeprefix("postgres://")
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value.removeprefix("postgresql://")
        return value

    def resolve(self, value: Path) -> Path:
        return value if value.is_absolute() else self.project_root / value

    @property
    def should_run_migrations_on_startup(self) -> bool:
        if self.run_migrations_on_startup is not None:
            return self.run_migrations_on_startup
        return self.environment == "development"

    @model_validator(mode="after")
    def validate_deployment_configuration(self) -> "Settings":
        if self.max_upload_bytes <= 0:
            raise ValueError("MAX_UPLOAD_BYTES phải lớn hơn 0.")
        if self.environment == "development":
            return self
        missing = []
        if self.run_migrations_on_startup:
            missing.append("RUN_MIGRATIONS_ON_STARTUP=false")
        if self.database_url.startswith("sqlite"):
            missing.append("DATABASE_URL (PostgreSQL)")
        if self.storage_backend != "s3":
            missing.append("STORAGE_BACKEND=s3")
        for name, value in (
            ("ALLOWED_ORIGINS", self.allowed_origins),
            ("S3_BUCKET", self.s3_bucket),
            ("S3_REGION", self.s3_region),
            ("S3_ACCESS_KEY_ID", self.s3_access_key_id),
            ("S3_SECRET_ACCESS_KEY", self.s3_secret_access_key),
            ("INTERNAL_API_TOKEN", self.internal_api_token),
        ):
            if not value:
                missing.append(name)
        if any(
            origin.strip().startswith(("http://localhost", "http://127.0.0.1"))
            for origin in self.allowed_origins.split(",")
        ):
            missing.append("ALLOWED_ORIGINS (không dùng localhost)")
        if any(origin.strip() == "*" for origin in self.allowed_origins.split(",")):
            missing.append("ALLOWED_ORIGINS (không dùng wildcard)")
        if missing:
            raise ValueError("Thiếu cấu hình deployment: " + ", ".join(missing))
        return self


settings = Settings()
