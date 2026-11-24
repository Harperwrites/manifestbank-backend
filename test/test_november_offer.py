from datetime import datetime, UTC
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi import HTTPException
from app.db.session import Base
import app.db.base
from app.models.user import User
from app.models.promotion import PromotionLogin, PromotionOptOut
from app.services import november_offer as offer
from app.services.email import render_november_offer_email

@pytest.fixture
def campaign_db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def member(db, name='free', **values):
    user = User(email=name+'@example.com', username=name, hashed_password='unused', email_verified=True, is_active=True, role='user', is_premium=False, **values)
    db.add(user); db.commit(); db.refresh(user)
    return user


def test_campaign_chicago_end_boundary():
    assert not offer.active(datetime(2026,11,23,5,59,59,tzinfo=UTC))
    assert offer.active(datetime(2026,11,23,6,0,tzinfo=UTC))
    assert offer.active(datetime(2026,12,1,5,59,59,tzinfo=UTC))
    assert not offer.active(datetime(2026,12,1,6,0,tzinfo=UTC))


def test_new_signups_wait_for_second_real_login(campaign_db, monkeypatch):
    monkeypatch.setattr(offer, 'active', lambda: True)
    monkeypatch.setattr(offer.settings, 'STRIPE_SECRET_KEY', None)
    db = campaign_db
    new = member(db)
    offer.record_signup(db,new.id); db.commit()
    offer.record_login(db,new.id)
    assert offer.offer_status(db,new)['show_alert'] is False
    # Status refresh never increments login counter.
    offer.offer_status(db,new); offer.offer_status(db,new)
    assert db.get(PromotionLogin,new.id).login_count == 1
    offer.record_login(db,new.id)
    result = offer.offer_status(db,new)
    assert result['show_alert'] is True
    assert result['delay_ms'] == 0
    assert result['first_year_cents'] == 2222
    old = member(db, 'existing')
    offer.record_login(db, old.id)
    assert offer.offer_status(db,old)['show_alert'] is True


def test_monthly_annual_and_stale_subscribers_are_all_excluded(campaign_db):
    for i, flags in enumerate([{'stripe_subscription_id':'sub_monthly'}, {'stripe_price_id':'price_annual'}, {'stripe_status':'trialing'}, {'stripe_status':'past_due'}, {'stripe_status':'active'}]):
        user = member(campaign_db, str(i), **flags)
        assert not offer.eligible(campaign_db,user)
    free = member(campaign_db,'premium')
    free.is_premium = True
    assert not offer.local_nonmember(free)
    free.is_premium=False; free.role='admin'
    assert offer.local_nonmember(free)


def test_duplicate_email_and_live_stripe_membership_fail_closed(campaign_db,monkeypatch):
    user = member(campaign_db, 'same')
    other = member(campaign_db, 'SAME', stripe_subscription_id='sub_monthly')
    assert not offer.eligible(campaign_db,user)
    other.stripe_subscription_id = None; campaign_db.commit()
    monkeypatch.setattr(offer.settings,'STRIPE_SECRET_KEY','test-key')
    monkeypatch.setattr(offer.stripe.Customer,'list',lambda **kw: SimpleNamespace(auto_paging_iter=lambda:iter([SimpleNamespace(id='cus_missing_locally')])))
    monkeypatch.setattr(offer.stripe.Subscription,'list',lambda **kw: SimpleNamespace(auto_paging_iter=lambda:iter([{'status':'active'}])))
    assert not offer.eligible(campaign_db,user,live=True)


