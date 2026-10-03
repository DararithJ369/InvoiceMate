import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional, Union, Dict, Any
from sqlalchemy import select, or_, func, and_
from sqlalchemy.orm import Session

from invoicemate.core.config import settings
from invoicemate.models.customer import Customer
from invoicemate.models.draft import Draft
from invoicemate.models.invoice import Invoice
from invoicemate.models.invoice_item import InvoiceItem
from invoicemate.models.invoice_event import InvoiceEvent
from invoicemate.models.enums import InvoiceStatus, DraftState, PdfStatus, EventType
from invoicemate.services.calculator import (
    calculate_line_total,
    calculate_subtotal,
    calculate_tax,
    calculate_total,
    recalculate_invoice_totals,
    to_decimal,
)
from invoicemate.services.numbering import assign_next_invoice_number, generate_next_invoice_number
from invoicemate.services.customer_service import get_or_create_customer, get_customer_by_id
from invoicemate.services.exchange_rate_service import resolve_exchange_rate, ExchangeRateResult

logger = logging.getLogger(__name__)

ItemDict = Dict[str, Any]


def _normalize_items(raw_items: List[Union[ItemDict, Any]]) -> List[Dict[str, Any]]:
    """
    Normalize raw item dicts or objects into a standardized format with Decimal quantities & prices.
    Raises ValueError if invalid.
    """
    if not raw_items:
        raise ValueError("Invoice must contain at least one item")

    normalized = []
    for item in raw_items:
        if isinstance(item, dict):
            name = item.get("product_name") or item.get("name")
            qty = item.get("quantity") if "quantity" in item else item.get("qty")
            price = item.get("unit_price") if "unit_price" in item else item.get("price")
            discount = item.get("discount_amount") or item.get("discount", 0)
        else:
            name = getattr(item, "product_name", None) or getattr(item, "name", None)
            qty = getattr(item, "quantity", None) or getattr(item, "qty", None)
            price = getattr(item, "unit_price", None) or getattr(item, "price", None)
            discount = getattr(item, "discount_amount", 0) or getattr(item, "discount", 0)

        if not name or not str(name).strip():
            raise ValueError("Every line item must have a valid product_name")
        if qty is None or price is None:
            raise ValueError(f"Line item '{name}' must have quantity and unit_price")

        qty_dec = to_decimal(qty)
        price_dec = to_decimal(price)
        discount_dec = to_decimal(discount)

        if qty_dec <= 0:
            raise ValueError(f"Quantity for '{name}' must be greater than 0")
        if price_dec < 0:
            raise ValueError(f"Unit price for '{name}' cannot be negative")

        line_tot = calculate_line_total(qty_dec, price_dec, discount_amount=discount_dec)
        normalized.append({
            "product_name": str(name).strip(),
            "quantity": qty_dec,
            "unit_price": price_dec,
            "discount_amount": discount_dec,
            "line_total": line_tot,
        })

    return normalized


