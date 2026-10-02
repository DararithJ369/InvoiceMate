from decimal import Decimal
import pytest

from invoicemate.models.enums import InvoiceStatus, DraftState
from invoicemate.services.org_service import create_org
from invoicemate.services.invoice_engine import (
    create_draft,
    update_draft,
    confirm_invoice,
    mark_as_paid,
    cancel_draft,
    cancel_invoice,
    search_invoices,
    get_invoice_by_id,
    get_invoice_by_number,
)


def test_create_draft_invoice(db_session):
    org = create_org(db_session, telegram_user_id="tg_eng_test1")
    items = [
        {"product_name": "Laptop Stand", "quantity": 2, "unit_price": 25.00},
        {"product_name": "USB-C Cable", "quantity": 1, "unit_price": 10.00},
    ]

    draft = create_draft(
        db_session,
        items=items,
        org_id=org.id,
        customer_name="Sokha Computer",
        currency="USD",
    )

    assert draft.id is not None
    assert draft.org_id == org.id
    assert draft.state == DraftState.WAITING_FOR_CONFIRMATION.value
    assert draft.draft_json["subtotal"] == 60.00
    assert draft.draft_json["total"] == 60.00
    assert len(draft.draft_json["items"]) == 2
    assert draft.customer.name == "Sokha Computer"


def test_create_draft_invalid_items(db_session):
    org = create_org(db_session, telegram_user_id="tg_eng_test2")
    with pytest.raises(ValueError, match="at least one item"):
        create_draft(db_session, items=[], org_id=org.id, customer_name="Test")

    with pytest.raises(ValueError, match="greater than 0"):
        create_draft(
            db_session,
            items=[{"product_name": "Item A", "quantity": 0, "unit_price": 10}],
            org_id=org.id,
            customer_name="Test",
        )


def test_update_draft_invoice(db_session):
    org = create_org(db_session, telegram_user_id="tg_eng_test3")
    items = [{"product_name": "Web Hosting", "quantity": 1, "unit_price": 100.00}]
    draft = create_draft(db_session, items=items, org_id=org.id, customer_name="Dara Store")

    updated_items = [
        {"product_name": "Web Hosting", "quantity": 1, "unit_price": 100.00},
        {"product_name": "Domain Name", "quantity": 2, "unit_price": 15.00},
    ]

    updated = update_draft(db_session, draft_id=draft.id, org_id=org.id, items=updated_items)

    assert updated.draft_json["subtotal"] == 130.00
    assert updated.draft_json["total"] == 130.00
    assert len(updated.draft_json["items"]) == 2


def test_cannot_update_confirmed_draft(db_session):
    org = create_org(db_session, telegram_user_id="tg_eng_test4")
    items = [{"product_name": "Item A", "quantity": 1, "unit_price": 50.00}]
    draft = create_draft(db_session, items=items, org_id=org.id, customer_name="Vandy")

    confirmed = confirm_invoice(db_session, draft_id=draft.id, org_id=org.id)
    assert confirmed.status == InvoiceStatus.SENT.value

    with pytest.raises(ValueError, match="Cannot update draft"):
        update_draft(
            db_session,
            draft_id=draft.id,
            org_id=org.id,
            items=[{"product_name": "New Item", "quantity": 1, "unit_price": 100.00}],
        )


def test_confirm_and_pay_invoice(db_session):
    org = create_org(db_session, telegram_user_id="tg_eng_test5")
    items = [{"product_name": "Consulting", "quantity": 5, "unit_price": 40.00}]
    draft = create_draft(db_session, items=items, org_id=org.id, customer_name="Sophea")

    # Confirm draft -> committed Invoice with status SENT
    sent_inv = confirm_invoice(db_session, draft_id=draft.id, org_id=org.id)
    assert sent_inv.status == InvoiceStatus.SENT.value
    assert sent_inv.invoice_number == "INV-000001"

    # Mark as paid
    paid_inv = mark_as_paid(db_session, sent_inv.id, org_id=org.id)
    assert paid_inv.status == InvoiceStatus.PAID.value


def test_search_invoices(db_session):
    org = create_org(db_session, telegram_user_id="tg_eng_test6")
    draft1 = create_draft(
        db_session,
        org_id=org.id,
        items=[{"product_name": "Coffee Beans Bag", "quantity": 5, "unit_price": 10}],
        customer_name="Bopha Coffee",
    )
    draft2 = create_draft(
        db_session,
        org_id=org.id,
        items=[{"product_name": "Espresso Machine", "quantity": 1, "unit_price": 500}],
        customer_name="Rithy Roasters",
    )

    inv1 = confirm_invoice(db_session, draft_id=draft1.id, org_id=org.id)
    inv2 = confirm_invoice(db_session, draft_id=draft2.id, org_id=org.id)

    # Search by customer name
    bopha_res = search_invoices(db_session, org_id=org.id, query="Bopha")
    assert len(bopha_res) == 1
    assert bopha_res[0].id == inv1.id

    # Search by product name
    espresso_res = search_invoices(db_session, org_id=org.id, query="espresso")
    assert len(espresso_res) == 1
    assert espresso_res[0].id == inv2.id

    # Search by status
    sent_res = search_invoices(db_session, org_id=org.id, status="sent")
    assert len(sent_res) == 2

    # Get by number
    by_num = get_invoice_by_number(db_session, inv1.invoice_number, org_id=org.id)
    assert by_num.id == inv1.id
