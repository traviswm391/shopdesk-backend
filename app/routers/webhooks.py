# Webhooks router for ShopDesk AI
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from fastapi.responses import RedirectResponse
from app.database import supabase
from app.services import openai_service, twilio_service, stripe_service
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("/svix-portal")
async def get_svix_portal():
    """Temporary: calls Clerk API to get Svix portal URL and redirects."""
    import httpx
    from app.config import settings
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.clerk.com/v1/webhooks/svix_url",
            headers={
                "Authorization": f"Bearer {settings.clerk_secret_key}",
                "Content-Type": "application/json"
            }
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Clerk API error: {resp.text}")
        data = resp.json()
        url = data.get("url", "")
        if not url:
            raise HTTPException(status_code=502, detail=f"No URL in response: {data}")
        return RedirectResponse(url=url)


@router.post("/retell")
async def retell_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        payload = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    event = payload.get("event")
    call_data = payload.get("call", {})
    if event == "call_started":
        _handle_call_started(call_data)
    elif event == "call_ended":
        background_tasks.add_task(_handle_call_ended, call_data)
    return {"status": "ok"}


def _handle_call_started(call_data):
    retell_call_id = call_data.get("call_id")
    agent_id = call_data.get("agent_id")
    shop_result = supabase.table("shops").select("id").eq("retell_agent_id", agent_id).execute()
    if not shop_result.data:
        return
    supabase.table("calls").insert({
        "shop_id": shop_result.data[0]["id"],
        "retell_call_id": retell_call_id,
        "caller_number": call_data.get("from_number"),
        "status": "in_progress"
    }).execute()


def _handle_call_ended(call_data):
    retell_call_id = call_data.get("call_id")
    agent_id = call_data.get("agent_id")
    call_result = supabase.table("calls").select("*, shops(*)").eq("retell_call_id", retell_call_id).execute()
    if call_result.data:
        call_record = call_result.data[0]
    else:
        shop_r = supabase.table("shops").select("*").eq("retell_agent_id", agent_id).execute()
        if not shop_r.data:
            return
        shop = shop_r.data[0]
        r = supabase.table("calls").insert({
            "shop_id": shop["id"],
            "retell_call_id": retell_call_id,
            "caller_number": call_data.get("from_number"),
            "status": "completed"
        }).execute()
        call_record = r.data[0]
        call_record["shops"] = shop
    shop = call_record.get("shops", {})
    call_id = call_record["id"]
    transcript_str = "".join(
        f"{e.get('role', '').capitalize()}: {e.get('content','')} "
        for e in call_data.get("transcript_object", [])
    )
    duration = int(
        (call_data.get("end_timestamp", 0) - call_data.get("start_timestamp", 0)) / 1000
    ) if call_data.get("end_timestamp") else None
    supabase.table("calls").update({
        "status": "completed",
        "transcript": transcript_str,
        "duration_seconds": duration
    }).eq("id", call_id).execute()
    if not transcript_str.strip():
        return
    try:
        ext = openai_service.extract_appointment_from_transcript(transcript_str, shop.get("name", "shop"))
        supabase.table("calls").update({
            "summary": ext.get("summary"),
            "appointment_booked": ext.get("appointment_booked", False)
        }).eq("id", call_id).execute()
        if ext.get("appointment_booked"):
            supabase.table("appointments").insert({
                "shop_id": shop["id"],
                "call_id": call_id,
                "customer_name": ext.get("customer_name"),
                "customer_phone": ext.get("customer_phone") or call_data.get("from_number"),
                "vehicle_info": ext.get("vehicle_info"),
                "service_requested": ext.get("service_requested"),
                "preferred_date": ext.get("preferred_date"),
                "preferred_time": ext.get("preferred_time")
            }).execute()
            cph = ext.get("customer_phone") or call_data.get("from_number")
            sph = shop.get("phone_number")
            if cph and sph:
                try:
                    body = openai_service.generate_sms_confirmation(ext, shop.get("name"), shop.get("phone_display") or sph)
                    twilio_service.send_sms(to=cph, from_=sph, body=body)
                except Exception as e:
                    pass
    except Exception as e:
        pass


@router.post("/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe_service.construct_webhook_event(payload, sig)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    t = event["type"]
    d = event["data"]["object"]
    if t == "checkout.session.completed":
        sid = d.get("metadata", {}).get("shop_id")
        if sid:
            supabase.table("shops").update({
                "stripe_subscription_id": d.get("subscription"),
                "stripe_customer_id": d.get("customer"),
                "subscription_status": "active"
            }).eq("id", sid).execute()
    elif t == "customer.subscription.deleted":
        supabase.table("shops").update({"subscription_status": "cancelled"}).eq("stripe_subscription_id", d.get("id")).execute()
    elif t == "customer.subscription.updated":
        supabase.table("shops").update({"subscription_status": d.get("status")}).eq("stripe_subscription_id", d.get("id")).execute()
    return {"status": "ok"}


@router.post("/clerk")
async def clerk_webhook(request: Request):
    from svix.webhooks import Webhook, WebhookVerificationError
    from app.config import settings
    payload = await request.body()
    headers = dict(request.headers)
    try:
        wh = Webhook(settings.clerk_webhook_secret)
        evt = wh.verify(payload, headers)
    except WebhookVerificationError:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    event_type = evt.get("type")
    data = evt.get("data", {})
    if event_type in ("user.created", "user.updated"):
        clerk_user_id = data.get("id")
        email = ""
        email_addresses = data.get("email_addresses", [])
        if email_addresses:
            email = email_addresses[0].get("email_address", "")
        if clerk_user_id:
            supabase.table("shops").upsert(
                {"clerk_user_id": clerk_user_id, "email": email, "name": email},
                on_conflict="clerk_user_id"
            ).execute()
            logger.info(f"Upserted shop for clerk_user_id={clerk_user_id}")
    return {"status": "ok"}
