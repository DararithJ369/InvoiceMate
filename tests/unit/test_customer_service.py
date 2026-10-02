from invoicemate.schemas.customer import CustomerCreate
from invoicemate.services.org_service import create_org
from invoicemate.services.customer_service import (
    create_customer,
    find_customers_by_name,
    get_customer_by_exact_name,
    get_or_create_customer,
    resolve_customer_name,
)


def test_create_and_find_customer(db_session):
    org = create_org(db_session, telegram_user_id="tg_cust_test1")
    cust_in = CustomerCreate(name="Bopha Mart", phone="+85512000111", default_currency="USD")
    cust = create_customer(db_session, org_id=org.id, customer_in=cust_in)
    assert cust.id is not None
    assert cust.org_id == org.id
    assert cust.name == "Bopha Mart"

    results = find_customers_by_name(db_session, org_id=org.id, name_query="bopha")
    assert len(results) == 1
    assert results[0].id == cust.id


def test_get_or_create_customer(db_session):
    org = create_org(db_session, telegram_user_id="tg_cust_test2")
    c1 = get_or_create_customer(db_session, org_id=org.id, name="Kravanh Co")
    assert c1.id is not None
    assert c1.org_id == org.id

    c2 = get_or_create_customer(db_session, org_id=org.id, name="Kravanh Co")
    assert c2.id == c1.id


def test_resolve_customer_name_ambiguity(db_session):
    org = create_org(db_session, telegram_user_id="tg_cust_test3")
    c1 = create_customer(db_session, org_id=org.id, customer_in=CustomerCreate(name="Sokha Computer Shop"))
    c2 = create_customer(db_session, org_id=org.id, customer_in=CustomerCreate(name="Sokha Telecom"))

    # Exact match -> resolved directly
    resolved, matches = resolve_customer_name(db_session, org_id=org.id, name_query="Sokha Computer Shop")
    assert resolved is not None
    assert resolved.id == c1.id
    assert len(matches) == 0

    # Partial query matching multiple -> disambiguation returned
    resolved_multi, matches_multi = resolve_customer_name(db_session, org_id=org.id, name_query="Sokha")
    assert resolved_multi is None
    assert len(matches_multi) == 2
