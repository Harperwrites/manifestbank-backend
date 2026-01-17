# app/db/init_db.py

from app.db.session import Base, engine
import app.db.base  # noqa: F401  (ensures models are imported/registered)

def init_db() -> None:
    Base.metadata.create_all(bind=engine)
