# app/routes/teller.py

import asyncio
import json
from datetime import datetime, UTC
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
import re
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.security import get_verified_user
from app.core.config import settings
import time
from app.db.session import get_db
from app.models.user import User
from app.models.teller import TellerThread, TellerMessage, TellerAuditLog
from app.models.account import Account
from app.crud.crud_ledger import create_ledger_entry, get_account_balance, create_transfer
from app.schemas.ledger import LedgerEntryCreate
from app.schemas.scheduled_entry import ScheduledEntryCreate
from app.crud.crud_scheduled_entry import create_scheduled_entry
from app.schemas.account import AccountCreate
from app.crud.crud_account import create_account, get_account, update_account_fields
from app.schemas.teller import (
    TellerThreadCreate,
    TellerThreadRead,
    TellerMessageRead,
    TellerChatRequest,
    TellerChatResponse,
    TellerConfirmRequest,
    TellerConfirmResponse,
    TellerExecuteRequest,
    TellerExecuteResponse,
    TellerStatusResponse,
    TellerThreadUpdate,
)
from app.services.teller_provider import generate_teller_reply, rate_limiter, set_persona_override, stream_teller_reply
try:
    from app.services.credit import record_credit_action, ensure_credit_actions
except Exception:  # Credit module not available in local Teller-only mode
    def ensure_credit_actions(db: Session) -> None:
        return

    def record_credit_action(db: Session, user_id: int, action_type: str) -> None:
        return
import httpx
from app.services.fx import convert_amount_with_rate

router = APIRouter(tags=["teller"])
STREAM_REPLY_TIMEOUT_SECONDS = 30
STREAM_IDLE_TIMEOUT_SECONDS = 12

CONFIRM_WORDS = {
    "yes",
    "y",
    "yea",
    "yeah",
    "yep",
    "confirm",
    "confirmed",
    "correct",
    "do it",
    "approve",
    "ok",
    "okay",
    "proceed",
    "sure",
    "thats right",
    "that's right",
}
CANCEL_WORDS = {"no", "n", "cancel", "stop", "never mind", "nevermind"}
EDIT_CONFIRMATION_PATTERNS = (
    "change",
    "different",
    "instead",
    "switch",
    "use ",
    "make it ",
    "not ",
)
NO_PARENT_WORDS = {"no", "none", "nope", "skip", "not now"}
ACCOUNT_POINTING_WORDS = {
    "that one",
    "this one",
    "that account",
    "this account",
    "the account",
    "just put it into the account",
    "put it into the account",
    "into that account",
    "into this account",
}
THANKS_WORDS = {"thanks", "thank you", "thx", "ty", "appreciate it"}
HISTORY_REFERENCE_WORDS = {
    "check history",
    "check your history",
    "check ur history",
    "weve talked about it",
    "we've talked about it",
    "we talked about it",
    "you know what i mean",
    "the new account",
    "that new account",
}
REPEAT_LAST_ACTION_WORDS = {
    "again",
    "another one",
    "one more",
    "do that again",
    "do that again please",
    "repeat that",
    "repeat that transfer",
    "repeat that deposit",
    "repeat that withdrawal",
}


def _is_confirm_message(message: str) -> bool:
    return _classify_confirmation_intent(message) == "approve"


def _is_strict_confirm_message(message: str) -> bool:
    lower_msg = message.lower().strip()
    normalized = re.sub(r"[^\w\s]", "", lower_msg).strip()
    if lower_msg in CONFIRM_WORDS or normalized in CONFIRM_WORDS:
        return True
    if lower_msg.startswith(("yes ", "yeah ", "yep ", "confirm ", "confirmed", "approve ", "approved", "proceed ", "do it ", "correct ", "thats right", "that's right")):
        return True
    if lower_msg in {"confirmed", "onfirmed", "affirmative", "correct"}:
        return True
    return lower_msg.startswith("onfirm")


def _is_cancel_message(message: str) -> bool:
    return _classify_confirmation_intent(message) == "reject"


def _build_cancel_reply(action: str | None) -> str:
    if action == "transfer":
        return "Got it. I canceled that transfer."
    if action == "deposit":
        return "Okay, that deposit is canceled."
    if action == "withdraw":
        return "Understood. I stopped that withdrawal."
    if action == "schedule":
        return "Okay, I canceled that scheduled movement."
    if action == "create_account":
        return "Okay, I canceled that account setup."
    if action == "rename_account":
        return "Got it. I canceled that rename."
    if action == "archive_account":
        return "Okay, I canceled that archive request."
    if action == "unarchive_account":
        return "Okay, I canceled that restore request."
    if action == "change_account_currency":
        return "Understood. I canceled that currency change."
    return "Understood. I stopped that action."


def _build_confirmation_clarify_reply(action: str | None) -> str:
    label = {
        "transfer": "transfer",
        "deposit": "deposit",
        "withdraw": "withdrawal",
        "schedule": "scheduled movement",
        "create_account": "account setup",
        "rename_account": "rename",
        "archive_account": "archive",
        "unarchive_account": "restore",
        "change_account_currency": "currency change",
    }.get(action, "action")
    return f"Did you want me to confirm this {label}?"


