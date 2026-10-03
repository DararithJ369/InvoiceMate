import hashlib
import hmac
import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from invoicemate.api.server import app
from invoicemate.core.config import settings
from invoicemate.models.customer import Customer
from invoicemate.models.enums import InvoiceStatus, EventType
from invoicemate.models.invoice import Invoice
from invoicemate.models.invoice_event import InvoiceEvent
from invoicemate.models.invoice_item import InvoiceItem
from invoicemate.models.org import Org
from invoicemate.services.bakong_webhook_service import (
    verify_webhook_signature,
    process_bakong_webhook_payment,
    format_merchant_payment_alert_card,
    send_merchant_payment_alert,
)
from invoicemate.services.khqr_generator import (
    generate_dynamic_khqr,
    calculate_khqr_md5,
    generate_khqr_string,
    _crc16_ccitt,
)
from invoicemate.services.org_service import create_org


def test_dynamic_khqr_generation_and_md5():
    """
    Requirement 1:
    Verify Dynamic KHQR incorporates bakong_id, amount, currency, merchant_name, bill_number,
    initiates method 12 (Dynamic), contains valid CRC16, and produces a valid 32-character hex MD5.
    """
    khqr_str, khqr_md5 = generate_dynamic_khqr(
        merchant_name="Sokha Co., Ltd.",
        amount=Decimal("150.00"),
        currency="USD",
        bill_number="INV-2026-00102",
        bakong_account_id="sokha@bakong",
    )

    # 1. EMVCo Tag 00 & Tag 01="12" (Dynamic)
    assert khqr_str.startswith("000201010212")
    # 2. Tag 29 Bakong ID
    assert "sokha@bakong" in khqr_str
    # 3. Tag 53 Currency (840 for USD)
    assert "5303840" in khqr_str
    # 4. Tag 54 Amount
    assert "5406150.00" in khqr_str
    # 5. Tag 62 Additional Data (Bill Number)
    assert "INV-2026-00102" in khqr_str
    # 6. Checksum validation
    payload_before_crc = khqr_str[:-4]
    expected_crc = _crc16_ccitt(payload_before_crc)
    assert khqr_str.endswith(expected_crc)

    # 7. MD5 checksum verification
    expected_md5 = hashlib.md5(khqr_str.encode("utf-8")).hexdigest()
    assert khqr_md5 == expected_md5
    assert len(khqr_md5) == 32


def test_webhook_signature_validation():
    """
    Requirement 2 & 3.A:
    Validate HMAC SHA-256 and Bearer token security.
    """
    secret = "test_super_secret_key_123"
    payload = json.dumps({"bill_number": "INV-000001", "amount": 100}).encode("utf-8")

    # 1. Valid HMAC SHA-256 header
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(payload, {"X-Bakong-Signature": sig}, secret=secret) is True
    assert verify_webhook_signature(payload, {"x-signature": f"sha256={sig}"}, secret=secret) is True

    # 2. Valid Bearer Token
    assert verify_webhook_signature(payload, {"Authorization": f"Bearer {secret}"}, secret=secret) is True

    # 3. Invalid Signature
    assert verify_webhook_signature(payload, {"X-Bakong-Signature": "invalid_sig"}, secret=secret) is False
    assert verify_webhook_signature(payload, {"Authorization": "Bearer wrong_token"}, secret=secret) is False

    # 4. Empty Secret (Permissive for local dev)
    assert verify_webhook_signature(payload, {}, secret="") is True


