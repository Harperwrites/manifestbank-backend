"""One approved campaign sender, durable quotas, no quota pooling or blind retries."""
import hashlib
import os
import time
import uuid
from datetime import datetime, UTC, timedelta
from urllib.parse import urlencode
import httpx
from fastapi import HTTPException
from sqlalchemy import func, update, or_
from sqlalchemy.exc import IntegrityError
from app.db.session import SessionLocal
from app.models.user import User
from app.models.promotion import PromotionEmail, PromotionOptOut
from app.models.email_center import EmailJob, EmailJobRecipient, EmailSenderDay, EmailCenterAudit
from app.services import november_offer as offer
from app.services.email import _configured_resend_accounts, render_november_offer_email
from app.core.config import settings


def now():
    return datetime.now(UTC)


def aware(value):
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


def active_sender():
    name = os.getenv('EMAIL_CENTER_SENDER', 'account_6')
    account = next((a for a in _configured_resend_accounts() if a.name == name), None)
    if not account:
        raise HTTPException(503, 'The campaign sender is not configured in Render.')
    return account


def sender_key(account):
    return hashlib.sha256(account.api_key.encode()).hexdigest()[:32]


def cap(account):
    # This is a ceiling for this queue, never a replacement for the provider quota.
    return max(0, min(account.daily_limit or 100, 100) - max(0, account.daily_buffer))


def next_reset():
    return (now() + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def audit(db, action, actor=None, job=None, detail=''):
    db.add(EmailCenterAudit(actor_id=actor, job_id=job, action=action, detail=detail[:500]))


def quota(db, account):
    key, date = sender_key(account), now().date().isoformat()
    row = db.query(EmailSenderDay).filter_by(sender_key=key, day=date).first()
    if row:
        return row
    prior = db.query(EmailSenderDay).filter_by(sender_key=key, confirmed=True).first()
    row = EmailSenderDay(sender_key=key, day=date, used=0, confirmed=bool(prior),
                         source='New UTC day; managed queue usage only' if prior else 'Confirm usage in Resend before first send')
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        row = db.query(EmailSenderDay).filter_by(sender_key=key, day=date).one()
    return row


def confirm_usage(db, used, actor):
    account = active_sender()
    row = quota(db, account)
    # Monotonic within a day; never lower usage to manufacture more capacity.
    claimed = db.execute(update(EmailSenderDay).where(EmailSenderDay.id == row.id, EmailSenderDay.used <= used)
                         .values(used=used, confirmed=True, source='Admin confirmed total used today in Resend'))
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, 'Usage cannot be lowered within the same UTC day.')
    audit(db, 'usage_confirmed', actor, detail='UTC usage baseline: ' + str(used))
    db.query(EmailJob).filter_by(status='needs_usage').update({'status': 'approved'})
    db.commit()


def reserve(db, account):
    row = quota(db, account)
    if not row.confirmed:
        return 'needs_usage'
    changed = db.execute(update(EmailSenderDay).where(EmailSenderDay.id == row.id,
                         EmailSenderDay.used < cap(account), EmailSenderDay.confirmed.is_(True))
                         .values(used=EmailSenderDay.used + 1))
    db.commit()
    return row.id if changed.rowcount == 1 else 'waiting_quota'


def release(db, quota_id):
    db.execute(update(EmailSenderDay).where(EmailSenderDay.id == quota_id, EmailSenderDay.used > 0)
               .values(used=EmailSenderDay.used - 1))


def job_view(db, job):
    rows = db.query(EmailJobRecipient).filter_by(job_id=job.id).order_by(EmailJobRecipient.user_id).all()
    counts = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return dict(id=job.id, status=job.status, note=job.note, requested=job.requested,
                sender=job.sender, created_at=job.created_at, approved_at=job.approved_at,
                resume_at=job.resume_at, counts=counts,
                recipients=[dict(user_id=r.user_id, email=r.email, status=r.status) for r in rows])


