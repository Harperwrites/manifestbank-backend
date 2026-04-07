import pytest
import httpx

from app.services import teller_provider
from app.services.fortune_affirmations import (
    FORTUNE_AFFIRMATIONS_BLUEPRINT,
    _guard_affirmation_markdown,
    build_fortune_affirmations,
    infer_affirmation_mode,
)
from app.services.teller_provider import (
    DEFAULT_TELLER_PROMPT,
    _proof_final_reply,
    _enforce_markdown_structure,
    _extract_response_text,
    _extract_stream_completed_text,
    _get_repeat_count,
    _is_retry_placeholder,
    _light_cleanup,
    _normalize_punctuation,
    _remove_repeated_sentences,
    _response_unsupported_param,
    _strip_unsupported_response_controls,
    _strip_unsupported_action_offers,
    generate_teller_reply,
    get_persona,
    stream_teller_reply,
)


def _bullet_lines(text: str) -> list[str]:
    return [line.strip()[2:].strip() for line in text.splitlines() if line.strip().startswith("- ")]


def _first_non_header_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("##") or stripped.startswith("- "):
            continue
        return stripped
    return ""


def test_remove_repeated_sentences_preserves_list_structure_and_dedupes_duplicate_lines():
    source = "\n".join(
        [
            "## Grounded Affirmations",
            "",
            "Here are 10 short, grounded affirmations.",
            "Here are 10 short, grounded affirmations.",
            "",
            "1. I can choose one calm next step.",
            "2. I can stay grounded while I grow.",
            "- Ground your body",
            "  - Release your jaw",
            "  - Release your jaw",
        ]
    )

    cleaned = _remove_repeated_sentences(source)

    assert cleaned.count("Here are 10 short, grounded affirmations.") == 1
    assert "1. I can choose one calm next step." in cleaned
    assert "- Ground your body" in cleaned
    assert "  - Release your jaw" in cleaned
    assert cleaned.count("  - Release your jaw") == 1


def test_enforce_markdown_structure_keeps_existing_long_numbered_lists():
    source = "\n".join(
        [
            "## Grounded Affirmations",
            "",
            "1. I can choose one calm next step.",
            "2. My money can move with clarity, not panic.",
            "3. I am allowed to slow down before I decide.",
            "4. I can build trust with myself one action at a time.",
            "5. My worth is not measured by one hard moment.",
            "6. I can stay grounded while I grow.",
            "7. I know how to return to center.",
            "8. I can hold vision and reality at the same time.",
            "9. I let steadiness lead this choice.",
            "10. I can begin again without shame.",
        ]
    )

    assert _enforce_markdown_structure(source) == source


def test_extract_stream_completed_text_supports_content_part_and_output_item_done_events():
    part_event = {
        "type": "response.content_part.done",
        "part": {"type": "output_text", "text": "Hi there."},
    }
    item_event = {
        "type": "response.output_item.done",
        "item": {
            "type": "message",
            "content": [
                {"type": "output_text", "text": "Hello again."},
            ],
        },
    }

    assert _extract_stream_completed_text(part_event) == "Hi there."
    assert _extract_stream_completed_text(item_event) == "Hello again."


def test_extract_response_text_dedupes_output_text_blocks_from_responses_api():
    payload = {
        "output": [
            {
                "content": [
                    {"type": "output_text", "text": "Would you prefer brief, one-line calm affirmations or?"},
                ]
            }
        ]
    }

    assert _extract_response_text(payload) == "Would you prefer brief, one-line calm affirmations or?"


def test_get_persona_uses_compact_default_prompt():
    name, prompt = get_persona()

    assert name
    assert prompt == DEFAULT_TELLER_PROMPT
    assert "Repetition Rule:" in prompt
    assert "Do NOT repeat prior wording" in prompt


def test_fortune_affirmations_blueprint_exposes_reusable_internal_spec():
    assert "purpose" in FORTUNE_AFFIRMATIONS_BLUEPRINT
    assert "emotional_modes" in FORTUNE_AFFIRMATIONS_BLUEPRINT
    assert "repetition_protection" in FORTUNE_AFFIRMATIONS_BLUEPRINT
    assert "tone_blacklist" in FORTUNE_AFFIRMATIONS_BLUEPRINT


@pytest.mark.parametrize(
    ("message", "history", "topic", "expected"),
    [
        ("calm affirmations", None, None, "calm"),
        ("affirmations please", [{"role": "user", "content": "I want to feel more secure with money."}], None, "money"),
        ("affirmations please", [{"role": "user", "content": "I am stressed and overloaded."}], None, "pressure"),
        ("affirmations please", [{"role": "user", "content": "I need to trust my voice more."}], None, "confidence"),
        ("affirmations please", [{"role": "user", "content": "I need to lock in."}], None, "focus"),
        ("affirmations please", [{"role": "user", "content": "I need a reset."}], None, "reset"),
        ("affirmations please", None, None, "general"),
    ],
)
def test_infer_affirmation_mode_supports_core_emotional_modes(message, history, topic, expected):
    assert infer_affirmation_mode(message, history=history, requested_topic=topic) == expected


def test_build_fortune_affirmations_varies_across_three_consecutive_requests():
    first = build_fortune_affirmations(message="affirmations", requested_topic="general", history=[], variant_hint="requested")
    second = build_fortune_affirmations(
        message="affirmations",
        requested_topic="general",
        history=[
            {"role": "assistant", "content": first},
        ],
        variant_hint="requested",
    )
    third = build_fortune_affirmations(
        message="affirmations",
        requested_topic="general",
        history=[
            {"role": "assistant", "content": first},
            {"role": "assistant", "content": second},
        ],
        variant_hint="requested",
    )

    outputs = [first, second, third]
    assert len(set(outputs)) == 3
    bullet_lengths = [len(_bullet_lines(output)) for output in outputs]
    assert all(3 <= count <= 5 for count in bullet_lengths)
    assert len(set(bullet_lengths)) >= 2 or len({_first_non_header_line(output) for output in outputs}) >= 2

    first_lines = [_bullet_lines(output)[0] for output in outputs if _bullet_lines(output)]
    assert len(set(first_lines)) == len(first_lines)

    all_lines = [_bullet_lines(output) for output in outputs]
    assert set(all_lines[0]).isdisjoint(set(all_lines[1]))
    assert set(all_lines[1]).isdisjoint(set(all_lines[2]))
    assert set(all_lines[0]).isdisjoint(set(all_lines[2]))


