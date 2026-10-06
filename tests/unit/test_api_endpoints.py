import os
import tempfile
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient

from invoicemate.api.server import app, get_db
from invoicemate.core.config import settings
from invoicemate.models.customer import Customer
from invoicemate.models.enums import InvoiceStatus
from invoicemate.models.invoice import Invoice
from invoicemate.models.invoice_item import InvoiceItem
from invoicemate.services.org_service import create_org


@pytest.fixture
def api_client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_health_check_endpoint(api_client):
    res = api_client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["app"] == settings.PROJECT_NAME


def test_list_and_get_invoices_api(api_client, db_session):
    org = create_org(db_session, telegram_user_id="tg_api_user_test")
    cust = Customer(org_id=org.id, name="Angkor Software Co.")
    db_session.add(cust)
    db_session.flush()

    inv = Invoice(
        org_id=org.id,
        invoice_number="INV-009999",
        customer_id=cust.id,
        subtotal=Decimal("500.00"),
        tax=Decimal("50.00"),
        total=Decimal("550.00"),
        currency="USD",
        status=InvoiceStatus.SENT.value,
        items=[
            InvoiceItem(
                product_name="Cloud Hosting Setup",
                quantity=Decimal("1"),
                unit_price=Decimal("500.00"),
                line_total=Decimal("500.00"),
            )
        ],
    )
    db_session.add(inv)
    db_session.commit()

    # 1. List invoices
    res_list = api_client.get(f"/api/invoices?org_id={org.id}")
    assert res_list.status_code == 200
    items = res_list.json()
    assert len(items) == 1
    assert items[0]["invoice_number"] == "INV-009999"
    assert items[0]["total"] == 550.00
    assert items[0]["customer"] == "Angkor Software Co."

    # 2. Get single invoice by exact uppercase number
    res_get = api_client.get(f"/api/invoices/INV-009999?org_id={org.id}")
    assert res_get.status_code == 200
    data = res_get.json()
    assert data["invoice_number"] == "INV-009999"
    assert data["subtotal"] == 500.00
    assert len(data["items"]) == 1
    assert data["items"][0]["product_name"] == "Cloud Hosting Setup"

    # 3. Get single invoice case-insensitively (lowercase 'inv-009999')
    res_case = api_client.get(f"/api/invoices/inv-009999?org_id={org.id}")
    assert res_case.status_code == 200
    assert res_case.json()["invoice_number"] == "INV-009999"

    # 4. Get non-existent invoice returns 404
    res_404 = api_client.get(f"/api/invoices/INV-NONEXISTENT?org_id={org.id}")
    assert res_404.status_code == 404


def test_serve_pdf_endpoints(api_client, monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_dir:
        monkeypatch.setattr(settings, "STORAGE_DIR", tmp_dir)

        # Create dummy PDF in storage directory
        token = "sec_token_123"
        token_dir = os.path.join(tmp_dir, token)
        os.makedirs(token_dir, exist_ok=True)
        pdf_file = os.path.join(token_dir, "INV-000001.pdf")
        with open(pdf_file, "wb") as f:
            f.write(b"%PDF-1.4 mock content")

        # Also create root PDF
        root_pdf = os.path.join(tmp_dir, "INV-000002.pdf")
        with open(root_pdf, "wb") as f:
            f.write(b"%PDF-1.4 root content")

        # 1. Secure token path - exact match
        res1 = api_client.get(f"/pdf/{token}/INV-000001.pdf")
        assert res1.status_code == 200
        assert res1.headers["content-type"] == "application/pdf"

        # 2. Secure token path - case-insensitive uppercase fallback
        res2 = api_client.get(f"/pdf/{token}/inv-000001.pdf")
        assert res2.status_code == 200

        # 3. Secure token path - non-pdf extension rejected with 400
        res_bad_ext = api_client.get(f"/pdf/{token}/INV-000001.txt")
        assert res_bad_ext.status_code == 400

        # 4. Secure token path - non-existent returns 404
        res_404 = api_client.get(f"/pdf/{token}/INV-999999.pdf")
        assert res_404.status_code == 404

        # 5. Direct invoice path - exact match
        res_direct = api_client.get("/invoices/INV-000002.pdf")
        assert res_direct.status_code == 200

        # 6. Direct invoice path - case-insensitive
        res_direct_case = api_client.get("/invoices/inv-000002.pdf")
        assert res_direct_case.status_code == 200

        # 7. Direct invoice path - non-pdf rejected with 400
        res_direct_bad = api_client.get("/invoices/test.db")
        assert res_direct_bad.status_code == 400

        # 8. Direct invoice path - 404
        res_direct_404 = api_client.get("/invoices/INV-NONE.pdf")
        assert res_direct_404.status_code == 404
