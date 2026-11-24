from decimal import Decimal
from invoicemate.models.customer import Customer
from invoicemate.models.invoice import Invoice
from invoicemate.models.invoice_item import InvoiceItem
from invoicemate.models.enums import InvoiceStatus
from invoicemate.services.export_service import export_invoices_to_csv
from invoicemate.services.exchange_rate_service import ExchangeRateResult


def test_export_invoices_to_csv_empty():
    csv_out = export_invoices_to_csv([])
    lines = csv_out.strip().splitlines()
    assert len(lines) == 1
    assert "Invoice Number" in lines[0]
    assert "Total (KHR)" in lines[0]


def test_export_invoices_to_csv_data():
    rate_info = ExchangeRateResult(rate=Decimal("4100"), source="NBC", bulletin_date="2026-10-01")
    customer = Customer(org_id=1, name="Angkor Tech Co.", phone="+85512345678")

    inv1 = Invoice(
        org_id=1,
        invoice_number="INV-000101",
        customer=customer,
        subtotal=Decimal("100.00"),
        tax=Decimal("10.00"),
        total=Decimal("110.00"),
        currency="USD",
        status=InvoiceStatus.PAID.value,
        payment_method="BAKONG_KHQR",
        bank_transaction_ref="TRX-123456",
        items=[InvoiceItem(product_name="Consulting", quantity=Decimal("1"), unit_price=Decimal("100.00"), line_total=Decimal("100.00"))],
    )

    inv2 = Invoice(
        org_id=1,
        invoice_number="INV-000102",
        customer=customer,
        subtotal=Decimal("400000"),
        tax=Decimal("0"),
        total=Decimal("400000"),
        currency="KHR",
        status=InvoiceStatus.SENT.value,
        payment_method="BAKONG_KHQR",
        items=[InvoiceItem(product_name="Equipment", quantity=Decimal("1"), unit_price=Decimal("400000"), line_total=Decimal("400000"))],
    )

    csv_out = export_invoices_to_csv([inv1, inv2], exchange_rate_result=rate_info)
    lines = csv_out.strip().splitlines()
    assert len(lines) == 3

    # Check headers
    headers = lines[0].split(",")
    assert "Invoice Number" in headers
    assert "Customer Name" in headers
    assert "Total (KHR)" in headers

    # Check row 1 (USD)
    row1 = lines[1]
    assert "INV-000101" in row1
    assert "Angkor Tech Co." in row1
    assert "USD" in row1
    assert "451,000" in row1  # 110 * 4100 = 451,000 KHR
    assert "PAID" in row1
    assert "TRX-123456" in row1

    # Check row 2 (KHR)
    row2 = lines[2]
    assert "INV-000102" in row2
    assert "KHR" in row2
    assert "400,000" in row2
    assert "SENT" in row2
