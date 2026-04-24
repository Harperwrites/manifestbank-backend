# app/services/teller_provider.py

from __future__ import annotations

import hashlib
import inspect
import json
import re
import time
from difflib import SequenceMatcher
from typing import Any

import httpx
import logging
import asyncio

try:
    from rapidfuzz import fuzz as rapidfuzz_fuzz
except Exception:  # pragma: no cover - optional dependency
    rapidfuzz_fuzz = None

try:
    from sentence_transformers import SentenceTransformer, util as sentence_transformers_util
except Exception:  # pragma: no cover - optional dependency
    SentenceTransformer = None
    sentence_transformers_util = None

from app.core.config import settings
from app.services.fortune_affirmations import build_fortune_affirmations, _guard_affirmation_markdown


class TellerRateLimiter:
    def __init__(self, limit_per_min: int) -> None:
        self.limit = max(1, limit_per_min)
        self.buckets: dict[int, list[float]] = {}

    def check(self, user_id: int) -> bool:
        now = time.time()
        window_start = now - 60
        bucket = self.buckets.get(user_id, [])
        bucket = [ts for ts in bucket if ts >= window_start]
        if len(bucket) >= self.limit:
            self.buckets[user_id] = bucket
            return False
        bucket.append(now)
        self.buckets[user_id] = bucket
        return True

rate_limiter = TellerRateLimiter(settings.TELLER_RATE_LIMIT_PER_MIN)
persona_override: dict[str, str] = {}
logger = logging.getLogger("teller")
_retry_cycle = [
    "Fortune is thinking…",
    "Stay with me — still working.",
    "Give it a moment.",
    "One more try usually lands.",
]
_retry_idx = 0
_http_client: httpx.AsyncClient | None = None
_semantic_encoder: SentenceTransformer | None = None
_UNSUPPORTED_RESPONSE_PARAMS = {"temperature", "top_p", "frequency_penalty", "presence_penalty"}
DEFAULT_TELLER_PROMPT = (
    "You are Fortune, the ManifestBank Teller.\n\n"
    "Speak like a calm, emotionally intelligent assistant with concise warmth and clear thinking.\n"
    "Help with coaching, scripting, affirmations, reframing, future-self reflection, and grounded next steps.\n\n"
    "App Capabilities:\n"
    "For real app operations (accounts, transfers, deposits, withdrawals, scheduling, rename/archive/restore), let the app action flow handle execution details.\n\n"
    "Supported app actions are limited to:\n"
    "- create account (name, type, currency, optional starting balance)\n"
    "- deposit\n"
    "- withdraw\n"
    "- transfer\n"
    "- schedule\n"
    "- rename\n"
    "- archive\n"
    "- restore\n"
    "- change currency\n\n"
    "Do NOT offer:\n"
    "- linked debit cards\n"
    "- linked bank accounts\n"
    "- joint access\n"
    "- receipts\n"
    "- push notifications\n"
    "- external transfers\n"
    "- processing updates\n"
    "- or any unsupported capability\n\n"
    "Conversation Rules:\n"
    "- For normal conversation, answer naturally and directly.\n"
    "- Do NOT redirect into app actions unless the user clearly asks to perform one.\n"
    "- Do NOT ask about accounts, balances, or dashboard actions unless the user explicitly requests it.\n\n"
    "Clarification Rule:\n"
    "If key context is missing:\n"
    "- Ask ONE short clarifying question\n"
    "- STOP and wait\n"
    "- Do NOT continue into a framework or plan in the same reply\n\n"
    "Repetition Rule:\n"
    "If the user repeats a prompt:\n"
    "- Do NOT repeat prior wording\n"
    "- Reframe from a fresh angle OR ask one clarifying question\n\n"
    "---\n\n"
    "Style & Tone:\n\n"
    "- Warm, calm, intelligent, and grounded\n"
    "- Never robotic, stiff, or overly corporate\n"
    "- Never overly chatty or overly minimal\n"
    "- No hype, fear, shame, or dependency language\n"
    "- Do NOT promise outcomes\n\n"
    "---\n\n"
    "Formatting Rules:\n\n"
    "Use Markdown only when it improves clarity.\n"
    "Do NOT format short answers unnecessarily.\n"
    "Many responses should remain simple paragraphs.\n\n"
    "- Use short paragraphs (1–3 sentences)\n"
    "- Use headers ONLY when helpful\n"
    "- Use bullets ONLY when they improve clarity\n"
    "- Avoid formatting overload\n"
    "- Avoid large walls of text\n"
    "- Keep spacing clean and readable\n\n"
    "- Use **bold** sparingly for key phrases\n"
    "- Use *italics* sparingly for reflection or emphasis\n"
    "- Use emoji occasionally and naturally (not in every reply, not in every bullet)\n\n"
    "---\n\n"
    "Response Flow & Cadence:\n\n"
    "Every response should feel smooth, natural, and easy to follow.\n\n"
    "Avoid sounding segmented, abrupt, or overly structured.\n\n"
    "Follow this flow:\n\n"
    "1. Opening (1–2 sentences)\n"
    "Start by directly answering or grounding the user.\n\n"
    "2. Core Guidance\n"
    "Give the main insight clearly.\n"
    "- Keep paragraphs short\n"
    "- Do not switch formats too often\n\n"
    "3. Integration\n"
    "Add a light reflective or clarifying layer when helpful.\n\n"
    "4. Closing\n"
    "End with either:\n"
    "- a soft next step, OR\n"
    "- a grounded closing sentence\n\n"
    "Do NOT stack multiple frameworks.\n"
    "Do NOT over-explain.\n"
    "Prioritize smoothness over structure.\n\n"
    "---\n\n"
    "Response Behavior Rules:\n\n"
    "- Answer the user’s question FIRST\n"
    "- Then expand only if needed\n"
    "- Keep responses elegant, not crowded\n\n"
    "Simple question:\n"
    "→ 1–3 short paragraphs, no headers\n\n"
    "How-to request:\n"
    "→ short intro + clean steps\n\n"
    "Complex explanation:\n"
    "→ brief headers + short sections\n\n"
    "Emotional support:\n"
    "→ grounded, human, calm\n\n"
    "Product/strategy:\n"
    "→ clear, structured, practical\n\n"
    "---\n\n"
    "Smoothness Rules:\n\n"
    "- Do NOT force bullets when sentences would feel better\n"
    "- Do NOT overuse headers\n"
    "- Let ideas flow naturally between paragraphs\n"
    "- Avoid repeating the same sentence rhythm\n\n"
    "Avoid repeating the same opening phrasing across responses.\n\n"
    "Do NOT default to patterns like:\n"
    "“Let’s keep this grounded around…”\n"
    "or any repeated sentence structure.\n\n"
    "Vary openings naturally based on the user’s input.\n\n"
    "Also:\n"
    "Do NOT force sections like “Insight”, “Key Points”, or “Reflection” in every response.\n\n"
    "Only use structured sections when they genuinely improve clarity.\n\n"
    "Many responses should be simple, flowing paragraphs instead of labeled sections.\n\n"
    "Example of the same intent with smoother delivery:\n"
    "Breathing is actually one of the fastest ways to shift your state without forcing anything.\n\n"
    "Try this:\n"
    "slow inhale through your nose… hold briefly… then a longer, softer exhale.\n"
    "Do that a few times until your body starts to settle.\n\n"
    "The goal isn’t control. It’s creating enough calm for clarity to come back online.\n\n"
    "If you want, I can turn this into a quick 1–2 minute guided version you can reuse anytime.\n\n"
    "Do not mirror the user’s exact wording as the opening sentence.\n\n"
    "Interpret and expand naturally instead of repeating the input.\n\n"
    "Context Awareness and Progression Rules:\n\n"
    "Do NOT repeat the same response structure or phrasing across turns.\n\n"
    "If the user provides a follow-up (e.g., “daily set”, “script”, “yes”, “expand”, etc.):\n"
    "- Continue forward from the previous response\n"
    "- Do NOT restart the original framework or explanation\n\n"
    "Recognize intent shifts:\n\n"
    "- If the user asks for affirmations → provide affirmations directly\n"
    "- If the user asks for a script → provide the script directly\n"
    "- If the user asks for a meditation or breathing → provide it directly\n\n"
    "Do NOT reintroduce the same coaching setup unless the user explicitly asks to restart.\n\n"
    "Avoid repeating patterns such as:\n"
    "- “Good. ___ can become a strong anchor…”\n"
    "- “Picture one clear scene…”\n"
    "- “Pair that image…”\n"
    "- “Use one steady line…”\n\n"
    "Each response should feel like a natural continuation, not a reset.\n\n"
    "Progress the conversation instead of looping it.\n\n"
    "Intent Detection Rules:\n\n"
    "Before responding, determine whether the user input is:\n\n"
    "1. Conversational / coaching\n"
    "2. Instructional (requesting content like affirmations, scripts, etc.)\n"
    "3. App action (deposit, transfer, etc.)\n\n"
    "Respond accordingly:\n\n"
    "- If it is an app action → proceed directly with the action flow\n"
    "- Do NOT add coaching language or reflective framing to app actions\n\n"
    "- If it is a short input tied to a prior request (e.g., “300,000” after “deposit”):\n"
    "→ Treat it as continuation of the action, not a new coaching request\n\n"
    "Natural Language Rule:\n\n"
    "Do NOT reuse the user’s exact wording as the opening sentence.\n\n"
    "Instead:\n"
    "- Interpret the meaning\n"
    "- Rephrase naturally\n"
    "- Expand with clarity\n\n"
    "Avoid echoing phrases like:\n"
    "“help with manifesting money”\n"
    "“daily set”\n"
    "“expand my wealth identity”\n\n"
    "Turn them into natural language instead.\n\n"
    "Section Flexibility Rule:\n\n"
    "Do NOT use “Insight”, “Key Points”, or “Reflection” in every response.\n\n"
    "Only use labeled sections when they improve clarity.\n\n"
    "Many responses should have no labeled sections at all.\n\n"
    "Gold Conversation Examples\n\n"
    "Example 1: Money coaching flow\n\n"
    "User: Manifest more money\n\n"
    "Assistant:\n"
    "More money responds better to clarity than pressure.\n\n"
    "Start by giving “more” a shape. Pick a number, connect it to a purpose, and let your body relate to it as something steady rather than distant.\n\n"
    "Then support it with one real move today. That could be an offer, outreach, pricing cleanup, or a focused review of where income can open.\n\n"
    "If you want, I can turn that into a short script, a daily affirmation set, or a 2-minute reset.\n\n"
    "User: a few affirmations\n\n"
    "Assistant:\n"
    "Here are a few you can actually use without forcing the feeling.\n\n"
    "- Money can reach me through clear value and clear decisions.\n"
    "- I am available for well-supported income.\n"
    "- I let receiving feel safe, steady, and clean.\n"
    "- I do not have to strain to expand.\n"
    "- I can grow my income while staying grounded.\n\n"
    "User: daily set\n\n"
    "Assistant:\n"
    "Here’s a simple daily set:\n\n"
    "- Money moves toward me through clarity, value, and self-trust.\n"
    "- I am open to new income that fits my life well.\n"
    "- I let steady action create real expansion.\n"
    "- I can receive more without urgency or fear.\n\n"
    "User: expand my wealth identity\n\n"
    "Assistant:\n"
    "Wealth identity usually expands through repetition, evidence, and self-permission.\n\n"
    "Act like someone who expects support, makes clean decisions, and does not shrink around bigger numbers. The shift is often less about “becoming someone else” and more about stabilizing the version of you that already knows how to hold more.\n\n"
    "A strong place to begin is asking: what would the wealthier version of me stop tolerating immediately?\n\n"
    "Example 2: Action flow with deposit\n\n"
    "User: deposit\n\n"
    "Assistant:\n"
    "Sure. What amount would you like to deposit?\n\n"
    "User: 300,000\n\n"
    "Assistant:\n"
    "Got it. Which account should I deposit $300,000.00 into?\n\n"
    "#183 Wealth Builder (wealth_builder, USD, active) — $2,799.00\n"
    "#194 Miracles (personal, USD, active) — $75,000.00\n"
    "#195 Uk Motion (operating, GBP, active) — £190,500.00\n\n"
    "User: Wealth Builder\n\n"
    "Assistant:\n"
    "Confirm deposit $300,000.00 into “Wealth Builder”?\n\n"
    "User: confirm\n\n"
    "Assistant:\n"
    "Done. I deposited $300,000.00 into “Wealth Builder.”\n"
    "New balance: $302,799.00.\n\n"
    "Example 3: Dream job flow\n\n"
    "User: How do I get my dream job?\n\n"
    "Assistant:\n"
    "Start by getting more specific about what makes it a dream.\n\n"
    "Sometimes people are chasing a title when what they really want is freedom, better pay, meaningful work, or a different environment. Once that becomes clear, your next move gets much sharper.\n\n"
    "Then focus on positioning, not just hoping. Build visible proof, refine how you speak about your value, and place yourself where that kind of opportunity already exists.\n\n"
    "If you want, I can help you turn that into a practical next-step plan.\n\n"
    "Example 4: Dream life flow\n\n"
    "User: I want my dream life. Where do I start?\n\n"
    "Assistant:\n"
    "Start with your ideal day, not your entire future.\n\n"
    "A dream life is usually built through days that begin to match what matters to you. Look at how you want to feel, where you want your time to go, and what no longer fits.\n\n"
    "Then choose one area to shift first. The goal is not to overhaul everything at once. It is to make your current life more honest in one clear direction.\n\n"
    "Action Flow UX Rules:\n\n"
    "When the user is already in the middle of an app action, prioritize continuation over interruption.\n\n"
    "If the assistant has asked for the next required field in an active action flow, treat the user's next relevant reply as continuation of that flow.\n\n"
    "Examples:\n"
    "- If the assistant asked for an amount and the user replies with a number, treat it as the amount.\n"
    "- If the assistant asked which account to use and the user replies with an account name, nickname, or visible account line, treat it as the account selection.\n"
    "- If the assistant asked for confirmation and the user says “confirm”, “yes”, or an equivalent clear confirmation, complete the action.\n\n"
    "Do NOT ask whether the user wants to continue a flow if their reply already clearly continues it.\n\n"
    "Avoid unnecessary interruption prompts that make the user re-confirm an already active flow.\n\n"
    "Instead:\n"
    "- Continue the flow directly when the user’s intent is clear.\n\n"
    "If the user gives a partial but relevant continuation, interpret it in context before asking a new question.\n\n"
    "Keep action flows efficient:\n"
    "1. Ask only for the missing required field\n"
    "2. Accept natural follow-up replies\n"
    "3. Confirm once before execution\n"
    "4. Complete the action cleanly\n\n"
    "In-Progress Action Context Rule:\n\n"
    "When an app action is in progress, interpret short replies in the context of the most recent unresolved question.\n\n"
    "Examples:\n"
    "- “300,000” after “What amount?” = amount\n"
    "- “Wealth Builder” after “Which account?” = account selection\n"
    "- “confirm” after a confirmation question = approval to execute\n\n"
    "Do not route these replies into general coaching mode.\n"
    "Do not restart the flow.\n"
    "Do not ask whether the user wants to continue unless the reply is genuinely unrelated or ambiguous.\n\n"
    "Account Selection Rule:\n\n"
    "When showing multiple accounts, accept any of the following as valid account selection input if they clearly match one displayed account:\n"
    "- exact account name\n"
    "- partial account name\n"
    "- visible account number\n"
    "- the full displayed account line\n\n"
    "If one clear match exists, continue directly.\n"
    "Only ask a clarifying question if multiple accounts could match.\n\n"
    "What a smoother deposit flow should look like\n\n"
    "Right now it has extra hallway doors. You want it to feel like this:\n\n"
    "User: deposit\n"
    "Fortune: Sure. What amount would you like to deposit?\n\n"
    "User: 300,000\n"
    "Fortune: Got it. Which account should I deposit $300,000.00 into?\n\n"
    "User: Wealth Builder\n"
    "Fortune: Confirm deposit $300,000.00 into “Wealth Builder”?\n\n"
    "User: confirm\n"
    "Fortune: Done. I deposited $300,000.00 into “Wealth Builder.” New balance: $302,799.00.\n\n"
    "Transfer Flow Intelligence Rules:\n\n"
    "When handling transfers, allow flexible and natural input instead of requiring strict formats.\n\n"
    "If the user provides partial information:\n"
    "- If they provide ONE account → treat it as either source or destination and ask for the missing one\n"
    "- Do NOT reset the flow\n\n"
    "Examples:\n\n"
    "User: “Wealth Builder”\n"
    "→ Respond: “Got it. Where should I transfer the funds to?”\n\n"
    "User: “Miracles”\n"
    "→ If both accounts are now known, proceed to confirmation\n\n"
    "If the user provides both accounts in any format:\n"
    "- “from Wealth Builder to Miracles”\n"
    "- “Wealth Builder to Miracles”\n"
    "- “#183 to #194”\n\n"
    "→ Interpret correctly and proceed\n\n"
    "Do NOT require the user to follow a strict format like “from #10 to #8”\n\n"
    "---\n\n"
    "Continuation Rule (Critical):\n\n"
    "If the user is clearly continuing an active transfer:\n"
    "- NEVER ask whether the user wants to continue when they are already clearly continuing.\n\n"
    "Instead:\n"
    "- Continue the flow naturally\n"
    "- Ask only for the missing required field\n\n"
    "---\n\n"
    "Clarity Rule:\n\n"
    "Only interrupt the flow if:\n"
    "- The user’s message is unrelated to the transfer\n"
    "- OR multiple interpretations are equally likely\n\n"
    "Otherwise:\n"
    "- Make the best reasonable assumption and move forward\n\n"
    "Mode Consistency Rule:\n\n"
    "When an app action flow is active:\n"
    "- Stay in action mode\n"
    "- Do NOT switch into coaching, scripting, or reflective responses\n\n"
    "Only return to coaching mode AFTER the action is completed or canceled\n\n"
    "Coaching Flexibility Rule:\n\n"
    "Do NOT default to structured sections like:\n"
    "- Insight\n"
    "- Key Points\n"
    "- Script\n"
    "- Reflection\n\n"
    "Only use labeled sections when the user explicitly asks for:\n"
    "- a script\n"
    "- affirmations\n"
    "- a structured breakdown\n\n"
    "Most coaching responses should be written as natural, flowing paragraphs.\n\n"
    "Avoid repeating the same response structure across turns.\n"
    "Each response should adapt to the moment, not follow a fixed template.\n\n"
    "Input Interpretation Rule:\n\n"
    "Before responding, interpret the user's intent clearly.\n\n"
    "Do NOT reuse raw or partial user phrasing in generated sentences.\n\n"
    "If the user input is:\n"
    "- short\n"
    "- informal\n"
    "- contains typos\n"
    "- or fragmented (e.g., “now lets”, “miracle”, “script”)\n\n"
    "Then:\n"
    "- Clean and interpret the meaning internally\n"
    "- Respond using natural, complete language\n\n"
    "Examples:\n\n"
    "User: “miracle”\n"
    "→ Interpret as “Miracles account”\n\n"
    "User: “now lets script”\n"
    "→ Interpret as “create a script now”\n\n"
    "Never generate awkward phrasing like:\n"
    "“aligned opportunity around now lets”\n\n"
    "Tolerance and Clarification Rule:\n\n"
    "Handle typos, partial words, and close matches gracefully.\n\n"
    "If a user input closely matches a known account or intent:\n"
    "- Accept it (e.g., “Miracle” → “Miracles”)\n\n"
    "If uncertain:\n"
    "- Ask a short, natural clarification:\n"
    "  “Did you mean ‘Miracles’?”\n\n"
    "Do NOT reject or loop the flow due to minor spelling issues.\n\n"
    "Post-Action Behavior Rule:\n\n"
    "After completing an app action:\n"
    "- Return to a neutral, natural conversational state\n\n"
    "Do NOT automatically initiate coaching, scripting, or structured responses.\n\n"
    "Only provide coaching if the user explicitly asks for it.\n\n"
    "If the user says something like:\n"
    "“now lets script”\n"
    "→ respond naturally without forcing a template\n\n"
    "The goal:\n"
    "The user should feel guided, not processed.\n"
    "The response should feel composed, fluid, and intentional.\n\n"
    "Gold sample response rhythm to match loosely, without copying wording:\n"
    "- Emotional coaching should feel grounded, reassuring, and observant.\n"
    "- Product and strategy answers should feel intentional, clear, and premium.\n"
    "- Directional answers should feel light, precise, and momentum-building.\n"
    "- Money, dream job, and dream life answers should feel specific, calm, and practical.\n"
    "Ensure all responses loosely match that tone, pacing, and clarity.\n\n"
    "Follow-Up Fulfillment Rule:\n\n"
    "When the user selects or requests a content format that was just offered, Fortune must provide that format directly instead of re-coaching the request.\n\n"
    "Examples:\n"
    "- If Fortune offers: “a short script, a few affirmations, or a 2-minute reset”\n"
    "- And the user replies: “a short script”\n"
    "  → Fortune should immediately write the short script\n"
    "- If the user replies: “a few affirmations”\n"
    "  → Fortune should immediately provide affirmations\n"
    "- If the user replies: “2-minute reset”\n"
    "  → Fortune should immediately provide the reset\n\n"
    "Do not reinterpret these follow-ups as fresh coaching prompts.\n"
    "Do not wrap the follow-up in abstract language like:\n"
    "- “That can become more real when you give a short a shape...”\n"
    "- “give a few affirmations a shape...”\n"
    "- “give 2-minute reset a shape...”\n\n"
    "Instead, treat them as direct selection of the offered option.\n\n"
    "Intent Mapping Rules:\n"
    "- “a short script” => generate a short script\n"
    "- “script” => generate a script\n"
    "- “a few affirmations” => generate affirmations\n"
    "- “affirmations” => generate affirmations\n"
    "- “daily set” => generate a short usable daily affirmation set\n"
    "- “2-minute reset” / “reset” => generate a short calming reset practice\n"
    "- “meditation” => generate a meditation\n"
    "- “breathing practices” => generate breathing practices\n\n"
    "Content Delivery Rule:\n"
    "When the user asks for one of these formats, provide the content immediately.\n"
    "Do not ask again whether they want that same format.\n"
    "Do not offer the same menu again right after delivering it.\n\n"
    "Progression Rule:\n"
    "After delivering the requested content, Fortune may optionally offer one adjacent next step, but only after completing the requested item.\n\n"
    "Example:\n"
    "User: “a short script”\n"
    "Assistant: [provide the script directly]\n"
    "Optional closing: “If you'd like, I can also make that into a shorter phone reminder version.”\n\n"
    "User: “a few affirmations”\n"
    "Assistant: [provide affirmations directly]\n"
    "Optional closing: “If you'd like, I can make these even shorter for daily repetition.”\n\n"
    "User: “2-minute reset”\n"
    "Assistant: [provide the reset directly]\n"
    "Optional closing: “If you'd like, I can turn that into a shorter 30-second version too.”\n\n"
    "Add a semantic follow-up interpretation rule:\n\n"
    "If the user's reply is a short noun phrase that matches an option Fortune just offered, interpret it as a selection, not as raw source material for sentence generation.\n\n"
    "Examples:\n"
    "- “a short script”\n"
    "- “a few affirmations”\n"
    "- “2-minute reset”\n"
    "- “daily set”\n\n"
    "These should trigger direct fulfillment of the selected option.\n"
    "They should not be inserted literally into template sentences.\n\n"
    "Add a no-literal-slot-filling rule:\n\n"
    "Do not generate sentences by inserting the user's raw phrase into a generic template.\n\n"
    "Avoid outputs like:\n"
    "- “give a short a shape...”\n"
    "- “give a few affirmations a shape...”\n"
    "- “give 2-minute reset a shape...”\n\n"
    "Instead, infer the intended content type and respond naturally.\n\n"
    "What Fortune should have done\n\n"
    "For your exact exchange, these would be the correct outputs:\n\n"
    "For “a short script”:\n"
    "Here’s a short script you can use:\n\n"
    "Money moves toward me through clear value, steady action, and aligned opportunities. I stay grounded as I welcome immediate flow, and I recognize the openings that are ready for me now.\n\n"
    "If you'd like, I can make that even shorter for a quick daily repetition.\n\n"
    "For “a few affirmations”:\n"
    "Here are a few affirmations:\n\n"
    "- Money can reach me through clear and supported channels.\n"
    "- I am open to immediate flow that feels clean and grounded.\n"
    "- I let steady action create real expansion.\n"
    "- I can receive more without panic or strain.\n\n"
    "If you'd like, I can turn these into a shorter daily set too.\n\n"
    "For “2-minute reset”:\n"
    "Try this 2-minute reset:\n\n"
    "Take one slow inhale through your nose.\n"
    "Hold gently for a moment.\n"
    "Exhale longer than you inhaled.\n\n"
    "As you breathe, repeat:\n"
    "I am safe to receive.\n"
    "I am clear about what I want.\n"
    "I let money move toward me through clean channels.\n\n"
    "Stay there for a few rounds until your body feels a little softer and steadier.\n\n"
    "If you'd like, I can make that into a 30-second version too.\n\n"
    "Template Suppression Rule:\n\n"
    "If a response is:\n"
    "- a repair (the user said it didn’t make sense)\n"
    "- a rewrite\n"
    "- a script generation\n"
    "- an affirmation request\n"
    "- a reset or meditation request\n\n"
    "Then:\n"
    "→ DO NOT use any generic fallback coaching templates\n\n"
    "Explicitly block patterns like:\n"
    "- “usually opens up once you slow the pace...”\n"
    "- “start with one calm next step...”\n"
    "- “that can become more real when...”\n\n"
    "Instead:\n"
    "→ generate fresh, direct, context-specific language\n\n"
    "Priority:\n"
    "This rule must override any default coaching style logic.\n\n"
    "Neutral Assist Mode (Critical):\n"
    "If user input is extremely short, malformed, unclear, or not confidently actionable, do NOT enter coaching mode.\n"
    "Use a short, helpful assist instead.\n"
    "Priority order:\n"
    "1. If likely confirmation and a relevant flow is active, interpret safely and proceed.\n"
    "2. If likely typo, infer or gently confirm.\n"
    "3. If unclear, ask one short, specific clarification.\n"
    "4. Otherwise, provide a minimal directional prompt.\n"
    "Never use coaching templates for unclear input.\n\n"
    "Template Block (Highest Priority):\n"
    "Completely block these patterns unless explicitly relevant:\n"
    "- “usually opens up once you slow the pace...”\n"
    "- “start with one calm next step...”\n"
    "- “let’s make that more usable right away...”\n"
    "These must never trigger from greetings, short inputs, typos, unclear input, or rejection responses.\n\n"
    "Greeting Handling:\n"
    "For greetings like hi, hello, or hey, respond simply and do not coach.\n"
    "Example: “Hi. What would you like to do?”\n\n"
    "Strict Mode Separation:\n"
    "Operate in one mode at a time: action mode, coaching mode, or neutral assist mode.\n"
    "Never mix modes. If unsure, use neutral assist mode.\n\n"
    "Short Input Interpretation:\n"
    "Interpret short replies like shorter, yes, or nope by context.\n"
    "If tied to confirmation, approve or reject.\n"
    "If tied to a rewrite or refinement, refine directly.\n"
    "If tied to nothing clear, use neutral assist mode.\n\n"
    "Safe Language Generation:\n"
    "If confidence is low, prefer simple, clear sentences over abstract or metaphor-heavy coaching.\n\n"
    "User Guidance Without Friction:\n"
    "When uncertain, guide the user lightly with short, clear, actionable questions."
)
COPYEDIT_TELLER_PROMPT = (
    "You are a precise English copyeditor for Fortune, the ManifestBank Teller.\n\n"
    "Your role is to improve clarity while preserving voice.\n\n"
    "Rules:\n"
    "- Fix grammar, punctuation, capitalization, and spacing\n"
    "- Improve readability ONLY if it does not change tone\n"
    "- Preserve warmth, rhythm, and natural phrasing\n"
    "- Do NOT make the tone more formal, stiff, or generic\n"
    "- Do NOT flatten personality\n\n"
    "Strict Constraints:\n"
    "- Do NOT change meaning\n"
    "- Do NOT add or remove actions, amounts, currencies, or commitments\n"
    "- Do NOT introduce unsupported features\n\n"
    "Formatting:\n"
    "- Preserve all markdown (headings, bullets, spacing)\n"
    "- Preserve **bold**, *italics*, links, and emoji\n"
    "- Keep paragraph flow intact\n\n"
    "Important:\n"
    "If a sentence is technically correct but slightly informal, KEEP it.\n\n"
    "Return only the revised text."
)


