from decimal import Decimal, ROUND_HALF_UP
from typing import List, Sequence, Union, Dict, Any, Optional

NumericType = Union[Decimal, float, int, str]


def to_decimal(val: NumericType) -> Decimal:
    """Convert any numeric input cleanly to Decimal."""
    if isinstance(val, Decimal):
        return val
    return Decimal(str(val))


def quantize_currency(val: Decimal, currency: str = "USD") -> Decimal:
    """
    Quantize decimal value:
    - 2 decimal places using ROUND_HALF_UP for USD
    - Integer (0 decimal places) for KHR
    """
    if currency.upper() == "KHR":
        return val.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_line_total(
    quantity: NumericType,
    unit_price: NumericType,
    discount_amount: NumericType = Decimal("0.00"),
) -> Decimal:
    """
    Calculate net total for a single invoice line item:
    Line Net Subtotal = (quantity * unit_price) - discount_amount
    Returns Decimal rounded to 2 decimal places.
    """
    qty = to_decimal(quantity)
    price = to_decimal(unit_price)
    discount = to_decimal(discount_amount)

    if qty < 0 or price < 0 or discount < 0:
        raise ValueError("Quantity, unit price, and discount must be non-negative")

    gross = qty * price
    if discount > gross:
        raise ValueError("Discount cannot exceed gross line item amount")

    return quantize_currency(gross - discount)


def calculate_subtotal(line_totals: Sequence[NumericType]) -> Decimal:
    """Calculate sum of all line item totals (Taxable Subtotal)."""
    total = Decimal("0.00")
    for item in line_totals:
        total += to_decimal(item)
    return quantize_currency(total)


def calculate_vat(taxable_subtotal: NumericType, vat_rate: NumericType = Decimal("0.10")) -> Decimal:
    """
    Calculate standard Cambodian VAT (default 10% per Prakas 723).
    VAT Amount = Taxable Subtotal * 0.10
    """
    sub = to_decimal(taxable_subtotal)
    rate = to_decimal(vat_rate)
    if rate < 0:
        raise ValueError("VAT rate cannot be negative")
    return quantize_currency(sub * rate)


def calculate_plt(taxable_subtotal: NumericType, plt_rate: NumericType = Decimal("0.05")) -> Decimal:
    """
    Calculate Public Lighting Tax (PLT) applied at 5% (per Prakas 168) for alcohol/tobacco products.
    """
    sub = to_decimal(taxable_subtotal)
    rate = to_decimal(plt_rate)
    if rate < 0:
        raise ValueError("PLT rate cannot be negative")
    return quantize_currency(sub * rate)


def calculate_accommodation_tax(
    taxable_subtotal: NumericType, acc_rate: NumericType = Decimal("0.02")
) -> Decimal:
    """
    Calculate Accommodation Tax applied at 2% (per Prakas 173) for hotels/accommodation services.
    """
    sub = to_decimal(taxable_subtotal)
    rate = to_decimal(acc_rate)
    if rate < 0:
        raise ValueError("Accommodation tax rate cannot be negative")
    return quantize_currency(sub * rate)


def calculate_withholding_tax_notation(
    subtotal: NumericType, wht_rate: NumericType = Decimal("0.15")
) -> Dict[str, Any]:
    """
    Calculate payer-side Withholding Tax notation (e.g. 15% for resident services).
    Per GDT guidelines, WHT is printed strictly as informational notation at the bottom
    and is NEVER subtracted from the supplier's gross total payable amount.
    """
    sub = to_decimal(subtotal)
    rate = to_decimal(wht_rate)
    amount = quantize_currency(sub * rate)
    return {
        "rate": rate,
        "rate_percentage": f"{rate * 100:g}%",
        "estimated_withheld_amount": amount,
        "is_deducted_from_total": False,
        "notice": "Informational payer-side withholding tax notice per GDT regulations. Not deducted from supplier grand total.",
    }


def calculate_tax(subtotal: NumericType, tax_rate: NumericType = Decimal("0.00")) -> Decimal:
    """Calculate general tax amount given subtotal and rate."""
    sub = to_decimal(subtotal)
    rate = to_decimal(tax_rate)
    if rate < 0:
        raise ValueError("Tax rate cannot be negative")
    return quantize_currency(sub * rate)


def calculate_total(subtotal: NumericType, tax: NumericType = Decimal("0.00")) -> Decimal:
    """Calculate total: subtotal + tax."""
    sub = to_decimal(subtotal)
    tax_amt = to_decimal(tax)
    return quantize_currency(sub + tax_amt)


def recalculate_invoice_totals(
    items: List[Dict[str, Any]],
    tax_rate: NumericType = Decimal("0.00"),
    is_tax_invoice: bool = False,
    apply_plt: bool = False,
    apply_accommodation_tax: bool = False,
    withholding_tax_rate: Optional[NumericType] = None,
    exchange_rate: Optional[NumericType] = None,
    currency: str = "USD",
) -> Dict[str, Any]:
    """
    Deterministic Cambodian tax arithmetic:
    - Item discounts and line net subtotals
    - Standard 10% VAT for tax invoices
    - Sector-specific PLT (5%) and Accommodation Tax (2%)
    - Informational withholding tax notation
    - Dual-currency USD/KHR total calculation
    """
    processed_items = []
    line_totals = []

    for item in items:
        qty = to_decimal(item.get("quantity") if "quantity" in item else item.get("qty", 0))
        price = to_decimal(item.get("unit_price") if "unit_price" in item else item.get("price", 0))
        discount = to_decimal(item.get("discount_amount") or item.get("discount", 0))

        line_tot = calculate_line_total(qty, price, discount_amount=discount)
        line_totals.append(line_tot)

        processed_item = dict(item)
        processed_item["quantity"] = qty
        processed_item["unit_price"] = price
        processed_item["discount_amount"] = discount
        processed_item["line_total"] = line_tot
        processed_items.append(processed_item)

    subtotal = calculate_subtotal(line_totals)

    # Taxes
    vat_amt = Decimal("0.00")
    if is_tax_invoice or tax_rate:
        eff_vat_rate = Decimal("0.10") if is_tax_invoice else to_decimal(tax_rate)
        vat_amt = calculate_vat(subtotal, eff_vat_rate)

    plt_amt = calculate_plt(subtotal) if apply_plt else Decimal("0.00")
    acc_amt = calculate_accommodation_tax(subtotal) if apply_accommodation_tax else Decimal("0.00")

    total_tax = vat_amt + plt_amt + acc_amt
    grand_total = calculate_total(subtotal, total_tax)

    # Informational WHT notation
    wht_info = None
    if withholding_tax_rate is not None:
        wht_info = calculate_withholding_tax_notation(subtotal, withholding_tax_rate)

    # Dual-currency KHR calculation
    khr_total = None
    if exchange_rate is not None and currency.upper() == "USD":
        rate_dec = to_decimal(exchange_rate)
        khr_total = quantize_currency(grand_total * rate_dec, currency="KHR")

    return {
        "items": processed_items,
        "subtotal": subtotal,
        "vat": vat_amt,
        "plt": plt_amt,
        "accommodation_tax": acc_amt,
        "tax": total_tax,
        "total": grand_total,
        "currency": currency,
        "total_khr": khr_total,
        "withholding_tax_notation": wht_info,
        "is_tax_invoice": is_tax_invoice,
    }