def create_draft(
    db: Session,
    items: List[Union[ItemDict, Any]],
    org_id: int = 1,
    chat_id: str = "default_chat",
    customer_id: Optional[int] = None,
    customer_name: Optional[str] = None,
    currency: Optional[str] = None,
    due_date: Optional[Union[date, str]] = None,
    tax_rate: Union[Decimal, float, int, str] = Decimal("0.00"),
    is_tax_invoice: bool = False,
    apply_plt: bool = False,
    apply_accommodation_tax: bool = False,
) -> Draft:
    """
    Create a new uncommitted conversational invoice draft strictly scoped to org_id.
    Persisted in drafts table without assigning a permanent invoice number yet.
    """
    normalized_items = _normalize_items(items)

    # Resolve customer within org_id
    target_customer = None
    if customer_id:
        target_customer = get_customer_by_id(db, customer_id, org_id=org_id)
        if not target_customer:
            raise ValueError(f"Customer with id {customer_id} not found in this organization")
    elif customer_name and customer_name.strip():
        curr = currency or settings.DEFAULT_CURRENCY
        target_customer = get_or_create_customer(
            db, org_id=org_id, name=customer_name.strip(), currency=curr
        )

    chosen_currency = (
        currency
        or (target_customer.default_currency if target_customer else None)
        or settings.DEFAULT_CURRENCY
    )

    # Calculate totals
    totals = recalculate_invoice_totals(
        normalized_items,
        tax_rate=tax_rate,
        is_tax_invoice=is_tax_invoice,
        apply_plt=apply_plt,
        apply_accommodation_tax=apply_accommodation_tax,
        currency=chosen_currency,
    )

    due_date_val = due_date.isoformat() if isinstance(due_date, date) else due_date

    draft_json = {
        "items": [
            {
                "product_name": itm["product_name"],
                "quantity": float(itm["quantity"]),
                "unit_price": float(itm["unit_price"]),
                "discount_amount": float(itm["discount_amount"]),
                "line_total": float(itm["line_total"]),
            }
            for itm in totals["items"]
        ],
        "subtotal": float(totals["subtotal"]),
        "vat": float(totals["vat"]),
        "plt": float(totals["plt"]),
        "accommodation_tax": float(totals["accommodation_tax"]),
        "tax": float(totals["tax"]),
        "total": float(totals["total"]),
        "currency": chosen_currency,
        "due_date": due_date_val,
        "customer_id": target_customer.id if target_customer else None,
        "customer_name": target_customer.name if target_customer else customer_name,
        "is_tax_invoice": is_tax_invoice,
    }

    draft = Draft(
        org_id=org_id,
        chat_id=str(chat_id),
        customer_id=target_customer.id if target_customer else None,
        draft_json=draft_json,
        state=DraftState.WAITING_FOR_CONFIRMATION.value,
    )

    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def update_draft(
    db: Session,
    draft_id: int,
    org_id: Optional[int] = None,
    items: Optional[List[Union[ItemDict, Any]]] = None,
    customer_id: Optional[int] = None,
    customer_name: Optional[str] = None,
    currency: Optional[str] = None,
    due_date: Optional[Union[date, str]] = None,
    tax_rate: Optional[Union[Decimal, float, int, str]] = None,
    is_tax_invoice: Optional[bool] = None,
) -> Draft:
    """
    Update an existing conversational draft using partial JSON merge/patch against drafts.draft_json.
    Only allowed when draft is uncommitted.
    """
    draft = db.get(Draft, draft_id)
    if not draft or (org_id is not None and draft.org_id != org_id):
        raise ValueError(f"Draft with id {draft_id} not found")

    if draft.state not in [
        DraftState.DRAFTING.value,
        DraftState.WAITING_FOR_CUSTOMER_SELECTION.value,
        DraftState.WAITING_FOR_CONFIRMATION.value,
    ]:
        raise ValueError(f"Cannot update draft {draft_id} because state is '{draft.state}'")

    current_json = dict(draft.draft_json or {})

    # Customer updates
    effective_org = draft.org_id
    if customer_id is not None:
        cust = get_customer_by_id(db, customer_id, org_id=effective_org)
        if not cust:
            raise ValueError(f"Customer with id {customer_id} not found")
        draft.customer_id = cust.id
        current_json["customer_id"] = cust.id
        current_json["customer_name"] = cust.name
    elif customer_name is not None and customer_name.strip():
        cust = get_or_create_customer(
            db, org_id=effective_org, name=customer_name.strip(), currency=currency or current_json.get("currency", "USD")
        )
        draft.customer_id = cust.id
        current_json["customer_id"] = cust.id
        current_json["customer_name"] = cust.name

    if currency:
        current_json["currency"] = currency
    if due_date is not None:
        current_json["due_date"] = due_date.isoformat() if isinstance(due_date, date) else due_date
    if is_tax_invoice is not None:
        current_json["is_tax_invoice"] = is_tax_invoice

    # Items update
    target_items = items if items is not None else current_json.get("items", [])
    normalized_items = _normalize_items(target_items)

    curr_tax_rate = (
        tax_rate
        if tax_rate is not None
        else Decimal(str(current_json.get("tax", 0))) / Decimal(str(current_json.get("subtotal", 1) or 1))
    )

    totals = recalculate_invoice_totals(
        normalized_items,
        tax_rate=curr_tax_rate,
        is_tax_invoice=current_json.get("is_tax_invoice", False),
        currency=current_json.get("currency", "USD"),
    )

    current_json["items"] = [
        {
            "product_name": itm["product_name"],
            "quantity": float(itm["quantity"]),
            "unit_price": float(itm["unit_price"]),
            "discount_amount": float(itm["discount_amount"]),
            "line_total": float(itm["line_total"]),
        }
        for itm in totals["items"]
    ]
    current_json["subtotal"] = float(totals["subtotal"])
    current_json["vat"] = float(totals["vat"])
    current_json["tax"] = float(totals["tax"])
    current_json["total"] = float(totals["total"])

    draft.draft_json = current_json
    draft.state = DraftState.WAITING_FOR_CONFIRMATION.value
    draft.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(draft)
    return draft


