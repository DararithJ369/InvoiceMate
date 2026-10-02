from datetime import datetime
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import String, DateTime, Text, Integer, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from invoicemate.models.base import Base

if TYPE_CHECKING:
    from invoicemate.models.customer import Customer
    from invoicemate.models.draft import Draft
    from invoicemate.models.invoice import Invoice


class Org(Base):
    __tablename__ = "orgs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    business_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    counter: Mapped[Optional["OrgInvoiceCounter"]] = relationship(
        "OrgInvoiceCounter", back_populates="org", uselist=False, cascade="all, delete-orphan"
    )
    customers: Mapped[List["Customer"]] = relationship(
        "Customer", back_populates="org", cascade="all, delete-orphan"
    )
    drafts: Mapped[List["Draft"]] = relationship(
        "Draft", back_populates="org", cascade="all, delete-orphan"
    )
    invoices: Mapped[List["Invoice"]] = relationship(
        "Invoice", back_populates="org", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Org(id={self.id}, telegram_user_id='{self.telegram_user_id}', business_name='{self.business_name}')>"


class OrgInvoiceCounter(Base):
    __tablename__ = "org_invoice_counters"

    org_id: Mapped[int] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), primary_key=True
    )
    current_value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    org: Mapped["Org"] = relationship("Org", back_populates="counter")

    def __repr__(self) -> str:
        return f"<OrgInvoiceCounter(org_id={self.org_id}, current_value={self.current_value})>"
