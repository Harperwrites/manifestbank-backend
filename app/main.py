# app/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings

from app.routes.auth import router as auth_router
from app.routes.accounts import router as accounts_router
from app.routes.transactions import router as transactions_router
from app.routes.users import router as users_router
from app.routes.dashboard import router as dashboard_router
from app.routes.ledger import router as ledger_router
from app.routes import admin
from app.routes import accounts 
from app.db import init_db
from app.db.init_db import init_db
from app.routes.summary import router as summary_router
from app.routes.scheduled import router as scheduled_router
from app.routes.ether import router as ether_router
from app.routes.pwa import router as pwa_router
from app.routes.dev import router as dev_router
from app.routes.journal import router as journal_router
from app.routes.affirmations import router as affirmations_router
from app.routes.contact import router as contact_router
from app.routes.statements import router as statements_router
from app.routes.legal import router as legal_router
from app.routes.billing import router as billing_router



app = FastAPI()

init_db()


@app.get("/")
def root():
    return {"status": "ok"}


app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(accounts_router)
app.include_router(transactions_router)
app.include_router(users_router)
app.include_router(dashboard_router)
app.include_router(admin.router)
app.include_router(accounts.router)
app.include_router(ledger_router)
app.include_router(summary_router)
app.include_router(scheduled_router)
app.include_router(ether_router)
app.include_router(pwa_router)
app.include_router(dev_router)
app.include_router(journal_router)
app.include_router(affirmations_router)
app.include_router(contact_router)
app.include_router(statements_router)
app.include_router(legal_router)
app.include_router(billing_router)

# Optional compatibility: POST /transfer (some earlier tests/tools used this)
from app.routes.transactions import transfer_route as root_transfer_route  # noqa: E402

app.post("/transfer")(root_transfer_route)

default_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
]
env_origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]
allow_origins = sorted(set(default_origins + env_origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health_check():
    return {
        "status": "ManifestBank backend alive",
        "googleAuthStart": "/auth/google/start",
        "googleAuthCallback": "/auth/google/callback",
    }


@app.on_event("startup")
async def start_scheduler():
    from app.services.scheduler import schedule_loop
    import asyncio

    asyncio.create_task(schedule_loop())