def confirm_invoice(
    db: Session,
    draft_id: int,
    org_id: Optional[int] = None,
    force_pdf_failure: bool = False,
    force_exchange_rate_failure: bool = False,
) -> Invoice:
    """
    Commit conversational draft into a final legal invoice in an atomic database transaction:
    1. Lock per-org counter and assign sequential invoice number (INV-XXXXXX).
    2. Insert committed invoice and invoice_items records.
    3. Log 'confirmed' event in invoice_events.
    4. Resolve exchange rate (NBC API -> GDT fallback -> hard failure).
    5. Render PDF with Bakong KHQR code.
       If rendering fails: retry x1. If retry fails:
       - Transition state to PDF_FAILED
       - Set invoice.pdf_status = 'failed'
       - Log 'pdf_failed' event
       - Raise RuntimeError without leaving a silent broken invoice.
    """
    draft = db.get(Draft, draft_id)
    if not draft or (org_id is not None and draft.org_id != org_id):
        raise ValueError(f"Draft with id {draft_id} not found")

    effective_org = draft.org_id
    payload = draft.draft_json or {}
    items_data = payload.get("items", [])
    if not items_data:
        raise ValueError("Cannot confirm invoice draft with zero items")

    # 1. Assign sequential invoice number inside commit transaction using row lock
    invoice_number = assign_next_invoice_number(db, org_id=effective_org)

    subtotal = to_decimal(payload.get("subtotal", 0))
    tax = to_decimal(payload.get("tax", 0))
    total = to_decimal(payload.get("total", 0))
    curr = payload.get("currency", "USD")

    due_date_obj = None
    raw_due = payload.get("due_date")
    if raw_due:
        if isinstance(raw_due, date):
            due_date_obj = raw_due
        else:
            try:
                due_date_obj = datetime.strptime(str(raw_due)[:10], "%Y-%m-%d").date()
            except Exception:
                due_date_obj = None

    from invoicemate.services.khqr_generator import calculate_khqr_md5, generate_khqr_string
    khqr_str = generate_khqr_string(
        amount=total,
        currency=curr,
        bill_number=invoice_number,
    )
    khqr_md5 = calculate_khqr_md5(khqr_str)

    # 2. Create final committed Invoice record
    invoice = Invoice(
        org_id=effective_org,
        invoice_number=invoice_number,
        customer_id=draft.customer_id,
        subtotal=subtotal,
        tax=tax,
        total=total,
        currency=curr,
        due_date=due_date_obj,
        status=InvoiceStatus.SENT.value,
        payment_method="BAKONG_KHQR",
        khqr_md5=khqr_md5,
        pdf_status=PdfStatus.PENDING.value,
    )
    db.add(invoice)
    db.flush()

    # 3. Create items
    for itm in items_data:
        invoice.items.append(
            InvoiceItem(
                invoice_id=invoice.id,
                product_name=itm["product_name"],
                quantity=to_decimal(itm["quantity"]),
                unit_price=to_decimal(itm["unit_price"]),
                line_total=to_decimal(itm["line_total"]),
            )
        )

    # 4. Log confirmation event
    db.add(
        InvoiceEvent(
            invoice_id=invoice.id,
            event_type=EventType.CONFIRMED.value,
            detail={"draft_id": draft.id, "total": float(total), "currency": curr},
        )
    )

    draft.state = DraftState.CONFIRMED.value
    db.commit()
    db.refresh(invoice)

    # 5. Resolve official exchange rate (NBC -> GDT fallback -> hard failure)
    exchange_rate_info = None
    try:
        exchange_rate_info = resolve_exchange_rate(force_hard_failure=force_exchange_rate_failure)
    except Exception as err:
        logger.error(f"Exchange rate resolution failure for invoice {invoice.invoice_number}: {err}")
        # Transition to PDF_FAILED
        invoice.pdf_status = PdfStatus.FAILED.value
        draft.state = DraftState.PDF_FAILED.value
        db.add(
            InvoiceEvent(
                invoice_id=invoice.id,
                event_type=EventType.PDF_FAILED.value,
                detail={"error": f"Exchange rate failure: {err}"},
            )
        )
        db.commit()
        db.refresh(invoice)
        raise RuntimeError(f"Invoice generation halted: {err}")

    # 6. Render PDF with retry logic (retry x1)
    pdf_generated = False
    last_pdf_err = None

    if not force_pdf_failure:
        for attempt in range(2):  # Try initial + 1 retry
            try:
                from invoicemate.services.pdf_generator import generate_invoice_pdf
                from invoicemate.services.storage_service import get_public_pdf_url

                pdf_path = generate_invoice_pdf(
                    invoice,
                    exchange_rate_result=exchange_rate_info,
                )
                invoice.pdf_url = get_public_pdf_url(pdf_path)
                invoice.pdf_status = PdfStatus.READY.value
                draft.state = DraftState.PDF_READY.value
                pdf_generated = True
                break
            except Exception as err:
                last_pdf_err = err
                logger.warning(f"PDF rendering attempt {attempt + 1} failed for {invoice.invoice_number}: {err}")

    if not pdf_generated:
        invoice.pdf_status = PdfStatus.FAILED.value
        draft.state = DraftState.PDF_FAILED.value
        db.add(
            InvoiceEvent(
                invoice_id=invoice.id,
                event_type=EventType.PDF_FAILED.value,
                detail={"error": f"PDF rendering failure: {last_pdf_err or 'forced failure'}"},
            )
        )
        db.commit()
        db.refresh(invoice)
        raise RuntimeError(f"PDF generation failed after retry: {last_pdf_err or 'rendering failure'}")

    db.commit()
    db.refresh(invoice)
    return invoice


