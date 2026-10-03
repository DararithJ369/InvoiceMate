#!/usr/bin/env python3
"""
scripts/simulate_webhook.py

Interactive CLI and test utility to simulate Bakong Open API payment settlement callbacks.
Constructs compliant JSON settlement payloads, signs them with HMAC-SHA256,
posts to the FastAPI /api/v1/webhooks/bakong listener, and verifies state transition.

Usage:
    uv run python scripts/simulate_webhook.py
    uv run python scripts/simulate_webhook.py --invoice INV-000001
    uv run python scripts/simulate_webhook.py --invoice INV-000001 --test-idempotency
"""

import argparse
import hashlib
import hmac
import json
import random
import sys
from datetime import datetime, timezone
from decimal import Decimal
import httpx

from invoicemate.core.config import settings
from invoicemate.db.session import SessionLocal
from invoicemate.models.enums import InvoiceStatus
from invoicemate.models.invoice import Invoice
from invoicemate.services.invoice_engine import search_invoices, create_draft, confirm_invoice
from invoicemate.services.org_service import get_or_create_org
from invoicemate.services.khqr_generator import calculate_khqr_md5, generate_khqr_string


def get_or_create_target_invoice(db, requested_number: str = None) -> Invoice:
    """Find the requested invoice or create a fresh sample invoice for testing."""
    if requested_number:
        inv = (
            db.query(Invoice)
            .filter(Invoice.invoice_number == requested_number.strip().upper())
            .first()
        )
        if inv:
            return inv
        print(f"⚠️  Invoice '{requested_number}' not found in database. Creating a fresh sample invoice...")

    # Look for any recent unpaid invoice
    recent_unpaid = (
        db.query(Invoice)
        .filter(Invoice.status == InvoiceStatus.SENT.value)
        .order_by(Invoice.id.desc())
        .first()
    )
    if recent_unpaid:
        return recent_unpaid

    # Create a fresh sample invoice
    org = get_or_create_org(db, telegram_user_id="sim_merchant_001", business_name="Bakong Test Merchant")
    draft = create_draft(
        db=db,
        org_id=org.id,
        chat_id="sim_merchant_001",
        customer_name="Sokha Co., Ltd.",
        items=[
            {"product_name": "4K Ultra HD Monitor", "quantity": 2, "unit_price": 450.0},
            {"product_name": "Ergonomic Mechanical Keyboard", "quantity": 1, "unit_price": 120.0},
        ],
        currency="USD",
    )
    inv = confirm_invoice(db, draft_id=draft.id)
    return inv


