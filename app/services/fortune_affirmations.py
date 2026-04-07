from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher

FORTUNE_AFFIRMATIONS_BLUEPRINT = {
    "purpose": (
        "Fortune affirmations support identity, regulation, steadiness, abundance, coherence, "
        "self-trust, and aligned action inside ManifestBank™. They should help the user feel "
        "clearer, steadier, and more able to follow through without hype or fantasy language."
    ),
    "voice": [
        "calm",
        "warm",
        "precise",
        "premium",
        "never hypey",
        "never cheesy",
        "never robotic",
        "never filler-heavy",
        "no desperate language",
        "no exaggerated certainty",
    ],
    "core_rules": [
        "Use present tense.",
        "Keep lines easy to say aloud.",
        "Keep lines short enough to feel clean.",
        "Keep language grounded enough to feel believable.",
        "Aim for elegant clarity, not vague mystique.",
        "Do not reuse repeated stems from recent outputs.",
        "Do not sound like a social media quote generator.",
    ],
    "emotional_modes": {
        "calm": {
            "aim": "Regulate the nervous system and restore steadiness.",
            "themes": ["safety", "breath", "enoughness", "ease", "steady decisions"],
            "avoid": ["adrenalized language", "forced confidence", "big promises"],
            "style": "soft, grounded, unclenched",
        },
        "money": {
            "aim": "Support clean receiving, value, stewardship, and paid work.",
            "themes": ["value", "capacity", "receiving", "stewardship", "clear decisions"],
            "avoid": ["fantasy claims", "desperation", "magical guarantees"],
            "style": "clear, composed, materially grounded",
        },
        "pressure": {
            "aim": "Reduce urgency and inner compression.",
            "themes": ["pacing", "clarity", "space", "self-trust", "clean next steps"],
            "avoid": ["panic language", "push harder framing", "self-attack"],
            "style": "steadying, simplifying, decompressing",
        },
        "confidence": {
            "aim": "Support self-belief, voice, and embodied certainty.",
            "themes": ["self-trust", "voice", "worthiness", "clean presence", "self-respect"],
            "avoid": ["bravado", "comparison", "overcompensation"],
            "style": "clear, assured, elegant",
        },
        "focus": {
            "aim": "Reinforce follow-through, simplicity, and mental precision.",
            "themes": ["consistency", "clarity", "one next step", "completion", "attention"],
            "avoid": ["scatter", "ten priorities", "overcomplication"],
            "style": "clean, direct, deliberate",
        },
        "reset": {
            "aim": "Help the user return to center without shame.",
            "themes": ["release", "re-entry", "soft restart", "unclenching", "returning"],
            "avoid": ["self-judgment", "all-or-nothing language", "punishment"],
            "style": "gentle, forgiving, centering",
        },
        "general": {
            "aim": "Provide broadly supportive, believable affirmations.",
            "themes": ["steadiness", "clarity", "self-trust", "follow-through", "coherence"],
            "avoid": ["narrow assumptions", "grandiosity", "filler"],
            "style": "balanced, premium, usable",
        },
    },
    "patterns": [
        "direct affirmations only",
        "short insight + affirmations",
        "affirmations + reflection",
        "short insight + affirmations + reflection",
    ],
    "repetition_protection": [
        "avoid the same opener in back-to-back outputs",
        "avoid the same first affirmation in back-to-back outputs",
        "avoid the same cadence in back-to-back outputs",
        "avoid the same high-level emotional angle in back-to-back outputs",
    ],
    "tone_blacklist": [
        "Nice.",
        "Sweet.",
        "fresh set",
        "different angle",
        "tokens",
        "deals",
        "imagine",
        "imagined",
        "imaginative",
    ],
}

_STOPWORDS = {
    "i",
    "my",
    "the",
    "a",
    "an",
    "and",
    "to",
    "of",
    "it",
    "is",
    "am",
    "be",
    "with",
    "that",
    "this",
    "more",
    "into",
    "for",
    "on",
    "at",
    "through",
    "from",
}

