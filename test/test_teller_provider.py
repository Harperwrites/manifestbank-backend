import pytest
import httpx

from app.services import teller_provider
from app.services.teller_provider import (
    DEFAULT_TELLER_PROMPT,
    _enforce_markdown_structure,
    _extract_stream_completed_text,
    _get_repeat_count,
    _is_retry_placeholder,
    _normalize_punctuation,
    _remove_repeated_sentences,
    _response_unsupported_param,
    _strip_unsupported_response_controls,
    _strip_unsupported_action_offers,
    generate_teller_reply,
    get_persona,
    stream_teller_reply,
)


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


def test_get_persona_uses_compact_default_prompt():
    name, prompt = get_persona()

    assert name
    assert prompt == DEFAULT_TELLER_PROMPT
    assert "Repetition Rule:" in prompt
    assert "Do NOT repeat prior wording" in prompt


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
    assert "**Shorter Script**" in reply or "simpler version" in reply.lower()
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
    assert "affirmation" in reply.lower()
    assert "short script" not in reply.lower()


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
    assert "**Shorter Script**" in reply
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
    assert "**Script**" in reply
    assert "\nI " in reply
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
    assert "**Script**" in reply
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
    assert "**Script**" in reply
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
    assert "**Script**" in reply
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
    assert "**Script**" in first and "**Script**" in second
    history.extend([{"role": "user", "content": "script"}, {"role": "assistant", "content": second}])
    cached, third = await stream_teller_reply(667798, "script", history=history)
    assert cached is False
    assert third not in {first, second}
    assert "**Script**" in third


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
    assert "affirmations" in first.lower()
    assert first.count("- ") >= 2

    history = [
        {"role": "user", "content": "give affirmations for new paying signature members shorter"},
        {"role": "assistant", "content": first},
    ]
    cached, second = await stream_teller_reply(667880, "more powerful", history=history)
    assert cached is False
    assert "affirmations" in second.lower()
    assert "short script, a few affirmations, or a 2-minute reset" not in second
    assert "premium" in second.lower() or "commitment" in second.lower() or "stronger version" in second.lower()


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
    assert "**Script**" in second
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
    assert reply == "Do you want a script about money, or based on that story?"


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
    assert "**Script**" in reply
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
    assert "**Script**" in reply
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
    assert "## Insight" in reply
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
    assert "Here are a few affirmations:" in reply
    assert "- " in reply


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
    assert "**Script**" in reply
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
    assert "**Script**" in reply
    assert "**Script**" in reply
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
    assert "**Shorter Script**" in reply
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
    assert "Here are a few affirmations:" in reply or "Use the ones that feel believable enough to repeat." in reply
    assert "Do you want me to turn that into a short script, a few affirmations, or a 2-minute reset?" not in reply
    assert "Good. a few affirmations" not in reply
    assert "can become a strong anchor" not in reply
