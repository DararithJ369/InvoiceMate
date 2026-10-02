from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from sqlalchemy import Numeric, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from invoicemate.models.base import Base

if TYPE_CHECKING:
    from invoicemate.models.invoice import Invoice


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_name: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="items")

    def __repr__(self) -> str:
        return f"<InvoiceItem(id={self.id}, product='{self.product_name}', qty={self.quantity}, line_total={self.line_total})>"
