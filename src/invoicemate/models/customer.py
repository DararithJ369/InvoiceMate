from datetime import datetime
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import String, DateTime, Text, Integer, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from invoicemate.models.base import Base

if TYPE_CHECKING:
    from invoicemate.models.org import Org
    from invoicemate.models.invoice import Invoice
    from invoicemate.models.draft import Draft


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    phone: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    location: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default="ភ្នំពេញ / Phnom Penh")
    telegram_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True)
    default_currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    org: Mapped["Org"] = relationship("Org", back_populates="customers")
    invoices: Mapped[List["Invoice"]] = relationship(
        "Invoice", back_populates="customer", passive_deletes="all"
    )
    drafts: Mapped[List["Draft"]] = relationship(
        "Draft", back_populates="customer"
    )

    def __repr__(self) -> str:
        return f"<Customer(id={self.id}, org_id={self.org_id}, name='{self.name}', currency='{self.default_currency}')>"
