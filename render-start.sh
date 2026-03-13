#!/usr/bin/env bash
set -e

alembic upgrade heads

exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