def account_records(db):
    """Admin-only account inventory; never return credential values from records."""
    import json
    allowed = ('email', 'gmail_status', 'resend_status', 'domain', 'domain_id',
               'domain_status', 'from_email', 'key_name', 'key_permission',
               'key_status', 'storage', 'campaign_use')
    records = {}
    for row in db.query(EmailCenterAudit).filter_by(action='account_record').order_by(EmailCenterAudit.id.desc()):
        try:
            value = json.loads(row.detail)
        except (ValueError, TypeError):
            continue
        if not isinstance(value, dict) or not isinstance(value.get('email'), str):
            continue
        if value['email'] in records:
            continue
        records[value['email']] = dict({k: value[k] for k in allowed if isinstance(value.get(k), str)}, recorded_at=row.created_at)
    return list(records.values())


def dashboard(db):
    account = active_sender()
    day = quota(db, account)
    counts = dict(db.query(PromotionEmail.status, func.count()).filter_by(campaign=offer.CAMPAIGN)
                  .group_by(PromotionEmail.status).all())
    return dict(campaign=offer.CAMPAIGN, active=offer.active(), ends_at=offer.END,
                campaign_counts=counts, active_sender=account.name,
                quota=dict(used=day.used, confirmed=day.confirmed, source=day.source, utc_day=day.day,
                           queue_cap=cap(account), allowance=max(0, cap(account)-day.used) if day.confirmed else 0,
                           reset_at=next_reset()),
                senders=[dict(name=a.name, email=a.from_email, selected=a.name == account.name,
                              daily_limit=a.daily_limit, reserve=a.daily_buffer) for a in _configured_resend_accounts()],
                jobs=[job_view(db, j) for j in db.query(EmailJob).order_by(EmailJob.created_at.desc()).limit(20)],
                audience=audience_view(db), account_records=account_records(db),
                audit=[dict(action=r.action, detail=r.detail, at=r.created_at) for r in
                       db.query(EmailCenterAudit).filter(EmailCenterAudit.action != 'account_record').order_by(EmailCenterAudit.id.desc()).limit(20)])


def audience_view(db):
    row=db.query(EmailCenterAudit).filter_by(action='audience_count').order_by(EmailCenterAudit.id.desc()).first()
    if not row:
        return None
    import json
    return dict(**json.loads(row.detail), checked_at=row.created_at)


def count_audience(audit_id):
    import json
    from concurrent.futures import ThreadPoolExecutor
    with SessionLocal() as db:
        recorded={r.email.strip().lower() for r in db.query(PromotionEmail).filter_by(campaign=offer.CAMPAIGN)}
        opted={r.email.strip().lower() for r in db.query(PromotionOptOut)}
        seen=set();ids=[]
        for user in db.query(User).filter(User.email_verified.is_(True),User.is_active.is_(True)).order_by(User.id):
            address=user.email.strip().lower()
            if address in seen:continue
            seen.add(address)
            if address not in recorded and address not in opted:ids.append(user.id)
    def check(uid):
        try:
            with SessionLocal() as db:
                return 1 if offer.eligible(db,db.get(User,uid),live=True) else 0
        except Exception:return -1
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(check,ids))
    with SessionLocal() as db:
        row=db.get(EmailCenterAudit,audit_id)
        row.detail=json.dumps(dict(status='complete',eligible=results.count(1),excluded=results.count(0),errors=results.count(-1)))
        row.created_at=now();db.commit()


def create_job(db, count, actor):
    if not offer.active():
        raise HTTPException(410, 'This November campaign has ended.')
    busy = db.query(EmailJob).filter(EmailJob.status.in_(['preparing','ready','approved','running','waiting_quota','needs_usage','needs_review','paused'])).first()
    if busy:
        raise HTTPException(409, 'Finish or cancel the existing batch before preparing another.')
    job = EmailJob(id=str(uuid.uuid4()), campaign=offer.CAMPAIGN, sender=active_sender().name,
                   requested=count, created_by=actor, status='preparing')
    db.add(job); audit(db, 'preview_requested', actor, job.id, str(count) + ' oldest eligible accounts')
    db.commit(); db.refresh(job)
    return job


