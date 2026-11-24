import os
from typing import Optional, Dict, Any, List
import uvicorn
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, Depends
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session
from invoicemate.core.config import settings
from invoicemate.db import init_db, SessionLocal
from invoicemate.models.customer import Customer
from invoicemate.schemas.customer import CustomerUpdate
from invoicemate.services.invoice_engine import (
    get_invoice_history,
    get_invoice_by_number,
    search_invoices,
    mark_as_paid,
    cancel_invoice,
)
from invoicemate.services.customer_service import (
    find_customers_by_name,
    get_customer_by_id,
    update_customer,
    get_customer_invoices,
    get_customer_metrics,
)
from invoicemate.services.export_service import export_invoices_to_csv
from invoicemate.services.exchange_rate_service import resolve_exchange_rate
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
def list_invoices_api(
    limit: int = 20,
    org_id: int = 1,
    status: Optional[str] = None,
    customer_id: Optional[int] = None,
    timeframe: str = "all",
    q: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    List invoices via REST API scoped by org_id with optional filters:
    - status: filter by invoice status ('sent', 'paid', 'cancelled')
    - customer_id: filter by customer ID
    - timeframe: filter by time ('today', 'this_week', 'this_month', 'all')
    - q: search query across invoice number, customer name, and line items
    - limit: max records to return (default 20)
    """
    if q and q.strip():
        invoices = search_invoices(
            db, org_id=org_id, query=q.strip(), customer_id=customer_id, status=status, limit=limit
        )
    else:
        invoices = get_invoice_history(
            db,
            org_id=org_id,
            timeframe=timeframe,
            status=status,
            customer_id=customer_id,
            limit=limit,
        )
    return [
        {
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "customer": inv.customer.name if inv.customer else None,
            "customer_id": inv.customer_id,
            "subtotal": float(inv.subtotal),
            "tax": float(inv.tax),
            "total": float(inv.total),
            "currency": inv.currency,
            "status": inv.status,
            "pdf_url": inv.pdf_url,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
        }
        for inv in invoices
    ]


@app.get("/api/invoices/export")
def export_invoices_csv_api(
    org_id: int = 1,
    timeframe: str = "all",
    status: Optional[str] = None,
    customer_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """
    Export organization sales journal to CSV format per Cambodian GDT regulations.
    Supports filtering by timeframe ('today', 'this_week', 'this_month', 'all'), status, or customer.
    """
    invoices = get_invoice_history(
        db,
        org_id=org_id,
        timeframe=timeframe,
        status=status,
        customer_id=customer_id,
        limit=5000,
    )
    try:
        rate_info = resolve_exchange_rate()
    except Exception:
        rate_info = None

    csv_content = export_invoices_to_csv(invoices, exchange_rate_result=rate_info)
    filename = f"sales_journal_{timeframe}.csv"

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/invoices/stats")
@app.get("/api/stats")
def get_invoice_stats_api(org_id: int = 1, db: Session = Depends(get_db)):
    """
    Get aggregated financial stats and counts for an organization:
    - total_invoices: total count of all invoices
    - paid_count: number of paid invoices
    - sent_count: number of sent/unpaid invoices
    - cancelled_count: number of cancelled invoices
    - revenue_by_currency: dict with total paid amounts grouped by currency (USD, KHR)
    - outstanding_by_currency: dict with total unpaid amounts grouped by currency (USD, KHR)
    """
    all_invoices = get_invoice_history(db, org_id=org_id, timeframe="all", limit=1000)

    paid_count = 0
    sent_count = 0
    cancelled_count = 0
    revenue_by_currency: Dict[str, float] = {}
    outstanding_by_currency: Dict[str, float] = {}

    for inv in all_invoices:
        curr = inv.currency or "USD"
        tot = float(inv.total)
        if inv.status == "paid":
            paid_count += 1
            revenue_by_currency[curr] = round(revenue_by_currency.get(curr, 0.0) + tot, 2)
        elif inv.status == "sent":
            sent_count += 1
            outstanding_by_currency[curr] = round(outstanding_by_currency.get(curr, 0.0) + tot, 2)
        elif inv.status == "cancelled":
            cancelled_count += 1

    return {
        "org_id": org_id,
        "total_invoices": len(all_invoices),
        "paid_count": paid_count,
        "sent_count": sent_count,
        "cancelled_count": cancelled_count,
        "revenue_by_currency": revenue_by_currency,
        "outstanding_by_currency": outstanding_by_currency,
    }


@app.get("/api/customers")
def list_customers_api(
    org_id: int = 1,
    q: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List or search customers within an organization."""
    if q and q.strip():
        customers = find_customers_by_name(db, org_id=org_id, name_query=q.strip())
    else:
        stmt = select(Customer).where(Customer.org_id == org_id).order_by(Customer.name.asc()).limit(limit)
        customers = list(db.scalars(stmt).all())

    return [
        {
            "id": c.id,
            "name": c.name,
            "phone": c.phone,
            "telegram_id": c.telegram_id,
            "default_currency": c.default_currency,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in customers
    ]


@app.get("/api/customers/{customer_id}")
def get_customer_api(
    customer_id: int,
    org_id: int = 1,
    db: Session = Depends(get_db),
):
    """Get single customer details by ID."""
    cust = get_customer_by_id(db, customer_id=customer_id, org_id=org_id)
    if not cust:
        raise HTTPException(status_code=404, detail=f"Customer with id {customer_id} not found.")

    return {
        "id": cust.id,
        "name": cust.name,
        "phone": cust.phone,
        "telegram_id": cust.telegram_id,
        "default_currency": cust.default_currency,
        "created_at": cust.created_at.isoformat() if cust.created_at else None,
    }


@app.put("/api/customers/{customer_id}")
def update_customer_api(
    customer_id: int,
    customer_in: CustomerUpdate,
    org_id: int = 1,
    db: Session = Depends(get_db),
):
    """Update customer details via REST API."""
    try:
        updated = update_customer(
            db=db,
            customer_id=customer_id,
            org_id=org_id,
            customer_in=customer_in,
        )
        return {
            "id": updated.id,
            "name": updated.name,
            "phone": updated.phone,
            "telegram_id": updated.telegram_id,
            "default_currency": updated.default_currency,
            "created_at": updated.created_at.isoformat() if updated.created_at else None,
        }
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err))


