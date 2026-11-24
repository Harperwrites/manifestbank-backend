from datetime import datetime, UTC, timedelta
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.session import Base, get_db
import app.db.base
from app.models.user import User
from app.models.promotion import PromotionEmail, PromotionOptOut
from app.models.email_center import EmailJob, EmailJobRecipient, EmailSenderDay
from app.services import email_center as ec
from app.routes.email_center import router
from app.core.security import get_current_user

@pytest.fixture
def center(tmp_path, monkeypatch):
    engine=create_engine('sqlite:///'+str(tmp_path/'email-center.db'),connect_args={'check_same_thread':False,'timeout':30})
    Base.metadata.create_all(engine)
    sessions=sessionmaker(bind=engine,expire_on_commit=False)
    monkeypatch.setattr(ec,'SessionLocal',sessions)
    account=SimpleNamespace(name='account_6',api_key='SECRET_NEVER_EXPOSE',from_email='ManifestBank <hello@dispatch.manifestbank.app>',daily_limit=3,daily_buffer=1)
    monkeypatch.setattr(ec,'active_sender',lambda:account)
    monkeypatch.setattr(ec,'_configured_resend_accounts',lambda:[account])
    monkeypatch.setattr(ec.offer,'active',lambda:True)
    monkeypatch.setattr(ec.offer,'eligible',lambda db,u,live=False:bool(u and u.is_active and not u.is_premium))
    monkeypatch.setattr(ec.offer,'checkout_discount',lambda *args:None)
    monkeypatch.setattr(ec.time,'sleep',lambda _:None)
    clock=[datetime(2026,11,24,20,tzinfo=UTC)]
    monkeypatch.setattr(ec,'now',lambda:clock[0])
    with sessions() as db:
        admin=User(email='admin@example.com',username='admin',hashed_password='unused',is_active=True,email_verified=True,is_premium=False,role='admin')
        db.add(admin);db.commit();admin_id=admin.id
    yield SimpleNamespace(sessions=sessions,account=account,admin=admin_id,clock=clock)
    engine.dispose()

def add(center,name,premium=False):
    with center.sessions() as db:
        u=User(email=name+'@example.com',username=name,hashed_password='unused',email_verified=True,is_active=True,is_premium=premium,role='user')
        db.add(u);db.commit();return u.id

def prepare(center,count=3,usage=0):
    with center.sessions() as db:
        if usage is not None:ec.confirm_usage(db,usage,center.admin)
        job=ec.create_job(db,count,center.admin);jid=job.id
    ec.prepare_job(jid)
    return jid

def test_admin_only_and_no_secrets_in_response(center):
    app=FastAPI();app.include_router(router)
    def database():
        with center.sessions() as db:yield db
    app.dependency_overrides[get_db]=database
    app.dependency_overrides[get_current_user]=lambda:SimpleNamespace(id=center.admin,role='user')
    client=TestClient(app)
    assert client.get('/admin/email-center').status_code==403
    assert client.get('/admin/email-center/guide').status_code==403
    app.dependency_overrides[get_current_user]=lambda:SimpleNamespace(id=center.admin,role='admin')
    response=client.get('/admin/email-center')
    assert response.status_code==200
    assert center.account.api_key not in response.text
    guide=client.get('/admin/email-center/guide')
    assert guide.status_code==200 and guide.content.startswith(b'%PDF')
    assert response.json()['quota']['confirmed'] is False
    assert client.post('/admin/email-center/batches',json={'count':76}).status_code==422
    assert client.post('/admin/email-center/usage',json={'used':0,'utc_day':'2000-01-01'}).status_code==409

def test_preview_is_dry_oldest_deduplicated_and_excludes_members_history_optouts(center,monkeypatch):
    first=add(center,'first');add(center,'signature',True);opted=add(center,'opted');old=add(center,'old');second=add(center,'second')
    with center.sessions() as db:
        db.add(PromotionOptOut(email='opted@example.com'))
        db.add(PromotionEmail(campaign=ec.offer.CAMPAIGN,email='old@example.com',status='failed'))
        db.commit()
    monkeypatch.setattr(ec,'dispatch',lambda *args:pytest.fail('Preview must never send'))
    jid=prepare(center)
    with center.sessions() as db:
        assert [r.user_id for r in db.query(EmailJobRecipient).filter_by(job_id=jid).order_by(EmailJobRecipient.user_id)]==[center.admin,first,second]
        assert db.get(EmailJob,jid).status=='ready'
        assert db.query(PromotionEmail).count()==1
    ec.tick()
    with center.sessions() as db:assert db.query(PromotionEmail).count()==1

