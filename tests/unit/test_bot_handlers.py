from decimal import Decimal
from invoicemate.bot.card_formatter import format_invoice_card, get_draft_keyboard
from invoicemate.models.customer import Customer
from invoicemate.models.invoice import Invoice
from invoicemate.models.invoice_item import InvoiceItem
from invoicemate.models.enums import InvoiceStatus


def test_format_invoice_card():
    customer = Customer(org_id=1, name="Sokha Computer Shop")
    invoice = Invoice(
        org_id=1,
        invoice_number="INV-000001",
        customer=customer,
        subtotal=Decimal("900.00"),
        tax=Decimal("0.00"),
        total=Decimal("900.00"),
        currency="USD",
        status=InvoiceStatus.SENT.value,
        items=[
            InvoiceItem(
                product_name="Dell 24-inch Monitor",
                quantity=Decimal("2"),
                unit_price=Decimal("450.00"),
                line_total=Decimal("900.00"),
            )
        ],
    )

    card_html = format_invoice_card(invoice, title="📝 TEST CONFIRMATION")

    assert "TEST CONFIRMATION" in card_html
    assert "INV-000001" in card_html
    assert "Sokha Computer Shop" in card_html
    assert "Dell 24-inch Monitor" in card_html
    assert "$900.00 USD" in card_html
    assert "SENT" in card_html


def test_get_draft_keyboard():
    kb = get_draft_keyboard(draft_id=42)
    assert kb is not None
    buttons = kb.inline_keyboard
    assert len(buttons) == 2
    assert buttons[0][0].callback_data == "cb_confirm_draft:42"
    assert buttons[1][0].callback_data == "cb_cancel_draft:42"


def test_bot_init_import():
    import invoicemate.bot as bot_pkg
    assert hasattr(bot_pkg, "router")
    assert hasattr(bot_pkg, "format_invoice_card")
    assert hasattr(bot_pkg, "run_bot")


def test_gifs_and_clean_formatting():
    from invoicemate.bot.gifs import get_animation_target, GIF_PATHS
    import os

    for key in ["welcome", "success", "paid", "clear"]:
        target = get_animation_target(key)
        assert target is not None
        assert os.path.exists(GIF_PATHS[key])

    # Ensure default titles have no emoji characters
    customer = Customer(org_id=1, name="Dara")
    invoice = Invoice(
        org_id=1,
        invoice_number="INV-000002",
        customer=customer,
        subtotal=Decimal("100.00"),
        tax=Decimal("0.00"),
        total=Decimal("100.00"),
        currency="USD",
        status=InvoiceStatus.PAID.value,
        items=[],
    )
    card_html = format_invoice_card(invoice)
    emojis = ["📝", "✅", "❌", "🟢", "🔵", "🔴", "🟡", "⚪", "🧹", "⚠️", "👤", "💵", "📄", "📥", "👉", "📊"]
    for emo in emojis:
        assert emo not in card_html