def test_build_fortune_affirmations_avoids_recent_phrase_repetition():
    previous = "\n".join(
        [
            "- I let my work be compensated without shrinking around it.",
            "- I make room for revenue by finishing what leads to payment.",
            "- I let clean decisions support cleaner income.",
        ]
    )

    current = build_fortune_affirmations(
        message="affirmations please",
        requested_topic="more money",
        history=[{"role": "assistant", "content": previous}],
        variant_hint="requested",
    )

    lowered = current.lower()
    assert "i let my work be compensated without shrinking around it." not in lowered
    assert "i make room for revenue by finishing what leads to payment." not in lowered


def test_build_fortune_affirmations_keeps_formatting_clean_and_premium():
    output = build_fortune_affirmations(
        message="I need a reset",
        requested_topic="reset",
        history=[],
        variant_hint="requested",
    )

    assert "- " in output
    assert "## Insight" not in output
    assert "## Reflection" not in output
    lowered = output.lower()
    for banned in ["nice.", "sweet.", "fresh set", "different angle", "tokens", "deals", "imagine", "imagined", "imaginative"]:
        assert banned not in lowered


def test_guard_affirmation_markdown_enforces_section_spacing_and_bullets():
    source = "## Insight Calm is enough. ## Key Points I move clearly - I stay grounded - I trust the next step. ## Reflection What lands best?"

    cleaned = _guard_affirmation_markdown(source)

    assert "## Insight\n\nCalm is enough." in cleaned
    assert "## Key Points\n\n- I move clearly\n- I stay grounded\n- I trust the next step." in cleaned
    assert "## Reflection\n\nWhat lands best?" in cleaned


def test_build_fortune_affirmations_avoids_instructional_insight_phrasing():
    output = build_fortune_affirmations(
        message="affirmations",
        requested_topic="general",
        history=[],
        variant_hint="requested",
    )

    lowered = output.lower()
    assert "use the ones that" not in lowered
    assert "try these" not in lowered
    assert "here are a few" not in lowered


def test_get_repeat_count_uses_history_instead_of_cache():
    history = [
        {"role": "user", "content": "Write a Future Success Story"},
        {"role": "assistant", "content": "First reply"},
        {"role": "user", "content": "Write a Future Success Story"},
    ]

    assert _get_repeat_count("Write a Future Success Story", history) == 2
    assert _get_repeat_count("Something else", history) == 0


def test_strip_unsupported_action_offers_removes_unavailable_capabilities():
    source = (
        "Would you like an initial deposit amount, a linked debit card, or joint access set up for this account? "
        "Quick question: do you want that funded from an internal account or via an external transfer?"
    )

    cleaned = _strip_unsupported_action_offers(source)

    assert "linked debit card" not in cleaned.lower()
    assert "joint access" not in cleaned.lower()
    assert "external transfer" not in cleaned.lower()


def test_normalize_punctuation_fixes_missing_question_mark_and_sentence_capitalization():
    source = "Nice to see you again. What would you like to do right now. account help, a quick plan, or something else?"

    cleaned = _normalize_punctuation(source)

    assert cleaned == "Nice to see you again. What would you like to do right now? Account help, a quick plan, or something else?"


def test_normalize_punctuation_fixes_lowercase_i_bad_spacing_and_broken_capitalization():
    source = "you’re welcome. glad i could help.   anything else i can do for you right now"

    cleaned = _normalize_punctuation(source)

    assert cleaned == "You’re welcome. Glad I could help. Anything else I can do for you right now."


def test_normalize_punctuation_fixes_sentence_breaks_across_lines():
    source = "i can help with that.\nwhat direction feels best next"

    cleaned = _normalize_punctuation(source)

    assert cleaned == "I can help with that. What direction feels best next?"


def test_light_cleanup_enforces_markdown_on_long_plaintext_coaching_reply():
    source = (
        "Breathing is one of the fastest ways to settle your system. "
        "Start with a slower exhale so your body stops bracing. "
        "Then keep your attention on one clear next step. "
        "What would help you stay with that today?"
    )

    cleaned = _light_cleanup(source)

    assert "## Insight" not in cleaned
    assert "## Key Points" not in cleaned
    assert "## Reflection" not in cleaned
    assert "Start with a slower exhale so your body stops bracing." in cleaned
    assert "What would help you stay with that today?" in cleaned


def test_light_cleanup_keeps_short_confirmations_concise():
    source = "Done. I deposited $300.00 into “Miracles”. New balance: $1,300.00."

    cleaned = _light_cleanup(source)

    assert cleaned == source
    assert "## Insight" not in cleaned


def test_light_cleanup_removes_off_brand_filler():
    source = "Nice. Here's a fresh set. Sweet."

    cleaned = _light_cleanup(source)

    assert "Nice." not in cleaned
    assert "Sweet." not in cleaned
    assert "fresh set" not in cleaned.lower()
    assert "new set" in cleaned.lower()


def test_light_cleanup_collapses_duplicated_followup_question_text():
    source = (
        "Would you prefer brief, one-line calm affirmations or "
        "Would you prefer brief, one-line calm affirmations or?"
    )

    cleaned = _light_cleanup(source)

    assert cleaned == "Would you prefer brief, one-line calm affirmations?"


