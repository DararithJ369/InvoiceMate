import csv
import io
from decimal import Decimal
from typing import List, Optional
from invoicemate.models.invoice import Invoice
from invoicemate.services.exchange_rate_service import ExchangeRateResult, get_gdt_fallback_rate


def export_invoices_to_csv(
    invoices: List[Invoice],
    exchange_rate_result: Optional[ExchangeRateResult] = None,
) -> str:
    """
    Export a list of Invoice ORM objects to a Cambodian GDT-compliant Sales Journal CSV string.
    Includes dual-currency calculation (USD -> KHR equivalent), VAT breakdown, and payment details.
    """
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    # GDT / Prakas 723 sales journal columns
    headers = [
        "Invoice Number",
        "Issue Date",
        "Due Date",
        "Customer Name",
        "Customer Phone",
        "Currency",
        "Subtotal",
        "Tax (VAT)",
        "Total",
        "Total (KHR)",
        "Exchange Rate",
        "Status",
        "Payment Method",
        "Bank Reference",
        "Paid Date",
    ]
    writer.writerow(headers)

    rate_info = exchange_rate_result or get_gdt_fallback_rate()

    for inv in invoices:
        cust_name = inv.customer.name if inv.customer else "Unknown Customer"
        cust_phone = inv.customer.phone if (inv.customer and inv.customer.phone) else ""
        issue_date = inv.created_at.strftime("%Y-%m-%d") if getattr(inv, "created_at", None) else ""
        due_date = inv.due_date.strftime("%Y-%m-%d") if getattr(inv, "due_date", None) else ""
        paid_date = inv.paid_at.strftime("%Y-%m-%d %H:%M:%S") if getattr(inv, "paid_at", None) else ""

        curr = inv.currency or "USD"
        if curr == "USD":
            khr_val = rate_info.to_khr(inv.total)
            khr_total_str = f"{khr_val:,.0f}"
            rate_used = f"1 USD = {rate_info.rate:g} KHR"
        else:
            khr_total_str = f"{inv.total:,.0f}"
            rate_used = "N/A (KHR Base)"

        writer.writerow([
            inv.invoice_number,
            issue_date,
            due_date,
            cust_name,
            cust_phone,
            curr,
            f"{inv.subtotal:.2f}" if curr == "USD" else f"{inv.subtotal:.0f}",
            f"{inv.tax:.2f}" if curr == "USD" else f"{inv.tax:.0f}",
            f"{inv.total:.2f}" if curr == "USD" else f"{inv.total:.0f}",
            khr_total_str,
            rate_used,
            inv.status.upper() if inv.status else "UNKNOWN",
            inv.payment_method or "",
            inv.bank_transaction_ref or "",
            paid_date,
        ])

    return output.getvalue()
