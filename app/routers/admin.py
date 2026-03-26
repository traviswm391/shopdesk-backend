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
            from app.services import elevenlabs_service
            elevenlabs_service.update_agent(shop["retell_agent_id"], updated_shop)
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


@router.get("/appointments")
async def list_all_appointments(x_clerk_user_id: str = Header(...), limit: int = 100):
    require_admin(x_clerk_user_id)
    result = (
        supabase.table("appointments")
        .select("*, shops(name)")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return {"appointments": result.data, "total": len(result.data)}
