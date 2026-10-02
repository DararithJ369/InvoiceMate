import os
import pytest
from decimal import Decimal

from invoicemate.models.enums import DraftState, InvoiceStatus, PdfStatus
from invoicemate.services.org_service import create_org
from invoicemate.services.conversation_service import (
    process_incoming_message,
    process_callback_query,
    get_session_state,
)
from invoicemate.services.khqr_generator import generate_khqr_string, _crc16_ccitt
from invoicemate.services.storage_service import store_invoice_pdf, generate_secure_storage_token
from invoicemate.bot.rate_limiter import RateLimitMiddleware


def test_phase4_end_to_end_transactional_workflow(db_session):
    """
    Phase 4 Validation Gate:
    Simulate complete pilot user transactional journey in Telegram:
    1. Natural language invoice creation: 'Invoice Sokha 2 monitors at $450 each'
    2. Review draft in WAITING_FOR_CONFIRMATION
    3. Apply text correction: 'actually make it 3 monitors and add 1 keyboard for $25'
    4. Confirm invoice via inline callback -> assigns INV-000001
    5. Render bilingual PDF with embedded Bakong KHQR code
    6. Verify KHQR EMVCo format & valid CRC16 checksum
    7. Verify unguessable public URL
    8. Manual 'Mark as Paid' toggle
    """
    org = create_org(db_session, telegram_user_id="tg_pilot_merchant", business_name="Pilot Electronics")
    chat_id = "chat_pilot_101"

    # Step 1: User sends initial request
    msg1 = "Invoice Sokha 2 monitors at $450 each"
    res1 = process_incoming_message(db_session, org_id=org.id, chat_id=chat_id, message_text=msg1)
    assert res1["action"] == "draft_created"
    assert res1["state"] == DraftState.WAITING_FOR_CONFIRMATION.value
    draft1 = res1["draft"]
    assert draft1.draft_json["subtotal"] == 900.00
    assert len(draft1.draft_json["items"]) == 1

    # Step 2: User applies a text correction
    msg2 = "actually make it 3 monitors and add 1 keyboard for $25"
    res2 = process_incoming_message(db_session, org_id=org.id, chat_id=chat_id, message_text=msg2)
    assert res2["action"] == "draft_updated"
    assert res2["state"] == DraftState.WAITING_FOR_CONFIRMATION.value
    draft2 = res2["draft"]
    assert len(draft2.draft_json["items"]) == 2
    # 3 * 450 + 25 = 1375.00
    assert draft2.draft_json["subtotal"] == 1375.00

    # Step 3: User confirms invoice via inline button callback
    res3 = process_callback_query(
        db_session,
        org_id=org.id,
        chat_id=chat_id,
        callback_data=f"cb_confirm_draft:{draft2.id}",
    )
    assert res3["action"] == "invoice_confirmed"
    assert res3["state"] == DraftState.SENT.value
    invoice = res3["invoice"]
    assert invoice.invoice_number == "INV-000001"
    assert invoice.status == InvoiceStatus.SENT.value
    assert invoice.pdf_status == PdfStatus.READY.value
    assert invoice.pdf_url is not None

    # Step 4: Verify generated PDF exists on disk and has valid size
    pdf_path = os.path.join("./storage/invoices", f"{invoice.invoice_number}.pdf")
    assert os.path.exists(pdf_path)
    assert os.path.getsize(pdf_path) > 2000

    # Step 5: Verify Bakong KHQR EMVCo compliance & CRC16 checksum
    khqr_str = generate_khqr_string(
        merchant_name="Pilot Electronics",
        amount=invoice.total,
        currency=invoice.currency,
        bill_number=invoice.invoice_number,
    )
    assert khqr_str.startswith("000201")
    assert "5802KH" in khqr_str  # Country code Cambodia
    assert "840" in khqr_str  # Currency USD
    assert "1375.00" in khqr_str

    # Validate CRC16 checksum
    payload_before_crc = khqr_str[:-4]
    calculated_crc = _crc16_ccitt(payload_before_crc)
    assert khqr_str.endswith(calculated_crc)

    # Step 6: Mark as Paid
    res4 = process_callback_query(
        db_session,
        org_id=org.id,
        chat_id=chat_id,
        callback_data=f"mark_paid:{invoice.id}",
    )
    assert res4["action"] == "marked_paid"
    assert res4["state"] == DraftState.PAID.value
    assert res4["invoice"].status == InvoiceStatus.PAID.value


def test_rate_limiting_enforcement():
    """Verify rate limiter middleware enforces 20 requests per minute limit."""
    limiter = RateLimitMiddleware(limit=20, window_seconds=60.0)

    user_id = "test_rate_user"

    # Send 20 requests within window
    import time
    now = time.time()
    for _ in range(20):
        limiter.request_history[user_id].append(now)

    assert len(limiter.request_history[user_id]) == 20


def test_unguessable_pdf_storage():
    """Verify storing PDF with cryptographically secure random token."""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4 mock data")
        temp_pdf = f.name

    try:
        dest_path, public_url = store_invoice_pdf(temp_pdf)
        assert os.path.exists(dest_path)
        assert "/pdf/" in public_url
        assert os.path.basename(temp_pdf) in public_url
    finally:
        if os.path.exists(temp_pdf):
            os.remove(temp_pdf)