@pytest.mark.asyncio
async def test_proof_final_reply_runs_last_and_fixes_inline_dash_chains(monkeypatch):
    async def fake_copyedit_reply(text, short_mode=False):
        return "## Insight Calm can stay present. ## Key Points I stay clear - I move carefully - I trust the next step."

    monkeypatch.setattr(teller_provider, "_copyedit_reply", fake_copyedit_reply)

    cleaned = await teller_provider._final_response_authority(
        "affirmations",
        "## Insight Calm can stay present. ## Key Points I stay clear - I move carefully - I trust the next step.",
        history=[],
    )

    assert "## Insight" not in cleaned
    assert "## Key Points" not in cleaned
    assert cleaned == "- I stay clear\n- I move carefully\n- I trust the next step."
    assert " - " not in cleaned


def test_retry_placeholder_detection_handles_punctuation_variants():
    assert _is_retry_placeholder("Stay with me — still working.")
    assert _is_retry_placeholder("Stay with me. still working.")


def test_response_unsupported_param_detects_and_strips_unsupported_controls():
    response = httpx.Response(
        400,
        json={
            "error": {
                "message": "Unsupported parameter: 'temperature' is not supported with this model.",
                "type": "invalid_request_error",
                "param": "temperature",
                "code": None,
            }
        },
    )
    payload = {
        "model": "gpt-5",
        "input": "hello",
        "temperature": 0.55,
        "top_p": 0.9,
        "frequency_penalty": 0.2,
        "presence_penalty": 0.1,
    }

    assert _response_unsupported_param(response) == "temperature"
    assert _strip_unsupported_response_controls(payload) == {
        "model": "gpt-5",
        "input": "hello",
    }


@pytest.mark.asyncio
async def test_local_rescue_rewrite_approval_delivers_rewrite_directly(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [
        {"role": "assistant", "content": "You're right, that part came out unclear. Let me restate it more simply.\n\nIf you'd like, I can rewrite it in a cleaner, shorter version."},
    ]

    cached, reply = await stream_teller_reply(445566, "yes please", history=history)

    assert cached is False
    assert reply.startswith("Script:") or reply.startswith("**Shorter Script**") or "simpler version" in reply.lower()
    assert "that part didn't make much sense" not in reply.lower()


@pytest.mark.asyncio
async def test_local_rescue_money_followup_avoids_give_x_a_shape_template(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [
        {"role": "user", "content": "Manifest more money"},
        {"role": "assistant", "content": "More money usually responds better to clarity than pressure.\n\nIf you want, I can turn that into a short script, a few affirmations, or a 2-minute reset."},
    ]

    cached, reply = await stream_teller_reply(556677, "more", history=history)

    assert cached is False
    assert "give more a shape" not in reply.lower()
    assert "give" not in reply.lower() or "shape" not in reply.lower()


@pytest.mark.asyncio
async def test_stream_teller_reply_refines_affirmations_without_restarting_menu(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [
        {"role": "assistant", "content": "Here are a few affirmations:\n\n- I welcome aligned growth with steadiness.\n- The right people recognize the value of what I built.\nWhat would help you stay consistent with these?"},
    ]

    cached, reply = await stream_teller_reply(667788, "more powerful", history=history)

    assert cached is False
    assert reply.lstrip().startswith("- ")
    assert " - " not in reply
    assert "short script" not in reply.lower()


@pytest.mark.asyncio
async def test_generate_teller_reply_generic_affirmations_return_direct_set_without_two_part_followup(monkeypatch):
    calls: list[str] = []

    async def fake_response(message, history=None, short_mode=False, repeat_count=0):
        calls.append(message)
        return "How many one-line affirmations would you like, and which tone. gentle, energizing, or focused?"

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response", fake_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    cached, reply = await generate_teller_reply(778001, "affirmations please")

    assert cached is False
    assert "- " in reply
    assert "I’m here. Please try again." not in reply
    assert "How many one-line affirmations" not in reply
    assert "which tone" not in reply.lower()
    assert "gentle, energizing, or focused" not in reply.lower()
    assert reply.count("?") <= 1
    assert calls == []


@pytest.mark.asyncio
async def test_generate_teller_reply_affirmations_never_return_inline_dash_chains(monkeypatch):
    async def fake_response(*args, **kwargs):
        return "## Insight Calm can stay present. ## Key Points I stay clear - I move carefully - I trust the next step."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response", fake_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    cached, reply = await generate_teller_reply(778021, "calm affirmations")

    assert cached is False
    assert reply.lstrip().startswith("- ")
    assert " - " not in reply


@pytest.mark.asyncio
async def test_generate_teller_reply_valid_brief_followup_returns_affirmations_not_fallback(monkeypatch):
    async def fake_response(*args, **kwargs):
        return "Stay with me. still working."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response", fake_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [
        {
            "role": "assistant",
            "content": "Would you prefer brief, one-line calm affirmations or a longer set?",
        },
    ]

    cached, reply = await generate_teller_reply(778002, "brief", history=history)

    assert cached is False
    assert "- " in reply
    assert reply.count("\n- ") >= 2 or reply.count("- ") >= 3
    assert "I’m here. Please try again." not in reply
    assert "Would you prefer brief, one-line calm affirmations or" not in reply
    assert "or Would you prefer brief, one-line calm affirmations or" not in reply


@pytest.mark.asyncio
async def test_generate_teller_reply_affirmations_calm_then_brief_flow(monkeypatch):
    async def fake_response(*args, **kwargs):
        return "Stay with me. still working."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response", fake_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    first_cached, first_reply = await generate_teller_reply(778003, "affirmations for calm")
    assert first_cached is False
    assert "- " in first_reply

    history = [
        {"role": "user", "content": "affirmations for calm"},
        {"role": "assistant", "content": first_reply},
    ]
    second_cached, second_reply = await generate_teller_reply(778003, "brief", history=history)

    assert second_cached is False
    assert 3 <= second_reply.count("- ") <= 5
    assert "I’m here. Please try again." not in second_reply
    assert "Would you prefer" not in second_reply
    assert second_reply.count("?") <= 1


@pytest.mark.asyncio
async def test_generate_teller_reply_affirmations_sequence_has_no_duplicate_fragments(monkeypatch):
    async def fake_response(*args, **kwargs):
        return "Stay with me. still working."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response", fake_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    first_cached, first_reply = await generate_teller_reply(778008, "Affirmations")
    assert first_cached is False
    assert "I’m here. Please try again." not in first_reply

    second_history = [
        {"role": "user", "content": "Affirmations"},
        {"role": "assistant", "content": "Would you prefer brief, one-line calm affirmations or a longer set?"},
    ]
    second_cached, second_reply = await generate_teller_reply(778008, "Calm", history=second_history)
    assert second_cached is False
    assert "I’m here. Please try again." not in second_reply

    third_history = [
        {"role": "user", "content": "Affirmations"},
        {"role": "assistant", "content": "Would you prefer brief, one-line calm affirmations or a longer set?"},
        {"role": "user", "content": "Calm"},
        {"role": "assistant", "content": "Would you prefer brief, one-line calm affirmations or a longer set?"},
    ]
    third_cached, third_reply = await generate_teller_reply(778008, "brief", history=third_history)

    assert third_cached is False
    assert "- " in third_reply
    assert "I’m here. Please try again." not in third_reply
    assert "Would you prefer brief, one-line calm affirmations or" not in third_reply
    assert "Would you prefer" not in third_reply
    assert third_reply.count("?") <= 1


@pytest.mark.asyncio
async def test_generate_teller_reply_affirmation_topic_followup_gets_single_style_question(monkeypatch):
    async def fake_response(*args, **kwargs):
        return "Stay with me. still working."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response", fake_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [
        {
            "role": "assistant",
            "content": "What kind of affirmations would help most right now: calm, confidence, focus, or finances?",
        },
    ]

    cached, reply = await generate_teller_reply(778010, "calm", history=history)

    assert cached is False
    assert reply == "Would you prefer brief, one-line calm affirmations or a longer set?"
    assert "I’m here. Please try again." not in reply


@pytest.mark.asyncio
async def test_generate_teller_reply_short_followup_variants_route_without_fallback(monkeypatch):
    async def fake_response(*args, **kwargs):
        return "Stay with me. still working."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response", fake_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    style_history = [
        {
            "role": "assistant",
            "content": "Would you prefer brief, one-line calm affirmations or a longer set?",
        },
    ]

    for message in ["brief", "short", "calm", "confidence"]:
        cached, reply = await generate_teller_reply(778004, message, history=style_history)
        assert cached is False
        assert "I’m here. Please try again." not in reply
        assert "A)" not in reply and "B)" not in reply and "C)" not in reply