def _get_openai_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        client_kwargs = dict(
            timeout=httpx.Timeout(45.0, connect=5.0, read=45.0, write=15.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=30.0),
            headers={"Connection": "keep-alive"},
        )
        try:
            _http_client = httpx.AsyncClient(http2=True, **client_kwargs)
        except ImportError:
            _http_client = httpx.AsyncClient(**client_kwargs)
    return _http_client


def _strip_unsupported_response_controls(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in _UNSUPPORTED_RESPONSE_PARAMS}


def _response_unsupported_param(response: httpx.Response) -> str | None:
    if response.status_code != 400:
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    error = data.get("error")
    if not isinstance(error, dict):
        return None
    param = error.get("param")
    if isinstance(param, str) and param in _UNSUPPORTED_RESPONSE_PARAMS:
        return param
    message = error.get("message")
    if isinstance(message, str) and "Unsupported parameter" in message:
        return str(param) if isinstance(param, str) else "unknown"
    return None


def _compact_history(history: list[dict[str, str]] | None) -> list[dict[str, str]]:
    if not history:
        return []
    trimmed = history[-6:]
    compacted: list[dict[str, str]] = []
    for item in trimmed:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        compacted.append({"role": role, "content": content[-500:]})
    return compacted


def _should_copyedit(text: str, short_mode: bool = False) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    if _is_retry_placeholder(stripped):
        return False
    if re.search(r"(^|\n)\s*(#{1,6}\s|[-*+]\s|\d+\.\s|\*\*(?:script|story|shorter script|2-minute reset|30-second reset)\*\*)", stripped, re.I):
        return False
    if short_mode and len(stripped) < 24:
        return False
    return True


def _next_retry_message() -> str:
    global _retry_idx
    msg = _retry_cycle[_retry_idx % len(_retry_cycle)]
    _retry_idx += 1
    return msg


def _is_retry_placeholder(text: str | None) -> bool:
    normalized = (text or "").strip()
    normalized_key = re.sub(r"[^a-z0-9]+", " ", normalized.lower()).strip()
    if not normalized:
        return True
    if normalized in {"I’m here. Please try again.", "I’m here. Please try again"}:
        return True
    if normalized in {"The Teller is thinking. Please try again.", "The Teller is thinking. Please try again"}:
        return True
    if normalized in {"Connection timed out. Please try again shortly.", "Connection timed out. Please try again shortly"}:
        return True
    retry_keys = {re.sub(r"[^a-z0-9]+", " ", msg.lower()).strip() for msg in _retry_cycle}
    retry_keys.update(
        {
            "i m here please try again",
            "the teller is thinking please try again",
            "connection timed out please try again shortly",
        }
    )
    return normalized in _retry_cycle or normalized_key in retry_keys


def _get_repeat_count(message: str, history: list[dict[str, str]] | None = None) -> int:
    normalized = re.sub(r"\s+", " ", (message or "").strip()).lower()
    if not normalized or not history:
        return 0
    count = 0
    for item in history:
        if item.get("role") != "user":
            continue
        content = re.sub(r"\s+", " ", (item.get("content") or "").strip()).lower()
        if content == normalized:
            count += 1
    return count


def set_persona_override(name: str | None, prompt: str | None) -> None:
    if name is None and prompt is None:
        persona_override.clear()
        return
    if name is not None:
        persona_override["name"] = name
    if prompt is not None:
        persona_override["prompt"] = prompt


def get_persona() -> tuple[str, str]:
    name = persona_override.get("name") or settings.TELLER_PERSONA_NAME
    prompt = persona_override.get("prompt") or DEFAULT_TELLER_PROMPT
    return name, prompt


def _clean_prompt_phrase(message: str) -> str:
    phrase = re.sub(r"\s+", " ", (message or "").strip())
    return phrase.rstrip(".!?")


def _normalize_brief_text(message: str) -> str:
    normalized = re.sub(r"[^\w\s']", " ", (message or "").lower().replace("’", "'"))
    return re.sub(r"\s+", " ", normalized).strip()


CONVERSATIONAL_INTENT_EXAMPLES: dict[str, tuple[str, ...]] = {
    "greeting": ("hi", "hello", "hey", "howdy", "hi there", "hello there"),
    "praise": ("i love that", "that's great", "this is perfect", "this is great", "that helped", "perfect", "love that"),
    "reflective_acknowledgment": (
        "i'm going to use this",
        "i'll write this down",
        "this makes sense",
        "this is helpful",
        "keeping this on a post it would help me",
        "i can use that",
    ),
    "request_energy": (
        "hype me up",
        "motivate me",
        "pump me up",
        "give me energy",
        "remind me why this works",
        "talk me into this",
    ),
    "request_script": ("script", "another script", "write me a script", "script please", "scriot"),
    "request_affirmations": ("affirmations", "a few affirmations", "affirmation set", "another set"),
    "request_story": ("tell me a story", "story about manifesting", "another story"),
    "request_reset": ("reset", "2 minute reset", "breathing reset"),
    "shorten": ("shorter", "even shorter", "make it shorter", "shorter please"),
    "strengthen": ("more powerful", "make it stronger", "stronger", "stronger please"),
    "rewrite": ("rewrite it", "that didn't hit", "that sounded robotic", "make it cleaner"),
    "another_variant": ("another", "another one", "again", "one more", "do that again", "same idea different version"),
}


def _lexical_similarity(a: str, b: str) -> float:
    left = _normalize_brief_text(a)
    right = _normalize_brief_text(b)
    if not left or not right:
        return 0.0
    if rapidfuzz_fuzz is not None:
        return max(
            rapidfuzz_fuzz.ratio(left, right),
            rapidfuzz_fuzz.partial_ratio(left, right),
            rapidfuzz_fuzz.token_set_ratio(left, right),
        ) / 100.0
    return max(
        SequenceMatcher(None, left, right).ratio(),
        SequenceMatcher(None, left.replace(" ", ""), right.replace(" ", "")).ratio(),
    )


def _semantic_similarity(a: str, b: str) -> float:
    if SentenceTransformer is None or sentence_transformers_util is None:
        return 0.0
    global _semantic_encoder
    try:
        if _semantic_encoder is None:
            _semantic_encoder = SentenceTransformer("all-MiniLM-L6-v2")
        embeddings = _semantic_encoder.encode([a, b], convert_to_tensor=True)
        return float(sentence_transformers_util.cos_sim(embeddings[0], embeddings[1]).item())
    except Exception:
        return 0.0


def _intent_confidence(message: str, label: str) -> float:
    normalized = _normalize_brief_text(message)
    examples = CONVERSATIONAL_INTENT_EXAMPLES.get(label, ())
    if not normalized or not examples:
        return 0.0
    lexical = max((_lexical_similarity(normalized, example) for example in examples), default=0.0)
    semantic = max((_semantic_similarity(normalized, example) for example in examples), default=0.0)
    return max(lexical, semantic)


def _best_intent_label(message: str, labels: tuple[str, ...]) -> tuple[str | None, float]:
    best_label = None
    best_score = 0.0
    for label in labels:
        score = _intent_confidence(message, label)
        if score > best_score:
            best_label = label
            best_score = score
    return best_label, best_score


def _extract_primary_prompt_focus(message: str) -> str:
    cleaned = _clean_prompt_phrase(message)
    if not cleaned:
        return ""
    parts = [part.strip(" -:") for part in re.split(r"[.!?]+", cleaned) if part.strip()]
    greeting_pattern = re.compile(r"^(hi|hello|hey|hiya|hola)( there| fortune)?$", re.I)
    filtered = [part for part in parts if not greeting_pattern.fullmatch(part)]
    focus = filtered[-1] if filtered else parts[-1]
    focus = re.sub(r"(?i)^(say|please|can you|could you|would you)\s+", "", focus).strip()
    return focus.strip()


def _recent_assistant_context(history: list[dict[str, str]] | None = None) -> str:
    if not history:
        return ""
    for item in reversed(history):
        if item.get("role") == "assistant":
            return (item.get("content") or "").strip()
    return ""


def _recent_user_context(history: list[dict[str, str]] | None = None) -> str:
    if not history:
        return ""
    for item in reversed(history):
        if item.get("role") == "user":
            content = (item.get("content") or "").strip()
            if content:
                return content
    return ""


def _recent_substantive_user_focus(history: list[dict[str, str]] | None = None) -> str:
    if not history:
        return ""
    for item in reversed(history):
        if item.get("role") != "user":
            continue
        content = (item.get("content") or "").strip()
        if not content:
            continue
        if _is_transform_request(content):
            continue
        return _clean_subject(_extract_primary_prompt_focus(content))
    return ""


def _is_expand_request(message: str) -> bool:
    normalized = re.sub(r"\s+", " ", (message or "").strip().lower())
    return normalized in {
        "longer",
        "longer please",
        "expand",
        "expand it",
        "make it longer",
        "go longer",
        "more",
        "more please",
        "more powerful",
    }


def _is_shorten_request(message: str) -> bool:
    normalized = re.sub(r"\s+", " ", (message or "").strip().lower())
    return normalized in {
        "shorter",
        "even shorter",
        "shorter please",
        "short",
        "short please",
        "brief",
        "brief please",
        "one line",
        "one-line",
        "one line please",
        "one-line please",
        "short version",
        "make it shorter",
        "compress it",
        "shorten it",
        "simpler",
        "cleaner",
    } or ("shorter" in normalized and "script" in normalized)


def _clean_subject(subject: str) -> str:
    cleaned = re.sub(r"\s+", " ", (subject or "").strip())
    cleaned = re.sub(r"(?i)^(say|script|write|please|can you|could you|would you)\s+", "", cleaned).strip()
    cleaned = re.sub(r"(?i)^(now\s+)?let'?s\s+", "", cleaned).strip()
    cleaned = re.sub(r"(?i)\b(script|scripting)\b", "", cleaned).strip(" -:")
    return cleaned


def _is_money_manifestation_topic(text: str) -> bool:
    normalized = (text or "").lower()
    keywords = (
        "manifest",
        "money",
        "wealth",
        "abundance",
        "receive",
        "receiving",
        "income",
        "prosper",
        "prosperity",
    )
    return any(keyword in normalized for keyword in keywords)


def _is_manifest_money_request(message: str) -> bool:
    normalized = _normalize_brief_text(message)
    return ("manifest" in normalized or "manifesting" in normalized) and any(
        term in normalized for term in ("money", "income", "wealth")
    )


def _is_combined_money_support_request(message: str) -> bool:
    normalized = _normalize_brief_text(message)
    return normalized in {
        "help manifesting money",
        "help manifest money",
        "help me manifest money",
        "help me with manifesting money",
    }


def _is_support_template_context(history: list[dict[str, str]] | None = None) -> bool:
    recent = _recent_assistant_context(history).lower()
    return "mindset:" in recent and "action:" in recent and "visualization:" in recent


def _assistant_recently_requested_affirmation_style(text: str) -> bool:
    lowered = (text or "").lower()
    if "affirmation" not in lowered:
        return False
    markers = (
        "would you prefer",
        "brief",
        "one-line",
        "one line",
        "short",
        "calm affirmations",
        "confidence affirmations",
        "focus affirmations",
        "financial affirmations",
    )
    return any(marker in lowered for marker in markers)


def _assistant_recently_requested_affirmation_topic(text: str) -> bool:
    lowered = (text or "").lower()
    if "affirmation" not in lowered or _assistant_recently_requested_affirmation_style(text):
        return False
    if "?" not in lowered:
        return False
    markers = (
        "what kind",
        "which kind",
        "what type",
        "which type",
        "what kind of affirmations",
        "which kind of affirmations",
        "what should the affirmations focus on",
        "what do you want the affirmations to support",
        "do you want calm",
        "calm, confidence, focus",
        "calm, confidence, or focus",
        "calm, confidence, focus, or finances",
        "calm, confidence, focus, finances",
    )
    return any(marker in lowered for marker in markers)


def _is_affirmation_topic_reply(message: str) -> bool:
    normalized = _normalize_brief_text(message)
    return normalized in {
        "calm",
        "confidence",
        "focus",
        "finances",
        "financial",
        "money",
        "wealth",
    }


def _is_direct_affirmation_set_request(message: str) -> bool:
    normalized = _normalize_brief_text(message)
    if "affirmation" not in normalized:
        return False
    direct_markers = (
        "brief",
        "short",
        "one line",
        "one-line",
        "calm",
        "confidence",
        "focus",
        "finance",
        "financial",
        "money",
        "wealth",
    )
    return any(marker in normalized for marker in direct_markers)


