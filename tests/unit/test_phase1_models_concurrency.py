import concurrent.futures
from decimal import Decimal
import os
import sqlite3
import tempfile
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from invoicemate.models import (
    Base,
    Org,
    OrgInvoiceCounter,
    Customer,
    Draft,
    Invoice,
    InvoiceItem,
    InvoiceEvent,
    InvoiceStatus,
)
from invoicemate.services.org_service import create_org, get_or_create_org
from invoicemate.services.customer_service import (
    create_customer,
    find_customers_by_name,
    get_customer_by_exact_name,
    resolve_customer_name,
)
from invoicemate.schemas.customer import CustomerCreate
from invoicemate.services.numbering import assign_next_invoice_number, parse_invoice_number


def test_org_creation_and_counter_seeding(db_session):
    """Verify org creation automatically seeds org_invoice_counters to 0."""
    org = create_org(
        db_session,
        telegram_user_id="tg_user_100",
        business_name="Angkor Tech Solutions",
        phone="+85512345678",
    )
    assert org.id is not None
    assert org.telegram_user_id == "tg_user_100"

    counter = db_session.get(OrgInvoiceCounter, org.id)
    assert counter is not None
    assert counter.current_value == 0


def test_multi_tenant_isolation(db_session):
    """Verify customers and queries are strictly isolated by org_id."""
    org1 = create_org(db_session, telegram_user_id="user_tenant_1", business_name="Org 1")
    org2 = create_org(db_session, telegram_user_id="user_tenant_2", business_name="Org 2")

    # Both orgs create a customer with the same name "Sokha"
    c1 = create_customer(db_session, org_id=org1.id, customer_in=CustomerCreate(name="Sokha"))
    c2 = create_customer(db_session, org_id=org2.id, customer_in=CustomerCreate(name="Sokha"))

    assert c1.id != c2.id
    assert c1.org_id == org1.id
    assert c2.org_id == org2.id

    # Org1 queries for Sokha
    results_org1 = find_customers_by_name(db_session, org_id=org1.id, name_query="Sokha")
    assert len(results_org1) == 1
    assert results_org1[0].id == c1.id

    # Org2 queries for Sokha
    results_org2 = find_customers_by_name(db_session, org_id=org2.id, name_query="Sokha")
    assert len(results_org2) == 1
    assert results_org2[0].id == c2.id

    # Cross-tenant query attempt returns empty
    results_cross = find_customers_by_name(db_session, org_id=org1.id, name_query="NonExistentInOrg1")
    assert len(results_cross) == 0


def test_customer_deletion_restricted_when_invoices_exist(db_session):
    """
    Verify foreign key constraint ON DELETE RESTRICT on invoices.customer_id.
    Prevents customer deletion from deleting or orphaning historical invoices (Prakas 723 10-year rule).
    """
    org = create_org(db_session, telegram_user_id="user_restrict_test")
    cust = create_customer(db_session, org_id=org.id, customer_in=CustomerCreate(name="Legal Entity"))

    inv = Invoice(
        org_id=org.id,
        invoice_number="INV-000001",
        customer_id=cust.id,
        subtotal=Decimal("100.00"),
        tax=Decimal("10.00"),
        total=Decimal("110.00"),
        status=InvoiceStatus.SENT.value,
    )
    db_session.add(inv)
    db_session.commit()

    # Attempting to delete the customer must fail with IntegrityError
    db_session.delete(cust)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_concurrent_invoice_sequence_assignment():
    """
    Phase 1 Validation Gate:
    Proves that simultaneous confirmation requests within the same organization
    produce consecutive invoice numbers with zero duplicates and zero race conditions.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    test_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )

    @event.listens_for(test_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        if isinstance(dbapi_connection, sqlite3.Connection):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    Base.metadata.create_all(bind=test_engine)
    Session = sessionmaker(bind=test_engine)

    try:
        # Create single organization
        with Session() as db:
            org = Org(telegram_user_id="tg_concurrent_org", business_name="Concurrent Test Corp")
            db.add(org)
            db.flush()
            counter = OrgInvoiceCounter(org_id=org.id, current_value=0)
            db.add(counter)
            db.commit()
            org_id = org.id

        total_requests = 20
        results = []

        def worker():
            with Session() as session:
                with session.begin():
                    num = assign_next_invoice_number(session, org_id=org_id)
                    return num

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(worker) for _ in range(total_requests)]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())

        # Verify results
        assert len(results) == total_requests
        assert len(set(results)) == total_requests, "Duplicate invoice numbers detected under concurrency!"

        numbers = sorted([parse_invoice_number(num) for num in results])
        expected_numbers = list(range(1, total_requests + 1))
        assert numbers == expected_numbers, f"Invoice sequence was not consecutive: {numbers}"

        with Session() as db:
            final_counter = db.get(OrgInvoiceCounter, org_id)
            assert final_counter.current_value == total_requests

    finally:
        test_engine.dispose()
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass
