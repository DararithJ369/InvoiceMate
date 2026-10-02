from enum import Enum
from typing import List, Optional, Any
from pydantic import BaseModel, Field, field_validator

from invoicemate.models.enums import IntentEnum


class ExtractedItem(BaseModel):
    name: str = Field(..., description="Name of the product or service")
    qty: float = Field(default=1.0, gt=0, description="Quantity sold")
    unit_price: float = Field(default=0.0, ge=0, description="Unit price per item")

    @field_validator("name")
    def validate_name(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            return "Item"
        return cleaned

    @field_validator("unit_price", mode="before")
    def validate_unit_price(cls, v: Any) -> float:
        if v is None:
            return 0.0
        return float(v)

    @field_validator("qty", mode="before")
    def validate_qty(cls, v: Any) -> float:
        if v is None or float(v) <= 0:
            return 1.0
        return float(v)


class ExtractionPayload(BaseModel):
    intent: IntentEnum
    confidence: float = Field(default=0.95, ge=0.0, le=1.0)
    customer_name: Optional[str] = None
    items: List[ExtractedItem] = Field(default_factory=list)
    due_date: Optional[str] = None
    currency: Optional[str] = None
    search_query: Optional[str] = None
    clarification_question: Optional[str] = None


# Alias for backwards compatibility
LLMExtractionResult = ExtractionPayload
