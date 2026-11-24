from decimal import Decimal
import pytest
from invoicemate.schemas.customer import CustomerCreate, CustomerUpdate
from invoicemate.models.invoice import Invoice
from invoicemate.models.enums import InvoiceStatus
from invoicemate.services.org_service import create_org
from invoicemate.services.customer_service import (
    create_customer,
    find_customers_by_name,
    get_customer_by_exact_name,
    get_or_create_customer,
    resolve_customer_name,
    update_customer,
    get_customer_invoices,
    get_customer_metrics,
)


def test_create_and_find_customer(db_session):
    org = create_org(db_session, telegram_user_id="tg_cust_test1")
    cust_in = CustomerCreate(name="Bopha Mart", phone="+85512000111", default_currency="USD")
    cust = create_customer(db_session, org_id=org.id, customer_in=cust_in)
    assert cust.id is not None
    assert cust.org_id == org.id
    assert cust.name == "Bopha Mart"

    results = find_customers_by_name(db_session, org_id=org.id, name_query="bopha")
    assert len(results) == 1
    assert results[0].id == cust.id


def test_get_or_create_customer(db_session):
    org = create_org(db_session, telegram_user_id="tg_cust_test2")
    c1 = get_or_create_customer(db_session, org_id=org.id, name="Kravanh Co")
    assert c1.id is not None
    assert c1.org_id == org.id

    c2 = get_or_create_customer(db_session, org_id=org.id, name="Kravanh Co")
    assert c2.id == c1.id


def test_resolve_customer_name_ambiguity(db_session):
    org = create_org(db_session, telegram_user_id="tg_cust_test3")
    c1 = create_customer(db_session, org_id=org.id, customer_in=CustomerCreate(name="Sokha Computer Shop"))
    c2 = create_customer(db_session, org_id=org.id, customer_in=CustomerCreate(name="Sokha Telecom"))

    # Exact match -> resolved directly
    resolved, matches = resolve_customer_name(db_session, org_id=org.id, name_query="Sokha Computer Shop")
    assert resolved is not None
    assert resolved.id == c1.id
    assert len(matches) == 0

    # Partial query matching multiple -> disambiguation returned
    resolved_multi, matches_multi = resolve_customer_name(db_session, org_id=org.id, name_query="Sokha")
    assert resolved_multi is None
    assert len(matches_multi) == 2


def test_update_customer(db_session):
    org = create_org(db_session, telegram_user_id="tg_cust_update_test")
    cust = create_customer(db_session, org_id=org.id, customer_in=CustomerCreate(name="Old Name", phone="+85512111222", default_currency="USD"))

    # Update phone and currency
    update_in = CustomerUpdate(name="New Name", phone="+85599000111", default_currency="KHR")
    updated = update_customer(db_session, customer_id=cust.id, org_id=org.id, customer_in=update_in)
    assert updated.name == "New Name"
    assert updated.phone == "+85599000111"
    assert updated.default_currency == "KHR"

    # Non-existent customer raises ValueError
    with pytest.raises(ValueError, match="not found"):
        update_customer(db_session, customer_id=99999, org_id=org.id, customer_in=update_in)


def test_get_customer_invoices_and_metrics(db_session):
    org = create_org(db_session, telegram_user_id="tg_cust_metrics_test")
    cust = create_customer(db_session, org_id=org.id, customer_in=CustomerCreate(name="Vibol Transport", default_currency="USD"))

    inv1 = Invoice(
        org_id=org.id,
        invoice_number="INV-007701",
        customer_id=cust.id,
        subtotal=Decimal("250.00"),
        tax=Decimal("0.00"),
        total=Decimal("250.00"),
        currency="USD",
        status=InvoiceStatus.PAID.value,
        items=[],
    )
    inv2 = Invoice(
        org_id=org.id,
        invoice_number="INV-007702",
        customer_id=cust.id,
        subtotal=Decimal("150.00"),
        tax=Decimal("0.00"),
        total=Decimal("150.00"),
        currency="USD",
        status=InvoiceStatus.SENT.value,
        items=[],
    )
    db_session.add_all([inv1, inv2])
    db_session.commit()

    invoices = get_customer_invoices(db_session, customer_id=cust.id, org_id=org.id)
    assert len(invoices) == 2

    paid_only = get_customer_invoices(db_session, customer_id=cust.id, org_id=org.id, status="paid")
    assert len(paid_only) == 1
    assert paid_only[0].invoice_number == "INV-007701"

    metrics = get_customer_metrics(db_session, customer_id=cust.id, org_id=org.id)
    assert metrics["customer_name"] == "Vibol Transport"
    assert metrics["total_invoices"] == 2
    assert metrics["paid_count"] == 1
    assert metrics["sent_count"] == 1
    assert metrics["total_paid_by_currency"]["USD"] == 250.00
    assert metrics["total_outstanding_by_currency"]["USD"] == 150.00