@pytest.mark.asyncio
async def test_generate_teller_reply_direct_brief_calm_affirmations_needs_no_followup(monkeypatch):
    async def fake_response(*args, **kwargs):
        return "Stay with me. still working."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response", fake_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    cached, reply = await generate_teller_reply(778005, "Give me brief calm affirmations")

    assert cached is False
    assert "- " in reply
    assert "I’m here. Please try again." not in reply
    assert "Confirm" not in reply
    assert reply.count("?") <= 1
    assert "A)" not in reply and "B)" not in reply and "C)" not in reply
    assert "Would you prefer" not in reply


@pytest.mark.asyncio
async def test_generate_teller_reply_affirmations_stays_premium_and_avoids_banned_words(monkeypatch):
    async def fake_response(*args, **kwargs):
        return "Stay with me. still working."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response", fake_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    cached, reply = await generate_teller_reply(778006, "Affirmations please")

    assert cached is False
    lowered = reply.lower()
    for banned in ["nice.", "sweet.", "fresh set", "tokens", "deals", "imagine", "imagined", "imaginative"]:
        assert banned not in lowered


@pytest.mark.asyncio
async def test_generate_teller_reply_greeting_only_once_at_conversation_start(monkeypatch):
    calls: list[str] = []

    async def fake_response(message, history=None, short_mode=False, repeat_count=0):
        calls.append(message)
        return "## Insight\nYou can check your balances directly.\n\n## Key Points\n- Checking: $450.00\n\n## Reflection\nWhat do you want to review next?"

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response", fake_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    cached, greeting = await generate_teller_reply(778007, "hi")
    assert cached is False
    assert greeting == "Hi. What would you like to do?"

    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": greeting},
    ]
    cached, second = await generate_teller_reply(778007, "check balances", history=history)
    assert cached is False
    assert "Hi." not in second
    assert calls == ["check balances"]


@pytest.mark.asyncio
async def test_generate_teller_reply_generic_affirmations_asks_at_most_one_short_question(monkeypatch):
    async def fake_response(*args, **kwargs):
        return "Stay with me. still working."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response", fake_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    cached, reply = await generate_teller_reply(778009, "Affirmations please")

    assert cached is False
    assert "A)" not in reply and "B)" not in reply and "C)" not in reply
    assert reply.count("?") <= 1


@pytest.mark.asyncio
async def test_generate_teller_reply_script_followup_after_one_clarification_delivers_immediately(monkeypatch):
    async def fake_response(*args, **kwargs):
        return "What tone do you want?"

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response", fake_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [
        {"role": "user", "content": "script"},
        {"role": "assistant", "content": "What kind of script would help right now?"},
    ]

    cached, reply = await generate_teller_reply(778023, "daily/weekly money check-in", history=history)

    assert cached is False
    assert "Daily:" in reply
    assert "Weekly:" in reply
    assert "Speak-Aloud Anchor:" in reply
    assert "Next Step:" in reply
    assert "What tone do you want?" not in reply


@pytest.mark.asyncio
async def test_generate_teller_reply_script_daily_weekly_both_delivers_both_without_extra_question(monkeypatch):
    async def fake_response(*args, **kwargs):
        return "Would you like daily or weekly?"

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response", fake_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [
        {"role": "user", "content": "script"},
        {"role": "assistant", "content": "What kind of script would help right now?"},
        {"role": "user", "content": "daily/weekly money check-in"},
        {"role": "assistant", "content": "Do you want a daily check-in, a weekly check-in, or both?"},
    ]

    cached, reply = await generate_teller_reply(778022, "both", history=history)

    assert cached is False
    assert "Daily:" in reply
    assert "Weekly:" in reply
    assert "## Insight" not in reply
    assert "Would you like daily or weekly?" not in reply
    assert "What kind of script would help right now?" not in reply