def test_allowance_waits_then_resumes_and_rechecks_membership(center,monkeypatch):
    first=add(center,'first');last=add(center,'last')
    calls=[];monkeypatch.setattr(ec,'dispatch',lambda a,e,i,u:(calls.append(e) or ('sent','accepted')))
    jid=prepare(center)
    with center.sessions() as db:ec.approve_job(db,jid,center.admin)
    ec.run_job(jid)
    with center.sessions() as db:
        assert len(calls)==2
        assert db.get(EmailJob,jid).status=='waiting_quota'
        db.get(User,last).is_premium=True;db.commit()
    ec.tick();assert len(calls)==2
    center.clock[0]+=timedelta(days=1)
    ec.tick()
    with center.sessions() as db:
        assert db.get(EmailJob,jid).status=='completed'
        assert db.query(EmailJobRecipient).filter_by(job_id=jid,status='excluded').count()==1
        assert db.query(PromotionEmail).count()==2
    assert len(calls)==2

def test_unknown_result_retains_claim_stops_and_never_automatically_retries(center,monkeypatch):
    add(center,'next')
    calls=[];monkeypatch.setattr(ec,'dispatch',lambda a,e,i,u:(calls.append(e) or ('unknown','uncertain')))
    jid=prepare(center,2)
    with center.sessions() as db:ec.approve_job(db,jid,center.admin)
    ec.run_job(jid);ec.tick();ec.run_job(jid)
    with center.sessions() as db:
        assert db.get(EmailJob,jid).status=='needs_review'
        assert db.query(PromotionEmail).one().status=='unknown'
        assert db.query(EmailSenderDay).one().used==1
    assert len(calls)==1

def test_quota_reservations_atomic_and_usage_monotonic(center):
    with center.sessions() as db:ec.confirm_usage(db,0,center.admin)
    def claim(_):
        with center.sessions() as db:return ec.reserve(db,center.account)
    with ThreadPoolExecutor(max_workers=6) as pool:out=list(pool.map(claim,range(8)))
    assert sum(isinstance(x,int) for x in out)==2
    with center.sessions() as db:
        assert db.query(EmailSenderDay).one().used==2
        with pytest.raises(HTTPException):ec.confirm_usage(db,1,center.admin)

def test_first_send_requires_usage_and_429_defers_without_fallback(center,monkeypatch):
    calls=[];monkeypatch.setattr(ec,'dispatch',lambda a,e,i,u:(calls.append((a.name,i)) or ('deferred','limit')))
    jid=prepare(center,1,usage=None)
    with center.sessions() as db:ec.approve_job(db,jid,center.admin)
    ec.run_job(jid)
    with center.sessions() as db:
        assert db.get(EmailJob,jid).status=='needs_usage';assert not calls
        ec.confirm_usage(db,0,center.admin)
    ec.tick()
    with center.sessions() as db:
        assert db.get(EmailJob,jid).status=='waiting_quota'
        assert db.query(EmailSenderDay).one().used==0
        delivery_id=db.query(PromotionEmail).one().id
    monkeypatch.setattr(ec,'dispatch',lambda a,e,i,u:(calls.append((a.name,i)) or ('sent','accepted')))
    center.clock[0]+=timedelta(days=1);ec.tick()
    with center.sessions() as db:assert db.get(EmailJob,jid).status=='completed'
    assert calls==[('account_6',delivery_id),('account_6',delivery_id)]

def test_optout_after_preview_is_honored_and_cancel_preserves_rows(center,monkeypatch):
    uid=add(center,'last')
    jid=prepare(center,2)
    with center.sessions() as db:
        db.add(PromotionOptOut(email='last@example.com'));db.commit();ec.stop_job(db,jid,center.admin,cancel=True)
    monkeypatch.setattr(ec,'dispatch',lambda *args:pytest.fail('Cancelled jobs never send'))
    ec.tick()
    with center.sessions() as db:
        assert db.query(EmailJobRecipient).filter_by(job_id=jid).count()==2
        assert db.get(EmailJob,jid).status=='cancelled'

def test_membership_and_optout_rechecked_after_approval(center,monkeypatch):
    member_id=add(center,'new-signature');add(center,'new-optout')
    jid=prepare(center,3)
    with center.sessions() as db:
        db.get(User,member_id).is_premium=True
        db.add(PromotionOptOut(email='new-optout@example.com'));db.commit()
        ec.approve_job(db,jid,center.admin)
    calls=[]
    monkeypatch.setattr(ec,'dispatch',lambda a,address,*args:(calls.append(address) or ('sent','accepted')))
    ec.run_job(jid)
    with center.sessions() as db:
        counts=ec.job_view(db,db.get(EmailJob,jid))['counts']
        assert counts=={'accepted':1,'excluded':2}
    assert calls==['admin@example.com']