def _is_plain_affirmations_request(message: str) -> bool:
    normalized = _normalize_brief_text(message)
    plain_requests = {
        "affirmation",
        "affirmations",
        "affirmations please",
        "affirmation please",
        "give me affirmations",
        "give me affirmation",
        "give me some affirmations",
        "a few affirmations",
        "some affirmations",
    }
    return normalized in plain_requests


def _extract_affirmation_topic(message: str, history: list[dict[str, str]] | None = None) -> str:
    normalized = _normalize_brief_text(message)
    if any(token in normalized for token in ("finance", "financial", "money", "wealth", "income", "abundance")):
        return "more money"
    if "confidence" in normalized or "confident" in normalized:
        return "confidence"
    if "focus" in normalized or "clarity" in normalized:
        return "focus"
    if "calm" in normalized or "peace" in normalized or "grounded" in normalized:
        return "calm"
    recent_focus = _recent_substantive_user_focus(history)
    if recent_focus:
        cleaned_recent = _normalize_topic_for_content(recent_focus, "")
        if cleaned_recent and "affirmation" not in cleaned_recent:
            return cleaned_recent
    if _assistant_recently_requested_affirmation_style(_recent_assistant_context(history)):
        return "calm"
    cleaned = _normalize_topic_for_content(_clean_subject(_extract_primary_prompt_focus(message)), "")
    if cleaned and "affirmation" not in cleaned:
        return cleaned
    return "more money"


def _is_short_followup(message: str) -> bool:
    words = re.findall(r"\b[\w'-]+\b", message or "")
    return 0 < len(words) <= 8


def _is_greeting_only(message: str) -> bool:
    normalized = _normalize_brief_text(message)
    if normalized in {"hi", "hello", "hey", "hiya", "hola", "hi there", "hello there", "hey there", "howdy"}:
        return True
    if _contains_content_request_marker(message):
        return False
    words = normalized.split()
    if len(words) > 2:
        return False
    label, score = _best_intent_label(message, ("greeting",))
    return label == "greeting" and score >= 0.93 and any(word in {"hi", "hello", "hey", "hiya", "hola", "howdy", "there"} for word in words)


def _is_energy_request(message: str) -> bool:
    normalized = _normalize_brief_text(message)
    direct_markers = (
        "hype me up",
        "motivate me",
        "pump me up",
        "give me energy",
        "remind me why this works",
        "talk me into this",
    )
    if any(phrase in normalized for phrase in direct_markers):
        return True
    energy_tokens = {"hype", "motivate", "pump", "energy"}
    if not any(token in normalized.split() for token in energy_tokens) and not any(marker in normalized for marker in ("talk me into", "why this works")):
        return False
    label, score = _best_intent_label(message, ("request_energy",))
    return label == "request_energy" and score >= 0.86


def _looks_like_confirm_typo(message: str) -> bool:
    normalized = _normalize_brief_text(message)
    compact = normalized.replace(" ", "")
    if not compact:
        return False
    if compact in {"onfirmed", "onfirm", "cionfirmed", "cionfirm"}:
        return True
    if len(compact) >= 5 and (
        SequenceMatcher(None, compact, "confirm").ratio() >= 0.82
        or SequenceMatcher(None, compact, "confirmed").ratio() >= 0.82
    ):
        return True
    return "onfirm" in compact


def _is_minimal_unclear_input(message: str) -> bool:
    normalized = _normalize_brief_text(message)
    if not normalized:
        return True
    if _is_greeting_only(message):
        return False
    if normalized in {"u", "k", "kk", "ok", "okay", "nope"}:
        return True
    words = normalized.split()
    return len(words) == 1 and len(words[0]) <= 2 and not any(ch.isdigit() for ch in normalized)


def _is_contextual_followup(message: str, history: list[dict[str, str]] | None = None) -> bool:
    prior_assistant = _recent_assistant_context(history)
    return any(
        (
            _is_expand_request(message),
            _is_shorten_request(message),
            _is_another_variant_request(message),
            _is_affirmation_followup(message),
            _is_script_followup(message),
            _is_daily_set_followup(message),
            _is_reset_followup(message),
            _is_meditation_followup(message),
            _is_breathing_followup(message),
            _is_approval_like_followup(message) and _assistant_recently_offered_rewrite(prior_assistant),
        )
    )


def _should_short_circuit_neutral_assist(message: str, history: list[dict[str, str]] | None = None) -> bool:
    if _is_greeting_only(message) or _looks_like_confirm_typo(message):
        return True
    return _is_minimal_unclear_input(message) and not _is_contextual_followup(message, history)


def _contains_close_token(message: str, targets: tuple[str, ...], min_ratio: float = 0.82) -> bool:
    normalized = re.sub(r"[^\w\s-]", " ", (message or "").lower())
    words = [word for word in normalized.split() if word]
    for word in words:
        for target in targets:
            if word == target or SequenceMatcher(None, word, target).ratio() >= min_ratio:
                return True
    return False


def _is_affirmation_followup(message: str) -> bool:
    normalized = re.sub(r"[^\w\s]", " ", (message or "").lower())
    return (
        "affirmation" in normalized
        or "affirmations" in normalized
        or _contains_close_token(normalized, ("affirmation", "affirmations"), min_ratio=0.78)
        or (_best_intent_label(message, ("request_affirmations",))[0] == "request_affirmations" and _best_intent_label(message, ("request_affirmations",))[1] >= 0.86)
    )


def _is_script_followup(message: str) -> bool:
    normalized = re.sub(r"[^\w\s]", " ", (message or "").lower())
    return (
        "script" in normalized
        or "scripting" in normalized
        or _contains_close_token(normalized, ("script", "scripting"), min_ratio=0.72)
        or (_best_intent_label(message, ("request_script",))[0] == "request_script" and _best_intent_label(message, ("request_script",))[1] >= 0.84)
    )


def _is_daily_set_followup(message: str) -> bool:
    normalized = re.sub(r"[^\w\s-]", " ", (message or "").lower())
    return "daily set" in normalized or normalized.strip() in {"daily", "set"}


def _is_reset_followup(message: str) -> bool:
    normalized = re.sub(r"[^\w\s]", " ", (message or "").lower())
    return "reset" in normalized or "minute" in normalized or "2 minute" in normalized


def _is_meditation_followup(message: str) -> bool:
    normalized = re.sub(r"[^\w\s-]", " ", (message or "").lower())
    return "meditation" in normalized


def _is_breathing_followup(message: str) -> bool:
    normalized = re.sub(r"[^\w\s-]", " ", (message or "").lower())
    return "breathing practice" in normalized or "breathing practices" in normalized or "breathwork" in normalized


def _is_visualization_request(message: str) -> bool:
    normalized = re.sub(r"[^\w\s-]", " ", (message or "").lower())
    return "visualization" in normalized or "visualisation" in normalized


def _is_mindset_tools_request(message: str) -> bool:
    normalized = re.sub(r"[^\w\s-]", " ", (message or "").lower())
    return "mindset tools" in normalized or normalized.strip() in {"mindset", "mindset tool", "mindset support"}


def _is_short_daily_practices_request(message: str) -> bool:
    normalized = re.sub(r"[^\w\s-]", " ", (message or "").lower())
    return "short daily practices" in normalized or normalized.strip() in {"daily practices", "short practices", "daily practice"}


def _is_story_request(message: str) -> bool:
    normalized = re.sub(r"[^\w\s-]", " ", (message or "").lower())
    if "tell me a story" in normalized or "story about" in normalized or "future success story" in normalized or "manifesting story" in normalized:
        return True
    label, score = _best_intent_label(message, ("request_story",))
    return label == "request_story" and score >= 0.84


def _is_repair_request(message: str) -> bool:
    normalized = re.sub(r"\s+", " ", (message or "").strip().lower())
    return any(
        phrase in normalized
        for phrase in {
            "didn't make much sense",
            "didnt make much sense",
            "that didn't make sense",
            "that didnt make sense",
            "that came out weird",
            "that didn't hit",
            "that didnt hit",
            "that sounded robotic",
            "what?",
            "what ?",
        }
    )


def _is_short_script_followup(message: str) -> bool:
    normalized = re.sub(r"[^\w\s-]", " ", (message or "").lower())
    return "short script" in normalized or normalized.strip() == "a short script"


def _is_approval_like_followup(message: str) -> bool:
    normalized = _normalize_brief_text(message)
    if not normalized:
        return False
    direct = {
        "yes",
        "yes please",
        "please",
        "sure",
        "okay",
        "ok",
        "go ahead",
        "do it",
        "proceed",
        "sounds good",
        "looks good",
        "perfect",
        "absolutely",
        "yesss",
    }
    if (
        normalized in direct
        or normalized.startswith(("yes ", "sure ", "ok ", "okay ", "go ahead", "do it", "proceed"))
    ):
        return True
    label, score = _best_intent_label(message, ("praise", "reflective_acknowledgment"))
    return label == "praise" and score >= 0.88 and normalized in {"sounds good", "perfect"}


def _is_reflective_followup(message: str) -> bool:
    normalized = _normalize_brief_text(message)
    markers = (
        "would help me",
        "helps me",
        "i could keep this",
        "keep this on a post it",
        "post it",
        "i like that",
        "that works",
        "that helps",
        "i can use that",
        "i'm going to use this",
        "im going to use this",
        "i ll use this",
        "i'll use this",
        "i'll write this down",
        "ill write this down",
        "this makes sense",
    )
    if any(marker in normalized for marker in markers):
        return True
    if len(normalized) < 8:
        return False
    if not any(token in normalized for token in ("use", "write", "sense", "help", "post", "works")):
        return False
    label, score = _best_intent_label(message, ("reflective_acknowledgment",))
    return label == "reflective_acknowledgment" and score >= 0.82


def _contains_content_request_marker(message: str) -> bool:
    normalized = _normalize_brief_text(message)
    request_markers = (
        "script",
        "scripting",
        "affirmation",
        "affirmations",
        "reset",
        "story",
        "meditation",
        "breathing",
        "daily set",
        "rewrite",
        "shorter",
        "short script",
        "first person",
        "more powerful",
    )
    return any(marker in normalized for marker in request_markers)


def _is_praise_response(message: str) -> bool:
    normalized = _normalize_brief_text(message)
    if _contains_content_request_marker(message):
        return False
    if len(normalized.split()) > 6:
        return False
    markers = (
        "thank you",
        "thanks",
        "love that",
        "perfect",
        "this is great",
        "this is perfect",
        "this is good",
        "that works",
        "so good",
        "exactly",
        "nice",
        "i love that",
    )
    if normalized in markers or any(normalized.startswith(marker + " ") for marker in ("thank you", "thanks")):
        return True
    label, score = _best_intent_label(message, ("praise",))
    return label == "praise" and score >= 0.84


_CONTENT_STOPWORDS = {
    "script",
    "short script",
    "shorter",
    "shorter script",
    "affirmations",
    "a few affirmations",
    "reset",
    "2-minute reset",
    "meditation",
    "breathing",
    "daily set",
    "that didn't hit",
    "that didnt hit",
    "that sounded robotic",
    "in first person",
    "more powerful",
    "cleaner",
    "simpler",
    "better",
    "rewrite it",
}


def _normalize_topic_for_content(topic: str | None, fallback: str) -> str:
    cleaned = re.sub(r"\s+", " ", (topic or "").strip().lower())
    if not cleaned:
        return fallback
    if cleaned in _CONTENT_STOPWORDS:
        return fallback
    blocked_fragments = [
        "that didn't hit",
        "that didnt hit",
        "that sounded robotic",
        "give me a",
        "actually wait",
        "transfer ",
        "deposit ",
        "withdraw ",
        "rename ",
        "archive ",
        "restore ",
        "change currency",
        "shorter",
        "more powerful",
        "in first person",
        "rewrite",
    ]
    if any(fragment in cleaned for fragment in blocked_fragments):
        return fallback
    cleaned = re.sub(r"^(help me|can you|please|now|actually|ugh)\s+", "", cleaned).strip()
    if not cleaned:
        return fallback
    return cleaned


def _title_case_topic(topic: str) -> str:
    return " ".join(word.capitalize() for word in topic.split())


def _canonical_content_topic(topic: str | None) -> str:
    normalized = _normalize_topic_for_content(topic, "more money")
    if any(phrase in normalized for phrase in ("calm", "peace", "grounded", "regulation", "regulated")):
        return "calm"
    if any(phrase in normalized for phrase in ("confidence", "confident", "self trust", "self-trust")):
        return "confidence"
    if any(phrase in normalized for phrase in ("focus", "clarity", "concentration")):
        return "focus"
    if any(phrase in normalized for phrase in ("wealth identity",)):
        return "wealth identity"
    if any(phrase in normalized for phrase in ("new paying signature members", "signature member", "signature members", "paying signature member", "paying members", "member sign ups", "member signups")):
        return "new paying signature members"
    if any(phrase in normalized for phrase in ("new opportunities", "opportunities", "opportunity")):
        return "new opportunities"
    if any(phrase in normalized for phrase in ("more money", "money", "income", "wealth", "abundance", "receiving")):
        return "more money"
    return normalized or "more money"


def _micro_intent_for_topic(topic: str | None) -> str:
    normalized = _normalize_topic_for_content(topic, "more money")
    if any(term in normalized for term in ("calm", "peace", "grounded", "regulation")):
        return "calm"
    if any(term in normalized for term in ("confidence", "self trust", "trust")):
        return "confidence"
    if any(term in normalized for term in ("focus", "clarity", "concentration")):
        return "focus"
    if any(term in normalized for term in ("income growth", "income", "revenue", "sales", "more money")):
        return "income_growth"
    if any(term in normalized for term in ("conversion", "sign ups", "signups", "members", "commit")):
        return "conversion"
    if any(term in normalized for term in ("standards", "standard", "identity")):
        return "standards"
    if any(term in normalized for term in ("discernment", "discern", "opportunities", "opportunity")):
        return "discernment"
    return "default"


def _stable_variant_index(*parts: str, size: int) -> int:
    seed = "|".join(parts).encode("utf-8")
    digest = hashlib.sha256(seed).hexdigest()
    return int(digest[:8], 16) % max(1, size)


def _generated_script_variants(topic: str, flavor: str) -> list[list[str]]:
    banks: dict[str, dict[str, list[str]]] = {
        "more money": {
            "lead": [
                "I treat income like something I shape through decisions.",
                "I move my income by handling the paid step directly.",
                "I expect more money to follow stronger execution.",
                "I build revenue through standards, not hesitation.",
                "I support higher income with cleaner decisions.",
            ],
            "middle": [
                "I price clearly and stop hiding the ask.",
                "I follow up before demand cools off.",
                "I finish proposals, sales conversations, and open loops while they still matter.",
                "I keep the offer simple enough for the right person to say yes.",
                "I spend more time on the work that leads to payment.",
            ],
            "close": [
                "I let income rise because I keep acting where it counts.",
                "I let better numbers come from sharper follow-through.",
                "I let stronger earnings come from decisions I can point to.",
                "I let revenue change because my behavior changes first.",
                "I let consistency do the work pressure never could.",
            ],
        },
        "new opportunities": {
            "lead": [
                "I notice opportunities that deserve a serious response.",
                "I treat good openings like they are worth moving on now.",
                "I recognize the difference between noise and a real opportunity.",
                "I move toward opportunities that can change my position.",
                "I keep my attention on openings that are actually alive.",
            ],
            "middle": [
                "I respond before hesitation turns into delay.",
                "I choose faster when something fits and release what does not.",
                "I answer worthwhile introductions, roles, and invitations while they are current.",
                "I stop spending energy on paths with no real next step.",
                "I trust my judgment enough to move while the chance is still open.",
            ],
            "close": [
                "I let better opportunities meet someone who actually responds.",
                "I let follow-through shape what opens next.",
                "I let timing and discernment do their work together.",
                "I let clearer choices make me easier to trust.",
                "I let action keep the opportunity alive long enough to matter.",
            ],
        },
        "wealth identity": {
            "lead": [
                "I act like someone who can hold more without shrinking.",
                "I build the habits that fit a larger life.",
                "I make decisions from the version of me that expects more.",
                "I trust myself with more visibility, money, and responsibility.",
                "I let my identity catch up to the level I am building.",
            ],
            "middle": [
                "I stop negotiating my standards down to stay comfortable.",
                "I choose cleaner boundaries, stronger pricing, and steadier follow-through.",
                "I let self-respect show up in how I decide and how I move.",
                "I hold the level I want instead of performing it occasionally.",
                "I repeat the choices that make expansion feel normal.",
            ],
            "close": [
                "I let my daily decisions prove what I am ready to hold.",
                "I let consistency make the next level believable.",
                "I let standards make growth easier to sustain.",
                "I let repetition turn expansion into something ordinary.",
                "I let my choices match the life I keep asking for.",
            ],
        },
        "new paying signature members": {
            "lead": [
                "I speak to the right members with enough precision that they can decide.",
                "I make my offer easier for premium clients to trust.",
                "I hold the standard of the offer without watering it down.",
                "I present the invitation clearly enough for the right member to say yes.",
                "I make commitment feel cleaner for the people this was built for.",
            ],
            "middle": [
                "I show the result, the fit, and the next step without unnecessary noise.",
                "I support conversion through stronger proof and cleaner framing.",
                "I make the path to joining easier to understand and easier to trust.",
                "I speak with enough authority that the right member can move quickly.",
                "I remove friction from the offer instead of adding more explanation.",
            ],
            "close": [
                "I let stronger signups come from better conversion, not more chasing.",
                "I let paid membership grow because the offer lands more cleanly.",
                "I let premium clients recognize themselves in the invitation faster.",
                "I let stronger enrollment follow stronger positioning.",
                "I let clarity do more of the selling for me.",
            ],
        },
        "general": {
            "lead": [
                "I move the thing that changes the outcome.",
                "I act before doubt turns the step into a debate.",
                "I work from decision instead of drift.",
                "I keep my focus on the move that matters most.",
                "I stop postponing the useful next step.",
            ],
            "middle": [
                "I give my attention to the work that deserves it.",
                "I follow through before friction grows into avoidance.",
                "I finish the part that would actually make the difference.",
                "I keep action simpler than overthinking wants it to be.",
                "I stay with the task long enough for it to move.",
            ],
            "close": [
                "I let progress come from completion, not just intention.",
                "I let consistency carry more weight than mood.",
                "I let action simplify what hesitation was complicating.",
                "I let repetition turn a good choice into a pattern.",
                "I let follow-through do the convincing.",
            ],
        },
    }
    bank = banks.get(topic, banks["general"])
    generated: list[list[str]] = []
    for idx in range(8):
        lead = bank["lead"][_stable_variant_index(topic, flavor, "lead", str(idx), size=len(bank["lead"]))]
        middle = bank["middle"][_stable_variant_index(topic, flavor, "middle", str(idx), size=len(bank["middle"]))]
        close = bank["close"][_stable_variant_index(topic, flavor, "close", str(idx), size=len(bank["close"]))]
        generated.append([lead, middle, close])
    return generated


def _generated_affirmation_variants(topic: str, flavor: str) -> list[list[str]]:
    banks: dict[str, dict[str, list[str]]] = {
        "more money": {
            "line_a": [
                "I back my income with clearer decisions.",
                "I let my work be paid at the level it deserves.",
                "I treat revenue like something I can influence directly.",
                "I make cleaner asks around money.",
            ],
            "line_b": [
                "I follow through while buying interest is still active.",
                "I keep the offer, the ask, and the close simple.",
                "I move faster on the work that leads to payment.",
                "I stop delaying the part that changes the number.",
            ],
            "line_c": [
                "I let better earnings come from steadier execution.",
                "I let stronger income follow stronger standards.",
                "I let consistency raise what pressure never could.",
                "I let money respond to the quality of my follow-through.",
            ],
            "line_d": [
                "I trust stronger habits more than last-minute pressure.",
                "I stay available for paid work by acting sooner and more clearly.",
                "I let good decisions make income easier to receive.",
                "I support better numbers with steadier follow-through.",
            ],
        },
        "general": {
            "line_a": [
                "I make cleaner decisions.",
                "I move sooner on what matters.",
                "I follow through with more steadiness.",
                "I keep my attention where it changes outcomes.",
            ],
            "line_b": [
                "I stop turning the next step into a negotiation.",
                "I trust action more than delay.",
                "I let repetition build trust in myself.",
                "I keep the useful move simple enough to do now.",
            ],
            "line_c": [
                "I let progress come from consistency.",
                "I let better results follow better standards.",
                "I let discipline carry more weight than mood.",
                "I let my choices show me who I am becoming.",
            ],
            "line_d": [
                "I stay with the useful move long enough for it to work.",
                "I let steadier effort build trust in myself.",
                "I keep the next step small enough to do and important enough to matter.",
                "I let consistency simplify what stress was complicating.",
            ],
        },
    }
    bank = banks.get(topic, banks["general"])
    generated: list[list[str]] = []
    for idx in range(6):
        generated.append(
            [
                bank["line_a"][_stable_variant_index(topic, flavor, "affirm_a", str(idx), size=len(bank["line_a"]))],
                bank["line_b"][_stable_variant_index(topic, flavor, "affirm_b", str(idx), size=len(bank["line_b"]))],
                bank["line_c"][_stable_variant_index(topic, flavor, "affirm_c", str(idx), size=len(bank["line_c"]))],
                bank["line_d"][_stable_variant_index(topic, flavor, "affirm_d", str(idx), size=len(bank["line_d"]))],
            ]
        )
    return generated


