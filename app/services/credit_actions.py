from __future__ import annotations

from typing import List, Dict


def _action(
    title: str,
    description: str,
    primary_bureau: str,
    action_type: str,
    action_route: str,
    confirmation_copy: str,
    secondary_bureau: str | None = None,
) -> Dict[str, str | None]:
    return {
        "title": title,
        "description": description,
        "primary_bureau": primary_bureau,
        "secondary_bureau": secondary_bureau,
        "confirmation_copy": confirmation_copy,
        "action_type": action_type,
        "action_route": action_route,
    }


def _repeat_variants(base_title: str, description: str, primary: str, action_type: str, route: str, count: int) -> list:
    variants = [
        base_title,
        f"{base_title} (Quick)",
        f"{base_title} (Focused)",
        f"{base_title} (Clean Finish)",
        f"{base_title} (Today)",
    ]
    items = []
    for i in range(count):
        title = variants[i % len(variants)]
        items.append(
            _action(
                title=title,
                description=description,
                primary_bureau=primary,
                action_type=action_type,
                action_route=route,
                confirmation_copy="Recorded.",
            )
        )
    return items


ACTION_LIBRARY: List[Dict[str, str | None]] = []

# Daily login (IAB)
ACTION_LIBRARY.append(
    _action(
        title="Daily Login",
        description="Sign in once per day to maintain signal continuity.",
        primary_bureau="IAB",
        action_type="daily_login",
        action_route="/dashboard",
        confirmation_copy="Recorded.",
    )
)

# IAB actions (40) – anchored to in-app actions
ACTION_LIBRARY += _repeat_variants(
    "Create a Journal Entry",
    "Write and save a new journal entry inside ManifestBank.",
    "IAB",
    "journal_entry",
    "/myjournal",
    10,
)
ACTION_LIBRARY += _repeat_variants(
    "Save an Affirmation",
    "Create a new affirmation entry and save it.",
    "IAB",
    "affirmation_save",
    "/myaffirmations",
    10,
)
ACTION_LIBRARY += _repeat_variants(
    "Post a Manifestation Check",
    "Create a check and post it to your ledger.",
    "IAB",
    "check_post",
    "/mychecks",
    10,
)
ACTION_LIBRARY += _repeat_variants(
    "Update Your Wealth Target",
    "Set or update your wealth target in your profile.",
    "IAB",
    "wealth_target_update",
    "/dashboard",
    10,
)

# Emotional Reserve actions (40)
ACTION_LIBRARY += _repeat_variants(
    "Log a Calm Deposit",
    "Post a small deposit with calm intent in your ledger.",
    "Emotional Reserve",
    "ledger_deposit",
    "/dashboard",
    10,
)
ACTION_LIBRARY += _repeat_variants(
    "Record a Gentle Expense",
    "Post an expense with a clear memo.",
    "Emotional Reserve",
    "ledger_expense",
    "/dashboard",
    10,
)
ACTION_LIBRARY += _repeat_variants(
    "Complete a Transfer",
    "Transfer between accounts with a clear reference.",
    "Emotional Reserve",
    "ledger_transfer",
    "/dashboard",
    10,
)
ACTION_LIBRARY += _repeat_variants(
    "Send a Teller Note",
    "Send one focused message in My Teller.",
    "Emotional Reserve",
    "teller_message",
    "/myteller",
    10,
)

# CTB actions (40)
ACTION_LIBRARY += _repeat_variants(
    "Write a Structured Journal Entry",
    "Create a journal entry with a clear title and focus.",
    "CTB",
    "journal_entry",
    "/myjournal",
    10,
)
ACTION_LIBRARY += _repeat_variants(
    "Respond to a Journal Prompt",
    "Open a journal prompt and respond in a new entry.",
    "IAB",
    "journal_prompt",
    "/myjournal",
    8,
)
ACTION_LIBRARY += _repeat_variants(
    "Save a Focused Affirmation",
    "Save one concise affirmation entry.",
    "CTB",
    "affirmation_save",
    "/myaffirmations",
    10,
)
ACTION_LIBRARY += _repeat_variants(
    "Post a Check With a Memo",
    "Create a check and add a precise memo.",
    "CTB",
    "check_post",
    "/mychecks",
    10,
)
ACTION_LIBRARY += _repeat_variants(
    "Complete a Teller Prompt",
    "Respond to a teller prompt with one clear answer.",
    "CTB",
    "teller_message",
    "/myteller",
    10,
)


IAB_POSITIVE = [
    "Consistent follow‑through strengthened your identity signal.",
    "Clear priorities improved your self‑alignment.",
    "Repeated completion raised your reliability mark.",
    "Stable daily standards increased continuity.",
    "Decisive action reduced identity drift.",
    "Strong boundary adherence lifted trust in your signal.",
    "On‑time closures reinforced personal consistency.",
    "Defined objectives raised alignment confidence.",
    "Regular check‑ins stabilized your profile.",
    "Reliable scheduling improved identity strength.",
    "Clean close‑outs increased continuity.",
    "Reaffirmed values elevated identity clarity.",
    "Timely confirmations boosted follow‑through.",
    "Measured commitments strengthened your record.",
    "Steady habits improved alignment depth.",
    "Improved planning raised consistency.",
    "Clear role selection enhanced identity focus.",
    "Stable routines increased signal strength.",
    "Reduced ambiguity improved self‑definition.",
    "Consistent standards elevated your profile.",
    "Completed promises increased credibility.",
    "Clear next steps improved alignment.",
    "Maintained deadlines increased identity stability.",
    "Focused execution raised reliability.",
    "Consistent check‑ins improved signal clarity.",
    "Reduced open loops strengthened identity.",
    "Intentional choices improved alignment.",
    "Strong completion rate raised your index.",
    "Honored commitments stabilized your profile.",
    "Clear yes/no decisions improved self‑trust.",
]