def prepare_job(job_id):
    with SessionLocal() as db:
        job = db.get(EmailJob, job_id)
        if not job or job.status != 'preparing':
            return
        try:
            recorded = {r.email.strip().lower() for r in db.query(PromotionEmail).filter_by(campaign=job.campaign)}
            opted = {r.email.strip().lower() for r in db.query(PromotionOptOut)}
            seen = set(); selected = 0
            users = db.query(User).filter(User.email_verified.is_(True), User.is_active.is_(True)).order_by(User.id).all()
            for user in users:
                address = user.email.strip().lower()
                if address in seen:
                    continue
                seen.add(address)
                if address in recorded or address in opted or not offer.eligible(db, user, live=True):
                    continue
                db.add(EmailJobRecipient(job_id=job.id, user_id=user.id, email=address, status='queued'))
                selected += 1
                if selected >= job.requested:
                    break
            db.refresh(job)
            if job.status != 'preparing':
                db.rollback(); return
            job.status = 'ready' if selected else 'completed'
            job.note = str(selected) + ' eligible recipients selected. Nothing sent until approval.'
            job.updated_at = now(); audit(db, 'preview_ready', job=job.id, detail=str(selected))
            db.commit()
        except Exception:
            db.rollback(); job = db.get(EmailJob, job_id)
            job.status = 'needs_review'; job.note = 'Eligibility check failed. No emails were sent; check backend logs.'
            db.commit()


def approve_job(db, job_id, actor):
    job = db.get(EmailJob, job_id)
    if not job:
        raise HTTPException(404, 'Batch not found.')
    if job.status not in ('ready','paused','waiting_quota','needs_usage'):
        raise HTTPException(409, 'This batch cannot be approved in its current state.')
    if not offer.active():
        raise HTTPException(410, 'This November campaign has ended.')
    if job.sender != active_sender().name:
        raise HTTPException(409, 'The sender configuration changed. Prepare a fresh batch.')
    job.approved_at = job.approved_at or now(); job.status = 'approved'; job.resume_at = None
    audit(db, 'send_approved', actor, job.id); db.commit()


def stop_job(db, job_id, actor, cancel=False):
    job = db.get(EmailJob, job_id)
    if not job:
        raise HTTPException(404, 'Batch not found.')
    job.status = 'cancelled' if cancel else 'paused'
    job.note = 'Stopped by admin. An already in-flight request may finish.'
    audit(db, 'cancelled' if cancel else 'paused', actor, job.id); db.commit()


def dispatch(account, address, delivery_id, unsubscribe_url):
    subject, html = render_november_offer_email(unsubscribe_url)
    try:
        response = httpx.post('https://api.resend.com/emails',
            headers={'Authorization': 'Bearer '+account.api_key, 'Idempotency-Key': offer.CAMPAIGN+'-'+str(delivery_id)},
            json={'from': account.from_email, 'to': [address], 'subject': subject, 'html': html}, timeout=20)
        if 200 <= response.status_code < 300:
            return 'sent', 'Accepted by Resend'
        if response.status_code == 429:
            return 'deferred', 'Resend limit reached; no sender switching. Review quota before resuming.'
        if 400 <= response.status_code < 500:
            return 'failed', 'Resend rejected this request (HTTP '+str(response.status_code)+'). Check Resend Logs.'
        return 'unknown', 'Provider result is uncertain. Review Resend Logs before any retry.'
    except Exception:
        return 'unknown', 'Provider result is uncertain. Review Resend Logs before any retry.'


