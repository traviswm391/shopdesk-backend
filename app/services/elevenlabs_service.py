import requests
from app.config import settings
import logging

logger = logging.getLogger(__name__)

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"

# Titan - Deep, Bold, and Powerful male voice (ElevenLabs v3 conversational)
DEFAULT_VOICE_ID = "dtSEyYGNJqjrtBArPCVZ"


def get_headers():
    return 
        "xi-api-key": settings.elevenlabs_api_key,
        "Content-Type": "application/json"
    }


def build_agent_prompt(shop: dict) -> str:
    shop_name = shop.get("name", "the shop")
    address = shop.get("address", "")
    services = shop.get("services", [])
    declined_services = shop.get("declined_services", [])
    greeting = shop.get("greeting", f"Thanks for calling {shop_name}, what can we do for you?")
    hours = shop.get("business_hours", {})

    services_str = ", ".join(services) if services else "general auto repair and maintenance"

    hours_str = ""
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for day in days:
        h = hours.get(day, {})
        if h.get("closed"):
            hours_str += f"{day.capitalize()}: Closed\n"
        else:
            open_t = h.get("open", "9:00 AM")
            close_t = h.get("close", "5:00 PM")
            hours_str += f"{day.capitalize()}: {open_t} - {close_t}\n"

    declined_str = ""
    if declined_services:
        declined_str = f"\nServices we do NOT offer: {', '.join(declined_services)}. If the caller asks about these, politely let them know we don't handle that and suggest they try another shop.\n"

    return f"""You are the AI receptionist for {shop_name}, an auto shop{"located at " + address if address else ""}.

Your personality: confident, direct, and no-nonsense. You sound like a knowledgeable guy who knows the automotive business inside and out. You're friendly but get straight to the point — no fluff. You instill confidence that the shop knows what they're doing.

Your job:
1. Answer with the opening greeting
2. Find out what the caller needs
3. Book an appointment by getting:
   - Full name
   - Best callback number
   - Vehicle make, model, and year
   - What service or repair they need
   - Preferred day and time
4. Repeat the details back to confirm
5. Let them know the shop will fire off a text confirmation
{declined_str}
Business hours:
{hours_str}
Services we handle: {services_str}

Ground rules:
- Keep it tight — confident and professional, no over-explaining
- On pricing: tell them it depends on the job and the guys will give them a solid quote
- After booking, wrap up the call professionally
- Never make up information you don't have
- If they ask something outside your scope, let them know the team will follow up"""


def create_agent(shop: dict) -> dict:
    """Create a new ElevenLabs Conversational AI agent for the shop."""
    prompt = build_agent_prompt(shop)
    greeting = shop.get("greeting", f"Thanks for calling {shop.get('name', 'the shop')}, what can we do for you?")

    webhook_url = f"{settings.backend_url}/webhooks/elevenlabs"

    payload = {
        "name": shop.get("name", "AI Receptionist"),
        "conversation_config": {
            "agent": {
                "prompt": {
                    "prompt": prompt,
                    "llm": "gpt-4o-mini",
                    "temperature": 0.5,
                    "max_tokens": 200
                },
                "first_message": greeting,
                "language": "en"
            },
            "tts": {
                "voice_id": DEFAULT_VOICE_ID,
                "model_id": "eleven_turbo_v2",
                "agent_output_audio_format": "ulaw_8000"
            },
            "stt": {
                "provider": "deepgram",
                "model": "nova-2-phonecall"
            },
            "conversation": {
                "max_duration_seconds": 600
            }
        },
        "platform_settings": {
            "webhook": {
                "url": webhook_url
            }
        }
    }

    resp = requests.post(
        f"{ELEVENLABS_BASE_URL}/convai/agents/create",
        headers=get_headers(),
        json=payload
    )
    resp.raise_for_status()
    return resp.json()


def update_agent(agent_id: str, shop: dict) -> dict:
    """Update an existing ElevenLabs agent's prompt and greeting."""
    prompt = build_agent_prompt(shop)
    greeting = shop.get("greeting", f"Thanks for calling {shop.get('name', 'the shop')}, what can we do for you?")

    payload = {
        "name": shop.get("name", "AI Receptionist"),
        "conversation_config": {
            "agent": {
                "prompt": {
                    "prompt": prompt,
                    "max_tokens": 200
                },
                "first_message": greeting
            }
        }
    }

    resp = requests.patch(
        f"{ELEVENLABS_BASE_URL}/convai/agents/{agent_id}",
        headers=get_headers(),
        json=payload
    )
    resp.raise_for_status()
    return resp.json()


def delete_agent(agent_id: str) -> None:
    """Delete an ElevenLabs agent."""
    requests.delete(
        f"{ELEVENLABS_BASE_URL}/convai/agents/{agent_id}",
        headers=get_headers()
    )


def get_twilio_webhook_url(agent_id: str) -> str:
    """Returns the ElevenLabs Twilio inbound call URL for this agent."""
    return f"{ELEVENLABS_BASE_URL}/convai/twilio/inbound_calls?agent_id={agent_id}"