_MODE_KEYWORDS = {
    "calm": ("calm", "grounded", "steady", "peace", "soft", "breathe", "gentle"),
    "money": ("money", "income", "paid", "payment", "balance", "deposit", "receive", "receiving", "wealth", "revenue"),
    "pressure": ("pressure", "overwhelm", "overwhelmed", "panic", "panicked", "urgent", "urgency", "stressed", "stress"),
    "confidence": ("confidence", "confident", "voice", "worthy", "worthiness", "certainty", "self trust"),
    "focus": ("focus", "focused", "clarity", "clear", "lock in", "discipline", "consistent", "consistency"),
    "reset": ("reset", "restart", "return", "begin again", "unclench", "release"),
}

_MODE_BANK = {
    "calm": [
        "I let steadiness lead before urgency does.",
        "My body can soften while I stay clear.",
        "I do not need pressure to make a clean decision.",
        "I return to center before I respond.",
        "Calm helps me see what matters without distortion.",
        "I trust grounded choices more than rushed ones.",
        "I can slow down without losing direction.",
        "My breath can reset the pace of this moment.",
        "I let enoughness settle my body first.",
        "I meet this moment without hardening around it.",
        "I let calm make the next step easier to see.",
        "I can keep my softness and still stay clear.",
        "I make room for quiet before I answer anything important.",
        "My system can settle without me abandoning the moment.",
    ],
    "money": [
        "I let paid work meet clearer standards.",
        "I make money decisions from steadiness, not strain.",
        "I receive support through clean offers and clean follow-through.",
        "I trust value to deepen when I handle it directly.",
        "I let stronger stewardship make receiving feel safer.",
        "I keep the paid step visible and I move it.",
        "I support better numbers with clearer execution.",
        "I let my work be compensated without shrinking around it.",
        "I make room for revenue by finishing what leads to payment.",
        "I let clean decisions support cleaner income.",
        "I let receiving feel cleaner when my standards are cleaner.",
        "I handle value in a way that makes money easier to hold.",
        "I trust steadier execution to support steadier income.",
        "I keep money conversations cleaner, clearer, and more direct.",
    ],
    "pressure": [
        "I release urgency that is not helping me think.",
        "I can move well without compressing myself.",
        "Pressure does not get to set the pace of my decisions.",
        "I let clarity replace internal rush.",
        "I can loosen my grip and still follow through.",
        "I trust paced action more than frantic action.",
        "I do not need to brace to be effective.",
        "I let one grounded move matter more than ten frantic ones.",
        "I make space inside the moment before I answer it.",
        "I let clean pacing protect good judgment.",
        "I loosen urgency so my thinking can stay accurate.",
        "I can reduce the rush without losing responsibility.",
        "I let steadier pacing protect the quality of my work.",
        "I do not need internal pressure to prove I care.",
    ],
    "confidence": [
        "I trust myself to speak clearly and stand by it.",
        "I do not need to overprove my value.",
        "My self-respect shows up in how I decide.",
        "I let clean follow-through strengthen my confidence.",
        "I take up space without apology or performance.",
        "I trust my voice more when I use it directly.",
        "I let steadiness make me easier to trust.",
        "I know how to move without making myself smaller first.",
        "I back my judgment with cleaner action.",
        "I let certainty grow through evidence, not force.",
        "I let composure strengthen the way I carry my value.",
        "I trust myself to stay clear even when I am visible.",
        "I let self-trust sound simple instead of loud.",
        "I move like someone who no longer needs to shrink first.",
    ],
    "focus": [
        "I give my attention to the step that changes the result.",
        "I let one clear move lead the next one.",
        "I keep the useful thing simple enough to finish.",
        "My attention works better when I stop scattering it.",
        "I trust completion more than constant switching.",
        "I return to the important task without drama.",
        "I let clarity narrow what needs my energy now.",
        "I keep my mind clean by choosing one priority at a time.",
        "I stay with the task long enough for it to move.",
        "I let consistency carry more weight than mood.",
        "I make precision easier by letting the next step stay small.",
        "I let simplicity sharpen what deserves my attention.",
        "I focus more easily when I stop feeding what scatters me.",
        "I let deliberate attention build cleaner momentum.",
    ],
    "reset": [
        "I can begin again without turning it into a verdict.",
        "I release the tension I do not need to carry forward.",
        "I return to myself without shame.",
        "I let this moment be a reset instead of a punishment.",
        "I can re-enter gently and still move well.",
        "I unclench before I decide what comes next.",
        "I do not need to earn the right to start fresh.",
        "I let softness and honesty share the same moment.",
        "I can reset my pace without abandoning my direction.",
        "I make room for a cleaner beginning now.",
        "I return gently and still trust myself afterward.",
        "I let this reset be honest, not dramatic.",
        "I can come back to the moment without hardening first.",
        "I make re-entry simpler by releasing the self-judgment around it.",
    ],
    "general": [
        "I trust clean decisions more than noisy ones.",
        "I keep my energy with the move that matters.",
        "I let steadiness shape what happens next.",
        "I follow through in ways I can respect.",
        "I let consistency build trust in myself.",
        "I give my attention to what changes the outcome.",
        "I keep the next step clear enough to do.",
        "I let self-respect show up in my actions.",
        "I move with enough calm to stay accurate.",
        "I make progress through clean repetition.",
        "I let simple follow-through quiet unnecessary noise.",
        "I keep my standards clear enough to act on them.",
        "I let steadier choices make my direction easier to trust.",
        "I stay close to what matters instead of circling it.",
        "I let clean pacing make better decisions possible.",
        "I keep the next move honest, clear, and usable.",
    ],
}