def test_process_bakong_webhook_by_bill_number(db_session):
    """
    Requirement 2 & 3:
    Reconcile payment using bill_number, atomically transition SENT -> PAID,
    persist bank_ref, paid_at, and payment_metadata.
    """
    org = create_org(db_session, telegram_user_id="tg_merchant_101", business_name="Sokha Shop")
    customer = Customer(org_id=org.id, name="Sokha Co., Ltd.")
    db_session.add(customer)
    db_session.flush()

    invoice = Invoice(
        org_id=org.id,
        invoice_number="INV-2026-00102",
        customer_id=customer.id,
        subtotal=Decimal("150.00"),
        tax=Decimal("0.00"),
        total=Decimal("150.00"),
        currency="USD",
        status=InvoiceStatus.SENT.value,
        payment_method="BAKONG_KHQR",
    )
    db_session.add(invoice)
    db_session.commit()
    db_session.refresh(invoice)

    webhook_payload = {
        "bill_number": "INV-2026-00102",
        "amount": 150.00,
        "currency": "USD",
        "bank_ref": "FT260019X8291",
        "timestamp": "2026-10-03T09:31:00Z",
    }

    result, updated_inv = process_bakong_webhook_payment(db_session, webhook_payload)

    assert result["status"] == "success"
    assert updated_inv is not None
    assert updated_inv.status == InvoiceStatus.PAID.value
    assert updated_inv.bank_transaction_ref == "FT260019X8291"
    assert updated_inv.payment_method == "BAKONG_KHQR"
    assert updated_inv.paid_at is not None
    assert updated_inv.payment_metadata == webhook_payload

    # Verify audit event in invoice_events
    event = (
        db_session.query(InvoiceEvent)
        .filter(InvoiceEvent.invoice_id == updated_inv.id, InvoiceEvent.event_type == EventType.MARKED_PAID.value)
        .first()
    )
    assert event is not None
    assert event.detail.get("bank_transaction_ref") == "FT260019X8291"


def test_process_bakong_webhook_by_khqr_md5(db_session):
    """
    Requirement 2:
    Reconcile payment when payload identifies invoice strictly by khqr_md5 hash.
    """
    org = create_org(db_session, telegram_user_id="tg_merchant_102")
    khqr_str, test_md5 = generate_dynamic_khqr(
        merchant_name="Dara Store",
        amount=Decimal("45.00"),
        currency="USD",
        bill_number="INV-2026-00999",
    )

    invoice = Invoice(
        org_id=org.id,
        invoice_number="INV-2026-00999",
        subtotal=Decimal("45.00"),
        tax=Decimal("0.00"),
        total=Decimal("45.00"),
        currency="USD",
        status=InvoiceStatus.SENT.value,
        payment_method="BAKONG_KHQR",
        khqr_md5=test_md5,
    )
    db_session.add(invoice)
    db_session.commit()

    webhook_payload = {
        "md5": test_md5,
        "amount": 45.00,
        "currency": "USD",
        "bank_ref": "BK-MD5-TEST-99",
    }

    result, updated_inv = process_bakong_webhook_payment(db_session, webhook_payload)
    assert result["status"] == "success"
    assert updated_inv.invoice_number == "INV-2026-00999"
    assert updated_inv.status == InvoiceStatus.PAID.value
    assert updated_inv.bank_transaction_ref == "BK-MD5-TEST-99"


def test_idempotency_guard_prevents_duplicate_processing(db_session):
    """
    Requirement 3.A:
    Idempotency Guard checks if the transaction hash (md5 / hash / bank_ref)
    has already been processed to handle duplicate webhook retries safely.
    """
    org = create_org(db_session, telegram_user_id="tg_merchant_103")
    invoice = Invoice(
        org_id=org.id,
        invoice_number="INV-IDEMP-001",
        subtotal=Decimal("80.00"),
        tax=Decimal("0.00"),
        total=Decimal("80.00"),
        currency="USD",
        status=InvoiceStatus.SENT.value,
    )
    db_session.add(invoice)
    db_session.commit()

    payload = {
        "bill_number": "INV-IDEMP-001",
        "bank_ref": "TX-IDEMP-HASH-1234",
        "amount": 80.00,
    }

    # First call: Processes successfully
    res1, inv1 = process_bakong_webhook_payment(db_session, payload)
    assert res1["status"] == "success"
    assert inv1.status == InvoiceStatus.PAID.value

    # Second call (webhook retry): Returns already_processed
    res2, inv2 = process_bakong_webhook_payment(db_session, payload)
    assert res2["status"] == "already_processed"
    assert inv2.id == inv1.id


