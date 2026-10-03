import hashlib
import hmac
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Dict, Any, Tuple
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from invoicemate.core.config import settings
from invoicemate.models.enums import InvoiceStatus
from invoicemate.models.invoice import Invoice
from invoicemate.models.org import Org
from invoicemate.services.invoice_engine import mark_as_paid

logger = logging.getLogger(__name__)


def verify_webhook_signature(
    raw_body: bytes,
    headers: Dict[str, str],
    secret: Optional[str] = None,
) -> bool:
    """
    Validate incoming request headers using HMAC-SHA256 signature or Bearer token.
    Complies with Bakong Open API security standards.
    If secret is empty or None, signature verification is bypassed (local dev / testing).
    """
    effective_secret = secret if secret is not None else settings.BAKONG_WEBHOOK_SECRET
    if not effective_secret:
        return True

    lower_headers = {k.lower(): v for k, v in headers.items()}

    # 1. Bearer Token Verification
    auth_header = lower_headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if hmac.compare_digest(token, effective_secret):
            return True

    # 2. HMAC SHA-256 Signature Verification
    signature = (
        lower_headers.get("x-bakong-signature")
        or lower_headers.get("x-signature")
        or lower_headers.get("signature")
    )
    if signature:
        sig_str = signature.strip()
        if sig_str.lower().startswith("sha256="):
            sig_str = sig_str.split("=", 1)[1].strip()

        expected_sig = hmac.new(
            effective_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()

        if hmac.compare_digest(sig_str.lower(), expected_sig.lower()):
            return True

    return False


def _parse_timestamp(val: Any) -> datetime:
    """Safely parse ISO string, unix timestamp, or return current UTC time."""
    if not val:
        return datetime.now(timezone.utc)
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(val, tz=timezone.utc)
    if isinstance(val, str):
        try:
            # Handle ISO string with or without Z
            clean_str = val.replace("Z", "+00:00")
            return datetime.fromisoformat(clean_str)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def process_bakong_webhook_payment(
    db: Session,
    payload: Dict[str, Any],
) -> Tuple[Dict[str, Any], Optional[Invoice]]:
    """
    Process incoming Bakong Open API payment settlement callback:
    1. Extracts transaction fields (bill_number, md5/hash, bank_ref, amount, currency).
    2. Idempotency Guard: Verifies if transaction_hash/bank_ref was already processed.
    3. Matches incoming bill_number or md5 hash against pending invoices.
    4. Atomically transitions invoice state to PAID and logs settlement metadata.
    """
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

    # Extract matching identifiers
    bill_number = (
        data.get("bill_number")
        or data.get("billNumber")
        or data.get("invoice_number")
        or data.get("order_id")
        or data.get("billNo")
    )
    if bill_number:
        bill_number = str(bill_number).strip()

    khqr_md5 = (
        data.get("md5")
        or data.get("khqr_md5")
        or data.get("hash")
        or data.get("transaction_hash")
    )
    if khqr_md5:
        khqr_md5 = str(khqr_md5).strip()

    bank_ref = (
        data.get("bank_ref")
        or data.get("bank_transaction_ref")
        or data.get("external_transaction_id")
        or data.get("transaction_id")
        or data.get("ref")
        or data.get("hash")
        or data.get("transaction_hash")
    )
    if bank_ref:
        bank_ref = str(bank_ref).strip()

    raw_timestamp = data.get("timestamp") or data.get("settled_at") or data.get("paid_at")
    settled_at = _parse_timestamp(raw_timestamp)

    # 1. Idempotency Check: if this bank reference has already been settled
    if bank_ref:
        existing_paid = (
            db.execute(
                select(Invoice).where(
                    Invoice.bank_transaction_ref == bank_ref,
                    Invoice.status == InvoiceStatus.PAID.value,
                )
            )
            .scalars()
            .first()
        )
        if existing_paid:
            return {
                "status": "already_processed",
                "message": f"Payment already processed for bank transaction {bank_ref}",
                "invoice_number": existing_paid.invoice_number,
                "bank_ref": bank_ref,
            }, existing_paid

    # 2. Lookup Invoice by bill_number
    target_invoice: Optional[Invoice] = None
    if bill_number:
        target_invoice = (
            db.execute(
                select(Invoice).where(
                    func.lower(Invoice.invoice_number) == bill_number.lower()
                )
            )
            .scalars()
            .first()
        )

    # Secondary lookup by khqr_md5
    if not target_invoice and khqr_md5:
        target_invoice = (
            db.execute(
                select(Invoice).where(
                    func.lower(Invoice.khqr_md5) == khqr_md5.lower()
                )
            )
            .scalars()
            .first()
        )

    if not target_invoice:
        return {
            "status": "not_found",
            "message": f"No invoice matching bill_number='{bill_number}' or khqr_md5='{khqr_md5}' found",
        }, None

    # Check if target invoice is already paid
    if target_invoice.status == InvoiceStatus.PAID.value:
        return {
            "status": "already_processed",
            "message": f"Invoice {target_invoice.invoice_number} is already marked as PAID",
            "invoice_number": target_invoice.invoice_number,
            "bank_ref": target_invoice.bank_transaction_ref or bank_ref,
        }, target_invoice

    # 3. Atomically transition state to PAID
    effective_bank_ref = bank_ref or f"BK-{int(datetime.now().timestamp())}"
    updated_invoice = mark_as_paid(
        db=db,
        invoice_id=target_invoice.id,
        org_id=target_invoice.org_id,
        bank_transaction_ref=effective_bank_ref,
        payment_method="BAKONG_KHQR",
        payment_metadata=payload,
        paid_at=settled_at,
    )

    return {
        "status": "success",
        "message": f"Invoice {updated_invoice.invoice_number} successfully marked as PAID",
        "invoice_number": updated_invoice.invoice_number,
        "amount_paid": float(updated_invoice.total),
        "currency": updated_invoice.currency,
        "bank_ref": effective_bank_ref,
        "paid_at": updated_invoice.paid_at.isoformat() if updated_invoice.paid_at else None,
    }, updated_invoice


def format_merchant_payment_alert_card(
    invoice: Invoice,
    bank_ref: Optional[str] = None,
    paid_at: Optional[datetime] = None,
) -> str:
    """
    Format instant payment receipt card for merchant Telegram push notification.
    Exact statutory format compliant with Feature Specification Section 3.C:
    ✅ Payment Received!

    ----------------------------------------
    Invoice:      INV-2026-00102
    Customer:     Sokha Co., Ltd.
    Amount Paid:  $150.00 USD (607,500 KHR)
    Bank Ref:     FT260019X8291
    Time:         03 Oct 2026, 09:31 AM
    Status:       PAID (Auto-Verified)
    ----------------------------------------

    📄 Updated invoice status saved to records.
    """
    customer_name = (
        invoice.customer.name if getattr(invoice, "customer", None) and invoice.customer.name
        else "Walk-in Customer"
    )

    effective_paid_at = paid_at or invoice.paid_at or datetime.now(timezone.utc)
    time_str = effective_paid_at.strftime("%d %b %Y, %I:%M %p")

    effective_bank_ref = bank_ref or invoice.bank_transaction_ref or "N/A"

    # Dual-currency amount display calculation
    usd_khr_rate = Decimal("4085")  # GDT statutory reference rate
    if invoice.currency == "USD":
        khr_equiv = round(invoice.total * usd_khr_rate)
        amount_display = f"${invoice.total:,.2f} USD ({khr_equiv:,.0f} KHR)"
    else:
        usd_equiv = invoice.total / usd_khr_rate
        amount_display = f"{invoice.total:,.0f} KHR (${usd_equiv:,.2f} USD)"

    card_text = (
        "✅ <b>Payment Received!</b>\n\n"
        "────────────────────────────────────────\n"
        f"<b>Invoice:</b>      <code>{invoice.invoice_number}</code>\n"
        f"<b>Customer:</b>     {customer_name}\n"
        f"<b>Amount Paid:</b>  <b>{amount_display}</b>\n"
        f"<b>Bank Ref:</b>     <code>{effective_bank_ref}</code>\n"
        f"<b>Time:</b>         {time_str}\n"
        "<b>Status:</b>       <b>PAID (Auto-Verified)</b>\n"
        "────────────────────────────────────────\n\n"
        "📄 <i>Updated invoice status saved to records.</i>"
    )
    return card_text


async def send_merchant_payment_alert(
    invoice_id: int,
    bank_ref: Optional[str] = None,
    paid_at: Optional[datetime] = None,
) -> bool:
    """
    Push instant payment confirmation receipt card directly to merchant's Telegram chat.
    Triggered asynchronously via FastAPI BackgroundTasks upon successful state transition.
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not configured; skipping merchant notification")
        return False

    from invoicemate.db.session import SessionLocal

    with SessionLocal() as db:
        invoice = db.get(Invoice, invoice_id)
        if not invoice:
            logger.warning(f"Invoice {invoice_id} not found for payment alert")
            return False

        org = db.get(Org, invoice.org_id)
        if not org or not org.telegram_user_id:
            logger.warning(f"No Telegram user ID found for org {invoice.org_id}")
            return False

        merchant_chat_id = org.telegram_user_id
        card_text = format_merchant_payment_alert_card(
            invoice=invoice,
            bank_ref=bank_ref,
            paid_at=paid_at,
        )

    from aiogram import Bot

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    try:
        from invoicemate.bot.gifs import PAID_GIF_URL
        # Try sending animation with card caption
        if PAID_GIF_URL:
            try:
                await bot.send_animation(
                    chat_id=merchant_chat_id,
                    animation=PAID_GIF_URL,
                    caption=card_text,
                    parse_mode="HTML",
                )
                logger.info(f"Sent payment notification animation to {merchant_chat_id} for {invoice.invoice_number}")
                return True
            except Exception as anim_err:
                logger.debug(f"Could not send animation, falling back to message: {anim_err}")

        await bot.send_message(
            chat_id=merchant_chat_id,
            text=card_text,
            parse_mode="HTML",
        )
        logger.info(f"Sent payment notification text to {merchant_chat_id} for {invoice.invoice_number}")
        return True
    except Exception as err:
        logger.warning(f"Failed to push Telegram payment alert to {merchant_chat_id}: {err}")
        return False
    finally:
        await bot.session.close()
