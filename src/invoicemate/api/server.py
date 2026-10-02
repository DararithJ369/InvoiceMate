import os
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from invoicemate.core.config import settings
from invoicemate.db import init_db, SessionLocal
from invoicemate.services.invoice_engine import get_invoice_history, get_invoice_by_number

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


@app.get("/pdf/{token}/{filename}")
def serve_secure_invoice_pdf(token: str, filename: str):
    """
    Serve generated PDF invoice via cryptographically unguessable token path.
    Example: GET /pdf/a8f3b9d2.../INV-000001.pdf
    """
    safe_token = os.path.basename(token)
    safe_filename = os.path.basename(filename)

    file_path = os.path.join(settings.STORAGE_DIR, safe_token, safe_filename)
    if not os.path.exists(file_path):
        # Fallback check directly in root storage
        file_path = os.path.join(settings.STORAGE_DIR, safe_filename)

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
    file_path = os.path.join(settings.STORAGE_DIR, safe_filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"PDF invoice '{safe_filename}' not found.")

    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=safe_filename,
        headers={"Content-Disposition": f"inline; filename={safe_filename}"},
    )


@app.get("/api/invoices")
def list_invoices_api(limit: int = 20, org_id: int = 1):
    """List recent invoices via REST API scoped by org_id."""
    with SessionLocal() as db:
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
                "created_at": inv.created_at.isoformat(),
            }
            for inv in invoices
        ]


@app.get("/api/invoices/{invoice_number}")
def get_invoice_api(invoice_number: str, org_id: int = 1):
    """Get single invoice details by invoice number via REST API."""
    with SessionLocal() as db:
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
            "created_at": inv.created_at.isoformat(),
        }


def run_server():
    """CLI entrypoint to run FastAPI PDF Hosting Server."""
    init_db()
    print(f"🚀 Starting InvoiceMate PDF Hosting & REST API Server on http://{settings.HOST}:{settings.PORT}")
    uvicorn.run("invoicemate.api.server:app", host=settings.HOST, port=settings.PORT, reload=False)


if __name__ == "__main__":
    run_server()
