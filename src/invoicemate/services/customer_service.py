from typing import List, Optional, Tuple
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from invoicemate.models.customer import Customer
from invoicemate.schemas.customer import CustomerCreate


def find_customers_by_name(db: Session, org_id: int, name_query: str) -> List[Customer]:
    """
    Search customers case-insensitively by name substring, strictly scoped to org_id.
    """
    cleaned_query = name_query.strip().lower()
    if not cleaned_query:
        return []
    stmt = select(Customer).where(
        and_(
            Customer.org_id == org_id,
            func.lower(Customer.name).contains(cleaned_query),
        )
    )
    return list(db.scalars(stmt).all())


def get_customer_by_exact_name(db: Session, org_id: int, name: str) -> Optional[Customer]:
    """
    Find customer by exact name (case-insensitive), strictly scoped to org_id.
    """
    cleaned_name = name.strip().lower()
    stmt = select(Customer).where(
        and_(
            Customer.org_id == org_id,
            func.lower(Customer.name) == cleaned_name,
        )
    )
    return db.scalars(stmt).first()


def resolve_customer_name(
    db: Session, org_id: int, name_query: str
) -> Tuple[Optional[Customer], List[Customer]]:
    """
    Resolve customer query according to ambiguity rules, strictly scoped to org_id:
    - Returns (exact_or_single_customer, []) if 1 match found.
    - Returns (None, matching_customers) if multiple matches found (disambiguation needed).
    - Returns (None, []) if 0 matches found (new customer confirmation needed).
    """
    exact = get_customer_by_exact_name(db, org_id=org_id, name=name_query)
    if exact:
        return exact, []

    matches = find_customers_by_name(db, org_id=org_id, name_query=name_query)
    if len(matches) == 1:
        return matches[0], []
    elif len(matches) > 1:
        return None, matches

    return None, []


def get_customer_by_id(db: Session, customer_id: int, org_id: Optional[int] = None) -> Optional[Customer]:
    """
    Fetch customer by primary key ID, optionally scoped to org_id.
    """
    cust = db.get(Customer, customer_id)
    if cust and org_id is not None and cust.org_id != org_id:
        return None
    return cust


def get_customer_by_telegram_id(db: Session, org_id: int, telegram_id: str) -> Optional[Customer]:
    """
    Fetch customer by Telegram ID, strictly scoped to org_id.
    """
    stmt = select(Customer).where(
        and_(
            Customer.org_id == org_id,
            Customer.telegram_id == str(telegram_id).strip(),
        )
    )
    return db.scalars(stmt).first()


def create_customer(db: Session, org_id: int, customer_in: CustomerCreate) -> Customer:
    """
    Create a new customer in database strictly assigned to org_id.
    """
    customer = Customer(
        org_id=org_id,
        name=customer_in.name.strip(),
        phone=customer_in.phone.strip() if customer_in.phone else None,
        telegram_id=str(customer_in.telegram_id).strip() if customer_in.telegram_id else None,
        default_currency=customer_in.default_currency or "USD",
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def get_or_create_customer(
    db: Session,
    org_id: int,
    name: str,
    phone: Optional[str] = None,
    telegram_id: Optional[str] = None,
    currency: str = "USD",
) -> Customer:
    """
    Get customer if exists by name within org_id, else create new customer record.
    """
    existing = get_customer_by_exact_name(db, org_id=org_id, name=name)
    if existing:
        return existing

    return create_customer(
        db,
        org_id=org_id,
        customer_in=CustomerCreate(
            name=name,
            phone=phone,
            telegram_id=telegram_id,
            default_currency=currency,
        ),
    )
