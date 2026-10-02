from invoicemate.models.customer import Customer
from invoicemate.models.invoice import Invoice
from invoicemate.models.org import Org
from invoicemate.services.seeder import seed_database


def test_seed_database(db_session):
    res = seed_database(db_session)
    assert res["status"] == "success"
    assert res["customers_count"] == 4
    assert res["invoices_count"] == 3
    assert res["org_id"] is not None

    org = db_session.get(Org, res["org_id"])
    assert org is not None

    customers = db_session.query(Customer).filter_by(org_id=res["org_id"]).all()
    assert len(customers) == 4

    invoices = db_session.query(Invoice).filter_by(org_id=res["org_id"]).all()
    assert len(invoices) == 3

    inv1 = db_session.query(Invoice).filter_by(invoice_number="INV-000001").first()
    assert inv1 is not None
    assert len(inv1.items) == 2


def test_seed_database_idempotent(db_session):
    seed_database(db_session)
    res2 = seed_database(db_session)
    assert res2["status"] == "skipped"
    assert db_session.query(Customer).count() == 4
