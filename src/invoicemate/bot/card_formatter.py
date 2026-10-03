from typing import Union, Any
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from invoicemate.models.invoice import Invoice
from invoicemate.models.draft import Draft


def format_draft_card(draft: Draft, title: str = "វិក្កយបត្រព្រាង / INVOICE DRAFT") -> str:
    """Format an uncommitted conversational draft into a bilingual Telegram confirmation card."""
    data = draft.draft_json or {}
    customer_name = data.get("customer_name") or "Not specified"
    currency = data.get("currency", "USD")
    currency_symbol = "$" if currency == "USD" else "៛"
    subtotal = data.get("subtotal", 0.0)
    tax = data.get("tax", 0.0)
    total = data.get("total", 0.0)
    due_date = data.get("due_date")

    lines = [
        f"<b>{title}</b>",
        "──────────────────────────────",
        f"<b>អតិថិជន / Customer:</b> {customer_name}",
        f"<b>ស្ថានភាព / State:</b> <code>{draft.state}</code>",
        f"<b>រូបិយប័ណ្ណ / Currency:</b> {currency}",
    ]

    if due_date:
        lines.append(f"<b>ថ្ងៃផុតកំណត់ / Due Date:</b> {due_date}")

    lines.append("\n<b>ទំនិញ ឬសេវាកម្ម / Items:</b>")
    items = data.get("items", [])
    for idx, itm in enumerate(items, 1):
        name = itm.get("product_name") or itm.get("name", "Item")
        qty = itm.get("quantity") or itm.get("qty", 1)
        price = itm.get("unit_price") or itm.get("price", 0)
        line_tot = itm.get("line_total", float(qty) * float(price))
        lines.append(
            f"  {idx}. <b>{name}</b>\n"
            f"     {qty:g} × {currency_symbol}{price:,.2f} = <b>{currency_symbol}{line_tot:,.2f}</b>"
        )

    lines.append("──────────────────────────────")
    lines.append(f"<b>សរុប / Subtotal:</b> {currency_symbol}{subtotal:,.2f}")
    if tax > 0:
        lines.append(f"<b>ពន្ធ / Tax:</b> {currency_symbol}{tax:,.2f}")
    lines.append(f"<b>សរុបរួម / TOTAL:</b> <b>{currency_symbol}{total:,.2f} {currency}</b>")
    lines.append("\n<i>សូមផ្ទៀងផ្ទាត់ ឬឆ្លើយតបដើម្បីកែប្រែ (e.g. <code>actually make it 3</code>):</i>")

    return "\n".join(lines)


def format_invoice_card(
    invoice_or_draft: Union[Invoice, Draft, Any],
    title: str = "វិក្កយបត្រ / INVOICE",
) -> str:
    """Format either an Invoice or Draft object into a clean bilingual Telegram card."""
    if isinstance(invoice_or_draft, Draft):
        return format_draft_card(invoice_or_draft, title=title)

    invoice = invoice_or_draft
    customer_name = invoice.customer.name if getattr(invoice, "customer", None) else "Not specified"
    currency_symbol = "$" if invoice.currency == "USD" else "៛"

    created_date = (
        invoice.created_at.strftime("%Y-%m-%d")
        if getattr(invoice, "created_at", None)
        else "N/A"
    )

    lines = [
        f"<b>{title}</b>",
        "──────────────────────────────",
        f"<b>លេខវិក្កយបត្រ / Invoice #:</b> {invoice.invoice_number}",
        f"<b>អតិថិជន / Customer:</b> {customer_name}",
        f"<b>កាលបរិច្ឆេទ / Date:</b> {created_date}",
        f"<b>ស្ថានភាព / Status:</b> <code>{invoice.status.upper()}</code>",
        f"<b>រូបិយប័ណ្ណ / Currency:</b> {invoice.currency}",
    ]

    if getattr(invoice, "due_date", None):
        lines.append(f"<b>ថ្ងៃផុតកំណត់ / Due Date:</b> {invoice.due_date}")

    lines.append("\n<b>ទំនិញ ឬសេវាកម្ម / Items:</b>")
    items = getattr(invoice, "items", [])
    for idx, item in enumerate(items, 1):
        price_formatted = f"{currency_symbol}{item.unit_price:,.2f}"
        total_formatted = f"{currency_symbol}{item.line_total:,.2f}"
        lines.append(
            f"  {idx}. <b>{item.product_name}</b>\n"
            f"     {item.quantity:g} × {price_formatted} = <b>{total_formatted}</b>"
        )

    lines.append("──────────────────────────────")
    lines.append(f"<b>សរុប / Subtotal:</b> {currency_symbol}{invoice.subtotal:,.2f}")
    if invoice.tax > 0:
        lines.append(f"<b>ពន្ធ / Tax:</b> {currency_symbol}{invoice.tax:,.2f}")
    lines.append(f"<b>សរុបរួម / TOTAL:</b> <b>{currency_symbol}{invoice.total:,.2f} {invoice.currency}</b>")

    if invoice.status == "sent":
        lines.append("\n<b>វិក្កយបត្របានបង្កើតជោគជ័យ / Confirmed & Issued!</b>")
        if invoice.pdf_url:
            lines.append(f"<a href=\"{invoice.pdf_url}\">ទាញយកវិក្កយបត្រ PDF / Download PDF</a>")
    elif invoice.status == "paid":
        lines.append("\n<b>បានទូទាត់រួចរាល់ / Marked as PAID!</b>")

    return "\n".join(lines)


def get_draft_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    """
    Generate inline keyboard buttons for draft confirmation and cancellation.
    Uses exact callback protocol mandated in TASK.md Section 4:
    - cb_confirm_draft:{draft_id}
    - cb_cancel_draft:{draft_id}
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="យល់ព្រម / Confirm & Issue",
                    callback_data=f"cb_confirm_draft:{draft_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="បោះបង់ / Cancel Draft",
                    callback_data=f"cb_cancel_draft:{draft_id}",
                ),
            ],
        ]
    )
    return keyboard


def get_issued_invoice_keyboard(invoice_id: int, status: str = "sent") -> InlineKeyboardMarkup:
    """
    Generate inline keyboard buttons for an issued invoice:
    - [🔄 ពិនិត្យការទូទាត់ / Check Payment]: Live query Bakong Open API
    - [🟢 កត់សម្គាល់ថាបានបង់ / Mark as Paid]: Manual toggle
    """
    if status == "paid":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ បានបង់ប្រាក់រួចរាល់ / Paid",
                        callback_data="cb_noop",
                    )
                ]
            ]
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 ពិនិត្យការទូទាត់ / Check Payment",
                    callback_data=f"cb_check_payment:{invoice_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🟢 កត់សម្គាល់ថាបានបង់ / Mark as Paid",
                    callback_data=f"mark_paid:{invoice_id}",
                ),
            ],
        ]
    )
