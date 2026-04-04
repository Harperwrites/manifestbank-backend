from datetime import datetime
from pydantic import BaseModel, ConfigDict


class CreditActionRead(BaseModel):
    id: int
    action_type: str | None = None
    action_route: str | None = None
    title: str
    description: str
    primary_bureau: str
    secondary_bureau: str | None = None
    confirmation_copy: str

    model_config = ConfigDict(from_attributes=True)


class CreditActionComplete(BaseModel):
    action_id: int


class CreditScores(BaseModel):
    composite: int
    iab: int
    emotional: int
    ctb: int


class CreditSummary(BaseModel):
    scores: CreditScores
    updated_at: datetime
    total_actions_7d: int
    total_actions_30d: int
    completed_iab_30d: int
    completed_emotional_30d: int
    completed_ctb_30d: int
    streak_days: int
    daily_cap: int
    daily_used: int
    trend_7d: list[int]
    drivers: dict


class CreditBureauDetail(BaseModel):
    bureau: str
    score: int
    trend: list[int]
    days: int
    drivers: list[str]


class CreditTodoRead(BaseModel):
    id: int
    action_id: int
    action_type: str | None = None
    status: str
    title: str
    description: str
    action_route: str | None = None

    model_config = ConfigDict(from_attributes=True)


class CreditTodoCreate(BaseModel):
    action_id: int


class CreditReportItem(BaseModel):
    action_id: int
    title: str
    primary_bureau: str
    completed_at: datetime
    points: int
    action_type: str | None = None


class CreditReport(BaseModel):
    items: list[CreditReportItem]
