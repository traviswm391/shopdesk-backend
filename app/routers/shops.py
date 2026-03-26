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
    r = supabase.table("shops").select("*").eq("clerk_user_id", owner_id).execute()
    return r.data[0] if r.data else None


@router.get("/me")
async def get_my_shop(user_id: str = Depends(get_current_user_id)):
    shop = get_shop_by_owner(user_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    return shop


@router.post("/")
async def create_shop(shop_data: ShopCreate, user_id: str = Depends(get_current_user_id)):
    if get_shop_by_owner(user_id):
        raise HTTPException(status_code=400, detail="Shop already exists")

    r = supabase.table("shops").insert({
        "clerk_user_id": user_id,
        "name": shop_data.name,
        "address": shop_data.address,
        "phone_display": shop_data.phone_display,
        "services": shop_data.services or [],
        "declined_services": shop_data.declined_services or [],
        "business_hours": shop_data.business_hours or {},
        "greeting": shop_data.greeting or f"Thank you for calling {shop_data.name}!",
    }).execute()
    shop = r.data[0]

    try:
        phone = twilio_service.provision_phone_number()
        agent_data = elevenlabs_service.create_agent(shop)
        agent_id = agent_data.get("agent_id")
        elevenlabs_webhook_url = elevenlabs_service.get_twilio_webhook_url(agent_id)
        twilio_service.configure_number_for_retell(phone, elevenlabs_webhook_url)
        supabase.table("shops").update({
            "phone_number": phone,
            "retell_agent_id": agent_id,
        }).eq("id", shop["id"]).execute()
        shop.update({"phone_number": phone, "retell_agent_id": agent_id})
    except Exception as e:
        logger.error(f"Failed to provision phone/agent for shop {shop['id']}: {e}")

    return shop


@router.patch("/me")
async def update_shop(shop_data: ShopUpdate, user_id: str = Depends(get_current_user_id)):
    shop = get_shop_by_owner(user_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    updates = shop_data.model_dump(exclude_none=True)
    if not updates:
        return shop

    r = supabase.table("shops").update(updates).eq("id", shop["id"]).execute()
    updated = r.data[0]

    if shop.get("retell_agent_id"):
        try:
            elevenlabs_service.update_agent(shop["retell_agent_id"], updated)
        except Exception:
            pass

    return updated


@router.post("/me/provision")
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


@router.post("/billing/checkout")
async def create_checkout(user_id: str = Depends(get_current_user_id)):
    shop = get_shop_by_owner(user_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    cid = shop.get("stripe_customer_id") or stripe_service.create_customer("", shop["name"])
    if not shop.get("stripe_customer_id"):
        supabase.table("shops").update({"stripe_customer_id": cid}).eq("id", shop["id"]).execute()
    url = stripe_service.create_checkout_session(cid, shop["id"], f"{settings.app_url}/dashboard?subscribed=true", f"{settings.app_url}/dashboard/billing")
    return {"url": url}


@router.post("/billing/portal")
async def billing_portal(user_id: str = Depends(get_current_user_id)):
    shop = get_shop_by_owner(user_id)
    if not shop or not shop.get("stripe_customer_id"):
        raise HTTPException(status_code=404, detail="No billing account found")
    url = stripe_service.create_portal_session(shop["stripe_customer_id"], f"{settings.app_url}/dashboard/billing")
    return {"url": url}
