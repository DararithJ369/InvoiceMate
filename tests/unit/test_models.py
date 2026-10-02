from datetime import date
from decimal import Decimal
import pytest
from invoicemate.models.org import Org
from invoicemate.models.customer import Customer
from invoicemate.models.invoice import Invoice
from invoicemate.models.invoice_item import InvoiceItem
from invoicemate.models.enums import InvoiceStatus
from invoicemate.services.org_service import create_org


def test_create_customer(db_session):
    org = create_org(db_session, telegram_user_id="tg_mod_test1")
    customer = Customer(
        org_id=org.id,
        name="Thida Store",
        phone="+85512999888",
        telegram_id="123456789",
        default_currency="USD",
    )
    db_session.add(customer)
    db_session.commit()

    assert customer.id is not None
    assert customer.org_id == org.id
    assert customer.name == "Thida Store"
    assert customer.default_currency == "USD"
    assert "Thida Store" in repr(customer)


def test_create_invoice_with_items(db_session):
    org = create_org(db_session, telegram_user_id="tg_mod_test2")
    customer = Customer(org_id=org.id, name="Chanda Trading")
    db_session.add(customer)
    db_session.commit()

    invoice = Invoice(
        org_id=org.id,
        invoice_number="INV-000001",
        customer_id=customer.id,
        subtotal=Decimal("150.00"),
        tax=Decimal("15.00"),
        total=Decimal("165.00"),
        currency="USD",
        due_date=date(2026, 8, 15),
        status=InvoiceStatus.SENT.value,
    )
    db_session.add(invoice)
    db_session.commit()

    item1 = InvoiceItem(
        invoice_id=invoice.id,
        product_name="Product A",
        quantity=Decimal("2.00"),
        unit_price=Decimal("50.00"),
        line_total=Decimal("100.00"),
    )
    item2 = InvoiceItem(
        invoice_id=invoice.id,
        product_name="Product B",
        quantity=Decimal("1.00"),
        unit_price=Decimal("50.00"),
        line_total=Decimal("50.00"),
    )
    db_session.add_all([item1, item2])
    db_session.commit()

    db_session.refresh(invoice)
    assert len(invoice.items) == 2
    assert invoice.customer.name == "Chanda Trading"
    assert invoice.total == Decimal("165.00")
    assert invoice.status == "sent"


def test_cascade_delete_invoice_deletes_items(db_session):
    org = create_org(db_session, telegram_user_id="tg_mod_test3")
    customer = Customer(org_id=org.id, name="Test Customer")
    db_session.add(customer)
    db_session.commit()

    invoice = Invoice(
        org_id=org.id,
        invoice_number="INV-000002",
        customer_id=customer.id,
        subtotal=Decimal("50.00"),
        tax=Decimal("0.00"),
        total=Decimal("50.00"),
    )
    db_session.add(invoice)
    db_session.commit()

    item = InvoiceItem(
        invoice_id=invoice.id,
        product_name="Item 1",
        quantity=Decimal("1.00"),
        unit_price=Decimal("50.00"),
        line_total=Decimal("50.00"),
    )
    db_session.add(item)
    db_session.commit()

    db_session.delete(invoice)
    db_session.commit()

    assert db_session.query(InvoiceItem).filter_by(invoice_id=invoice.id).count() == 0