@app.get("/api/customers/{customer_id}/invoices")
def get_customer_invoices_api(
    customer_id: int,
    org_id: int = 1,
    status: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Get all invoices for a specific customer."""
    cust = get_customer_by_id(db, customer_id=customer_id, org_id=org_id)
    if not cust:
        raise HTTPException(status_code=404, detail=f"Customer with id {customer_id} not found.")

    invoices = get_customer_invoices(db, customer_id=customer_id, org_id=org_id, status=status, limit=limit)
    return [
        {
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "subtotal": float(inv.subtotal),
            "tax": float(inv.tax),
            "total": float(inv.total),
            "currency": inv.currency,
            "status": inv.status,
            "pdf_url": inv.pdf_url,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
        }
        for inv in invoices
    ]


@app.get("/api/customers/{customer_id}/stats")
def get_customer_stats_api(
    customer_id: int,
    org_id: int = 1,
    db: Session = Depends(get_db),
):
    """Get lifetime billing metrics for a specific customer."""
    try:
        return get_customer_metrics(db=db, customer_id=customer_id, org_id=org_id)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err))


@app.post("/api/invoices/{invoice_number}/paid")
def mark_invoice_paid_api(
    invoice_number: str,
    org_id: int = 1,
    bank_transaction_ref: Optional[str] = None,
    payment_method: Optional[str] = "MANUAL",
    db: Session = Depends(get_db),
):
    """Mark an invoice as paid via REST API."""
    inv = get_invoice_by_number(db, invoice_number, org_id=org_id)
    if not inv:
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_number}' not found.")
    try:
        paid_inv = mark_as_paid(
            db=db,
            invoice_id=inv.id,
            org_id=org_id,
            bank_transaction_ref=bank_transaction_ref,
            payment_method=payment_method,
        )
        return {
            "status": "success",
            "message": f"Invoice {paid_inv.invoice_number} marked as paid.",
            "invoice_number": paid_inv.invoice_number,
            "status_code": paid_inv.status,
            "paid_at": paid_inv.paid_at.isoformat() if paid_inv.paid_at else None,
        }
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@app.post("/api/invoices/{invoice_number}/cancel")
def cancel_invoice_api(
    invoice_number: str,
    org_id: int = 1,
    db: Session = Depends(get_db),
):
    """Cancel an invoice via REST API."""
    inv = get_invoice_by_number(db, invoice_number, org_id=org_id)
    if not inv:
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_number}' not found.")
    try:
        cancelled_inv = cancel_invoice(db=db, invoice_id=inv.id, org_id=org_id)
        return {
            "status": "success",
            "message": f"Invoice {cancelled_inv.invoice_number} cancelled.",
            "invoice_number": cancelled_inv.invoice_number,
            "status_code": cancelled_inv.status,
        }
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


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
