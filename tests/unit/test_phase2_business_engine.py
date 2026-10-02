from datetime import date
from decimal import Decimal
import pytest

from invoicemate.models.enums import InvoiceStatus, DraftState, PdfStatus, EventType
from invoicemate.models.invoice_event import InvoiceEvent
from invoicemate.services.org_service import create_org
from invoicemate.services.calculator import (
    calculate_line_total,
    calculate_subtotal,
    calculate_vat,
    calculate_plt,
    calculate_accommodation_tax,
    calculate_withholding_tax_notation,
    recalculate_invoice_totals,
)
from invoicemate.services.exchange_rate_service import (
    resolve_exchange_rate,
    fetch_nbc_exchange_rate,
    get_gdt_fallback_rate,
    ExchangeRateResult,
)
from invoicemate.services.invoice_engine import (
    create_draft,
    update_draft,
    confirm_invoice,
    mark_as_paid,
    cancel_draft,
    search_invoices,
    get_invoice_history,
)


def test_prakas723_tax_calculation_and_discounts():
    """
    Phase 2 Validation:
    Verify net subtotals after item discounts, explicit 10% VAT, PLT 5%, and WHT notation.
    """
    items = [
        {"name": "Dell Monitor", "qty": 2, "price": 450.00, "discount": 50.00},  # 900 - 50 = 850
        {"name": "Mechanical Keyboard", "qty": 1, "price": 100.00, "discount": 10.00},  # 100 - 10 = 90
    ]

    totals = recalculate_invoice_totals(
        items,
        is_tax_invoice=True,
        apply_plt=True,
        withholding_tax_rate="0.15",
        exchange_rate="4085",
        currency="USD",
    )

    # Net taxable subtotal = 850 + 90 = 940.00
    assert totals["subtotal"] == Decimal("940.00")
    # VAT (10%) = 94.00
    assert totals["vat"] == Decimal("94.00")
    # PLT (5%) = 47.00
    assert totals["plt"] == Decimal("47.00")
    # Total Tax = 94 + 47 = 141.00
    assert totals["tax"] == Decimal("141.00")
    # Grand Total (USD) = 940 + 141 = 1081.00
    assert totals["total"] == Decimal("1081.00")
    # Dual-Currency Grand Total (KHR) = 1,081 * 4,085 = 4,415,885 KHR
    assert totals["total_khr"] == Decimal("4415885")

    # Withholding tax notation: informational only, not deducted from supplier total
    wht = totals["withholding_tax_notation"]
    assert wht is not None
    assert wht["estimated_withheld_amount"] == Decimal("141.00")  # 15% of 940
    assert wht["is_deducted_from_total"] is False


def test_exchange_rate_fallback_hierarchy():
    """Verify NBC primary query, GDT local fallback, and hard failure mode."""
    # 1. Mock NBC daily rate
    mock_res = resolve_exchange_rate(mock_nbc_rate=Decimal("4090"))
    assert mock_res.rate == Decimal("4090")
    assert "NBC" in mock_res.source

    # 2. Force fallback to GDT rate
    fallback_res = get_gdt_fallback_rate()
    assert fallback_res.rate == Decimal("4085")
    assert "GDT" in fallback_res.source

    # 3. Hard failure mode
    with pytest.raises(RuntimeError, match="both NBC API and GDT fallback are unavailable"):
        resolve_exchange_rate(force_hard_failure=True)


def test_create_and_update_draft_patch(db_session):
    """Verify creating a draft and partial JSON patching during revisions."""
    org = create_org(db_session, telegram_user_id="tg_draft_test")
    items = [{"name": "Web Hosting", "qty": 1, "price": 100.00}]

    draft = create_draft(
        db_session,
        items=items,
        org_id=org.id,
        chat_id="chat_12345",
        customer_name="Dara Store",
        currency="USD",
    )

    assert draft.id is not None
    assert draft.org_id == org.id
    assert draft.state == DraftState.WAITING_FOR_CONFIRMATION.value
    assert draft.draft_json["subtotal"] == 100.00

    # User textual revision: add domain name for $15
    updated_items = [
        {"name": "Web Hosting", "qty": 1, "price": 100.00},
        {"name": "Domain Name", "qty": 2, "price": 15.00},
    ]

    updated = update_draft(
        db_session,
        draft_id=draft.id,
        org_id=org.id,
        items=updated_items,
    )

    assert updated.draft_json["subtotal"] == 130.00
    assert len(updated.draft_json["items"]) == 2


def test_confirm_invoice_success_and_events(db_session):
    """Verify committing draft assigns sequential number, generates PDF, and logs events."""
    org = create_org(db_session, telegram_user_id="tg_confirm_test")
    items = [{"name": "Solar Panel", "qty": 4, "price": 120.00}]

    draft = create_draft(
        db_session,
        items=items,
        org_id=org.id,
        chat_id="chat_777",
        customer_name="Siem Reap Green",
    )

    invoice = confirm_invoice(db_session, draft_id=draft.id, org_id=org.id)

    assert invoice.id is not None
    assert invoice.invoice_number == "INV-000001"
    assert invoice.status == InvoiceStatus.SENT.value
    assert invoice.pdf_status == PdfStatus.READY.value
    assert invoice.pdf_url is not None
    assert len(invoice.items) == 1

    # Check invoice events audit trail
    events = db_session.query(InvoiceEvent).filter_by(invoice_id=invoice.id).all()
    event_types = [e.event_type for e in events]
    assert EventType.CONFIRMED.value in event_types

    # Mark as paid
    paid_inv = mark_as_paid(db_session, invoice_id=invoice.id, org_id=org.id)
    assert paid_inv.status == InvoiceStatus.PAID.value
    assert paid_inv.paid_at is not None


def test_confirm_invoice_pdf_failure_transition(db_session):
    """
    Phase 2 Validation:
    Verify that when PDF rendering fails after retry, state transitions to PDF_FAILED,
    pdf_status is marked 'failed', and an event is logged (no silent unrendered invoices).
    """
    org = create_org(db_session, telegram_user_id="tg_fail_test")
    items = [{"name": "Cloud Storage 1TB", "qty": 1, "price": 50.00}]

    draft = create_draft(
        db_session,
        items=items,
        org_id=org.id,
        chat_id="chat_888",
        customer_name="Fail Test Corp",
    )

    # Force PDF rendering failure
    with pytest.raises(RuntimeError, match="PDF generation failed after retry"):
        confirm_invoice(db_session, draft_id=draft.id, org_id=org.id, force_pdf_failure=True)

    db_session.refresh(draft)
    assert draft.state == DraftState.PDF_FAILED.value

    # Check that failed event was logged
    event = db_session.query(InvoiceEvent).filter_by(event_type=EventType.PDF_FAILED.value).first()
    assert event is not None
