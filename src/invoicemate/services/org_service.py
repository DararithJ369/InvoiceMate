from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from invoicemate.models.org import Org, OrgInvoiceCounter


def get_org_by_id(db: Session, org_id: int) -> Optional[Org]:
    """Retrieve an organization by its primary key ID."""
    return db.get(Org, org_id)


def get_org_by_telegram_user_id(db: Session, telegram_user_id: str) -> Optional[Org]:
    """Retrieve an organization by its owning Telegram user ID."""
    stmt = select(Org).where(Org.telegram_user_id == str(telegram_user_id).strip())
    return db.scalars(stmt).first()


def create_org(
    db: Session,
    telegram_user_id: str,
    business_name: Optional[str] = None,
    phone: Optional[str] = None,
) -> Org:
    """
    Create a new organization and atomically seed its invoice counter to 0.
    Satisfies multi-tenant root entity requirements.
    """
    uid = str(telegram_user_id).strip()
    org = Org(
        telegram_user_id=uid,
        business_name=business_name.strip() if business_name else None,
        phone=phone.strip() if phone else None,
    )
    db.add(org)
    db.flush()  # populate org.id

    counter = OrgInvoiceCounter(org_id=org.id, current_value=0)
    db.add(counter)
    db.commit()
    db.refresh(org)
    return org


def get_or_create_org(
    db: Session,
    telegram_user_id: str,
    business_name: Optional[str] = None,
    phone: Optional[str] = None,
) -> Org:
    """Retrieve existing org by telegram_user_id or create new one with seeded counter."""
    existing = get_org_by_telegram_user_id(db, telegram_user_id)
    if existing:
        return existing
    return create_org(db, telegram_user_id=telegram_user_id, business_name=business_name, phone=phone)