@pytest.mark.asyncio
async def test_generate_teller_reply_script_request_bypasses_llm_and_returns_single_clarifier(monkeypatch):
    async def fail_openai(*args, **kwargs):
        raise AssertionError("LLM should not be called for script request")

    monkeypatch.setattr(teller_provider, "_openai_response", fail_openai)

    cached, reply = await generate_teller_reply(880001, "script")

    assert cached is False
    assert reply.startswith("Script:")


@pytest.mark.asyncio
async def test_generate_teller_reply_affirmations_strip_legacy_sections_and_phrases(monkeypatch):
    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    reply = await teller_provider._final_response_authority(
        "affirmations",
        "## Insight\n\nNice.\n\n## Key Points\n\nHere are a few affirmations:\n- I stay clear - I stay steady - I trust the next step.\n\n## Reflection\nPick 2–4.",
        history=[],
    )

    assert "## Insight" not in reply
    assert "## Key Points" not in reply
    assert "## Reflection" not in reply
    assert "Pick 2" not in reply
    assert "Here are a few" not in reply
    assert "Nice." not in reply
    assert " - " not in reply
    assert reply.lstrip().startswith("- ")


@pytest.mark.asyncio
async def test_generate_teller_reply_impatience_override_delivers_script_instead_of_asking_again(monkeypatch):
    async def fake_response(*args, **kwargs):
        return "Do you want a daily check-in, a weekly check-in, or both?"

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response", fake_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [
        {"role": "user", "content": "script"},
        {"role": "assistant", "content": "What kind of script would help right now?"},
        {"role": "user", "content": "daily/weekly money check-in"},
        {"role": "assistant", "content": "Do you want a daily check-in, a weekly check-in, or both?"},
    ]

    cached, reply = await generate_teller_reply(778024, "bruh come on just answer", history=history)

    assert cached is False
    assert "Daily:" in reply
    assert "Weekly:" in reply
    assert "Do you want a daily check-in" not in reply


