from sqlalchemy.orm import Session

from app.models.legal_acceptance import LegalAcceptance
from app.models.user import User


def record_legal_acceptances(
    db: Session,
    user: User,
    *,
    accepted_at,
    terms_version: str,
    privacy_version: str,
) -> None:
    existing = {
        (row.document_type, row.version)
        for row in db.query(LegalAcceptance)
        .filter(LegalAcceptance.user_id == user.id)
        .all()
    }

    rows = []
    if ("terms", terms_version) not in existing:
        rows.append(
            LegalAcceptance(
                user_id=user.id,
                document_type="terms",
                version=terms_version,
                accepted_at=accepted_at,
            )
        )
    if ("privacy", privacy_version) not in existing:
        rows.append(
            LegalAcceptance(
                user_id=user.id,
                document_type="privacy",
                version=privacy_version,
                accepted_at=accepted_at,
            )
        )

    if rows:
        db.add_all(rows)
