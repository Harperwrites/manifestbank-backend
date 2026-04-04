from __future__ import annotations

import re


def normalize_eval_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def count_bulletish_lines(text: str) -> int:
    count = 0
    for line in (text or "").splitlines():
        stripped = line.strip()
        if re.match(r"^(-|\d+\.)\s+", stripped):
            count += 1
    return count


def assert_expected_phrases(text: str, expects_all: tuple[str, ...], expects_any: tuple[str, ...]) -> None:
    lowered = text.lower()
    for expected in expects_all:
        assert expected.lower() in lowered, f"Missing expected phrase: {expected}\nActual: {text}"
    if expects_any:
        assert any(expected.lower() in lowered for expected in expects_any), (
            f"Missing any of expected phrases {expects_any}\nActual: {text}"
        )


def assert_banned_patterns_absent(text: str, banned_patterns: tuple[str, ...]) -> None:
    lowered = text.lower()
    for pattern in banned_patterns:
        assert pattern.lower() not in lowered, f"Found banned pattern: {pattern}\nActual: {text}"


def assert_action_mode_only(text: str) -> None:
    assert_banned_patterns_absent(
        text,
        (
            "let your shoulders drop",
            "what would help you feel more steady",
            "do you want to continue that request, or switch tasks and cancel it?",
            "can become a strong anchor",
            "let’s keep this grounded around",
            "let's keep this grounded around",
        ),
    )


def assert_transfer_direction(text: str, source: str, destination: str) -> None:
    lowered = text.lower()
    source_lower = source.lower()
    destination_lower = destination.lower()
    assert source_lower in lowered and destination_lower in lowered, text
    assert lowered.index(source_lower) < lowered.index(destination_lower), text


def assert_repair_response(text: str) -> None:
    lowered = text.lower()
    assert (
        "you’re right, that part came out unclear" in lowered
        or "you're right, that part came out unclear" in lowered
        or "let me restate it more simply" in lowered
        or "you’re right. let me" in lowered
        or "you're right. let me" in lowered
        or "let me make it cleaner" in lowered
        or "let me make those land more cleanly" in lowered
        or "here’s a cleaner version" in lowered
        or "here's a cleaner version" in lowered
        or "here’s a stronger version" in lowered
        or "here's a stronger version" in lowered
    ), text
    assert "that last part didn't make much sense a shape" not in lowered, text
    assert "that didnt make much sense a shape" not in lowered, text


def assert_final_sentence_complete(text: str) -> None:
    normalized = normalize_eval_text(text)
    assert normalized[-1:] in {".", "?", "!"}, normalized