IAB_NEGATIVE = [
    "Extended inactivity reduced identity continuity.",
    "Unclosed loops softened your signal.",
    "Frequent changes lowered consistency.",
    "Missed commitments reduced reliability.",
    "Ambiguous priorities weakened alignment.",
    "Deferred decisions reduced clarity.",
    "Irregular follow‑through lowered stability.",
    "Delayed closures reduced trust in your signal.",
    "Incomplete tasks lowered consistency.",
    "Shifting standards reduced identity strength.",
    "Missed deadlines softened reliability.",
    "Reduced check‑ins lowered continuity.",
    "Inconsistent routines weakened alignment.",
    "Unclear objectives reduced self‑definition.",
    "Unresolved items lowered credibility.",
    "Repeated deferrals reduced stability.",
    "Incomplete confirmations softened your profile.",
    "Open loops reduced identity strength.",
    "Irregular priorities lowered coherence.",
    "Reduced planning weakened alignment.",
]

ER_POSITIVE = [
    "Regular resets strengthened your reserve.",
    "Calm pacing improved recovery capacity.",
    "Steady breathing raised regulation quality.",
    "Reduced input improved emotional balance.",
    "Consistent grounding increased reserve stability.",
    "Smooth recoveries strengthened your signal.",
    "Short pauses improved response quality.",
    "Lowered tension improved reserve strength.",
    "Timely breaks increased regulation.",
    "Gentle pacing improved steadiness.",
    "Reduced stimulus improved emotional bandwidth.",
    "Clear state‑naming stabilized your reserve.",
    "Consistent calm actions improved recovery.",
    "Reduced rush improved resilience.",
    "Careful pacing strengthened reserve quality.",
    "Regular resets increased reserve stability.",
    "Balanced transitions improved emotional steadiness.",
    "Calm starts improved regulation.",
    "Soft endings raised recovery quality.",
    "Reduced pressure improved reserve strength.",
    "Grounded posture improved emotional balance.",
    "Calm response timing improved stability.",
    "Reduced overload improved resilience.",
    "Steady breathing improved reserve capacity.",
    "Gentle check‑ins improved regulation.",
    "Balanced input improved steadiness.",
    "Managed pace improved reserve integrity.",
    "Reduced tension improved emotional strength.",
    "Short resets increased reserve quality.",
    "Consistent calmness improved emotional steadiness.",
]

ER_NEGATIVE = [
    "Extended strain reduced reserve stability.",
    "High pace lowered recovery capacity.",
    "Frequent overstimulation reduced balance.",
    "Irregular resets lowered resilience.",
    "Unmanaged tension reduced reserve strength.",
    "Prolonged overload reduced steadiness.",
    "Missed breaks lowered regulation.",
    "Escalated pace reduced recovery.",
    "Reduced grounding lowered stability.",
    "Persistent tension reduced reserve quality.",
    "Inconsistent pauses reduced regulation.",
    "High input lowered emotional bandwidth.",
    "Limited recovery time reduced steadiness.",
    "Sustained pressure reduced reserve.",
    "Unbalanced pacing lowered stability.",
    "Skipped resets reduced regulation.",
    "Reduced check‑ins lowered recovery.",
    "Increased strain reduced reserve capacity.",
    "Irregular calm actions lowered steadiness.",
    "Overload reduced reserve integrity.",
]

CTB_POSITIVE = [
    "Clear focus improved thought stability.",
    "Reduced distraction raised cognitive signal.",
    "Precise language improved clarity.",
    "Consistent focus blocks strengthened stability.",
    "Timely decisions improved narrative control.",
    "Simplified plans improved cognitive flow.",
    "Strong task framing improved focus.",
    "Clear goals improved thought coherence.",
    "Reduced multitasking improved stability.",
    "Defined outcomes improved clarity.",
    "Short plans improved follow‑through.",
    "Clean summaries strengthened narrative.",
    "Reduced ambiguity improved focus.",
    "Consistent priority setting improved control.",
    "Clear constraints improved cognitive discipline.",
    "Precise questions improved thought quality.",
    "Reduced scope improved clarity.",
    "Stable routines improved cognitive balance.",
    "Quick clarifications improved signal strength.",
    "Improved task naming improved focus.",
    "Ordered priorities improved coherence.",
    "Consistent decisions improved stability.",
    "Clear next steps improved narrative control.",
    "Defined metrics improved cognitive focus.",
    "Reduced noise improved thought quality.",
    "Clear framing improved stability.",
    "Timely updates improved coherence.",
    "Consistent summaries improved clarity.",
    "Improved attention control raised stability.",
    "Strong focus choices improved thought integrity.",
]

CTB_NEGATIVE = [
    "Prolonged distraction reduced focus stability.",
    "Unclear priorities lowered cognitive signal.",
    "Inconsistent planning reduced coherence.",
    "Frequent task switching lowered stability.",
    "Vague language reduced clarity.",
    "Missed decisions reduced narrative control.",
    "Overloaded lists reduced focus.",
    "Unclear outcomes lowered signal strength.",
    "Reduced structure lowered cognitive balance.",
    "Undefined next steps reduced clarity.",
    "Elevated noise lowered focus quality.",
    "Scope creep reduced cognitive control.",
    "Unresolved questions reduced stability.",
    "Fragmented attention lowered coherence.",
    "Unclear constraints reduced discipline.",
    "Interrupted focus blocks reduced stability.",
    "Unsorted priorities reduced clarity.",
    "Missed summaries lowered narrative stability.",
    "Inconsistent task framing reduced focus.",
    "Reduced precision lowered thought quality.",
]
