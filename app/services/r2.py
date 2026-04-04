import uuid
import os
from typing import IO

import boto3
from botocore.config import Config

from app.core.config import settings


LOCAL_UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "uploads")


def _require_setting(value: str | None, name: str) -> str:
    if not value:
        raise RuntimeError(f"Missing {name}")
    return value


def get_r2_client():
    account_id = _require_setting(settings.R2_ACCOUNT_ID, "R2_ACCOUNT_ID")
    access_key = _require_setting(settings.R2_ACCESS_KEY_ID, "R2_ACCESS_KEY_ID")
    secret_key = _require_setting(settings.R2_SECRET_ACCESS_KEY, "R2_SECRET_ACCESS_KEY")

    endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def upload_bytes(fileobj: IO[bytes], key: str, content_type: str) -> str:
    try:
        bucket = _require_setting(settings.R2_BUCKET, "R2_BUCKET")
        public_base = _require_setting(settings.R2_PUBLIC_BASE_URL, "R2_PUBLIC_BASE_URL").rstrip("/")
        client = get_r2_client()
        fileobj.seek(0)
        client.upload_fileobj(
            fileobj,
            bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        return f"{public_base}/{key}"
    except Exception:
        fileobj.seek(0)
        return _store_local_upload(fileobj, key)


def _store_local_upload(fileobj: IO[bytes], key: str) -> str:
    relative_path = key.lstrip("/").replace("\\", "/")
    destination = os.path.join(LOCAL_UPLOADS_DIR, *relative_path.split("/"))
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(destination, "wb") as handle:
        handle.write(fileobj.read())
    base = settings.BACKEND_BASE_URL.rstrip("/")
    return f"{base}/uploads/{relative_path}"


def build_key(prefix: str, filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    return f"{prefix}/{uuid.uuid4().hex}{ext}"
