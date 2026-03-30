from fastapi import APIRouter, Depends, HTTPException
from app.auth import get_current_user_id
from app.database import supabase
from app.models.shop import ShopCreate, ShopUpdate
from app.services import elevenlabs_service, twilio_service, stripe_service
from app.config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/shops", tags=["shops"])


def get_shop_by_owner(owner_id: str):
    """Return first shop for backwards compatibility with single-location flow."""
    r = supabase.table("shops").select("*").eq("clerk_user_id", owner_id).order("created_at").execute()
    return r.data[0] if r.data else None


# ---------------------------------------------------------------------------
# Multi-location: list all shops for this user (#13)
# ---------------------------------------------------------------------------

@router.get("/")
async def get_my_shops(user_id: str = Depends(get_current_user_id)):
    """Return all locations owned by the authenticated user."""
    r = supabase.table("shops").select("*").eq("clerk_user_id", user_id).order("created_at").execute()
    return {"shops": r.data, "total": len(r.data)}


# ---------------------------------------------------------------------------
# Single-shop convenience endpoint (existing dashboards use /me)
# ---------------------------------------------------------------------------

@router.get("/me")
async def get_my_shop(user_id: str = Depends(get_current_user_id)):
    shop = get_shop_by_owner(user_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    return shop


# ---------------------------------------------------------------------------
# Create a new shop / location (#13 â allows multiple per user)
# ---------------------------------------------------------------------------

@router.post("/")
async def create_shop(shop_data: ShopCreate, user_id: str = Depends(get_current_user_id)):
    # For multi-location: allow multiple shops per user.
    # Enforce unique location_name within the same user account if provided.
    location_name = shop_data.location_name or None
    if location_name:
        dup = (
            supabase.table("shops")
            .select("id")
            .eq("clerk_user_id", user_id)
            .eq("location_name", location_name)
            .execute()
        )
        if dup.data:
            raise HTTPException(status_code=400, detail=f"A location named '{location_name}' already exists.")

    payload = {
        "clerk_user_id": user_id,
        "name": shop_data.name,
        "address": shop_data.address,
        "phone_display": shop_data.phone_display,
        "services": shop_data.services or [],
        "declined_services": shop_data.declined_services or [],
        "business_hours": shop_data.business_hours or {},
        "greeting": shop_data.greeting,
        "location_name": location_name,
        "notification_phone": shop_data.notification_phone or None,
    }
    result = supabase.table("shops").insert(payload).execute()
    shop = result.data[0]

    # Auto-create Stripe customer if no existing shop has one
    existing = get_shop_by_owner(user_id)
    if not existing or not existing.get("stripe_customer_id"):
        try:
            customer = stripe_service.create_customer(
                email=shop_data.phone_display or "",
                name=shop_data.name,
                metadata={"clerk_user_id": user_id, "shop_id": shop["id"]}
            )
            supabase.table("shops").update({"stripe_customer_id": customer["id"]}).eq("id", shop["id"]).execute()
            shop["stripe_customer_id"] = customer["id"]
        except Exception as e:
            logger.warning(f"Stripe customer creation failed: {e}")

    return shop


# ---------------------------------------------------------------------------
# Update the primary (first) shop â backwards compat for existing dashboard
# ---------------------------------------------------------------------------

@router.put("/me")
async def update_my_shop(shop_data: ShopUpdate, user_id: str = Depends(get_current_user_id)):
    shop = get_shop_by_owner(user_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    return await _do_update_shop(shop, shop_data)


# ---------------------------------------------------------------------------
# Update a specific location by ID (#13)
# ------------------------------------------------------------------------------------

@router.patch("/{shop_id}")
async def update_shop_by_id(
    shop_id: str,
    shop_data: ShopUpdate,
    user_id: str = Depends(get_current_user_id),
):
    result = supabase.table("shops").select("*").eq("id", shop_id).eq("clerk_user_id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Shop not found")
    shop = result.data[0]
    return await _do_update_shop(shop, shop_data)


async def _do_update_shop(shop: dict, shop_data: ShopUpdate) -> dict:
    """Shared update logic: persists to DB and syncs ElevenLabs agent if needed."""
    updates = shop_data.model_dump(exclude_none=True)
    if not updates:
        return shop

    updated = supabase.table("shops").update(updates).eq("id", shop["id"]).execute()
    updated_shop = updated.data[0]

    # Sync ElevenLabs agent if voice-related fields changed
    voice_fields = {"name", "greeting", "tone", "services", "declined_services", "business_hours"}
    if shop.get("retell_agent_id") and voice_fields.intersection(updates.keys()):
        try:
            elevenlabs_service.update_agent(shop["retell_agent_id"], updated_shop)
        except Exception as e:
            logger.warning(f"ElevenLabs agent sync failed: {e}")

    return updated_shop


# ---------------------------------------------------------------------------
# Provision phone + AI agent for a shop
# ---------------------------------------------------------------------------

@router.post("/provision")
async def provision_shop(user_id: str = Depends(get_current_user_id)):
    shop = get_shop_by_owner(user_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    if shop.get("retell_agent_id") and shop.get("phone_number"):
        return {"status": "already_provisioned", "phone_number": shop["phone_number"], "agent_id": shop["retell_agent_id"]}

    try:
        phone = shop.get("phone_number") or twilio_service.provision_phone_number()
        agent_id = shop.get("retell_agent_id")
        if not agent_id:
            agent_data = elevenlabs_service.create_agent(shop)
            agent_id = agent_data.get("agent_id")
        elevenlabs_webhook_url = elevenlabs_service.get_twilio_webhook_url(agent_id)
        twilio_service.configure_number_for_retell(phone, elevenlabs_webhook_url)
        supabase.table("shops").update({"phone_number": phone, "retell_agent_id": agent_id}).eq("id", shop["id"]).execute()
        return {"status": "provisioned", "phone_number": phone, "agent_id": agent_id}
    except Exception as e:
        logger.error(f"Provision failed for shop {shop['id']}: {e}")
        raise HTTPException(status_code=500, detail=f"Provisioning failed: {str(e)}")


# ---------------------------------------------------------------------------
# Provision a specific location by ID (#13)
# ---------------------------------------------------------------------------

@router.post("/{shop_id}/provision")
async def provision_shop_by_id(shop_id: str, user_id: str = Depends(get_current_user_id)):
    result = supabase.table("shops").select("*").eq("id", shop_id).eq("clerk_user_id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Shop not found")
    shop = result.data[0]

    if shop.get("retell_agent_id") and shop.get("phone_number"):
        return {"status": "already_provisioned", "phone_number": shop["phone_number"], "agent_id": shop["retell_agent_id"]}

    try:
        phone = shop.get("phone_number") or twilio_service.provision_phone_number()
        agent_id = shop.get("retell_agent_id")
        if not agent_id:
            agent_data = elevenlabs_service.create_agent(shop)
            agent_id = agent_data.get("agent_id")
        elevenlabs_webhook_url = elevenlabs_service.get_twilio_webhook_url(agent_id)
        twilio_service.configure_number_for_retell(phone, elevenlabs_webhook_url)
        supabase.table("shops").update({"phone_number": phone, "retell_agent_id": agent_id}).eq("id", shop["id"]).execute()
        return {"status": "provisioned", "phone_number": phone, "agent_id": agent_id}
    except Exception as e:
        logger.error(f"Provision failed for shop {shop['id']}: {e}")
        raise HTTPException(status_code=500, detail=f"Provisioning failed: {str(e)}")
