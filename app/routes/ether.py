# app/routes/ether.py

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Response
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_
from datetime import datetime
import io

from app.db.session import get_db
from app.core.security import get_current_user, get_verified_user
from app.models.ether import (
    Profile,
    EtherPost,
    EtherComment,
    EtherLike,
    EtherCommentLike,
    EtherGroup,
    EtherGroupMember,
    EtherThread,
    EtherThreadMember,
    EtherMessage,
    EtherSyncRequest,
    EtherNotification,
)
from app.models.user import User
from app.schemas.ether import (
    ProfileRead,
    ProfileUpdate,
    EtherPostCreate,
    EtherPostRead,
    EtherCommentCreate,
    EtherCommentRead,
    EtherGroupCreate,
    EtherGroupRead,
    EtherThreadCreate,
    EtherThreadRead,
    EtherMessageCreate,
    EtherMessageRead,
    EtherSyncRequestRead,
    EtherNotificationRead,
)
from app.services.r2 import upload_bytes, build_key
from app.services.moderation import moderate_avatar_image_bytes, moderate_image_bytes, moderate_text
from app.core.config import settings

from urllib.request import urlopen
from urllib.parse import urlparse

router = APIRouter(tags=["ether"], dependencies=[Depends(get_verified_user)])
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _find_direct_thread_ids(db: Session, profile_a_id: int, profile_b_id: int) -> list[int]:
    member_counts = (
        db.query(
            EtherThreadMember.thread_id.label("thread_id"),
            func.count(EtherThreadMember.profile_id).label("member_count"),
        )
        .group_by(EtherThreadMember.thread_id)
        .subquery()
    )
    threads = (
        db.query(EtherThreadMember.thread_id)
        .join(member_counts, member_counts.c.thread_id == EtherThreadMember.thread_id)
        .filter(
            EtherThreadMember.profile_id.in_([profile_a_id, profile_b_id]),
            member_counts.c.member_count == 2,
        )
        .group_by(EtherThreadMember.thread_id)
        .having(func.count(EtherThreadMember.profile_id) == 2)
        .all()
    )
    return [row.thread_id for row in threads]


def _ensure_safe_text(text: str | None) -> None:
    ok, reason = moderate_text(text)
    if not ok:
        raise HTTPException(status_code=400, detail=reason or "Text rejected.")

def is_admin(user) -> bool:
    return getattr(user, "role", None) == "admin"


def get_or_create_profile(db: Session, user) -> Profile:
    return get_or_create_profile_for_user(db, user)


def get_or_create_profile_for_user(db: Session, user) -> Profile:
    profile = db.query(Profile).filter(Profile.user_id == user.id).first()
    if profile:
        return profile
    display = user.username or user.email.split("@")[0]
    profile = Profile(user_id=user.id, display_name=display, is_public=True)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/ether/me-profile", response_model=ProfileRead)