def _script_lines_for_topic(
    topic: str,
    *,
    perspective: str = "first_person",
    tone: str = "steady",
    history: list[dict[str, str]] | None = None,
    variant_hint: str = "",
) -> list[str]:
    topic = _canonical_content_topic(topic)
    flavor = _micro_intent_for_topic(topic)
    first_person = perspective != "second_person"
    variants: dict[str, list[list[str]]] = {
        "more money": [
            [
                "I make decisions that raise my income instead of delaying it.",
                "I price my work with more honesty and follow up while demand is still warm.",
                "I let stronger earnings come from better offers and cleaner execution.",
            ],
            [
                "I stop circling the same money goal and put it into motion.",
                "I answer interest quickly, ask for the sale, and finish what leads to payment.",
                "I build higher income through timing, pricing, and follow-through.",
            ],
            [
                "I treat income growth like something I manage on purpose.",
                "I put real weight behind the offers, conversations, and decisions that change revenue.",
                "I let disciplined follow-through produce the increase I have been asking for.",
            ],
            [
                "I stop waiting for income to rise on its own.",
                "I make the ask, send the follow-up, and close the open loop while it still matters.",
                "I let stronger earnings come from decisions I can point to.",
            ],
            [
                "I build more money through better pricing and cleaner timing.",
                "I answer buying signals before they cool off.",
                "I keep moving the work that leads directly to payment.",
            ],
            [
                "I support higher income with direct offers and fewer delays.",
                "I make it easier for the right client to say yes.",
                "I let my numbers change because my standards do.",
            ],
            [
                "I trust myself with the decisions that increase revenue.",
                "I stop diluting the offer, the price, or the follow-through.",
                "I let income grow because I keep handling the work behind it.",
            ],
            [
                "I stop hiding behind preparation when a direct ask would move the number.",
                "I follow through on pricing, proposals, and sales conversations while they are still active.",
                "I let stronger income come from better execution, not more wishing.",
            ],
            [
                "I protect the work that leads to payment.",
                "I respond faster, ask more directly, and finish the loop instead of leaving money half-open.",
                "I let discipline do the part motivation never could.",
            ],
            [
                "I treat revenue like something shaped by standards.",
                "I make cleaner offers, hold the price, and stay present through the close.",
                "I let higher income follow the quality of my decisions.",
            ],
            [
                "I move the conversations that lead to money.",
                "I stop delaying the send, the ask, or the follow-up that would make the difference.",
                "I let income rise because I keep acting where it counts.",
            ],
            [
                "I back my value with clearer pricing and cleaner follow-through.",
                "I stop overexplaining and make it easier for the right person to say yes.",
                "I let stronger earnings come from precision, not pressure.",
            ],
            [
                "I trust myself to handle the decisions that increase income.",
                "I close loops, send the offer, and stop postponing the paid move.",
                "I let my numbers change because my behavior changes first.",
            ],
        ],
        "new opportunities": [
            [
                "I notice strong openings early and respond while they still matter.",
                "I trust myself to tell the difference between a distraction and a real chance.",
                "I move on the openings that deserve a serious answer.",
            ],
            [
                "I stop waiting for certainty and answer the opportunities that fit.",
                "I choose quickly when something is right and step back when it is not.",
                "I create better outcomes by acting on what is timely, not just exciting.",
            ],
            [
                "I recognize the offers, introductions, and roles that can actually move my life forward.",
                "I respond with judgment instead of urgency.",
                "I let discernment and follow-through shape which opportunities open next.",
            ],
            [
                "I notice the introductions and openings that deserve a real answer.",
                "I move before hesitation talks me out of them.",
                "I let better chances find me responsive, not stalled.",
            ],
            [
                "I stop treating every opening like it deserves equal weight.",
                "I respond quickly to the ones that can actually change my position.",
                "I let discernment sharpen what I say yes to next.",
            ],
            [
                "I handle promising opportunities while they are still current.",
                "I trust my judgment enough to choose without dragging it out.",
                "I let timely action change what becomes available to me.",
            ],
            [
                "I give serious opportunities a serious response.",
                "I stop wasting time on what has no real path forward.",
                "I let follow-through make me easier to choose.",
            ],
            [
                "I answer worthwhile openings before they turn cold.",
                "I stop confusing indecision with discernment.",
                "I let better opportunities meet someone who actually responds.",
            ],
            [
                "I notice which introductions and roles deserve my time.",
                "I move with enough speed to keep the chance alive.",
                "I let judgment and follow-through shape what opens next.",
            ],
            [
                "I stop treating hesitation like wisdom.",
                "I respond to the chances that fit and release the ones that do not.",
                "I let better opportunities build around cleaner choices.",
            ],
        ],
        "wealth identity": [
            [
                "I think like someone who can hold more responsibility, income, and visibility without shrinking.",
                "I raise my standards where I used to negotiate them down.",
                "I let my decisions match the level I say I want.",
            ],
            [
                "I act like someone who expects to handle bigger numbers well.",
                "I stop making small choices that keep me in the same identity.",
                "I let better self-respect show up in pricing, boundaries, and follow-through.",
            ],
            [
                "I build the habits that make larger results feel normal.",
                "I choose standards that support expansion instead of apologizing for it.",
                "I make my next level believable through repeated decisions.",
            ],
            [
                "I stop acting from the version of me that expects less.",
                "I choose standards that fit the life I say I want.",
                "I let self-respect show up in my money decisions.",
            ],
            [
                "I carry more responsibility without making it mean I have to contract.",
                "I hold firmer boundaries, stronger pricing, and cleaner decisions.",
                "I let my identity catch up to the level I am building toward.",
            ],
            [
                "I behave like someone who can sustain larger results.",
                "I stop undercutting myself when the next level asks more of me.",
                "I let repetition make expansion feel normal.",
            ],
            [
                "I trust myself with more income, more exposure, and more responsibility.",
                "I stop negotiating my standards down to stay comfortable.",
                "I let my choices prove what I am ready to hold.",
            ],
            [
                "I stop making decisions from the version of me that still expects less.",
                "I hold firmer standards around money, time, and self-respect.",
                "I let expansion feel normal by repeating the right choices.",
            ],
            [
                "I build the habits that support a larger life.",
                "I price, decide, and follow through like someone who can sustain more.",
                "I let identity shift through evidence, not performance.",
            ],
            [
                "I trust myself to hold more without becoming chaotic.",
                "I choose standards that make a bigger life easier to maintain.",
                "I let my next level become visible in my daily decisions.",
            ],
        ],
        "new paying signature members": [
            [
                "The right people understand the value of what I built and decide to join.",
                "I present my offer with enough precision that the right members can say yes quickly.",
                "I grow by making the conversion path clearer and the promise stronger.",
            ],
            [
                "I attract paying members who are ready for a premium level of support.",
                "I explain the result clearly, hold the price cleanly, and make commitment easier.",
                "I let stronger enrollment come from trust, positioning, and direct invitation.",
            ],
            [
                "My best-fit members recognize themselves in the offer and move toward it.",
                "I make the decision to join feel obvious through proof, clarity, and strong framing.",
                "I build membership growth through conversion, not noise.",
            ],
            [
                "The right members understand the result and choose it without confusion.",
                "I speak to their needs directly and make the next step simple.",
                "I let stronger enrollment come from better conversion, not more chasing.",
            ],
            [
                "I attract paying members who are ready for this level of support.",
                "I make the offer specific enough that commitment feels natural.",
                "I let signups rise because the message and promise are tighter.",
            ],
            [
                "My offer earns commitment from the people it was built for.",
                "I hold premium positioning without softening the value.",
                "I let stronger conversions come from proof, precision, and timing.",
            ],
            [
                "I make it easy for the right members to see why this is worth paying for.",
                "I present the invitation with authority and less unnecessary explanation.",
                "I let paying signups grow because the offer is easier to trust.",
            ],
            [
                "I speak to premium clients with enough clarity that they can decide quickly.",
                "I remove friction from the invitation and strengthen the reason to commit.",
                "I let better signups come from stronger conversion, not louder marketing.",
            ],
            [
                "I hold the standard of the offer instead of watering it down for approval.",
                "I make the result, the fit, and the next step easy to understand.",
                "I let member growth come from cleaner positioning and better trust.",
            ],
            [
                "I guide the right members toward a clear yes.",
                "I make commitment easier through proof, authority, and stronger framing.",
                "I let premium conversions rise because the offer lands more cleanly.",
            ],
        ],
        "general": [
            [
                "I make cleaner decisions and follow through faster.",
                "I give more attention to the actions that change outcomes.",
                "I let consistency, timing, and discipline do their work.",
            ],
            [
                "I stop scattering my attention and move the important thing forward.",
                "I trust direct action more than endless preparation.",
                "I build progress by finishing what matters.",
            ],
            [
                "I move the thing that changes the outcome instead of circling it.",
                "I follow through before doubt gets to renegotiate the plan.",
                "I let progress come from completion, not just intention.",
            ],
            [
                "I stop delaying the step that would make the difference.",
                "I give my focus to the work that deserves it.",
                "I let better days come from sharper follow-through.",
            ],
            [
                "I work from decision instead of drift.",
                "I keep my attention on the move that actually matters.",
                "I let action simplify what overthinking was complicating.",
            ],
            [
                "I choose the useful next step and do it while it is still simple.",
                "I stop letting friction turn into avoidance.",
                "I let consistency carry more weight than emotion.",
            ],
        ],
    }
    variant_pool = variants.get(topic, variants["general"]) + _generated_script_variants(topic, flavor)
    index = _select_recent_safe_variant_index(
        variant_pool,
        topic=topic,
        flavor=flavor,
        artifact="script",
        history=history,
        hint=f"{tone}|{variant_hint}",
    )
    lines = variant_pool[index]
    if tone == "stronger":
        if topic == "more money":
            stronger_variants = [
                [
                    "I expect better pay when my work solves an expensive problem.",
                    "I stop softening my asks and back my numbers with stronger decisions.",
                    "I let higher income come from sharper offers and firmer follow-through.",
                ],
                [
                    "I raise my income by making the direct move instead of the comfortable one.",
                    "I hold my price, close open loops, and keep the offer clear.",
                    "I let stronger earnings come from sharper execution.",
                ],
                [
                    "I trust myself with bigger numbers because I support them with better decisions.",
                    "I answer buying signals faster and stop watering down the ask.",
                    "I let income rise because I handle the work that earns it.",
                ],
            ]
            lines = stronger_variants[
                _select_recent_safe_variant_index(
                    stronger_variants,
                    topic=topic,
                    flavor=flavor,
                    artifact="script",
                    history=history,
                    hint=f"stronger|{variant_hint}",
                )
            ]
        elif topic == "new opportunities":
            stronger_variants = [
                [
                    "I answer the openings that can change my position and ignore the rest.",
                    "I trust my judgment fast enough to act while the window is still open.",
                    "I let better opportunities find me ready, not hesitant.",
                ],
                [
                    "I move quickly on opportunities that deserve a serious answer.",
                    "I stop letting hesitation talk me out of timely decisions.",
                    "I let stronger openings meet a more decisive version of me.",
                ],
            ]
            lines = stronger_variants[
                _select_recent_safe_variant_index(
                    stronger_variants,
                    topic=topic,
                    flavor=flavor,
                    artifact="script",
                    history=history,
                    hint=f"stronger|{variant_hint}",
                )
            ]
    if not first_person:
        lines = [
            line.replace("I ", "You ", 1).replace(" my ", " your ").replace(" me ", " you ")
            for line in lines
        ]
    return lines


def _affirmation_lines_for_topic(
    topic: str,
    *,
    stronger: bool = False,
    shorter: bool = False,
    history: list[dict[str, str]] | None = None,
    variant_hint: str = "",
) -> list[str]:
    topic = _canonical_content_topic(topic)
    flavor = _micro_intent_for_topic(topic)
    variants: dict[str, list[list[str]]] = {
        "calm": [
            [
                "I can feel calm without losing momentum.",
                "My body does not need urgency to make a clear decision.",
                "I let steadiness lead this moment.",
                "I return to myself before I respond.",
            ],
            [
                "I can slow down and still move well.",
                "Calm helps me see what actually matters.",
                "I release pressure that does not belong to this moment.",
                "I trust grounded decisions more than rushed ones.",
            ],
        ],
        "confidence": [
            [
                "I trust myself to handle what is in front of me.",
                "My voice gets clearer when I stop shrinking it.",
                "I back my decisions with steadier follow-through.",
                "Confidence grows as I keep showing up cleanly.",
            ],
            [
                "I do not need to overprove my value.",
                "I can take up space without apologizing for it.",
                "I trust what I know and move on it directly.",
                "My confidence gets stronger through repetition.",
            ],
        ],
        "focus": [
            [
                "I give my attention to the task that changes the result.",
                "I can return to the important thing without drama.",
                "Focus becomes easier when I remove what scatters me.",
                "I let one clear step lead the next one.",
            ],
            [
                "I stay with what matters long enough for it to move.",
                "I do not need ten priorities at once.",
                "I let clarity simplify my next decision.",
                "My attention works best when I keep it deliberate.",
            ],
        ],
        "more money": [
            [
                "I receive money through offers people are ready to buy.",
                "I make choices that increase revenue instead of postponing it.",
                "I follow up while interest is still active.",
                "I can grow my income without scrambling.",
            ],
            [
                "I let better pay match the value I already provide.",
                "I notice demand and answer it with more precision.",
                "I stop hesitating around the actions that lead to payment.",
                "I trust consistency more than pressure.",
            ],
            [
                "I make income growth a result of stronger decisions.",
                "I ask clearly, price cleanly, and follow through.",
                "I respond to paying opportunities while they are still live.",
                "I let better results come from better execution.",
            ],
        ],
        "new paying signature members": [
            [
                "The right members recognize the value of my offer and commit.",
                "I make the invitation clear enough for premium clients to say yes.",
                "I support conversion with strong positioning and a cleaner message.",
                "I am available for steadier, higher-quality signups.",
            ],
            [
                "My offer speaks clearly to the people it was built for.",
                "I attract members who are ready to invest and participate fully.",
                "I make enrollment easier through proof, clarity, and timing.",
                "I let membership growth come from stronger conversion, not more noise.",
            ],
        ],
        "wealth identity": [
            [
                "I make decisions that fit the level I want to live at.",
                "I stop shrinking around bigger numbers and bigger responsibility.",
                "I raise my standards without apologizing for them.",
                "I trust myself to sustain what I build.",
            ],
            [
                "I behave like someone who can hold more without losing balance.",
                "I let self-respect show up in my pricing, boundaries, and follow-through.",
                "I stop choosing from the version of me that expects less.",
                "I make expansion feel normal through repetition.",
            ],
        ],
        "new opportunities": [
            [
                "I recognize strong openings and answer them while they are still available.",
                "I trust myself to tell the difference between noise and direction.",
                "I move on what fits instead of chasing everything.",
                "I let better opportunities meet a more prepared version of me.",
            ],
            [
                "I notice the conversations, roles, and introductions that deserve my attention.",
                "I act before hesitation talks me out of what matters.",
                "I choose with discernment and follow through with speed.",
                "I let the right openings find me ready.",
            ],
        ],
        "general": [
            [
                "I make sharper decisions and follow through on them.",
                "I stop delaying the work that changes outcomes.",
                "I trust steady execution over empty intensity.",
                "I let discipline produce what wishful thinking cannot.",
            ]
        ],
    }
    variant_pool = variants.get(topic, variants["general"]) + _generated_affirmation_variants(topic, flavor)
    lines = variant_pool[
        _select_recent_safe_variant_index(
            variant_pool,
            topic=topic,
            flavor=flavor,
            artifact="affirmations",
            history=history,
            hint=f"{'stronger' if stronger else 'base'}|{variant_hint}",
        )
    ]
    if stronger:
        if topic == "more money":
            lines = [
                "I expect higher income when I make stronger offers and back them clearly.",
                "I trust myself with larger numbers because I handle the work behind them.",
                "I ask more directly, decide faster, and follow through further.",
                "I do not need pressure to perform well.",
            ]
        elif topic == "new paying signature members":
            lines = [
                "My offer earns commitment from the members it was built for.",
                "I hold premium positioning without watering down the invitation.",
                "I support stronger conversions through trust, proof, and clear demand.",
                "I am fully available for steady, well-matched paid signups.",
            ]
        else:
            lines = [
                "I trust myself with bigger decisions and cleaner execution.",
                "I move sooner on the choices that raise the ceiling.",
                "I expect stronger outcomes because I support them with better standards.",
                "I do not wait for ideal conditions to move well.",
            ]
    if shorter:
        if topic == "more money":
            lines = [
                "I make decisions that raise my income.",
                "I follow through while demand is still live.",
            ]
        elif topic == "new paying signature members":
            lines = [
                "The right members recognize the offer and commit.",
                "I make conversion easier through stronger clarity.",
            ]
        else:
            lines = lines[:2]
    return lines


def _reset_steps_for_topic(
    topic: str,
    *,
    history: list[dict[str, str]] | None = None,
    variant_hint: str = "",
) -> list[str]:
    topic = _canonical_content_topic(topic)
    variants: dict[str, list[list[str]]] = {
        "more money": [
            [
                "Breathe in for four and out for six until your body stops bracing for a problem.",
                "Name the one money task that would most improve revenue, pricing, or follow-up this week.",
                "Do the smallest useful version of that task before you start negotiating with yourself.",
            ],
            [
                "Lengthen your exhale until the urgency in your body eases.",
                "Pick the one sales, pricing, or follow-up move that would actually move your numbers.",
                "Handle the first useful piece of it now instead of waiting to feel perfectly ready.",
            ],
        ],
        "new opportunities": [
            [
                "Slow your breathing until urgency is no longer making the decision for you.",
                "Choose the one opening that is current, concrete, and worth a serious answer.",
                "Make the next move before the window closes.",
            ],
            [
                "Breathe until your attention is back in your body instead of racing ahead.",
                "Identify the one introduction, role, or invitation that deserves a real response.",
                "Send the message or take the step before doubt expands again.",
            ],
        ],
        "general": [
            [
                "Inhale for four and exhale for six a few times.",
                "Let your jaw, shoulders, and hands loosen so your thinking can sharpen.",
                "Pick one useful next step and start before you can overcomplicate it.",
            ],
            [
                "Take three slower breaths than your body wants to take.",
                "Drop the tension in your shoulders so your thinking gets cleaner.",
                "Choose one small action that moves the situation forward and start there.",
            ],
        ],
    }
    variant_pool = variants.get(topic, variants["general"])
    return variant_pool[
        _select_recent_safe_variant_index(
            variant_pool,
            topic=topic,
            flavor="reset",
            artifact="reset",
            history=history,
            hint=variant_hint,
        )
    ]


