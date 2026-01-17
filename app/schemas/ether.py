# app/schemas/ether.py

from datetime import datetime
from pydantic import BaseModel


class ProfileRead(BaseModel):
    id: int
    user_id: int
    display_name: str
    bio: str | None = None
    avatar_url: str | None = None
    is_public: bool
    sync_requires_approval: bool
    store_url: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    display_name: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    is_public: bool | None = None
    sync_requires_approval: bool | None = None


class EtherPostCreate(BaseModel):
    kind: str = "post"
    content: str
    image_url: str | None = None


class EtherPostRead(BaseModel):
    id: int
    author_profile_id: int
    kind: str
    content: str
    image_url: str | None = None
    created_at: datetime
    like_count: int = 0
    liked_by_me: bool = False
    comment_count: int = 0
    author_display_name: str | None = None
    author_avatar_url: str | None = None

    class Config:
        from_attributes = True


class EtherCommentCreate(BaseModel):
    content: str


class EtherCommentRead(BaseModel):
    id: int
    post_id: int
    author_profile_id: int
    content: str
    created_at: datetime
    author_display_name: str | None = None
    author_avatar_url: str | None = None
    align_count: int = 0
    aligned_by_me: bool = False

    class Config:
        from_attributes = True


class EtherGroupCreate(BaseModel):
    name: str
    description: str | None = None
    is_private: bool = False


class EtherGroupRead(BaseModel):
    id: int
    name: str
    description: str | None = None
    is_private: bool
    created_by_profile_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class EtherThreadCreate(BaseModel):
    participant_profile_ids: list[int]


class EtherThreadRead(BaseModel):
    id: int
    created_at: datetime
    participants: list[int]


class EtherMessageCreate(BaseModel):
    content: str


class EtherMessageRead(BaseModel):
    id: int
    thread_id: int
    sender_profile_id: int
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class EtherSyncRequestRead(BaseModel):
    id: int
    requester_profile_id: int
    target_profile_id: int
    status: str
    created_at: datetime
    responded_at: datetime | None = None
    requester_display_name: str | None = None
    requester_avatar_url: str | None = None
    requester_display_name: str | None = None
    requester_avatar_url: str | None = None

    class Config:
        from_attributes = True


class EtherNotificationRead(BaseModel):
    id: int
    recipient_profile_id: int
    actor_profile_id: int
    kind: str
    post_id: int | None = None
    comment_id: int | None = None
    created_at: datetime
    read_at: datetime | None = None
    actor_display_name: str | None = None
    actor_avatar_url: str | None = None

    class Config:
        from_attributes = True