def test_checkout_coupon_once_and_annual_72_verified(campaign_db,monkeypatch):
    user = member(campaign_db)
    monkeypatch.setattr(offer,'active',lambda:True)
    monkeypatch.setattr(offer,'eligible',lambda *args,**kwargs:True)
    monkeypatch.setattr(offer.settings,'STRIPE_PRICE_ANNUAL','annual72')
    monkeypatch.setattr(offer.settings,'STRIPE_NOVEMBER_COUPON_ID','first2222')
    price={'active':True,'currency':'usd','unit_amount':7200,'recurring':{'interval':'year','interval_count':1},'product':'signature'}
    coupon={'valid':True,'duration':'once','amount_off':4978,'currency':'usd','percent_off':None}
    monkeypatch.setattr(offer.stripe.Price,'retrieve',lambda _:price)
    monkeypatch.setattr(offer.stripe.Coupon,'retrieve',lambda _:coupon)
    code={'id':'promo_1111','code':'1111','active':True,'coupon':{'id':'first2222'},'expires_at':int(offer.END.timestamp())-60,'restrictions':{'minimum_amount':7200,'minimum_amount_currency':'usd'}}
    monkeypatch.setattr(offer.stripe.PromotionCode,'list',lambda **kw:SimpleNamespace(auto_paging_iter=lambda:iter([code])))
    class CampaignClock(datetime):
        @classmethod
        def now(cls, tz=None): return datetime(2026,11,24,2,0,tzinfo=UTC)
    monkeypatch.setattr(offer,'datetime',CampaignClock)
    assert offer.checkout_discount(campaign_db,user) == {'promotion_code':'promo_1111'}
    code['coupon']={'id':'wrong_coupon'}
    with pytest.raises(HTTPException): offer.checkout_discount(campaign_db,user)
    code['coupon']={'id':'first2222'}
    code['restrictions']['minimum_amount']=888
    with pytest.raises(HTTPException): offer.checkout_discount(campaign_db,user)
    code['restrictions']['minimum_amount']=7200
    code['expires_at']=0
    with pytest.raises(HTTPException): offer.checkout_discount(campaign_db,user)
    code['expires_at']=int(offer.END.timestamp())-60
    assert price['unit_amount'] - coupon['amount_off'] == 2222
    # A stale coupon for the superseded price must never be charged.
    coupon['amount_off']=6089
    with pytest.raises(HTTPException) as stale: offer.checkout_discount(campaign_db,user)
    assert stale.value.status_code == 503
    coupon['amount_off']=4978
    coupon['duration']='forever'
    with pytest.raises(HTTPException) as exc: offer.checkout_discount(campaign_db,user)
    assert exc.value.status_code == 503
    coupon['duration']='once'; price['unit_amount']=3600
    with pytest.raises(HTTPException): offer.checkout_discount(campaign_db,user)
    monkeypatch.setattr(offer,'active',lambda:False)
    with pytest.raises(HTTPException) as exc: offer.checkout_discount(campaign_db,user)
    assert exc.value.status_code == 410


def test_email_has_prices_renewal_deadline_unsubscribe_and_existing_brand():
    subject,html=render_november_offer_email('https://example.com/unsubscribe?token=demo')
    assert '$22.22' in subject
    assert '$11.11' not in subject + html
    for phrase in ['$22.22','$72/year','first year','renewing automatically','November 30, 2026','Central Time','monthly and annual subscribers','Unsubscribe','marble-veins.png','manifestbank-glow-edge-logo.png']:
        assert phrase in html
    assert 'SIGNATURE50' not in html
    assert '/november-offer/video' in html
    assert '/promos/november-2026/november-video-poster.jpg' in html
    assert 'Watch the November promo' in html
    assert '<video' not in html


def test_signed_unsubscribe_persists_and_does_not_accept_login_tokens(campaign_db):
    token=offer.unsubscribe_token('FREE@EXAMPLE.COM')
    offer.opt_out(campaign_db,token); offer.opt_out(campaign_db,token)
    assert campaign_db.query(PromotionOptOut).count()==1
    assert campaign_db.get(PromotionOptOut,'free@example.com')
    from app.core.security import create_access_token
    with pytest.raises(HTTPException):offer.opt_out(campaign_db,create_access_token({'sub':'1'}))


def test_campaign_checkout_excludes_members_and_arbitrary_price(campaign_db,monkeypatch):
    from app.routes import billing
    monkeypatch.setattr(billing,'_require_stripe_key',lambda:None)
    user=member(campaign_db,stripe_subscription_id='sub_monthly')
    monkeypatch.setattr(offer,'active',lambda:True)
    with pytest.raises(HTTPException) as exc:
        billing.create_checkout_session({'plan':'annual','campaign':offer.CAMPAIGN},campaign_db,user)
    assert exc.value.status_code==403
    for payload in [{'plan':'monthly','campaign':offer.CAMPAIGN},{'plan':'annual','campaign':offer.CAMPAIGN,'price_id':'other'}]:
        with pytest.raises(HTTPException) as exc:billing.create_checkout_session(payload,campaign_db,user)
        assert exc.value.status_code==400