_STEM_BANK = {
    "calm": {
        "allow": [
            "I allow steadiness to lead before urgency does.",
            "I allow calm to settle my body first.",
            "I allow enoughness to soften this moment.",
            "I allow quiet to make the next step easier to see.",
        ],
        "choose": [
            "I choose grounded decisions over rushed ones.",
            "I choose a softer pace that still holds direction.",
            "I choose clarity before I answer anything important.",
            "I choose calm that keeps my judgment accurate.",
        ],
        "move": [
            "I move gently and stay clear.",
            "I move at a pace my body can trust.",
            "I move without hardening around the moment.",
            "I move with enough calm to stay accurate.",
        ],
    },
    "money": {
        "allow": [
            "I allow receiving to feel cleaner and steadier.",
            "I allow paid work to meet clearer standards.",
            "I allow value to deepen when I handle it directly.",
            "I allow stronger stewardship to support stronger income.",
        ],
        "choose": [
            "I choose money decisions that come from steadiness, not strain.",
            "I choose cleaner execution over vague hoping.",
            "I choose direct money conversations that support better results.",
            "I choose standards that make receiving easier to hold.",
        ],
        "move": [
            "I move the paid step while it still matters.",
            "I move on the offer, the ask, or the follow-up that changes the number.",
            "I move revenue forward by finishing what leads to payment.",
            "I move with visible value and clear follow-through.",
        ],
    },
    "pressure": {
        "allow": [
            "I allow urgency to loosen so clarity can return.",
            "I allow more space inside this decision.",
            "I allow steadier pacing to protect good judgment.",
            "I allow this moment to be simpler than the pressure suggests.",
        ],
        "choose": [
            "I choose paced action over frantic action.",
            "I choose clarity instead of internal rush.",
            "I choose one grounded move over ten scattered ones.",
            "I choose enough space to think well.",
        ],
        "move": [
            "I move without compressing myself.",
            "I move with clean pacing instead of panic.",
            "I move one clear step at a time.",
            "I move forward without making urgency my identity.",
        ],
    },
    "confidence": {
        "allow": [
            "I allow my value to be visible without overproving it.",
            "I allow composure to strengthen how I carry myself.",
            "I allow self-trust to sound simple instead of loud.",
            "I allow steadiness to make me easier to trust.",
        ],
        "choose": [
            "I choose clear self-respect in how I decide.",
            "I choose a direct voice over apology or performance.",
            "I choose certainty that grows through evidence.",
            "I choose presence that does not need to shrink first.",
        ],
        "move": [
            "I move like someone who trusts her own judgment.",
            "I move without making myself smaller first.",
            "I move with clean follow-through that strengthens confidence.",
            "I move with a voice that stays clear and usable.",
        ],
    },
    "focus": {
        "allow": [
            "I allow one clear priority to hold my attention.",
            "I allow simplicity to sharpen what matters now.",
            "I allow consistency to carry more weight than mood.",
            "I allow the next useful move to stay small and finishable.",
        ],
        "choose": [
            "I choose the step that changes the result.",
            "I choose completion over constant switching.",
            "I choose deliberate attention over scattered effort.",
            "I choose one useful task instead of ten competing ones.",
        ],
        "move": [
            "I move the important task far enough for it to count.",
            "I move with focused attention that stays clean.",
            "I move one priority at a time.",
            "I move with consistency that reduces noise.",
        ],
    },
    "reset": {
        "allow": [
            "I allow this moment to be a clean return.",
            "I allow softness and honesty to share the same moment.",
            "I allow re-entry without turning it into punishment.",
            "I allow a gentler pace to become a real reset.",
        ],
        "choose": [
            "I choose a fresh start without self-attack.",
            "I choose release before I decide what comes next.",
            "I choose a cleaner beginning over shame.",
            "I choose re-entry that feels honest and usable.",
        ],
        "move": [
            "I move back into the moment without hardening first.",
            "I move forward gently and still trust myself.",
            "I move from reset into one clear next step.",
            "I move on without carrying the old tension with me.",
        ],
    },
    "general": {
        "allow": [
            "I allow steady choices to shape better outcomes.",
            "I allow self-respect to show up in my actions.",
            "I allow clean pacing to support better decisions.",
            "I allow steadiness to quiet unnecessary noise.",
            "I allow simple follow-through to strengthen trust in myself.",
            "I allow clear standards to make action easier.",
        ],
        "choose": [
            "I choose clarity over internal noise.",
            "I choose the next step that actually moves things forward.",
            "I choose standards that are clear enough to act on.",
            "I choose consistency that I can respect.",
            "I choose decisions that keep momentum clean and usable.",
            "I choose the version of the step I can finish well.",
        ],
        "move": [
            "I move forward with clean, usable action.",
            "I move with enough calm to stay accurate.",
            "I move on what matters instead of circling it.",
            "I move with follow-through that keeps building trust.",
            "I move in ways that keep my direction honest.",
            "I move the useful thing before overthinking it.",
        ],
    },
}

