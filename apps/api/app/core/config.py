from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    project_root: Path = Path(__file__).resolve().parents[4]
    database_url: str = "sqlite:///./storage/database/huce.db"
    upload_dir: Path = Path("./storage/uploads")
    export_dir: Path = Path("./storage/exports")
    source_dir: Path = Path("./data/local/source")
    cors_origins: str = "http://127.0.0.1:3000,http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def resolve(self, value: Path) -> Path:
        return value if value.is_absolute() else self.project_root / value


settings = Settings()