def _normalize_confirmation_text(message: str) -> str:
    lowered = (message or "").lower().strip()
    lowered = lowered.replace("’", "'")
    lowered = re.sub(r"[^\w\s']+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


def _classify_confirmation_intent(message: str) -> str:
    normalized = _normalize_confirmation_text(message)
    compact = normalized.replace(" ", "")
    if not normalized:
        return "unclear"

    reject_phrases = {
        "no",
        "n",
        "cancel",
        "stop",
        "never mind",
        "nevermind",
        "wait",
        "hold on",
        "not that",
        "wrong",
        "nope",
    }
    edit_phrases = {
        "change the amount",
        "different account",
        "use a different account",
        "switch accounts",
        "make it",
        "from",
        "use",
    }
    approve_phrases = {
        *CONFIRM_WORDS,
        "confirmed",
        "affirmative",
        "exactly",
        "perfect",
        "sounds good",
        "looks good",
        "that works",
        "right",
        "kk",
        "go ahead",
        "let's do it",
        "lets do it",
        "absolutely",
        "please do",
        "fine",
        "yesss",
    }

    if normalized in reject_phrases or normalized.startswith(("no ", "cancel ", "stop ", "wait ", "hold on")):
        return "reject"
    if any(phrase in normalized for phrase in edit_phrases) or any(token in normalized for token in EDIT_CONFIRMATION_PATTERNS):
        if normalized not in approve_phrases:
            return "edit"
    if normalized in approve_phrases:
        return "approve"
    if normalized.startswith(
        (
            "yes ",
            "yeah ",
            "yep ",
            "confirm ",
            "confirmed",
            "approve ",
            "approved",
            "proceed ",
            "do it ",
            "correct ",
            "thats right",
            "that's right",
            "sounds good",
            "looks good",
            "go ahead",
            "please do",
        )
    ):
        return "approve"
    if normalized.startswith("onfirm"):
        return "approve"
    if compact in {"cionfirmed", "cionfirm", "onfirmed", "onfirm"}:
        return "approve"
    if len(compact) >= 5 and (
        SequenceMatcher(None, compact, "confirm").ratio() >= 0.82
        or SequenceMatcher(None, compact, "confirmed").ratio() >= 0.82
    ):
        return "approve"
    if re.search(r"\b(go ahead|do it|proceed|please do|sounds good|looks good|that works|that's right|thats right)\b", normalized):
        return "approve"
    if compact in {"ye", "yea", "yep", "yup", "yas", "yese", "yess", "yesss", "correc", "confim", "confrim"}:
        return "approve"
    short_approve_targets = ("yes", "yep", "yup", "okay", "ok", "correct", "confirm", "confirmed")
    for target in short_approve_targets:
        if SequenceMatcher(None, compact, target).ratio() >= (0.75 if len(compact) > 3 else 0.66):
            return "approve"
    return "unclear"


def _looks_like_confirmation_typo(message: str) -> bool:
    normalized = _normalize_confirmation_text(message)
    compact = normalized.replace(" ", "")
    if not compact or _classify_confirmation_intent(message) != "unclear":
        return False
    targets = ("yes", "yep", "yup", "confirm", "confirmed", "correct", "okay")
    return any(SequenceMatcher(None, compact, target).ratio() >= 0.62 for target in targets)


def _is_thanks_message(message: str) -> bool:
    lower_msg = re.sub(r"[.!?,]+", "", message.lower()).strip()
    return lower_msg in THANKS_WORDS


def _is_repeat_last_action_request(message: str) -> bool:
    normalized = _normalize_confirmation_text(message)
    return normalized in REPEAT_LAST_ACTION_WORDS or normalized.startswith(("do that again", "repeat that", "again "))


def _get_recent_executed_action(db: Session, user_id: int, thread_id: int | None) -> TellerAuditLog | None:
    if not thread_id:
        return None
    audits = (
        db.query(TellerAuditLog)
        .filter(
            TellerAuditLog.user_id == user_id,
            TellerAuditLog.thread_id == thread_id,
            TellerAuditLog.action_type == "pending_action",
            TellerAuditLog.status == "executed",
        )
        .order_by(TellerAuditLog.created_at.desc())
        .limit(8)
        .all()
    )
    for audit in audits:
        if (audit.action_payload or {}).get("action") in {"transfer", "deposit", "withdraw"}:
            return audit
    return None


def _mentions_history_or_prior_context(message: str) -> bool:
    lower_msg = re.sub(r"\s+", " ", message.lower()).strip()
    return any(phrase in lower_msg for phrase in HISTORY_REFERENCE_WORDS)

def _is_action_phrase(message: str) -> bool:
    msg = message.lower()
    return any(
        phrase in msg
        for phrase in ["create account", "new account", "open account", "open new account", "add account", "another account", "account open"]
    )


def _looks_like_pending_followup(action: str | None, message: str) -> bool:
    lower_msg = message.lower().strip()
    if not lower_msg:
        return False
    if _classify_confirmation_intent(message) in {"approve", "reject", "edit"} or lower_msg in NO_PARENT_WORDS:
        return True
    if lower_msg in ACCOUNT_POINTING_WORDS:
        return True
    if _parse_account_id(message) is not None:
        return True
    if action == "schedule":
        return bool(_extract_amount(lower_msg) or _parse_date(lower_msg) or "schedule" in lower_msg or "scheduled" in lower_msg)
    if action in {"deposit", "withdraw"}:
        return bool(
            _extract_amount(lower_msg)
            or re.search(r"\b(from|to|into)\b", lower_msg)
            or lower_msg in ACCOUNT_POINTING_WORDS
            or len(lower_msg.split()) <= 4
        )
    if action == "transfer":
        return bool(
            _extract_amount(lower_msg)
            or re.search(r"\b(from|to|into)\b", lower_msg)
            or lower_msg in ACCOUNT_POINTING_WORDS
            or len(lower_msg.split()) <= 6
        )
    if action in {"rename_account", "change_account_currency", "archive_account", "unarchive_account", "create_account"}:
        return len(lower_msg.split()) <= 8 or bool(_parse_currency_code(message) or _parse_account_type(message) or _parse_new_name(message))
    return False


def _pending_confirmation_ready(pending: TellerAuditLog | None) -> bool:
    if not pending or pending.status != "pending":
        return False
    payload = pending.action_payload or {}
    action = payload.get("action")
    if action in {"deposit", "withdraw"}:
        return bool(payload.get("account_id") and payload.get("amount"))
    if action == "transfer":
        return bool(payload.get("from_account_id") and payload.get("to_account_id") and payload.get("amount"))
    if action == "schedule":
        return bool(payload.get("account_id") and payload.get("amount") and payload.get("scheduled_for"))
    if action == "create_account":
        if not payload.get("name") or not payload.get("account_type"):
            return False
        if payload.get("starting_balance_prompted") and payload.get("starting_balance") is None:
            return False
        return True
    if action == "rename_account":
        return bool(payload.get("account_id") and payload.get("new_name"))
    if action == "change_account_currency":
        return bool(payload.get("account_id") and payload.get("currency"))
    if action in {"archive_account", "unarchive_account"}:
        return bool(payload.get("account_id"))
    return False


def _reconfirm_pending_action(pending: TellerAuditLog, db: Session, user_id: int) -> str:
    payload = pending.action_payload or {}
    action = payload.get("action")
    if action == "deposit":
        acct_name = payload.get("account_name")
        amount = Decimal(str(payload.get("amount") or "0"))
        if not acct_name:
            return "Which account should I use?\n" + _format_accounts(_list_accounts(db, user_id))
        return f"Confirm deposit {_format_money(amount, payload.get('currency') or 'USD')} into “{acct_name}”?"
    if action == "withdraw":
        acct_name = payload.get("account_name")
        amount = Decimal(str(payload.get("amount") or "0"))
        if not acct_name:
            return "Which account should I use?\n" + _format_accounts(_list_accounts(db, user_id))
        return f"Confirm withdrawal of {_format_money(amount, payload.get('currency') or 'USD')} from “{acct_name}”?"
    if action == "transfer":
        amount = Decimal(str(payload.get("amount") or "0"))
        from_name = payload.get("from_account_name")
        to_name = payload.get("to_account_name")
        if not from_name:
            return "Which account should I transfer from?\n" + _format_accounts(_list_accounts(db, user_id))
        if not to_name:
            accounts = [acct for acct in _list_accounts(db, user_id) if acct["id"] != payload.get("from_account_id")]
            return "Which account should I transfer to?\n" + _format_accounts(accounts)
        return f"Confirm transfer {_format_money(amount, payload.get('currency') or 'USD')} from “{from_name}” to “{to_name}”?"
    if action == "schedule":
        amount = Decimal(str(payload.get("amount") or "0"))
        acct_name = payload.get("account_name")
        scheduled_for = payload.get("scheduled_for")
        if not acct_name:
            return "Which account should I use?\n" + _format_accounts(_list_accounts(db, user_id))
        if not scheduled_for:
            return "When should I schedule it? (YYYY-MM-DD or YYYY-MM-DD HH:MM)"
        return f"Confirm schedule {_format_money(amount, payload.get('currency') or 'USD')} for “{acct_name}” on {scheduled_for}?"
    if action == "create_account":
        name = payload.get("name")
        account_type = payload.get("account_type")
        currency = (payload.get("currency") or "USD").upper()
        starting_balance = payload.get("starting_balance")
        if starting_balance and Decimal(str(starting_balance)) > 0:
            return (
                f"Confirm create account “{name}” ({account_type}, {currency}) "
                f"with starting balance {_format_money(Decimal(str(starting_balance)), currency)}?"
            )
        return f"Confirm create account “{name}” ({account_type}, {currency})?"
    return f"Confirm {_format_action_label(action)}?"


def _build_transfer_followup_reply(
    db: Session,
    user_id: int,
    thread_id: int,
    clause: str,
) -> str | None:
    accounts = _list_accounts(db, user_id)
    amount = _extract_amount(clause)
    explicit_from, explicit_to = _parse_transfer_account_phrase(clause, accounts)
    account_hint = _match_account(clause, accounts)
    if not amount:
        pending = TellerAuditLog(
            user_id=user_id,
            thread_id=thread_id,
            action_type="pending_action",
            status="awaiting_amount",
            action_payload={"action": "transfer", "memo": "Teller transfer", "transfer_stage": "from"},
        )
        db.add(pending)
        db.commit()
        return "Next: what amount should I transfer?"
    if explicit_from and explicit_to:
        pending = TellerAuditLog(
            user_id=user_id,
            thread_id=thread_id,
            action_type="pending_action",
            status="pending",
            action_payload={
                "action": "transfer",
                "amount": str(amount),
                "from_account_id": explicit_from["id"],
                "from_account_name": explicit_from["name"],
                "to_account_id": explicit_to["id"],
                "to_account_name": explicit_to["name"],
                "currency": explicit_from.get("currency") or "USD",
                "memo": "Teller transfer",
                "transfer_stage": "to",
            },
        )
        db.add(pending)
        db.commit()
        return (
            f"Next: confirm transfer {_format_money(amount, explicit_from.get('currency', 'USD'))} "
            f"from “{explicit_from['name']}” to “{explicit_to['name']}”?"
        )
    payload = {"action": "transfer", "amount": str(amount), "memo": "Teller transfer", "transfer_stage": "from"}
    if explicit_from:
        payload.update({"from_account_id": explicit_from["id"], "from_account_name": explicit_from["name"], "currency": explicit_from.get("currency") or "USD"})
        status_value = "awaiting_account"
        prompt = (
            f"Next: which account should I transfer {_format_money(amount, payload.get('currency') or 'USD')} to?\n"
            + _format_accounts([acct for acct in accounts if acct["id"] != explicit_from["id"]])
        )
    elif account_hint:
        payload.update({"to_account_id": account_hint["id"], "to_account_name": account_hint["name"]})
        status_value = "awaiting_account"
        prompt = (
            f"Next: which account should I transfer {_format_money(amount)} from?\n"
            + _format_accounts([acct for acct in accounts if acct["id"] != account_hint["id"]])
        )
    else:
        status_value = "awaiting_account"
        prompt = f"Next: which account should I transfer {_format_money(amount)} from?\n" + _format_accounts(accounts)
    pending = TellerAuditLog(
        user_id=user_id,
        thread_id=thread_id,
        action_type="pending_action",
        status=status_value,
        action_payload=payload,
    )
    db.add(pending)
    db.commit()
    return prompt


def _handle_pending_confirmation_edit(
    pending: TellerAuditLog,
    message: str,
    db: Session,
    user_id: int,
) -> str | None:
    payload = pending.action_payload or {}
    action = payload.get("action")
    lower_msg = message.lower().strip()
    amount = _extract_amount(message)
    accounts = _list_accounts(db, user_id)

    if action in {"deposit", "withdraw", "schedule"}:
        if amount is not None:
            pending.action_payload = {**payload, "amount": str(amount)}
            db.add(pending)
            db.commit()
            return _reconfirm_pending_action(pending, db, user_id)
        acct = _match_account(message, accounts)
        if acct:
            pending.action_payload = {
                **payload,
                "account_id": acct["id"],
                "account_name": acct["name"],
                "currency": acct.get("currency") or payload.get("currency") or "USD",
            }
            db.add(pending)
            db.commit()
            return _reconfirm_pending_action(pending, db, user_id)
        if "amount" in lower_msg or "make it" in lower_msg:
            return "What amount should I use instead?"
        if "account" in lower_msg or "use " in lower_msg:
            return "Which account should I use instead?\n" + _format_accounts(accounts)
        return "What should I change: the amount or the account?"

    if action == "transfer":
        next_payload = dict(payload)
        if amount is not None:
            next_payload["amount"] = str(amount)
        currency_code = _parse_currency_code(message)
        next_payload, currency_prompt = _apply_transfer_currency_update(next_payload, currency_code, accounts)
        explicit_source, explicit_destination = _parse_transfer_account_phrase(message, accounts)
        if explicit_source:
            next_payload["from_account_id"] = explicit_source["id"]
            next_payload["from_account_name"] = explicit_source["name"]
            next_payload["currency"] = next_payload.get("currency") or explicit_source.get("currency") or "USD"
        if explicit_destination:
            next_payload["to_account_id"] = explicit_destination["id"]
            next_payload["to_account_name"] = explicit_destination["name"]
        single_match = _match_account(message, accounts)
        if single_match and not explicit_source and not explicit_destination:
            if "to " in lower_msg or "into " in lower_msg:
                next_payload["to_account_id"] = single_match["id"]
                next_payload["to_account_name"] = single_match["name"]
            elif "from " in lower_msg or "use " in lower_msg or "instead" in lower_msg:
                next_payload["from_account_id"] = single_match["id"]
                next_payload["from_account_name"] = single_match["name"]
                next_payload["currency"] = next_payload.get("currency") or single_match.get("currency") or "USD"
            elif not next_payload.get("from_account_id"):
                next_payload["from_account_id"] = single_match["id"]
                next_payload["from_account_name"] = single_match["name"]
                next_payload["currency"] = next_payload.get("currency") or single_match.get("currency") or "USD"
            else:
                next_payload["to_account_id"] = single_match["id"]
                next_payload["to_account_name"] = single_match["name"]
        pending.action_payload = next_payload
        if next_payload.get("amount") and next_payload.get("from_account_id") and next_payload.get("to_account_id"):
            pending.status = "pending"
        elif next_payload.get("amount"):
            pending.status = "awaiting_account"
        db.add(pending)
        db.commit()
        if currency_prompt:
            return currency_prompt
        if amount is not None or explicit_source or explicit_destination or single_match:
            return _reconfirm_pending_action(pending, db, user_id)
        if "different account" in lower_msg or "use a different account" in lower_msg or "switch accounts" in lower_msg:
            return "Which account should I transfer from?\n" + _format_accounts(accounts)
        if "amount" in lower_msg or "make it" in lower_msg:
            return "What amount should I use instead?"
        if "from" in lower_msg or "source" in lower_msg:
            return "Which account should I transfer from?\n" + _format_accounts(accounts)
        if "to" in lower_msg or "into" in lower_msg or "destination" in lower_msg:
            return "Which account should I transfer to?\n" + _format_accounts(accounts)
        return "What should I change: the amount, the source account, or the destination account?"

    if action == "create_account":
        updated_payload = dict(payload)
        next_name = _parse_account_name(message)
        next_type = _parse_account_type(message)
        next_currency = _parse_currency_code(message)
        if next_name:
            updated_payload["name"] = next_name
        if next_type:
            updated_payload["account_type"] = next_type
        if next_currency:
            updated_payload["currency"] = next_currency
        if amount is not None:
            updated_payload["starting_balance"] = str(amount)
        pending.action_payload = updated_payload
        db.add(pending)
        db.commit()
        if next_name or next_type or next_currency or amount is not None:
            return _reconfirm_pending_action(pending, db, user_id)
        return "What should I change: the name, type, currency, or starting balance?"

    return "What should I change?"

def _is_negated_transfer(message: str) -> bool:
    msg = message.lower()
    return bool(
        re.search(r"\b(no|not|dont|don't|didn't|did not)\b.*\btransfer\b", msg)
        or re.search(r"\btransfer\b.*\b(no|not|dont|don't|didn't|did not)\b", msg)
    )


def _contains_transfer_intent(message: str) -> bool:
    if not message:
        return False
    lowered = message.lower()
    words = re.findall(r"\b[a-z]+\b", lowered)
    for word in words:
        if word == "transfer":
            return True
        if len(word) >= 5 and SequenceMatcher(None, word, "transfer").ratio() >= 0.82:
            return True
    return False


def _is_content_interrupt_request(message: str) -> bool:
    lowered = re.sub(r"\s+", " ", (message or "").lower()).strip()
    if not lowered:
        return False
    if any(token in lowered for token in ("script", "affirmation", "affirmations", "reset", "meditation", "breathing", "future success story")):
        return True
    words = re.findall(r"\b[a-z]+\b", lowered)
    return any(SequenceMatcher(None, word, "script").ratio() >= 0.72 for word in words)


def _is_switch_tasks_request(message: str) -> bool:
    lowered = re.sub(r"\s+", " ", (message or "").lower()).strip()
    return "switch tasks" in lowered or "switch" == lowered


def _extract_multi_action_followup(message: str) -> str | None:
    lowered = re.sub(r"\s+", " ", (message or "").strip())
    separators = (" then ", ". then ", " and then ")
    for separator in separators:
        if separator in lowered.lower():
            parts = re.split(re.escape(separator.strip()), lowered, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2:
                followup = parts[1].strip(" .")
                return followup or None
    transfer_idx = lowered.lower().find(" transfer ")
    deposit_idx = lowered.lower().find(" deposit ")
    if deposit_idx != -1 and transfer_idx != -1 and transfer_idx > deposit_idx:
        return lowered[transfer_idx + 1 :].strip(" .")
    return None


def _extract_primary_action_clause(message: str) -> str:
    lowered = re.sub(r"\s+", " ", (message or "").strip())
    lowered_comp = lowered.lower()
    for marker in (" then ", " and then "):
        idx = lowered_comp.find(marker)
        if idx != -1:
            return lowered[:idx].strip(" .")
    transfer_idx = lowered_comp.find(" transfer ")
    deposit_idx = lowered_comp.find("deposit")
    if deposit_idx != -1 and transfer_idx != -1 and transfer_idx > deposit_idx:
        return lowered[:transfer_idx].strip(" .")
    return lowered


def _account_match_candidates(message: str, accounts: list[dict]) -> list[tuple[float, dict]]:
    msg = re.sub(r"\s+", " ", message.lower()).strip()
    if not msg:
        return []
    normalized_msg = re.sub(r"[^a-z0-9\s]", " ", msg)
    normalized_msg = re.sub(r"\s+", " ", normalized_msg).strip()
    candidates: list[tuple[float, dict]] = []
    for acct in accounts:
        name = acct["name"].lower()
        normalized_name = re.sub(r"[^a-z0-9\s]", " ", name)
        normalized_name = re.sub(r"\s+", " ", normalized_name).strip()
        score = 0.0
        if name and name in msg:
            score = 1.0
        elif normalized_msg and normalized_name:
            if normalized_msg in normalized_name or normalized_name in normalized_msg:
                score = 0.96
            else:
                score = SequenceMatcher(None, normalized_msg, normalized_name).ratio()
        if score >= 0.8:
            candidates.append((score, acct))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates


def _select_single_account_match(message: str, accounts: list[dict]) -> dict | None:
    candidates = _account_match_candidates(message, accounts)
    if not candidates:
        return None
    best_score, best_match = candidates[0]
    if len(candidates) > 1 and abs(best_score - candidates[1][0]) < 0.03:
        return None
    return best_match


def _find_alias_account_match(message: str, accounts: list[dict]) -> dict | None:
    lowered = re.sub(r"\s+", " ", message.lower()).strip()
    if not lowered:
        return None
    if "uk account" in lowered:
        gbp_accounts = [acct for acct in accounts if (acct.get("currency") or "USD").upper() == "GBP"]
        return gbp_accounts[0] if len(gbp_accounts) == 1 else None
    if "main account" in lowered:
        wealth_builder_accounts = [acct for acct in accounts if acct.get("account_type") == "wealth_builder"]
        if len(wealth_builder_accounts) == 1:
            return wealth_builder_accounts[0]
        return accounts[0] if len(accounts) == 1 else None
    return None


def _parse_transfer_account_phrase(message: str, accounts: list[dict]) -> tuple[dict | None, dict | None]:
    lowered = re.sub(r"\s+", " ", message.lower()).strip()
    if not lowered:
        return None, None

    explicit = re.search(r"\bfrom\s+(.+?)\s+(?:to|into)\s+(.+)$", lowered)
    if explicit:
        source = _match_account(explicit.group(1), accounts)
        destination = _match_account(explicit.group(2), accounts)
        return source, destination

    between = re.search(r"(.+?)\s+\bto\b\s+(.+)", lowered)
    if between and "what amount" not in lowered:
        source = _match_account(between.group(1), accounts)
        destination = _match_account(between.group(2), accounts)
        if source or destination:
            return source, destination

    return None, None


def _looks_like_transfer_update(message: str, accounts: list[dict]) -> bool:
    lowered = re.sub(r"\s+", " ", (message or "").lower()).strip()
    if not lowered:
        return False
    if re.search(r"\b#?\d+\s+to\s+#?\d+\b", lowered):
        return False
    if _extract_amount(message) is not None or _parse_currency_code(message):
        return True
    explicit_from, explicit_to = _parse_transfer_account_phrase(message, accounts)
    if explicit_from or explicit_to:
        return True
    if _match_account(message, accounts):
        return True
    update_markers = (
        "make it",
        "instead",
        "use ",
        "not that one",
        "not dollars",
        "not usd",
        "pounds",
        "gbp",
        "dollars",
        "usd",
        "eur",
    )
    return any(marker in lowered for marker in update_markers)


def _apply_transfer_currency_update(
    payload: dict,
    currency_code: str | None,
    accounts: list[dict],
) -> tuple[dict, str | None]:
    next_payload = dict(payload)
    if not currency_code:
        return next_payload, None
    next_payload["currency"] = currency_code
    from_id = next_payload.get("from_account_id")
    if from_id:
        source = next((acct for acct in accounts if acct["id"] == from_id), None)
        if source and (source.get("currency") or "USD").upper() != currency_code:
            next_payload.pop("from_account_id", None)
            next_payload.pop("from_account_name", None)
            next_payload["transfer_stage"] = "from"
            gbp_or_requested = [acct for acct in accounts if (acct.get("currency") or "USD").upper() == currency_code]
            return next_payload, f"Which {currency_code} account should I transfer from?\n" + _format_accounts(gbp_or_requested or accounts)
    return next_payload, None

ACCOUNT_TYPES: dict[str, str] = {
    "personal": "personal",
    "family office": "family_office",
    "family_office": "family_office",
    "trust": "trust",
    "estate": "estate",
    "foundation": "foundation",
    "holding": "holding",
    "holding company": "holding",
    "investment": "investment",
    "private investment": "investment",
    "entity": "entity",
    "operating": "operating",
    "wealth builder": "wealth_builder",
    "wealth_builder": "wealth_builder",
}

def _format_account_types() -> str:
    labels = [
        "Personal",
        "Family Office",
        "Trust",
        "Estate",
        "Foundation",
        "Holding Company",
        "Private Investment",
        "Entity",
        "Operating",
        "Wealth Builder",
    ]
    return "Types: " + ", ".join(labels)

def _parse_account_type(message: str) -> str | None:
    msg = message.lower()
    for label, value in ACCOUNT_TYPES.items():
        if label in msg:
            return value
    return None

def _parse_account_name(message: str) -> str | None:
    # supports: named "X" / called "X"
    match = re.search(r"(?:named|called)\s+\"([^\"]+)\"", message, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"(?:named|called)\s+(.+)", message, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"(.+?)\s+should be the name\b", message, re.IGNORECASE)
    if match:
        return match.group(1).strip(" \"'")
    return None


def _is_valid_account_name_candidate(message: str) -> bool:
    cleaned = re.sub(r"\s+", " ", message.strip())
    lowered = cleaned.lower()
    if not cleaned or len(cleaned) > 60:
        return False
    if _mentions_history_or_prior_context(cleaned):
        return False
    if "?" in cleaned:
        return False
    if any(phrase in lowered for phrase in ["create account", "open account", "new account", "deposit", "transfer", "withdraw", "rename", "archive", "restore"]):
        return False
    return True

def _parse_starting_balance(message: str) -> Decimal | None:
    if "start" not in message.lower() and "starting" not in message.lower() and "seed" not in message.lower():
        return None
    return _extract_amount(message)


def _parse_create_account_starting_balance(message: str) -> Decimal | None:
    explicit = _parse_starting_balance(message)
    if explicit is not None:
        return explicit
    lowered = message.lower()
    if any(phrase in lowered for phrase in ["initial deposit", "initial balance", "open with", "with deposit", "with a deposit"]):
        return _extract_amount(message)
    normalized = re.sub(r"\s+", " ", lowered).strip()
    if re.fullmatch(r"[£$€]?\s?\d{1,3}(?:,\d{3})*(?:\.\d+)?(?:\s+(pounds?|sterling|euros?|dollars?))?", normalized):
        return _extract_amount(message)
    return None


def _parse_new_name(message: str) -> str | None:
    match = re.search(r"\bto\b\s+[\"“]?([^\"”]+)[\"”]?\s*$", message, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _parse_currency_code(message: str) -> str | None:
    stripped = message.strip()
    direct = re.fullmatch(r"([A-Za-z]{3})", stripped)
    if direct and direct.group(1).upper() in {"USD", "GBP", "EUR"}:
        return direct.group(1).upper()

    lowered = stripped.lower()
    for word, code in {
        "pound": "GBP",
        "pounds": "GBP",
        "sterling": "GBP",
        "euro": "EUR",
        "euros": "EUR",
        "dollar": "USD",
        "dollars": "USD",
    }.items():
        if re.search(rf"\b{word}\b", lowered):
            return code

    for pattern in (
        r"\bto\s+([A-Za-z]{3})\b\s*$",
        r"\bin\s+([A-Za-z]{3})\b\s*$",
        r"\bin\s+([A-Za-z]{3})\s+currency\b",
        r"\b([A-Za-z]{3})\s+currency\b",
        r"\bcurrency\s+to\s+([A-Za-z]{3})\b\s*$",
    ):
        match = re.search(pattern, stripped, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None


def _format_action_label(action: str | None) -> str:
    if not action:
        return "that request"
    labels = {
        "create_account": "creating this account",
        "deposit": "that deposit",
        "withdraw": "that withdrawal",
        "transfer": "that transfer",
        "schedule": "that scheduled movement",
        "rename_account": "renaming that account",
        "archive_account": "archiving that account",
        "unarchive_account": "restoring that account",
        "change_account_currency": "changing that account’s currency",
    }
    return labels.get(action, action.replace("_", " "))


def _build_same_user_history(
    db: Session,
    user_id: int,
    thread_id: int | None,
    current_history: list[dict[str, str]],
) -> list[dict[str, str]]:
    history_payload = list(current_history)
    if not user_id:
        return history_payload
    other_rows = (
        db.query(TellerMessage, TellerThread.updated_at)
        .join(TellerThread, TellerThread.id == TellerMessage.thread_id)
        .filter(
            TellerThread.user_id == user_id,
            TellerMessage.role.in_(["user", "assistant"]),
            TellerMessage.thread_id != (thread_id or -1),
        )
        .order_by(TellerThread.updated_at.desc(), TellerMessage.created_at.desc())
        .limit(6)
        .all()
    )
    if not other_rows:
        return history_payload
    cross_thread: list[dict[str, str]] = []
    for row, _updated_at in reversed(other_rows):
        content = (row.content or "").strip()
        if not content:
            continue
        cross_thread.append(
            {
                "role": row.role,
                "content": f"[Same user, another Teller conversation] {content}",
            }
        )
    return cross_thread + history_payload

def _list_trust_accounts(accounts: list[dict]) -> list[dict]:
    return [acct for acct in accounts if acct["account_type"] == "trust"]

def _is_schedule_intent(message: str) -> bool:
    msg = message.lower()
    if any(word in msg for word in ["schedule", "scheduled", "tomorrow"]):
        return True
    return _parse_date(msg) is not None

def _parse_account_id(message: str) -> int | None:
    match = re.search(r"(?:account\s*#?\s*|#)(\d+)", message.lower())
    if match:
        return int(match.group(1))
    digits = re.findall(r"\b(\d{1,6})\b", message)
    if digits:
        try:
            return int(digits[0])
        except ValueError:
            return None
    return None

def _parse_date(message: str) -> datetime | None:
    # Supports YYYY-MM-DD or YYYY-MM-DD HH:MM
    match = re.search(r"(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?", message)
    if not match:
        return None
    date_part = match.group(1)
    time_part = match.group(2) or "09:00"
    try:
        return datetime.fromisoformat(f"{date_part} {time_part}")
    except ValueError:
        return None

def _clean_amount(value: str) -> Decimal | None:
    raw = value.replace(",", "").replace("$", "").strip()
    try:
        amt = Decimal(raw)
    except InvalidOperation:
        return None
    if amt <= 0:
        return None
    return amt


def _currency_symbol(currency: str | None) -> str:
    code = (currency or "USD").upper()
    return {"USD": "$", "GBP": "£", "EUR": "€"}.get(code, f"{code} ")


def _format_money(amount: Decimal | int | float | str, currency: str | None = "USD") -> str:
    value = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    symbol = _currency_symbol(currency)
    formatted = f"{value:,.2f}"
    if symbol in {"$", "£", "€"}:
        return f"{symbol}{formatted}"
    return f"{symbol}{formatted}"

def _extract_amount(message: str) -> Decimal | None:
    normalized = (message or "").lower().replace(",", "")
    suffix_matches = list(re.finditer(r"(?<!\w)(\d+(?:\.\d+)?)\s*([km])\b", normalized))
    number_matches = list(re.finditer(r"(\$?\s?\d{1,3}(?:,\d{3})+(?:\.\d+)?|\$?\s?\d+(?:\.\d+)?)", message))
    correction_hint = any(phrase in normalized for phrase in ("make it", "actually", "instead", "no,"))
    if suffix_matches:
        chosen = suffix_matches[-1] if correction_hint else suffix_matches[0]
        base = Decimal(chosen.group(1))
        multiplier = Decimal("1000") if chosen.group(2) == "k" else Decimal("1000000")
        amount = base * multiplier
        return amount if amount > 0 else None
    if not number_matches:
        return None
    chosen = number_matches[-1] if correction_hint else number_matches[0]
    return _clean_amount(chosen.group(1))


def _get_recent_executed_deposit(db: Session, user_id: int, thread_id: int | None) -> TellerAuditLog | None:
    if not thread_id:
        return None
    audits = (
        db.query(TellerAuditLog)
        .filter(
            TellerAuditLog.user_id == user_id,
            TellerAuditLog.thread_id == thread_id,
            TellerAuditLog.action_type == "pending_action",
            TellerAuditLog.status == "executed",
        )
        .order_by(TellerAuditLog.created_at.desc())
        .limit(8)
        .all()
    )
    for audit in audits:
        if (audit.action_payload or {}).get("action") == "deposit":
            return audit
    return None

def _list_accounts(db: Session, user_id: int, include_inactive: bool = False) -> list[dict]:
    query = db.query(Account).filter(Account.owner_user_id == user_id)
    if not include_inactive:
        query = query.filter(Account.is_active.is_(True))
    accounts = query.order_by(Account.created_at.asc()).all()
    items: list[dict] = []
    for acct in accounts:
        native_currency = (acct.currency or "USD").upper()
        balance = get_account_balance(db, acct.id, native_currency)
        items.append(
            {
                "id": acct.id,
                "name": acct.name,
                "account_type": acct.account_type,
                "balance": f"{balance:.2f}",
                "currency": native_currency,
                "is_active": bool(acct.is_active),
            }
        )
    return items

def _match_account(message: str, accounts: list[dict]) -> dict | None:
    alias_match = _find_alias_account_match(message, accounts)
    if alias_match:
        return alias_match
    msg = re.sub(r"\s+", " ", message.lower()).strip()
    if not msg:
        return None
    exact_matches = [acct for acct in accounts if acct["name"].lower() in msg]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        return None
    return _select_single_account_match(msg, accounts)

def _match_accounts_in_text(message: str, accounts: list[dict]) -> list[dict]:
    msg = message.lower()
    hits = []
    explicit_source, explicit_destination = _parse_transfer_account_phrase(msg, accounts)
    if explicit_source:
        hits.append(explicit_source)
    if explicit_destination and explicit_destination != explicit_source:
        hits.append(explicit_destination)
    if hits:
        return hits
    for acct in accounts:
        name = acct["name"].lower()
        if name and name in msg:
            hits.append(acct)
            continue
        normalized_msg = re.sub(r"[^a-z0-9\s]", " ", msg)
        normalized_msg = re.sub(r"\s+", " ", normalized_msg).strip()
        normalized_name = re.sub(r"[^a-z0-9\s]", " ", name)
        normalized_name = re.sub(r"\s+", " ", normalized_name).strip()
        if normalized_msg and normalized_name and SequenceMatcher(None, normalized_msg, normalized_name).ratio() >= 0.8:
            hits.append(acct)
    return hits

def _format_accounts(accounts: list[dict]) -> str:
    if not accounts:
        return "You don’t have any accounts yet."
    lines = []
    for acct in accounts:
        status_label = "active" if acct.get("is_active", True) else "archived"
        lines.append(
            f"- #{acct['id']} {acct['name']} ({acct['account_type']}, {acct.get('currency', 'USD')}, {status_label}) — {_format_money(acct['balance'], acct.get('currency', 'USD'))}"
        )
    return "\n".join(lines)


def require_signature(user: User) -> None:
    if user.role == "admin":
        return
    if not user.is_premium:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="ManifestBank™ Signature is required to use the Teller.",
        )


def _ndjson_event(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str) + "\n"


def _should_use_standard_teller_chat(
    db: Session,
    user_id: int,
    thread_id: int | None,
    message: str,
) -> bool:
    lower_msg = message.lower().strip()
    pending_query = (
        db.query(TellerAuditLog)
        .filter(
            TellerAuditLog.user_id == user_id,
            TellerAuditLog.action_type == "pending_action",
            TellerAuditLog.status.in_(["pending", "awaiting_account"]),
        )
        .order_by(TellerAuditLog.created_at.desc())
    )
    if thread_id:
        if pending_query.filter(TellerAuditLog.thread_id == thread_id).first():
            return True
    elif pending_query.first():
        return True

    if lower_msg in CONFIRM_WORDS or lower_msg in CANCEL_WORDS:
        return True

    return _is_explicit_account_request(lower_msg)


def _is_explicit_account_request(lower_msg: str) -> bool:
    if any(phrase in lower_msg for phrase in [
        "create account",
        "new account",
        "open account",
        "rename account",
        "change account name",
        "rename my account",
        "change currency",
        "update currency",
        "set currency",
        "restore account",
        "account #",
    ]):
        return True
    if re.search(r"\b(deposit|withdraw|withdrawal|expense|spend|transfer|schedule|archive|unarchive|restore|rename)\b", lower_msg):
        return True
    if re.search(r"\b(show|list|view|check|review)\b.{0,40}\b(accounts?|balances?)\b", lower_msg):
        return True
    if re.search(r"\b(accounts?|balances?)\b.{0,40}\b(show|list|view|check|review)\b", lower_msg):
        return True
    return False


@router.get("/teller/status", response_model=TellerStatusResponse)
def teller_status(current_user: User = Depends(get_verified_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    provider = settings.TELLER_PROVIDER.lower()
    mode = "live" if provider == "openai" and settings.OPENAI_API_KEY else "stub"
    return TellerStatusResponse(provider=provider, model=settings.OPENAI_MODEL, mode=mode)


@router.get("/teller/threads", response_model=list[TellerThreadRead])
def list_threads(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
):
    require_signature(current_user)
    return (
        db.query(TellerThread)
        .filter(TellerThread.user_id == current_user.id)
        .order_by(TellerThread.updated_at.desc())
        .all()
    )


@router.post("/teller/threads", response_model=TellerThreadRead)
def create_thread(
    payload: TellerThreadCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
):
    require_signature(current_user)
    title = (payload.title or "New Teller Session").strip() or "New Teller Session"
    thread = TellerThread(user_id=current_user.id, title=title)
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


@router.put("/teller/threads/{thread_id}", response_model=TellerThreadRead)
def update_thread(
    thread_id: int,
    payload: TellerThreadUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
):
    require_signature(current_user)
    thread = (
        db.query(TellerThread)
        .filter(TellerThread.id == thread_id, TellerThread.user_id == current_user.id)
        .first()
    )
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    thread.title = title[:200]
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


@router.get("/teller/threads/{thread_id}/messages", response_model=list[TellerMessageRead])
def list_messages(
    thread_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
):
    require_signature(current_user)
    thread = (
        db.query(TellerThread)
        .filter(TellerThread.id == thread_id, TellerThread.user_id == current_user.id)
        .first()
    )
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return (
        db.query(TellerMessage)
        .filter(TellerMessage.thread_id == thread.id)
        .order_by(TellerMessage.created_at.asc())
        .all()
    )


@router.delete("/teller/threads/{thread_id}")
def delete_thread(
    thread_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
):
    require_signature(current_user)
    thread = (
        db.query(TellerThread)
        .filter(TellerThread.id == thread_id, TellerThread.user_id == current_user.id)
        .first()
    )
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    db.delete(thread)
    db.commit()
    return {"status": "deleted"}


@router.post("/teller/chat", response_model=TellerChatResponse)
async def chat(
    payload: TellerChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
):
    require_signature(current_user)
    if not rate_limiter.check(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Teller rate limit reached. Please wait a moment.",
        )

    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    # Handle pending confirmations
    pending_query = (
        db.query(TellerAuditLog)
        .filter(
            TellerAuditLog.user_id == current_user.id,
            TellerAuditLog.action_type == "pending_action",
            TellerAuditLog.status.in_(["pending", "awaiting_account", "awaiting_amount"]),
        )
        .order_by(TellerAuditLog.created_at.desc())
    )
    pending = None
    if payload.thread_id:
        pending = pending_query.filter(TellerAuditLog.thread_id == payload.thread_id).first()
        if pending:
            cutoff = datetime.now(UTC).timestamp() - 600
            if pending.created_at and pending.created_at.timestamp() < cutoff:
                pending = None
    lower_msg = message.lower().strip()
    if pending and lower_msg in {"continue", "continue that request", "keep going", "go ahead with that", "resume"}:
        action = (pending.action_payload or {}).get("action")
        if pending.status == "awaiting_amount" and action == "transfer":
            reply = "What amount should I transfer?"
        elif pending.status == "awaiting_account" and action == "transfer":
            reply = "Which accounts should I transfer between?\n" + _format_accounts(_list_accounts(db, current_user.id)) + "\nReply like: from #10 to #8"
        elif pending.status == "awaiting_account":
            reply = "Which account should I use?\n" + _format_accounts(_list_accounts(db, current_user.id))
        else:
            current_action = _format_action_label(action)
            reply = f"We’re still in the middle of {current_action}. Please answer the last question so I can continue."
        thread = (
            db.query(TellerThread)
            .filter(TellerThread.id == payload.thread_id, TellerThread.user_id == current_user.id)
            .first()
        )
        if not thread:
            thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
            db.add(thread)
            db.commit()
            db.refresh(thread)
        user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
        assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
        thread.updated_at = datetime.now(UTC)
        db.add(user_message)
        db.add(assistant_message)
        db.add(thread)
        db.commit()
        db.refresh(user_message)
        db.refresh(assistant_message)
        return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)
    if pending and _is_content_interrupt_request(message) and not _looks_like_pending_followup((pending.action_payload or {}).get("action"), message):
        pending.status = "paused"
        db.add(pending)
        db.commit()
        thread = (
            db.query(TellerThread)
            .filter(TellerThread.id == payload.thread_id, TellerThread.user_id == current_user.id)
            .first()
        )
        if not thread:
            thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
            db.add(thread)
            db.commit()
            db.refresh(thread)
        history_rows = (
            db.query(TellerMessage)
            .filter(TellerMessage.thread_id == thread.id)
            .order_by(TellerMessage.created_at.asc())
            .all()
        )
        history = [{"role": row.role, "content": row.content} for row in history_rows if row.role in {"user", "assistant"}]
        combined_history = _build_same_user_history(db, current_user.id, thread.id, history)
        _cached, reply = await generate_teller_reply(current_user.id, message, history=combined_history)
        user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
        assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
        thread.updated_at = datetime.now(UTC)
        db.add(user_message)
        db.add(assistant_message)
        db.add(thread)
        db.commit()
        db.refresh(user_message)
        db.refresh(assistant_message)
        return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)
    if pending and _is_switch_tasks_request(message):
        pending.status = "cancelled"
        db.add(pending)
        db.commit()
        reply = "Okay. I exited that action. What would you like to do instead?"
        thread = (
            db.query(TellerThread)
            .filter(TellerThread.id == payload.thread_id, TellerThread.user_id == current_user.id)
            .first()
        )
        if not thread:
            thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
            db.add(thread)
            db.commit()
            db.refresh(thread)
        user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
        assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
        thread.updated_at = datetime.now(UTC)
        db.add(user_message)
        db.add(assistant_message)
        db.add(thread)
        db.commit()
        db.refresh(user_message)
        db.refresh(assistant_message)
        return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)
    if pending and not _looks_like_pending_followup((pending.action_payload or {}).get("action"), message):
        reply = _reconfirm_pending_action(pending, db, current_user.id)
        thread = (
            db.query(TellerThread)
            .filter(TellerThread.id == payload.thread_id, TellerThread.user_id == current_user.id)
            .first()
        )
        if not thread:
            thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
            db.add(thread)
            db.commit()
            db.refresh(thread)
        user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
        assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
        thread.updated_at = datetime.now(UTC)
        db.add(user_message)
        db.add(assistant_message)
        db.add(thread)
        db.commit()
        db.refresh(user_message)
        db.refresh(assistant_message)
        return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)
    if not pending and _is_repeat_last_action_request(message):
        recent_action = _get_recent_executed_action(db, current_user.id, payload.thread_id)
        if recent_action and (recent_action.action_payload or {}).get("action") in {"transfer", "deposit", "withdraw"}:
            repeated_payload = dict(recent_action.action_payload or {})
            repeated_payload.pop("queued_followup", None)
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=payload.thread_id or recent_action.thread_id,
                action_type="pending_action",
                status="pending",
                action_payload=repeated_payload,
            )
            db.add(pending)
            db.commit()
            db.refresh(pending)
            reply = _reconfirm_pending_action(pending, db, current_user.id)
        else:
            reply = "Do you want me to repeat that transfer?"
        thread = (
            db.query(TellerThread)
            .filter(TellerThread.id == payload.thread_id, TellerThread.user_id == current_user.id)
            .first()
        )
        if not thread:
            thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
            db.add(thread)
            db.commit()
            db.refresh(thread)
        user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
        assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
        thread.updated_at = datetime.now(UTC)
        db.add(user_message)
        db.add(assistant_message)
        db.add(thread)
        db.commit()
        db.refresh(user_message)
        db.refresh(assistant_message)
        return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)
    if _is_thanks_message(message):
        reply = "You’re welcome. Glad I could help. Is there anything else I can help with right now?"
        thread = (
            db.query(TellerThread)
            .filter(TellerThread.id == payload.thread_id, TellerThread.user_id == current_user.id)
            .first()
        )
        if not thread:
            thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
            db.add(thread)
            db.commit()
            db.refresh(thread)
        user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
        assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
        thread.updated_at = datetime.now(UTC)
        db.add(user_message)
        db.add(assistant_message)
        db.add(thread)
        db.commit()
        db.refresh(user_message)
        db.refresh(assistant_message)
        return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)
    if not pending:
        recent_deposit = _get_recent_executed_deposit(db, current_user.id, payload.thread_id)
        corrected_amount = _extract_amount(message)
        if (
            recent_deposit
            and corrected_amount is not None
            and any(phrase in lower_msg for phrase in ["i said", "i meant", "should be", "not 300", "wrong"])
        ):
            recent_payload = recent_deposit.action_payload or {}
            previous_amount = Decimal(str(recent_payload.get("amount") or "0"))
            acct_id = recent_payload.get("account_id")
            acct_name = recent_payload.get("account_name")
            if acct_id and acct_name and corrected_amount > previous_amount:
                delta_amount = corrected_amount - previous_amount
                pending = TellerAuditLog(
                    user_id=current_user.id,
                    thread_id=payload.thread_id,
                    action_type="pending_action",
                    status="pending",
                    action_payload={
                        "action": "deposit",
                        "account_id": acct_id,
                        "account_name": acct_name,
                        "amount": str(delta_amount),
                        "memo": "Teller deposit correction",
                    },
                )
                db.add(pending)
                db.commit()
                reply = (
                    f"Confirm an additional deposit of {_format_money(delta_amount)} into “{acct_name}” "
                    f"so the total becomes {_format_money(corrected_amount)}?"
                )
                thread = (
                    db.query(TellerThread)
                    .filter(TellerThread.id == payload.thread_id, TellerThread.user_id == current_user.id)
                    .first()
                )
                if not thread:
                    thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
                    db.add(thread)
                    db.commit()
                    db.refresh(thread)
                user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
                assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
                thread.updated_at = datetime.now(UTC)
                db.add(user_message)
                db.add(assistant_message)
                db.add(thread)
                db.commit()
                db.refresh(user_message)
                db.refresh(assistant_message)
                return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)
    confirmation_ready = _pending_confirmation_ready(pending)
    confirmation_intent = _classify_confirmation_intent(message) if confirmation_ready else "unclear"
    if confirmation_ready and (
        confirmation_intent == "edit"
        or ((pending.action_payload or {}).get("action") == "transfer" and _looks_like_transfer_update(message, _list_accounts(db, current_user.id)))
    ):
            reply = _handle_pending_confirmation_edit(pending, message, db, current_user.id) or "What should I change?"
            thread = (
                db.query(TellerThread)
                .filter(TellerThread.id == payload.thread_id, TellerThread.user_id == current_user.id)
                .first()
            )
            if not thread:
                thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
                db.add(thread)
                db.commit()
                db.refresh(thread)
            user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
            assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
            thread.updated_at = datetime.now(UTC)
            db.add(user_message)
            db.add(assistant_message)
            db.add(thread)
            db.commit()
            db.refresh(user_message)
            db.refresh(assistant_message)
            return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)
    if confirmation_ready and confirmation_intent == "reject":
            pending.status = "cancelled"
            db.add(pending)
            db.commit()
            reply = _build_cancel_reply((pending.action_payload or {}).get("action"))
            thread = (
                db.query(TellerThread)
                .filter(TellerThread.id == payload.thread_id, TellerThread.user_id == current_user.id)
                .first()
            )
            if not thread:
                thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
                db.add(thread)
                db.commit()
                db.refresh(thread)
            user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
            assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
            thread.updated_at = datetime.now(UTC)
            db.add(user_message)
            db.add(assistant_message)
            db.add(thread)
            db.commit()
            db.refresh(user_message)
            db.refresh(assistant_message)
            return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)
    if confirmation_ready and confirmation_intent == "unclear" and _looks_like_confirmation_typo(message):
            reply = _build_confirmation_clarify_reply((pending.action_payload or {}).get("action"))
            thread = (
                db.query(TellerThread)
                .filter(TellerThread.id == payload.thread_id, TellerThread.user_id == current_user.id)
                .first()
            )
            if not thread:
                thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
                db.add(thread)
                db.commit()
                db.refresh(thread)
            user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
            assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
            thread.updated_at = datetime.now(UTC)
            db.add(user_message)
            db.add(assistant_message)
            db.add(thread)
            db.commit()
            db.refresh(user_message)
            db.refresh(assistant_message)
            return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)
    if pending and ((confirmation_ready and confirmation_intent == "approve") or (not confirmation_ready and pending.status != "pending" and _is_strict_confirm_message(message))):
        action = (pending.action_payload or {}).get("action")
        if action == "deposit":
                acct_id = pending.action_payload.get("account_id")
                amount_raw = pending.action_payload.get("amount")
                if not acct_id:
                    reply = "Which account should I use?\n" + _format_accounts(_list_accounts(db, current_user.id))
                else:
                    acct = get_account(db, int(acct_id))
                    if not acct or acct.owner_user_id != current_user.id:
                        pending.status = "cancelled"
                        db.add(pending)
                        db.commit()
                        reply = "That account isn’t available. Please choose another."
                    else:
                        amount = Decimal(str(amount_raw))
                        memo = pending.action_payload.get("memo") or "Teller deposit"
                        entry = create_ledger_entry(
                            db,
                            current_user.id,
                            LedgerEntryCreate(
                                account_id=int(acct_id),
                                direction="credit",
                                amount=amount,
                                entry_type="deposit",
                                status="posted",
                                memo=memo,
                            ),
                        )
                    pending.status = "executed"
                    db.add(pending)
                    db.commit()
                    balance = get_account_balance(db, entry.account_id, acct.currency or "USD")
                    reply = (
                        f"Done. I deposited {_format_money(amount, acct.currency)} into “{acct.name}”. "
                        f"New balance: {_format_money(balance, acct.currency)}."
                    )
                    queued_followup = (pending.action_payload or {}).get("queued_followup")
                    if queued_followup and _contains_transfer_intent(queued_followup):
                        followup_reply = _build_transfer_followup_reply(
                            db,
                            current_user.id,
                            payload.thread_id or pending.thread_id,
                            queued_followup,
                        )
                        if followup_reply:
                            reply = f"{reply}\n\n{followup_reply}"
        elif action == "withdraw":
                acct_id = pending.action_payload.get("account_id")
                amount_raw = pending.action_payload.get("amount")
                if not acct_id:
                    reply = "Which account should I use?\n" + _format_accounts(_list_accounts(db, current_user.id))
                else:
                    acct = get_account(db, int(acct_id))
                    if not acct or acct.owner_user_id != current_user.id:
                        pending.status = "cancelled"
                        db.add(pending)
                        db.commit()
                        reply = "That account isn’t available. Please choose another."
                    else:
                        amount = Decimal(str(amount_raw))
                        memo = pending.action_payload.get("memo") or "Teller withdrawal"
                        entry = create_ledger_entry(
                            db,
                            current_user.id,
                            LedgerEntryCreate(
                                account_id=int(acct_id),
                                direction="debit",
                                amount=amount,
                                entry_type="withdrawal",
                                status="posted",
                                memo=memo,
                            ),
                        )
                        pending.status = "executed"
                        db.add(pending)
                        db.commit()
                        balance = get_account_balance(db, entry.account_id, acct.currency or "USD")
                        reply = (
                            f"Done. I withdrew {_format_money(amount, acct.currency)} from “{acct.name}”. "
                            f"New balance: {_format_money(balance, acct.currency)}."
                        )
        elif action == "transfer":
                from_id = pending.action_payload.get("from_account_id")
                to_id = pending.action_payload.get("to_account_id")
                amount_raw = pending.action_payload.get("amount")
                if not from_id or not to_id:
                    reply = "Which accounts should I transfer between?\n" + _format_accounts(_list_accounts(db, current_user.id))
                else:
                    from_acct = get_account(db, int(from_id))
                    to_acct = get_account(db, int(to_id))
                    if (
                        not from_acct
                        or not to_acct
                        or from_acct.owner_user_id != current_user.id
                        or to_acct.owner_user_id != current_user.id
                    ):
                        pending.status = "cancelled"
                        db.add(pending)
                        db.commit()
                        reply = "Those accounts aren’t available. Please choose another."
                    else:
                        amount = Decimal(str(amount_raw))
                        memo = pending.action_payload.get("memo") or "Teller transfer"
                        base_currency = ((pending.action_payload.get("currency") or from_acct.currency or "USD")).upper()
                        debit_currency = (from_acct.currency or base_currency).upper()
                        credit_currency = (to_acct.currency or base_currency).upper()
                        debit_amount, missing_debit, debit_rate = convert_amount_with_rate(
                            amount, base_currency, debit_currency
                        )
                        credit_amount, missing_credit, credit_rate = convert_amount_with_rate(
                            amount, base_currency, credit_currency
                        )
                        create_transfer(
                            db,
                            current_user.id,
                            int(from_id),
                            int(to_id),
                            debit_amount,
                            debit_currency,
                            credit_amount,
                            credit_currency,
                            memo=memo,
                            meta={
                                "fx_base_currency": base_currency,
                                "fx_debit_currency": debit_currency,
                                "fx_credit_currency": credit_currency,
                                "fx_debit_rate": str(debit_rate),
                                "fx_credit_rate": str(credit_rate),
                                "fx_timestamp": datetime.now(UTC).isoformat(),
                                "fx_missing_rates": list({*missing_debit, *missing_credit}),
                            },
                        )
                        pending.status = "executed"
                        db.add(pending)
                        db.commit()
                        reply = (
                            f"Done. I transferred {_format_money(amount, base_currency)} "
                            f"from “{from_acct.name}” to “{to_acct.name}”."
                        )
        elif action == "schedule":
                acct_id = pending.action_payload.get("account_id")
                amount_raw = pending.action_payload.get("amount")
                scheduled_for = pending.action_payload.get("scheduled_for")
                direction = pending.action_payload.get("direction") or "credit"
                if not acct_id:
                    reply = "Which account should I use?\n" + _format_accounts(_list_accounts(db, current_user.id))
                elif not scheduled_for:
                    reply = "When should I schedule it? (YYYY-MM-DD or YYYY-MM-DD HH:MM)"
                else:
                    acct = get_account(db, int(acct_id))
                    if not acct or acct.owner_user_id != current_user.id:
                        pending.status = "cancelled"
                        db.add(pending)
                        db.commit()
                        reply = "That account isn’t available. Please choose another."
                    else:
                        amount = Decimal(str(amount_raw))
                        memo = pending.action_payload.get("memo") or "Teller scheduled movement"
                        create_scheduled_entry(
                            db,
                            current_user.id,
                            ScheduledEntryCreate(
                                account_id=int(acct_id),
                                direction=direction,
                                amount=amount,
                                currency="USD",
                                entry_type="scheduled",
                                memo=memo,
                                scheduled_for=datetime.fromisoformat(scheduled_for),
                            ),
                        )
                        pending.status = "executed"
                        db.add(pending)
                        db.commit()
                        reply = f"Done. I scheduled {_format_money(amount, acct.currency or 'USD')}."
        elif action == "create_account":
                name = (pending.action_payload or {}).get("name")
                account_type = (pending.action_payload or {}).get("account_type") or "personal"
                account_currency = ((pending.action_payload or {}).get("currency") or "USD").upper()
                parent_id = (pending.action_payload or {}).get("parent_account_id")
                starting_balance = (pending.action_payload or {}).get("starting_balance")
                if not name:
                    reply = "What should the account be named?"
                else:
                    if parent_id:
                        parent = get_account(db, int(parent_id))
                        if not parent or parent.owner_user_id != current_user.id or parent.account_type != "trust":
                            reply = "Parent trust not found. Choose a valid trust account.\n" + _format_accounts(_list_accounts(db, current_user.id))
                        else:
                            acct = create_account(
                                db,
                                current_user.id,
                                AccountCreate(
                                    name=name,
                                    account_type=account_type,
                                    currency=account_currency,
                                    parent_account_id=int(parent_id),
                                    is_active=True,
                                ),
                            )
                            if starting_balance and Decimal(str(starting_balance)) > 0:
                                amount = Decimal(str(starting_balance))
                                create_ledger_entry(
                                    db,
                                    current_user.id,
                                    LedgerEntryCreate(
                                        account_id=int(acct.id),
                                        direction="credit",
                                        amount=amount,
                                        entry_type="deposit",
                                        status="posted",
                                        currency=account_currency,
                                        memo="Starting balance",
                                    ),
                                )
                            pending.status = "executed"
                            db.add(pending)
                            db.commit()
                            reply = f"Account created: #{acct.id} {acct.name} ({acct.account_type})."
                    else:
                        acct = create_account(
                            db,
                            current_user.id,
                            AccountCreate(name=name, account_type=account_type, currency=account_currency, is_active=True),
                        )
                        if starting_balance and Decimal(str(starting_balance)) > 0:
                            amount = Decimal(str(starting_balance))
                            create_ledger_entry(
                                db,
                                current_user.id,
                                LedgerEntryCreate(
                                    account_id=int(acct.id),
                                    direction="credit",
                                    amount=amount,
                                    entry_type="deposit",
                                    status="posted",
                                    currency=account_currency,
                                    memo="Starting balance",
                                ),
                            )
                        pending.status = "executed"
                        db.add(pending)
                        db.commit()
                        reply = f"Account created: #{acct.id} {acct.name} ({acct.account_type})."
        elif action == "rename_account":
                acct_id = pending.action_payload.get("account_id")
                next_name = (pending.action_payload.get("new_name") or "").strip()
                acct = get_account(db, int(acct_id)) if acct_id else None
                if not acct or acct.owner_user_id != current_user.id:
                    pending.status = "cancelled"
                    db.add(pending)
                    db.commit()
                    reply = "That account isn’t available. Please choose another."
                elif not next_name:
                    reply = "What should the new account name be?"
                else:
                    previous_name = acct.name
                    update_account_fields(db, acct, next_name, None)
                    pending.status = "executed"
                    db.add(pending)
                    db.commit()
                    reply = f"Done. I renamed “{previous_name}” to “{next_name}”."
        elif action == "archive_account":
                acct_id = pending.action_payload.get("account_id")
                acct = get_account(db, int(acct_id)) if acct_id else None
                if not acct or acct.owner_user_id != current_user.id:
                    pending.status = "cancelled"
                    db.add(pending)
                    db.commit()
                    reply = "That account isn’t available. Please choose another."
                else:
                    update_account_fields(db, acct, None, None, False)
                    pending.status = "executed"
                    db.add(pending)
                    db.commit()
                    reply = f"Done. I archived “{acct.name}”."
        elif action == "unarchive_account":
                acct_id = pending.action_payload.get("account_id")
                acct = get_account(db, int(acct_id)) if acct_id else None
                if not acct or acct.owner_user_id != current_user.id:
                    pending.status = "cancelled"
                    db.add(pending)
                    db.commit()
                    reply = "That account isn’t available. Please choose another."
                else:
                    update_account_fields(db, acct, None, None, True)
                    pending.status = "executed"
                    db.add(pending)
                    db.commit()
                    reply = f"Done. I restored “{acct.name}”."
        elif action == "change_account_currency":
                acct_id = pending.action_payload.get("account_id")
                next_currency = (pending.action_payload.get("currency") or "").strip().upper()
                acct = get_account(db, int(acct_id)) if acct_id else None
                if not acct or acct.owner_user_id != current_user.id:
                    pending.status = "cancelled"
                    db.add(pending)
                    db.commit()
                    reply = "That account isn’t available. Please choose another."
                elif len(next_currency) != 3 or not next_currency.isalpha():
                    reply = "Which 3-letter currency code should I use?"
                else:
                    update_account_fields(db, acct, None, next_currency)
                    pending.status = "executed"
                    db.add(pending)
                    db.commit()
                    reply = f"Done. I changed “{acct.name}” to {next_currency}."
        else:
            reply = "Got it. That action is queued."
        # store messages and return
        thread_id = payload.thread_id or pending.thread_id
        thread = None
        if thread_id:
            thread = (
                db.query(TellerThread)
                .filter(TellerThread.id == thread_id, TellerThread.user_id == current_user.id)
                .first()
            )
        if not thread:
            thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
            db.add(thread)
            db.commit()
            db.refresh(thread)
        user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
        assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
        thread.updated_at = datetime.now(UTC)
        db.add(user_message)
        db.add(assistant_message)
        db.add(thread)
        db.commit()
        db.refresh(user_message)
        db.refresh(assistant_message)
        return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)
    if (
        pending
        and _is_cancel_message(message)
        and not ((pending.action_payload or {}).get("action") == "transfer" and _looks_like_transfer_update(message, _list_accounts(db, current_user.id)))
        and not (
            (pending.action_payload or {}).get("action") == "create_account"
            and (pending.action_payload or {}).get("starting_balance_prompted")
            and not (pending.action_payload or {}).get("starting_balance")
            and lower_msg in NO_PARENT_WORDS
        )
    ):
            pending.status = "cancelled"
            db.add(pending)
            db.commit()
            reply = _build_cancel_reply((pending.action_payload or {}).get("action"))
            thread_id = payload.thread_id or pending.thread_id
            thread = None
            if thread_id:
                thread = (
                    db.query(TellerThread)
                    .filter(TellerThread.id == thread_id, TellerThread.user_id == current_user.id)
                    .first()
                )
            if not thread:
                thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
                db.add(thread)
                db.commit()
                db.refresh(thread)
            user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
            assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
            thread.updated_at = datetime.now(UTC)
            db.add(user_message)
            db.add(assistant_message)
            db.add(thread)
            db.commit()
            db.refresh(user_message)
            db.refresh(assistant_message)
            return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)
    if pending and pending.status == "awaiting_amount":
        action = (pending.action_payload or {}).get("action")
        if action in {"transfer", "deposit", "withdraw"}:
            updated_amount = _extract_amount(message)
            if updated_amount is None:
                if action == "transfer":
                    reply = "What amount should I transfer?"
                elif action == "withdraw":
                    reply = "What amount should I withdraw?"
                else:
                    reply = "What amount should I deposit?"
            else:
                current_payload = pending.action_payload or {}
                next_payload = {**current_payload, "amount": str(updated_amount)}
                if action == "transfer":
                    next_payload["transfer_stage"] = "from"
                pending.action_payload = next_payload
                pending.status = "awaiting_account"
                db.add(pending)
                db.commit()
                if action == "transfer":
                    reply = "Which account should I transfer from?\n" + _format_accounts(_list_accounts(db, current_user.id))
                else:
                    reply = "Which account should I use?\n" + _format_accounts(_list_accounts(db, current_user.id))

            thread = (
                db.query(TellerThread)
                .filter(TellerThread.id == payload.thread_id, TellerThread.user_id == current_user.id)
                .first()
            )
            if not thread:
                thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
                db.add(thread)
                db.commit()
                db.refresh(thread)
            user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
            assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
            thread.updated_at = datetime.now(UTC)
            db.add(user_message)
            db.add(assistant_message)
            db.add(thread)
            db.commit()
            db.refresh(user_message)
            db.refresh(assistant_message)
            return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)

    if pending and pending.status == "awaiting_account":
        action = (pending.action_payload or {}).get("action")
        accounts = _list_accounts(db, current_user.id)
        if action == "transfer":
            current_payload = pending.action_payload or {}
            if _looks_like_transfer_update(message, accounts):
                reply = _handle_pending_confirmation_edit(pending, message, db, current_user.id) or _reconfirm_pending_action(pending, db, current_user.id)
                thread = (
                    db.query(TellerThread)
                    .filter(TellerThread.id == payload.thread_id, TellerThread.user_id == current_user.id)
                    .first()
                )
                if not thread:
                    thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
                    db.add(thread)
                    db.commit()
                    db.refresh(thread)
                user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
                assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
                thread.updated_at = datetime.now(UTC)
                db.add(user_message)
                db.add(assistant_message)
                db.add(thread)
                db.commit()
                db.refresh(user_message)
                db.refresh(assistant_message)
                return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)
            stage = current_payload.get("transfer_stage") or "from"
            pair_match = re.search(r"\b(\d+)\s+to\s+(\d+)\b", lower_msg)
            if pair_match:
                from_id = int(pair_match.group(1))
                to_id = int(pair_match.group(2))
                from_acct = next((a for a in accounts if a["id"] == from_id), None)
                to_acct = next((a for a in accounts if a["id"] == to_id), None)
                if from_acct and to_acct and from_id != to_id:
                    pending.action_payload = {
                        **current_payload,
                        "from_account_id": from_id,
                        "from_account_name": from_acct["name"],
                        "to_account_id": to_id,
                        "to_account_name": to_acct["name"],
                        "transfer_stage": "to",
                    }
                    pending.status = "pending"
                    db.add(pending)
                    db.commit()
                    amount = Decimal(str(pending.action_payload.get("amount")))
                    reply = (
                        f"Confirm transfer {_format_money(amount, from_acct.get('currency', 'USD'))} "
                        f"from “{from_acct['name']}” to “{to_acct['name']}”?"
                    )
                    thread = (
                        db.query(TellerThread)
                        .filter(TellerThread.id == payload.thread_id, TellerThread.user_id == current_user.id)
                        .first()
                    )
                    if not thread:
                        thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
                        db.add(thread)
                        db.commit()
                        db.refresh(thread)
                    user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
                    assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
                    thread.updated_at = datetime.now(UTC)
                    db.add(user_message)
                    db.add(assistant_message)
                    db.add(thread)
                    db.commit()
                    db.refresh(user_message)
                    db.refresh(assistant_message)
                    return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)
            explicit_from, explicit_to = _parse_transfer_account_phrase(message, accounts)
            if explicit_from and explicit_to and explicit_from["id"] != explicit_to["id"]:
                pending.action_payload = {
                    **current_payload,
                    "from_account_id": explicit_from["id"],
                    "from_account_name": explicit_from["name"],
                    "to_account_id": explicit_to["id"],
                    "to_account_name": explicit_to["name"],
                    "transfer_stage": "to",
                }
                pending.status = "pending"
                db.add(pending)
                db.commit()
                amount = Decimal(str(pending.action_payload.get("amount")))
                reply = (
                    f"Confirm transfer {_format_money(amount, explicit_from.get('currency', 'USD'))} "
                    f"from “{explicit_from['name']}” to “{explicit_to['name']}”?"
                )
                thread = (
                    db.query(TellerThread)
                    .filter(TellerThread.id == payload.thread_id, TellerThread.user_id == current_user.id)
                    .first()
                )
                if not thread:
                    thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
                    db.add(thread)
                    db.commit()
                    db.refresh(thread)
                user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
                assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
                thread.updated_at = datetime.now(UTC)
                db.add(user_message)
                db.add(assistant_message)
                db.add(thread)
                db.commit()
                db.refresh(user_message)
                db.refresh(assistant_message)
                return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)
            selected_id = _parse_account_id(message)
            selected_acct = next((a for a in accounts if a["id"] == selected_id), None) if selected_id else None
            if not selected_acct:
                selected_acct = _match_account(lower_msg, accounts)
            if not selected_acct and len(accounts) == 1 and (_is_strict_confirm_message(message) or lower_msg in ACCOUNT_POINTING_WORDS):
                selected_acct = accounts[0]
            if not selected_acct:
                if stage == "to":
                    from_id = current_payload.get("from_account_id")
                    available_accounts = [acct for acct in accounts if acct["id"] != from_id]
                    reply = "Which account should I transfer to?\n" + _format_accounts(available_accounts)
                else:
                    reply = "Which account should I transfer from?\n" + _format_accounts(accounts)
            elif stage == "from":
                requested_currency = (current_payload.get("currency") or "").upper()
                if requested_currency and (selected_acct.get("currency") or "USD").upper() != requested_currency:
                    available_accounts = [acct for acct in accounts if (acct.get("currency") or "USD").upper() == requested_currency]
                    reply = f"Which {requested_currency} account should I transfer from?\n" + _format_accounts(available_accounts or accounts)
                    thread = (
                        db.query(TellerThread)
                        .filter(TellerThread.id == payload.thread_id, TellerThread.user_id == current_user.id)
                        .first()
                    )
                    if not thread:
                        thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
                        db.add(thread)
                        db.commit()
                        db.refresh(thread)
                    user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
                    assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
                    thread.updated_at = datetime.now(UTC)
                    db.add(user_message)
                    db.add(assistant_message)
                    db.add(thread)
                    db.commit()
                    db.refresh(user_message)
                    db.refresh(assistant_message)
                    return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)
                pending.action_payload = {
                    **current_payload,
                    "from_account_id": selected_acct["id"],
                    "from_account_name": selected_acct["name"],
                    "currency": requested_currency or selected_acct.get("currency") or "USD",
                    "transfer_stage": "to",
                }
                pending.status = "awaiting_account"
                db.add(pending)
                db.commit()
                available_accounts = [acct for acct in accounts if acct["id"] != selected_acct["id"]]
                reply = "Which account should I transfer to?\n" + _format_accounts(available_accounts)
            else:
                from_id = current_payload.get("from_account_id")
                if from_id == selected_acct["id"]:
                    available_accounts = [acct for acct in accounts if acct["id"] != selected_acct["id"]]
                    reply = "Choose a different destination account.\n" + _format_accounts(available_accounts)
                else:
                    from_acct = next((a for a in accounts if a["id"] == from_id), None)
                    if not from_acct:
                        pending.status = "cancelled"
                        db.add(pending)
                        db.commit()
                        reply = "That source account isn’t available anymore. Start the transfer again."
                    else:
                        pending.action_payload = {
                            **current_payload,
                            "to_account_id": selected_acct["id"],
                            "to_account_name": selected_acct["name"],
                        }
                        pending.status = "pending"
                        db.add(pending)
                        db.commit()
                        amount = Decimal(str(pending.action_payload.get("amount")))
                        reply = (
                            f"Confirm transfer {_format_money(amount, pending.action_payload.get('currency') or from_acct.get('currency', 'USD'))} "
                            f"from “{from_acct['name']}” to “{selected_acct['name']}”?"
                        )
        elif action == "create_account":
            # Waiting on parent trust selection
            trusts = _list_trust_accounts(accounts)
            if lower_msg in NO_PARENT_WORDS or not trusts:
                current_payload = pending.action_payload or {}
                pending.action_payload = {**current_payload, "parent_account_id": None}
                pending.status = "pending"
                db.add(pending)
                db.commit()
                name = pending.action_payload.get("name")
                account_type = pending.action_payload.get("account_type")
                currency = (pending.action_payload.get("currency") or "USD").upper()
                starting_balance = pending.action_payload.get("starting_balance")
                if starting_balance and Decimal(str(starting_balance)) > 0:
                    reply = (
                        f"Confirm create account “{name}” ({account_type}, {currency}) "
                        f"with starting balance {_format_money(starting_balance, currency)}?"
                    )
                else:
                    reply = f"Confirm create account “{name}” ({account_type}, {currency})?"
            else:
                acct_id = _parse_account_id(lower_msg)
                parent = next((a for a in trusts if a["id"] == acct_id), None)
                if not parent and _is_strict_confirm_message(message) and len(trusts) == 1:
                    parent = trusts[0]
                if not parent:
                    reply = "Choose a parent trust or reply 'no'.\n" + _format_accounts(trusts)
                else:
                    current_payload = pending.action_payload or {}
                    pending.action_payload = {**current_payload, "parent_account_id": parent["id"]}
                    pending.status = "pending"
                    db.add(pending)
                    db.commit()
                    name = pending.action_payload.get("name")
                    account_type = pending.action_payload.get("account_type")
                    currency = (pending.action_payload.get("currency") or "USD").upper()
                    starting_balance = pending.action_payload.get("starting_balance")
                    if starting_balance and Decimal(str(starting_balance)) > 0:
                        reply = (
                            f"Confirm create account “{name}” ({account_type}, {currency}) under “{parent['name']}” "
                            f"with starting balance {_format_money(starting_balance, currency)}?"
                        )
                    else:
                        reply = f"Confirm create account “{name}” ({account_type}, {currency}) under “{parent['name']}”?"
        else:
            acct_id = _parse_account_id(lower_msg)
            acct = None
            if acct_id:
                acct = next((a for a in accounts if a["id"] == acct_id), None)
            if not acct:
                acct = _match_account(lower_msg, accounts)
            if not acct and (_is_strict_confirm_message(message) or lower_msg in ACCOUNT_POINTING_WORDS) and len(accounts) == 1:
                acct = accounts[0]
            if not acct:
                reply = "Which account should I use?\n" + _format_accounts(accounts)
            else:
                current_payload = pending.action_payload or {}
                pending.action_payload = {
                    **current_payload,
                    "account_id": acct["id"],
                    "account_name": acct["name"],
                }
                pending.status = "pending"
                db.add(pending)
                db.commit()
                amount = Decimal(str(pending.action_payload.get("amount")))
                if action == "withdraw":
                    reply = f"Confirm withdrawal {_format_money(amount, acct.get('currency', 'USD'))} from “{acct['name']}”?"
                elif action == "schedule":
                    reply = "When should I schedule it? (YYYY-MM-DD or YYYY-MM-DD HH:MM)"
                else:
                    reply = f"Confirm deposit {_format_money(amount, acct.get('currency', 'USD'))} into “{acct['name']}”?"

        thread = (
            db.query(TellerThread)
            .filter(TellerThread.id == payload.thread_id, TellerThread.user_id == current_user.id)
            .first()
        )
        if not thread:
            thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
            db.add(thread)
            db.commit()
            db.refresh(thread)
        user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
        assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
        thread.updated_at = datetime.now(UTC)
        db.add(user_message)
        db.add(assistant_message)
        db.add(thread)
        db.commit()
        db.refresh(user_message)
        db.refresh(assistant_message)
        return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)

    if pending and pending.status == "pending":
        action = (pending.action_payload or {}).get("action")
        if action in {"deposit", "withdraw"}:
            updated_amount = _extract_amount(message)
            if updated_amount is not None:
                current_payload = pending.action_payload or {}
                pending.action_payload = {**current_payload, "amount": str(updated_amount)}
                db.add(pending)
                db.commit()
                account_name = current_payload.get("account_name")
                if action == "withdraw":
                    reply = f"Confirm withdrawal {_format_money(updated_amount, current_payload.get('currency') or 'USD')} from “{account_name}”?"
                else:
                    reply = f"Confirm deposit {_format_money(updated_amount, current_payload.get('currency') or 'USD')} into “{account_name}”?"

                thread_id = payload.thread_id or pending.thread_id
                thread = None
                if thread_id:
                    thread = (
                        db.query(TellerThread)
                        .filter(TellerThread.id == thread_id, TellerThread.user_id == current_user.id)
                        .first()
                    )
                if not thread:
                    thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
                    db.add(thread)
                    db.commit()
                    db.refresh(thread)
                user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
                assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
                thread.updated_at = datetime.now(UTC)
                db.add(user_message)
                db.add(assistant_message)
                db.add(thread)
                db.commit()
                db.refresh(user_message)
                db.refresh(assistant_message)
                return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)
        if action == "schedule" and not (pending.action_payload or {}).get("scheduled_for"):
            scheduled_for = _parse_date(lower_msg)
            if scheduled_for:
                current_payload = pending.action_payload or {}
                pending.action_payload = {**current_payload, "scheduled_for": scheduled_for.isoformat()}
                db.add(pending)
                db.commit()
                amount = Decimal(str(pending.action_payload.get("amount")))
                reply = f"Confirm scheduled movement of ${amount:.2f} on {scheduled_for.date()}?"
                thread_id = payload.thread_id or pending.thread_id
                thread = None
                if thread_id:
                    thread = (
                        db.query(TellerThread)
                        .filter(TellerThread.id == thread_id, TellerThread.user_id == current_user.id)
                        .first()
                    )
                if not thread:
                    thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
                    db.add(thread)
                    db.commit()
                    db.refresh(thread)
                user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
                assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
                thread.updated_at = datetime.now(UTC)
                db.add(user_message)
                db.add(assistant_message)
                db.add(thread)
                db.commit()
                db.refresh(user_message)
                db.refresh(assistant_message)
                return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)
        if action == "rename_account":
            current_payload = pending.action_payload or {}
            accounts_all = _list_accounts(db, current_user.id, include_inactive=True)
            acct_id = current_payload.get("account_id")
            if not acct_id:
                acct_match = None
                parsed_id = _parse_account_id(message)
                if parsed_id:
                    acct_match = next((a for a in accounts_all if a["id"] == parsed_id), None)
                if not acct_match:
                    acct_match = _match_account(message, accounts_all)
                if acct_match:
                    pending.action_payload = {**current_payload, "account_id": acct_match["id"], "account_name": acct_match["name"]}
                    db.add(pending)
                    db.commit()
                    reply = "What should the new account name be?"
                else:
                    reply = "Which account should I rename?\n" + _format_accounts(accounts_all)
            else:
                new_name = _parse_new_name(message) or message.strip()
                if new_name:
                    pending.action_payload = {**current_payload, "new_name": new_name}
                    db.add(pending)
                    db.commit()
                    reply = f"Confirm rename “{current_payload.get('account_name')}” to “{new_name}”?"
                else:
                    reply = "What should the new account name be?"

            thread_id = payload.thread_id or pending.thread_id
            thread = None
            if thread_id:
                thread = (
                    db.query(TellerThread)
                    .filter(TellerThread.id == thread_id, TellerThread.user_id == current_user.id)
                    .first()
                )
            if not thread:
                thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
                db.add(thread)
                db.commit()
                db.refresh(thread)
            user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
            assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
            thread.updated_at = datetime.now(UTC)
            db.add(user_message)
            db.add(assistant_message)
            db.add(thread)
            db.commit()
            db.refresh(user_message)
            db.refresh(assistant_message)
            return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)
        if action == "change_account_currency":
            current_payload = pending.action_payload or {}
            accounts_all = _list_accounts(db, current_user.id, include_inactive=True)
            acct_id = current_payload.get("account_id")
            if not acct_id:
                acct_match = None
                parsed_id = _parse_account_id(message)
                if parsed_id:
                    acct_match = next((a for a in accounts_all if a["id"] == parsed_id), None)
                if not acct_match:
                    acct_match = _match_account(message, accounts_all)
                if acct_match:
                    pending.action_payload = {**current_payload, "account_id": acct_match["id"], "account_name": acct_match["name"]}
                    db.add(pending)
                    db.commit()
                    reply = "Which 3-letter currency code should I use?"
                else:
                    reply = "Which account should I update?\n" + _format_accounts(accounts_all)
            else:
                next_currency = _parse_currency_code(message)
                if next_currency:
                    pending.action_payload = {**current_payload, "currency": next_currency}
                    db.add(pending)
                    db.commit()
                    reply = f"Confirm change currency for “{current_payload.get('account_name')}” to {next_currency}?"
                else:
                    reply = "Which 3-letter currency code should I use?"

            thread_id = payload.thread_id or pending.thread_id
            thread = None
            if thread_id:
                thread = (
                    db.query(TellerThread)
                    .filter(TellerThread.id == thread_id, TellerThread.user_id == current_user.id)
                    .first()
                )
            if not thread:
                thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
                db.add(thread)
                db.commit()
                db.refresh(thread)
            user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
            assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
            thread.updated_at = datetime.now(UTC)
            db.add(user_message)
            db.add(assistant_message)
            db.add(thread)
            db.commit()
            db.refresh(user_message)
            db.refresh(assistant_message)
            return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)
        if action in {"archive_account", "unarchive_account"}:
            current_payload = pending.action_payload or {}
            include_inactive = action == "unarchive_account"
            accounts_all = _list_accounts(db, current_user.id, include_inactive=True)
            acct_id = current_payload.get("account_id")
            if not acct_id:
                pool = [
                    acct
                    for acct in accounts_all
                    if bool(acct["is_active"]) is (action == "archive_account")
                ]
                acct_match = None
                parsed_id = _parse_account_id(message)
                if parsed_id:
                    acct_match = next((a for a in pool if a["id"] == parsed_id), None)
                if not acct_match:
                    acct_match = _match_account(message, pool)
                if acct_match:
                    pending.action_payload = {**current_payload, "account_id": acct_match["id"], "account_name": acct_match["name"]}
                    db.add(pending)
                    db.commit()
                    verb = "archive" if action == "archive_account" else "restore"
                    reply = f"Confirm {verb} for “{acct_match['name']}”?"
                else:
                    prompt = "Which account should I archive?\n" if action == "archive_account" else "Which account should I restore?\n"
                    reply = prompt + _format_accounts(pool)
            else:
                verb = "archive" if action == "archive_account" else "restore"
                reply = f"Confirm {verb} for “{current_payload.get('account_name')}”?"

            thread_id = payload.thread_id or pending.thread_id
            thread = None
            if thread_id:
                thread = (
                    db.query(TellerThread)
                    .filter(TellerThread.id == thread_id, TellerThread.user_id == current_user.id)
                    .first()
                )
            if not thread:
                thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
                db.add(thread)
                db.commit()
                db.refresh(thread)
            user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
            assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
            thread.updated_at = datetime.now(UTC)
            db.add(user_message)
            db.add(assistant_message)
            db.add(thread)
            db.commit()
            db.refresh(user_message)
            db.refresh(assistant_message)
            return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)
        if action == "create_account":
            current_payload = pending.action_payload or {}
            if not current_payload.get("name"):
                name = _parse_account_name(message)
                if not name and _mentions_history_or_prior_context(message):
                    currency = (current_payload.get("currency") or "USD").upper()
                    reply = f"I’m still creating that account. What name should I use? I currently have the currency set to {currency}."
                    thread_id = payload.thread_id or pending.thread_id
                    thread = None
                    if thread_id:
                        thread = (
                            db.query(TellerThread)
                            .filter(TellerThread.id == thread_id, TellerThread.user_id == current_user.id)
                            .first()
                        )
                    if not thread:
                        thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
                        db.add(thread)
                        db.commit()
                        db.refresh(thread)
                    user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
                    assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
                    thread.updated_at = datetime.now(UTC)
                    db.add(user_message)
                    db.add(assistant_message)
                    db.add(thread)
                    db.commit()
                    db.refresh(user_message)
                    db.refresh(assistant_message)
                    return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)
                if not name and not _is_action_phrase(message) and _is_valid_account_name_candidate(message):
                    name = message.strip()
                if name:
                    account_type = _parse_account_type(message) or current_payload.get("account_type")
                    account_currency = _parse_currency_code(message) or current_payload.get("currency")
                    updated_payload = {
                        **current_payload,
                        "name": name,
                        **({"currency": account_currency} if account_currency else {}),
                        **({"account_type": account_type} if account_type else {}),
                    }
                    start_balance = _parse_create_account_starting_balance(message)
                    if start_balance is not None:
                        updated_payload["starting_balance"] = str(start_balance)
                        updated_payload["starting_balance_prompted"] = True
                    pending.action_payload = updated_payload
                    db.add(pending)
                    db.commit()
                    if not account_type:
                        reply = "Which account type?\n" + _format_account_types()
                    else:
                        trusts = _list_trust_accounts(_list_accounts(db, current_user.id))
                        if account_type != "trust" and trusts and current_payload.get("parent_account_id") is None:
                            pending.status = "awaiting_account"
                            db.add(pending)
                            db.commit()
                            reply = "Should this go under a parent trust? Reply with a trust account # or 'no'.\n" + _format_accounts(trusts)
                        elif start_balance is not None:
                            reply = (
                                f"Confirm create account “{name}” ({account_type}, {(account_currency or 'USD').upper()}) "
                                f"with starting balance {_format_money(start_balance, account_currency or 'USD')}?"
                            )
                        else:
                            pending.action_payload = {**pending.action_payload, "starting_balance_prompted": True}
                            db.add(pending)
                            db.commit()
                            reply = "Starting balance? Reply with an amount or 'no'."
                else:
                    reply = "What should the account be named?"
            elif not current_payload.get("account_type"):
                account_type = _parse_account_type(message)
                account_currency = _parse_currency_code(message) or current_payload.get("currency")
                if account_type:
                    pending.action_payload = {
                        **current_payload,
                        "account_type": account_type,
                        **({"currency": account_currency} if account_currency else {}),
                    }
                    db.add(pending)
                    db.commit()
                    trusts = _list_trust_accounts(_list_accounts(db, current_user.id))
                    if account_type != "trust" and trusts:
                        pending.status = "awaiting_account"
                        db.add(pending)
                        db.commit()
                        reply = "Should this go under a parent trust? Reply with a trust account # or 'no'.\n" + _format_accounts(trusts)
                    else:
                        pending.action_payload = {**pending.action_payload, "starting_balance_prompted": True}
                        db.add(pending)
                        db.commit()
                        reply = "Starting balance? Reply with an amount or 'no'."
                else:
                    reply = "Which account type?\n" + _format_account_types()
            else:
                # Handle starting balance prompt
                if _mentions_history_or_prior_context(message):
                    currency = (current_payload.get("currency") or "USD").upper()
                    name = current_payload.get("name") or "that account"
                    account_type = current_payload.get("account_type") or "personal"
                    existing_balance = current_payload.get("starting_balance")
                    if existing_balance:
                        reply = (
                            f"I’m still creating “{name}” ({account_type}, {currency}) "
                            f"with starting balance {_format_money(existing_balance, currency)}. Reply 'yes' to confirm, or send a new starting balance."
                        )
                    else:
                        reply = f"I’m still creating “{name}” ({account_type}, {currency}). What starting balance should I use?"
                elif current_payload.get("starting_balance_prompted") and not current_payload.get("starting_balance"):
                    if lower_msg in NO_PARENT_WORDS:
                        pending.action_payload = {**current_payload, "starting_balance": "0"}
                        db.add(pending)
                        db.commit()
                        reply = (
                            f"Confirm create account “{pending.action_payload.get('name')}” "
                            f"({pending.action_payload.get('account_type')}, {(pending.action_payload.get('currency') or 'USD').upper()})?"
                        )
                    else:
                        start_balance = _parse_create_account_starting_balance(message)
                        if start_balance:
                            pending.action_payload = {**current_payload, "starting_balance": str(start_balance)}
                            db.add(pending)
                            db.commit()
                            reply = (
                                f"Confirm create account “{pending.action_payload.get('name')}” "
                                f"({pending.action_payload.get('account_type')}, {(pending.action_payload.get('currency') or 'USD').upper()}) "
                                f"with starting balance {_format_money(start_balance, pending.action_payload.get('currency') or 'USD')}?"
                            )
                        else:
                            reply = "Starting balance? Reply with an amount or 'no'."
                else:
                    reply = (
                        f"Confirm create account “{pending.action_payload.get('name')}” "
                        f"({pending.action_payload.get('account_type')}, {(pending.action_payload.get('currency') or 'USD').upper()})?"
                    )

            thread_id = payload.thread_id or pending.thread_id
            thread = None
            if thread_id:
                thread = (
                    db.query(TellerThread)
                    .filter(TellerThread.id == thread_id, TellerThread.user_id == current_user.id)
                    .first()
                )
            if not thread:
                thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
                db.add(thread)
                db.commit()
                db.refresh(thread)
            user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
            assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
            thread.updated_at = datetime.now(UTC)
            db.add(user_message)
            db.add(assistant_message)
            db.add(thread)
            db.commit()
            db.refresh(user_message)
            db.refresh(assistant_message)
            return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)

    thread = None
    if payload.thread_id:
        thread = (
            db.query(TellerThread)
            .filter(TellerThread.id == payload.thread_id, TellerThread.user_id == current_user.id)
            .first()
        )
    if not thread:
        thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
        db.add(thread)
        db.commit()
        db.refresh(thread)

    last_msg = (
        db.query(TellerMessage)
        .filter(TellerMessage.thread_id == thread.id)
        .order_by(TellerMessage.created_at.desc())
        .first()
    )
    if last_msg and last_msg.role == "user" and last_msg.content.strip() == message:
        raise HTTPException(status_code=409, detail="Please wait for the Teller to respond.")

    user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
    db.add(user_message)
    db.commit()
    db.refresh(user_message)

    accounts = _list_accounts(db, current_user.id)
    all_accounts = _list_accounts(db, current_user.id, include_inactive=True)

    if any(phrase in lower_msg for phrase in ["rename account", "change account name", "rename my account"]):
        acct_match = None
        parsed_id = _parse_account_id(message)
        if parsed_id:
            acct_match = next((a for a in all_accounts if a["id"] == parsed_id), None)
        if not acct_match:
            acct_match = _match_account(message, all_accounts)
        next_name = _parse_new_name(message)
        if not acct_match:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="awaiting_account",
                action_payload={"action": "rename_account"},
            )
            db.add(pending)
            db.commit()
            reply = "Which account should I rename?\n" + _format_accounts(all_accounts)
        elif not next_name:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="pending",
                action_payload={"action": "rename_account", "account_id": acct_match["id"], "account_name": acct_match["name"]},
            )
            db.add(pending)
            db.commit()
            reply = "What should the new account name be?"
        else:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="pending",
                action_payload={
                    "action": "rename_account",
                    "account_id": acct_match["id"],
                    "account_name": acct_match["name"],
                    "new_name": next_name,
                },
            )
            db.add(pending)
            db.commit()
            reply = f"Confirm rename “{acct_match['name']}” to “{next_name}”?"

        assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
        thread.updated_at = datetime.now(UTC)
        db.add(assistant_message)
        db.add(thread)
        db.commit()
        db.refresh(assistant_message)
        return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)

    if any(phrase in lower_msg for phrase in ["change currency", "update currency", "set currency"]):
        acct_match = None
        parsed_id = _parse_account_id(message)
        if parsed_id:
            acct_match = next((a for a in all_accounts if a["id"] == parsed_id), None)
        if not acct_match:
            acct_match = _match_account(message, all_accounts)
        next_currency = _parse_currency_code(message)
        if not acct_match:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="awaiting_account",
                action_payload={"action": "change_account_currency"},
            )
            db.add(pending)
            db.commit()
            reply = "Which account should I update?\n" + _format_accounts(all_accounts)
        elif not next_currency:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="pending",
                action_payload={
                    "action": "change_account_currency",
                    "account_id": acct_match["id"],
                    "account_name": acct_match["name"],
                },
            )
            db.add(pending)
            db.commit()
            reply = "Which 3-letter currency code should I use?"
        else:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="pending",
                action_payload={
                    "action": "change_account_currency",
                    "account_id": acct_match["id"],
                    "account_name": acct_match["name"],
                    "currency": next_currency,
                },
            )
            db.add(pending)
            db.commit()
            reply = f"Confirm change currency for “{acct_match['name']}” to {next_currency}?"

        assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
        thread.updated_at = datetime.now(UTC)
        db.add(assistant_message)
        db.add(thread)
        db.commit()
        db.refresh(assistant_message)
        return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)

    if "unarchive" in lower_msg or "restore account" in lower_msg:
        archived_accounts = [acct for acct in all_accounts if not acct["is_active"]]
        acct_match = None
        parsed_id = _parse_account_id(message)
        if parsed_id:
            acct_match = next((a for a in archived_accounts if a["id"] == parsed_id), None)
        if not acct_match:
            acct_match = _match_account(message, archived_accounts)
        if not acct_match:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="awaiting_account",
                action_payload={"action": "unarchive_account"},
            )
            db.add(pending)
            db.commit()
            reply = "Which account should I restore?\n" + _format_accounts(archived_accounts)
        else:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="pending",
                action_payload={"action": "unarchive_account", "account_id": acct_match["id"], "account_name": acct_match["name"]},
            )
            db.add(pending)
            db.commit()
            reply = f"Confirm restore for “{acct_match['name']}”?"

        assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
        thread.updated_at = datetime.now(UTC)
        db.add(assistant_message)
        db.add(thread)
        db.commit()
        db.refresh(assistant_message)
        return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)

    if "archive" in lower_msg:
        active_accounts = [acct for acct in all_accounts if acct["is_active"]]
        acct_match = None
        parsed_id = _parse_account_id(message)
        if parsed_id:
            acct_match = next((a for a in active_accounts if a["id"] == parsed_id), None)
        if not acct_match:
            acct_match = _match_account(message, active_accounts)
        if not acct_match:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="awaiting_account",
                action_payload={"action": "archive_account"},
            )
            db.add(pending)
            db.commit()
            reply = "Which account should I archive?\n" + _format_accounts(active_accounts)
        else:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="pending",
                action_payload={"action": "archive_account", "account_id": acct_match["id"], "account_name": acct_match["name"]},
            )
            db.add(pending)
            db.commit()
            reply = f"Confirm archive for “{acct_match['name']}”?"

        assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
        thread.updated_at = datetime.now(UTC)
        db.add(assistant_message)
        db.add(thread)
        db.commit()
        db.refresh(assistant_message)
        return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)

    # Detect create account intent
    if any(phrase in lower_msg for phrase in ["create account", "new account", "add account", "open account", "another account", "account open"]):
        name = _parse_account_name(message)
        account_type = _parse_account_type(message)
        account_currency = _parse_currency_code(message)
        start_balance = _parse_create_account_starting_balance(message)
        trusts = _list_trust_accounts(accounts)
        if not name:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="pending",
                action_payload={"action": "create_account", **({"currency": account_currency} if account_currency else {})},
            )
            db.add(pending)
            db.commit()
            if account_currency:
                reply = f"What should the account be named? I can create it in {account_currency}."
            else:
                reply = "What should the account be named?"
        elif not account_type:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="pending",
                action_payload={"action": "create_account", "name": name, **({"currency": account_currency} if account_currency else {})},
            )
            db.add(pending)
            db.commit()
            reply = "Which account type?\n" + _format_account_types()
        else:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="pending",
                action_payload={
                    "action": "create_account",
                    "name": name,
                    "account_type": account_type,
                    **({"currency": account_currency} if account_currency else {}),
                },
            )
            db.add(pending)
            db.commit()
            if account_type != "trust" and trusts:
                pending.status = "awaiting_account"
                db.add(pending)
                db.commit()
                reply = "Should this go under a parent trust? Reply with a trust account # or 'no'.\n" + _format_accounts(trusts)
            else:
                pending.action_payload = {
                    **pending.action_payload,
                    "starting_balance_prompted": True,
                    **({"starting_balance": str(start_balance)} if start_balance is not None else {}),
                }
                db.add(pending)
                db.commit()
                if start_balance is not None:
                    reply = (
                        f"Confirm create account “{name}” ({account_type}, {(account_currency or 'USD').upper()}) "
                        f"with starting balance {_format_money(start_balance, account_currency or 'USD')}?"
                    )
                else:
                    reply = "Starting balance? Reply with an amount or 'no'."

        assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
        thread.updated_at = datetime.now(UTC)
        db.add(assistant_message)
        db.add(thread)
        db.commit()
        db.refresh(assistant_message)
        return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)

    # Detect scheduled movement intent
    if _is_schedule_intent(lower_msg):
        amount = _extract_amount(lower_msg)
        direction = "debit" if any(word in lower_msg for word in ["withdraw", "withdrawal", "expense", "debit"]) else "credit"
        acct_id = _parse_account_id(lower_msg)
        match = None
        if acct_id:
            match = next((a for a in accounts if a["id"] == acct_id), None)
        if not match:
            match = _match_account(lower_msg, accounts)
        scheduled_for = _parse_date(lower_msg)
        if not amount:
            reply = "What amount should I schedule?"
        elif not match:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="awaiting_account",
                action_payload={
                    "action": "schedule",
                    "amount": str(amount),
                    "memo": "Teller scheduled movement",
                    "direction": direction,
                },
            )
            db.add(pending)
            db.commit()
            reply = "Which account should I use?\n" + _format_accounts(accounts)
        elif not scheduled_for:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="pending",
                action_payload={
                    "action": "schedule",
                    "account_id": match["id"],
                    "account_name": match["name"],
                    "amount": str(amount),
                    "memo": "Teller scheduled movement",
                    "direction": direction,
                },
            )
            db.add(pending)
            db.commit()
            reply = "When should I schedule it? (YYYY-MM-DD or YYYY-MM-DD HH:MM)"
        else:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="pending",
                action_payload={
                    "action": "schedule",
                    "account_id": match["id"],
                    "account_name": match["name"],
                    "amount": str(amount),
                    "memo": "Teller scheduled movement",
                    "direction": direction,
                    "scheduled_for": scheduled_for.isoformat(),
                },
            )
            db.add(pending)
            db.commit()
            reply = f"Confirm scheduled movement of ${amount:.2f} on {scheduled_for.date()} for “{match['name']}”?"

        assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
        thread.updated_at = datetime.now(UTC)
        db.add(assistant_message)
        db.add(thread)
        db.commit()
        db.refresh(assistant_message)
        return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)

    # Detect deposit intent
    if any(word in lower_msg for word in ["deposit", "add", "credit"]):
        primary_clause = _extract_primary_action_clause(message)
        primary_lower_msg = primary_clause.lower()
        amount = _extract_amount(primary_clause)
        queued_followup = _extract_multi_action_followup(message)
        acct_id = _parse_account_id(primary_clause)
        match = None
        if acct_id:
            match = next((a for a in accounts if a["id"] == acct_id), None)
        if not match:
            match = _match_account(primary_lower_msg, accounts)
        if not amount:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="awaiting_amount",
                action_payload={
                    "action": "deposit",
                    "memo": "Teller deposit",
                    **({"queued_followup": queued_followup} if queued_followup else {}),
                },
            )
            db.add(pending)
            db.commit()
            reply = "What amount should I deposit?"
        elif not match:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="awaiting_account",
                action_payload={
                    "action": "deposit",
                    "amount": str(amount),
                    "memo": "Teller deposit",
                    **({"queued_followup": queued_followup} if queued_followup else {}),
                },
            )
            db.add(pending)
            db.commit()
            reply = "Which account should I use?\n" + _format_accounts(accounts)
        else:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="pending",
                action_payload={
                    "action": "deposit",
                    "account_id": match["id"],
                    "account_name": match["name"],
                    "amount": str(amount),
                    "memo": "Teller deposit",
                    **({"queued_followup": queued_followup} if queued_followup else {}),
                },
            )
            db.add(pending)
            db.commit()
            reply = f"Confirm deposit {_format_money(amount, match.get('currency', 'USD'))} into “{match['name']}”?"

        assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
        thread.updated_at = datetime.now(UTC)
        db.add(assistant_message)
        db.add(thread)
        db.commit()
        db.refresh(assistant_message)
        return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)

    # Detect withdrawal/expense intent
    if any(word in lower_msg for word in ["withdraw", "withdrawal", "expense", "debit", "spend"]):
        amount = _extract_amount(lower_msg)
        acct_id = _parse_account_id(lower_msg)
        match = None
        if acct_id:
            match = next((a for a in accounts if a["id"] == acct_id), None)
        if not match:
            match = _match_account(lower_msg, accounts)
        if not amount:
            reply = "What amount should I withdraw?"
        elif not match:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="awaiting_account",
                action_payload={
                    "action": "withdraw",
                    "amount": str(amount),
                    "memo": "Teller withdrawal",
                },
            )
            db.add(pending)
            db.commit()
            reply = "Which account should I use?\n" + _format_accounts(accounts)
        else:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="pending",
                action_payload={
                    "action": "withdraw",
                    "account_id": match["id"],
                    "account_name": match["name"],
                    "amount": str(amount),
                    "memo": "Teller withdrawal",
                },
            )
            db.add(pending)
            db.commit()
            reply = f"Confirm withdrawal {_format_money(amount, match.get('currency', 'USD'))} from “{match['name']}”?"

        assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
        thread.updated_at = datetime.now(UTC)
        db.add(assistant_message)
        db.add(thread)
        db.commit()
        db.refresh(assistant_message)
        return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)

    # Detect transfer intent
    if _contains_transfer_intent(lower_msg) and not _is_negated_transfer(lower_msg):
        amount = _extract_amount(lower_msg)
        ids = re.findall(r"(?:account\s*#?\s*|#)(\d+)", lower_msg)
        from_id = int(ids[0]) if len(ids) > 0 else None
        to_id = int(ids[1]) if len(ids) > 1 else None
        explicit_from, explicit_to = _parse_transfer_account_phrase(message, accounts)
        if explicit_from:
            from_id = explicit_from["id"]
        if explicit_to:
            to_id = explicit_to["id"]
        name_matches = _match_accounts_in_text(lower_msg, accounts)
        preferred_currency = _parse_currency_code(lower_msg)
        if preferred_currency and not from_id:
            preferred_accounts = [acct for acct in accounts if (acct.get("currency") or "USD").upper() == preferred_currency]
            if len(preferred_accounts) == 1:
                from_id = preferred_accounts[0]["id"]
        if not from_id and not to_id and len(name_matches) >= 2:
            from_id = name_matches[0]["id"]
            to_id = name_matches[1]["id"]
        if not amount:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="awaiting_amount",
                action_payload={
                    "action": "transfer",
                    "memo": "Teller transfer",
                    "transfer_stage": "from",
                },
            )
            db.add(pending)
            db.commit()
            reply = "What amount should I transfer?"
        elif not from_id or not to_id:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="awaiting_account",
                action_payload={
                    "action": "transfer",
                    "amount": str(amount),
                    "memo": "Teller transfer",
                    "transfer_stage": "from",
                    **({"currency": preferred_currency} if preferred_currency else {}),
                    **({"from_account_id": from_id} if from_id else {}),
                },
            )
            db.add(pending)
            db.commit()
            if from_id:
                available_accounts = [acct for acct in accounts if acct["id"] != from_id]
                reply = "Which account should I transfer to?\n" + _format_accounts(available_accounts)
            else:
                reply = "Which account should I transfer from?\n" + _format_accounts(accounts)
        else:
            from_acct = next((a for a in accounts if a["id"] == from_id), None)
            to_acct = next((a for a in accounts if a["id"] == to_id), None)
            if not from_acct or not to_acct:
                pending = TellerAuditLog(
                    user_id=current_user.id,
                    thread_id=thread.id,
                    action_type="pending_action",
                    status="awaiting_account",
                    action_payload={
                        "action": "transfer",
                        "amount": str(amount),
                        "memo": "Teller transfer",
                        "transfer_stage": "from",
                    },
                )
                db.add(pending)
                db.commit()
                reply = "Which account should I transfer from?\n" + _format_accounts(accounts)
            else:
                pending = TellerAuditLog(
                    user_id=current_user.id,
                    thread_id=thread.id,
                    action_type="pending_action",
                    status="pending",
                    action_payload={
                        "action": "transfer",
                        "from_account_id": from_id,
                        "from_account_name": from_acct["name"],
                        "to_account_id": to_id,
                        "to_account_name": to_acct["name"],
                        "amount": str(amount),
                        "currency": preferred_currency or from_acct.get("currency") or "USD",
                        "memo": "Teller transfer",
                        "transfer_stage": "to",
                    },
                )
                db.add(pending)
                db.commit()
                reply = f"Confirm transfer {_format_money(amount, preferred_currency or from_acct.get('currency', 'USD'))} from “{from_acct['name']}” to “{to_acct['name']}”?"

        assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
        thread.updated_at = datetime.now(UTC)
        db.add(assistant_message)
        db.add(thread)
        db.commit()
        db.refresh(assistant_message)
        return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)

    # Detect scheduled movement intent
    if "schedule" in lower_msg or "scheduled" in lower_msg:
        amount = _extract_amount(lower_msg)
        direction = "debit" if any(word in lower_msg for word in ["withdraw", "withdrawal", "expense", "debit"]) else "credit"
        acct_id = _parse_account_id(lower_msg)
        match = None
        if acct_id:
            match = next((a for a in accounts if a["id"] == acct_id), None)
        if not match:
            match = _match_account(lower_msg, accounts)
        scheduled_for = _parse_date(lower_msg)
        if not amount:
            reply = "What amount should I schedule?"
        elif not match:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="awaiting_account",
                action_payload={
                    "action": "schedule",
                    "amount": str(amount),
                    "memo": "Teller scheduled movement",
                    "direction": direction,
                },
            )
            db.add(pending)
            db.commit()
            reply = "Which account should I use?\n" + _format_accounts(accounts)
        elif not scheduled_for:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="pending",
                action_payload={
                    "action": "schedule",
                    "account_id": match["id"],
                    "account_name": match["name"],
                    "amount": str(amount),
                    "memo": "Teller scheduled movement",
                    "direction": direction,
                },
            )
            db.add(pending)
            db.commit()
            reply = "When should I schedule it? (YYYY-MM-DD or YYYY-MM-DD HH:MM)"
        else:
            pending = TellerAuditLog(
                user_id=current_user.id,
                thread_id=thread.id,
                action_type="pending_action",
                status="pending",
                action_payload={
                    "action": "schedule",
                    "account_id": match["id"],
                    "account_name": match["name"],
                    "amount": str(amount),
                    "memo": "Teller scheduled movement",
                    "direction": direction,
                    "scheduled_for": scheduled_for.isoformat(),
                },
            )
            db.add(pending)
            db.commit()
            reply = f"Confirm scheduled movement of ${amount:.2f} on {scheduled_for.date()} for “{match['name']}”?"

        assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
        thread.updated_at = datetime.now(UTC)
        db.add(assistant_message)
        db.add(thread)
        db.commit()
        db.refresh(assistant_message)
        return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)

    # Lightweight account/balance awareness for teller actions
    if _is_explicit_account_request(lower_msg) and ("account" in lower_msg or "accounts" in lower_msg or "balance" in lower_msg):
        reply = _format_accounts(accounts)
        assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
        thread.updated_at = datetime.now(UTC)
        db.add(assistant_message)
        db.add(thread)
        db.commit()
        db.refresh(assistant_message)
        return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)

    history = (
        db.query(TellerMessage)
        .filter(TellerMessage.thread_id == thread.id)
        .order_by(TellerMessage.created_at.desc())
        .limit(10)
        .all()
    )
    history_payload = [
        {"role": row.role, "content": row.content} for row in reversed(history) if row.role in {"user", "assistant"}
    ]
    history_payload = _build_same_user_history(db, current_user.id, thread.id, history_payload)
    cached, reply = await generate_teller_reply(
        current_user.id, message, history=history_payload, short_mode=bool(payload.short_mode)
    )
    assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
    thread.updated_at = datetime.now(UTC)
    db.add(assistant_message)
    db.add(thread)
    db.commit()
    db.refresh(assistant_message)
    db.refresh(thread)
    ensure_credit_actions(db)
    record_credit_action(db, current_user.id, "teller_message")

    audit = TellerAuditLog(
        user_id=current_user.id,
        thread_id=thread.id,
        action_type="chat",
        status="cached" if cached else "generated",
        action_payload={"message": message},
    )
    db.add(audit)
    db.commit()

    return TellerChatResponse(thread=thread, user_message=user_message, assistant_message=assistant_message)


