# Webhooks router for ShopDesk AI
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from fastapi.responses import RedirectResponse
from app.database import supabase
from app.services import openai_service, twilio_service, stripe_service
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ---------------------------------------------------------------------------
# Owner notification helpers (#10 missed-call SMS, #12 booking SMS)
# ---------------------------------------------------------------------------

def _owner_notification_number(shop: dict) -> str | None:
    """Return the owner's notification phone (dedicated or fallback to shop phone)."""
    return shop.get("notification_phone") or shop.get("phone_display") or None


def _send_missed_call_sms(shop: dict, caller_number: str) -> None:
    """Send an SMS to the shop owner when a call ended with no booking (#10)."""
    owner_phone = _owner_notification_number(shop)
    if not owner_phone:
        return
    shop_phone = shop.get("phone_number", "your AI number")
    location = shop.get("location_name") or shop.get("name", "your shop")
    body = (
        f"ð Missed call at {location}: {caller_number} called but didn't book. "
        f"Consider calling them back! (via ShopDesk AI)"
    )
    try:
        twilio_service.send_sms(to=owner_phone, from_=shop_phone, body=body)
    except Exception as e:
        logger.warning(f"Could not send missed-call SMS to {owner_phone}: {e}")


def _send_owner_booking_sms(shop: dict, ext: dict, caller_number: str) -> None:
    """Send an SMS to the shop owner confirming a new booking (#12)."""
    owner_phone = _owner_notification_number(shop)
    if not owner_phone:
        return
    shop_phone = shop.get("phone_number", "your AI number")
    location = shop.get("location_name") or shop.get("name", "your shop")
    customer_name = ext.get("customer_name") or "A customer"
    service = ext.get("service") or "an appointment"
    appt_time = ext.get("appointment_time") or "a time TBD"
    body = (
        f"â New booking at {location}: {customer_name} booked {service} "
        f"for {appt_time}. Caller: {caller_number} (via ShopDesk AI)"
    )
    try:
        twilio_service.send_sms(to=owner_phone, from_=shop_phone, body=body)
    except Exception as e:
        logger.warning(f"Could not send booking-confirmation SMS to {owner_phone}: {e}")


# ---------------------------------------------------------------------------
# Svix / Clerk portal proxy
# ---------------------------------------------------------------------------

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
        portal_url = data.get("url")
        if not portal_url:
            raise HTTPException(status_code=502, detail="No URL in Clerk response")
        return RedirectResponse(url=portal_url)


# ---------------------------------------------------------------------------
# Stripe webhook
# ---------------------------------------------------------------------------

