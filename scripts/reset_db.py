#!/usr/bin/env python3
"""
Database reset and cleaning utility for InvoiceMate.
Usage:
    uv run python scripts/reset_db.py             # Reset database tables (empty)
    uv run python scripts/reset_db.py --seed      # Reset database and seed demo data
    uv run python scripts/reset_db.py --all       # Reset database + clear storage/invoices
"""

import os
import sys
import glob
import argparse
from invoicemate.db.database import engine, init_db
from invoicemate.db.session import SessionLocal
from invoicemate.models.base import Base
from invoicemate.services.seeder import seed_database
from invoicemate.core.config import settings


def reset_database(seed: bool = False, clear_storage: bool = False):
    print(f"Connecting to database: {settings.DATABASE_URL}")

    # 1. Drop and recreate all tables
    print("Dropping existing tables...")
    Base.metadata.drop_all(bind=engine)
    print("Recreating clean tables...")
    init_db(bind_engine=engine)
    print("Database schema successfully recreated!")

    # 2. Optionally seed demo records
    if seed:
        print("Seeding demo organizations, customers, and invoices...")
        db = SessionLocal()
        try:
            res = seed_database(db, telegram_user_id="seed_admin")
            print(f"Seed complete: {res}")
        finally:
            db.close()

    # 3. Optionally clean generated PDF files
    if clear_storage:
        pdf_dir = settings.STORAGE_DIR
        print(f"Cleaning generated invoice storage: {pdf_dir}...")
        for pattern in [os.path.join(pdf_dir, "*.pdf"), os.path.join(pdf_dir, "qr", "*.png")]:
            for f in glob.glob(pattern):
                try:
                    os.remove(f)
                except Exception:
                    pass
        print("Storage cleaned.")

    print("\nDatabase reset successfully finished!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="InvoiceMate Database Reset Utility")
    parser.add_argument("--seed", action="store_true", help="Seed default demo customers & invoices")
    parser.add_argument("--clear-storage", action="store_true", help="Delete generated PDFs & QR images")
    parser.add_argument("--all", action="store_true", help="Reset DB, seed demo data, and clear storage")

    args = parser.parse_args()

    do_seed = args.seed or args.all
    do_clear = args.clear_storage or args.all

    reset_database(seed=do_seed, clear_storage=do_clear)
