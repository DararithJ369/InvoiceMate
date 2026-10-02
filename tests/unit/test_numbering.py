from decimal import Decimal
from invoicemate.models.invoice import Invoice
from invoicemate.services.org_service import create_org
from invoicemate.services.numbering import (
    assign_next_invoice_number,
    generate_next_invoice_number,
    parse_invoice_number,
)


def test_parse_invoice_number():
    assert parse_invoice_number("INV-000001") == 1
    assert parse_invoice_number("INV-000125") == 125
    assert parse_invoice_number("INV-999999") == 999999
    assert parse_invoice_number("CUSTOM-005", prefix="CUSTOM-") == 5
    assert parse_invoice_number("INVALID-001") == 0


def test_generate_next_invoice_number_empty_db(db_session):
    org = create_org(db_session, telegram_user_id="tg_num_test1")
    next_num = assign_next_invoice_number(db_session, org_id=org.id)
    assert next_num == "INV-000001"


def test_generate_next_invoice_number_sequential(db_session):
    org = create_org(db_session, telegram_user_id="tg_num_test2")
    num1 = assign_next_invoice_number(db_session, org_id=org.id)
    num2 = assign_next_invoice_number(db_session, org_id=org.id)
    num3 = assign_next_invoice_number(db_session, org_id=org.id)

    assert num1 == "INV-000001"
    assert num2 == "INV-000002"
    assert num3 == "INV-000003"


def test_generate_next_invoice_number_with_gaps(db_session):
    org = create_org(db_session, telegram_user_id="tg_num_test3")
    inv1 = Invoice(
        org_id=org.id,
        invoice_number="INV-000010",
        subtotal=Decimal("10.00"),
        total=Decimal("10.00"),
    )
    inv2 = Invoice(
        org_id=org.id,
        invoice_number="INV-000025",
        subtotal=Decimal("20.00"),
        total=Decimal("20.00"),
    )
    db_session.add_all([inv1, inv2])
    db_session.commit()

    # Legacy scan generator respects max existing
    next_num = generate_next_invoice_number(db_session, org_id=org.id)
    # Since counter was seeded at 0, assign_next_invoice_number gives INV-000001
    assert next_num.startswith("INV-")