def me_profile(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    return profile


@router.patch("/ether/me-profile", response_model=ProfileRead)
def update_profile(
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    if payload.display_name is not None:
        _ensure_safe_text(payload.display_name)
        profile.display_name = payload.display_name
    if payload.bio is not None:
        _ensure_safe_text(payload.bio)
        profile.bio = payload.bio
    if payload.links is not None:
        _ensure_safe_text(payload.links)
        profile.links = payload.links
    if payload.avatar_url is not None:
        profile.avatar_url = payload.avatar_url
    if payload.is_public is not None:
        profile.is_public = payload.is_public
    if payload.sync_requires_approval is not None:
        profile.sync_requires_approval = payload.sync_requires_approval
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/ether/feed", response_model=list[EtherPostRead])
def feed(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    posts = (
        db.query(EtherPost)
        .order_by(EtherPost.created_at.desc())
        .limit(50)
        .all()
    )
    return build_post_reads(db, posts, profile.id)


def build_post_reads(
    db: Session, posts: list[EtherPost], current_profile_id: int | None = None
) -> list[EtherPostRead]:
    if not posts:
        return []

    post_ids = [p.id for p in posts]
    like_counts = dict(
        db.query(EtherLike.post_id, func.count(EtherLike.id))
        .filter(EtherLike.post_id.in_(post_ids))
        .group_by(EtherLike.post_id)
        .all()
    )
    comment_counts = dict(
        db.query(EtherComment.post_id, func.count(EtherComment.id))
        .filter(EtherComment.post_id.in_(post_ids))
        .group_by(EtherComment.post_id)
        .all()
    )

    author_ids = list({p.author_profile_id for p in posts})
    authors = {
        row.id: row
        for row in db.query(Profile).filter(Profile.id.in_(author_ids)).all()
    }
    liked_by_me: set[int] = set()
    if current_profile_id:
        liked_by_me = {
            row[0]
            for row in db.query(EtherLike.post_id)
            .filter(
                EtherLike.post_id.in_(post_ids),
                EtherLike.profile_id == current_profile_id,
            )
            .all()
        }

    result: list[EtherPostRead] = []
    for post in posts:
        author = authors.get(post.author_profile_id)
        result.append(
            EtherPostRead(
                id=post.id,
                author_profile_id=post.author_profile_id,
                kind=post.kind,
                content=post.content,
                image_url=post.image_url,
                created_at=post.created_at,
                like_count=int(like_counts.get(post.id, 0)),
                liked_by_me=post.id in liked_by_me,
                comment_count=int(comment_counts.get(post.id, 0)),
                author_display_name=author.display_name if author else None,
                author_avatar_url=author.avatar_url if author else None,
            )
        )
    return result


def build_comment_reads(
    db: Session, comments: list[EtherComment], current_profile_id: int | None = None
) -> list[EtherCommentRead]:
    if not comments:
        return []

    profile_ids = {c.author_profile_id for c in comments}
    profiles = db.query(Profile).filter(Profile.id.in_(profile_ids)).all()
    profile_map = {p.id: p for p in profiles}
    comment_ids = [c.id for c in comments]
    align_counts = dict(
        db.query(EtherCommentLike.comment_id, func.count(EtherCommentLike.id))
        .filter(EtherCommentLike.comment_id.in_(comment_ids))
        .group_by(EtherCommentLike.comment_id)
        .all()
    )
    aligned_by_me = set()
    if current_profile_id is not None:
        aligned_by_me = {
            row[0]
            for row in db.query(EtherCommentLike.comment_id)
            .filter(
                EtherCommentLike.profile_id == current_profile_id,
                EtherCommentLike.comment_id.in_(comment_ids),
            )
            .all()
        }

    return [
        EtherCommentRead(
            id=c.id,
            post_id=c.post_id,
            author_profile_id=c.author_profile_id,
            content=c.content,
            created_at=c.created_at,
            author_display_name=profile_map.get(c.author_profile_id).display_name
            if profile_map.get(c.author_profile_id)
            else None,
            author_avatar_url=profile_map.get(c.author_profile_id).avatar_url
            if profile_map.get(c.author_profile_id)
            else None,
            align_count=int(align_counts.get(c.id, 0)),
            aligned_by_me=c.id in aligned_by_me,
        )
        for c in comments
    ]


def build_notification_reads(
    db: Session, notifications: list[EtherNotification]
) -> list[EtherNotificationRead]:
    if not notifications:
        return []

    actor_ids = {n.actor_profile_id for n in notifications}
    profiles = db.query(Profile).filter(Profile.id.in_(actor_ids)).all()
    profile_map = {p.id: p for p in profiles}

    return [
        EtherNotificationRead(
            id=n.id,
            recipient_profile_id=n.recipient_profile_id,
            actor_profile_id=n.actor_profile_id,
            kind=n.kind,
            post_id=n.post_id,
            comment_id=n.comment_id,
            created_at=n.created_at,
            read_at=n.read_at,
            actor_display_name=profile_map.get(n.actor_profile_id).display_name
            if profile_map.get(n.actor_profile_id)
            else None,
            actor_avatar_url=profile_map.get(n.actor_profile_id).avatar_url
            if profile_map.get(n.actor_profile_id)
            else None,
        )
        for n in notifications
    ]


def create_notification(
    db: Session,
    recipient_profile_id: int,
    actor_profile_id: int,
    kind: str,
    post_id: int | None = None,
    comment_id: int | None = None,
) -> None:
    if recipient_profile_id == actor_profile_id:
        return
    notification = EtherNotification(
        recipient_profile_id=recipient_profile_id,
        actor_profile_id=actor_profile_id,
        kind=kind,
        post_id=post_id,
        comment_id=comment_id,
    )
    db.add(notification)


@router.get("/ether/posts/mine", response_model=list[EtherPostRead])
def my_posts(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    posts = (
        db.query(EtherPost)
        .filter(EtherPost.author_profile_id == profile.id)
        .order_by(EtherPost.created_at.desc())
        .limit(50)
        .all()
    )
    return build_post_reads(db, posts, profile.id)


@router.get("/ether/posts/profile/{profile_id}", response_model=list[EtherPostRead])
def posts_by_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    target = db.query(Profile).filter(Profile.id == profile_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Profile not found")

    if target.id != profile.id and not target.is_public:
        approved = (
            db.query(EtherSyncRequest)
            .filter(
                EtherSyncRequest.status == "approved",
                or_(
                    and_(
                        EtherSyncRequest.requester_profile_id == profile.id,
                        EtherSyncRequest.target_profile_id == target.id,
                    ),
                    and_(
                        EtherSyncRequest.requester_profile_id == target.id,
                        EtherSyncRequest.target_profile_id == profile.id,
                    ),
                ),
            )
            .first()
        )
        if not approved:
            user = db.query(User).filter(User.id == target.user_id).first()
            display = (user.username if user else None) or (user.email if user else None) or target.display_name
            return ProfileRead(
                id=target.id,
                user_id=target.user_id,
                display_name=display,
                bio=None,
                avatar_url=target.avatar_url,
                is_public=target.is_public,
                sync_requires_approval=target.sync_requires_approval,
                created_at=target.created_at,
            )

    posts = (
        db.query(EtherPost)
        .filter(EtherPost.author_profile_id == target.id)
        .order_by(EtherPost.created_at.desc())
        .limit(50)
        .all()
    )
    return build_post_reads(db, posts, profile.id)


@router.get("/ether/timeline", response_model=list[EtherPostRead])
def timeline(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)

    approved_syncs = (
        db.query(EtherSyncRequest)
        .filter(
            EtherSyncRequest.status == "approved",
            or_(
                EtherSyncRequest.requester_profile_id == profile.id,
                EtherSyncRequest.target_profile_id == profile.id,
            ),
        )
        .all()
    )

    sync_profile_ids = set()
    for req in approved_syncs:
        other = req.target_profile_id if req.requester_profile_id == profile.id else req.requester_profile_id
        sync_profile_ids.add(other)

    posts = (
        db.query(EtherPost)
        .filter(
            EtherPost.author_profile_id.in_(list(sync_profile_ids) or [-1])
        )
        .order_by(EtherPost.created_at.desc())
        .limit(50)
        .all()
    )
    return build_post_reads(db, posts, profile.id)


@router.post("/ether/posts", response_model=EtherPostRead)
def create_post(
    payload: EtherPostCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    _ensure_safe_text(payload.content)
    post = EtherPost(
        author_profile_id=profile.id,
        kind=payload.kind,
        content=payload.content,
        image_url=payload.image_url,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return EtherPostRead(
        id=post.id,
        author_profile_id=post.author_profile_id,
        kind=post.kind,
        content=post.content,
        image_url=post.image_url,
        created_at=post.created_at,
        like_count=0,
        liked_by_me=False,
        comment_count=0,
        author_display_name=profile.display_name,
        author_avatar_url=profile.avatar_url,
    )


@router.delete("/ether/posts/{post_id}")
def delete_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    post = db.query(EtherPost).filter(EtherPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.author_profile_id != profile.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to delete this post")

    db.query(EtherLike).filter(EtherLike.post_id == post_id).delete()
    db.query(EtherComment).filter(EtherComment.post_id == post_id).delete()
    db.delete(post)
    db.commit()
    return {"status": "deleted"}


@router.post("/ether/posts/{post_id}/comments", response_model=EtherCommentRead)
def add_comment(
    post_id: int,
    payload: EtherCommentCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    post = db.query(EtherPost).filter(EtherPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    _ensure_safe_text(payload.content)
    comment = EtherComment(
        post_id=post.id,
        author_profile_id=profile.id,
        content=payload.content,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    create_notification(
        db,
        recipient_profile_id=post.author_profile_id,
        actor_profile_id=profile.id,
        kind="post_comment",
        post_id=post.id,
        comment_id=comment.id,
    )
    db.commit()
    return EtherCommentRead(
        id=comment.id,
        post_id=comment.post_id,
        author_profile_id=comment.author_profile_id,
        content=comment.content,
        created_at=comment.created_at,
        author_display_name=profile.display_name,
        author_avatar_url=profile.avatar_url,
        align_count=0,
        aligned_by_me=False,
    )


@router.get("/ether/posts/{post_id}/comments", response_model=list[EtherCommentRead])
def list_comments(
    post_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    comments = (
        db.query(EtherComment)
        .filter(EtherComment.post_id == post_id)
        .order_by(EtherComment.created_at.asc())
        .all()
    )
    return build_comment_reads(db, comments, profile.id)


@router.post("/ether/posts/{post_id}/like")
def toggle_like(
    post_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    post = db.query(EtherPost).filter(EtherPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    existing = (
        db.query(EtherLike)
        .filter(EtherLike.post_id == post_id, EtherLike.profile_id == profile.id)
        .first()
    )
    if existing:
        db.delete(existing)
        db.commit()
        return {"status": "unliked"}
    like = EtherLike(post_id=post_id, profile_id=profile.id)
    db.add(like)
    create_notification(
        db,
        recipient_profile_id=post.author_profile_id,
        actor_profile_id=profile.id,
        kind="post_align",
        post_id=post.id,
    )
    db.commit()
    return {"status": "liked"}


@router.post("/ether/comments/{comment_id}/align")
def toggle_comment_align(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    comment = db.query(EtherComment).filter(EtherComment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    existing = (
        db.query(EtherCommentLike)
        .filter(EtherCommentLike.comment_id == comment_id, EtherCommentLike.profile_id == profile.id)
        .first()
    )
    if existing:
        db.delete(existing)
        db.commit()
        count = (
            db.query(EtherCommentLike)
            .filter(EtherCommentLike.comment_id == comment_id)
            .count()
        )
        return {"status": "unaligned", "align_count": count}

    like = EtherCommentLike(comment_id=comment_id, profile_id=profile.id)
    db.add(like)
    post = db.query(EtherPost).filter(EtherPost.id == comment.post_id).first()
    if post:
        create_notification(
            db,
            recipient_profile_id=post.author_profile_id,
            actor_profile_id=profile.id,
            kind="comment_align",
            post_id=post.id,
            comment_id=comment.id,
        )
    db.commit()
    count = (
        db.query(EtherCommentLike)
        .filter(EtherCommentLike.comment_id == comment_id)
        .count()
    )
    return {"status": "aligned", "align_count": count}


@router.get("/ether/groups", response_model=list[EtherGroupRead])
def list_groups(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _ = get_or_create_profile(db, current_user)
    return db.query(EtherGroup).order_by(EtherGroup.created_at.desc()).all()


@router.post("/ether/groups", response_model=EtherGroupRead)
def create_group(
    payload: EtherGroupCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    _ensure_safe_text(payload.name)
    _ensure_safe_text(payload.description)
    profile = get_or_create_profile(db, current_user)
    group = EtherGroup(
        name=payload.name,
        description=payload.description,
        is_private=payload.is_private,
        created_by_profile_id=profile.id,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    member = EtherGroupMember(group_id=group.id, profile_id=profile.id, role="admin")
    db.add(member)
    db.commit()
    return group


@router.post("/ether/groups/{group_id}/join")
def join_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    group = db.query(EtherGroup).filter(EtherGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    existing = (
        db.query(EtherGroupMember)
        .filter(EtherGroupMember.group_id == group_id, EtherGroupMember.profile_id == profile.id)
        .first()
    )
    if existing:
        return {"status": "already_member"}
    member = EtherGroupMember(group_id=group_id, profile_id=profile.id, role="member")
    db.add(member)
    db.commit()
    return {"status": "joined"}


@router.get("/ether/profiles/search", response_model=list[ProfileRead])
def search_profiles(
    query: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    if not query.strip():
        return []
    raw = query.strip().lower()
    q = f"%{raw}%"
    normalized = raw.replace(" ", "").replace("_", "").replace("-", "")
    qn = f"%{normalized}%"

    def normalize(expr):
        return func.replace(func.replace(func.replace(func.lower(expr), " ", ""), "_", ""), "-", "")

    matched_profiles = (
        db.query(Profile)
        .filter(Profile.id != profile.id)
        .filter(
            or_(
                func.lower(Profile.display_name).like(q),
                normalize(Profile.display_name).like(qn),
            )
        )
        .limit(10)
        .all()
    )

    matched_users = (
        db.query(User)
        .filter(User.id != current_user.id)
        .filter(
            or_(
                func.lower(User.username).like(q),
                func.lower(User.email).like(q),
                normalize(User.username).like(qn),
                normalize(User.email).like(qn),
            )
        )
        .limit(10)
        .all()
    )

    profiles_by_id = {p.id: p for p in matched_profiles}
    users_by_id = {u.id: u for u in matched_users}

    for user in matched_users:
        prof = db.query(Profile).filter(Profile.user_id == user.id).first()
        if not prof:
            prof = get_or_create_profile_for_user(db, user)
        profiles_by_id[prof.id] = prof
        users_by_id[user.id] = user

    payload = []
    for prof in profiles_by_id.values():
        user = users_by_id.get(prof.user_id)
        display = (user.username if user else None) or (user.email if user else None) or prof.display_name
        payload.append(
            ProfileRead(
                id=prof.id,
                user_id=prof.user_id,
                display_name=display,
                bio=prof.bio,
                links=prof.links,
                avatar_url=prof.avatar_url,
                is_public=prof.is_public,
                sync_requires_approval=prof.sync_requires_approval,
                created_at=prof.created_at,
            )
        )

    payload = payload[:10]
    return payload


@router.get("/ether/profiles/{profile_id}", response_model=ProfileRead)
def get_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    target = db.query(Profile).filter(Profile.id == profile_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Profile not found")
    user = db.query(User).filter(User.id == target.user_id).first()
    store_url = "https://a.co/d/856lhhB" if (user and user.email == "billionaireBrea@wealth.com") else None

    if target.id != profile.id and not target.is_public:
        approved = (
            db.query(EtherSyncRequest)
            .filter(
                EtherSyncRequest.status == "approved",
                or_(
                    and_(
                        EtherSyncRequest.requester_profile_id == profile.id,
                        EtherSyncRequest.target_profile_id == target.id,
                    ),
                    and_(
                        EtherSyncRequest.requester_profile_id == target.id,
                        EtherSyncRequest.target_profile_id == profile.id,
                    ),
                ),
            )
            .first()
        )
        if not approved:
            display = (user.username if user else None) or (user.email if user else None) or target.display_name
            return ProfileRead(
                id=target.id,
                user_id=target.user_id,
                display_name=display,
                bio=None,
                links=None,
                avatar_url=target.avatar_url,
                is_public=target.is_public,
                sync_requires_approval=target.sync_requires_approval,
                store_url=store_url,
                created_at=target.created_at,
            )

    display = (user.username if user else None) or (user.email if user else None) or target.display_name
    return ProfileRead(
        id=target.id,
        user_id=target.user_id,
        display_name=display,
        bio=target.bio,
        links=target.links,
        avatar_url=target.avatar_url,
        is_public=target.is_public,
        sync_requires_approval=target.sync_requires_approval,
        store_url=store_url,
        created_at=target.created_at,
    )


@router.post("/ether/upload/avatar")
def upload_avatar(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    content_type = file.content_type or "image/jpeg"
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image uploads are supported.")
    payload = file.file.read()
    if len(payload) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds 5MB limit.")
    ok, reason = moderate_avatar_image_bytes(payload)
    if not ok:
        raise HTTPException(status_code=400, detail=reason or "Image rejected.")
    key = build_key(f"avatars/{profile.id}", file.filename)
    url = upload_bytes(io.BytesIO(payload), key, content_type)
    profile.avatar_url = url
    db.add(profile)
    db.commit()
    return {"url": url}


@router.post("/ether/upload/post-image")
def upload_post_image(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    content_type = file.content_type or "image/jpeg"
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image uploads are supported.")
    payload = file.file.read()
    if len(payload) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds 5MB limit.")
    ok, reason = moderate_image_bytes(payload)
    if not ok:
        raise HTTPException(status_code=400, detail=reason or "Image rejected.")
    key = build_key(f"posts/{profile.id}", file.filename)
    url = upload_bytes(io.BytesIO(payload), key, content_type)
    return {"url": url}


@router.get("/ether/avatar/source")
def proxy_avatar(
    url: str,
    db: Session = Depends(get_db),
):
    base = (settings.R2_PUBLIC_BASE_URL or "").rstrip("/")
    if not base:
        raise HTTPException(status_code=400, detail="Invalid avatar source")

    base_host = urlparse(base).netloc
    target = urlparse(url)
    if not base_host or target.scheme not in ("http", "https") or target.netloc != base_host:
        raise HTTPException(status_code=400, detail="Invalid avatar source")

    try:
        with urlopen(url) as resp:
            content = resp.read()
            content_type = resp.headers.get("Content-Type", "image/jpeg")
    except Exception:
        raise HTTPException(status_code=400, detail="Unable to load avatar")

    return Response(content=content, media_type=content_type)


@router.post("/ether/sync/requests/{target_profile_id}", response_model=EtherSyncRequestRead)
def create_sync_request(
    target_profile_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    if profile.id == target_profile_id:
        raise HTTPException(status_code=400, detail="Cannot sync with yourself")

    existing = (
        db.query(EtherSyncRequest)
        .filter(
            EtherSyncRequest.requester_profile_id == profile.id,
            EtherSyncRequest.target_profile_id == target_profile_id,
        )
        .first()
    )
    if existing:
        return existing

    target_profile = db.query(Profile).filter(Profile.id == target_profile_id).first()
    if not target_profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    status_value = "approved" if target_profile.sync_requires_approval is False else "pending"
    sync_request = EtherSyncRequest(
        requester_profile_id=profile.id,
        target_profile_id=target_profile_id,
        status=status_value,
    )
    db.add(sync_request)
    db.commit()
    db.refresh(sync_request)
    return sync_request


@router.get("/ether/sync/requests", response_model=list[EtherSyncRequestRead])
def list_sync_requests(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    requests = (
        db.query(EtherSyncRequest)
        .filter(EtherSyncRequest.target_profile_id == profile.id, EtherSyncRequest.status == "pending")
        .order_by(EtherSyncRequest.created_at.desc())
        .all()
    )
    requester_ids = [req.requester_profile_id for req in requests]
    if not requester_ids:
      return []
    requesters = (
        db.query(Profile, User)
        .join(User, Profile.user_id == User.id)
        .filter(Profile.id.in_(requester_ids))
        .all()
    )
    requester_map = {
        prof.id: {"name": user.username or user.email, "avatar": prof.avatar_url}
        for prof, user in requesters
    }
    for req in requests:
        info = requester_map.get(req.requester_profile_id, {})
        setattr(req, "requester_display_name", info.get("name"))
        setattr(req, "requester_avatar_url", info.get("avatar"))
    return requests


@router.get("/ether/sync/requests/outgoing", response_model=list[EtherSyncRequestRead])
def list_outgoing_sync_requests(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    return (
        db.query(EtherSyncRequest)
        .filter(EtherSyncRequest.requester_profile_id == profile.id, EtherSyncRequest.status == "pending")
        .order_by(EtherSyncRequest.created_at.desc())
        .all()
    )


@router.delete("/ether/sync/requests/{request_id}")
def cancel_sync_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    request = db.query(EtherSyncRequest).filter(EtherSyncRequest.id == request_id).first()
    if not request or request.requester_profile_id != profile.id:
        raise HTTPException(status_code=404, detail="Request not found")
    if request.status != "pending":
        raise HTTPException(status_code=400, detail="Request is not pending")
    db.delete(request)
    db.commit()
    return {"status": "cancelled"}


@router.delete("/ether/syncs/{profile_id}")
def remove_sync(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    request = (
        db.query(EtherSyncRequest)
        .filter(
            EtherSyncRequest.status == "approved",
            (
                (EtherSyncRequest.requester_profile_id == profile.id)
                & (EtherSyncRequest.target_profile_id == profile_id)
            )
            | (
                (EtherSyncRequest.requester_profile_id == profile_id)
                & (EtherSyncRequest.target_profile_id == profile.id)
            ),
        )
        .first()
    )
    if not request:
        raise HTTPException(status_code=404, detail="Sync not found")
    db.delete(request)
    db.commit()
    return {"status": "removed"}


@router.post("/ether/sync/requests/{request_id}/approve", response_model=EtherSyncRequestRead)
def approve_sync(
    request_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    request = db.query(EtherSyncRequest).filter(EtherSyncRequest.id == request_id).first()
    if not request or request.target_profile_id != profile.id:
        raise HTTPException(status_code=404, detail="Request not found")
    request.status = "approved"
    request.responded_at = func.now()
    db.add(request)
    create_notification(
        db,
        recipient_profile_id=request.requester_profile_id,
        actor_profile_id=profile.id,
        kind="sync_approved",
    )
    db.commit()
    db.refresh(request)
    return request


@router.post("/ether/sync/requests/{request_id}/decline", response_model=EtherSyncRequestRead)
def decline_sync(
    request_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    request = db.query(EtherSyncRequest).filter(EtherSyncRequest.id == request_id).first()
    if not request or request.target_profile_id != profile.id:
        raise HTTPException(status_code=404, detail="Request not found")
    request.status = "declined"
    request.responded_at = func.now()
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


@router.get("/ether/syncs", response_model=list[ProfileRead])
def list_syncs(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    approved = (
        db.query(EtherSyncRequest)
        .filter(
            EtherSyncRequest.status == "approved",
            (EtherSyncRequest.requester_profile_id == profile.id)
            | (EtherSyncRequest.target_profile_id == profile.id),
        )
        .all()
    )
    partner_ids = set()
    for req in approved:
        partner_ids.add(req.requester_profile_id)
        partner_ids.add(req.target_profile_id)
    partner_ids.discard(profile.id)
    if not partner_ids:
        return []
    return db.query(Profile).filter(Profile.id.in_(list(partner_ids))).all()


@router.get("/ether/notifications", response_model=list[EtherNotificationRead])
def list_notifications(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    notifications = (
        db.query(EtherNotification)
        .filter(EtherNotification.recipient_profile_id == profile.id)
        .order_by(EtherNotification.created_at.desc())
        .limit(50)
        .all()
    )
    return build_notification_reads(db, notifications)


@router.post("/ether/notifications/mark-read")
def mark_notifications_read(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    db.query(EtherNotification).filter(
        EtherNotification.recipient_profile_id == profile.id,
        EtherNotification.read_at.is_(None),
    ).update({EtherNotification.read_at: func.now()})
    db.commit()
    return {"status": "ok"}


@router.delete("/ether/notifications/{notification_id}")
def delete_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    notification = (
        db.query(EtherNotification)
        .filter(
            EtherNotification.id == notification_id,
            EtherNotification.recipient_profile_id == profile.id,
        )
        .first()
    )
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    db.delete(notification)
    db.commit()
    return {"status": "deleted"}


@router.post("/ether/threads", response_model=EtherThreadRead)
def create_thread(
    payload: EtherThreadCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    if profile.id not in payload.participant_profile_ids:
        payload.participant_profile_ids.append(profile.id)
    participants = list(set(payload.participant_profile_ids))
    if len(participants) == 2:
        existing_ids = _find_direct_thread_ids(db, participants[0], participants[1])
        if existing_ids:
            threads = db.query(EtherThread).filter(EtherThread.id.in_(existing_ids)).all()
            canonical = sorted(threads, key=lambda t: t.created_at or datetime.min)[0]
            extras = [t for t in threads if t.id != canonical.id]
            if extras:
                extra_ids = [t.id for t in extras]
                db.query(EtherMessage).filter(EtherMessage.thread_id.in_(extra_ids)).update(
                    {EtherMessage.thread_id: canonical.id}, synchronize_session=False
                )
                db.query(EtherThreadMember).filter(EtherThreadMember.thread_id.in_(extra_ids)).delete(
                    synchronize_session=False
                )
                db.query(EtherThread).filter(EtherThread.id.in_(extra_ids)).delete(synchronize_session=False)
                db.commit()
            member = (
                db.query(EtherThreadMember)
                .filter(EtherThreadMember.thread_id == canonical.id, EtherThreadMember.profile_id == profile.id)
                .first()
            )
            if member and member.deleted_at:
                member.deleted_at = None
                db.add(member)
                db.commit()
            return EtherThreadRead(id=canonical.id, created_at=canonical.created_at, participants=participants)
    thread = EtherThread()
    db.add(thread)
    db.commit()
    db.refresh(thread)
    for pid in participants:
        db.add(EtherThreadMember(thread_id=thread.id, profile_id=pid))
    db.commit()
    return EtherThreadRead(id=thread.id, created_at=thread.created_at, participants=participants)


@router.get("/ether/threads", response_model=list[EtherThreadRead])
def list_threads(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    thread_ids = [
        row.thread_id
        for row in db.query(EtherThreadMember.thread_id)
        .filter(EtherThreadMember.profile_id == profile.id)
        .all()
    ]
    threads = db.query(EtherThread).filter(EtherThread.id.in_(thread_ids)).all() if thread_ids else []
    result = []
    participant_cache: dict[int, list[int]] = {}
    for thread in threads:
        participants = [
            row.profile_id
            for row in db.query(EtherThreadMember.profile_id)
            .filter(EtherThreadMember.thread_id == thread.id)
            .all()
        ]
        participant_cache[thread.id] = participants
    pair_map: dict[tuple[int, int], list[EtherThread]] = {}
    for thread in threads:
        participants = participant_cache.get(thread.id, [])
        if len(participants) == 2:
            key = tuple(sorted(participants))
            pair_map.setdefault(key, []).append(thread)
    for items in pair_map.values():
        if len(items) <= 1:
            continue
        canonical = sorted(items, key=lambda t: t.created_at or datetime.min)[0]
        extra_ids = [t.id for t in items if t.id != canonical.id]
        if extra_ids:
            db.query(EtherMessage).filter(EtherMessage.thread_id.in_(extra_ids)).update(
                {EtherMessage.thread_id: canonical.id}, synchronize_session=False
            )
            db.query(EtherThreadMember).filter(EtherThreadMember.thread_id.in_(extra_ids)).delete(
                synchronize_session=False
            )
            db.query(EtherThread).filter(EtherThread.id.in_(extra_ids)).delete(synchronize_session=False)
            db.commit()
            for extra_id in extra_ids:
                participant_cache.pop(extra_id, None)
            threads = [t for t in threads if t.id not in extra_ids]
    for thread in threads:
        participants = participant_cache.get(thread.id, [])
        result.append(EtherThreadRead(id=thread.id, created_at=thread.created_at, participants=participants))
    return result


@router.post("/ether/threads/{thread_id}/messages", response_model=EtherMessageRead)
def send_message(
    thread_id: int,
    payload: EtherMessageCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    member = (
        db.query(EtherThreadMember)
        .filter(EtherThreadMember.thread_id == thread_id, EtherThreadMember.profile_id == profile.id)
        .first()
    )
    if not member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a thread member")
    if member.deleted_at:
        member.deleted_at = None
        db.add(member)
        db.commit()
    _ensure_safe_text(payload.content)
    msg = EtherMessage(thread_id=thread_id, sender_profile_id=profile.id, content=payload.content)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


@router.get("/ether/threads/{thread_id}/messages", response_model=list[EtherMessageRead])
def list_messages(
    thread_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    member = (
        db.query(EtherThreadMember)
        .filter(EtherThreadMember.thread_id == thread_id, EtherThreadMember.profile_id == profile.id)
        .first()
    )
    if not member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a thread member")
    query = db.query(EtherMessage).filter(EtherMessage.thread_id == thread_id)
    if member.deleted_at:
        query = query.filter(EtherMessage.created_at > member.deleted_at)
    return query.order_by(EtherMessage.created_at.asc()).all()


@router.post("/ether/threads/{thread_id}/clear")
def clear_thread(
    thread_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = get_or_create_profile(db, current_user)
    member = (
        db.query(EtherThreadMember)
        .filter(EtherThreadMember.thread_id == thread_id, EtherThreadMember.profile_id == profile.id)
        .first()
    )
    if not member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a thread member")
    member.deleted_at = func.now()
    db.add(member)
    db.commit()
    return {"status": "cleared"}