_MODE_INSIGHTS = {
    "calm": [
        "Quiet and steady is enough here.",
        "A softer pace can still hold direction.",
        "This can stay simple and grounded.",
    ],
    "money": [
        "Value holds better when the pace stays clean.",
        "Receiving feels steadier when the language stays grounded.",
        "This can stay clear, direct, and well-held.",
    ],
    "pressure": [
        "Less internal rush leaves more room for clarity.",
        "The pace can soften without losing direction.",
        "This moment does not need more force.",
    ],
    "confidence": [
        "Confidence can stay clean and quiet.",
        "Clarity carries more weight than performance.",
        "A steadier voice is enough here.",
    ],
    "focus": [
        "Clarity gets easier when the next step stays simple.",
        "A narrower focus can hold more power.",
        "This can stay deliberate and clean.",
    ],
    "reset": [
        "A clean return is enough.",
        "This can feel gentle without losing honesty.",
        "There is room to begin again without force.",
    ],
    "general": [
        "Simple and believable is enough.",
        "This can stay clean and steady.",
        "A grounded tone carries well here.",
    ],
}

_MODE_REFLECTIONS = {
    "calm": [
        "What helps your body believe these most right now?",
        "Which one settles you the fastest?",
    ],
    "money": [
        "Which line makes receiving feel cleaner today?",
        "Which one supports your next paid move best?",
    ],
    "pressure": [
        "Which line eases the rush the most?",
        "Which one gives you more space immediately?",
    ],
    "confidence": [
        "Which line lets you stand taller without forcing it?",
        "Which one sounds most like your real voice?",
    ],
    "focus": [
        "Which line makes the next step simplest?",
        "Which one helps your attention hold steady?",
    ],
    "reset": [
        "Which line feels easiest to return to today?",
        "Which one gives you the cleanest reset?",
    ],
    "general": [
        "Which line feels easiest to repeat without strain?",
        "Which one lands most cleanly today?",
    ],
}


def _normalize(text: str | None) -> str:
    text = (text or "").lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9\s']", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _words(text: str) -> set[str]:
    return {token for token in re.findall(r"\b[a-z']+\b", _normalize(text)) if token not in _STOPWORDS and len(token) > 2}


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    ratio = SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()
    wa = _words(a)
    wb = _words(b)
    overlap = len(wa & wb) / max(1, len(wa | wb)) if wa and wb else 0.0
    return max(ratio, overlap)