def test_email_dispatch_excludes_subscribers_optouts_and_duplicates(campaign_db,monkeypatch):
    from app.scripts import send_november_offer as sender
    db=campaign_db
    member(db,'invited')
    member(db,'monthly',stripe_subscription_id='sub_monthly')
    premium=member(db,'annual'); premium.is_premium=True
    opted=member(db,'opted'); db.add(PromotionOptOut(email=opted.email)); db.commit()
    monkeypatch.setattr(sender,'SessionLocal',lambda:db)
    monkeypatch.setattr(sender,'active',lambda:True)
    monkeypatch.setattr(sender.settings,'STRIPE_SECRET_KEY','test-key')
    monkeypatch.setattr(sender.settings,'STRIPE_PRICE_ANNUAL','annual72')
    monkeypatch.setattr(sender.settings,'STRIPE_NOVEMBER_COUPON_ID','first2222')
    monkeypatch.setattr(sender.settings,'FRONTEND_BASE_URL','https://manifestbank.app')
    monkeypatch.setattr(sender.settings,'BACKEND_BASE_URL','https://api.example.com')
    monkeypatch.setattr(sender,'_configured_resend_accounts',lambda:[object()])
    monkeypatch.setattr(offer.stripe.Customer,'list',lambda **kw: SimpleNamespace(auto_paging_iter=lambda:iter([])))
    monkeypatch.setattr(offer.stripe.Subscription,'retrieve',lambda sid:{'id':sid,'status':'active','metadata':{'tier_name':'signature'}})
    monkeypatch.setattr(sender,'checkout_discount',lambda *args:None)
    sent=[]
    monkeypatch.setattr(sender,'send_november_offer_email',lambda email,url,id: sent.append(email) or 'sent')
    dry=sender.run()
    assert dry['eligible']==1 and sent==[]
    sender.run(send=True); sender.run(send=True)
    assert sent==['invited@example.com']


