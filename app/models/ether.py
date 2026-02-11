# app/models/ether.py

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, func, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.session import Base


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=False)
    bio = Column(Text, nullable=True)
    links = Column(Text, nullable=True)
    avatar_url = Column(String, nullable=True)
    is_public = Column(Boolean, default=True, nullable=False)
    sync_requires_approval = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", backref="profile")


class EtherPost(Base):
    __tablename__ = "ether_posts"

    id = Column(Integer, primary_key=True, index=True)
    author_profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False, index=True)
    kind = Column(String, nullable=False, default="post")  # post | win | manifestation
    content = Column(Text, nullable=False)
    image_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    author = relationship("Profile", foreign_keys=[author_profile_id])


class EtherComment(Base):
    __tablename__ = "ether_comments"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("ether_posts.id"), nullable=False, index=True)
    author_profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    post = relationship("EtherPost", foreign_keys=[post_id])
    author = relationship("Profile", foreign_keys=[author_profile_id])


class EtherCommentLike(Base):
    __tablename__ = "ether_comment_likes"

    id = Column(Integer, primary_key=True, index=True)
    comment_id = Column(Integer, ForeignKey("ether_comments.id"), nullable=False, index=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("comment_id", "profile_id", name="uq_ether_comment_like"),
    )


class EtherNotification(Base):
    __tablename__ = "ether_notifications"

    id = Column(Integer, primary_key=True, index=True)
    recipient_profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False, index=True)
    actor_profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)
    post_id = Column(Integer, ForeignKey("ether_posts.id"), nullable=True, index=True)
    comment_id = Column(Integer, ForeignKey("ether_comments.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=True)

class EtherLike(Base):
    __tablename__ = "ether_likes"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("ether_posts.id"), nullable=False, index=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("post_id", "profile_id", name="uq_ether_like_post_profile"),
    )


class EtherGroup(Base):
    __tablename__ = "ether_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    description = Column(Text, nullable=True)
    is_private = Column(Boolean, default=False, nullable=False)
    created_by_profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    owner = relationship("Profile", foreign_keys=[created_by_profile_id])


class EtherGroupMember(Base):
    __tablename__ = "ether_group_members"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("ether_groups.id"), nullable=False, index=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False, index=True)
    role = Column(String, nullable=False, default="member")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("group_id", "profile_id", name="uq_ether_group_member"),
    )


class EtherSyncRequest(Base):
    __tablename__ = "ether_sync_requests"

    id = Column(Integer, primary_key=True, index=True)
    requester_profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False, index=True)
    target_profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False, index=True)
    status = Column(String, nullable=False, default="pending")  # pending | approved | declined
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    responded_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("requester_profile_id", "target_profile_id", name="uq_ether_sync_request"),
    )


class EtherThread(Base):
    __tablename__ = "ether_threads"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EtherThreadMember(Base):
    __tablename__ = "ether_thread_members"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(Integer, ForeignKey("ether_threads.id"), nullable=False, index=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("thread_id", "profile_id", name="uq_ether_thread_member"),
    )


class EtherMessage(Base):
    __tablename__ = "ether_messages"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(Integer, ForeignKey("ether_threads.id"), nullable=False, index=True)
    sender_profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    thread = relationship("EtherThread", foreign_keys=[thread_id])
    sender = relationship("Profile", foreign_keys=[sender_profile_id])