def mark_as_paid(
    db: Session,
    invoice_id: int,
    org_id: Optional[int] = None,
    bank_transaction_ref: Optional[str] = None,
    payment_method: Optional[str] = None,
    payment_metadata: Optional[Dict[str, Any]] = None,
    paid_at: Optional[datetime] = None,
) -> Invoice:
    """
    Mark invoice as paid strictly within org_id.
    Persists bank transaction reference, payment method, metadata, and timestamps.
    """
    invoice = db.get(Invoice, invoice_id)
    if not invoice or (org_id is not None and invoice.org_id != org_id):
        raise ValueError(f"Invoice with id {invoice_id} not found")

    if invoice.status == InvoiceStatus.CANCELLED.value:
        raise ValueError(f"Cannot mark cancelled invoice {invoice.invoice_number} as paid")

    invoice.status = InvoiceStatus.PAID.value
    invoice.paid_at = paid_at or datetime.now(timezone.utc)
    if bank_transaction_ref:
        invoice.bank_transaction_ref = bank_transaction_ref
    if payment_method:
        invoice.payment_method = payment_method
    elif not invoice.payment_method:
        invoice.payment_method = "BAKONG_KHQR"
    if payment_metadata:
        invoice.payment_metadata = payment_metadata

    event_detail: Dict[str, Any] = {
        "paid_at": invoice.paid_at.isoformat(),
        "payment_method": invoice.payment_method,
    }
    if invoice.bank_transaction_ref:
        event_detail["bank_transaction_ref"] = invoice.bank_transaction_ref

    db.add(
        InvoiceEvent(
            invoice_id=invoice.id,
            event_type=EventType.MARKED_PAID.value,
            detail=event_detail,
        )
    )

    db.commit()
    db.refresh(invoice)
    return invoice


