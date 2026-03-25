from fastapi import APIRouter, HTTPException, Header
from app.database import supabase
from app.models.shop import ShopCreate, ShopUpdate
from app.services import retell_service, twilio_service, stripe_service
from app.config import settings
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/shops", tags=["shops"])

def get_shop_by_owner(owner_id):
    r = supabase.table("shops").select("*").eq("clerk_user_id", owner_id).execute()
    return r.data[0] if r.data else None

@router.get("/me")
async def get_my_shop(x_clerk_user_id: str = Header(...)):
    shop = get_shop_by_owner(x_clerk_user_id)
    if not shop: raise HTTPException(status_code=404, detail="Shop not found")
    return shop

@router.post("/")
async def create_shop(shop_data: ShopCreate, x_clerk_user_id: str = Header(...)):
    if get_shop_by_owner(x_clerk_user_id): raise HTTPException(status_code=400, detail="Shop already exists")
    r = supabase.table("shops").insert({"clerk_user_id": x_clerk_user_id, "name": shop_data.name, "address": shop_data.address, "phone_display": shop_data.phone_display, "services": shop_data.services or {}, "business_hours": shop_data.business_hours or {}, "greeting": shop_data.greeting or f"Thank you for calling {shop_data.name}!"}).execute()
    shop = r.data[0]
    try:
        phone = twilio_service.provision_phone_number()
        agent_id, llm_id = retell_service.create_agent(shop, f"{settings.app_url}/webhooks/retell")
        retell_service.import_twilio_number(phone, agent_id)
        supabase.table("shops").update({"phone_number": phone, "retell_agent_id": agent_id, "retell_llm_id": llm_id}).eq("id", shop["id"]).execute()
        shop.update({"phone_number": phone, "retell_agent_id": agent_id})
    except Exception as e:
        logger.error(f"Failed to provision phone/agent for shop {shop['id']}: {e}")
    return shop

@router.patch("/me")
async def update_shop(shop_data: ShopUpdate, x_clerk_user_id: str = Header(...)):
    shop = get_shop_by_owner(x_clerk_user_id)
    if not shop: raise HTTPException(status_code=404, detail="Shop not found")
    updates = shop_data.model_dump(exclude_none=True)
    if not updates: return shop
    r = supabase.table("shops").update(updates).eq("id", shop["id"]).execute()
    updated = r.data[0]
    if shop.get("retell_agent_id"):
        try: retell_service.update_agent(shop["retell_agent_id"], updated)
        except: pass
    return updated

@router.post("/billing/checkout")
async def create_checkout(x_clerk_user_id: str = Header(...), x_clerk_user_email: str = Header(...)):
    shop = get_shop_by_owner(x_clerk_user_id)
    if not shop: raise HTTPException(status_code=404,detail="Shop not found")
    cid = shop.get("stripe_customer_id") or stripe_service.create_customer(x_clerk_user_email,shop["name"])
    if not shop.get("stripe_customer_id"): supabase.table("shops").update({"stripe_customer_id":cid}).eq("id",shop["id"]).execute()
    url = stripe_service.create_checkout_session(cid,shop["id"],f"{settings.app_url}/dashboard?subscribed=true",f"{settings.app_url}/dashboard/billing")
    return {"url": url}

@router.post("/billing/portal")
async def billing_portal(x_clerk_user_id: str = Header(...)):
    shop = get_shop_by_owner(x_clerk_user_id)
    if not shop or not shop.get("stripe_customer_id"): raise HTTPException(status_code=404,detail="No billing account")
    url = stripe_service.create_billing_portal_session(shop["stripe_customer_id"],f"{settings.app_url}/dashboard/billing")
    return {"url": url}