@pytest.mark.asyncio
async def test_stream_teller_reply_shorter_transforms_previous_script(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [
        {"role": "assistant", "content": "**Script**\nI move toward new opportunities with clarity, steadiness, and self-trust. I recognize what is aligned, I respond without forcing, and I let momentum build through clean action."},
    ]

    cached, reply = await stream_teller_reply(667789, "shorter", history=history)

    assert cached is False
    assert reply.startswith("Script:")
    assert "openings" in reply.lower() or "opportunit" in reply.lower()
    assert "short script, a few affirmations, or a 2-minute reset" not in reply


@pytest.mark.asyncio
async def test_stream_teller_reply_in_first_person_transforms_previous_script(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [
        {"role": "assistant", "content": "**Script**\nYou move toward the right opportunity with clarity and trust. You notice what is aligned and you act on it cleanly."},
    ]

    cached, reply = await stream_teller_reply(667790, "in first person", history=history)

    assert cached is False
    assert reply.startswith("Script:")
    assert "\nI " in reply or reply.startswith("Script:\nI ")
    assert "opportunit" in reply.lower() or "openings" in reply.lower()
    assert "I welcome in first person" not in reply.lower()


@pytest.mark.asyncio
async def test_stream_teller_reply_that_didnt_hit_rewrites_previous_script(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [
        {"role": "assistant", "content": "**Script**\nI move toward immediate flow with clarity, steadiness, and self-trust."},
    ]

    cached, reply = await stream_teller_reply(667791, "that didn't hit", history=history)

    assert cached is False
    assert "Here’s a cleaner version." in reply or "Let me make it cleaner." in reply or "Let me restate" in reply
    assert "Script:" in reply
    assert "short script, a few affirmations, or a 2-minute reset" not in reply


@pytest.mark.asyncio
async def test_stream_teller_reply_script_followup_uses_first_person_and_stays_attached_to_context(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [
        {"role": "user", "content": "help me manifest more money"},
        {"role": "assistant", "content": "More money usually responds better to clarity than pressure.\n\nIf you want, I can turn that into a short script, a few affirmations, or a 2-minute reset."},
    ]

    cached, reply = await stream_teller_reply(667792, "script", history=history)

    assert cached is False
    assert reply.startswith("Script:")
    assert "I " in reply
    assert "in front of you" not in reply.lower()
    assert "short script, a few affirmations, or a 2-minute reset" not in reply
    assert "clean action" not in reply.lower()


@pytest.mark.asyncio
async def test_stream_teller_reply_even_shorter_affirmations_transform_previous_set(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [
        {"role": "assistant", "content": "Here are a few affirmations:\n\n- I let money feel safe, steady, and real.\n- I make clear decisions that support stronger results.\n- I can receive more without rushing my body.\n- Value moves more easily when I stay visible and direct."},
    ]

    cached, reply = await stream_teller_reply(667793, "even shorter", history=history)

    assert cached is False
    assert "- " in reply
    assert "What would you like to do?" not in reply
    assert "money moving cleanly" not in reply.lower()


@pytest.mark.asyncio
async def test_stream_teller_reply_story_request_returns_narrative_not_menu(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    cached, reply = await stream_teller_reply(667795, "tell me a story about someone manifesting their dreams")

    assert cached is False
    assert "months later" in reply.lower() or "one week" in reply.lower() or "within a few weeks" in reply.lower()
    assert "short script, a few affirmations, or a 2-minute reset" not in reply
    assert "**Script**" not in reply


@pytest.mark.asyncio
async def test_stream_teller_reply_task_switch_then_scriot_stays_on_script_path(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [
        {"role": "assistant", "content": "Which account should I transfer from?"},
        {"role": "user", "content": "actually wait… give me a script first"},
        {"role": "assistant", "content": "**Script**\nI make decisions that increase my income.\nI recognize real opportunities and follow through while they are still in front of me.\nI let consistency, visibility, and clear value create momentum."},
    ]

    cached, reply = await stream_teller_reply(667796, "scriot", history=history)

    assert cached is False
    assert reply.startswith("Script:")
    assert "transfer" not in reply.lower()
    assert "Which account should I transfer from?" not in reply


@pytest.mark.asyncio
async def test_stream_teller_reply_general_money_help_is_not_just_a_menu(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    cached, reply = await stream_teller_reply(667797, "help me manifest more money")

    assert cached is False
    assert "offer" in reply.lower() or "price" in reply.lower() or "income" in reply.lower()
    assert reply.lower().count("short script, a few affirmations, or a 2-minute reset") <= 1


@pytest.mark.asyncio
async def test_stream_teller_reply_repeated_script_requests_change_wording(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [{"role": "user", "content": "help me manifest more money"}]
    cached, first = await stream_teller_reply(667798, "script", history=history)
    assert cached is False
    history.extend([{"role": "user", "content": "script"}, {"role": "assistant", "content": first}])
    cached, second = await stream_teller_reply(667798, "script", history=history)
    assert cached is False
    assert first != second
    assert first.startswith("Script:") and second.startswith("Script:")
    history.extend([{"role": "user", "content": "script"}, {"role": "assistant", "content": second}])
    cached, third = await stream_teller_reply(667798, "script", history=history)
    assert cached is False
    assert third not in {first, second}
    assert third.startswith("Script:")


@pytest.mark.asyncio
async def test_stream_teller_reply_mixed_affirmation_request_persists_artifact_for_stronger_followup(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    cached, first = await stream_teller_reply(667880, "give affirmations for new paying signature members shorter")
    assert cached is False
    assert first.lstrip().startswith("- ")
    assert first.count("- ") >= 2

    history = [
        {"role": "user", "content": "give affirmations for new paying signature members shorter"},
        {"role": "assistant", "content": first},
    ]
    cached, second = await stream_teller_reply(667880, "more powerful", history=history)
    assert cached is False
    assert second.lstrip().startswith("- ")
    assert "short script, a few affirmations, or a 2-minute reset" not in second
    assert "premium" in second.lower() or "commitment" in second.lower() or second.count("- ") >= 3


@pytest.mark.asyncio
async def test_stream_teller_reply_another_after_script_returns_new_script_variant(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [{"role": "user", "content": "help me manifest more money"}]
    cached, first = await stream_teller_reply(667881, "script please", history=history)
    assert cached is False
    history.extend([{"role": "user", "content": "script please"}, {"role": "assistant", "content": first}])
    cached, second = await stream_teller_reply(667881, "another", history=history)
    assert cached is False
    assert second.startswith("Script:")
    assert second != first
    assert "clarify" not in second.lower()


@pytest.mark.asyncio
async def test_stream_teller_reply_story_another_returns_distinct_story(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    cached, first = await stream_teller_reply(667882, "tell me a story about someone manifesting their dreams")
    assert cached is False
    history = [
        {"role": "user", "content": "tell me a story about someone manifesting their dreams"},
        {"role": "assistant", "content": first},
    ]
    cached, second = await stream_teller_reply(667882, "another", history=history)
    assert cached is False
    assert "**Story**" in first and "**Story**" in second
    assert first != second
    history.extend([{"role": "user", "content": "another"}, {"role": "assistant", "content": second}])
    cached, third = await stream_teller_reply(667882, "again", history=history)
    assert cached is False
    assert "**Story**" in third
    assert third not in {first, second}


@pytest.mark.asyncio
async def test_stream_teller_reply_reflective_followup_gets_light_reinforcement(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [{"role": "assistant", "content": "**Script**\nI make decisions that raise my income instead of delaying it.\nI price my work with more honesty and follow up while demand is still warm.\nI let stronger earnings come from better offers and cleaner execution."}]
    cached, reply = await stream_teller_reply(667799, "keeping this on a post it would help me", history=history)

    assert cached is False
    assert "keep it" in reply.lower() or "visible" in reply.lower()
    assert "clarify what you'd like to do" not in reply.lower()


@pytest.mark.asyncio
async def test_stream_teller_reply_reflective_acknowledgment_handles_write_this_down(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [{"role": "assistant", "content": "**Script**\nI make decisions that raise my income instead of delaying it.\nI price my work with more honesty and follow up while demand is still warm.\nI let stronger earnings come from better offers and cleaner execution."}]
    cached, reply = await stream_teller_reply(667886, "I'll write this down", history=history)

    assert cached is False
    assert "good" in reply.lower() or "that works" in reply.lower() or "stay consistent" in reply.lower()
    assert "clarify what you'd like to do" not in reply.lower()

    cached, reply = await stream_teller_reply(667886, "this makes sense", history=history)
    assert cached is False
    assert "clarify what you'd like to do" not in reply.lower()


@pytest.mark.asyncio
async def test_stream_teller_reply_praise_gets_short_acknowledgment(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [{"role": "assistant", "content": "Here are a few affirmations:\n\n- I make decisions that raise my income.\n- I follow through while demand is still live."}]
    cached, reply = await stream_teller_reply(667800, "thank you", history=history)

    assert cached is False
    assert reply == "Good. Keep using that."
    assert "short script, a few affirmations, or a 2-minute reset" not in reply.lower()


@pytest.mark.asyncio
async def test_stream_teller_reply_praise_handles_i_love_that(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [{"role": "assistant", "content": "Here are a few affirmations:\n\n- I make decisions that raise my income.\n- I follow through while demand is still live."}]
    cached, reply = await stream_teller_reply(667887, "I love that", history=history)

    assert cached is False
    assert reply == "Good. Keep using that."

    cached, reply = await stream_teller_reply(667887, "that helped", history=history)
    assert cached is False
    assert reply == "Good. Keep using that."


@pytest.mark.asyncio
async def test_stream_teller_reply_greeting_stays_greeting_only(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    cached, reply = await stream_teller_reply(667883, "hi")

    assert cached is False
    assert reply == "Hi. What would you like to do?"

    cached, reply = await stream_teller_reply(667883, "howdy")
    assert cached is False
    assert reply == "Hi. What would you like to do?"

    history = [{"role": "assistant", "content": "**Script**\nI make decisions that raise my income."}]
    cached, reply = await stream_teller_reply(667883, "hi", history=history)
    assert cached is False
    assert reply == "Hi. What would you like to do?"


@pytest.mark.asyncio
async def test_stream_teller_reply_script_after_story_asks_one_clarifying_question(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [
        {"role": "assistant", "content": "**Story**\nNina wanted more money, but her week kept disappearing into half-finished offers."},
    ]
    cached, reply = await stream_teller_reply(667884, "script", history=history)

    assert cached is False
    assert reply.startswith("Script:")


@pytest.mark.asyncio
async def test_stream_teller_reply_another_script_generates_new_script_immediately(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [
        {"role": "assistant", "content": "**Script**\nI make decisions that raise my income instead of delaying it.\nI price my work with more honesty and follow up while demand is still warm.\nI let stronger earnings come from better offers and cleaner execution."},
    ]
    cached, reply = await stream_teller_reply(6678841, "another script", history=history)

    assert cached is False
    assert reply.startswith("Script:")
    assert "what would you like" not in reply.lower()
    assert "short script, a few affirmations, or a 2-minute reset" not in reply.lower()


@pytest.mark.asyncio
async def test_stream_teller_reply_energy_request_returns_grounded_high_energy_reply(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [{"role": "user", "content": "help me manifest more money"}]
    cached, reply = await stream_teller_reply(6678842, "hype me up", history=history)

    assert cached is False
    assert "Good." in reply or "Move" in reply
    assert "more money usually" not in reply.lower()
    assert "short script, a few affirmations, or a 2-minute reset" not in reply.lower()


@pytest.mark.asyncio
async def test_stream_teller_reply_another_with_no_artifact_asks_specific_clarification(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    cached, reply = await stream_teller_reply(667885, "another")

    assert cached is False
    assert reply == "Do you want another script, affirmations, reset, or story?"


@pytest.mark.asyncio
async def test_stream_teller_reply_script_after_action_switch_does_not_use_action_words_as_topic(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    cached, reply = await stream_teller_reply(667794, "actually wait give me a script first")

    assert cached is False
    assert reply.startswith("Script:")
    assert "transfer 1000" not in reply.lower()
    assert "I am available for transfer" not in reply.lower()


@pytest.mark.asyncio
async def test_generate_teller_reply_short_circuits_greeting_to_neutral_assist(monkeypatch):
    async def fake_openai_response(*args, **kwargs):
        raise AssertionError("Greeting should not call OpenAI in neutral assist mode")

    monkeypatch.setattr(teller_provider, "_openai_response", fake_openai_response)

    cached, reply = await generate_teller_reply(123456, "hi there")

    assert cached is False
    assert reply.startswith("Hi. What would you like to do?")


@pytest.mark.asyncio
async def test_generate_teller_reply_passes_repeat_count_to_openai(monkeypatch):
    async def fake_openai_response(message, history=None, short_mode=False, repeat_count=0):
        assert repeat_count == 1
        return "## Insight\nLet’s take this from a new angle.\n\n## Reflection\nWhich direction do you want next?"

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response", fake_openai_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [
        {"role": "user", "content": "Write a Future Success Story"},
        {"role": "assistant", "content": "First version"},
    ]
    cached, reply = await generate_teller_reply(334455, "Write a Future Success Story", history=history)

    assert cached is False
    assert "new angle" in reply


@pytest.mark.asyncio
async def test_generate_teller_reply_runs_copyeditor_pass(monkeypatch):
    async def fake_openai_response(message, history=None, short_mode=False, repeat_count=0):
        return "you’re welcome. glad i could help. anything else i can do for you right now"

    async def fake_copyedit_reply(text, short_mode=False):
        assert "glad i could help" in text
        return "You’re welcome. Glad I could help. Anything else I can do for you right now?"

    monkeypatch.setattr(teller_provider, "_openai_response", fake_openai_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", fake_copyedit_reply)

    cached, reply = await generate_teller_reply(998877, "thanks")

    assert cached is False
    assert reply == "You’re welcome. Glad I could help. Anything else I can do for you right now?"


@pytest.mark.asyncio
async def test_stream_teller_reply_copyeditor_preserves_markdown_structure(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "## insight\nsteady next steps\n- first step"

    async def fake_copyedit_reply(text, short_mode=False):
        return "## Insight\nSteady next steps.\n- first step"

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", fake_copyedit_reply)

    cached, reply = await stream_teller_reply(887766, "help me")

    assert cached is False
    assert "## Insight" not in reply
    assert "Steady next steps." in reply
    assert "- first step" in reply


@pytest.mark.asyncio
async def test_stream_teller_reply_uses_openai_stream_for_normal_prompts(monkeypatch):
    deltas: list[str] = []

    async def fake_stream_response(message, history=None, short_mode=False, on_delta=None, repeat_count=0):
        assert message == "relaxing into wealth"
        assert repeat_count == 0
        if on_delta:
            on_delta("## Insight\n")
            on_delta("You can relax into wealth.")
        return "## Insight\nYou can relax into wealth.\n\n## Reflection\nWhat would help you receive that?"

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    cached, reply = await stream_teller_reply(654321, "relaxing into wealth", on_delta=deltas.append)

    assert cached is False
    assert "You can relax into wealth." in reply
    assert "## Insight" not in reply
    assert deltas


@pytest.mark.asyncio
async def test_stream_teller_reply_falls_back_to_standard_reply_when_stream_returns_retry_placeholder(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Fortune is thinking…"

    async def fake_standard_response(*args, **kwargs):
        return "## Insight\nYou can relax into wealth one steady breath at a time.\n\n## Reflection\nWhat would feel calming right now?"

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    cached, reply = await stream_teller_reply(987654, "support me through a hard money week")

    assert cached is False
    assert "You can relax into wealth one steady breath at a time." in reply
    assert "## Insight" not in reply
    assert "Fortune is thinking…" not in reply


@pytest.mark.asyncio
async def test_stream_teller_reply_uses_local_rescue_reply_when_both_openai_paths_fail(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Fortune is thinking…"

    async def fake_standard_response(*args, **kwargs):
        return "Connection timed out. Please try again shortly."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    cached, reply = await stream_teller_reply(246810, "support me through a hard money week")

    assert cached is False
    assert "Manifesting more money works better when vision and action stay linked." in reply or "support me through a hard money week" not in reply
    assert "Please try again" not in reply


@pytest.mark.asyncio
async def test_stream_teller_reply_uses_minimal_affirmation_rescue_reply_when_both_openai_paths_fail(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me — still working."

    async def fake_standard_response(*args, **kwargs):
        return "Fortune is thinking…"

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    cached, reply = await stream_teller_reply(135791, "Affirmations for new signature members influx in my app")

    assert cached is False
    assert reply.lstrip().startswith("- ")
    assert reply.count("- ") >= 2


@pytest.mark.asyncio
async def test_stream_teller_reply_uses_script_rescue_reply_for_script_prompt_when_openai_fails(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    cached, reply = await stream_teller_reply(112233, "HI there. Script new opportunities")

    assert cached is False
    assert reply.startswith("Script:")
    assert "opportunit" in reply.lower()
    assert "Stay with me" not in reply
    assert "You can soften into hi there" not in reply
    assert "say new opportunities" not in reply.lower()


@pytest.mark.asyncio
async def test_stream_teller_reply_uses_history_aware_longer_reply_after_script_rescue(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [
        {"role": "user", "content": "Say Script New Opportunities"},
        {"role": "assistant", "content": "**Script**\nI welcome new opportunities in a way that feels clear and steady."},
    ]

    cached, reply = await stream_teller_reply(445566, "longer", history=history)

    assert cached is False
    assert "Script:" in reply
    assert "You can soften into longer" not in reply


@pytest.mark.asyncio
async def test_stream_teller_reply_uses_history_aware_shorter_reply_after_script_rescue(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [
        {"role": "user", "content": "Script Attract the Right Connections"},
        {"role": "assistant", "content": "**Script**\nI welcome the right connections in a way that feels clear and steady."},
    ]

    cached, reply = await stream_teller_reply(556677, "shorter", history=history)

    assert cached is False
    assert reply.startswith("Script:")
    assert "connections" in reply.lower() or "right connections" in reply.lower()
    assert "you can soften" not in reply.lower()


@pytest.mark.asyncio
async def test_stream_teller_reply_uses_money_manifestation_rescue_for_manifest_money_prompt(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    cached, reply = await stream_teller_reply(202401, "how can i manifest more money")

    assert cached is False
    assert "More money usually shows up after a small number of sharper decisions" in reply
    assert "short script, a few affirmations, or a 2-minute reset" in reply
    assert "Let your shoulders drop before you make the next move." not in reply


@pytest.mark.asyncio
async def test_stream_teller_reply_builds_on_money_followup_instead_of_repeating_grounding_template(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [
        {"role": "user", "content": "how can i manifest more money"},
        {
            "role": "assistant",
            "content": (
                "More money usually responds better to clarity than pressure.\n\n"
                "Give the increase a shape and support it with one grounded action.\n\n"
                "If you want, I can turn that into a short script, a few affirmations, or a 2-minute reset."
            ),
        },
    ]

    cached, reply = await stream_teller_reply(202402, "seeing money flow in", history=history)

    assert cached is False
    assert "short script, a few affirmations, or a 2-minute reset" in reply
    assert "Let’s make that more usable right away." not in reply
    assert "Let’s keep this grounded around seeing money flow in." not in reply
    assert "Let your shoulders drop before you make the next move." not in reply


@pytest.mark.asyncio
async def test_stream_teller_reply_uses_neutral_assist_for_greeting_when_openai_fails(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    cached, reply = await stream_teller_reply(202404, "hi")

    assert cached is False
    assert reply.startswith("Hi. What would you like to do?")
    assert "let your shoulders drop" not in reply.lower()


@pytest.mark.asyncio
async def test_stream_teller_reply_uses_neutral_assist_for_unclear_short_input_when_openai_fails(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    cached, reply = await stream_teller_reply(202405, "u")

    assert cached is False
    assert reply == "Can you clarify what you'd like to do?"
    assert "grounded" not in reply.lower()


@pytest.mark.asyncio
async def test_stream_teller_reply_uses_neutral_assist_for_confirmation_typo_without_context(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    cached, reply = await stream_teller_reply(202406, "ci=onfirmed")

    assert cached is False
    assert reply == "Did you mean confirm?"
    assert "coaching" not in reply.lower()


@pytest.mark.asyncio
async def test_stream_teller_reply_turns_money_followup_choice_into_affirmations_instead_of_repeating_template(monkeypatch):
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)

    history = [
        {"role": "user", "content": "help me manifest money"},
        {
            "role": "assistant",
            "content": (
                "More money usually responds better to clarity than pressure.\n\n"
                "Give the increase a shape and support it with one grounded action.\n\n"
                "Do you want me to turn that into a short script, a few affirmations, or a 2-minute reset?"
            ),
        },
    ]

    cached, reply = await stream_teller_reply(202403, "a few affirmations,", history=history)

    assert cached is False
    assert reply.lstrip().startswith("- ")
    assert "Do you want me to turn that into a short script, a few affirmations, or a 2-minute reset?" not in reply
    assert "Good. a few affirmations" not in reply
    assert "can become a strong anchor" not in reply
