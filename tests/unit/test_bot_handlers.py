from decimal import Decimal
import pytest
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


@pytest.mark.anyio
async def test_bot_callback_queries():
    from unittest.mock import AsyncMock
    from invoicemate.bot.handlers import handle_noop_cb, handle_edit_draft_cb, handle_fallback_cb

    cb_noop = AsyncMock()
    await handle_noop_cb(cb_noop)
    cb_noop.answer.assert_called_once()
    assert "បានបង់រួចហើយ" in cb_noop.answer.call_args[0][0]

    cb_edit = AsyncMock()
    await handle_edit_draft_cb(cb_edit)
    cb_edit.answer.assert_called_once()
    assert "កែប្រែ" in cb_edit.answer.call_args[0][0]

    cb_fallback = AsyncMock()
    await handle_fallback_cb(cb_fallback)
    cb_fallback.answer.assert_called_once()


def test_conversation_service_edit_draft_callback(db_session):
    from invoicemate.services.conversation_service import process_callback_query

    res = process_callback_query(db_session, org_id=1, chat_id="123", callback_data="cb_edit_draft:10")
    assert res["action"] == "prompt_edit"
    assert res["draft_id"] == 10


@pytest.mark.anyio
async def test_bot_status_and_revenue_summary(db_session, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    from invoicemate.bot.handlers import handle_status_command
    from invoicemate.services.org_service import create_org

    org = create_org(db_session, telegram_user_id="tg_status_user")
    inv_paid = Invoice(
        org_id=org.id,
        invoice_number="INV-008001",
        subtotal=Decimal("200.00"),
        tax=Decimal("0.00"),
        total=Decimal("200.00"),
        currency="USD",
        status=InvoiceStatus.PAID.value,
        items=[],
    )
    inv_unpaid = Invoice(
        org_id=org.id,
        invoice_number="INV-008002",
        subtotal=Decimal("50000"),
        tax=Decimal("0.00"),
        total=Decimal("50000"),
        currency="KHR",
        status=InvoiceStatus.SENT.value,
        items=[],
    )
    db_session.add_all([inv_paid, inv_unpaid])
    db_session.commit()

    class SessionContext:
        def __enter__(self):
            return db_session
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr("invoicemate.bot.handlers.SessionLocal", SessionContext)

    # 1. Test overall status summary with revenue metrics
    msg = AsyncMock()
    msg.text = "/status"
    msg.from_user = MagicMock()
    msg.from_user.id = "tg_status_user"
    msg.from_user.full_name = "Status User"
    msg.from_user.username = "statususer"

    await handle_status_command(msg)
    msg.answer.assert_called_once()
    reply_text = msg.answer.call_args[0][0]
    assert "INVOICE & REVENUE SUMMARY" in reply_text
    assert "$200.00" in reply_text
    assert "50,000 ៛" in reply_text

    # 2. Test status of specific invoice
    msg.reset_mock()
    msg.text = "/status INV-008001"
    await handle_status_command(msg)
    msg.answer.assert_called_once()
    reply_text_single = msg.answer.call_args[0][0]
    assert "INV-008001" in reply_text_single
    assert "PAID" in reply_text_single


@pytest.mark.anyio
async def test_bot_search_and_cancel_invoice_commands(db_session, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    from invoicemate.bot.handlers import handle_search_command, handle_cancel_invoice_command
    from invoicemate.services.org_service import create_org

    org = create_org(db_session, telegram_user_id="tg_search_cancel_user")
    cust = Customer(org_id=org.id, name="Sovan Technologies")
    db_session.add(cust)
    db_session.flush()

    inv = Invoice(
        org_id=org.id,
        invoice_number="INV-008003",
        customer_id=cust.id,
        subtotal=Decimal("150.00"),
        tax=Decimal("0.00"),
        total=Decimal("150.00"),
        currency="USD",
        status=InvoiceStatus.SENT.value,
        items=[InvoiceItem(product_name="Mechanical Keyboard", quantity=Decimal("1"), unit_price=Decimal("150.00"), line_total=Decimal("150.00"))],
    )
    db_session.add(inv)
    db_session.commit()

    class SessionContext:
        def __enter__(self):
            return db_session
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr("invoicemate.bot.handlers.SessionLocal", SessionContext)

    msg = AsyncMock()
    msg.from_user = MagicMock()
    msg.from_user.id = "tg_search_cancel_user"
    msg.from_user.full_name = "Test User"
    msg.from_user.username = "testuser"

    # Search usage
    msg.text = "/search"
    await handle_search_command(msg)
    assert "Usage:" in msg.answer.call_args[0][0]

    # Search query
    msg.reset_mock()
    msg.text = "/search Keyboard"
    await handle_search_command(msg)
    msg.answer.assert_called_once()
    search_reply = msg.answer.call_args[0][0]
    assert "INV-008003" in search_reply
    assert "Sovan Technologies" in search_reply

    # Cancel invoice
    msg.reset_mock()
    msg.text = "/cancel_invoice INV-008003"
    await handle_cancel_invoice_command(msg)
    db_session.refresh(inv)
    assert inv.status == "cancelled"

    # Cancel already cancelled
    msg.reset_mock()
    msg.text = "/cancel_invoice INV-008003"
    await handle_cancel_invoice_command(msg)
    assert "already cancelled" in msg.answer.call_args[0][0]


@pytest.mark.anyio
async def test_bot_unpaid_and_export_and_customer_commands(db_session, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    from invoicemate.bot.handlers import handle_unpaid_command, handle_export_command, handle_customer_command
    from invoicemate.services.org_service import create_org

    org = create_org(db_session, telegram_user_id="tg_unpaid_export_user")
    cust = Customer(org_id=org.id, name="Angkor Handicrafts", phone="+85588776655", default_currency="USD")
    db_session.add(cust)
    db_session.flush()

    inv = Invoice(
        org_id=org.id,
        invoice_number="INV-008888",
        customer_id=cust.id,
        subtotal=Decimal("200.00"),
        tax=Decimal("0.00"),
        total=Decimal("200.00"),
        currency="USD",
        status=InvoiceStatus.SENT.value,
        items=[InvoiceItem(product_name="Silver Bracelet", quantity=Decimal("2"), unit_price=Decimal("100.00"), line_total=Decimal("200.00"))],
    )
    db_session.add(inv)
    db_session.commit()

    class SessionContext:
        def __enter__(self):
            return db_session
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr("invoicemate.bot.handlers.SessionLocal", SessionContext)

    msg = AsyncMock()
    msg.from_user = MagicMock()
    msg.from_user.id = "tg_unpaid_export_user"
    msg.from_user.full_name = "Craft Merchant"
    msg.from_user.username = "craftmerchant"

    # 1. Test /unpaid command with pending invoice
    msg.text = "/unpaid"
    await handle_unpaid_command(msg)
    msg.answer.assert_called_once()
    unpaid_reply = msg.answer.call_args[0][0]
    assert "UNPAID INVOICES" in unpaid_reply
    assert "INV-008888" in unpaid_reply
    assert "$200.00" in unpaid_reply

    # 2. Test /export command
    msg.reset_mock()
    msg.text = "/export all"
    await handle_export_command(msg)
    msg.answer_document.assert_called_once()
    doc_call = msg.answer_document.call_args[1]
    assert "document" in doc_call
    assert "Sales Journal Export" in doc_call["caption"]

    # 3. Test /customer usage without argument
    msg.reset_mock()
    msg.text = "/customer"
    await handle_customer_command(msg)
    assert "Usage:" in msg.answer.call_args[0][0]

    # 4. Test /customer lookup with query
    msg.reset_mock()
    msg.text = "/customer Angkor"
    await handle_customer_command(msg)
    msg.answer.assert_called_once()
    cust_reply = msg.answer.call_args[0][0]
    assert "CUSTOMER PROFILE" in cust_reply
    assert "Angkor Handicrafts" in cust_reply
    assert "INV-008888" in cust_reply

    # 5. Test /customer non-existent
    msg.reset_mock()
    msg.text = "/customer NonExistentCustomer"
    await handle_customer_command(msg)
    assert "No customer found" in msg.answer.call_args[0][0]