def test_authenticated_alert_and_second_login_http(campaign_db,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routes.auth import router as auth_router
    from app.routes.promotions import router as promo_router
    from app.core.security import get_password_hash
    from app.db.session import get_db
    db=campaign_db
    user=member(db,'newsignup')
    user.hashed_password=get_password_hash('Local-test-password-1111')
    offer.record_signup(db,user.id); db.commit()
    monkeypatch.setattr(offer,'active',lambda:True)
    monkeypatch.setattr(offer.settings,'STRIPE_SECRET_KEY',None)
    app=FastAPI(); app.include_router(auth_router,prefix='/auth'); app.include_router(promo_router)
    def database():yield db
    app.dependency_overrides[get_db]=database
    with TestClient(app) as client:
        assert client.get('/promotions/november').status_code==401
        first=client.post('/auth/login',json={'identifier':user.email,'password':'Local-test-password-1111'})
        assert first.status_code==200
        headers={'Authorization':'Bearer '+first.json()['access_token']}
        assert client.get('/promotions/november',headers=headers).json()['show_alert'] is False
        client.post('/auth/refresh',json={'refresh_token':first.json()['refresh_token']})
        assert client.get('/promotions/november',headers=headers).json()['show_alert'] is False
        second=client.post('/auth/login',json={'identifier':user.email,'password':'Local-test-password-1111'})
        assert second.status_code==200
        assert client.get('/promotions/november',headers=headers).json()['show_alert'] is True
        user.stripe_subscription_id='sub_monthly'; db.commit()
        assert client.get('/promotions/november',headers=headers).json()['show_alert'] is False


def test_code_1111_links_existing_annual_checkout_to_stripe_promotion(campaign_db, monkeypatch):
    from app.routes import billing
    user = member(campaign_db, stripe_customer_id='cus_free')
    monkeypatch.setattr(billing, '_require_stripe_key', lambda: None)
    monkeypatch.setattr(billing.settings, 'STRIPE_PRICE_ANNUAL', 'price_annual72')
    monkeypatch.setattr(billing, 'checkout_discount', lambda db, user: {'promotion_code': 'promo_1111'})
    captured = {}
    def create_session(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(url='https://checkout.stripe.com/test-only')
    monkeypatch.setattr(billing.stripe.checkout.Session, 'create', create_session)
    response = billing.create_checkout_session({'plan':'annual','promo_code':'1111'},campaign_db,user)
    assert response['url'] == 'https://checkout.stripe.com/test-only'
    assert captured['line_items'] == [{'price':'price_annual72','quantity':1}]
    assert captured['discounts'] == [{'promotion_code':'promo_1111'}]
    assert 'allow_promotion_codes' not in captured
    assert captured['metadata']['campaign'] == offer.CAMPAIGN
    for payload in [{'plan':'monthly','promo_code':'1111'}, {'plan':'annual','promo_code':'invalid'}, {'plan':'annual','promo_code':'1111','price_id':'other'}]:
        with pytest.raises(HTTPException):billing.create_checkout_session(payload,campaign_db,user)


def test_existing_members_cannot_open_generic_code_enabled_annual_checkout(campaign_db, monkeypatch):
    from app.routes import billing
    user = member(campaign_db, stripe_subscription_id='sub_monthly')
    monkeypatch.setattr(billing, '_require_stripe_key', lambda: None)
    monkeypatch.setattr(billing, 'november_active', lambda: True)
    for payload in [{'plan':'annual'}, {'plan':'annual','campaign':'arbitrary'}]:
        with pytest.raises(HTTPException) as exc:billing.create_checkout_session(payload,campaign_db,user)
        assert exc.value.status_code == 403


def test_canceled_signature_account_with_old_ids_can_buy_again(campaign_db,monkeypatch):
    user=member(campaign_db,'returning',stripe_customer_id='cus_old',stripe_subscription_id='sub_old',stripe_price_id='price_annual',stripe_status='canceled')
    assert offer.local_nonmember(user)
    monkeypatch.setattr(offer.settings,'STRIPE_SECRET_KEY','test-key')
    monkeypatch.setattr(offer.stripe.Customer,'list',lambda **kw:SimpleNamespace(auto_paging_iter=lambda:iter([])))
    subs=[{'id':'sub_old','status':'canceled','items':{'data':[{'price':{'id':'price_annual','product':offer.SIGNATURE_PRODUCT_ID}}]}}]
    monkeypatch.setattr(offer.stripe.Subscription,'list',lambda **kw:SimpleNamespace(auto_paging_iter=lambda:iter(subs)))
    assert offer.eligible(campaign_db,user,live=True)
    # Stale local current status is reconciled against live Stripe, without editing records.
    user.stripe_status='active';campaign_db.commit()
    assert offer.eligible(campaign_db,user,live=True)
    assert user.stripe_subscription_id=='sub_old'
    subs[0]['status']='active'
    assert not offer.eligible(campaign_db,user,live=True)


def test_incomplete_first_checkout_and_unrelated_subscription_are_not_signature(campaign_db,monkeypatch):
    user=member(campaign_db,'firstpurchase',stripe_customer_id='cus_new',stripe_subscription_id='sub_incomplete',stripe_status='incomplete')
    monkeypatch.setattr(offer.settings,'STRIPE_SECRET_KEY','test-key')
    monkeypatch.setattr(offer.stripe.Customer,'list',lambda **kw:SimpleNamespace(auto_paging_iter=lambda:iter([])))
    subs=[{'id':'sub_incomplete','status':'incomplete'}, {'status':'active','items':{'data':[{'price':{'id':'unrelated','product':'other_product'}}]}}]
    monkeypatch.setattr(offer.stripe.Subscription,'list',lambda **kw:SimpleNamespace(auto_paging_iter=lambda:iter(subs)))
    assert offer.eligible(campaign_db,user,live=True)
    user.role='admin';campaign_db.commit()
    assert offer.eligible(campaign_db,user,live=True)
    user.is_premium=True;campaign_db.commit()
    assert not offer.eligible(campaign_db,user,live=True)


def test_canceled_accounts_are_in_email_audience_but_current_subscribers_are_not(campaign_db,monkeypatch):
    from app.scripts import send_november_offer as sender
    db=campaign_db
    returning=member(db,'returning-email',stripe_customer_id='cus_returning',stripe_subscription_id='sub_ended',stripe_status='canceled')
    member(db,'current-email',stripe_customer_id='cus_current',stripe_subscription_id='sub_current',stripe_status='active')
    monkeypatch.setattr(sender,'SessionLocal',lambda:db)
    monkeypatch.setattr(sender,'active',lambda:True)
    monkeypatch.setattr(offer.settings,'STRIPE_SECRET_KEY','test-key')
    monkeypatch.setattr(offer.stripe.Customer,'list',lambda **kw:SimpleNamespace(auto_paging_iter=lambda:iter([])))
    def subscriptions(**kw):
        status='canceled' if kw['customer']=='cus_returning' else 'active'
        return SimpleNamespace(auto_paging_iter=lambda:iter([{'id':'sub_ended' if status=='canceled' else 'sub_current','status':status,'metadata':{'tier_name':'signature'}}]))
    monkeypatch.setattr(offer.stripe.Subscription,'list',subscriptions)
    monkeypatch.setattr(sender,'send_november_offer_email',lambda *args:pytest.fail('Dry run must never send'))
    result=sender.run()
    assert result['eligible']==1 and result['excluded']==1 and result['sent']==0


def test_deleted_stripe_reference_does_not_block_free_account(campaign_db,monkeypatch):
    user=member(campaign_db,'deleted-reference',stripe_customer_id='cus_deleted',stripe_subscription_id='sub_deleted',stripe_status='canceled')
    monkeypatch.setattr(offer.settings,'STRIPE_SECRET_KEY','test-key')
    monkeypatch.setattr(offer.stripe.Customer,'list',lambda **kw:SimpleNamespace(auto_paging_iter=lambda:iter([])))
    def missing(*args,**kwargs):raise offer.stripe.InvalidRequestError('No such resource','id',code='resource_missing')
    monkeypatch.setattr(offer.stripe.Subscription,'list',missing)
    monkeypatch.setattr(offer.stripe.Subscription,'retrieve',missing)
    assert offer.eligible(campaign_db,user,live=True)


def test_blast_limit_selects_oldest_eligible_accounts_and_never_backfills(campaign_db,monkeypatch):
    from app.scripts import send_november_offer as sender
    db=campaign_db
    oldest=member(db,'oldest')
    current=member(db,'already-signature');current.is_premium=True;db.commit()
    second=member(db,'second-oldest')
    later=member(db,'later')
    monkeypatch.setattr(sender,'SessionLocal',lambda:db)
    monkeypatch.setattr(sender,'active',lambda:True)
    monkeypatch.setattr(sender,'eligible',lambda db,u,live=False:not u.is_premium)
    monkeypatch.setattr(sender.settings,'STRIPE_SECRET_KEY','test')
    monkeypatch.setattr(sender.settings,'STRIPE_PRICE_ANNUAL','annual')
    monkeypatch.setattr(sender.settings,'STRIPE_NOVEMBER_COUPON_ID','coupon')
    monkeypatch.setattr(sender.settings,'FRONTEND_BASE_URL','https://manifestbank.app')
    monkeypatch.setattr(sender.settings,'BACKEND_BASE_URL','https://api.manifestbank.app')
    monkeypatch.setattr(sender,'_configured_resend_accounts',lambda:[object()])
    monkeypatch.setattr(sender,'checkout_discount',lambda *args:None)
    monkeypatch.setattr(sender.time,'sleep',lambda *args:None)
    plan=sender.run(limit=2)
    assert plan['selected_user_ids']==[oldest.id,second.id]
    calls=[]
    def deliver(email,*args):
        calls.append(email)
        return 'failed' if email==oldest.email else 'sent'
    monkeypatch.setattr(sender,'send_november_offer_email',deliver)
    result=sender.run(send=True,limit=2,user_ids=plan['selected_user_ids'])
    assert calls==[oldest.email,second.email]
    assert result['attempted']==2 and result['sent']==1 and result['failed']==1
    assert later.email not in calls
    sender.run(send=True,limit=2,user_ids=plan['selected_user_ids'])
    assert calls==[oldest.email,second.email]

def test_current_signature_members_never_receive_popup(campaign_db,monkeypatch):
    monkeypatch.setattr(offer,'active',lambda:True)
    monkeypatch.setattr(offer.settings,'STRIPE_SECRET_KEY',None)
    monthly=member(campaign_db,'popup-monthly',stripe_status='active',stripe_subscription_id='sub_monthly_current')
    annual=member(campaign_db,'popup-annual',stripe_status='trialing',stripe_price_id='price_annual_current')
    for user in (monthly,annual):
        state=offer.offer_status(campaign_db,user)
        assert state['eligible'] is False
        assert state['show_alert'] is False
