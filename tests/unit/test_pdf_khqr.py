import os
from decimal import Decimal
from invoicemate.models.customer import Customer
from invoicemate.models.invoice import Invoice
from invoicemate.models.invoice_item import InvoiceItem
from invoicemate.models.enums import InvoiceStatus
from invoicemate.services.khqr_generator import generate_khqr_string, generate_khqr_image
from invoicemate.services.pdf_generator import generate_invoice_pdf


def test_generate_khqr_string():
    khqr = generate_khqr_string(
        merchant_name="Sokha Store",
        amount=Decimal("450.00"),
        currency="USD",
        bill_number="INV-000001",
    )
    assert khqr.startswith("000201")
    assert "840" in khqr  # USD currency code
    assert "450.00" in khqr
    assert len(khqr) > 50


def test_generate_khqr_image():
    khqr = "00020101021229190017invoicemate@bakong5204599953038405406450.005802KH5911Sokha Store6010Phnom Penh6304"
    img_path = generate_khqr_image(khqr, output_path="./storage/test_qr.png")
    assert os.path.exists(img_path)
    assert img_path.endswith(".png")


def test_generate_invoice_pdf():
    customer = Customer(org_id=1, name="Dara Tech Solutions", phone="+85512345678")
    invoice = Invoice(
        org_id=1,
        invoice_number="INV-000099",
        customer=customer,
        subtotal=Decimal("750.00"),
        tax=Decimal("0.00"),
        total=Decimal("750.00"),
        currency="USD",
        status=InvoiceStatus.SENT.value,
        items=[
            InvoiceItem(
                product_name="Web Consulting Services",
                quantity=Decimal("10"),
                unit_price=Decimal("75.00"),
                line_total=Decimal("750.00"),
            )
        ],
    )

    pdf_path = generate_invoice_pdf(invoice, output_dir="./storage/test_invoices")
    assert os.path.exists(pdf_path)
    assert pdf_path.endswith("INV-000099.pdf")
    assert os.path.getsize(pdf_path) > 1000  # Non-empty valid PDF


def test_exchange_rate_to_usd():
    from invoicemate.services.exchange_rate_service import ExchangeRateResult

    rate_info = ExchangeRateResult(rate=Decimal("4000"), source="Test", bulletin_date="2026-10-01")
    assert rate_info.to_khr(Decimal("100.00")) == Decimal("400000")
    assert rate_info.to_usd(Decimal("400000")) == Decimal("100.00")
    assert rate_info.to_usd(Decimal("20000")) == Decimal("5.00")

    zero_rate = ExchangeRateResult(rate=Decimal("0"), source="Zero", bulletin_date="2026-10-01")
    assert zero_rate.to_usd(Decimal("1000")) == Decimal("0.00")


def test_generate_khr_invoice_pdf():
    customer = Customer(org_id=1, name="Chanthy Khmer Grocery", phone="+85599887766")
    invoice = Invoice(
        org_id=1,
        invoice_number="INV-000100",
        customer=customer,
        subtotal=Decimal("400000"),
        tax=Decimal("0"),
        total=Decimal("400000"),
        currency="KHR",
        status=InvoiceStatus.SENT.value,
        items=[
            InvoiceItem(
                product_name="Jasmine Rice 50kg",
                quantity=Decimal("2"),
                unit_price=Decimal("200000"),
                line_total=Decimal("400000"),
            )
        ],
    )

    pdf_path = generate_invoice_pdf(invoice, output_dir="./storage/test_invoices")
    assert os.path.exists(pdf_path)
    assert pdf_path.endswith("INV-000100.pdf")
    assert os.path.getsize(pdf_path) > 1000

