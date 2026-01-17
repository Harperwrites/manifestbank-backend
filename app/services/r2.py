import uuid
import os
from typing import IO

import boto3
from botocore.config import Config

from app.core.config import settings


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
    bucket = _require_setting(settings.R2_BUCKET, "R2_BUCKET")
    public_base = _require_setting(settings.R2_PUBLIC_BASE_URL, "R2_PUBLIC_BASE_URL").rstrip("/")
    client = get_r2_client()

    client.upload_fileobj(
        fileobj,
        bucket,
        key,
        ExtraArgs={"ContentType": content_type},
    )
    return f"{public_base}/{key}"


def build_key(prefix: str, filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    return f"{prefix}/{uuid.uuid4().hex}{ext}"
