# app/services/moderation.py

from __future__ import annotations

import io
import os
import re
from functools import lru_cache
from typing import Iterable, Tuple

from PIL import Image
import numpy as np

from app.core.config import settings


UNSAFE_LABELS: Tuple[str, ...] = (
    "nudity",
    "pornography",
    "sexual content",
    "graphic nudity",
    "violence",
    "graphic violence",
    "gore",
    "blood",
    "weapon",
    "gun",
    "knife",
    "explosion",
    "hate symbol",
    "racist symbol",
    "extremist symbol",
)
SAFE_LABEL = "safe, family-friendly photo"
UNSAFE_THRESHOLD = 0.28
TEXT_UNSAFE_THRESHOLD = 0.55
TEXT_UNSAFE_LABELS: Tuple[str, ...] = (
    "toxicity",
    "severe_toxicity",
    "obscene",
    "threat",
    "insult",
    "identity_attack",
    "sexual_explicit",
)
TEXT_MAX_LENGTH = 2000
LITE_SKIN_THRESHOLD = 0.38
AVATAR_SKIN_THRESHOLD = 0.62
LITE_MAX_IMAGE_SIZE = 8 * 1024 * 1024
LITE_WORD_BLOCKLIST: Tuple[str, ...] = (
    "gun",
    "guns",
    "weapon",
    "weapons",
    "knife",
    "bomb",
    "explosive",
    "murder",
    "kill",
    "killing",
    "rape",
    "porn",
    "pornography",
    "nude",
    "nudity",
    "sex",
    "sexual",
    "nazi",
    "kkk",
    "racist",
)
LITE_PHRASE_BLOCKLIST: Tuple[str, ...] = (
    "hate speech",
    "white power",
    "kill yourself",
)
LITE_REGEX_BLOCKLIST: Tuple[re.Pattern, ...] = (
    re.compile(r"\b(?:g\s*u\s*n|g[u\W_]*n)\b"),
    re.compile(r"\b(?:k\s*i\s*l\s*l|k[i\W_]*l+l)\b"),
    re.compile(r"\b(?:r\s*a\s*p\s*e|r[a\W_]*p[e\W_]*)\b"),
)

MODERATION_MODE = (settings.MODERATION_MODE or os.getenv("MODERATION_MODE", "lite")).lower()


@lru_cache(maxsize=1)
def _load_clip():
    from transformers import CLIPModel, CLIPProcessor  # heavy import, keep lazy

    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
    processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    model.eval()
    return model, processor


@lru_cache(maxsize=1)
def _load_text_classifier():
    from transformers import pipeline  # heavy import, keep lazy

    return pipeline(
        "text-classification",
        model="unitary/unbiased-toxic-roberta",
        top_k=None,
        truncation=True,
    )


def _score_image(image: Image.Image, labels: Iterable[str]) -> list[float]:
    import torch

    model, processor = _load_clip()
    inputs = processor(text=list(labels), images=image, return_tensors="pt", padding=True)
    with torch.no_grad():
        logits = model(**inputs).logits_per_image
    probs = logits.softmax(dim=1).cpu().numpy()[0]
    return probs.tolist()


def _moderate_image_lite(payload: bytes, skin_threshold: float = LITE_SKIN_THRESHOLD) -> tuple[bool, str | None]:
    if len(payload) > LITE_MAX_IMAGE_SIZE:
        return False, "Image rejected: file is too large."
    try:
        image = Image.open(io.BytesIO(payload)).convert("RGB")
    except Exception:
        return False, "Invalid or unsupported image."
    image.thumbnail((256, 256))
    arr = np.asarray(image).astype(np.float32)
    r = arr[:, :, 0]
    g = arr[:, :, 1]
    b = arr[:, :, 2]
    cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
    cb = 128 - 0.168736 * r - 0.331364 * g + 0.5 * b
    skin_mask = (
        (r > 60)
        & (g > 40)
        & (b > 20)
        & (r > g)
        & (r > b)
        & (cr > 135)
        & (cr < 180)
        & (cb > 85)
        & (cb < 135)
    )
    skin_ratio = float(skin_mask.mean()) if skin_mask.size else 0.0
    if skin_ratio >= skin_threshold:
        return False, "Image rejected for unsafe content."
    return True, None


def _moderate_image_full(payload: bytes) -> tuple[bool, str | None]:
    try:
        image = Image.open(io.BytesIO(payload)).convert("RGB")
    except Exception:
        return False, "Invalid or unsupported image."

    labels = (SAFE_LABEL,) + UNSAFE_LABELS
    probs = _score_image(image, labels)
    safe_prob = probs[0]
    unsafe_probs = probs[1:]
    worst_prob = max(unsafe_probs)
    worst_label = UNSAFE_LABELS[unsafe_probs.index(worst_prob)]

    if worst_prob >= UNSAFE_THRESHOLD and worst_prob > safe_prob:
        return False, f"Image rejected for unsafe content: {worst_label}."

    return True, None


def moderate_image_bytes(payload: bytes) -> tuple[bool, str | None]:
    if MODERATION_MODE == "off":
        return True, None
    if MODERATION_MODE == "lite":
        return _moderate_image_lite(payload)
    return _moderate_image_full(payload)


def moderate_avatar_image_bytes(payload: bytes) -> tuple[bool, str | None]:
    if MODERATION_MODE == "off":
        return True, None
    if MODERATION_MODE == "lite":
        return _moderate_image_lite(payload, skin_threshold=AVATAR_SKIN_THRESHOLD)
    return _moderate_image_full(payload)


def _normalize_text(text: str) -> str:
    lowered = text.lower()
    lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _moderate_text_lite(text: str | None) -> tuple[bool, str | None]:
    if text is None:
        return True, None
    cleaned = text.strip()
    if not cleaned:
        return True, None
    normalized = _normalize_text(cleaned)[:TEXT_MAX_LENGTH]
    if not normalized:
        return True, None

    for phrase in LITE_PHRASE_BLOCKLIST:
        if phrase in normalized:
            return False, "Text rejected for unsafe content."

    tokens = set(normalized.split())
    for token in tokens:
        if token in LITE_WORD_BLOCKLIST:
            return False, "Text rejected for unsafe content."

    for pattern in LITE_REGEX_BLOCKLIST:
        if pattern.search(normalized):
            return False, "Text rejected for unsafe content."

    return True, None


def _moderate_text_full(text: str | None) -> tuple[bool, str | None]:
    if text is None:
        return True, None
    cleaned = text.strip()
    if not cleaned:
        return True, None
    snippet = cleaned[:TEXT_MAX_LENGTH]

    classifier = _load_text_classifier()
    results = classifier(snippet)
    labels = results[0] if results else []

    worst_label = None
    worst_score = 0.0
    for item in labels:
        label = item.get("label")
        score = float(item.get("score", 0))
        if label in TEXT_UNSAFE_LABELS and score > worst_score:
            worst_label = label
            worst_score = score

    if worst_label and worst_score >= TEXT_UNSAFE_THRESHOLD:
        return False, f"Text rejected for unsafe content: {worst_label}."

    return True, None


def moderate_text(text: str | None) -> tuple[bool, str | None]:
    if MODERATION_MODE == "off":
        return True, None
    if MODERATION_MODE == "lite":
        return _moderate_text_lite(text)
    return _moderate_text_full(text)
