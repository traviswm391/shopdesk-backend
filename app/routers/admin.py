from fastapi import APIRouter, HTTPException, Header, Body
from app.database import supabase
from app.services import email_service
import os
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])

ADMIN_USER_IDS = {
    os.environ.get("ADMIN_CLERK_USER_ID", "user_3BQ84qxBvEBwI5E5WaVkwKBDVYY"),
}


def require_admin(x_clerk_user_id: str):
    if x_clerk_user_id not in ADMIN_USER_IDS:
        raise HTTPException(status_code=403, detail="Admin access required")


def require_admin_secret(x_admin_secret: str | None):
    """Alternative auth for cron/server-to-server calls via ADMIN_SECRET env var."""
    secret = os.environ.get("ADMIN_SECRET", "")
    if not secret or x_admin_secret != secret:
        raise HTTPException(status_code=403, detail="Admin access required")


# ---------------------------------------------------------------------------
# Existing admin endpoints
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Weekly digest email (#11)
# Secured by X-Admin-Secret header â safe to call from Railway cron scheduler
# ---------------------------------------------------------------------------

@router.post("/send-weekly-digest")
async def send_weekly_digest(x_admin_secret: str = Header(None)):
    """
    Send a weekly summary email to each shop owner.
    Call this from Railway's cron scheduler (e.g. every Monday at 8am).
    Requires X-Admin-Secret header matching the ADMIN_SECRET env var.
    """
    require_admin_secret(x_admin_secret)

    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    shops_result = supabase.table("shops").select("*").execute()
    shops = shops_result.data or []

    sent = 0
    errors = []

    for shop in shops:
        owner_id = shop.get("clerk_user_id")
        shop_name = shop.get("name", "Your Shop")
        location = shop.get("location_name") or shop_name

        # Get last 7 days of calls for this shop
        calls_result = (
            supabase.table("calls")
            .select("id, status, duration_seconds, created_at")
            .eq("shop_id", shop["id"])
            .gte("created_at", since)
            .execute()
        )
        calls = calls_result.data or []

        # Get appointments for the same window
        appts_result = (
            supabase.table("appointments")
            .select("id, created_at")
            .eq("shop_id", shop["id"])
            .gte("created_at", since)
            .execute()
        )
        appts = appts_result.data or []

        total_calls = len(calls)
        total_booked = len(appts)
        missed_calls = total_calls - total_booked if total_calls > total_booked else 0
        avg_duration = (
            int(sum(c.get("duration_seconds", 0) for c in calls) / total_calls)
            if total_calls > 0
            else 0
        )

        # Get owner email via Supabase admin API
        owner_email = None
        try:
            user_resp = supabase.auth.admin.get_user_by_id(owner_id)
            if user_resp and user_resp.user:
                owner_email = user_resp.user.email
        except Exception as e:
            logger.warning(f"Could not fetch email for owner {owner_id}: {e}")

        if not owner_email:
            errors.append({"shop_id": shop["id"], "reason": "no owner email"})
            continue

        stats = {
            "total_calls": total_calls,
            "appointments_booked": total_booked,
            "missed_calls": missed_calls,
            "avg_duration_seconds": avg_duration,
        }

        try:
            html = email_service.build_weekly_digest_html(shop_name, location, stats)
            email_service.send_email(
                to=owner_email,
                subject=f"ð Your ShopDesk AI Weekly Report â {shop_name}",
                html=html,
            )
            sent += 1
            logger.info(f"Weekly digest sent to {owner_email} for shop {shop['id']}")
        except Exception as e:
            logger.error(f"Failed to send digest for shop {shop['id']}: {e}")
            errors.append({"shop_id": shop["id"], "reason": str(e)})

    return {
        "sent": sent,
        "total_shops": len(shops),
        "errors": errors,
        "since": since,
    }
