# test/conftest.py

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app as fastapi_app
from app.db.session import get_db, Base
from app.models.user import User
from app.core.config import settings
from app.services import email as email_service
from app.routes import auth as auth_routes

# Ensure models are imported so Base.metadata is populated
# Adjust imports if your models live somewhere else.
try:
    import app.models  # noqa: F401
except Exception:
    pass


SQLALCHEMY_DATABASE_URL = "sqlite+pysqlite://"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest_asyncio.fixture
async def client(db):
    settings.RESEND_API_KEY = None
    settings.RESEND_FROM_EMAIL = None
    settings.RESEND_FALLBACK_API_KEY = None
    settings.RESEND_FALLBACK_FROM_EMAIL = None
    settings.SIGNUP_ALERT_EMAIL = None
    email_service.send_verification_email = lambda *args, **kwargs: True
    email_service.send_signup_alert_email = lambda *args, **kwargs: True
    auth_routes.send_verification_email = lambda *args, **kwargs: True
    auth_routes.send_signup_alert_email = lambda *args, **kwargs: True

    def override_get_db():
        yield db

    fastapi_app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    fastapi_app.dependency_overrides.clear()


@pytest.fixture
def auth_helper(db):
    async def _register_and_login(
        client,
        email: str,
        password: str,
        username: str,
        *,
        premium: bool = True,
        verified: bool = True,
    ):
        await client.post(
            "/auth/register",
            json={
                "email": email,
                "password": password,
                "username": username,
                "accept_terms": True,
            },
        )
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.email_verified = verified
            user.is_premium = premium
            db.add(user)
            db.commit()
        return await client.post("/auth/login", json={"email": email, "password": password})

    return _register_and_login