def cancel_draft(db: Session, draft_id: int, org_id: Optional[int] = None) -> Draft:
    """Cancel an active draft session."""
    draft = db.get(Draft, draft_id)
    if not draft or (org_id is not None and draft.org_id != org_id):
        raise ValueError(f"Draft with id {draft_id} not found")

    draft.state = DraftState.IDLE.value
    db.commit()
    db.refresh(draft)
    return draft


def cancel_invoice(db: Session, invoice_id: int, org_id: Optional[int] = None) -> Invoice:
    """Cancel committed invoice."""
    invoice = db.get(Invoice, invoice_id)
    if not invoice or (org_id is not None and invoice.org_id != org_id):
        raise ValueError(f"Invoice with id {invoice_id} not found")

    invoice.status = InvoiceStatus.CANCELLED.value
    db.commit()
    db.refresh(invoice)
    return invoice


def search_invoices(
    db: Session,
    org_id: int = 1,
    query: Optional[str] = None,
    customer_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 20,
) -> List[Invoice]:
    """
    Deterministic org-scoped search engine for invoices.
    Searches across invoice numbers, customer names, and product names.
    """
    stmt = (
        select(Invoice)
        .outerjoin(Customer)
        .outerjoin(InvoiceItem)
        .where(Invoice.org_id == org_id)
    )

    filters = []
    if status:
        filters.append(Invoice.status == status.lower())
    if customer_id:
        filters.append(Invoice.customer_id == customer_id)

    if query and query.strip():
        q = f"%{query.strip().lower()}%"
        filters.append(
            or_(
                func.lower(Invoice.invoice_number).like(q),
                func.lower(Customer.name).like(q),
                func.lower(InvoiceItem.product_name).like(q),
            )
        )

    if filters:
        stmt = stmt.where(*filters)

    stmt = stmt.distinct().order_by(Invoice.created_at.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def get_invoice_history(
    db: Session,
    org_id: int = 1,
    timeframe: str = "all",
    status: Optional[str] = None,
    customer_id: Optional[int] = None,
    limit: int = 20,
) -> List[Invoice]:
    """
    Fetch org-scoped invoice history with timeframe filtering ('today', 'this_week', 'this_month', 'all').
    """
    from datetime import timedelta

    stmt = select(Invoice).outerjoin(Customer).where(Invoice.org_id == org_id)
    filters = []

    now = datetime.now()

    if timeframe == "today":
        start_of_day = datetime(now.year, now.month, now.day, 0, 0, 0)
        filters.append(Invoice.created_at >= start_of_day)
    elif timeframe == "this_week":
        start_of_week = now - timedelta(days=now.weekday())
        start_of_week = datetime(start_of_week.year, start_of_week.month, start_of_week.day, 0, 0, 0)
        filters.append(Invoice.created_at >= start_of_week)
    elif timeframe == "this_month":
        start_of_month = datetime(now.year, now.month, 1, 0, 0, 0)
        filters.append(Invoice.created_at >= start_of_month)

    if status:
        filters.append(Invoice.status == status.lower())
    if customer_id:
        filters.append(Invoice.customer_id == customer_id)

    if filters:
        stmt = stmt.where(*filters)

    stmt = stmt.distinct().order_by(Invoice.created_at.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def get_invoice_by_id(db: Session, invoice_id: int, org_id: Optional[int] = None) -> Optional[Invoice]:
    """Fetch invoice by primary key ID, strictly scoped to org_id if provided."""
    inv = db.get(Invoice, invoice_id)
    if inv and org_id is not None and inv.org_id != org_id:
        return None
    return inv


def get_invoice_by_number(db: Session, invoice_number: str, org_id: Optional[int] = None) -> Optional[Invoice]:
    """Fetch invoice by invoice number, strictly scoped to org_id if provided."""
    stmt = select(Invoice).where(Invoice.invoice_number == invoice_number.strip())
    if org_id is not None:
        stmt = stmt.where(Invoice.org_id == org_id)
    return db.scalars(stmt).first()
