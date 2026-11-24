from datetime import datetime, UTC
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from pathlib import Path
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.core.security import require_role
from app.db.session import get_db
from app.services import email_center as center
from app.services.email import render_november_offer_email
from app.models.email_center import EmailCenterAudit

router = APIRouter(prefix='/admin/email-center', tags=['admin email center'])
admin_only = require_role('admin')

@router.get('/guide')
def guide(admin=Depends(admin_only)):
    path=Path(__file__).resolve().parents[1]/'assets'/'manifestbank-email-center-guide.pdf'
    if not path.exists():
        raise HTTPException(503,'The PDF guide is not available on this deployment.')
    return FileResponse(path,media_type='application/pdf',filename='ManifestBank-Email-Center-Guide.pdf')

class BatchRequest(BaseModel):
    count: int = Field(default=75, ge=1, le=75)

class UsageRequest(BaseModel):
    used: int = Field(ge=0, le=1000000)
    utc_day: str

@router.get('')
def overview(db: Session = Depends(get_db), admin=Depends(admin_only)):
    return center.dashboard(db)

@router.get('/template')
def template(admin=Depends(admin_only)):
    subject, html = render_november_offer_email('https://api.manifestbank.app/promotions/unsubscribe?preview=1')
    return {'subject': subject, 'html': html}

@router.post('/usage')
def usage(body: UsageRequest, db: Session = Depends(get_db), admin=Depends(admin_only)):
    if body.utc_day != datetime.now(UTC).date().isoformat():
        raise HTTPException(409, 'The UTC day changed. Refresh before confirming usage.')
    center.confirm_usage(db, body.used, admin.id)
    return center.dashboard(db)

@router.post('/audience/check', status_code=202)
def audience(tasks: BackgroundTasks, db: Session = Depends(get_db), admin=Depends(admin_only)):
    prior=center.audience_view(db)
    if prior and prior.get('status')=='checking' and (datetime.now(UTC)-center.aware(prior['checked_at'])).total_seconds()<600:
        raise HTTPException(409,'Audience check is already running.')
    row=EmailCenterAudit(actor_id=admin.id,action='audience_count',detail='{"status":"checking"}')
    db.add(row);db.commit();db.refresh(row)
    tasks.add_task(center.count_audience,row.id)
    return {'status':'checking'}

@router.post('/batches', status_code=202)
def preview(body: BatchRequest, tasks: BackgroundTasks, db: Session = Depends(get_db), admin=Depends(admin_only)):
    job = center.create_job(db, body.count, admin.id)
    tasks.add_task(center.prepare_job, job.id)
    return {'id': job.id, 'status': job.status}

@router.post('/batches/{job_id}/send', status_code=202)
def send(job_id: str, tasks: BackgroundTasks, db: Session = Depends(get_db), admin=Depends(admin_only)):
    center.approve_job(db, job_id, admin.id)
    tasks.add_task(center.run_job, job_id)
    return {'status': 'approved'}

@router.post('/batches/{job_id}/pause')
def pause(job_id: str, db: Session = Depends(get_db), admin=Depends(admin_only)):
    center.stop_job(db, job_id, admin.id)
    return {'status': 'paused'}

@router.post('/batches/{job_id}/cancel')
def cancel(job_id: str, db: Session = Depends(get_db), admin=Depends(admin_only)):
    center.stop_job(db, job_id, admin.id, cancel=True)
    return {'status': 'cancelled'}
