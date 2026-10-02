from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session

from invoicemate.models.org import Org
from invoicemate.models.customer import Customer
from invoicemate.models.invoice import Invoice
from invoicemate.models.invoice_item import InvoiceItem
from invoicemate.models.enums import InvoiceStatus
from invoicemate.services.org_service import get_or_create_org
from invoicemate.services.calculator import calculate_line_total, calculate_subtotal, calculate_total
from invoicemate.services.numbering import assign_next_invoice_number


def seed_database(db: Session, telegram_user_id: str = "seed_admin") -> dict:
    """
    Seed sample organization, customers, and invoices into database for development and testing.
    Returns dict containing created records count.
    """
    existing_customers_count = db.query(Customer).count()
    if existing_customers_count > 0:
        return {"status": "skipped", "message": "Database already contains seed data"}

    org = get_or_create_org(
        db,
        telegram_user_id=telegram_user_id,
        business_name="Phnom Penh Enterprises",
        phone="+85512000000",
    )

    customers = [
        Customer(
            org_id=org.id,
            name="Sokha Computer Shop",
            phone="+85512345678",
            telegram_id="tg_1001",
            default_currency="USD",
        ),
        Customer(
            org_id=org.id,
            name="Dara Tech Solutions",
            phone="+85598765432",
            telegram_id="tg_1002",
            default_currency="USD",
        ),
        Customer(
            org_id=org.id,
            name="Bopha Coffee & Bakery",
            phone="+85588776655",
            telegram_id="tg_1003",
            default_currency="USD",
        ),
        Customer(
            org_id=org.id,
            name="Vandy Logistics",
            phone="+85511223344",
            telegram_id="tg_1004",
            default_currency="KHR",
        ),
    ]
    db.add_all(customers)
    db.commit()

    sokha = db.query(Customer).filter_by(org_id=org.id, name="Sokha Computer Shop").first()
    dara = db.query(Customer).filter_by(org_id=org.id, name="Dara Tech Solutions").first()
    bopha = db.query(Customer).filter_by(org_id=org.id, name="Bopha Coffee & Bakery").first()

    today = date.today()

    # Invoice 1
    inv1_num = assign_next_invoice_number(db, org_id=org.id)
    item1_1_qty, item1_1_price = Decimal("2.00"), Decimal("450.00")
    line1_1 = calculate_line_total(item1_1_qty, item1_1_price)

    item1_2_qty, item1_2_price = Decimal("1.00"), Decimal("25.00")
    line1_2 = calculate_line_total(item1_2_qty, item1_2_price)

    subtotal1 = calculate_subtotal([line1_1, line1_2])
    tax1 = Decimal("0.00")
    total1 = calculate_total(subtotal1, tax1)

    inv1 = Invoice(
        org_id=org.id,
        invoice_number=inv1_num,
        customer_id=sokha.id,
        subtotal=subtotal1,
        tax=tax1,
        total=total1,
        currency="USD",
        due_date=today + timedelta(days=14),
        status=InvoiceStatus.SENT.value,
        items=[
            InvoiceItem(
                product_name="Dell 24-inch Monitor",
                quantity=item1_1_qty,
                unit_price=item1_1_price,
                line_total=line1_1,
            ),
            InvoiceItem(
                product_name="Wireless Keyboard & Mouse Combo",
                quantity=item1_2_qty,
                unit_price=item1_2_price,
                line_total=line1_2,
            ),
        ],
    )
    db.add(inv1)
    db.commit()

    # Invoice 2
    inv2_num = assign_next_invoice_number(db, org_id=org.id)
    item2_1_qty, item2_1_price = Decimal("10.00"), Decimal("75.00")
    line2_1 = calculate_line_total(item2_1_qty, item2_1_price)

    subtotal2 = calculate_subtotal([line2_1])
    tax2 = Decimal("0.00")
    total2 = calculate_total(subtotal2, tax2)

    inv2 = Invoice(
        org_id=org.id,
        invoice_number=inv2_num,
        customer_id=dara.id,
        subtotal=subtotal2,
        tax=tax2,
        total=total2,
        currency="USD",
        due_date=today + timedelta(days=7),
        status=InvoiceStatus.PAID.value,
        items=[
            InvoiceItem(
                product_name="Web Development Consulting (Hours)",
                quantity=item2_1_qty,
                unit_price=item2_1_price,
                line_total=line2_1,
            ),
        ],
    )
    db.add(inv2)
    db.commit()

    # Invoice 3
    inv3_num = assign_next_invoice_number(db, org_id=org.id)
    item3_1_qty, item3_1_price = Decimal("5.00"), Decimal("12.00")
    line3_1 = calculate_line_total(item3_1_qty, item3_1_price)

    subtotal3 = calculate_subtotal([line3_1])
    tax3 = Decimal("0.00")
    total3 = calculate_total(subtotal3, tax3)

    inv3 = Invoice(
        org_id=org.id,
        invoice_number=inv3_num,
        customer_id=bopha.id,
        subtotal=subtotal3,
        tax=tax3,
        total=total3,
        currency="USD",
        due_date=today + timedelta(days=30),
        status=InvoiceStatus.SENT.value,
        items=[
            InvoiceItem(
                product_name="Specialty Coffee Beans (1kg bag)",
                quantity=item3_1_qty,
                unit_price=item3_1_price,
                line_total=line3_1,
            ),
        ],
    )
    db.add(inv3)
    db.commit()

    return {
        "status": "success",
        "org_id": org.id,
        "customers_count": len(customers),
        "invoices_count": 3,
    }
