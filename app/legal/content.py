from __future__ import annotations

import hashlib
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _read_text(name: str) -> str:
    path = BASE_DIR / name
    return path.read_text(encoding="utf-8").strip()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


TERMS_TEXT = _read_text("terms.txt")
PRIVACY_TEXT = _read_text("privacy.txt")

TERMS_HASH = _hash_text(TERMS_TEXT)
PRIVACY_HASH = _hash_text(PRIVACY_TEXT)