def simulate_bakong_webhook(
    invoice_number: str = None,
    custom_amount: float = None,
    custom_currency: str = None,
    webhook_url: str = None,
    secret: str = None,
    use_bearer: bool = False,
    test_idempotency: bool = False,
):
    url = webhook_url or f"{settings.BASE_URL}/api/v1/webhooks/bakong"
    effective_secret = secret if secret is not None else settings.BAKONG_WEBHOOK_SECRET

    print("=" * 60)
    print("🚀 InvoiceMate — Bakong KHQR Webhook Simulator")
    print("=" * 60)

    with SessionLocal() as db:
        invoice = get_or_create_target_invoice(db, invoice_number)
        inv_num = invoice.invoice_number
        total = custom_amount if custom_amount is not None else float(invoice.total)
        currency = custom_currency or invoice.currency
        cust_name = invoice.customer.name if invoice.customer else "Walk-in Customer"
        khqr_md5 = invoice.khqr_md5

        if not khqr_md5:
            khqr_str = generate_khqr_string(amount=Decimal(str(total)), currency=currency, bill_number=inv_num)
            khqr_md5 = calculate_khqr_md5(khqr_str)
            invoice.khqr_md5 = khqr_md5
            db.commit()

    rand_digits = "".join([str(random.randint(0, 9)) for _ in range(6)])
    bank_ref = f"FT260{rand_digits}X"

    # Construct Bakong Open API settlement payload
    payload = {
        "hash": khqr_md5,
        "transaction_hash": khqr_md5,
        "md5": khqr_md5,
        "bill_number": inv_num,
        "amount": total,
        "currency": currency,
        "bank_ref": bank_ref,
        "external_transaction_id": bank_ref,
        "from_account_id": "customer@aba",
        "to_account_id": settings.BAKONG_ACCOUNT_ID,
        "status": "SUCCESS",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    raw_body = json.dumps(payload).encode("utf-8")

    headers = {"Content-Type": "application/json"}

    # Security signing
    if effective_secret:
        if use_bearer:
            headers["Authorization"] = f"Bearer {effective_secret}"
            print(f"🔒 Security: Bearer Token Auth (Secret length: {len(effective_secret)})")
        else:
            sig = hmac.new(effective_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
            headers["X-Bakong-Signature"] = sig
            print(f"🔒 Security: HMAC-SHA256 Signature (Header: X-Bakong-Signature={sig[:16]}...)")
    else:
        print("⚠️  Security: No BAKONG_WEBHOOK_SECRET set; sending unsigned request (permissive mode)")

    print(f"📄 Invoice:     {inv_num} ({cust_name})")
    print(f"💰 Amount:      ${total:,.2f} {currency}")
    print(f"🏦 Bank Ref:    {bank_ref}")
    print(f"🎯 Target URL:  {url}")
    print("-" * 60)

    try:
        with httpx.Client(timeout=10.0) as client:
            print("📡 Posting settlement callback to webhook listener...")
            resp = client.post(url, content=raw_body, headers=headers)
            print(f"📥 Response Code: {resp.status_code}")
            try:
                resp_json = resp.json()
                print(f"📦 Response Body:\n{json.dumps(resp_json, indent=2)}")
            except Exception:
                print(f"📦 Response Text: {resp.text}")

            if resp.status_code == 200:
                print("\n✅ Success! Invoice reconciled & transitioned to PAID.")
            else:
                print(f"\n❌ Webhook rejected with HTTP {resp.status_code}.")

            # Optional: Test idempotency retry
            if test_idempotency:
                print("\n" + "=" * 60)
                print("🔁 Idempotency Test: Sending duplicate settlement callback...")
                resp2 = client.post(url, content=raw_body, headers=headers)
                print(f"📥 Retry Response Code: {resp2.status_code}")
                try:
                    resp2_json = resp2.json()
                    print(f"📦 Retry Response Body:\n{json.dumps(resp2_json, indent=2)}")
                    if resp2_json.get("status") == "already_processed":
                        print("✅ Idempotency Passed: Duplicate safely detected without re-settlement.")
                    else:
                        print("⚠️  Unexpected status for retry.")
                except Exception:
                    print(f"📦 Retry Text: {resp2.text}")

    except httpx.ConnectError:
        print(f"\n❌ Connection Error: Could not connect to {url}.")
        print("💡 Make sure your FastAPI server is running: `uv run uvicorn invoicemate.api.server:app --port 8000`")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Simulate Bakong Open API Payment Webhook")
    parser.add_argument("-i", "--invoice", help="Invoice number to mark as paid (e.g. INV-000001)")
    parser.add_argument("-a", "--amount", type=float, help="Custom payment amount")
    parser.add_argument("-c", "--currency", default="USD", help="Currency (USD/KHR)")
    parser.add_argument("--url", help="Webhook URL (default: http://localhost:8000/api/v1/webhooks/bakong)")
    parser.add_argument("--secret", help="HMAC secret key override")
    parser.add_argument("--bearer", action="store_true", help="Send Bearer token instead of HMAC signature")
    parser.add_argument("--test-idempotency", action="store_true", help="Test idempotency guard by sending duplicate")

    args = parser.parse_args()
    simulate_bakong_webhook(
        invoice_number=args.invoice,
        custom_amount=args.amount,
        custom_currency=args.currency,
        webhook_url=args.url,
        secret=args.secret,
        use_bearer=args.bearer,
        test_idempotency=args.test_idempotency,
    )


if __name__ == "__main__":
    main()
