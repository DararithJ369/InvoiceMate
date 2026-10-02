from typing import Generator
from sqlalchemy.orm import sessionmaker, Session
from invoicemate.db.database import engine

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db(session_factory=SessionLocal) -> Generator[Session, None, None]:
    """Dependency / context provider for DB session."""
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
