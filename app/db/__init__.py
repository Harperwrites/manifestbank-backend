# app/db/__init__.py
# Keep this file light to avoid circular imports.

from app.db.session import Base, engine, get_db  # re-export if you like