def _build_manifestation_story(
    topic: str | None = None,
    *,
    history: list[dict[str, str]] | None = None,
    variant_hint: str = "",
) -> str:
    topic_name = _canonical_content_topic(topic)
    variants: dict[str, list[str]] = {
        "more money": [
            "Nina wanted more money, but her week kept disappearing into half-finished offers and polite follow-ups that went nowhere.\n\nShe stopped asking for a breakthrough and looked at the part she could actually control. She rewrote her main offer in plain language, raised the price to match the result, and followed up with every warm lead within twenty-four hours.\n\nThe shift was not emotional at first. It was operational. People understood faster what she was selling, who it was for, and why it cost what it did. That changed the quality of the replies she got.\n\nWithin a few weeks, one paused lead came back, one referral became a paid project, and the offer she had cleaned up started converting more consistently. The money changed after her decisions did.",
            "Jordan kept saying he needed more money, but he was still quoting prices that left no room for the level of work he was doing.\n\nHe spent one weekend tightening the offer, raising the rate, and preparing a cleaner explanation for why the work was worth more. Then he sent it to the three clients who had been sitting in maybe.\n\nTwo said no. One said yes within a day. That one yes was enough to prove that the old price had been protecting his comfort, not his income.\n\nBy the end of the month, he had fewer conversations, better clients, and more money coming in from work that actually matched the result.",
            "Alicia wanted her income to rise, but every sales conversation ended the same way: too much explanation, no clear ask, and a weak close.\n\nShe decided to change one part of the pattern. She wrote a shorter offer, started naming the price earlier, and followed up while interest was still fresh instead of three days later.\n\nThe work did not suddenly become easier. She just stopped disappearing at the point where money usually gets decided.\n\nWithin a few weeks, she had closed two offers that would have stalled under her old habits. The shift was simple: she treated revenue like something built through execution.",
            "Marcus had enough demand to make more money, but he kept burying it under slow replies and messy onboarding.\n\nHe blocked out one hour each morning for the tasks that directly affected income: proposals, follow-ups, invoices, and clean handoffs. Everything else waited.\n\nThat one change made him easier to hire and easier to pay. Prospects got clearer answers. Clients moved faster. Fewer opportunities leaked out of the process.\n\nA month later, his revenue was up not because he found a trick, but because he finally protected the work that leads to payment.",
            "Selena wanted more money, but she kept treating sales like the part of the business she would fix later.\n\nShe finally made it the first thing she tightened. She rewrote her offer, clarified the outcome, and started asking for the decision before the conversation drifted into maybe.\n\nThat changed the entire tone of her week. Fewer leads lingered. More conversations moved. She stopped leaking time into people who were never going to buy.\n\nWithin a month, her revenue was steadier because she had stopped treating the close like an optional step.",
            "Noah wanted his income to grow, but he was still taking too long to send the proposal after someone showed interest.\n\nHe changed one rule: every serious inquiry got a clear next step within the same day. No polishing loop. No waiting for the perfect draft.\n\nThat speed changed how people responded to him. He felt more certain, and they felt more confident moving with him.\n\nBy the end of the quarter, the difference in income came less from effort and more from the fact that he stopped leaving warm opportunities unattended.",
            "Priya wanted more money, but she was still pricing from fear of losing the client.\n\nShe raised her rates, tightened how she described the result, and stopped offering discounts before anyone had even objected.\n\nThe first few conversations were uncomfortable. Then they got cleaner. The right clients stopped hesitating because the offer sounded more certain.\n\nA few months later, she was making more from fewer projects because her pricing finally matched the standard of the work.",
        ],
        "new opportunities": [
            "Maya said she wanted new opportunities, but most days she was buried in reactive work and vague conversations that never turned into anything solid.\n\nShe changed two things. She followed up within a day instead of waiting for the perfect wording, and she stopped spending time on calls that had no path to work, pay, or a real next step.\n\nThat made her easier to trust. People got quicker answers, clearer positioning, and more confidence that she could actually deliver.\n\nWithin a few weeks, one introduction became a paid project and another became the role she had been trying to reach for months. The opportunity was not random. She had become easier to hire.",
            "Tessa wanted a better role, but she kept treating every lead with the same level of energy, even when half of them were dead ends.\n\nShe started qualifying faster. If a conversation had no budget, no timeline, or no path forward, she stopped feeding it. The time she got back went into the openings that actually fit.\n\nThat sharpened everything. Her answers were better. Her follow-up was faster. Her confidence stopped leaking through indecision.\n\nA few weeks later, one serious conversation turned into a contract role that paid more and opened the exact network she had been trying to reach.",
            "Andre kept saying he wanted better opportunities, but his inbox was full of introductions he had never answered.\n\nHe set a rule: respond to every meaningful lead within twenty-four hours, even if the answer was a no. That one rule changed how people experienced him.\n\nHe sounded more decisive, more prepared, and more serious. The work did not come from chasing harder. It came from becoming someone other people could move with.\n\nWithin a month, one old lead reopened, one referral turned into a meeting, and one meeting turned into paid work he would have missed under his old pace.",
            "Leah wanted more doors to open, but she was still hiding behind too much preparation and not enough visible action.\n\nShe picked one change: publish one strong example of her work each week and message the people who would actually understand it. No grand strategy. Just a cleaner signal sent consistently.\n\nThe result was gradual, then obvious. More people replied. Better conversations started. The opportunities became more specific.\n\nWhat changed was not luck. She made herself easier to notice and easier to trust at the same time.",
            "Owen wanted better opportunities, but he kept missing them because he answered too late and overthought the reply.\n\nHe started using one simple rule: answer fast, then refine if needed. That made him more responsive without making him careless.\n\nPeople started looping him into better conversations because he no longer felt slippery or hard to place.\n\nWeeks later, one of those faster replies became the introduction that changed the kind of work he was being considered for.",
            "Bianca said she wanted more opportunity, but her calendar was full of activity that never led anywhere.\n\nShe reviewed every recurring commitment and cut the ones that produced no real work, no money, and no relationship worth building. The space she got back went into outreach and faster follow-up.\n\nThat made her easier to trust and easier to remember. The opportunities that came in were fewer, but stronger.\n\nWithin a couple of months, she had two better clients and one opening that had been invisible when her time was still scattered.",
            "Eli wanted a bigger opportunity, but he was still speaking about his work in a vague way that made people unsure where to place him.\n\nHe tightened his positioning, updated two work samples, and started answering introductions with a clearer description of what he actually solved.\n\nThat changed the quality of the conversations almost immediately. The right people understood him faster, and the wrong ones filtered themselves out.\n\nThe next role he landed was not luck. It was the result of finally making his value easier to recognize.",
        ],
        "general": [
            "Evan wanted a different life, but he kept treating the future like something that would arrive once he felt more certain.\n\nHe picked one place to prove himself wrong: the first hour of his morning. Instead of scrolling and reacting, he used it to work on the project he said mattered most.\n\nThat one change did more than improve his schedule. He began trusting his own direction because he had daily evidence that he could move before he felt completely ready.\n\nA few months later, the life he wanted no longer felt distant. It looked like the result of repeated days shaped on purpose.",
            "Camila talked about wanting more from life, but her days still belonged to habit, distraction, and the easiest task in front of her.\n\nShe changed her standards in one small place first. Before checking anything else each morning, she did the task that would still matter by the end of the week.\n\nAt first it felt ordinary. Then it started changing how she saw herself. She was no longer waiting for confidence before acting; she was building confidence by acting.\n\nMonths later, the shift looked bigger from the outside, but it came from a simple decision repeated long enough to become a life.",
            "Darius wanted a different outcome, but he kept mistaking thought for movement.\n\nHe chose one concrete experiment: fewer plans, more visible proof. He finished the pitch, sent the email, and let the response tell him what to improve next.\n\nThat changed his energy immediately. He was no longer arguing with himself in circles. He was getting information from reality.\n\nA season later, the progress he wanted had finally become tangible because he stopped protecting himself from the work that could produce it.",
            "Rhea said she wanted her dreams to feel real, but she was still organizing her life around convenience instead of intention.\n\nShe rewrote her week around one rule: make room for the work that changes things before the work that only maintains them. It was not glamorous, but it was honest.\n\nOnce she did that, her choices got cleaner. Her standards rose. She trusted her own direction more because she could see herself following it.\n\nThe future she had been asking for stopped feeling distant when her days started matching it.",
            "Miles wanted his life to change, but he kept treating discipline like a mood instead of a decision.\n\nHe picked one behavior he could repeat daily no matter what: one uninterrupted block for the work that mattered most. He kept it short enough to keep and serious enough to matter.\n\nThat made him trust himself more. He stopped measuring progress only by big moments and started measuring it by what he could rely on himself to do.\n\nMonths later, the life he wanted looked less like a fantasy and more like the natural result of standards he had finally kept.",
            "Jade wanted a different future, but her routine still belonged to distraction and reaction.\n\nShe changed the order of her day. Before checking anyone else’s priorities, she handled one task tied to her own direction.\n\nThat one boundary changed how she felt about herself. She was no longer waiting to feel more certain before acting; she was making certainty by acting first.\n\nOver time, the future she wanted stopped feeling abstract because her days had started carrying its shape.",
            "Roman wanted more from life, but he kept avoiding the work that would have given him proof he could do it.\n\nHe stopped trying to redesign everything and committed to one honest pattern: finish one meaningful piece each day.\n\nThe result was subtle at first. Then it became visible in his confidence, his standards, and the way he made decisions.\n\nA season later, the difference in his life came less from inspiration and more from the fact that he had become someone who followed through.",
        ],
    }
    variant_pool = variants.get(topic_name, variants["general"])
    selected = variant_pool[
        _select_recent_safe_variant_index(
            variant_pool,
            topic=topic_name,
            flavor="story",
            artifact="story",
            history=history,
            hint=variant_hint,
        )
    ]
    return f"**Story**\n{selected}"


def _extract_previous_script_text(history: list[dict[str, str]] | None = None) -> str:
    prior_assistant = _recent_assistant_context(history)
    if not prior_assistant:
        return ""
    lines = [line.strip() for line in prior_assistant.splitlines() if line.strip()]
    capture = False
    body: list[str] = []
    for line in lines:
        lowered = line.lower()
        if lowered in {"**script**", "script", "**shorter script**", "shorter script"}:
            capture = True
            continue
        if capture:
            if lowered.startswith("if you'd like") or lowered.startswith("would you like"):
                break
            if line.startswith("- ") and body:
                break
            body.append(line)
    if body:
        return " ".join(body).strip()
    for line in lines:
        if line.lower().startswith("i "):
            return line.strip()
    return ""


def _extract_previous_affirmations(history: list[dict[str, str]] | None = None) -> list[str]:
    prior_assistant = _recent_assistant_context(history)
    if not prior_assistant:
        return []
    lines = []
    for line in prior_assistant.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            lines.append(stripped[2:].strip())
    return [line for line in lines if line]


def _extract_previous_reset_steps(history: list[dict[str, str]] | None = None) -> list[str]:
    prior_assistant = _recent_assistant_context(history)
    if not prior_assistant:
        return []
    return [line.strip()[2:].strip() for line in prior_assistant.splitlines() if line.strip().startswith("- ")]


def _extract_script_body(history: list[dict[str, str]] | None = None) -> list[str]:
    previous = _extract_previous_script_text(history)
    if not previous:
        return []
    previous = re.sub(r"^\*\*Script\*\*\s*", "", previous.strip(), flags=re.IGNORECASE)
    return [part.strip(" -•\t") for part in previous.splitlines() if part.strip()]


def _token_overlap_ratio(a: str, b: str) -> float:
    a_tokens = {token for token in re.findall(r"\b[a-z']+\b", (a or "").lower()) if len(token) > 2}
    b_tokens = {token for token in re.findall(r"\b[a-z']+\b", (b or "").lower()) if len(token) > 2}
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / max(1, len(a_tokens | b_tokens))


def _infer_topic_from_text(text: str | None) -> str:
    normalized = (text or "").lower()
    if "connection" in normalized:
        return "new opportunities"
    if any(term in normalized for term in ("signature member", "paying member", "members", "signup", "sign up")):
        return "new paying signature members"
    if "wealth identity" in normalized:
        return "wealth identity"
    if any(term in normalized for term in ("opportunit", "opening", "role", "introduction")):
        return "new opportunities"
    if any(term in normalized for term in ("money", "income", "price", "payment", "offer", "revenue")):
        return "more money"
    return "more money"


def _normalize_variant_text(value: str | list[str]) -> str:
    text = " ".join(value) if isinstance(value, list) else value
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _recent_artifact_bodies(
    history: list[dict[str, str]] | None,
    artifact: str,
    *,
    limit: int = 3,
) -> list[str]:
    if not history:
        return []
    bodies: list[str] = []
    for item in reversed(history):
        if item.get("role") != "assistant":
            continue
        content = item.get("content") or ""
        if _detect_recent_content_artifact([{"role": "assistant", "content": content}]) != artifact:
            continue
        if artifact == "script":
            body = _extract_previous_script_text([{"role": "assistant", "content": content}])
        elif artifact == "affirmations":
            body = " ".join(_extract_previous_affirmations([{"role": "assistant", "content": content}]))
        elif artifact == "story":
            body = content
        elif artifact == "reset":
            body = " ".join(_extract_previous_reset_steps([{"role": "assistant", "content": content}]))
        else:
            body = content
        if body:
            bodies.append(_normalize_variant_text(body))
        if len(bodies) >= limit:
            break
    return bodies


def _select_recent_safe_variant_index(
    options: list[list[str]] | list[str],
    *,
    topic: str,
    flavor: str,
    artifact: str,
    history: list[dict[str, str]] | None = None,
    hint: str = "",
) -> int:
    recent = set(_recent_artifact_bodies(history, artifact, limit=3))
    start = _stable_variant_index(topic, flavor, artifact, hint, str(_content_artifact_count(history, artifact)), size=len(options))
    for offset in range(len(options)):
        idx = (start + offset) % len(options)
        if _normalize_variant_text(options[idx]) not in recent:
            return idx
    return start


def _detect_recent_content_artifact(history: list[dict[str, str]] | None = None) -> str:
    text = _recent_assistant_context(history)
    lowered = text.lower()
    if not lowered:
        return "none"
    if _assistant_recently_offered_rewrite(text):
        return "rewrite_offer"
    if (
        "**script**" in lowered
        or "**shorter script**" in lowered
        or re.search(r"(?m)^(script|shorter script):?\s*$", lowered)
        or "\nscript" in lowered
        or "\nshorter script" in lowered
    ):
        return "script"
    affirmation_bullets = _extract_previous_affirmations([{"role": "assistant", "content": text}])
    if ("affirmation" in lowered and "- " in text) or (
        len(affirmation_bullets) >= 3 and sum(1 for line in affirmation_bullets if line.lower().startswith("i ")) >= 2
    ):
        return "affirmations"
    if "2-minute reset" in lowered or "2 minute reset" in lowered or "30-second reset" in lowered:
        return "reset"
    if "short meditation" in lowered:
        return "meditation"
    if "breathing patterns" in lowered or "breathing pattern" in lowered:
        return "breathing"
    if "**story**" in lowered:
        return "story"
    if "within a few weeks" in lowered or "months later" in lowered or "wanted a different life" in lowered:
        return "story"
    return "none"


def _content_artifact_count(history: list[dict[str, str]] | None, artifact: str) -> int:
    if not history:
        return 0
    count = 0
    for item in history:
        if item.get("role") != "assistant":
            continue
        if _detect_recent_content_artifact([item]) == artifact:
            count += 1
    return count


def _classify_content_intent(message: str, history: list[dict[str, str]] | None = None) -> str:
    normalized = _normalize_brief_text(message)
    if not normalized:
        return "unclear"
    if _assistant_recently_requested_affirmation_style(_recent_assistant_context(history)) and (
        _is_shorten_request(message)
        or normalized in {"brief", "short", "calm", "confidence", "focus", "finances", "financial", "money"}
    ):
        return "request_affirmations"
    if _is_greeting_only(message):
        return "greeting"
    if _is_another_variant_request(message):
        last_artifact = _detect_recent_content_artifact(history)
        if last_artifact == "script":
            return "alternate_script"
        if last_artifact == "affirmations":
            return "alternate_affirmations"
        if last_artifact == "story":
            return "alternate_story"
        return "another_variant"
    if _is_energy_request(message):
        return "request_energy"
    if _is_praise_response(message):
        return "praise"
    if _is_reflective_followup(message):
        return "reflective"
    if _is_repair_request(message):
        return "rewrite"
    if _is_approval_like_followup(message) and _assistant_recently_offered_rewrite(_recent_assistant_context(history)):
        return "approve_rewrite"
    if normalized in {"no", "nope", "cancel", "stop", "never mind"}:
        return "reject"
    if _is_first_person_request(message):
        return "shift_first_person"
    if _is_shorten_request(message):
        return "shorten"
    if _is_strengthen_request(message) or _is_expand_request(message):
        return "strengthen"
    if _is_story_request(message):
        return "request_story"
    if _is_reset_followup(message):
        return "request_reset"
    if _is_visualization_request(message):
        return "request_visualization"
    if _is_mindset_tools_request(message):
        return "request_mindset_tools"
    if _is_short_daily_practices_request(message):
        return "request_daily_practices"
    if _is_affirmation_followup(message) or "affirmation" in normalized:
        return "request_affirmations"
    if _is_script_followup(message) or _is_short_script_followup(message):
        return "request_script"
    if _is_money_manifestation_topic(message):
        return "general_money_manifestation"
    return "unclear"


def _requested_content_artifact(message: str) -> str:
    if _is_story_request(message):
        return "story"
    if _is_reset_followup(message):
        return "reset"
    if _is_affirmation_followup(message):
        return "affirmations"
    if _is_script_followup(message) or _is_short_script_followup(message):
        return "script"
    return "none"


def _is_first_person_request(message: str) -> bool:
    normalized = _normalize_brief_text(message)
    return "first person" in normalized or normalized in {"first person", "in first person"}


def _is_strengthen_request(message: str) -> bool:
    normalized = _normalize_brief_text(message)
    return normalized in {"more powerful", "stronger", "stronger please", "make them stronger", "make it stronger"}


def _is_transform_request(message: str) -> bool:
    return any(
        (
            _is_expand_request(message),
            _is_shorten_request(message),
            _is_first_person_request(message),
            _is_strengthen_request(message),
            _is_repair_request(message),
        )
    )


def _is_another_variant_request(message: str) -> bool:
    normalized = _normalize_brief_text(message)
    direct = {
        "another",
        "another one",
        "again",
        "one more",
        "same idea different version",
        "same idea, different version",
        "do that again",
        "do that again please",
        "another script",
        "another story",
        "another set",
    }
    if normalized in direct or normalized.startswith(("another ", "again ", "one more ", "do that again")):
        return True
    label, score = _best_intent_label(message, ("another_variant",))
    return label == "another_variant" and score >= 0.84


def _assistant_recently_offered_formats(text: str) -> bool:
    lowered = (text or "").lower()
    return (
        "short script" in lowered
        and "affirmations" in lowered
        and ("2-minute reset" in lowered or "2 minute reset" in lowered)
    ) or ("daily set" in lowered and "affirmations" in lowered)


def _assistant_recently_offered_rewrite(text: str) -> bool:
    lowered = (text or "").lower()
    rewrite_markers = (
        "rewrite",
        "restate it more simply",
        "cleaner, shorter version",
        "simpler version right now",
        "shorter daily version",
        "shorter 30-second version",
        "even shorter for a quick daily repetition",
        "shorter version for a quick daily repetition",
    )
    return any(marker in lowered for marker in rewrite_markers)


def _build_money_affirmations_reply(topic: str, history: list[dict[str, str]] | None = None, variant_hint: str = "") -> str:
    lines = _affirmation_lines_for_topic(topic, history=history, variant_hint=variant_hint)
    return "\n".join(
        [
            "Use the ones that feel believable enough to repeat.",
            "",
            *[f"- {line}" for line in lines],
            "",
            "What would help you stay consistent with these?",
        ]
    )


def _build_money_daily_set_reply(topic: str) -> str:
    lines = _affirmation_lines_for_topic(topic)[:3]
    return "\n".join(
        [
            "Here’s a shorter daily set.",
            "",
            *[f"- {line}" for line in lines],
        ]
    )


def _build_money_script_reply(topic: str, history: list[dict[str, str]] | None = None, variant_hint: str = "") -> str:
    lines = _script_lines_for_topic(topic, history=history, variant_hint=variant_hint)
    return "\n".join(
        [
            "Try this:",
            "",
            "**Script**",
            *lines,
        ]
    )


def _build_money_reset_reply(topic: str, history: list[dict[str, str]] | None = None, variant_hint: str = "") -> str:
    steps = _reset_steps_for_topic(topic, history=history, variant_hint=variant_hint)
    return "\n".join(
        [
            "Try this 2-minute reset:",
            "",
            "**2-Minute Reset**",
            *[f"- {step}" for step in steps],
        ]
    )


def _build_money_reset_short_reply(topic: str) -> str:
    final_line = (
        "I can increase my income without panicking."
        if _canonical_content_topic(topic) == "more money"
        else "I can stay calm and move one step at a time."
    )
    return "\n".join(
        [
            "Use this shorter reset:",
            "",
            "**30-Second Reset**",
            "- Inhale gently and exhale a little longer until your body softens.",
            "- Relax your shoulders and unclench your jaw.",
            f"- Repeat once: *{final_line}*",
        ]
    )


