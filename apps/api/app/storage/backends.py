from __future__ import annotations

import shutil
import tempfile
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterator, Protocol

from app.core.config import Settings, settings


class StorageBackend(Protocol):
    def put(self, source: Path, key: str) -> str: ...

    def materialize(self, reference: str) -> AbstractContextManager[Path]: ...


def _safe_key(key: str) -> str:
    candidate = PurePosixPath(key)
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.name:
        raise ValueError("STORAGE_KEY_INVALID")
    return candidate.as_posix()


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def put(self, source: Path, key: str) -> str:
        safe_key = _safe_key(key)
        destination = self.root / safe_key
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise ValueError("STORAGE_OBJECT_ALREADY_EXISTS")
        shutil.copy2(source, destination)
        return f"local://{safe_key}"

    @contextmanager
    def materialize(self, reference: str) -> Iterator[Path]:
        if reference.startswith("local://"):
            path = self.root / _safe_key(reference.removeprefix("local://"))
        else:
            # Backward compatibility for frozen v1/v1.1 profiles.
            path = Path(reference)
            if not path.is_file():
                path = self.root.parent / "template" / Path(reference).name
        if not path.is_file():
            raise FileNotFoundError(reference)
        yield path


class S3CompatibleStorage:
    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        client=None,
    ):
        self.bucket = bucket
        if client is None:
            import boto3

            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                region_name=region,
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
            )
        self.client = client

    def put(self, source: Path, key: str) -> str:
        safe_key = _safe_key(key)
        self.client.upload_file(str(source), self.bucket, safe_key)
        return f"s3://{self.bucket}/{safe_key}"

    @contextmanager
    def materialize(self, reference: str) -> Iterator[Path]:
        prefix = f"s3://{self.bucket}/"
        if not reference.startswith(prefix):
            raise ValueError("STORAGE_REFERENCE_INVALID")
        key = _safe_key(reference.removeprefix(prefix))
        with tempfile.TemporaryDirectory(prefix="huce-object-") as directory:
            path = Path(directory) / Path(key).name
            try:
                self.client.download_file(self.bucket, key, str(path))
            except Exception as error:
                response = getattr(error, "response", {})
                code = str(response.get("Error", {}).get("Code", ""))
                if code in {"404", "NoSuchKey", "NotFound"}:
                    raise FileNotFoundError(reference) from error
                raise
            yield path


def get_storage_backend(config: Settings = settings) -> StorageBackend:
    if config.storage_backend == "local":
        return LocalStorage(config.resolve(config.upload_dir) / "objects")
    return S3CompatibleStorage(
        bucket=config.s3_bucket or "",
        region=config.s3_region or "",
        endpoint_url=config.s3_endpoint_url,
        access_key_id=config.s3_access_key_id,
        secret_access_key=config.s3_secret_access_key,
    )