@router.post("/teller/chat-stream")
async def chat_stream(
    payload: TellerChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
):
    require_signature(current_user)
    if not rate_limiter.check(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Teller rate limit reached. Please wait a moment.",
        )

    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    if _should_use_standard_teller_chat(db, current_user.id, payload.thread_id, message):
        response = await chat(payload, db, current_user)

        async def fallback_stream():
            yield _ndjson_event({"type": "thread", "thread": response.thread.model_dump(mode="json")})
            yield _ndjson_event({"type": "user_message", "message": response.user_message.model_dump(mode="json")})
            yield _ndjson_event({"type": "assistant_message", "message": response.assistant_message.model_dump(mode="json")})
            yield _ndjson_event({"type": "done"})

        return StreamingResponse(fallback_stream(), media_type="application/x-ndjson")

    thread = None
    if payload.thread_id:
        thread = (
            db.query(TellerThread)
            .filter(TellerThread.id == payload.thread_id, TellerThread.user_id == current_user.id)
            .first()
        )
    if not thread:
        thread = TellerThread(user_id=current_user.id, title=message[:42] or "New Teller Session")
        db.add(thread)
        db.commit()
        db.refresh(thread)

    last_msg = (
        db.query(TellerMessage)
        .filter(TellerMessage.thread_id == thread.id)
        .order_by(TellerMessage.created_at.desc())
        .first()
    )
    if last_msg and last_msg.role == "user" and last_msg.content.strip() == message:
        raise HTTPException(status_code=409, detail="Please wait for the Teller to respond.")

    user_message = TellerMessage(thread_id=thread.id, role="user", content=message)
    db.add(user_message)
    db.commit()
    db.refresh(user_message)

    history = (
        db.query(TellerMessage)
        .filter(TellerMessage.thread_id == thread.id)
        .order_by(TellerMessage.created_at.desc())
        .limit(10)
        .all()
    )
    history_payload = [
        {"role": row.role, "content": row.content} for row in reversed(history) if row.role in {"user", "assistant"}
    ]
    history_payload = _build_same_user_history(db, current_user.id, thread.id, history_payload)

    async def event_stream():
        queue: asyncio.Queue[dict] = asyncio.Queue()

        async def on_delta(delta: str):
            await queue.put({"type": "delta", "delta": delta})

        async def produce():
            try:
                cached, reply = await asyncio.wait_for(
                    stream_teller_reply(
                        current_user.id,
                        message,
                        history=history_payload,
                        short_mode=bool(payload.short_mode),
                        on_delta=on_delta,
                    ),
                    timeout=STREAM_REPLY_TIMEOUT_SECONDS,
                )
                await queue.put({"type": "final_reply", "cached": cached, "reply": reply})
            except asyncio.TimeoutError:
                await queue.put(
                    {
                        "type": "final_reply",
                        "cached": False,
                        "reply": "## Insight\nI hit a delay before the reply completed.\n\n## Reflection\nPlease send that once more, or tell me whether you want grounding, scripting, affirmations, or a next step.",
                    }
                )
            except Exception as exc:
                await queue.put({"type": "error", "detail": str(exc)})

        producer = asyncio.create_task(produce())

        try:
            yield _ndjson_event({"type": "thread", "thread": TellerThreadRead.model_validate(thread).model_dump(mode="json")})
            yield _ndjson_event({"type": "user_message", "message": TellerMessageRead.model_validate(user_message).model_dump(mode="json")})

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=STREAM_IDLE_TIMEOUT_SECONDS)
                except asyncio.TimeoutError:
                    event = {
                        "type": "final_reply",
                        "cached": False,
                        "reply": "## Insight\nThe reply stream stalled before Fortune could finish.\n\n## Reflection\nPlease send that once more, or tell me the direction you want: grounding, scripting, affirmations, or a next step.",
                    }
                event_type = event.get("type")
                if event_type == "delta":
                    yield _ndjson_event(event)
                    continue
                if event_type == "error":
                    yield _ndjson_event(event)
                    break
                if event_type == "final_reply":
                    reply = event.get("reply") or "I’m here. Please try again."
                    assistant_message = TellerMessage(thread_id=thread.id, role="assistant", content=reply)
                    thread.updated_at = datetime.now(UTC)
                    db.add(assistant_message)
                    db.add(thread)
                    db.commit()
                    db.refresh(assistant_message)
                    db.refresh(thread)
                    ensure_credit_actions(db)
                    record_credit_action(db, current_user.id, "teller_message")
                    audit = TellerAuditLog(
                        user_id=current_user.id,
                        thread_id=thread.id,
                        action_type="chat",
                        status="cached" if event.get("cached") else "generated",
                        action_payload={"message": message},
                    )
                    db.add(audit)
                    db.commit()
                    yield _ndjson_event({"type": "assistant_message", "message": TellerMessageRead.model_validate(assistant_message).model_dump(mode="json")})
                    yield _ndjson_event({"type": "done"})
                    break
        finally:
            if not producer.done():
                producer.cancel()

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.post("/teller/confirm", response_model=TellerConfirmResponse)
def confirm_action(
    payload: TellerConfirmRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
):
    require_signature(current_user)
    audit = TellerAuditLog(
        user_id=current_user.id,
        thread_id=payload.thread_id,
        action_type=payload.action_type,
        status="confirmed",
        action_payload=payload.action_payload,
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return TellerConfirmResponse(confirmation_id=audit.id, status="confirmed")


@router.post("/teller/execute", response_model=TellerExecuteResponse)
def execute_action(
    payload: TellerExecuteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
):
    require_signature(current_user)
    audit = (
        db.query(TellerAuditLog)
        .filter(TellerAuditLog.id == payload.confirmation_id, TellerAuditLog.user_id == current_user.id)
        .first()
    )
    if not audit:
        raise HTTPException(status_code=404, detail="Confirmation not found")
    execute_log = TellerAuditLog(
        user_id=current_user.id,
        thread_id=audit.thread_id,
        action_type="execute",
        status="queued",
        action_payload={"confirmation_id": audit.id},
    )
    db.add(execute_log)
    db.commit()
    return TellerExecuteResponse(status="queued")


@router.post("/teller/persona")
def update_persona(
    payload: dict,
    current_user: User = Depends(get_verified_user),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    name = payload.get("name")
    prompt = payload.get("prompt")
    set_persona_override(name=name, prompt=prompt)
    return {"status": "updated"}


@router.get("/teller/health")
async def teller_health():
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0)) as client:
            res = await client.get("https://api.openai.com/v1/models")
        return {"ok": res.status_code in {200, 401}, "status": res.status_code}
    except httpx.HTTPError as exc:
        return {"ok": False, "status": "error", "detail": str(exc)}


@router.post("/teller/test-openai")
async def teller_test_openai(current_user: User = Depends(get_verified_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY is missing")
    payload = {
        "model": settings.OPENAI_MODEL,
        "input": "ping",
        "max_output_tokens": 16,
    }
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}
    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
            res = await client.post("https://api.openai.com/v1/responses", json=payload, headers=headers)
        if res.status_code >= 400:
            return {
                "ok": False,
                "status": res.status_code,
                "ms": int((time.time() - start) * 1000),
                "error": res.text[:800],
            }
        return {"ok": True, "status": res.status_code, "ms": int((time.time() - start) * 1000)}
    except httpx.HTTPError as exc:
        return {"ok": False, "status": "error", "detail": str(exc)}