def _stable_index(*parts: str, size: int) -> int:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % max(1, size)


def _recent_affirmation_texts(history: list[dict[str, str]] | None, limit: int = 2) -> list[str]:
    if not history:
        return []
    outputs: list[str] = []
    for item in reversed(history):
        if item.get("role") != "assistant":
            continue
        content = (item.get("content") or "").strip()
        if "- " not in content:
            continue
        bullets = [line.strip()[2:].strip() for line in content.splitlines() if line.strip().startswith("- ")]
        if len(bullets) < 2:
            continue
        outputs.append(content)
        if len(outputs) >= limit:
            break
    return outputs


def _recent_affirmation_lines(history: list[dict[str, str]] | None, limit: int = 2) -> list[str]:
    lines: list[str] = []
    for content in _recent_affirmation_texts(history, limit=limit):
        lines.extend([line.strip()[2:].strip() for line in content.splitlines() if line.strip().startswith("- ")])
    return lines


def _recent_openers(history: list[dict[str, str]] | None, limit: int = 2) -> list[str]:
    openers: list[str] = []
    for content in _recent_affirmation_texts(history, limit=limit):
        first = ""
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("##") or stripped.startswith("- "):
                continue
            first = stripped
            break
        if first:
            openers.append(first)
    return openers


def _recent_reflections(history: list[dict[str, str]] | None, limit: int = 2) -> list[str]:
    reflections: list[str] = []
    for content in _recent_affirmation_texts(history, limit=limit):
        capture = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped == "## Reflection":
                capture = True
                continue
            if capture and stripped:
                reflections.append(stripped)
                break
        if len(reflections) >= limit:
            break
    return reflections


def _select_recent_safe_phrase(
    options: list[str],
    *,
    history: list[dict[str, str]] | None = None,
    limit: int = 2,
    hint: str = "",
    recent_kind: str = "opener",
) -> str:
    recent = _recent_reflections(history, limit=limit) if recent_kind == "reflection" else _recent_openers(history, limit=limit)
    ranked: list[tuple[float, int, str]] = []
    for idx, option in enumerate(options):
        penalty = 0.0
        for prior in recent:
            penalty = max(penalty, _similarity(option, prior))
        ranked.append((penalty, _stable_index(hint, str(idx), size=97), option))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return ranked[0][2]


def infer_affirmation_mode(
    message: str | None,
    history: list[dict[str, str]] | None = None,
    requested_topic: str | None = None,
) -> str:
    normalized = _normalize(message)
    topic = _normalize(requested_topic)
    recent_user = " ".join((item.get("content") or "") for item in (history or [])[-6:] if item.get("role") == "user")
    context = " ".join(part for part in [normalized, topic, _normalize(recent_user)] if part)

    if any(term in context for term in _MODE_KEYWORDS["reset"]):
        return "reset"
    if any(term in context for term in _MODE_KEYWORDS["pressure"]):
        return "pressure"
    if any(term in context for term in _MODE_KEYWORDS["calm"]):
        return "calm"
    if any(term in context for term in _MODE_KEYWORDS["money"]):
        return "money"
    if any(term in context for term in _MODE_KEYWORDS["focus"]):
        return "focus"
    if any(term in context for term in _MODE_KEYWORDS["confidence"]):
        return "confidence"
    if topic in {"calm", "confidence", "focus"}:
        return topic
    if topic in {"more money", "money", "wealth identity", "new paying signature members"}:
        return "money"
    return "general"


def _pick_stem_line(
    mode: str,
    stem: str,
    *,
    history: list[dict[str, str]] | None = None,
    selected: list[str] | None = None,
    hint: str = "",
) -> str:
    bank = list(_STEM_BANK.get(mode, _STEM_BANK["general"]).get(stem, []))
    recent_lines = _recent_affirmation_lines(history, limit=3)
    recent_keys = {_normalize(line) for line in recent_lines}
    selected_keys = {_normalize(line) for line in (selected or [])}
    ranked: list[tuple[float, int, str]] = []
    for idx, line in enumerate(bank):
        penalty = 0.0
        for recent in recent_lines:
            penalty = max(penalty, _similarity(line, recent))
        if selected:
            for existing in selected:
                penalty = max(penalty, _similarity(line, existing))
        ranked.append((penalty, _stable_index(mode, stem, hint, str(idx), size=97), line))
    ranked.sort(key=lambda item: (item[0], item[1]))
    for penalty, _, line in ranked:
        normalized_line = _normalize(line)
        if normalized_line in recent_keys or normalized_line in selected_keys:
            continue
        if recent_lines and penalty >= 0.68:
            continue
        if selected and any(_similarity(line, existing) >= 0.72 for existing in selected):
            continue
        return line
    return ranked[0][2]


