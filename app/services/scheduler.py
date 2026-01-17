import asyncio

from app.db.session import SessionLocal
from app.crud.crud_scheduled_entry import post_due_entries


async def schedule_loop():
    while True:
        db = SessionLocal()
        try:
            post_due_entries(db)
        finally:
            db.close()
        await asyncio.sleep(60)
