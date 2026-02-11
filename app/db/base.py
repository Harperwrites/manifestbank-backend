# app/db/base.py
# Import Base and ALL models so they register on Base.metadata

from app.db.session import Base  # Base lives in session.py

# Import models to register them (do not use these imports elsewhere)
from app.models.user import User
from app.models.account import Account
from app.models.ledger import LedgerEntry
from app.models.subscriber import EmailSubscriber
from app.models.scheduled_entry import ScheduledEntry
from app.models.ether import (
    Profile,
    EtherPost,
    EtherComment,
    EtherLike,
    EtherGroup,
    EtherGroupMember,
    EtherThread,
    EtherThreadMember,
    EtherMessage,
    EtherSyncRequest,
)
from app.models.pwa import PwaEvent
from app.models.journal import JournalEntry
from app.models.affirmation import AffirmationEntry
