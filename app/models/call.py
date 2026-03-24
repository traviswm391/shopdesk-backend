from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class AppointmentDetails(BaseModel):
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    vehicle_info: Optional[str] = None
    service_requested: Optional[str] = None
    preferred_date: Optional[str] = None
    preferred_time: Optional[str] = None
    notes: Optional[str] = None

class Call(BaseModel):
    id: str
    shop_id: str
    retell_call_id: Optional[str] = None
    caller_number: Optional[str] = None
    duration_seconds: Optional[int] = None
    transcript: Optional[str] = None
    summary: Optional[str] = None
    appointment_booked: bool = False
    appointment_details: Optional[AppointmentDetails] = None
    recording_url: Optional[str] = None
    status: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

class RetellCallEndedPayload(BaseModel):
    event: str
    call: dict