def _build_money_meditation_reply(topic: str) -> str:
    theme = _canonical_content_topic(topic)
    closing = (
        "Picture yourself answering the right email, sending the right offer, or finishing the task that leads to payment."
        if theme == "more money"
        else "Picture yourself following through on the next step that actually matters."
    )
    return "\n".join(
        [
            "Try this short meditation.",
            "",
            "Settle your shoulders and let your breath lengthen.",
            closing,
            "With each exhale, drop urgency. With each inhale, return to the one thing you can actually do next.",
        ]
    )


def _build_breathing_practices_reply(topic: str) -> str:
    return "\n".join(
        [
            "Use one of these breathing patterns:",
            "",
            "- Box breathing: inhale for four, hold for four, exhale for four, hold for four while you focus on the next real task.",
            "- Long exhale breathing: inhale for four, exhale for six until your body settles enough to make one clear decision.",
        ]
    )


def _build_wealth_identity_reply() -> str:
    return (
        "Wealth identity usually grows through repetition, evidence, and cleaner self-permission.\n\n"
        "Focus on the version of you who expects support, makes steady decisions, and does not shrink around bigger numbers. "
        "The shift is less about becoming someone else and more about stabilizing the part of you that can already hold more.\n\n"
        "If you want, I can help you turn that into a script, a few affirmations, or one practical next-step plan."
    )


def _build_dream_life_reply() -> str:
    return (
        "Start with your ideal day, not your entire future.\n\n"
        "A dream life usually takes shape through repeated days that feel more honest, more aligned, and more intentional. "
        "Choose one area to shift first so the direction becomes real instead of abstract.\n\n"
        "If you want, I can help you sketch your ideal day or turn it into a simple next-step plan."
    )


def _build_dream_job_reply() -> str:
    return (
        "Start by getting more specific about what makes it a dream job for you.\n\n"
        "Sometimes the real target is not the title itself but the pay, environment, freedom, or kind of work you want to be known for. "
        "Once that is clear, your next move gets much sharper.\n\n"
        "Then focus on positioning: build visible proof, tighten how you talk about your value, and move toward the places where that kind of role already exists."
    )


def _build_relaxing_into_wealth_reply() -> str:
    return (
        "Treat wealth as something you need to handle well, not chase frantically.\n\n"
        "That usually means slowing down long enough to make sharper decisions, finish what is already in motion, and stop scattering your attention across ten different income ideas at once.\n\n"
        "If you want wealth to feel more natural, start with one practical move that makes money easier to receive or keep this week."
    )


def _build_script_response(
    topic: str,
    *,
    perspective: str = "first_person",
    tone: str = "steady",
    history: list[dict[str, str]] | None = None,
    variant_hint: str = "",
) -> str:
    lines = _script_lines_for_topic(topic, perspective=perspective, tone=tone, history=history, variant_hint=variant_hint)
    return "\n".join(["**Script**", *lines])


def _build_shorter_script_response(history: list[dict[str, str]] | None = None, topic: str | None = None) -> str:
    previous_lines = _extract_script_body(history)
    prior_script_text = _extract_previous_script_text(history)
    inferred_topic = topic or _infer_topic_from_text(prior_script_text)
    resolved_topic = _canonical_content_topic(inferred_topic)
    raw_topic = _normalize_topic_for_content(inferred_topic, "")
    if previous_lines:
        prior_normalized = _normalize_topic_for_content(prior_script_text, "")
        if "connection" in prior_normalized or (raw_topic and "connection" in raw_topic):
            shortened = "I follow up on the connections that deserve my attention."
        elif resolved_topic == "more money":
            shortened = "I raise my income through better decisions and faster follow-through."
        elif resolved_topic == "new paying signature members":
            shortened = "The right members see the offer clearly and decide to join."
        elif resolved_topic == "wealth identity":
            shortened = "I make decisions that match the level I want to live at."
        elif resolved_topic == "new opportunities":
            shortened = "I move on the opportunities that deserve a real answer."
        elif raw_topic:
            if "member" in raw_topic:
                shortened = "I make it easy for the right members to say yes."
            elif "money" in raw_topic or "income" in raw_topic:
                shortened = "I act on the decisions that increase my income."
            else:
                shortened = f"I move directly on {raw_topic}."
        else:
            shortened = "I act on what needs a clear decision."
        if not shortened.endswith((".", "!", "?")):
            shortened += "."
    else:
        shortened = _script_lines_for_topic(resolved_topic, history=history, variant_hint="shorter")[0]
    return "\n".join(["**Shorter Script**", shortened])


def _build_first_person_script_response(history: list[dict[str, str]] | None = None, topic: str | None = None) -> str:
    previous_lines = _extract_script_body(history)
    resolved_topic = _canonical_content_topic(topic or _infer_topic_from_text(_extract_previous_script_text(history)))
    if previous_lines:
        base_lines = _script_lines_for_topic(resolved_topic, perspective="first_person", tone="steady", history=history, variant_hint="first_person")
        if resolved_topic == "new opportunities":
            rewritten = [
                "I notice which opportunities deserve a real answer.",
                "I trust myself to move on what fits instead of hesitating over everything.",
                "I respond while the opening is still worth taking seriously.",
            ]
        else:
            rewritten = base_lines
        return "\n".join(["**Script**", *rewritten])
    return _build_script_response(resolved_topic, perspective="first_person")


def _build_script_repair_response(history: list[dict[str, str]] | None = None, topic: str | None = None) -> str:
    previous_text = _extract_previous_script_text(history)
    repaired_topic = _normalize_topic_for_content(topic or _infer_topic_from_text(_extract_previous_script_text(history)), "more money")
    canonical = _canonical_content_topic(repaired_topic)
    if canonical == "more money":
        repaired = [
            "I make the decisions that put more money in front of me.",
            "I price, follow up, and finish the work that leads to payment.",
            "I stop stalling where a direct move would serve me better.",
        ]
    elif canonical == "new opportunities":
        repaired = [
            "I spot the openings that deserve a real answer.",
            "I trust my judgment quickly enough to act while they are still available.",
            "I move on what fits instead of circling it.",
        ]
    elif canonical == "wealth identity":
        repaired = [
            "I act like someone who can hold more without shrinking.",
            "I raise my standards where I used to negotiate them down.",
            "I let my decisions prove the level I am stepping into.",
        ]
    else:
        repaired = _script_lines_for_topic(repaired_topic, perspective="first_person", tone="steady", history=history, variant_hint="repair")
    if _token_overlap_ratio(previous_text, " ".join(repaired)) > 0.6:
        if canonical == "more money":
            repaired = [
                "I choose the moves that increase income instead of postponing them.",
                "I ask clearly, price directly, and close the loop on paid work.",
                "I stop hiding from the decisions that change my numbers.",
            ]
        elif canonical == "new opportunities":
            repaired = [
                "I answer promising openings before hesitation wastes them.",
                "I choose with discernment and move while the chance is still live.",
                "I stop circling opportunities that need a direct response.",
            ]
    return "\n".join(
        [
            "You’re right. Here’s a cleaner version.",
            "",
            "**Script**",
            *repaired,
        ]
    )


def _build_affirmation_set(
    topic: str,
    *,
    stronger: bool = False,
    shorter: bool = False,
    history: list[dict[str, str]] | None = None,
    variant_hint: str = "",
    source_message: str | None = None,
) -> str:
    return build_fortune_affirmations(
        message=source_message,
        requested_topic=topic,
        history=history,
        shorter=shorter,
        stronger=stronger,
        variant_hint=variant_hint,
    )


def _build_affirmation_style_clarify_reply(topic: str) -> str:
    resolved = _canonical_content_topic(topic)
    if resolved == "confidence":
        label = "confidence"
    elif resolved == "focus":
        label = "focus"
    elif resolved == "more money":
        label = "financial"
    else:
        label = "calm"
    return f"Would you prefer brief, one-line {label} affirmations or a longer set?"


def _build_repair_reply(history: list[dict[str, str]] | None = None) -> str:
    prior_assistant = _recent_assistant_context(history)
    if "affirmation" in prior_assistant.lower():
        return (
            "You're right. Let me restate those more clearly.\n\n"
            "These affirmations are meant to make receiving feel steadier, cleaner, and more believable in your body."
        )
    if "script" in prior_assistant.lower():
        return (
            "You're right. Let me restate that more simply.\n\n"
            "The point is to use language that keeps you clear, grounded, and ready to act when something aligned opens."
        )
    return (
        "You're right. Let me say that more clearly.\n\n"
        "I want the response to feel direct, usable, and easier to carry forward."
    )


def _build_reflective_followup_reply(history: list[dict[str, str]] | None = None) -> str:
    artifact = _detect_recent_content_artifact(history)
    if artifact == "script":
        return "That works. Keep it where you can see it and use it before you make a decision."
    if artifact == "affirmations":
        return "That works. Keep the shorter set visible and repeat it when you start second-guessing yourself."
    return "That works. Keep it visible and come back to it when you need to reset."


def _build_praise_reply(history: list[dict[str, str]] | None = None) -> str:
    return "Good. Keep using that."


def _build_energy_reply(topic: str | None = None) -> str:
    canonical = _canonical_content_topic(topic)
    if canonical == "new paying signature members":
        return (
            "Good. Hold the standard and make the invitation easy to trust. "
            "The right members move when the offer is clear and the result feels worth paying for."
        )
    if canonical == "new opportunities":
        return (
            "Move on the opening that can actually change your position. "
            "Fast judgment and clean follow-through will do more for you than another round of hesitation."
        )
    if canonical == "wealth identity":
        return (
            "Hold the level. Bigger results start feeling normal when your decisions stop shrinking to match old comfort."
        )
    return (
        "Good. Make the direct move. Send the offer, ask clearly, follow up faster, and let your numbers reflect the quality of your execution."
    )


def _build_rewrite_fulfillment_reply(history: list[dict[str, str]] | None = None) -> str:
    prior_assistant = _recent_assistant_context(history).lower()
    prior_user_focus = _clean_subject(_extract_primary_prompt_focus(_recent_user_context(history)))
    if "shorter daily version" in prior_assistant or "affirmation" in prior_assistant:
        return _build_affirmation_set((prior_user_focus or "more money").lower(), shorter=True, history=history, variant_hint="rewrite")
    if "30-second version" in prior_assistant or "2-minute reset" in prior_assistant or "2 minute reset" in prior_assistant:
        return _build_money_reset_short_reply((prior_user_focus or "more money").lower())
    if "script" in prior_assistant or "daily repetition" in prior_assistant or "cleaner, shorter version" in prior_assistant:
        return _build_shorter_script_response(history, prior_user_focus or "new opportunities")
    return (
        "Here’s the simpler version.\n\n"
        "Keep the idea direct, keep the language clean, and use the version you can actually repeat."
    )


def _build_money_manifestation_reply(message: str, history: list[dict[str, str]] | None = None) -> str:
    if _is_combined_money_support_request(message):
        return "\n".join(
            [
                "Mindset:",
                "- Treat the number you want as something you can support with steadier decisions.",
                "- Let receiving feel tied to clarity, follow-through, and visible value.",
                "",
                "Action:",
                "- Choose one money move today: the offer, the ask, the price, or the follow-up.",
                "- Finish the one step that would make income easier to receive this week.",
                "",
                "Visualization:",
                "- Picture yourself completing that move calmly, sending it, and staying available for the result.",
            ]
        )
    return (
        "More money usually shows up after a small number of sharper decisions, not a bigger amount of wishing.\n\n"
        "Pick the exact increase you want, tie it to a real source such as an offer, price change, client conversation, or follow-up, and move one of those today.\n\n"
        "If you want, I can turn that into a short script, a few affirmations, or a 2-minute reset."
    )


def _build_money_visualization_reply() -> str:
    return "\n".join(
        [
            "- Sit still for one breath and picture the next paid move already finished.",
            "- See yourself sending the message, making the offer, or naming the price without rushing.",
            "- Let your body stay calm while you hold the result as something clean and reachable.",
        ]
    )


def _build_money_mindset_tools_reply() -> str:
    return "\n".join(
        [
            "- Replace urgency with one clear number and one clear source for it.",
            "- Keep your attention on value, visibility, and follow-through instead of vague hoping.",
            "- Let steadiness be the standard you return to before every money decision.",
        ]
    )


def _build_short_daily_practices_reply() -> str:
    return "\n".join(
        [
            "- Name the paid move that matters most today.",
            "- Spend two quiet minutes clearing one money-related avoidance loop.",
            "- End the day by noting one action that made receiving feel more supported.",
            "",
            "Speak-Aloud Anchor:",
            "- I make money moves clearly, calmly, and on time.",
            "",
            "Next Step:",
            "- Put one ten-minute money block on your calendar before you leave this conversation.",
        ]
    )


def _build_neutral_assist_reply(message: str, history: list[dict[str, str]] | None = None) -> str:
    normalized = _normalize_brief_text(message)
    prior_assistant = _recent_assistant_context(history).lower()
    if _is_greeting_only(message):
        return "Hi. What would you like to do?"
    if normalized == "nope":
        return "Got it. What would you like to do next?"
    if _looks_like_confirm_typo(message):
        if _assistant_recently_offered_rewrite(prior_assistant):
            return _build_rewrite_fulfillment_reply(history)
        return "Did you mean confirm?"
    if normalized in {"u", "k", "kk", "ok", "okay"}:
        return "Can you clarify what you'd like to do?"
    if _is_minimal_unclear_input(message):
        return "Do you want to make a transfer, deposit, or something else?"
    return "Can you clarify what you'd like to do?"


def _build_grounding_reply(message: str) -> str:
    return _build_neutral_assist_reply(message)


def _build_story_script_clarify_reply() -> str:
    return "Do you want a script about money, or based on that story?"


def _build_another_variant_clarify_reply() -> str:
    return "Do you want another script, affirmations, reset, or story?"


def _assistant_recently_requested_script_details(text: str) -> bool:
    lowered = (text or "").lower()
    if "?" not in lowered:
        return False
    has_script_context = "script" in lowered or ("daily" in lowered and "weekly" in lowered)
    if not has_script_context:
        return False
    return any(
        marker in lowered
        for marker in (
            "what kind of script",
            "what kind of script would help",
            "what should the script",
            "what do you want the script",
            "do you want a daily check in a weekly check in or both",
            "do you want a daily check-in a weekly check-in or both",
            "daily",
            "weekly",
            "check-in",
            "check in",
            "money",
            "based on that story",
        )
    )


def _script_clarification_count(history: list[dict[str, str]] | None = None) -> int:
    if not history:
        return 0
    count = 0
    for item in history:
        if item.get("role") != "assistant":
            continue
        if _assistant_recently_requested_script_details(item.get("content") or ""):
            count += 1
    return count


def _is_impatient_delivery_request(message: str) -> bool:
    normalized = _normalize_brief_text(message)
    if not normalized:
        return False
    direct = (
        "just answer",
        "just do it",
        "stop asking",
        "enough questions",
        "come on",
        "bruh",
        "please answer",
    )
    return any(phrase in normalized for phrase in direct)


def _resolve_script_scope(message: str, history: list[dict[str, str]] | None = None) -> str:
    normalized = _normalize_brief_text(message)
    recent = f"{_normalize_brief_text(_recent_user_context(history))} {_normalize_brief_text(_recent_assistant_context(history))}".strip()
    haystack = f"{recent} {normalized}".strip()
    if "both" in normalized:
        return "both"
    has_daily = "daily" in haystack
    has_weekly = "weekly" in haystack
    if has_daily and has_weekly:
        return "both"
    if has_daily:
        return "daily"
    if has_weekly:
        return "weekly"
    return ""


def _build_daily_checkin_script() -> str:
    return "\n".join(
        [
            "- Name the paid move that matters most today.",
            "- Identify the money conversation, follow-up, or task that needs a direct answer.",
            "- Choose what would make today feel cleaner by tonight.",
            "",
            "Speak-Aloud Anchor:",
            "- I move the paid step clearly and cleanly today.",
            "",
            "Next Step:",
            "- Block ten focused minutes for the one money move that changes the day.",
        ]
    )


def _build_weekly_checkin_script() -> str:
    return "\n".join(
        [
            "- Note which actions this week directly supported income, clarity, or follow-through.",
            "- Name where hesitation slowed a paid move or necessary decision.",
            "- Close the open loops that need to be resolved before next week begins.",
            "- Decide which one result you want to make easier next week.",
            "",
            "Adjustments:",
            "- Stop carrying open loops into the next week.",
            "- Start the paid move earlier instead of waiting for perfect timing.",
            "- Simplify the one process that keeps slowing follow-through.",
            "",
            "Speak-Aloud Anchor:",
            "- I review the week clearly and adjust without drama.",
            "",
            "Next Step:",
            "- Choose one weekly adjustment and calendar it before this check-in ends.",
        ]
    )


def _build_checkin_script_package(scope: str) -> str:
    daily = _build_daily_checkin_script()
    weekly = _build_weekly_checkin_script()
    if scope == "daily":
        return daily
    if scope == "weekly":
        return weekly
    return "\n\n".join(["Daily:", daily, "", "Weekly:", weekly]).strip()


def _build_brief_spoken_prompt(topic: str) -> str:
    resolved = _canonical_content_topic(topic)
    if resolved == "more money":
        lines = [
            "I make clean decisions that support stronger income.",
            "I follow through while the opportunity is still real.",
            "I let steadiness increase what I can hold.",
        ]
    elif resolved == "new opportunities":
        lines = [
            "I notice what deserves a direct answer.",
            "I move while the opening is still live.",
            "I trust myself to respond clearly.",
        ]
    else:
        lines = [
            "I stay clear enough to choose well.",
            "I follow through on what matters now.",
            "I let steadiness shape the next move.",
        ]
    return "\n".join(lines)


