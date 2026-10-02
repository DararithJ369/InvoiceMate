from datetime import datetime
from typing import Optional, Dict, Any, TYPE_CHECKING
from sqlalchemy import DateTime, Text, Integer, ForeignKey, JSON, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from invoicemate.models.base import Base
from invoicemate.models.enums import DraftState

if TYPE_CHECKING:
    from invoicemate.models.org import Org
    from invoicemate.models.customer import Customer


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chat_id: Mapped[str] = mapped_column(Text, nullable=False)
    customer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    draft_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    state: Mapped[str] = mapped_column(Text, nullable=False, default=DraftState.DRAFTING.value)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    org: Mapped["Org"] = relationship("Org", back_populates="drafts")
    customer: Mapped[Optional["Customer"]] = relationship("Customer", back_populates="drafts")

    __table_args__ = (
        Index("idx_drafts_org_chat", "org_id", "chat_id"),
    )

    def __repr__(self) -> str:
        return f"<Draft(id={self.id}, org_id={self.org_id}, chat_id='{self.chat_id}', state='{self.state}')>"
