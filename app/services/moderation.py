# app/services/moderation.py

from __future__ import annotations

import io
from functools import lru_cache
from typing import Iterable, Tuple

from PIL import Image


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


def moderate_image_bytes(payload: bytes) -> tuple[bool, str | None]:
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


def moderate_text(text: str | None) -> tuple[bool, str | None]:
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
