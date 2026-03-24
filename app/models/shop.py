from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class BusinessHours(BaseModel):
    open: str = "08:00"
    close: str = "17:00"
    closed: bool = False

class ShopCreate(BaseModel):
    name: str
    address: Optional[str] = None
    phone_display: Optional[str] = None  # shop's existing public phone (not Twilio)
    services: Optional[list[str]] = None
    business_hours: Optional[dict] = None
    greeting: Optional[str] = None

class ShopUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    phone_display: Optional[str] = None
    services: Optional[list[str]] = None
    business_hours: Optional[dict] = None
    greeting: Optional[str] = None

class Shop(BaseModel):
    id: str
    owner_id: str
    name: str
    phone_number: Optional[str] = None
    retell_agent_id: Optional[str] = None
    address: Optional[str] = None
    phone_display: Optional[str] = None
    services: Optional[list[str]] = None
    business_hours: Optional[dict] = None
    greeting: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    subscription_status: str = "inactive"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
