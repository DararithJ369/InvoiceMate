from datetime import datetime
from typing import Optional, Dict, Any, TYPE_CHECKING
from sqlalchemy import DateTime, Text, Integer, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from invoicemate.models.base import Base

if TYPE_CHECKING:
    from invoicemate.models.invoice import Invoice


class InvoiceEvent(Base):
    __tablename__ = "invoice_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="events")

    def __repr__(self) -> str:
        return f"<InvoiceEvent(id={self.id}, invoice_id={self.invoice_id}, event_type='{self.event_type}')>"
