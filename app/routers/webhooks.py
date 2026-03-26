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
        url = data.get("svix_url", "") or data.get("url", "")
        if not url:
            raise HTTPException(status_code=502, detail=f"No URL in response: {data}")
        return RedirectResponse(url=url)


# ---------------------------------------------------------------------------
# ElevenLabs webhook — handles post-call transcription events
# ---------------------------------------------------------------------------

@router.post("/elevenlabs")
async def elevenlabs_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = payload.get("type")

    if event_type == "post_call_transcription":
        background_tasks.add_task(_handle_elevenlabs_call_ended, payload.get("data", {}))

    return {"status": "ok"}


def _handle_elevenlabs_call_ended(data: dict):
    """Process ElevenLabs post-call data: save transcript, extract appointment, send SMS."""
    conversation_id = data.get("conversation_id")
    agent_id = data.get("agent_id")

    if not conversation_id:
        return

    # Find shop by ElevenLabs agent_id (stored in retell_agent_id column)
    shop_result = supabase.table("shops").select("*").eq("retell_agent_id", agent_id).execute()
    if not shop_result.data:
        logger.warning(f"No shop found for ElevenLabs agent_id {agent_id}")
        return

    shop = shop_result.data[0]

    # Build transcript string from ElevenLabs format
    transcript_items = data.get("transcript", [])
    transcript_str = ""
    for item in transcript_items:
        role = item.get("role", "unknown").capitalize()
        message = item.get("message", "")
        transcript_str += f"{role}: {message}\n"

    metadata = data.get("metadata", {})
    duration = metadata.get("call_duration_secs", 0)
    phone_meta = metadata.get("phone_call", {})
    caller_number = phone_meta.get("phone_number_from", "")

    # Check if call record already exists (from call_started if we add that later)
    existing = supabase.table("calls").select("id").eq("retell_call_id", conversation_id).execute()

    if existing.data:
        call_id = existing.data[0]["id"]
        supabase.table("calls").update({
            "status": "completed",
            "transcript": transcript_str,
            "duration_seconds": duration,
        }).eq("id", call_id).execute()
    else:
        r = supabase.table("calls").insert({
            "shop_id": shop["id"],
            "retell_call_id": conversation_id,
            "caller_number": caller_number,
            "status": "completed",
            "transcript": transcript_str,
            "duration_seconds": duration,
        }).execute()
        call_id = r.data[0]["id"]

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
                "customer_phone": ext.get("customer_phone") or caller_number,
                "vehicle_info": ext.get("vehicle_info"),
                "service_requested": ext.get("service_requested"),
                "preferred_date": ext.get("preferred_date"),
                "preferred_time": ext.get("preferred_time"),
                "status": "pending"
            }).execute()

            sms_to = ext.get("customer_phone") or caller_number
            if sms_to:
                try:
                    msg = (
                        f"Hi {ext.get('customer_name', 'there')}! Your appointment at "
                        f"{shop.get('name', 'the shop')} has been requested for "
                        f"{ext.get('preferred_date', 'your preferred date')} at "
                        f"{ext.get('preferred_time', 'your preferred time')}. "
                        f"The team will confirm shortly!"
                    )
                    twilio_service.send_sms(shop.get("phone_number"), sms_to, msg)
                except Exception as sms_err:
                    logger.warning(f"SMS send failed: {sms_err}")
    except Exception as e:
        logger.error(f"Failed to process ElevenLabs call {conversation_id}: {e}")


# ---------------------------------------------------------------------------
# Retell webhook (kept for backward compatibility)
# ---------------------------------------------------------------------------

@router.post("/retell")
async def retell_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    event = payload.get("event")
    call_data = payload.get("call", {})
    if event == "call_started":
        _handle_retell_call_started(call_data)
    elif event == "call_ended":
        background_tasks.add_task(_handle_retell_call_ended, call_data)
    return {"status": "ok"}


def _handle_retell_call_started(call_data):
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


def _handle_retell_call_ended(call_data):
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

    call_id = call_record["id"]
    shop = call_record.get("shops") or {}
    transcript_items = call_data.get("transcript", [])
    transcript_str = "\n".join(
        f"{item.get('role','').capitalize()}: {item.get('content','')}"
        for item in transcript_items
    )
    duration = call_data.get("duration_ms", 0) // 1000
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
                "preferred_time": ext.get("preferred_time"),
                "status": "pending"
            }).execute()
            sms_to = ext.get("customer_phone") or call_data.get("from_number")
            if sms_to:
                try:
                    msg = (
                        f"Hi {ext.get('customer_name', 'there')}! Your appointment at "
                        f"{shop.get('name', 'the shop')} has been requested. The team will confirm shortly!"
                    )
                    twilio_service.send_sms(shop.get("phone_number"), sms_to, msg)
                except Exception:
                    pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Stripe webhook
# ---------------------------------------------------------------------------

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
        supabase.table("shops").update({"subscription_status": d.get("status", "active")}).eq("stripe_subscription_id", d.get("id")).execute()
    return {"status": "ok"}
