import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from app.auth import get_current_user_id
from app.database import supabase
from app.config import settings

router = APIRouter(prefix="/api/calls", tags=["calls"])


def get_shop_by_owner(owner_id: str):
    r = supabase.table("shops").select("id").eq("clerk_user_id", owner_id).execute()
    return r.data[0] if r.data else None


@router.post("/inbound")
async def inbound_call(request: Request):
    form_data = await request.form()
    from_number = form_data.get("From", "")
    to_number = form_data.get("To", "")

    r = supabase.table("shops").select("retell_agent_id").eq("phone_number", to_number).execute()
    if r.data and r.data[0].get("retell_agent_id"):
        agent_id = r.data[0]["retell_agent_id"]
        elevenlabs_url = f"https://api.elevenlabs.io/v1/convai/twilio/inbound_calls?agent_id={agent_id}"
    else:
        elevenlabs_url = "https://api.elevenlabs.io/v1/convai/twilio/inbound_calls"

    twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{elevenlabs_url}" />
    </Connect>
</Response>'''
    return Response(content=twiml, media_type="application/xml")


@router.get("/")
async def list_calls(
    user_id: str = Depends(get_current_user_id),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    shop = get_shop_by_owner(user_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    r = supabase.table("calls").select("*").eq("shop_id", shop["id"]).order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return {"calls": r.data, "total": len(r.data)}


@router.get("/stats/summary")
async def call_stats(user_id: str = Depends(get_current_user_id)):
    shop = get_shop_by_owner(user_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    calls = supabase.table("calls").select("status,appointment_booked,duration_seconds").eq("shop_id", shop["id"]).execute()
    t = len(calls.data)
    a = sum(1 for c in calls.data if c.get("appointment_booked"))
    avg = sum(c.get("duration_seconds", 0) for c in calls.data) / t if t else 0
    return {"total_calls": t, "appointments_booked": a, "conversion_rate": round(a / t * 100, 1) if t else 0, "avg_duration_seconds": round(avg)}


@router.get("/{call_id}")
async def get_call(call_id: str, user_id: str = Depends(get_current_user_id)):
    shop = get_shop_by_owner(user_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    r = supabase.table("calls").select("*,appointments(*)").eq("id", call_id).eq("shop_id", shop["id"]).execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="Call not found")
    return r.data[0]
