from __future__ import annotations

from dataclasses import dataclass


COMMON_BANNED_PATTERNS = (
    "can become a strong anchor",
    "let’s keep this grounded around",
    "let's keep this grounded around",
    "give a short a shape",
    "give a few affirmations a shape",
    "give 2-minute reset a shape",
    "anchor this intention around give me affirmations",
    "usually opens up once you slow the pace",
    "start with one calm next step",
    "that can become more real when",
    "let’s make that more usable right away",
    "let's make that more usable right away",
    "i welcome aligned shorter",
    "i welcome in first person",
    "i welcome short",
    "do you want to continue that request, or switch tasks and cancel it?",
    "welcome back. take one slow breath. say",
    "money moving cleanly",
    "aligned growth",
    "clean action",
    "visible and direct",
    "momentum build through clean action",
    "clear value",
    "visible value",
    "the right opportunities",
    "stronger results",
)


@dataclass(frozen=True)
class ProviderEvalCase:
    id: str
    title: str
    conversation: tuple[str, ...]
    expects_all: tuple[str, ...] = ()
    expects_any: tuple[str, ...] = ()
    banned_patterns: tuple[str, ...] = COMMON_BANNED_PATTERNS
    seed_history: tuple[tuple[str, str], ...] = ()
    min_bullet_lines: int = 0
    repair_expected: bool = False
    final_sentence_complete: bool = False


@dataclass(frozen=True)
class ActionEvalTurn:
    message: str
    expects_all: tuple[str, ...] = ()
    expects_any: tuple[str, ...] = ()
    banned_patterns: tuple[str, ...] = COMMON_BANNED_PATTERNS
    direction_expected: tuple[str, str] | None = None


@dataclass(frozen=True)
class ActionEvalCase:
    id: str
    title: str
    turns: tuple[ActionEvalTurn, ...]
    setup_accounts: tuple[tuple[str, str, str], ...] = ()
    initial_deposits: tuple[tuple[str, str], ...] = ()
    confirmation_variants: tuple[str, ...] = ()
    action_mode_confirmation_only: bool = True