def run_job(job_id):
    with SessionLocal() as db:
        job = db.get(EmailJob, job_id)
        if not job or job.status not in ('approved','waiting_quota') or not job.approved_at:
            return
        if job.resume_at and aware(job.resume_at) > now():
            return
        if not offer.active():
            job.status='expired'; job.note='Campaign ended. No further mail will be sent.'; db.commit(); return
        account = active_sender()
        if account.name != job.sender:
            job.status='needs_review';job.note='Sender changed. No automatic account switching.';db.commit();return
        claimed=db.execute(update(EmailJob).where(EmailJob.id==job.id, EmailJob.status.in_(['approved','waiting_quota']))
            .values(status='running', lease_until=now()+timedelta(minutes=3)))
        db.commit()
        if claimed.rowcount != 1:
            return
        try:
            rows=db.query(EmailJobRecipient).filter_by(job_id=job.id).order_by(EmailJobRecipient.user_id).all()
            for row in rows:
                db.refresh(job)
                if job.status != 'running':
                    return
                if row.status not in ('queued','deferred'):
                    continue
                if not offer.active():
                    job.status='expired';db.commit();return
                user=db.get(User,row.user_id)
                address=row.email
                if not user or not user.email_verified or user.email.strip().lower()!=address or db.get(PromotionOptOut,address) or not offer.eligible(db,user,live=True):
                    row.status='excluded';db.commit();continue
                delivery=db.query(PromotionEmail).filter_by(campaign=job.campaign,email=address).first()
                if delivery and not (row.status=='deferred' and row.delivery_id==delivery.id and delivery.status=='deferred'):
                    row.status='already_recorded' if delivery.status=='sent' else 'needs_review'
                    db.commit()
                    if row.status=='needs_review':
                        job.status='needs_review';job.note='Existing uncertain or failed delivery requires review; not retried.';db.commit();return
                    continue
                offer.checkout_discount(db,user)
                quota_id=reserve(db,account)
                if not isinstance(quota_id,int):
                    job.status=quota_id;job.resume_at=next_reset() if quota_id=='waiting_quota' else None
                    job.note='Daily queue allowance reached; resumes after reset.' if quota_id=='waiting_quota' else 'Confirm today’s total usage from Resend before sending.'
                    db.commit();return
                if not delivery:
                    delivery=PromotionEmail(campaign=job.campaign,email=address,status='pending')
                    db.add(delivery)
                else:
                    delivery.status='pending'
                row.status='in_flight';job.lease_until=now()+timedelta(minutes=3)
                try:
                    db.flush();row.delivery_id=delivery.id;db.commit()
                except IntegrityError:
                    db.rollback();release(db,quota_id);db.commit();continue
                url=settings.BACKEND_BASE_URL.rstrip('/')+'/promotions/unsubscribe?'+urlencode({'token':offer.unsubscribe_token(address)})
                status,note=dispatch(account,address,delivery.id,url)
                delivery.status=status;delivery.updated_at=now();delivery.sent_at=now() if status=='sent' else None
                row.status='accepted' if status=='sent' else status
                if status in ('failed','deferred'):
                    release(db,quota_id)
                job.updated_at=now();job.note=note
                if status!='sent':
                    job.status='waiting_quota' if status=='deferred' else 'needs_review'
                    job.resume_at=next_reset() if status=='deferred' else None
                db.commit()
                if status!='sent':
                    return
                time.sleep(0.7)
            db.refresh(job)
            if job.status=='running':
                job.status='completed';job.note='Batch finished. Accepted means accepted by Resend, not confirmed inbox delivery.'
                job.lease_until=None;audit(db,'batch_completed',job=job.id);db.commit()
        except Exception:
            db.rollback();job=db.get(EmailJob,job_id)
            job.status='needs_review';job.note='Processing stopped. Pending/uncertain deliveries are never automatically retried.'
            db.commit()


def tick():
    """Called by the existing minute scheduler; only explicitly approved batches run."""
    with SessionLocal() as db:
        stale=db.query(EmailJob).filter(EmailJob.status=='running', EmailJob.lease_until < now()).all()
        for job in stale:
            job.status='needs_review';job.note='Worker interrupted. Review pending delivery records before resuming.'
        db.commit()
        ids=[j.id for j in db.query(EmailJob).filter(EmailJob.status.in_(['approved','waiting_quota'])).all()]
    for job_id in ids:
        run_job(job_id)
