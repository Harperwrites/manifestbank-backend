# app/deps.py
# Compatibility shim: some modules import get_current_user from app.deps

from app.auth.deps import get_current_user, get_db  # re-export
