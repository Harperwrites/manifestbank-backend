from datetime import datetime, UTC
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.user import User
from app.models.ether import Profile, EtherThread, EtherThreadMember, EtherMessage

ADMIN_EMAIL = "billionairebrea@wealth.com"

WELCOME_MESSAGE = (
    "Welcome to ManifestBank™ ✨\n"
    "You didn’t arrive here by accident.\n"
    "This space exists to help you slow down, clarify your intentions, and bring order to the energy behind your goals—before they ever touch the physical world.\n"
    "Inside ManifestBank™, you can:\n"
    "• Set intentions with purpose\n"
    "• Observe patterns without judgment\n"
    "• Track growth with clarity\n"
    "• Engage in The Ether™ as a space for reflection, not noise\n"
    "There’s no rush here. Start where you are. Explore at your own pace. Let consistency do the quiet work.\n"
    "When you’re ready, begin by creating your first intention—or simply sit with the space and feel into what you’re building.\n"
    "Welcome to the practice.\n"
    "Welcome to the process.\n"
    "Welcome to your becoming.\n"
    "— ManifestBank™"
)


def _get_or_create_admin_profile(db: Session) -> Profile | None:
    admin_user = db.query(User).filter(func.lower(User.email) == ADMIN_EMAIL.lower()).first()
    if not admin_user:
        return None
    profile = db.query(Profile).filter(Profile.user_id == admin_user.id).first()
    if profile:
        return profile
    profile = Profile(
        user_id=admin_user.id,
        display_name=admin_user.username or admin_user.email.split("@")[0],
        is_public=True,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def _find_direct_thread_id(db: Session, profile_a_id: int, profile_b_id: int) -> int | None:
    member_counts = (
        db.query(
            EtherThreadMember.thread_id.label("thread_id"),
            func.count(EtherThreadMember.profile_id).label("member_count"),
        )
        .group_by(EtherThreadMember.thread_id)
        .subquery()
    )
    thread = (
        db.query(EtherThreadMember.thread_id)
        .join(member_counts, member_counts.c.thread_id == EtherThreadMember.thread_id)
        .filter(
            EtherThreadMember.profile_id.in_([profile_a_id, profile_b_id]),
            member_counts.c.member_count == 2,
        )
        .group_by(EtherThreadMember.thread_id)
        .having(func.count(EtherThreadMember.profile_id) == 2)
        .first()
    )
    return thread.thread_id if thread else None


def _get_or_create_direct_thread(db: Session, profile_a_id: int, profile_b_id: int) -> EtherThread:
    existing_id = _find_direct_thread_id(db, profile_a_id, profile_b_id)
    if existing_id:
        return db.query(EtherThread).filter(EtherThread.id == existing_id).first()
    thread = EtherThread()
    db.add(thread)
    db.commit()
    db.refresh(thread)
    for pid in {profile_a_id, profile_b_id}:
        db.add(EtherThreadMember(thread_id=thread.id, profile_id=pid))
    db.commit()
    return thread


def ensure_welcome_message(db: Session, target_profile: Profile) -> bool:
    admin_profile = _get_or_create_admin_profile(db)
    if not admin_profile:
        return False
    thread = _get_or_create_direct_thread(db, admin_profile.id, target_profile.id)
    existing = (
        db.query(EtherMessage)
        .filter(
            EtherMessage.thread_id == thread.id,
            EtherMessage.sender_profile_id == admin_profile.id,
            EtherMessage.content == WELCOME_MESSAGE,
        )
        .first()
    )
    if existing:
        return False
    msg = EtherMessage(
        thread_id=thread.id,
        sender_profile_id=admin_profile.id,
        content=WELCOME_MESSAGE,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return True


def send_welcome_messages_to_all(db: Session) -> int:
    admin_profile = _get_or_create_admin_profile(db)
    if not admin_profile:
        return 0
    sent = 0
    profiles = db.query(Profile).filter(Profile.id != admin_profile.id).all()
    for profile in profiles:
        if ensure_welcome_message(db, profile):
            sent += 1
    return sent
