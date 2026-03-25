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
    """Build a system prompt for the Retell AI agent based on shop config."""
    shop_name = shop.get("name", "the shop")
    address = shop.get("address", "")
    services = shop.get("services", [])
    greeting = shop.get("greeting", f"Thank you for calling {shop_name}!")
    hours = shop.get("business_hours", {})

    services_str = ", ".join(services) if services else "general auto repair and maintenance"

    hours_str = ""
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for day in days:
        h = hours.get(day, {})
        if h.get("closed"):
            hours_str += f"{day.capitalize()}: Closed\n"
        else:
            hours_str += f"{day.capitalize()}: {h.get('open', '8:00 AM')} - {h.get('close', '5:00 PM')}\n"

    return f"""You are the AI receptionist for {shop_name}, an auto mechanic shop{"located at " + address if address else ""}.

Your job is to:
1. Greet callers warmly
2. Understand what service they need
3. Collect their information to book an appointment:
   - Full name
   - Best callback phone number
   - Vehicle make, model, and year
   - Service or repair needed
   - Preferred date and time
4. Confirm the appointment details back to the customer
5. Let them know the shop will send them a text confirmation

Business hours:
{hours_str}
Services offered: {services_str}

Important rules:
- Be friendly, professional, and concise
- If asked about pricing, say prices vary by job and the team will provide a quote
- If someone calls after hours, take their info and tell them the shop will call back next business day
- Always confirm you have the right phone number before ending the call
- Do NOT make up availability — tell them "we'll confirm the exact time shortly"

Start every call with: "{greeting}"
"""


def create_agent(shop: dict, webhook_url: str) -> str:
    """Create a Retell AI agent for a shop. Returns the agent_id."""
    prompt = build_agent_prompt(shop)

    llm_payload = {
        "model": "gpt-4o",
        "general_prompt": prompt,
        "general_tools": [],
        "starting_state": "introduction",
        "states": [
            {
                "name": "introduction",
                "state_prompt": prompt,
                "edges": []
            }
        ]
    }

    llm_resp = requests.post(
        f"{RETELL_BASE_URL}/create-retell-llm",
        headers=HEADERS,
        json=llm_payload
    )

    if llm_resp.status_code not in (200, 201):
        logger.error(f"Failed to create Retell LLM: {llm_resp.text}")
        raise Exception(f"Retell LLM creation failed: {llm_resp.text}")

    llm_id = llm_resp.json()["llm_id"]

    agent_payload = {
        "agent_name": f"{shop['name']} AI Receptionist",
        "voice_id": "11labs-Adrian",
        "response_engine": {
            "type": "retell-llm",
            "llm_id": llm_id
        },
        "webhook_url": webhook_url,
        "enable_backchannel": True,
        "ambient_sound": "coffee-shop",
        "language": "en-US",
        "opt_out_sensitive_data_storage": False
    }

    agent_resp = requests.post(
        f"{RETELL_BASE_URL}/create-agent",
        headers=HEADERS,
        json=agent_payload
    )

    if agent_resp.status_code not in (200, 201):
        logger.error(f"Failed to create Retell agent: {agent_resp.text}")
        raise Exception(f"Retell agent creation failed: {agent_resp.text}")

    return agent_resp.json()["agent_id"], llm_id


def update_agent(agent_id: str, shop: dict):
    """Update an existing agent's prompt when shop settings change."""
    prompt = build_agent_prompt(shop)

    agent_resp = requests.get(
        f"{RETELL_BASE_URL}/get-agent/{agent_id}",
        headers=HEADERS
    )
    if agent_resp.status_code != 200:
        raise Exception(f"Could not fetch agent {agent_id}")

    llm_id = agent_resp.json().get("response_engine", {}).get("llm_id")

    if llm_id:
        requests.patch(
            f"{RETELL_BASE_URL}/update-retell-llm/{llm_id}",
            headers=HEADERS,
            json={"general_prompt": prompt}
        )


def delete_agent(agent_id: str):
    """Delete a Retell AI agent."""
    requests.delete(f"{RETELL_BASE_URL}/delete-agent/{agent_id}", headers=HEADERS)


def import_twilio_number(phone_number: str, retell_agent_id: str):
    """Import an existing Twilio number into Retell AI and link it to an agent."""
    payload = {
        "phone_number": phone_number,
        "twilio_account_sid": settings.twilio_account_sid,
        "twilio_auth_token": settings.twilio_auth_token,
        "inbound_agent_id": retell_agent_id,
        "termination_uri": f"{settings.twilio_account_sid}.pstn.twilio.com"
    }

    resp = requests.post(
        f"{RETELL_BASE_URL}/import-phone-number",
        headers=HEADERS,
        json=payload
    )

    if resp.status_code not in (200, 201):
        logger.error(f"Failed to import number to Retell: {resp.text}")
        raise Exception(f"Retell phone import failed: {resp.text}")
