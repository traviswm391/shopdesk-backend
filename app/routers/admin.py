from fastapi import APIRouter, HTTPException, Header, Body
from app.database import supabase
import os

router = APIRouter(prefix="/api/admin", tags=["admin"])

ADMIN_USER_IDS = {
    os.environ.get("ADMIN_CLERK_USER_ID", "user_3BQ84qxBvEBwI5E5WaVkwKBDVYY"),
}


def require_admin(x_clerk_user_id: str):
    if x_clerk_user_id not in ADMIN_USER_IDS:
        raise HTTPException(status_code=403, detail="Admin access required")


@router.get("/shops")
async def list_all_shops(x_clerk_user_id: str = Header(...)):
    require_admin(x_clerk_user_id)
    result = supabase.table("shops").select("*").order("created_at", desc=True).execute()
    return {"shops": result.data, "total": len(result.data)}


@router.get("/shops/{shop_id}")
async def get_shop_detail(shop_id: str, x_clerk_user_id: str = Header(...)):
    require_admin(x_clerk_user_id)
    result = supabase.table("shops").select("*").eq("id", shop_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Shop not found")
    return result.data[0]


@router.get("/shops/{shop_id}/calls")
async def get_shop_calls(shop_id: str, x_clerk_user_id: str = Header(...), limit: int = 100):
    require_admin(x_clerk_user_id)
    result = (
        supabase.table("calls")
        .select("*")
        .eq("shop_id", shop_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return {"calls": result.data, "total": len(result.data)}


@router.patch("/shops/{shop_id}")
async def update_shop_as_admin(
    shop_id: str,
    x_clerk_user_id: str = Header(...),
    updates: dict = Body(...),
):
    require_admin(x_clerk_user_id)
    result = supabase.table("shops").select("*").eq("id", shop_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Shop not found")
    shop = result.data[0]
    updated = supabase.table("shops").update(updates).eq("id", shop_id).execute()
    updated_shop = updated.data[0]
    if shop.get("retell_agent_id"):
        try:
            from app.services import retell_service
            retell_service.update_agent(shop["retell_agent_id"], updated_shop)
        except Exception:
            pass
    return updated_shop


@router.get("/calls")
async def list_all_calls(x_clerk_user_id: str = Header(...), limit: int = 100):
    require_admin(x_clerk_user_id)
    result = (
        supabase.table("calls")
        .select("*, shops(name)")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return {"calls": result.data, "total": len(result.data)}


@router.get("/stats")
async def platform_stats(x_clerk_user_id: str = Header(...)):
    require_admin(x_clerk_user_id)
    shops = supabase.table("shops").select("id, name, subscription_status, created_at").execute()
    calls = supabase.table("calls").select("id, appointment_booked, duration_seconds, status, shop_id").execute()
    total_shops = len(shops.data)
    active_shops = sum(1 for s in shops.data if s.get("subscription_status") == "active")
    total_calls = len(calls.data)
    total_booked = sum(1 for c in calls.data if c.get("appointment_booked"))
    avg_duration = (
        sum(c.get("duration_seconds", 0) or 0 for c in calls.data) / total_calls
        if total_calls > 0
        else 0
    )
    shop_call_counts = {}
    for call in calls.data:
        sid = call.get("shop_id")
        shop_call_counts[sid] = shop_call_counts.get(sid, 0) + 1
    shops_with_counts = [
        {**s, "call_count": shop_call_counts.get(s["id"], 0)}
        for s in shops.data
    ]
    return {
        "total_shops": total_shops,
        "active_shops": active_shops,
        "total_calls": total_calls,
        "total_appointments_booked": total_booked,
        "platform_conversion_rate": round(total_booked / total_calls * 100, 1) if total_calls > 0 else 0,
        "avg_call_duration_seconds": round(avg_duration),
        "shops": shops_with_counts,
    }