def _stem_sequence(line_count: int, hint: str) -> list[str]:
    base = ["allow", "choose", "move"]
    sequences = {
        3: [
            ["allow", "choose", "move"],
            ["choose", "move", "allow"],
            ["move", "allow", "choose"],
        ],
        4: [
            ["allow", "choose", "move", "allow"],
            ["choose", "move", "allow", "choose"],
            ["move", "allow", "choose", "move"],
        ],
        5: [
            ["allow", "choose", "move", "allow", "move"],
            ["choose", "move", "allow", "choose", "move"],
            ["move", "allow", "choose", "allow", "move"],
        ],
    }
    options = sequences.get(line_count, [base])
    return options[_stable_index(hint, str(line_count), size=len(options))]


def _select_lines(
    mode: str,
    *,
    history: list[dict[str, str]] | None = None,
    line_count: int = 4,
    hint: str = "",
) -> list[str]:
    stems = _stem_sequence(line_count, hint)
    selected: list[str] = []
    for idx, stem in enumerate(stems):
        selected.append(_pick_stem_line(mode, stem, history=history, selected=selected, hint=f"{hint}|{idx}"))
    return selected[:line_count]


def _choose_structure(
    mode: str,
    *,
    history: list[dict[str, str]] | None = None,
    shorter: bool = False,
    hint: str = "",
) -> str:
    recent_openers = _recent_openers(history, limit=2)
    sequence = ["bare", "insight", "framed", "framed"]
    idx = _stable_index(mode, hint, str(len(recent_openers)), size=len(sequence))
    choice = sequence[idx]
    if shorter:
        return "bare"
    if recent_openers and choice == "insight":
        return "framed"
    return choice


def _guard_affirmation_markdown(text: str) -> str:
    if not text:
        return text
    guarded = text.strip()
    for header in ("Insight", "Key Points", "Reflection"):
        guarded = re.sub(rf"## {header}[ \t]*([^\n#].+)", rf"## {header}\n\n\1", guarded)
        guarded = re.sub(rf"## {header}\n(?!\n)", f"## {header}\n\n", guarded)

    match = re.search(r"## Key Points\s*\n\n(?P<body>.*?)(?=\n## |\Z)", guarded, re.S)
    if match:
        body = match.group("body").strip()
        body_lines = [line.strip() for line in body.splitlines() if line.strip()]
        if body_lines and not all(line.startswith("- ") for line in body_lines):
            if " - " in body:
                parts = [part.strip(" -") for part in re.split(r"\s+-\s+", body) if part.strip()]
            else:
                parts = [part.strip(" -") for part in body_lines if part.strip()]
            if parts:
                rebuilt = "\n".join(f"- {part}" for part in parts)
                guarded = guarded[: match.start("body")] + rebuilt + guarded[match.end("body") :]

    guarded = re.sub(r"\n{3,}", "\n\n", guarded).strip()
    return guarded


def build_fortune_affirmations(
    *,
    message: str | None,
    requested_topic: str | None = None,
    history: list[dict[str, str]] | None = None,
    shorter: bool = False,
    stronger: bool = False,
    variant_hint: str = "",
) -> str:
    mode = infer_affirmation_mode(message, history=history, requested_topic=requested_topic)
    mode_bank_key = mode if mode in _MODE_BANK else "general"
    response_count = len(_recent_affirmation_texts(history, limit=2))
    line_count = 3 if shorter else 3 + _stable_index(mode_bank_key, variant_hint, str(response_count), size=3)
    if stronger and line_count < 4:
        line_count = 4
    lines = _select_lines(mode_bank_key, history=history, line_count=line_count, hint=f"{variant_hint}|{response_count}")
    return "\n".join(f"- {line}" for line in lines)