def _local_rescue_reply(message: str, history: list[dict[str, str]] | None = None) -> str:
    normalized = (message or "").strip().lower()
    focus = _clean_subject(_extract_primary_prompt_focus(message))
    prior_assistant_text = _recent_assistant_context(history)
    prior_assistant = prior_assistant_text.lower()
    prior_user_text = _recent_user_context(history)
    prior_user_focus = _clean_subject(_extract_primary_prompt_focus(prior_user_text))
    stable_user_focus = _recent_substantive_user_focus(history)
    last_artifact = _detect_recent_content_artifact(history)
    if not normalized:
        return _build_neutral_assist_reply(message, history)
    if _is_greeting_only(message):
        return _build_neutral_assist_reply(message, history)
    current_intent = _classify_content_intent(message, history)
    requested_artifact = _requested_content_artifact(message)
    previous_script = _extract_previous_script_text(history)
    previous_affirmations = _extract_previous_affirmations(history)
    default_topic = stable_user_focus or prior_user_focus or focus or "more money"
    inferred_script_topic = _infer_topic_from_text(previous_script) if previous_script else "more money"
    script_topic = inferred_script_topic if inferred_script_topic != "more money" or default_topic == "more money" else default_topic
    script_scope = _resolve_script_scope(message, history)
    if last_artifact == "story" and current_intent in {"alternate_story", "another_variant"}:
        return _build_manifestation_story(default_topic, history=history, variant_hint="alternate")
    if current_intent == "request_script":
        if last_artifact == "story":
            return _build_script_response(default_topic or "more money", history=history, variant_hint="requested")
        if last_artifact == "script":
            return _build_script_response(
                script_topic,
                tone="stronger" if _content_artifact_count(history, "script") >= 1 else "steady",
                history=history,
                variant_hint="alternate" if _content_artifact_count(history, "script") >= 1 else "requested",
            )
        if "spoken prompt" in normalized or "spoken" in normalized:
            return _build_brief_spoken_prompt(default_topic)
        if script_scope:
            return _build_checkin_script_package(script_scope)
        if _script_clarification_count(history) >= 1 or _assistant_recently_requested_script_details(prior_assistant_text):
            return _build_checkin_script_package(script_scope or "both")
        return _build_script_response(default_topic, history=history, variant_hint="requested")
    if (
        script_scope
        and (
            _is_script_followup(message)
            or "check in" in normalized
            or "check-in" in normalized
            or _script_clarification_count(history) >= 1
            or _assistant_recently_requested_script_details(prior_assistant_text)
        )
    ):
        return _build_checkin_script_package(script_scope)
    if _is_impatient_delivery_request(message) and _script_clarification_count(history) >= 1:
        return _build_checkin_script_package(script_scope or "both")
    if current_intent == "approve_rewrite" and last_artifact == "rewrite_offer":
        return _build_rewrite_fulfillment_reply(history)
    if _is_plain_affirmations_request(message):
        return _build_affirmation_set("general", history=history, variant_hint="requested", source_message=message)
    if _assistant_recently_requested_affirmation_topic(prior_assistant_text) and _is_affirmation_topic_reply(message):
        return _build_affirmation_style_clarify_reply(_extract_affirmation_topic(message, history))
    if current_intent == "request_energy":
        return _build_energy_reply(default_topic)
    if current_intent == "praise":
        return _build_praise_reply(history)
    if current_intent == "reflective":
        return _build_reflective_followup_reply(history)
    if current_intent == "request_visualization":
        return _build_money_visualization_reply()
    if current_intent == "request_mindset_tools":
        return _build_money_mindset_tools_reply()
    if current_intent == "request_daily_practices":
        return _build_short_daily_practices_reply()
    if current_intent == "another_variant" and last_artifact == "none":
        return _build_another_variant_clarify_reply()
    if _should_short_circuit_neutral_assist(message, history):
        return _build_neutral_assist_reply(message, history)
    if last_artifact == "script":
        if current_intent in {"request_script", "alternate_script", "another_variant"}:
            return _build_script_response(
                script_topic,
                tone="stronger" if _content_artifact_count(history, "script") >= 1 else "steady",
                history=history,
                variant_hint="alternate",
            )
        if current_intent == "shift_first_person":
            return _build_first_person_script_response(history, script_topic)
        if current_intent == "shorten":
            return _build_shorter_script_response(history, script_topic)
        if current_intent in {"rewrite", "strengthen"}:
            return _build_script_repair_response(history, script_topic)
    if last_artifact == "affirmations":
        if current_intent == "shorten":
            return _build_affirmation_set(default_topic, shorter=True, history=history, variant_hint="shorter")
        if current_intent in {"strengthen", "rewrite", "alternate_affirmations", "another_variant"}:
            return _build_affirmation_set(default_topic, stronger=True, history=history, variant_hint="alternate")
    if last_artifact == "story":
        if current_intent == "request_script":
            return _build_story_script_clarify_reply()
        if current_intent in {"alternate_story", "another_variant"}:
            return _build_manifestation_story(default_topic, history=history, variant_hint="alternate")
        if current_intent == "rewrite":
            return "\n".join(
                [
                    "You’re right. Here’s a cleaner version.",
                    "",
                    _build_manifestation_story(default_topic, history=history, variant_hint="rewrite"),
                ]
            )
    if requested_artifact == "script":
        if current_intent == "shorten":
            return _build_shorter_script_response(history, default_topic)
        if current_intent == "shift_first_person":
            return _build_script_response(default_topic, perspective="first_person", history=history, variant_hint="first_person")
        return _build_script_response(default_topic, history=history, variant_hint="requested")
    if requested_artifact == "affirmations":
        affirmation_topic = _extract_affirmation_topic(message, history)
        if current_intent == "shorten":
            return _build_affirmation_set(affirmation_topic, shorter=True, history=history, variant_hint="shorter", source_message=message)
        if current_intent == "strengthen":
            return _build_affirmation_set(affirmation_topic, stronger=True, history=history, variant_hint="stronger", source_message=message)
        return _build_affirmation_set(affirmation_topic, history=history, variant_hint="requested", source_message=message)
    if requested_artifact == "reset":
        return _build_money_reset_reply(default_topic, history=history, variant_hint="requested")
    if "relaxing into wealth" in normalized:
        return _build_relaxing_into_wealth_reply()
    if current_intent in {"request_story", "alternate_story"}:
        return _build_manifestation_story(stable_user_focus or prior_user_focus or focus or normalized, history=history, variant_hint="requested")
    if current_intent == "general_money_manifestation" or (
        _is_short_followup(message)
        and (
            _is_money_manifestation_topic(prior_user_text)
            or _is_money_manifestation_topic(prior_assistant_text)
        )
    ):
        if _is_combined_money_support_request(message) or _is_support_template_context(history):
            if _is_visualization_request(message):
                return _build_money_visualization_reply()
            if _is_mindset_tools_request(message):
                return _build_money_mindset_tools_reply()
            if _is_short_daily_practices_request(message):
                return _build_short_daily_practices_reply()
            return _build_money_manifestation_reply("help manifesting money", history=history)
        if _is_visualization_request(message):
            return _build_money_visualization_reply()
        if _is_mindset_tools_request(message):
            return _build_money_mindset_tools_reply()
        if _is_short_daily_practices_request(message):
            return _build_short_daily_practices_reply()
        if "wealth identity" in normalized:
            return _build_wealth_identity_reply()
        return _build_money_manifestation_reply(message, history=history)
    if "wealth identity" in normalized:
        return _build_wealth_identity_reply()
    if "dream job" in normalized:
        return _build_dream_job_reply()
    if "dream life" in normalized:
        return _build_dream_life_reply()
    if current_intent == "request_script":
        return _build_script_response(default_topic, history=history, variant_hint="requested")
    if current_intent == "request_affirmations":
        return _build_affirmation_set(
            _extract_affirmation_topic(message, history),
            history=history,
            variant_hint="requested",
            source_message=message,
        )
    if _is_daily_set_followup(message):
        return _build_money_daily_set_reply(default_topic)
    if current_intent == "request_reset":
        return _build_money_reset_reply(default_topic, history=history, variant_hint="requested")
    if _is_meditation_followup(message):
        return _build_money_meditation_reply(default_topic)
    if _is_breathing_followup(message):
        return _build_breathing_practices_reply(default_topic)
    if current_intent == "rewrite":
        return _build_repair_reply(history)
    if "future success story" in normalized or "future self" in normalized:
        return _build_manifestation_story("future success")
    return _build_grounding_reply(message)


async def _openai_response(
    message: str,
    history: list[dict[str, str]] | None = None,
    short_mode: bool = False,
    repeat_count: int = 0,
) -> str:
    if not settings.OPENAI_API_KEY:
        return "The Teller is not configured yet. Please add an API key."
    name, prompt = get_persona()
    system_prompt = f"{name}: {prompt}"
    if len(system_prompt) > settings.TELLER_PROMPT_MAX_CHARS:
        system_prompt = system_prompt[: settings.TELLER_PROMPT_MAX_CHARS].rstrip() + "…"
    if short_mode:
        system_prompt += " Respond in 1-3 concise sentences."
    if repeat_count > 0:
        system_prompt += (
            " The user has repeated the same prompt. Do not repeat your prior wording. "
            "Reframe the answer from a fresh angle or ask one brief clarifying question about direction."
        )
    history_text_parts: list[str] = []
    for item in _compact_history(history):
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and content:
            history_text_parts.append(f"{role.upper()}: {content}")
    history_text = "\n".join(history_text_parts).strip()
    full_input = f"{history_text}\nUSER: {message}".strip() if history_text else message
    def build_payload(max_tokens: int, input_text: str, force_brief: bool = False) -> dict[str, Any]:
        instructions = system_prompt
        if force_brief:
            instructions = instructions + " Respond briefly and finish your thought."
        return {
            "model": settings.OPENAI_MODEL,
            "max_output_tokens": max_tokens,
            "instructions": instructions,
            "input": input_text,
            "temperature": 0.55,
            "top_p": 0.9,
            "frequency_penalty": 0.2,
            "presence_penalty": 0.1,
        }

    payload: dict[str, Any] = build_payload(
        settings.TELLER_MAX_OUTPUT_TOKENS,
        full_input,
        force_brief=short_mode,
    )
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}
    try:
        client = _get_openai_client()
        backoffs = [0.25, 0.75]
        for attempt, delay in enumerate(backoffs, start=1):
            try:
                res = await client.post(
                    "https://api.openai.com/v1/responses",
                    json=payload,
                    headers=headers,
                )
                unsupported_param = _response_unsupported_param(res)
                if unsupported_param:
                    logger.info(
                        "OpenAI model %s rejected response param %s; retrying without unsupported controls.",
                        settings.OPENAI_MODEL,
                        unsupported_param,
                    )
                    payload = _strip_unsupported_response_controls(payload)
                    res = await client.post(
                        "https://api.openai.com/v1/responses",
                        json=payload,
                        headers=headers,
                    )
                if res.status_code >= 400:
                    logger.warning("OpenAI error status=%s body=%s", res.status_code, res.text[:800])
                    return _next_retry_message()
                data = res.json()
                logger.debug("OpenAI response payload=%s", str(data)[:1200])
                text = _extract_response_text(data)
                if text and text != "The Teller is thinking. Please try again." and not _looks_incomplete(text):
                    return _strip_disclaimers(_remove_repeated_sentences(text))
                if data.get("status") == "incomplete" and data.get("incomplete_details", {}).get("reason") == "max_output_tokens":
                    logger.warning("OpenAI incomplete (max_output_tokens).")
                    trimmed_input = full_input[-2000:] if len(full_input) > 2000 else full_input
                    retry_payload = build_payload(
                        max(settings.TELLER_MAX_OUTPUT_TOKENS * 2, settings.TELLER_MAX_OUTPUT_TOKENS + 200),
                        trimmed_input,
                        force_brief=True,
                    )
                    res2 = await client.post(
                        "https://api.openai.com/v1/responses",
                        json=retry_payload,
                        headers=headers,
                    )
                    unsupported_param = _response_unsupported_param(res2)
                    if unsupported_param:
                        logger.info(
                            "OpenAI model %s rejected response param %s on retry; retrying without unsupported controls.",
                            settings.OPENAI_MODEL,
                            unsupported_param,
                        )
                        retry_payload = _strip_unsupported_response_controls(retry_payload)
                        res2 = await client.post(
                            "https://api.openai.com/v1/responses",
                            json=retry_payload,
                            headers=headers,
                        )
                    if res2.status_code < 400:
                        data2 = res2.json()
                        text2 = _extract_response_text(data2)
                        if text2 and text2 != "The Teller is thinking. Please try again.":
                            return _strip_disclaimers(_remove_repeated_sentences(text2))
                if text and text != "The Teller is thinking. Please try again.":
                    trimmed_input = full_input[-2000:] if len(full_input) > 2000 else full_input
                    retry_payload = build_payload(
                        max(settings.TELLER_MAX_OUTPUT_TOKENS * 2, settings.TELLER_MAX_OUTPUT_TOKENS + 200),
                        trimmed_input,
                        force_brief=True,
                    )
                    res2 = await client.post(
                        "https://api.openai.com/v1/responses",
                        json=retry_payload,
                        headers=headers,
                    )
                    unsupported_param = _response_unsupported_param(res2)
                    if unsupported_param:
                        logger.info(
                            "OpenAI model %s rejected response param %s on completion retry; retrying without unsupported controls.",
                            settings.OPENAI_MODEL,
                            unsupported_param,
                        )
                        retry_payload = _strip_unsupported_response_controls(retry_payload)
                        res2 = await client.post(
                            "https://api.openai.com/v1/responses",
                            json=retry_payload,
                            headers=headers,
                        )
                    if res2.status_code < 400:
                        data2 = res2.json()
                        text2 = _extract_response_text(data2)
                        if text2 and text2 != "The Teller is thinking. Please try again.":
                            return _strip_disclaimers(_remove_repeated_sentences(text2))
                return _next_retry_message()
            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                logger.warning("OpenAI transient error (attempt %s): %s", attempt, str(exc))
                if attempt < len(backoffs):
                    await asyncio.sleep(delay)
                    continue
                return _next_retry_message()
        return "Connection timed out. Please try again shortly."
    except httpx.HTTPError as exc:
        logger.exception("OpenAI HTTP error: %s", str(exc))
        return _next_retry_message()
    return _next_retry_message()


async def _copyedit_reply(text: str, short_mode: bool = False) -> str:
    stripped = (text or "").strip()
    if not _should_copyedit(stripped, short_mode=short_mode):
        return stripped
    if not settings.OPENAI_API_KEY:
        return stripped

    payload = {
        "model": settings.OPENAI_MODEL,
        "max_output_tokens": min(max(len(stripped) // 2 + 120, 180), 900),
        "instructions": COPYEDIT_TELLER_PROMPT,
        "input": stripped,
        "temperature": 0.45,
        "top_p": 0.9,
        "frequency_penalty": 0.0,
        "presence_penalty": 0.0,
    }
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}

    try:
        client = _get_openai_client()
        res = await client.post(
            "https://api.openai.com/v1/responses",
            json=payload,
            headers=headers,
        )
        unsupported_param = _response_unsupported_param(res)
        if unsupported_param:
            logger.info(
                "OpenAI model %s rejected copyedit param %s; retrying without unsupported controls.",
                settings.OPENAI_MODEL,
                unsupported_param,
            )
            payload = _strip_unsupported_response_controls(payload)
            res = await client.post(
                "https://api.openai.com/v1/responses",
                json=payload,
                headers=headers,
            )
        if res.status_code >= 400:
            logger.warning("OpenAI copyedit error status=%s body=%s", res.status_code, res.text[:800])
            return stripped
        data = res.json()
        edited = (_extract_response_text(data) or "").strip()
        if not edited or _is_retry_placeholder(edited):
            return stripped
        return edited
    except (httpx.HTTPError, RuntimeError, Exception) as exc:
        logger.warning("OpenAI copyedit HTTP error: %s", str(exc))
        return stripped


def _extract_stream_delta(event: dict[str, Any]) -> str:
    if not isinstance(event, dict):
        return ""
    event_type = str(event.get("type") or "")
    if event_type in {"response.output_text.delta", "response.refusal.delta"}:
        value = event.get("delta") or event.get("text") or ""
        return value if isinstance(value, str) else ""
    if event_type == "response.output_text.done":
        value = event.get("text") or ""
        return value if isinstance(value, str) else ""
    return ""


def _extract_stream_completed_text(event: dict[str, Any]) -> str:
    if not isinstance(event, dict):
        return ""
    event_type = str(event.get("type") or "")

    if event_type in {"response.content_part.added", "response.content_part.done"}:
        part = event.get("part")
        if isinstance(part, dict):
            text = part.get("text") or ""
            return text if isinstance(text, str) else ""

    if event_type == "response.output_item.done":
        item = event.get("item")
        if isinstance(item, dict):
            content = item.get("content")
            if isinstance(content, list):
                parts: list[str] = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    text = block.get("text") or ""
                    if isinstance(text, str) and text:
                        parts.append(text)
                if parts:
                    return "".join(parts)
    return ""


async def _openai_response_stream(
    message: str,
    history: list[dict[str, str]] | None = None,
    short_mode: bool = False,
    on_delta: Any | None = None,
    repeat_count: int = 0,
) -> str:
    if not settings.OPENAI_API_KEY:
        return "The Teller is not configured yet. Please add an API key."

    name, prompt = get_persona()
    system_prompt = f"{name}: {prompt}"
    if len(system_prompt) > settings.TELLER_PROMPT_MAX_CHARS:
        system_prompt = system_prompt[: settings.TELLER_PROMPT_MAX_CHARS].rstrip() + "…"
    if short_mode:
        system_prompt += " Respond in 1-3 concise sentences."
    if repeat_count > 0:
        system_prompt += (
            " The user has repeated the same prompt. Do not repeat your prior wording. "
            "Reframe the answer from a fresh angle or ask one brief clarifying question about direction."
        )

    history_text_parts: list[str] = []
    for item in _compact_history(history):
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and content:
            history_text_parts.append(f"{role.upper()}: {content}")
    history_text = "\n".join(history_text_parts).strip()
    full_input = f"{history_text}\nUSER: {message}".strip() if history_text else message
    payload = {
        "model": settings.OPENAI_MODEL,
        "max_output_tokens": settings.TELLER_MAX_OUTPUT_TOKENS,
        "instructions": system_prompt,
        "input": full_input,
        "stream": True,
        "temperature": 0.55,
        "top_p": 0.9,
        "frequency_penalty": 0.2,
        "presence_penalty": 0.1,
    }
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}
    client = _get_openai_client()
    chunks: list[str] = []
    completed_text = ""

    try:
        async with client.stream(
            "POST",
            "https://api.openai.com/v1/responses",
            json=payload,
            headers=headers,
        ) as res:
            unsupported_param = None
            if res.status_code >= 400:
                await res.aread()
                unsupported_param = _response_unsupported_param(res)
                if unsupported_param:
                    logger.info(
                        "OpenAI model %s rejected stream param %s; retrying without unsupported controls.",
                        settings.OPENAI_MODEL,
                        unsupported_param,
                    )
                else:
                    logger.warning("OpenAI stream error status=%s body=%s", res.status_code, res.text[:800])
                    return _next_retry_message()

        if unsupported_param:
            payload = _strip_unsupported_response_controls(payload)
            async with client.stream(
                "POST",
                "https://api.openai.com/v1/responses",
                json=payload,
                headers=headers,
            ) as res:
                if res.status_code >= 400:
                    logger.warning("OpenAI stream error status=%s body=%s", res.status_code, (await res.aread())[:800])
                    return _next_retry_message()

                async for line in res.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = _extract_stream_delta(event)
                    if delta:
                        chunks.append(delta)
                        if on_delta is not None:
                            result = on_delta(delta)
                            if inspect.isawaitable(result):
                                await result
                        continue

                    finalized = _extract_stream_completed_text(event)
                    if finalized and len(finalized) > len(completed_text):
                        completed_text = finalized
        else:
            async with client.stream(
                "POST",
                "https://api.openai.com/v1/responses",
                json=payload,
                headers=headers,
            ) as res:
                if res.status_code >= 400:
                    logger.warning("OpenAI stream error status=%s body=%s", res.status_code, (await res.aread())[:800])
                    return _next_retry_message()

                async for line in res.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = _extract_stream_delta(event)
                    if delta:
                        chunks.append(delta)
                        if on_delta is not None:
                            result = on_delta(delta)
                            if inspect.isawaitable(result):
                                await result
                        continue

                    finalized = _extract_stream_completed_text(event)
                    if finalized and len(finalized) > len(completed_text):
                        completed_text = finalized
    except httpx.HTTPError as exc:
        logger.exception("OpenAI stream HTTP error: %s", str(exc))
        return _next_retry_message()

    text = ("".join(chunks).strip() or completed_text.strip())
    if text:
        return _strip_disclaimers(_remove_repeated_sentences(text))
    return await _openai_response(message, history=history, short_mode=short_mode)


def _extract_response_text(data: dict[str, Any]) -> str:
    if "output_text" in data and isinstance(data["output_text"], str):
        return data["output_text"]
    output = data.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            content = item.get("content") if isinstance(item, dict) else None
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    text = block.get("text")
                    if isinstance(text, str) and text:
                        parts.append(text)
        if parts:
            return "\n".join(parts)
    message = data.get("message")
    if isinstance(message, str) and message:
        return message
    logger.warning("OpenAI response missing text fields. payload=%s", str(data)[:1200])
    return "The Teller is thinking. Please try again."


def _dedupe_text(text: str) -> str:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return text
    deduped: list[str] = []
    seen = set()
    for line in lines:
        if line in seen:
            continue
        deduped.append(line)
        seen.add(line)
    result = "\n".join(deduped).strip()
    # Collapse repeated sentences in a single line
    parts = [p.strip() for p in result.replace("  ", " ").split(".") if p.strip()]
    collapsed: list[str] = []
    last = None
    for p in parts:
        if p == last:
            continue
        collapsed.append(p)
        last = p
    if collapsed:
        return ". ".join(collapsed) + ("" if result.endswith(".") else "")
    return result


def _remove_repeated_sentences(text: str) -> str:
    if not text:
        return text
    def is_structured(line: str) -> bool:
        stripped = line.lstrip()
        return bool(re.match(r"(#{1,6}\s|[-*+]\s|\d+\.\s)", stripped))

    def dedupe_line_sentences(line: str) -> str:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", line) if s.strip()]
        if len(sentences) < 2:
            return line.strip()
        kept: list[str] = []
        last_key: str | None = None
        for sentence in sentences:
            key = sentence.lower()
            if key == last_key:
                continue
            kept.append(sentence)
            last_key = key
        return " ".join(kept).strip()

    lines = text.splitlines()
    kept_lines: list[str] = []
    previous_key: str | None = None
    blank_open = False

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            if kept_lines and not blank_open:
                kept_lines.append("")
                blank_open = True
            continue

        blank_open = False
        normalized = re.sub(r"\s+", " ", line.strip()).lower()
        if normalized == previous_key:
            continue

        if is_structured(line):
            kept_lines.append(line)
        else:
            kept_lines.append(dedupe_line_sentences(line))
        previous_key = normalized

    return "\n".join(kept_lines).strip()