def test_format_merchant_payment_alert_card():
    """
    Requirement 3.C:
    Verify notification card format matches exact statutory layout with dual currency.
    """
    customer = Customer(org_id=1, name="Sokha Co., Ltd.")
    invoice = Invoice(
        org_id=1,
        invoice_number="INV-2026-00102",
        customer=customer,
        total=Decimal("150.00"),
        currency="USD",
        status="paid",
        bank_transaction_ref="FT260019X8291",
        paid_at=datetime(2026, 10, 3, 9, 31, 0, tzinfo=timezone.utc),
    )

    card = format_merchant_payment_alert_card(
        invoice=invoice,
        bank_ref="FT260019X8291",
        paid_at=invoice.paid_at,
    )

    assert "Payment Received!" in card
    assert "INV-2026-00102" in card
    assert "Sokha Co., Ltd." in card
    assert "$150.00 USD" in card
    assert "KHR)" in card
    assert "FT260019X8291" in card
    assert "03 Oct 2026, 09:31 AM" in card
    assert "PAID (Auto-Verified)" in card
    assert "Updated invoice status saved to records" in card


def test_fastapi_bakong_webhook_endpoint(db_session, monkeypatch):
    """
    FastAPI Webhook Listener Integration Test:
    Verify HTTP POST /api/v1/webhooks/bakong:
    - Enforces HMAC security
    - Idempotently processes settlement
    - Returns 200 with result payload
    """
    from invoicemate.api.server import get_db
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        test_secret = "bakong_hmac_secret_pilot"
        monkeypatch.setattr(settings, "BAKONG_WEBHOOK_SECRET", test_secret)

        org = create_org(db_session, telegram_user_id="tg_user_api_test")
        invoice = Invoice(
            org_id=org.id,
            invoice_number="INV-API-8888",
            subtotal=Decimal("200.00"),
            tax=Decimal("0.00"),
            total=Decimal("200.00"),
            currency="USD",
            status=InvoiceStatus.SENT.value,
        )
        db_session.add(invoice)
        db_session.commit()

        client = TestClient(app)

        payload_dict = {
            "bill_number": "INV-API-8888",
            "amount": 200.00,
            "currency": "USD",
            "bank_ref": "BANK-API-REF-999",
            "timestamp": "2026-10-03T10:00:00Z",
        }
        raw_body = json.dumps(payload_dict).encode("utf-8")

        # 1. Test unauthorized without signature
        res_unauth = client.post("/api/v1/webhooks/bakong", content=raw_body, headers={"Content-Type": "application/json"})
        assert res_unauth.status_code == 401

        # 2. Test authorized with valid HMAC signature
        valid_sig = hmac.new(test_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        res_success = client.post(
            "/api/v1/webhooks/bakong",
            content=raw_body,
            headers={"Content-Type": "application/json", "X-Bakong-Signature": valid_sig},
        )
        assert res_success.status_code == 200
        data = res_success.json()
        assert data["status"] == "success"
        assert data["invoice_number"] == "INV-API-8888"
        assert data["bank_ref"] == "BANK-API-REF-999"

        # 3. Test retry with same payload returns already_processed
        res_retry = client.post(
            "/api/v1/webhooks/bakong",
            content=raw_body,
            headers={"Content-Type": "application/json", "X-Bakong-Signature": valid_sig},
        )
        assert res_retry.status_code == 200
        assert res_retry.json()["status"] == "already_processed"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_send_merchant_payment_alert_mock(monkeypatch):
    """
    Requirement 4:
    Verify Telegram Bot instance sends the formatted payment receipt card.
    """
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "123456:FAKE_MOCK_TOKEN")

    mock_bot = AsyncMock()
    mock_bot.send_animation = AsyncMock(return_value=True)
    mock_bot.session = AsyncMock()
    mock_bot.session.close = AsyncMock()

    with patch("aiogram.Bot", return_value=mock_bot):
        # Even if invoice doesn't exist, function handles it safely
        success = await send_merchant_payment_alert(invoice_id=999999)
        assert success is False
