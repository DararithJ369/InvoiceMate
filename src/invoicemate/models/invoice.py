from datetime import datetime, date
from decimal import Decimal
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import String, Numeric, DateTime, Date, ForeignKey, Text, Integer, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from invoicemate.models.base import Base
from invoicemate.models.enums import InvoiceStatus, PdfStatus

if TYPE_CHECKING:
    from invoicemate.models.org import Org
    from invoicemate.models.customer import Customer
    from invoicemate.models.invoice_item import InvoiceItem
    from invoicemate.models.invoice_event import InvoiceEvent


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice_number: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    customer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    tax: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default=InvoiceStatus.SENT.value, nullable=False, index=True
    )
    payment_reference: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    pdf_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pdf_status: Mapped[str] = mapped_column(
        String(20), default=PdfStatus.PENDING.value, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    org: Mapped["Org"] = relationship("Org", back_populates="invoices")
    customer: Mapped[Optional["Customer"]] = relationship("Customer", back_populates="invoices")
    items: Mapped[List["InvoiceItem"]] = relationship(
        "InvoiceItem", back_populates="invoice", cascade="all, delete-orphan"
    )
    events: Mapped[List["InvoiceEvent"]] = relationship(
        "InvoiceEvent", back_populates="invoice", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("org_id", "invoice_number", name="uq_invoices_org_invoice_number"),
        Index("idx_invoices_org_created", "org_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Invoice(id={self.id}, org_id={self.org_id}, number='{self.invoice_number}', total={self.total} {self.currency}, status='{self.status}')>"
