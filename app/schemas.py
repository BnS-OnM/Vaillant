from pydantic import BaseModel
from typing import List, Optional

class OrderLine(BaseModel):
    product_code: Optional[str]
    description: str
    quantity: float
    unit_price: float
    tax_percent: float

class Quotation(BaseModel):
    currency: str
    lines: List[OrderLine]

class Customer(BaseModel):
    name: str
    email: Optional[str] = None

class GPTResponse(BaseModel):
    customer: Customer
    quotation: Quotation
