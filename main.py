from invoicemate.db import init_db, SessionLocal
from invoicemate.services.seeder import seed_database


def main():
    print("Initializing InvoiceMate database...")
    init_db()
    with SessionLocal() as db:
        res = seed_database(db)
        print(f"Seeding completed: {res}")
    print("Database ready!")


if __name__ == "__main__":
    main()
