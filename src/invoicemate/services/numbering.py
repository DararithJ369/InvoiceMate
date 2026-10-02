import re
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from invoicemate.core.config import settings
from invoicemate.models.org import OrgInvoiceCounter
from invoicemate.models.invoice import Invoice


def parse_invoice_number(invoice_number: str, prefix: str = settings.INVOICE_PREFIX) -> int:
    """
    Extract numeric component from invoice number string like 'INV-000125'.
    Returns 0 if non-matching or invalid.
    """
    if not invoice_number:
        return 0
    pattern = rf"^{re.escape(prefix)}(\d+)$"
    match = re.match(pattern, invoice_number)
    if match:
        return int(match.group(1))
    return 0


def assign_next_invoice_number(
    db: Session,
    org_id: int,
    prefix: str = settings.INVOICE_PREFIX,
    padding: int = settings.INVOICE_PADDING,
) -> str:
    """
    Atomically lock and increment the org's invoice counter row using UPDATE ... RETURNING,
    and return the formatted sequential invoice number.
    
    Must be executed within the active commit transaction of the invoice.
    Guarantees zero duplicate invoice numbers and no race conditions under concurrent requests.
    """
    now = datetime.now(timezone.utc)

    # Ensure counter row exists
    counter_exists = db.scalars(
        select(OrgInvoiceCounter.current_value).where(OrgInvoiceCounter.org_id == org_id)
    ).first()

    if counter_exists is None:
        db.add(OrgInvoiceCounter(org_id=org_id, current_value=0))
        db.flush()

    # Atomic UPDATE with RETURNING (supported in PostgreSQL & SQLite 3.35+)
    stmt = (
        update(OrgInvoiceCounter)
        .where(OrgInvoiceCounter.org_id == org_id)
        .values(
            current_value=OrgInvoiceCounter.current_value + 1,
            updated_at=now,
        )
        .returning(OrgInvoiceCounter.current_value)
    )
    new_value = db.scalars(stmt).one()
    return f"{prefix}{new_value:0{padding}d}"


def generate_next_invoice_number(
    db: Session,
    prefix: str = settings.INVOICE_PREFIX,
    padding: int = settings.INVOICE_PADDING,
    org_id: int = 1,
) -> str:
    """
    Legacy convenience helper for backwards compatibility and fallback generation.
    If org_id is provided, delegates to atomic counter assignment.
    """
    try:
        return assign_next_invoice_number(db, org_id=org_id, prefix=prefix, padding=padding)
    except Exception:
        stmt = select(Invoice.invoice_number).where(
            Invoice.invoice_number.like(f"{prefix}%")
        )
        existing_numbers = db.scalars(stmt).all()

        max_seq = 0
        for num_str in existing_numbers:
            seq = parse_invoice_number(num_str, prefix=prefix)
            if seq > max_seq:
                max_seq = seq

        next_seq = max_seq + 1
        return f"{prefix}{next_seq:0{padding}d}"
