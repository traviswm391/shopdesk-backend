import requests
from app.config import settings
import logging

logger = logging.getLogger(__name__)

RETELL_BASE_URL = "https://api.retellai.com"
HEADERS = {
    "Authorization": f"Bearer {settings.retell_api_key}",
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
    days = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
    for day in days:
        h = hours.get(day, {})
        if h.get("closed"):
            hours_str += f"{day.capitalize()}: Closed\n"
        else:
            hours_str += f"{day.capitalize()}: {h.get('open', '8:00 AM')} - {h.get('close', '5:00 PM')}\n"
    declined_str = ""
    if declined_services:
        declined_list = ", ".join(declined_services)
        declined_str = f"\nServices this shop does NOT perform (declined jobs):\n{declined_list}\n\nIf a caller asks about any of these services, be straight with them — let them know that's not something the shop handles, and suggest they contact a specialist. Don't book appointments for declined services under any circumstances.\n"
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
- After hours calls: grab their info and let them know someone will get back to them first thing next business day
- Always double-check the phone number before you wrap up
- Don't commit to specific times — say "we'll lock in the exact slot and confirm with you"
- If someone's rude or aggressive, stay calm and professional — don't match their energy

Open every call with: "{greeting}"
"""


def create_agent(shop: dict) -> dict:
    prompt = build_agent_prompt(shop)
    payload = {
        "response_engine": {
            "type": "retell-llm",
            "llm_id": None
        },
        "voice_id": "11labs-Adrian",
        "agent_name": shop.get("name", "AI Receptionist"),
    }
    # First create the LLM
    llm_payload = {
        "model": "gpt-4o",
        "general_prompt": prompt,
        "begin_message": shop.get("greeting", f"Thanks for calling {shop.get('name', 'the shop')}, what can we do for you?"),
        "general_tools": [
            {
                "type": "end_call",
                "name": "end_call",
                "description": "End the call after appointment is booked and confirmed or caller says goodbye."
            }
        ]
    }
    llm_resp = requests.post(
        f"{RETELL_BASE_URL}/create-retell-llm",
        headers=HEADERS,
        json=llm_payload
    )
    llm_resp.raise_for_status()
    llm_data = llm_resp.json()
    llm_id = llm_data["llm_id"]

    payload["response_engine"]["llm_id"] = llm_id
    agent_resp = requests.post(
        f"{RETELL_BASE_URL}/create-agent",
        headers=HEADERS,
        json=payload
    )
    agent_resp.raise_for_status()
    return agent_resp.json()


def update_agent(agent_id: str, shop: dict) -> dict:
    prompt = build_agent_prompt(shop)
    # Get the agent to find the llm_id
    get_resp = requests.get(
        f"{RETELL_BASE_URL}/get-agent/{agent_id}",
        headers=HEADERS
    )
    get_resp.raise_for_status()
    agent_data = get_resp.json()
    llm_id = agent_data.get("response_engine", {}).get("llm_id")

    if llm_id:
        llm_payload = {
            "general_prompt": prompt,
            "begin_message": shop.get("greeting", f"Thanks for calling {shop.get('name', 'the shop')}, what can we do for you?"),
        }
        requests.patch(
            f"{RETELL_BASE_URL}/update-retell-llm/{llm_id}",
            headers=HEADERS,
            json=llm_payload
        )

    agent_payload = {
        "agent_name": shop.get("name", "AI Receptionist"),
    }
    resp = requests.patch(
        f"{RETELL_BASE_URL}/update-agent/{agent_id}",
        headers=HEADERS,
        json=agent_payload
    )
    resp.raise_for_status()
    return resp.json()


def delete_agent(agent_id: str) -> None:
    requests.delete(
        f"{RETELL_BASE_URL}/delete-agent/{agent_id}",
        headers=HEADERS
    )


def import_twilio_number(phone_number: str, agent_id: str) -> dict:
    payload = {
        "phone_number": phone_number,
        "termination_uri": None,
        "inbound_agent_id": agent_id,
    }
    resp = requests.post(
        f"{RETELL_BASE_URL}/import-phone-number",
        headers=HEADERS,
        json=payload
    )
    resp.raise_for_status()
    return resp.json()
