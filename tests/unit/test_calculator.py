from decimal import Decimal
import pytest

from invoicemate.services.calculator import (
    calculate_line_total,
    calculate_subtotal,
    calculate_tax,
    calculate_total,
    recalculate_invoice_totals,
    to_decimal,
    quantize_currency,
)


def test_to_decimal_and_quantize():
    assert to_decimal(10) == Decimal("10")
    assert to_decimal(10.5) == Decimal("10.5")
    assert to_decimal("25.99") == Decimal("25.99")
    assert quantize_currency(Decimal("10.556")) == Decimal("10.56")
    assert quantize_currency(Decimal("10.554")) == Decimal("10.55")


def test_calculate_line_total():
    assert calculate_line_total(3, 15.50) == Decimal("46.50")
    assert calculate_line_total(Decimal("2.5"), Decimal("10.00")) == Decimal("25.00")
    assert calculate_line_total("1.5", "10.00") == Decimal("15.00")


def test_calculate_line_total_invalid():
    with pytest.raises(ValueError):
        calculate_line_total(-1, 10)
    with pytest.raises(ValueError):
        calculate_line_total(5, -10)


def test_calculate_subtotal():
    line_totals = [Decimal("10.50"), Decimal("20.25"), Decimal("5.25")]
    assert calculate_subtotal(line_totals) == Decimal("36.00")


def test_calculate_tax():
    subtotal = Decimal("100.00")
    assert calculate_tax(subtotal, Decimal("0.10")) == Decimal("10.00")
    assert calculate_tax(subtotal, Decimal("0.07")) == Decimal("7.00")
    assert calculate_tax(subtotal, Decimal("0.00")) == Decimal("0.00")


def test_calculate_total():
    subtotal = Decimal("100.00")
    tax = Decimal("10.00")
    assert calculate_total(subtotal, tax) == Decimal("110.00")


def test_recalculate_invoice_totals():
    items = [
        {"quantity": "3", "unit_price": "12.50"},
        {"quantity": "1", "unit_price": "50.00"},
    ]
    result = recalculate_invoice_totals(items, tax_rate="0.10")

    assert len(result["items"]) == 2
    assert result["items"][0]["line_total"] == Decimal("37.50")
    assert result["items"][1]["line_total"] == Decimal("50.00")
    assert result["subtotal"] == Decimal("87.50")
    assert result["tax"] == Decimal("8.75")
    assert result["total"] == Decimal("96.25")
