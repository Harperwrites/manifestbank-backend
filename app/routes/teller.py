# app/routes/teller.py

from datetime import datetime, UTC
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_verified_user
from app.core.config import settings
import time
from app.db.session import get_db
from app.models.user import User
from app.models.teller import TellerThread, TellerMessage, TellerAuditLog
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
from app.services.teller_provider import generate_teller_reply, rate_limiter, set_persona_override
from app.services.credit import record_credit_action, ensure_credit_actions
import httpx

router = APIRouter(tags=["teller"])


def require_signature(user: User) -> None:
    if user.role == "admin":
        return
    if not user.is_premium:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="ManifestBank™ Signature is required to use the Teller.",
        )


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
