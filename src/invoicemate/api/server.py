import os
import uvicorn
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from invoicemate.core.config import settings
from invoicemate.db import init_db, SessionLocal
from invoicemate.services.invoice_engine import get_invoice_history, get_invoice_by_number
from invoicemate.services.bakong_webhook_service import (
    verify_webhook_signature,
    process_bakong_webhook_payment,
    send_merchant_payment_alert,
)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="FastAPI Web & PDF Hosting Server for InvoiceMate / InvoiceAI",
)

# Ensure storage directory exists
os.makedirs(settings.STORAGE_DIR, exist_ok=True)

# Mount static files
app.mount("/static/invoices", StaticFiles(directory=settings.STORAGE_DIR), name="static_invoices")


@app.get("/health")
def health_check():
    return {"status": "ok", "app": settings.PROJECT_NAME, "version": settings.VERSION}


def get_db():
    """Database session dependency for FastAPI routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/pdf/{token}/{filename}")
def serve_secure_invoice_pdf(token: str, filename: str):
    """
    Serve generated PDF invoice via cryptographically unguessable token path.
    Example: GET /pdf/a8f3b9d2.../INV-000001.pdf
    """
    safe_token = os.path.basename(token)
    safe_filename = os.path.basename(filename)

    if not safe_filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files can be served.")

    file_path = os.path.join(settings.STORAGE_DIR, safe_token, safe_filename)
    if not os.path.exists(file_path):
        # Fallback check directly in root storage
        file_path = os.path.join(settings.STORAGE_DIR, safe_filename)

    # Fallback to uppercase filename check for case-sensitive filesystems
    if not os.path.exists(file_path):
        upper_name = safe_filename.upper()
        if not upper_name.endswith(".PDF"):
            upper_name += ".PDF"
        upper_token_path = os.path.join(settings.STORAGE_DIR, safe_token, upper_name)
        if os.path.exists(upper_token_path):
            file_path = upper_token_path
        else:
            upper_root_path = os.path.join(settings.STORAGE_DIR, upper_name)
            if os.path.exists(upper_root_path):
                file_path = upper_root_path

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"PDF invoice '{safe_filename}' not found.")

    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=safe_filename,
        headers={"Content-Disposition": f"inline; filename={safe_filename}"},
    )


@app.get("/invoices/{filename}")
def serve_invoice_pdf(filename: str):
    """
    Serve generated PDF invoice directly (legacy route).
    Example: GET /invoices/INV-000001.pdf
    """
    safe_filename = os.path.basename(filename)

    if not safe_filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files can be served.")

    file_path = os.path.join(settings.STORAGE_DIR, safe_filename)
    if not os.path.exists(file_path):
        upper_name = safe_filename.upper()
        if not upper_name.endswith(".PDF"):
            upper_name += ".PDF"
        upper_path = os.path.join(settings.STORAGE_DIR, upper_name)
        if os.path.exists(upper_path):
            file_path = upper_path

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"PDF invoice '{safe_filename}' not found.")

    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=safe_filename,
        headers={"Content-Disposition": f"inline; filename={safe_filename}"},
    )


@app.get("/api/invoices")
def list_invoices_api(limit: int = 20, org_id: int = 1, db: Session = Depends(get_db)):
    """List recent invoices via REST API scoped by org_id."""
    invoices = get_invoice_history(db, org_id=org_id, timeframe="all", limit=limit)
    return [
        {
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "customer": inv.customer.name if inv.customer else None,
            "total": float(inv.total),
            "currency": inv.currency,
            "status": inv.status,
            "pdf_url": inv.pdf_url,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
        }
        for inv in invoices
    ]


@app.get("/api/invoices/{invoice_number}")
def get_invoice_api(invoice_number: str, org_id: int = 1, db: Session = Depends(get_db)):
    """Get single invoice details by invoice number via REST API."""
    inv = get_invoice_by_number(db, invoice_number, org_id=org_id)
    if not inv:
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_number}' not found.")

    return {
        "id": inv.id,
        "invoice_number": inv.invoice_number,
        "customer": inv.customer.name if inv.customer else None,
        "subtotal": float(inv.subtotal),
        "tax": float(inv.tax),
        "total": float(inv.total),
        "currency": inv.currency,
        "status": inv.status,
        "pdf_url": inv.pdf_url,
        "items": [
            {
                "product_name": item.product_name,
                "quantity": float(item.quantity),
                "unit_price": float(item.unit_price),
                "line_total": float(item.line_total),
            }
            for item in inv.items
        ],
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
    }


@app.post("/api/v1/webhooks/bakong")
@app.post("/webhooks/bakong")
async def handle_bakong_payment_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Bakong Open API payment settlement webhook listener:
    1. Validates HMAC-SHA256 signature / Bearer token security.
    2. Enforces idempotency via bank transaction reference / hash.
    3. Matches incoming bill_number or md5 hash against pending invoices.
    4. Atomically transitions invoice state to PAID and logs audit event.
    5. Dispatches asynchronous Telegram payment receipt card to the merchant.
    """
    raw_body = await request.body()
    headers_dict = dict(request.headers)

    # 1. Signature validation
    if not verify_webhook_signature(raw_body=raw_body, headers=headers_dict, secret=settings.BAKONG_WEBHOOK_SECRET):
        raise HTTPException(
            status_code=401,
            detail="Invalid or unauthorized Bakong webhook signature.",
        )

    # 2. Parse JSON payload
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Malformed JSON in webhook request body.")

    # 3. Process payment reconciliation
    result, invoice = process_bakong_webhook_payment(db=db, payload=payload)

    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=result.get("message"))

    # 4. Trigger async merchant notification upon success
    if result.get("status") == "success" and invoice:
        background_tasks.add_task(
            send_merchant_payment_alert,
            invoice_id=invoice.id,
            bank_ref=invoice.bank_transaction_ref,
            paid_at=invoice.paid_at,
        )

    return JSONResponse(status_code=200, content=result)


def run_server():
    """CLI entrypoint to run FastAPI PDF Hosting Server."""
    init_db()
    print(f"🚀 Starting InvoiceMate PDF Hosting & REST API Server on http://{settings.HOST}:{settings.PORT}")
    uvicorn.run("invoicemate.api.server:app", host=settings.HOST, port=settings.PORT, reload=False)


if __name__ == "__main__":
    run_server()