FORTUNE_PROVIDER_EVAL_CASES: tuple[ProviderEvalCase, ...] = (
    ProviderEvalCase(
        id="01_money_manifestation_coaching",
        title="Money manifestation coaching",
        conversation=("Manifest more money",),
        expects_all=("More money", "short script, a few affirmations, or a 2-minute reset"),
    ),
    ProviderEvalCase(
        id="02_followup_short_script",
        title="Coaching follow-up short script",
        conversation=("Manifest more money", "a short script"),
        expects_any=("**Script**", "Try this:", "I am available for"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("a short script a shape",),
    ),
    ProviderEvalCase(
        id="03_followup_affirmations",
        title="Coaching follow-up affirmations",
        conversation=("help me manifest money", "a few affirmations"),
        expects_any=("Here are a few affirmations:", "Use the ones that feel believable enough to repeat."),
        min_bullet_lines=4,
    ),
    ProviderEvalCase(
        id="04_followup_daily_set",
        title="Coaching follow-up daily set",
        conversation=("help me manifest money", "a few affirmations", "daily set"),
        expects_any=("Here’s a shorter daily set.", "Here are a few affirmations:"),
        min_bullet_lines=3,
    ),
    ProviderEvalCase(
        id="05_followup_reset",
        title="Coaching follow-up 2-minute reset",
        conversation=("Manifest more money", "2-minute reset"),
        expects_any=("2-Minute Reset", "Take one slow inhale", "Breathe in for four"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("2-minute reset a shape",),
    ),
    ProviderEvalCase(
        id="06_wealth_identity",
        title="Wealth identity coaching",
        conversation=("expand my wealth identity",),
        expects_any=("wealth", "identity"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("expand my wealth identity",),
    ),
    ProviderEvalCase(
        id="07_dream_job",
        title="Dream job coaching",
        conversation=("How do I get my dream job?",),
        expects_any=("dream", "job", "position"),
    ),
    ProviderEvalCase(
        id="08_dream_life",
        title="Dream life coaching",
        conversation=("I want my dream life. Where do I start?",),
        expects_any=("ideal day", "one area", "direction"),
    ),
    ProviderEvalCase(
        id="09_future_success_story",
        title="Future success story",
        conversation=("write a future success story",),
        expects_any=("**Story**", "Months later", "wanted more from life", "wanted a different life", "first hour of his morning"),
    ),
    ProviderEvalCase(
        id="10_relaxing_into_wealth",
        title="Relaxing into wealth",
        conversation=("relaxing into wealth",),
        expects_any=("wealth", "calm", "grounded"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("relaxing into wealth",),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="11_post_action_transition",
        title="Post-action transition into coaching",
        seed_history=(
            ("assistant", "Done. I transferred $3,900.00 from “Miracles” to “Wealth Builder”. New balance: $71,100.00."),
        ),
        conversation=("Thank you. Now scripting to bring in immediate flow of money",),
        expects_any=("script", "immediate flow", "Money"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("now scripting to bring in immediate flow of money",),
    ),
    ProviderEvalCase(
        id="12_typo_tolerance_script",
        title="Typo tolerance for script request",
        conversation=("now lets script",),
        expects_any=("**Script**", "Try this:", "I move toward"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("aligned opportunity around now lets",),
    ),
    ProviderEvalCase(
        id="13_typo_tolerance_affirmations",
        title="Typo tolerance for affirmations",
        conversation=("afirmations",),
        expects_any=("affirmations", "Here are a few affirmations"),
        min_bullet_lines=4,
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="20_bad_phrase_regression",
        title="Anti-regression bad phrase detection",
        conversation=("Manifest more money", "a short script"),
        expects_any=("**Script**", "Try this:"),
        banned_patterns=COMMON_BANNED_PATTERNS,
    ),
    ProviderEvalCase(
        id="24_affirmations_clean_closer",
        title="Affirmations for new paying signature member sign ups stay grammatically clean",
        conversation=("Can you give me affirmations for new paying signature member sign ups in my app?",),
        expects_any=("affirmations", "signature", "sign ups"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("anchor this intention around give me affirmations",),
        min_bullet_lines=4,
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="25_repair_unclear_wording",
        title="Repair unclear wording without raw phrase echo",
        seed_history=(("assistant", "What feels most supportive as you anchor this intention around give me affirmations?"),),
        conversation=("that last part didn't make much sense",),
        banned_patterns=COMMON_BANNED_PATTERNS + ("that last part didn't make much sense a shape",),
        repair_expected=True,
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="26_rewrite_approval_after_repair",
        title="Rewrite approval fulfills the offered rewrite directly",
        seed_history=(("assistant", "You're right, that part came out unclear. Let me restate it more simply.\n\nIf you'd like, I can rewrite it in a cleaner, shorter version."),),
        conversation=("yes please",),
        expects_any=("Shorter Script", "cleaner, shorter version", "simpler version"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("that last part didn't make much sense",),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="27_repair_that_didnt_hit",
        title="Repair request for that didn't hit stays specific",
        seed_history=(("assistant", "**Script**\nI stay grounded, I notice what is opening, and I move when the next clear opportunity is mine."),),
        conversation=("that didn't hit",),
        repair_expected=True,
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="28_repair_robotic_wording",
        title="Repair request for robotic wording stays specific",
        seed_history=(("assistant", "Here are a few affirmations:\n\n- I welcome aligned growth with steadiness."),),
        conversation=("that sounded robotic",),
        repair_expected=True,
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="29_greeting_uses_neutral_assist_mode",
        title="Greeting stays in neutral assist mode",
        conversation=("hi",),
        expects_all=("Hi. What would you like to do?",),
        banned_patterns=COMMON_BANNED_PATTERNS + ("let your shoulders drop",),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="30_unclear_short_input_uses_neutral_assist_mode",
        title="Unclear short input uses neutral assist mode",
        conversation=("u",),
        expects_any=("Can you clarify what you'd like to do?", "Do you want to make a transfer, deposit, or something else?"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("grounded around", "steady breath"),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="31_script_shorter_transforms_previous_content",
        title="Shorter transforms the previous script",
        seed_history=(("assistant", "**Script**\nI move toward the right opportunity with clarity, steadiness, and self-trust. I recognize what is aligned, I respond without forcing, and I let momentum build through clean action."),),
        conversation=("shorter",),
        expects_any=("Shorter Script", "I move toward", "I stay grounded"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("short script, a few affirmations, or a 2-minute reset",),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="32_script_first_person_transforms_previous_content",
        title="In first person rewrites the previous script",
        seed_history=(("assistant", "**Script**\nYou move toward the right opportunity with clarity and trust. You notice what is aligned and you act on it cleanly."),),
        conversation=("in first person",),
        expects_any=("**Script**", "I move", "I notice"),
        banned_patterns=COMMON_BANNED_PATTERNS,
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="33_repair_that_didnt_hit_rewrites_previous_script",
        title="That didn't hit rewrites script instead of reopening menu",
        seed_history=(("assistant", "**Script**\nI move toward immediate flow with clarity, steadiness, and self-trust."),),
        conversation=("that didn't hit",),
        expects_any=("Let me make it cleaner", "Let me restate", "**Script**"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("short script, a few affirmations, or a 2-minute reset",),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="34_script_followup_stays_first_person",
        title="Explicit script follow-up delivers first-person script directly",
        conversation=("help me manifest more money", "script"),
        expects_any=("**Script**", "I am", "I move"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("in front of you",),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="35_script_transform_chain_stays_attached",
        title="Script transform chain rewrites prior content instead of reopening menus",
        seed_history=(("assistant", "**Script**\nI move toward the next clear opportunity with clarity, steadiness, and self-trust. I notice what is aligned and I act on it cleanly."),),
        conversation=("shorter", "that didn't hit", "shorter better script"),
        expects_any=("**Script**", "Shorter Script", "Let me make it cleaner"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("what would you like to do", "short script, a few affirmations, or a 2-minute reset"),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="36_even_shorter_affirmations_stay_attached",
        title="Even shorter keeps refining affirmations instead of reopening options",
        seed_history=(("assistant", "Here are a few affirmations:\n\n- I let money feel safe, steady, and real.\n- I make clear decisions that support stronger results.\n- I can receive more without rushing my body.\n- Value moves more easily when I stay visible and direct."),),
        conversation=("shorter", "even shorter"),
        expects_any=("affirmations", "- I", "- Steady action"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("what would you like to do", "short script, a few affirmations, or a 2-minute reset"),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="37_story_request_returns_story",
        title="Story request returns a narrative instead of coaching or menus",
        conversation=("tell me a story about someone manifesting their dreams",),
        expects_any=("One week", "Within a few weeks", "months later", "wanted a different life"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("short script, a few affirmations, or a 2-minute reset",),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="38_affirmation_refinement_chain_stays_attached",
        title="Affirmations get shorter then stronger without reopening menus",
        seed_history=(("assistant", "Here are a few affirmations:\n\n- I receive money through clear value and strong decisions.\n- I notice opportunities that are actually worth my time.\n- I follow through in ways that increase my income.\n- I can grow without forcing or scrambling."),),
        conversation=("shorter", "more powerful"),
        expects_any=("stronger version", "Here are a few affirmations:", "bigger numbers"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("short script, a few affirmations, or a 2-minute reset",),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="39_task_switch_script_typo_stays_detached_from_action",
        title="Task switch to script keeps later script typo on content path",
        seed_history=(
            ("assistant", "Which account should I transfer from?"),
            ("user", "actually wait… give me a script first"),
            ("assistant", "**Script**\nI make decisions that increase my income.\nI recognize real opportunities and follow through while they are still in front of me.\nI let consistency, visibility, and clear value create momentum."),
        ),
        conversation=("scriot",),
        expects_any=("**Script**", "I make decisions", "I recognize real opportunities"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("which account should i transfer from",),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="40_script_in_first_person_rewrites_cleanly",
        title="Script in first person rewrites previous script without contamination",
        seed_history=(("assistant", "**Script**\nYou notice the right opportunities early and respond with clarity.\nYou trust yourself to move on what fits and ignore what distracts you."),),
        conversation=("script in first person",),
        expects_any=("**Script**", "I notice", "I trust myself"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("in first person",),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="41_money_entry_is_not_just_a_menu",
        title="General money manifestation help gives grounded guidance before the menu",
        conversation=("help me manifest more money",),
        expects_any=("More money", "income", "price", "offer"),
        banned_patterns=COMMON_BANNED_PATTERNS,
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="42_repeated_script_requests_do_not_repeat_identically",
        title="Repeated script requests in one thread do not return identical wording",
        conversation=("help me manifest more money", "script", "script"),
        expects_any=("**Script**", "income", "offer"),
        banned_patterns=COMMON_BANNED_PATTERNS,
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="43_reflective_followup_gets_light_reinforcement",
        title="Reflective followup gets acknowledgment instead of neutral clarification",
        seed_history=(("assistant", "**Script**\nI make decisions that raise my income instead of delaying it.\nI price my work with more honesty and follow up while demand is still warm.\nI let stronger earnings come from better offers and cleaner execution."),),
        conversation=("keeping this on a post it would help me",),
        expects_any=("keep it", "visible", "repeat it"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("can you clarify what you'd like to do",),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="44_praise_gets_short_acknowledgment",
        title="Praise gets a short acknowledgment instead of a new guidance block",
        seed_history=(("assistant", "Here are a few affirmations:\n\n- I make decisions that raise my income.\n- I follow through while demand is still live."),),
        conversation=("thank you",),
        expects_any=("Good. Keep using that.",),
        banned_patterns=COMMON_BANNED_PATTERNS + ("short script, a few affirmations, or a 2-minute reset",),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="48_greeting_stays_greeting_only",
        title="Greeting stays in neutral assist mode",
        conversation=("hi",),
        expects_any=("Hi. What would you like to do?",),
        banned_patterns=COMMON_BANNED_PATTERNS + ("transfer", "deposit", "planning your next move"),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="49_post_story_script_asks_clarifying_question",
        title="Script after story asks one clarifying question",
        seed_history=(("assistant", "**Story**\nNina wanted more money, but her week kept disappearing into half-finished offers."),),
        conversation=("script",),
        expects_any=("Do you want a script about money, or based on that story?",),
        banned_patterns=COMMON_BANNED_PATTERNS + ("**Script**",),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="50_another_without_context_asks_specific_clarification",
        title="Another without context asks a single specific clarification",
        conversation=("another",),
        expects_any=("Do you want another script, affirmations, reset, or story?",),
        banned_patterns=COMMON_BANNED_PATTERNS,
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="51_reflective_acknowledgment_handles_write_this_down",
        title="Reflective acknowledgment handles natural human reflection",
        seed_history=(("assistant", "**Script**\nI make decisions that raise my income instead of delaying it.\nI price my work with more honesty and follow up while demand is still warm.\nI let stronger earnings come from better offers and cleaner execution."),),
        conversation=("I'll write this down",),
        expects_any=("Good.", "That works.", "Stay consistent"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("can you clarify what you'd like to do",),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="53_reflective_acknowledgment_handles_this_makes_sense",
        title="Reflective acknowledgment handles this makes sense",
        seed_history=(("assistant", "**Script**\nI make decisions that raise my income instead of delaying it.\nI price my work with more honesty and follow up while demand is still warm.\nI let stronger earnings come from better offers and cleaner execution."),),
        conversation=("this makes sense",),
        expects_any=("Good.", "That works.", "Keep it visible"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("can you clarify what you'd like to do",),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="52_praise_handles_i_love_that",
        title="Praise intent handles I love that without reopening anything",
        seed_history=(("assistant", "Here are a few affirmations:\n\n- I make decisions that raise my income.\n- I follow through while demand is still live."),),
        conversation=("I love that",),
        expects_any=("Good. Keep using that.",),
        banned_patterns=COMMON_BANNED_PATTERNS + ("short script, a few affirmations, or a 2-minute reset",),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="54_praise_handles_that_helped",
        title="Praise intent handles that helped",
        seed_history=(("assistant", "Here are a few affirmations:\n\n- I make decisions that raise my income.\n- I follow through while demand is still live."),),
        conversation=("that helped",),
        expects_any=("Good. Keep using that.",),
        banned_patterns=COMMON_BANNED_PATTERNS + ("short script, a few affirmations, or a 2-minute reset",),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="45_mixed_affirmation_request_keeps_affirmation_artifact",
        title="Mixed affirmation request keeps artifact for stronger follow-up",
        conversation=("give affirmations for new paying signature members shorter", "more powerful"),
        expects_any=("affirmations", "commitment", "premium", "stronger version"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("short script, a few affirmations, or a 2-minute reset",),
        min_bullet_lines=2,
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="46_another_after_script_returns_new_variant",
        title="Another after script returns another script variant",
        conversation=("script please", "another"),
        expects_any=("**Script**", "income", "offer", "decisions"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("clarify what you'd like to do",),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="47_story_another_returns_distinct_story",
        title="Another after story returns another story instead of a menu",
        conversation=("tell me a story about someone manifesting their dreams", "another"),
        expects_any=("**Story**", "Within a few weeks", "A few months later", "One week"),
        banned_patterns=COMMON_BANNED_PATTERNS + ("short script, a few affirmations, or a 2-minute reset",),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="55_greeting_priority_holds_even_with_prior_script",
        title="Greeting stays greeting-only even with prior content history",
        seed_history=(("assistant", "**Script**\nI make decisions that raise my income."),),
        conversation=("hi",),
        expects_any=("Hi. What would you like to do?",),
        banned_patterns=COMMON_BANNED_PATTERNS + ("clarify what you'd like to do", "short script, a few affirmations, or a 2-minute reset"),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="56_another_script_returns_script_not_menu",
        title="Another script returns a fresh script directly",
        seed_history=(("assistant", "**Script**\nI make decisions that raise my income instead of delaying it.\nI price my work with more honesty and follow up while demand is still warm.\nI let stronger earnings come from better offers and cleaner execution."),),
        conversation=("another script",),
        expects_any=("**Script**",),
        banned_patterns=COMMON_BANNED_PATTERNS + ("what would you like", "short script, a few affirmations, or a 2-minute reset"),
        final_sentence_complete=True,
    ),
    ProviderEvalCase(
        id="57_energy_request_returns_grounded_push",
        title="Energy request returns grounded high-energy reinforcement",
        seed_history=(("user", "help me manifest more money"),),
        conversation=("hype me up",),
        expects_any=("Good.", "Move on", "Make the direct move."),
        banned_patterns=COMMON_BANNED_PATTERNS + ("more money usually", "short script, a few affirmations, or a 2-minute reset"),
        final_sentence_complete=True,
    ),
)


FORTUNE_ACTION_EVAL_CASES: tuple[ActionEvalCase, ...] = (
    ActionEvalCase(
        id="14_typo_transfer_intent",
        title="Typo tolerance for transfer intent",
        setup_accounts=(
            ("Wealth Builder", "wealth_builder", "USD"),
            ("Miracles", "personal", "USD"),
        ),
        turns=(
            ActionEvalTurn("tranfer 5000", expects_all=("Which account should I transfer from?",)),
        ),
    ),
    ActionEvalCase(
        id="15_deposit_basic",
        title="Deposit flow basic",
        setup_accounts=(
            ("Wealth Builder", "wealth_builder", "USD"),
            ("Miracles", "personal", "USD"),
        ),
        turns=(
            ActionEvalTurn("deposit", expects_all=("What amount should I deposit?",)),
            ActionEvalTurn("300000", expects_all=("Which account should I use?",)),
            ActionEvalTurn("Wealth Builder", expects_all=("Confirm deposit $300,000.00 into “Wealth Builder”?",)),
            ActionEvalTurn("confirm", expects_all=("Done. I deposited $300,000.00 into “Wealth Builder”.",)),
        ),
    ),
    ActionEvalCase(
        id="16_transfer_basic",
        title="Transfer flow basic",
        setup_accounts=(
            ("Miracles", "personal", "USD"),
            ("Wealth Builder", "wealth_builder", "USD"),
        ),
        initial_deposits=(("Miracles", "5000.00"),),
        turns=(
            ActionEvalTurn("transfer", expects_all=("What amount should I transfer?",)),
            ActionEvalTurn("3900", expects_all=("Which account should I transfer from?",)),
            ActionEvalTurn("Miracles", expects_all=("Which account should I transfer to?",)),
            ActionEvalTurn("Wealth Builder", expects_all=("Confirm transfer $3,900.00 from “Miracles” to “Wealth Builder”?",)),
        ),
        confirmation_variants=("confirmed",),
    ),
    ActionEvalCase(
        id="17_transfer_typo_accounts",
        title="Transfer flow typo-tolerant accounts",
        setup_accounts=(
            ("Wealth Builder", "wealth_builder", "USD"),
            ("Miracles", "personal", "USD"),
        ),
        initial_deposits=(("Wealth Builder", "5000.00"),),
        turns=(
            ActionEvalTurn("transfer", expects_all=("What amount should I transfer?",)),
            ActionEvalTurn("3000", expects_all=("Which account should I transfer from?",)),
            ActionEvalTurn("wealth buidler", expects_any=("Which account should I transfer to?", "Did you mean")),
            ActionEvalTurn("Miracle", expects_any=("Confirm transfer $3,000.00", "Did you mean")),
        ),
        confirmation_variants=("yes",),
    ),
    ActionEvalCase(
        id="18_partial_transfer_continuation",
        title="Partial continuation during transfer",
        setup_accounts=(
            ("Wealth Builder", "wealth_builder", "USD"),
            ("Miracles", "personal", "USD"),
        ),
        initial_deposits=(("Wealth Builder", "7000.00"),),
        turns=(
            ActionEvalTurn("transfer", expects_all=("What amount should I transfer?",)),
            ActionEvalTurn("5000", expects_all=("Which account should I transfer from?",)),
            ActionEvalTurn("Wealth Builder", expects_all=("Which account should I transfer to?",)),
        ),
    ),
    ActionEvalCase(
        id="19_confirmation_variants",
        title="Confirmation variants complete transfer",
        setup_accounts=(
            ("Miracles", "personal", "USD"),
            ("Wealth Builder", "wealth_builder", "USD"),
        ),
        initial_deposits=(("Miracles", "6000.00"),),
        turns=(
            ActionEvalTurn("transfer", expects_all=("What amount should I transfer?",)),
            ActionEvalTurn("2500", expects_all=("Which account should I transfer from?",)),
            ActionEvalTurn("Miracles", expects_all=("Which account should I transfer to?",)),
            ActionEvalTurn("Wealth Builder", expects_all=("Confirm transfer $2,500.00 from “Miracles” to “Wealth Builder”?",)),
        ),
        confirmation_variants=("yes", "confirm", "confirmed", "perfect", "sounds good", "looks good", "go ahead", "do it", "proceed", "absolutely", "okay", "yesss"),
    ),
    ActionEvalCase(
        id="21_explicit_transfer_direction_after_deposit",
        title="Explicit transfer direction is preserved after deposit flow",
        setup_accounts=(
            ("Miracles", "personal", "USD"),
            ("Wealth Builder", "wealth_builder", "USD"),
        ),
        turns=(
            ActionEvalTurn("Hi deposit 1400", expects_all=("Which account should I use?",)),
            ActionEvalTurn("miracles", expects_all=("Confirm deposit $1,400.00 into “Miracles”?",)),
            ActionEvalTurn("yes", expects_all=("Done. I deposited $1,400.00 into “Miracles”.",)),
            ActionEvalTurn(
                "Thank you. now lets transfer 1200 from miracles into wealth builder",
                expects_all=("Confirm transfer $1,200.00 from “Miracles” to “Wealth Builder”?",),
                direction_expected=("Miracles", "Wealth Builder"),
            ),
        ),
    ),
    ActionEvalCase(
        id="22_confirmation_synonyms_execute_transfer",
        title="Confirmation synonyms execute transfer during confirmation step",
        setup_accounts=(
            ("Uk Motion", "operating", "GBP"),
            ("Miracles", "personal", "USD"),
        ),
        initial_deposits=(("Uk Motion", "3000.00"),),
        turns=(
            ActionEvalTurn("transfer", expects_all=("What amount should I transfer?",)),
            ActionEvalTurn("1200", expects_all=("Which account should I transfer from?",)),
            ActionEvalTurn("Uk Motion", expects_all=("Which account should I transfer to?",)),
            ActionEvalTurn("Miracles", expects_all=("Confirm transfer £1,200.00 from “Uk Motion” to “Miracles”?",), direction_expected=("Uk Motion", "Miracles")),
        ),
        confirmation_variants=("correct", "yep", "yeah", "that's right"),
    ),
    ActionEvalCase(
        id="23_fuzzy_alias_account_mapping",
        title="Fuzzy alias account mapping for uk account",
        setup_accounts=(
            ("Uk Motion", "operating", "GBP"),
            ("Miracles", "personal", "USD"),
        ),
        initial_deposits=(("Uk Motion", "2500.00"),),
        turns=(
            ActionEvalTurn("another transfer", expects_all=("What amount should I transfer?",)),
            ActionEvalTurn("1300 pounds", expects_all=("Which account should I transfer from?",)),
            ActionEvalTurn("uk account", expects_any=("Which account should I transfer to?", "Did you mean")),
        ),
    ),
    ActionEvalCase(
        id="27_confirmation_reject_cancel",
        title="Confirmation rejection cancels transfer",
        setup_accounts=(
            ("Miracles", "personal", "USD"),
            ("Wealth Builder", "wealth_builder", "USD"),
        ),
        initial_deposits=(("Miracles", "6000.00"),),
        turns=(
            ActionEvalTurn("transfer 2500 from miracles to wealth builder", expects_all=("Confirm transfer $2,500.00 from “Miracles” to “Wealth Builder”?",)),
            ActionEvalTurn("cancel", expects_all=("Got it. I canceled that transfer.",)),
        ),
    ),
    ActionEvalCase(
        id="28_confirmation_edit_amount",
        title="Confirmation edit updates amount instead of executing",
        setup_accounts=(
            ("Miracles", "personal", "USD"),
            ("Wealth Builder", "wealth_builder", "USD"),
        ),
        initial_deposits=(("Miracles", "6000.00"),),
        turns=(
            ActionEvalTurn("transfer 2500 from miracles to wealth builder", expects_all=("Confirm transfer $2,500.00 from “Miracles” to “Wealth Builder”?",)),
            ActionEvalTurn("make it 1500", expects_all=("Confirm transfer $1,500.00 from “Miracles” to “Wealth Builder”?",)),
        ),
    ),
    ActionEvalCase(
        id="29_nonpending_approval_word_stays_in_active_state",
        title="Approval-like word does not execute when confirmation is not pending",
        setup_accounts=(
            ("Miracles", "personal", "USD"),
        ),
        initial_deposits=(("Miracles", "6000.00"),),
        turns=(
            ActionEvalTurn("transfer", expects_all=("What amount should I transfer?",)),
            ActionEvalTurn("perfect", expects_all=("What amount should I transfer?",)),
        ),
    ),
    ActionEvalCase(
        id="30_confirmation_typo_only_executes_when_confirmation_is_pending",
        title="Malformed confirm-like input only executes during active confirmation",
        setup_accounts=(
            ("Miracles", "personal", "USD"),
            ("Wealth Builder", "wealth_builder", "USD"),
        ),
        initial_deposits=(("Miracles", "6000.00"),),
        turns=(
            ActionEvalTurn("transfer", expects_all=("What amount should I transfer?",)),
            ActionEvalTurn("ci=onfirmed", expects_all=("What amount should I transfer?",)),
            ActionEvalTurn("2500", expects_all=("Which account should I transfer from?",)),
            ActionEvalTurn("Miracles", expects_all=("Which account should I transfer to?",)),
            ActionEvalTurn("Wealth Builder", expects_all=("Confirm transfer $2,500.00 from “Miracles” to “Wealth Builder”?",)),
            ActionEvalTurn("ci=onfirmed", expects_all=("Done. I transferred $2,500.00 from “Miracles” to “Wealth Builder”.",)),
        ),
    ),
    ActionEvalCase(
        id="31_typo_confirmation_yese",
        title="Typo approval confirms pending transfer",
        setup_accounts=(
            ("Miracles", "personal", "USD"),
            ("Wealth Builder", "wealth_builder", "USD"),
        ),
        initial_deposits=(("Miracles", "6000.00"),),
        turns=(
            ActionEvalTurn("transfer 3000 from miracles to wealth builder", expects_all=("Confirm transfer $3,000.00 from “Miracles” to “Wealth Builder”?",), direction_expected=("Miracles", "Wealth Builder")),
            ActionEvalTurn("yese", expects_all=("Done. I transferred $3,000.00 from “Miracles” to “Wealth Builder”.",), direction_expected=("Miracles", "Wealth Builder")),
        ),
    ),
    ActionEvalCase(
        id="32_transfer_correction_updates_not_cancel",
        title="Mid-flow correction updates active transfer instead of cancelling",
        setup_accounts=(
            ("Miracles", "personal", "USD"),
            ("Wealth Builder", "wealth_builder", "USD"),
            ("Uk Motion", "operating", "GBP"),
        ),
        turns=(
            ActionEvalTurn("transfer 2000", expects_all=("Which account should I transfer from?",)),
            ActionEvalTurn("miracles", expects_all=("Which account should I transfer to?",)),
            ActionEvalTurn("no wait not that one wealth builder to uk motion", expects_all=("Confirm transfer $2,000.00 from “Wealth Builder” to “Uk Motion”?",), direction_expected=("Wealth Builder", "Uk Motion")),
        ),
    ),
    ActionEvalCase(
        id="33_currency_integrity_pounds",
        title="Explicit pounds amount stays intact through transfer confirmation",
        setup_accounts=(
            ("Uk Motion", "operating", "GBP"),
            ("Wealth Builder", "wealth_builder", "USD"),
        ),
        turns=(
            ActionEvalTurn("transfer 2000 pounds to wealth builder", expects_any=("Which account should I transfer from?", "Confirm transfer £2,000.00 from “Uk Motion” to “Wealth Builder”?"), direction_expected=("Uk Motion", "Wealth Builder")),
        ),
    ),
)
