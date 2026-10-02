from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class CustomerBase(BaseModel):
    name: str
    phone: Optional[str] = None
    telegram_id: Optional[str] = None
    default_currency: str = "USD"


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    telegram_id: Optional[str] = None
    default_currency: Optional[str] = None


class CustomerRead(CustomerBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
