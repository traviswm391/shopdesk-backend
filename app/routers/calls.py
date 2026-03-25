import httpx
from fastapi import APIRouter, HTTPException, Header, Query, Request, Response
from app.database import supabase
from app.config import settings

router = APIRouter(prefix="/api/calls", tags=["calls"])

def get_shop_by_owner(owner_id):
    r = supabase.table("shops").select("id").eq("clerk_user_id", owner_id).execute()
    return r.data[0] if r.data else None

@router.post("/inbound")
async def inbound_call(request: Request):
    form_data = await request.form()
    from_number = form_data.get("From", "")
    to_number = form_data.get("To", "")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.retellai.com/v2/register-phone-call",
            headers={
                "Authorization": f"Bearer {settings.retell_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "agent_id": "agent_e9da1f0338818d262f562612a9",
                "from_number": from_number,
                "to_number": to_number,
            },
        )

    call_data = resp.json()
    call_id = call_data["call_id"]

    twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial>
    <Sip>sip:{call_id}@sip.retellai.com</Sip>
  </Dial>
</Response>'''
    return Response(content=twiml, media_type="application/xml")

@router.get("/")
async def list_calls(x_clerk_user_id: str = Header(...), limit: int = Query(50,le=200), offset: int = Query(0)):
    shop = get_shop_by_owner(x_clerk_user_id)
    if not shop: raise HTTPException(status_code=404,detail="Shop not found")
    r = supabase.table("calls").select("*").eq("shop_id",shop["id"]).order("created_at",desc=True).range(offset,offset+limit-1).execute()
    return {"calls": r.data, "total": len(r.data)}

@router.get("/stats/summary")
async def call_stats(x_clerk_user_id: str = Header(...)):
    shop = get_shop_by_owner(x_clerk_user_id)
    if not shop: raise HTTPException(status_code=404,detail="Shop not found")
    calls = supabase.table("calls").select("status,appointment_booked,duration_seconds").eq("shop_id",shop["id"]).execute()
    t = len(calls.data); a = sum(1 for c in calls.data if c.get("appointment_booked")); avg = sum(c.get("duration_seconds",0) for c in calls.data)/t if t else 0
    return {"total_calls":t,"appointments_booked":a,"conversion_rate":round(a/t*100,1) if t else 0,"avg_duration_seconds":round(avg)}

@router.get("/{call_id}")
async def get_call(call_id: str, x_clerk_user_id: str = Header(...)):
    shop = get_shop_by_owner(x_clerk_user_id)
    if not shop: raise HTTPException(status_code=404,detail="Shop not found")
    r = supabase.table("calls").select("*,appointments(*)").eq("id",call_id).eq("shop_id",shop["id"]).execute()
    if not r.data: raise HTTPException(status_code=404,detail="Call not found")
    return r.data[0]
