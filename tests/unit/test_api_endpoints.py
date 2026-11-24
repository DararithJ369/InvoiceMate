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


def test_invoice_filtering_and_stats_api(api_client, db_session):
    org = create_org(db_session, telegram_user_id="tg_filter_stats_user")
    cust = Customer(org_id=org.id, name="Bopha Silk Shop")
    db_session.add(cust)
    db_session.flush()

    inv1 = Invoice(
        org_id=org.id,
        invoice_number="INV-001001",
        customer_id=cust.id,
        subtotal=Decimal("100.00"),
        tax=Decimal("10.00"),
        total=Decimal("110.00"),
        currency="USD",
        status=InvoiceStatus.SENT.value,
        items=[InvoiceItem(product_name="Silk Scarf", quantity=Decimal("2"), unit_price=Decimal("50.00"), line_total=Decimal("100.00"))],
    )
    inv2 = Invoice(
        org_id=org.id,
        invoice_number="INV-001002",
        customer_id=cust.id,
        subtotal=Decimal("200000"),
        tax=Decimal("0"),
        total=Decimal("200000"),
        currency="KHR",
        status=InvoiceStatus.PAID.value,
        items=[InvoiceItem(product_name="Khmer Fabric", quantity=Decimal("1"), unit_price=Decimal("200000"), line_total=Decimal("200000"))],
    )
    db_session.add_all([inv1, inv2])
    db_session.commit()

    # 1. Filter by status=sent
    res_sent = api_client.get(f"/api/invoices?org_id={org.id}&status=sent")
    assert res_sent.status_code == 200
    sent_list = res_sent.json()
    assert len(sent_list) == 1
    assert sent_list[0]["invoice_number"] == "INV-001001"

    # 2. Filter by status=paid
    res_paid = api_client.get(f"/api/invoices?org_id={org.id}&status=paid")
    assert res_paid.status_code == 200
    paid_list = res_paid.json()
    assert len(paid_list) == 1
    assert paid_list[0]["invoice_number"] == "INV-001002"

    # 3. Search query ?q=Fabric
    res_q = api_client.get(f"/api/invoices?org_id={org.id}&q=Fabric")
    assert res_q.status_code == 200
    q_list = res_q.json()
    assert len(q_list) == 1
    assert q_list[0]["invoice_number"] == "INV-001002"

    # 4. Aggregated stats endpoint
    res_stats = api_client.get(f"/api/invoices/stats?org_id={org.id}")
    assert res_stats.status_code == 200
    stats = res_stats.json()
    assert stats["total_invoices"] == 2
    assert stats["sent_count"] == 1
    assert stats["paid_count"] == 1
    assert stats["cancelled_count"] == 0
    assert stats["outstanding_by_currency"]["USD"] == 110.00
    assert stats["revenue_by_currency"]["KHR"] == 200000.0


def test_customers_api_endpoints(api_client, db_session):
    org = create_org(db_session, telegram_user_id="tg_cust_api_user")
    c1 = Customer(org_id=org.id, name="Sokha Retail", phone="+85511223344", default_currency="USD")
    c2 = Customer(org_id=org.id, name="Dara Services", phone="+85577889900", default_currency="KHR")
    db_session.add_all([c1, c2])
    db_session.commit()

    # List all customers
    res_all = api_client.get(f"/api/customers?org_id={org.id}")
    assert res_all.status_code == 200
    custs = res_all.json()
    assert len(custs) == 2

    # Search customer by query ?q=Dara
    res_search = api_client.get(f"/api/customers?org_id={org.id}&q=Dara")
    assert res_search.status_code == 200
    dara_results = res_search.json()
    assert len(dara_results) == 1
    assert dara_results[0]["name"] == "Dara Services"

    # Get single customer by ID
    res_get = api_client.get(f"/api/customers/{c1.id}?org_id={org.id}")
    assert res_get.status_code == 200
    assert res_get.json()["name"] == "Sokha Retail"
    assert res_get.json()["phone"] == "+85511223344"

    # Get non-existent customer returns 404
    res_404 = api_client.get(f"/api/customers/999999?org_id={org.id}")
    assert res_404.status_code == 404


def test_invoice_actions_api(api_client, db_session):
    org = create_org(db_session, telegram_user_id="tg_action_api_user")
    inv = Invoice(
        org_id=org.id,
        invoice_number="INV-002001",
        subtotal=Decimal("300.00"),
        tax=Decimal("0.00"),
        total=Decimal("300.00"),
        currency="USD",
        status=InvoiceStatus.SENT.value,
        items=[InvoiceItem(product_name="Design System", quantity=Decimal("1"), unit_price=Decimal("300.00"), line_total=Decimal("300.00"))],
    )
    db_session.add(inv)
    db_session.commit()

    # 1. Mark paid via REST API
    res_paid = api_client.post(
        f"/api/invoices/INV-002001/paid?org_id={org.id}&bank_transaction_ref=BANK-REF-999"
    )
    assert res_paid.status_code == 200
    data_paid = res_paid.json()
    assert data_paid["status"] == "success"
    assert data_paid["invoice_number"] == "INV-002001"

    # Verify db status is paid
    db_session.refresh(inv)
    assert inv.status == "paid"
    assert inv.bank_transaction_ref == "BANK-REF-999"

    # 2. Non-existent invoice returns 404
    res_paid_404 = api_client.post(f"/api/invoices/INV-NONEXIST/paid?org_id={org.id}")
    assert res_paid_404.status_code == 404

    # 3. Cancel another invoice via REST API
    inv_cancel = Invoice(
        org_id=org.id,
        invoice_number="INV-002002",
        subtotal=Decimal("50.00"),
        tax=Decimal("0.00"),
        total=Decimal("50.00"),
        currency="USD",
        status=InvoiceStatus.SENT.value,
        items=[InvoiceItem(product_name="Domain registration", quantity=Decimal("1"), unit_price=Decimal("50.00"), line_total=Decimal("50.00"))],
    )
    db_session.add(inv_cancel)
    db_session.commit()

    res_cancel = api_client.post(f"/api/invoices/INV-002002/cancel?org_id={org.id}")
    assert res_cancel.status_code == 200
    assert res_cancel.json()["status"] == "success"

    db_session.refresh(inv_cancel)
    assert inv_cancel.status == "cancelled"


def test_export_invoices_csv_api(api_client, db_session):
    org = create_org(db_session, telegram_user_id="tg_export_api_user")
    inv = Invoice(
        org_id=org.id,
        invoice_number="INV-003001",
        subtotal=Decimal("120.00"),
        tax=Decimal("12.00"),
        total=Decimal("132.00"),
        currency="USD",
        status=InvoiceStatus.SENT.value,
        items=[InvoiceItem(product_name="Consulting", quantity=Decimal("1"), unit_price=Decimal("120.00"), line_total=Decimal("120.00"))],
    )
    db_session.add(inv)
    db_session.commit()

    res = api_client.get(f"/api/invoices/export?org_id={org.id}&timeframe=all")
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    assert "attachment; filename=sales_journal_all.csv" in res.headers["content-disposition"]
    text = res.text
    assert "Invoice Number" in text
    assert "INV-003001" in text
    assert "132.00" in text