@router.post("/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        stripe_service.handle_webhook(payload, sig)
    except Exception as e:
        logger.error(f"Stripe webhook error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# ElevenLabs post-call webhook (#10, #12 owner SMS added here)
# ---------------------------------------------------------------------------

@router.post("/elevenlabs/post-call")
async def elevenlabs_post_call(request: Request, background_tasks: BackgroundTasks):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    background_tasks.add_task(_handle_elevenlabs_post_call, payload)
    return {"status": "ok"}


def _handle_elevenlabs_post_call(payload: dict):
    try:
        conversation_id = payload.get("conversation_id", "")
        agent_id = payload.get("agent_id", "")
        transcript = payload.get("transcript", [])
        metadata = payload.get("metadata", {})
        duration = metadata.get("call_duration_secs", 0)

        # Look up shop by agent_id
        shop_result = supabase.table("shops").select("*").eq("retell_agent_id", agent_id).execute()
        if not shop_result.data:
            logger.warning(f"No shop found for ElevenLabs agent_id={agent_id}")
            return
        shop = shop_result.data[0]

        caller_number = metadata.get("from_number", "")
        transcript_str = "\n".join(
            f"{t.get('role', 'unknown')}: {t.get('message', '')}"
            for t in transcript
        )

        # Upsert call record
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

        # Extract appointment via OpenAI
        try:
            ext = openai_service.extract_appointment_from_transcript(transcript_str, shop.get("name", "shop"))
        except Exception as e:
            logger.error(f"OpenAI extraction failed: {e}")
            ext = {}

        appointment_booked = ext.get("appointment_booked", False)

        if appointment_booked:
            # Save appointment
            try:
                supabase.table("appointments").insert({
                    "shop_id": shop["id"],
                    "call_id": call_id,
                    "customer_name": ext.get("customer_name"),
                    "customer_phone": caller_number,
                    "service": ext.get("service"),
                    "appointment_time": ext.get("appointment_time"),
                    "notes": ext.get("notes"),
                }).execute()
            except Exception as e:
                logger.error(f"Failed to save appointment: {e}")

            # SMS confirmation to customer
            if caller_number and shop.get("phone_number"):
                try:
                    service = ext.get("service") or "your appointment"
                    appt_time = ext.get("appointment_time") or "the scheduled time"
                    msg = (
                        f"Hi {ext.get('customer_name', 'there')}! This is {shop.get('name')}. "
                        f"Your booking for {service} at {appt_time} is confirmed. "
                        f"Call us if anything changes!"
                    )
                    twilio_service.send_sms(to=caller_number, from_=shop["phone_number"], body=msg)
                except Exception as e:
                    logger.warning(f"Could not send customer confirmation SMS: {e}")

            # SMS notification to owner (#12)
            _send_owner_booking_sms(shop, ext, caller_number)

        else:
            # No booking â notify owner of missed opportunity (#10)
            _send_missed_call_sms(shop, caller_number)

    except Exception as e:
        logger.error(f"ElevenLabs post-call handler error: {e}", exc_info=True)


# ---------------------------------------------------------------------------
# Retell webhooks (#10, #12 owner SMS added to call_ended handler)
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
    try:
        retell_call_id = call_data.get("call_id")
        agent_id = call_data.get("agent_id")
        caller_number = call_data.get("from_number", "")
        transcript_list = call_data.get("transcript", [])
        duration = call_data.get("duration_ms", 0) // 1000

        shop_result = supabase.table("shops").select("*").eq("retell_agent_id", agent_id).execute()
        if not shop_result.data:
            logger.warning(f"No shop found for Retell agent_id={agent_id}")
            return
        shop = shop_result.data[0]

        transcript_str = "\n".join(
            f"{t.get('role', 'unknown')}: {t.get('content', '')}"
            for t in transcript_list
        )

        # Upsert call record
        existing = supabase.table("calls").select("id").eq("retell_call_id", retell_call_id).execute()
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
                "retell_call_id": retell_call_id,
                "caller_number": caller_number,
                "status": "completed",
                "transcript": transcript_str,
                "duration_seconds": duration,
            }).execute()
            call_id = r.data[0]["id"]

        if not transcript_str.strip():
            return

        # Extract appointment via OpenAI
        try:
            ext = openai_service.extract_appointment_from_transcript(transcript_str, shop.get("name", "shop"))
        except Exception as e:
            logger.error(f"OpenAI extraction failed (Retell): {e}")
            ext = {}

        appointment_booked = ext.get("appointment_booked", False)

        if appointment_booked:
            try:
                supabase.table("appointments").insert({
                    "shop_id": shop["id"],
                    "call_id": call_id,
                    "customer_name": ext.get("customer_name"),
                    "customer_phone": caller_number,
                    "service": ext.get("service"),
                    "appointment_time": ext.get("appointment_time"),
                    "notes": ext.get("notes"),
                }).execute()
            except Exception as e:
                logger.error(f"Failed to save appointment (Retell): {e}")

            # SMS to customer
            if caller_number and shop.get("phone_number"):
                try:
                    service = ext.get("service") or "your appointment"
                    appt_time = ext.get("appointment_time") or "the scheduled time"
                    msg = (
                        f"Hi {ext.get('customer_name', 'there')}! This is {shop.get('name')}. "
                        f"Your booking for {service} at {appt_time} is confirmed. "
                        f"Call us if anything changes!"
                    )
                    twilio_service.send_sms(to=caller_number, from_=shop["phone_number"], body=msg)
                except Exception as e:
                    logger.warning(f"Could not send customer SMS (Retell): {e}")

            # SMS to owner (#12)
            _send_owner_booking_sms(shop, ext, caller_number)

        else:
            # Missed call â notify owner (#10)
            _send_missed_call_sms(shop, caller_number)

    except Exception as e:
        logger.error(f"Retell call_ended handler error: {e}", exc_info=True)
