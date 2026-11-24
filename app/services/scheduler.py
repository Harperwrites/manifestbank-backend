import asyncio
import logging
from app.db.session import SessionLocal
from app.crud.crud_scheduled_entry import post_due_entries


async def schedule_loop():
    from app.services.email_center import tick
    while True:
        db = SessionLocal()
        try:
            post_due_entries(db)
        except Exception:
            db.rollback()
            logging.exception('Scheduled entries stopped; will check next minute')
        finally:
            db.close()
        try:
            await asyncio.to_thread(tick)
        except Exception:
            logging.exception('Email center tick stopped; no blind send retries')
        await asyncio.sleep(60)
