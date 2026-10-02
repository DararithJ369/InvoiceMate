from datetime import datetime, date
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field
from invoicemate.models.enums import InvoiceStatus
from invoicemate.schemas.customer import CustomerRead


class InvoiceItemBase(BaseModel):
    product_name: str
    quantity: Decimal = Field(..., gt=0)
    unit_price: Decimal = Field(..., ge=0)


class InvoiceItemCreate(InvoiceItemBase):
    pass


class InvoiceItemRead(InvoiceItemBase):
    id: int
    invoice_id: int
    line_total: Decimal

    model_config = ConfigDict(from_attributes=True)


class InvoiceBase(BaseModel):
    currency: str = "USD"
    due_date: Optional[date] = None
    status: InvoiceStatus = InvoiceStatus.DRAFT


class InvoiceCreate(InvoiceBase):
    customer_id: Optional[int] = None
    items: List[InvoiceItemCreate] = []
    tax_rate: Decimal = Field(default=Decimal("0.00"), ge=0)


class InvoiceRead(InvoiceBase):
    id: int
    invoice_number: str
    customer_id: Optional[int] = None
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    pdf_url: Optional[str] = None
    created_at: datetime
    customer: Optional[CustomerRead] = None
    items: List[InvoiceItemRead] = []

    model_config = ConfigDict(from_attributes=True)