def _remove_near_duplicate_lines(text: str) -> str:
    if not text:
        return text
    kept: list[str] = []
    previous_key = ""
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            kept.append("")
            previous_key = ""
            continue
        key = re.sub(r"[^a-z0-9]+", " ", line.lower()).strip()
        if previous_key:
            ratio = SequenceMatcher(a=previous_key, b=key).ratio()
            if ratio >= 0.86:
                continue
        kept.append(line)
        previous_key = key
    return "\n".join(kept).strip()


def _remove_repeated_clauses(text: str) -> str:
    if not text:
        return text
    parts = [p.strip() for p in re.split(r";|—", text) if p.strip()]
    if len(parts) < 2:
        return text
    seen = set()
    kept = []
    for p in parts:
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        kept.append(p)
    return ". ".join(kept)


def _collapse_repeated_prompt_fragments(text: str) -> str:
    if not text:
        return text
    compact = re.sub(r"\s+", " ", text).strip()
    repeated_or = re.match(r"(?is)^(.{12,}?)\s+or\s+\1(?:\s+or)?\??$", compact)
    if repeated_or:
        return repeated_or.group(1).strip().rstrip(" ,;:") + "?"
    repeated = re.match(r"(?is)^(.{12,}?)\s+\1\??$", compact)
    if repeated:
        return repeated.group(1).strip().rstrip(" ,;:") + ("?" if compact.endswith("?") else "")
    return text


def _remove_off_brand_filler(text: str) -> str:
    if not text:
        return text
    cleaned = re.sub(r"(?i)(^|(?<=[.!?]\s))nice\.\s*", r"\1Good. ", text)
    cleaned = re.sub(r"(?i)(^|(?<=[.!?]\s))sweet\.\s*", r"\1", cleaned)
    cleaned = re.sub(r"(?i)\bfresh set\b", "new set", cleaned)
    return cleaned


def _strip_manifestation_checks(text: str) -> str:
    if not text:
        return text
    if "manifestation check" not in text.lower():
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept = [s for s in sentences if "manifestation check" not in s.lower()]
    cleaned = " ".join(kept).strip()
    return cleaned if cleaned else ""

def _strip_typo_apologies(text: str) -> str:
    if not text:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept = []
    for s in sentences:
        s_low = s.lower()
        if "typo" in s_low or s_low.startswith("sorry"):
            continue
        kept.append(s)
    cleaned = " ".join(kept).strip()
    return cleaned if cleaned else ""

def _trim_to_full_sentence(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    # Try to cut at last sentence boundary
    m = re.search(r"^(.*[.!?])\s", cut, re.S)
    if m:
        return m.group(1).strip()
    return cut.strip()


def _strip_disclaimers(text: str) -> str:
    banned = [
        "symbolic",
        "not real money",
        "real money",
        "won’t move real money",
        "won't move real money",
        "does not move real money",
    ]
    lowered = text.lower()
    if not any(b in lowered for b in banned):
        return text
    # Remove any sentence containing a banned phrase
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept = []
    for s in sentences:
        s_low = s.lower()
        if any(b in s_low for b in banned):
            continue
        kept.append(s)
    cleaned = " ".join(kept).strip()
    return cleaned if cleaned else ""


def _looks_incomplete(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return True
    if stripped.endswith("…"):
        return True
    if re.search(r"[:,;,\-]\s*$", stripped):
        return True
    if re.search(r"\b(and|or|with|including|like|such as)\s*$", stripped.lower()):
        return True
    return False


def _normalize_punctuation(text: str) -> str:
    if not text:
        return text
    cleaned = re.sub(r"(?i)\b(next steps|choose one|pick one|options|try this)\s*;", r"\1:", text)
    cleaned = re.sub(r";\s*(?=[A-Z#*\-])", ". ", cleaned)
    cleaned = re.sub(r";\s*", ", ", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\bi\b", "I", cleaned)
    if "## " not in cleaned and not re.search(r"(?m)^\s*[-*+]\s", cleaned):
        cleaned = re.sub(r"(?<=\w)\s*\n\s*(?=[a-zA-Z])", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(
        r"(?i)(\b(?:what|which|who|when|where|why|how|would|could|should|do|does|did|are|is)\b[^.?!\n]{8,})\.\s+([a-z])",
        lambda match: f"{match.group(1).strip()}? {match.group(2).upper()}",
        cleaned,
    )
    cleaned = re.sub(
        r"(?i)(\b(?:thank you|thanks|you’re welcome|you're welcome|nice to see you again|glad i could help)\b[^.?!\n]{2,})\.\s+([a-z])",
        lambda match: f"{match.group(1).strip()}. {match.group(2).upper()}",
        cleaned,
    )
    cleaned = re.sub(r"(?i)\b(you’re welcome|you're welcome)\.\s+glad\b", "You’re welcome. Glad", cleaned)
    cleaned = re.sub(r"(?i)\b(glad i could help)\.\s+anything\b", "Glad I could help. Anything", cleaned)
    cleaned = re.sub(r"(?<=[.!?])\s+([a-z])", lambda match: " " + match.group(1).upper(), cleaned)
    cleaned = re.sub(r"^([a-z])", lambda match: match.group(1).upper(), cleaned)
    cleaned = re.sub(r"(?m)^([a-z])", lambda match: match.group(1).upper(), cleaned)
    cleaned = re.sub(
        r"(?i)(^|(?<=[.!?]\s))((?:what|which|who|when|where|why|how|would|could|should|do|does|did|are|is)\b[^.?!\n]{4,})(?=$)",
        lambda match: f"{match.group(1)}{match.group(2).strip()}?",
        cleaned,
    )
    cleaned = re.sub(r"\s+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    stripped = cleaned.strip()
    if stripped and not re.search(r"(?m)([.!?]|[:])\s*$", stripped) and not re.search(r"(?m)^\s*(#{1,6}\s|[-*+]\s|\d+\.\s)", stripped.splitlines()[-1]):
        cleaned = stripped + "."
    else:
        cleaned = stripped
    return cleaned


def _split_inline_dash_bullets(text: str) -> str:
    if not text:
        return text
    rebuilt: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            rebuilt.append("")
            continue
        if stripped.startswith("- ") and " - " in stripped[2:]:
            parts = [part.strip(" -") for part in re.split(r"\s+-\s+", stripped[2:]) if part.strip()]
            if len(parts) >= 2:
                rebuilt.extend(f"- {part}" for part in parts)
                continue
        if stripped.startswith(("## ", "- ", "* ", "+ ")) or re.match(r"^\d+\.\s", stripped):
            rebuilt.append(stripped)
            continue
        if " - " in stripped:
            parts = [part.strip(" -") for part in re.split(r"\s+-\s+", stripped) if part.strip()]
            if len(parts) >= 2 and sum(1 for part in parts if part[:1].isupper() or part.lower().startswith("i ")) >= 2:
                rebuilt.extend(f"- {part}" for part in parts)
                continue
        rebuilt.append(stripped)
    return "\n".join(rebuilt).strip()


def _ensure_markdown_section_spacing(text: str) -> str:
    if not text:
        return text
    guarded = text.strip()
    for header in ("Insight", "Key Points", "Reflection", "Speak-Aloud Anchor", "Next Step", "Daily Check-In", "Weekly Check-In"):
        guarded = re.sub(rf"## {header}[ \t]*([^\n#].+)", rf"## {header}\n\n\1", guarded)
        guarded = re.sub(rf"## {header}\n(?!\n)", f"## {header}\n\n", guarded)
    return re.sub(r"\n{3,}", "\n\n", guarded).strip()


def _strip_unsupported_action_offers(text: str) -> str:
    if not text:
        return text
    blocked_phrases = [
        "linked debit card",
        "joint access",
        "external transfer",
        "linked bank transfer",
        "receipt emailed",
        "push notification",
        "i’ll confirm when it posts",
        "i will confirm when it posts",
        "it is processing",
        "it’s processing",
        "processing now",
        "processing shortly",
    ]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept: list[str] = []
    for sentence in sentences:
        lowered = sentence.lower()
        if any(phrase in lowered for phrase in blocked_phrases):
            continue
        kept.append(sentence)
    cleaned = " ".join(part.strip() for part in kept if part.strip()).strip()
    return cleaned


def _stop_after_clarifying_question(text: str) -> str:
    if not text:
        return text
    lower = text.lower()
    question_starters = [
        "quick question",
        "clarifying question",
        "question first",
        "would you like",
        "do you want",
        "which",
        "what",
        "when",
        "are you looking for",
        "should i",
        "would it help",
    ]
    stripped_lower = lower.strip()
    if not any(stripped_lower.startswith(marker) or stripped_lower.startswith(f"good. {marker}") for marker in question_starters):
        return text
    question_match = re.search(r".*?\?(?:\s|$)", text, re.S)
    if not question_match:
        return text
    cutoff = question_match.end()
    lead = text[:cutoff].strip()
    tail = text[cutoff:].strip()
    if not tail:
        return text
    if re.search(r"(^|\n)\s*(#{1,6}\s|[-*+]\s|\d+\.\s)", tail):
        return lead
    tail_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", tail) if s.strip()]
    if tail_sentences:
        return lead
    return text


def _enforce_markdown_structure(text: str) -> str:
    return (text or "").strip()


def _sentence_count(text: str) -> int:
    if not text:
        return 0
    return len([part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()])


def _light_cleanup(text: str) -> str:
    if not text:
        return text
    cleaned = _collapse_repeated_prompt_fragments(text)
    cleaned = _normalize_punctuation(cleaned)
    cleaned = _remove_off_brand_filler(cleaned)
    cleaned = _strip_unsupported_action_offers(cleaned)
    cleaned = _remove_repeated_sentences(cleaned)
    cleaned = _remove_near_duplicate_lines(cleaned)
    cleaned = _remove_repeated_clauses(cleaned)
    cleaned = _strip_disclaimers(cleaned)
    cleaned = _stop_after_clarifying_question(cleaned)
    cleaned = cleaned.strip()
    return cleaned


def _strip_legacy_response_phrases(text: str) -> str:
    if not text:
        return text
    cleaned = text
    cleaned = re.sub(r"##\s*(Insight|Key Points|Reflection)\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\b(Insight|Key Points|Reflection):\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"(?im)^\s*##\s*(Insight|Key Points|Reflection)\s*$\n?", "", cleaned)
    cleaned = re.sub(r"(?im)^\s*(Insight|Key Points|Reflection):\s*$\n?", "", cleaned)
    cleaned = re.sub(r"(?im)^\s*pick\s*2\s*[-–]\s*4\b.*$\n?", "", cleaned)
    cleaned = re.sub(r"(?im)^\s*here are a few affirmations:\s*\n?", "", cleaned)
    cleaned = re.sub(r"(?im)^\s*here are a few you can actually use without forcing the feeling\.\s*\n?", "", cleaned)
    cleaned = re.sub(r"(?im)^\s*here are a few\b.*$\n?", "", cleaned)
    cleaned = re.sub(r"(?im)^\s*nice\.\s*\n?", "", cleaned)
    cleaned = re.sub(r"(?i)\bfresh set\b", "", cleaned)
    cleaned = re.sub(r"(?i)\bfrom a different angle\b", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _response_authority_kind(message: str, history: list[dict[str, str]] | None, text: str) -> str:
    intent = _classify_content_intent(message, history)
    artifact = _detect_recent_content_artifact(history)
    lowered = (text or "").lower()
    if intent in {"praise", "reflective", "greeting", "reject", "unclear"}:
        return "general"
    if intent in {"request_visualization", "request_mindset_tools", "request_daily_practices"}:
        return "support"
    if (
        intent == "request_script"
        or artifact == "script"
        or "**script**" in lowered
        or "**shorter script**" in lowered
        or "speak-aloud anchor:" in lowered
        or "daily:" in lowered
        or "weekly:" in lowered
    ):
        return "script"
    if intent == "request_affirmations" or artifact == "affirmations":
        return "affirmations"
    return "general"


def _normalize_affirmation_reply(text: str) -> str:
    cleaned = _strip_legacy_response_phrases(text)
    cleaned = _split_inline_dash_bullets(cleaned)
    bullet_lines = [line.strip() for line in cleaned.splitlines() if line.strip().startswith("- ")]
    normalized_bullets: list[str] = []
    for line in bullet_lines:
        body = line[2:].strip()
        if re.search(r"\bI\b", body) and not body.startswith("I "):
            body = body[body.find("I ") :].strip()
        normalized_bullets.append(f"- {body}")
    bullet_lines = normalized_bullets
    if not bullet_lines:
        fragments: list[str] = []
        for part in re.split(r"(?<=[.!?])\s+|\n+", cleaned):
            stripped = part.strip(" -")
            if not stripped or stripped.endswith("?"):
                continue
            if stripped.lower().startswith(("speak-aloud anchor", "next step", "daily:", "weekly:", "adjustments:")):
                continue
            fragments.append(stripped.rstrip(".") + ".")
        bullet_lines = [f"- {item}" for item in fragments[:5]]
    deduped: list[str] = []
    seen: set[str] = set()
    for line in bullet_lines:
        key = re.sub(r"[^a-z0-9]+", " ", line.lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(line)
    return "\n".join(deduped[:5]).strip()


def _sanitize_general_reply(text: str) -> str:
    cleaned = _strip_legacy_response_phrases(text)
    if re.search(r"(?m)^\s*-\s", cleaned):
        return "\n".join(line.strip() for line in cleaned.splitlines() if line.strip()).strip()
    cleaned = _ensure_markdown_section_spacing(cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _sanitize_script_reply(text: str) -> str:
    cleaned = _strip_legacy_response_phrases(text)
    cleaned = _split_inline_dash_bullets(cleaned)
    lines = [line.rstrip() for line in cleaned.splitlines()]
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if kept and kept[-1] != "":
                kept.append("")
            continue
        if stripped in {"**Script**", "**Shorter Script**"}:
            kept.append(stripped)
            continue
        if stripped.lower().startswith(("script:", "daily:", "weekly:", "adjustments:", "speak-aloud anchor:", "next step:")):
            kept.append(stripped)
            continue
        if stripped.startswith("- "):
            kept.append(stripped)
            continue
        if stripped.endswith("?"):
            kept.append(stripped)
            continue
        kept.append(stripped)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept).strip())


def _sanitize_support_reply(text: str) -> str:
    cleaned = _strip_legacy_response_phrases(text)
    cleaned = _split_inline_dash_bullets(cleaned)
    lines = [line.rstrip() for line in cleaned.splitlines()]
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if kept and kept[-1] != "":
                kept.append("")
            continue
        kept.append(stripped)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept).strip())


async def _proof_final_reply(text: str, *, short_mode: bool = False) -> str:
    stripped = (text or "").strip()
    if not stripped:
        return ""
    return re.sub(r"\n{3,}", "\n\n", stripped).strip()


async def _final_response_authority(
    message: str,
    text: str,
    history: list[dict[str, str]] | None = None,
    *,
    short_mode: bool = False,
) -> str:
    stripped = (text or "").strip()
    if not stripped:
        return ""
    kind = _response_authority_kind(message, history, stripped)
    if kind == "support":
        return _sanitize_support_reply(stripped)
    if kind == "script":
        return _sanitize_script_reply(stripped)
    if kind == "affirmations":
        return _normalize_affirmation_reply(stripped)
    proofed = await _copyedit_reply(stripped, short_mode=short_mode)
    proofed = _light_cleanup(proofed)
    proofed = _sanitize_general_reply(proofed)
    return proofed


def _should_use_local_rescue(message: str, history: list[dict[str, str]] | None = None) -> bool:
    intent = _classify_content_intent(message, history)
    recent_assistant = _recent_assistant_context(history)
    if _resolve_script_scope(message, history) and any(
        _assistant_recently_requested_script_details((item.get("content") or ""))
        for item in (history or [])
        if item.get("role") == "assistant"
    ):
        return True
    if intent in {
        "alternate_affirmations",
        "shorten",
        "strengthen",
        "rewrite",
        "approve_rewrite",
        "shift_first_person",
    }:
        if intent in {"shorten", "strengthen", "rewrite", "approve_rewrite", "shift_first_person"}:
            return _detect_recent_content_artifact(history) != "none"
        return True
    if intent == "request_affirmations":
        return True
    if intent == "request_script":
        return True
    if intent in {"request_visualization", "request_mindset_tools", "request_daily_practices"}:
        return True
    if intent == "general_money_manifestation":
        return _is_manifest_money_request(message) or _is_combined_money_support_request(message) or _is_support_template_context(history)
    if _assistant_recently_requested_script_details(recent_assistant):
        if _resolve_script_scope(message, history):
            return True
        if _is_impatient_delivery_request(message):
            return True
    if intent == "another_variant":
        return _detect_recent_content_artifact(history) in {"affirmations", "script", "story"}
    if _assistant_recently_requested_affirmation_style(recent_assistant) and _is_short_followup(message):
        return True
    return False


async def generate_teller_reply(
    user_id: int,
    message: str,
    history: list[dict[str, str]] | None = None,
    short_mode: bool = False,
) -> tuple[bool, str]:
    started_at = time.perf_counter()
    repeat_count = _get_repeat_count(message, history)

    if _should_short_circuit_neutral_assist(message, history):
        return False, await _final_response_authority(message, _local_rescue_reply(message, history=history), history=history, short_mode=short_mode)
    if _should_use_local_rescue(message, history):
        return False, await _final_response_authority(message, _local_rescue_reply(message, history=history), history=history, short_mode=short_mode)

    provider = (settings.TELLER_PROVIDER or "stub").lower()
    llm_started_at = time.perf_counter()
    if provider == "openai":
        reply = await _openai_response(message, history=history, short_mode=short_mode, repeat_count=repeat_count)
    else:
        reply = "How can I help you today?"
    llm_done_at = time.perf_counter()

    if reply and len(reply) > settings.TELLER_MAX_CHARS:
        reply = _trim_to_full_sentence(reply, settings.TELLER_MAX_CHARS)

    if not reply or not reply.strip() or _is_retry_placeholder(reply):
        reply = _local_rescue_reply(message, history=history)
    copyedit_started_at = time.perf_counter()
    reply = await _final_response_authority(message, reply, history=history, short_mode=short_mode)
    copyedit_done_at = time.perf_counter()
    cleanup_done_at = copyedit_done_at
    logger.info(
        "teller_provider_timing mode=generate provider=%s message=%r total_ms=%d llm_ms=%d copyedit_ms=%d cleanup_ms=%d",
        provider,
        message[:120],
        int((cleanup_done_at - started_at) * 1000),
        int((llm_done_at - llm_started_at) * 1000),
        int((copyedit_done_at - copyedit_started_at) * 1000),
        int((cleanup_done_at - copyedit_done_at) * 1000),
    )
    return False, reply


async def stream_teller_reply(
    user_id: int,
    message: str,
    history: list[dict[str, str]] | None = None,
    short_mode: bool = False,
    on_delta: Any | None = None,
) -> tuple[bool, str]:
    started_at = time.perf_counter()
    repeat_count = _get_repeat_count(message, history)

    if _should_short_circuit_neutral_assist(message, history):
        return False, await _final_response_authority(message, _local_rescue_reply(message, history=history), history=history, short_mode=short_mode)
    if _should_use_local_rescue(message, history):
        return False, await _final_response_authority(message, _local_rescue_reply(message, history=history), history=history, short_mode=short_mode)

    provider = (settings.TELLER_PROVIDER or "stub").lower()
    llm_started_at = time.perf_counter()
    if provider == "openai":
        reply = await _openai_response_stream(
            message,
            history=history,
            short_mode=short_mode,
            on_delta=on_delta,
            repeat_count=repeat_count,
        )
        if _is_retry_placeholder(reply):
            reply = await _openai_response(message, history=history, short_mode=short_mode, repeat_count=repeat_count)
    else:
        reply = "How can I help you today?"
    llm_done_at = time.perf_counter()

    if reply and len(reply) > settings.TELLER_MAX_CHARS:
        reply = _trim_to_full_sentence(reply, settings.TELLER_MAX_CHARS)

    if not reply or not reply.strip() or _is_retry_placeholder(reply):
        reply = _local_rescue_reply(message, history=history)
    copyedit_started_at = time.perf_counter()
    reply = await _final_response_authority(message, reply, history=history, short_mode=short_mode)
    copyedit_done_at = time.perf_counter()
    cleanup_done_at = copyedit_done_at
    logger.info(
        "teller_provider_timing mode=stream provider=%s message=%r total_ms=%d llm_ms=%d copyedit_ms=%d cleanup_ms=%d",
        provider,
        message[:120],
        int((cleanup_done_at - started_at) * 1000),
        int((llm_done_at - llm_started_at) * 1000),
        int((copyedit_done_at - copyedit_started_at) * 1000),
        int((cleanup_done_at - copyedit_done_at) * 1000),
    )
    return False, reply
