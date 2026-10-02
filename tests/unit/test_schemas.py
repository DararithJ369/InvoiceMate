from decimal import Decimal
from invoicemate.schemas.customer import CustomerCreate, CustomerRead
from invoicemate.schemas.invoice import InvoiceCreate, InvoiceItemCreate


def test_customer_schemas():
    data = CustomerCreate(name="Bopha Mart", phone="+85512000111", default_currency="USD")
    assert data.name == "Bopha Mart"
    assert data.default_currency == "USD"


def test_invoice_schemas():
    item = InvoiceItemCreate(product_name="Coffee Beans", quantity=Decimal("2"), unit_price=Decimal("15.00"))
    inv = InvoiceCreate(customer_id=1, items=[item], currency="USD")

    assert len(inv.items) == 1
    assert inv.items[0].product_name == "Coffee Beans"
    assert inv.items[0].quantity == Decimal("2")
