from datetime import datetime, timedelta
from decimal import Decimal
from invoicemate.models.enums import InvoiceStatus
from invoicemate.services.org_service import create_org
from invoicemate.services.invoice_engine import (
    create_draft,
    confirm_invoice,
    mark_as_paid,
    get_invoice_history,
    search_invoices,
)


def test_get_invoice_history_timeframe_filtering(db_session):
    org = create_org(db_session, telegram_user_id="tg_hist_test1")
    draft1 = create_draft(
        db_session,
        org_id=org.id,
        items=[{"product_name": "Consulting", "quantity": 1, "unit_price": 100}],
        customer_name="Sokha",
    )
    inv1 = confirm_invoice(db_session, draft_id=draft1.id, org_id=org.id)

    # Fetch history today
    today_invoices = get_invoice_history(db_session, org_id=org.id, timeframe="today")
    assert len(today_invoices) >= 1
    assert today_invoices[0].id == inv1.id

    # Fetch history this week
    week_invoices = get_invoice_history(db_session, org_id=org.id, timeframe="this_week")
    assert len(week_invoices) >= 1


def test_manual_status_toggle_paid(db_session):
    org = create_org(db_session, telegram_user_id="tg_hist_test2")
    draft = create_draft(
        db_session,
        org_id=org.id,
        items=[{"product_name": "Logo Design", "quantity": 1, "unit_price": 250}],
        customer_name="Dara",
    )
    inv = confirm_invoice(db_session, draft_id=draft.id, org_id=org.id)

    # Mark as paid
    paid_inv = mark_as_paid(db_session, invoice_id=inv.id, org_id=org.id)
    assert paid_inv.status == InvoiceStatus.PAID.value


def test_search_history_queries(db_session):
    org = create_org(db_session, telegram_user_id="tg_hist_test3")
    draft1 = create_draft(
        db_session,
        org_id=org.id,
        items=[{"product_name": "Office Chair", "quantity": 2, "unit_price": 80}],
        customer_name="Bopha Coffee",
    )
    inv1 = confirm_invoice(db_session, draft_id=draft1.id, org_id=org.id)

    results = search_invoices(db_session, org_id=org.id, query="Chair")
    assert len(results) == 1
    assert results[0].id == inv1.id
