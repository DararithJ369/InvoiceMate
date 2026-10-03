import sqlite3
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from invoicemate.core.config import settings
from invoicemate.models.base import Base

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    connect_args["timeout"] = 30.0

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=settings.SQL_ECHO,
)


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable foreign key constraints and WAL journal mode for SQLite."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass
        cursor.close()


def init_db(bind_engine=None) -> None:
    """Initialize database tables and apply lightweight missing column migrations."""
    from sqlalchemy import text
    target_engine = bind_engine or engine
    Base.metadata.create_all(bind=target_engine)

    if settings.DATABASE_URL.startswith("sqlite"):
        with target_engine.connect() as conn:
            try:
                res = conn.execute(text("PRAGMA table_info(customers)")).fetchall()
                col_names = [r[1] for r in res]
                if "location" not in col_names:
                    conn.execute(text("ALTER TABLE customers ADD COLUMN location TEXT DEFAULT 'ភ្នំពេញ / Phnom Penh'"))
                    conn.commit()
            except Exception:
                pass

            try:
                res = conn.execute(text("PRAGMA table_info(invoice_items)")).fetchall()
                col_names = [r[1] for r in res]
                if "note" not in col_names:
                    conn.execute(text("ALTER TABLE invoice_items ADD COLUMN note TEXT"))
                    conn.commit()
            except Exception:
                pass

            try:
                res = conn.execute(text("PRAGMA table_info(invoices)")).fetchall()
                col_names = [r[1] for r in res]
                if "payment_method" not in col_names:
                    conn.execute(text("ALTER TABLE invoices ADD COLUMN payment_method VARCHAR(50) DEFAULT 'BAKONG_KHQR'"))
                if "khqr_md5" not in col_names:
                    conn.execute(text("ALTER TABLE invoices ADD COLUMN khqr_md5 VARCHAR(64)"))
                if "bank_transaction_ref" not in col_names:
                    conn.execute(text("ALTER TABLE invoices ADD COLUMN bank_transaction_ref VARCHAR(100)"))
                if "payment_metadata" not in col_names:
                    conn.execute(text("ALTER TABLE invoices ADD COLUMN payment_metadata JSON"))
                conn.commit()
            except Exception:
                pass

