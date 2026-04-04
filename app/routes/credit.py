from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.session import get_db
from app.core.security import get_current_user
from app.models.credit import CreditAction, CreditActionCompletion, CreditTodo
from app.schemas.credit import (
    CreditActionRead,
    CreditActionComplete,
    CreditSummary,
    CreditBureauDetail,
    CreditTodoRead,
    CreditTodoCreate,
    CreditReport,
    CreditReportItem,
)
from app.services.credit import (
    complete_credit_action_by_id,
    ensure_credit_actions,
    get_credit_summary,
    get_bureau_detail,
    points_for_action_type,
    record_daily_login,
)
from app.services.tier import is_premium

router = APIRouter(prefix="/credit", tags=["credit"])


@router.get("/summary", response_model=CreditSummary)
def credit_summary(
    days: int = 7,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    ensure_credit_actions(db)
    safe_days = 7 if days not in {7, 30, 90} else days
    return get_credit_summary(db, current_user.id, safe_days)


@router.get("/actions", response_model=list[CreditActionRead])
def credit_actions(
    bureau: str | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    ensure_credit_actions(db)
    query = db.query(CreditAction).filter(CreditAction.active.is_(True))
    if bureau:
        query = query.filter(CreditAction.primary_bureau == bureau)
    actions = query.order_by(func.random()).limit(6).all()
    return actions


@router.post("/actions/complete", response_model=dict)
def complete_action(
    payload: CreditActionComplete,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    ensure_credit_actions(db)
    action, completed = complete_credit_action_by_id(db, current_user.id, payload.action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found.")
    if not completed:
        raise HTTPException(status_code=429, detail="Daily credit cap reached.")
    return {"status": "completed", "confirmation": action.confirmation_copy}


@router.get("/bureau/{bureau}", response_model=CreditBureauDetail)
def bureau_detail(
    bureau: str,
    days: int = 7,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    ensure_credit_actions(db)
    normalized = bureau.strip().lower()
    mapping = {
        "iab": "IAB",
        "identity": "IAB",
        "emotional": "Emotional Reserve",
        "emotional-reserve": "Emotional Reserve",
        "reserve": "Emotional Reserve",
        "ctb": "CTB",
        "cognitive": "CTB",
    }
    if normalized not in mapping:
        raise HTTPException(status_code=404, detail="Bureau not found.")
    safe_days = 7 if days not in {7, 30, 90} else days
    return get_bureau_detail(db, current_user.id, mapping[normalized], safe_days)


@router.get("/todos", response_model=list[CreditTodoRead])
def list_todos(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    ensure_credit_actions(db)
    todos = (
        db.query(CreditTodo)
        .filter(CreditTodo.user_id == current_user.id)
        .order_by(CreditTodo.created_at.desc())
        .all()
    )
    return [
        CreditTodoRead(
            id=todo.id,
            action_id=todo.action_id,
            action_type=todo.action_type,
            status=todo.status,
            title=todo.action.title,
            description=todo.action.description,
            action_route=todo.action.action_route,
        )
        for todo in todos
    ]


@router.post("/todos", response_model=CreditTodoRead)
def create_todo(
    payload: CreditTodoCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    ensure_credit_actions(db)
    if not is_premium(current_user):
        raise HTTPException(status_code=403, detail="ManifestBank™ Signature required to pin credit actions.")
    action = db.query(CreditAction).filter(CreditAction.id == payload.action_id).first()
    if not action or not action.active:
        raise HTTPException(status_code=404, detail="Action not found.")
    existing = (
        db.query(CreditTodo)
        .filter(
            CreditTodo.user_id == current_user.id,
            CreditTodo.action_id == action.id,
            CreditTodo.status == "open",
        )
        .first()
    )
    if existing:
        return CreditTodoRead(
            id=existing.id,
            action_id=existing.action_id,
            action_type=existing.action_type,
            status=existing.status,
            title=action.title,
            description=action.description,
            action_route=action.action_route,
        )
    action_type = action.action_type or "unknown"
    todo = CreditTodo(user_id=current_user.id, action_id=action.id, action_type=action_type, status="open")
    db.add(todo)
    db.commit()
    db.refresh(todo)
    return CreditTodoRead(
        id=todo.id,
        action_id=todo.action_id,
        action_type=todo.action_type,
        status=todo.status,
        title=action.title,
        description=action.description,
        action_route=action.action_route,
    )


@router.delete("/todos/{todo_id}")
def delete_todo(todo_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    todo = db.query(CreditTodo).filter(CreditTodo.id == todo_id, CreditTodo.user_id == current_user.id).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found.")
    db.delete(todo)
    db.commit()
    return {"status": "deleted"}


@router.delete("/todos/by-action/{action_id}")
def delete_todo_by_action(action_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    todo = (
        db.query(CreditTodo)
        .filter(CreditTodo.user_id == current_user.id, CreditTodo.action_id == action_id, CreditTodo.status == "open")
        .first()
    )
    if not todo:
        return {"status": "not_found"}
    db.delete(todo)
    db.commit()
    return {"status": "deleted"}


@router.get("/report", response_model=CreditReport)
def credit_report(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    ensure_credit_actions(db)
    premium = is_premium(current_user)
    rows = (
        db.query(CreditActionCompletion, CreditAction)
        .join(CreditAction, CreditAction.id == CreditActionCompletion.action_id)
        .filter(CreditActionCompletion.user_id == current_user.id)
        .order_by(CreditActionCompletion.completed_at.desc())
        .limit(200)
        .all()
    )
    items = [
        CreditReportItem(
            action_id=action.id,
            title=action.title,
            primary_bureau=action.primary_bureau,
            completed_at=completion.completed_at,
            points=points_for_action_type(action.action_type, premium),
            action_type=action.action_type,
        )
        for completion, action in rows
    ]
    return CreditReport(items=items)


@router.post("/daily-login")
def credit_daily_login(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    ensure_credit_actions(db)
    awarded = record_daily_login(db, current_user.id)
    points = points_for_action_type("daily_login", is_premium(current_user)) if awarded else 0
    return {"awarded": awarded, "points": points}
