import requests
from app.config import settings
import logging

logger = logging.getLogger(__name__)
RETELL_BASE_URL = "https://api.retellai.com"
HEADERS = {"Authorization": f"Bearer {settings.retell_api_key}", "Content-Type": "application/json"}

def build_agent_prompt(shop):
    shop_name = shop.get("name", "the shop")
    address = shop.get("address", "")
    services = shop.get("services", [])
    greeting = shop.get("greeting", f"Thank you for calling {shop_name}!")
    hours = shop.get("business_hours", {})
    services_str = ", ".join(services) if services else "general auto repair and maintenance"
    hours_lines = []
    for day in ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]:
        h = hours.get(day, {})
        if h.get("closed"):
            hours_lines.append(f"{day.capitalize()}: Closed")
        else:
            hours_lines.append(f"{day.capitalize()}: {h.get('open','8:00 AM')} - {h.get('close','5:00 PM')}")
    hours_str = "\n".join(hours_lines)
    return f"""You are the AI receptionist for {shop_name}{", located at " + address if address else ""}. You answer calls professionally, help customers book appointments, and answer common questions about auto repair services. You speak naturally — this is a phone call, so keep responses brief and conversational.

Greeting: Start every call with: "{greeting}"

YOUR GOALS:
1. Greet the caller and understand why they are calling
2. Walk them through the appointment booking flow below
3. Answer common questions about services and pricing honestly
4. Handle after-hours calls gracefully

APPOINTMENT BOOKING FLOW — collect in this order:
Step 1 – Vehicle: Ask for the year, make, and model (e.g. "2019 Toyota Camry")
Step 2 – Issue or service: Ask what they need or what they're experiencing (e.g. oil change, brakes squeaking, check engine light on)
Step 3 – Contact info: Ask for their name and best callback phone number
Step 4 – Preferred time: Ask for their preferred drop-off date and time
Step 5 – Confirm: Read back all details and let them know a text confirmation is coming

SERVICES OFFERED:
{services_str}

COMMON SERVICES & TYPICAL PRICE RANGES (always clarify exact pricing requires a tech inspection):
• Oil change (conventional): $35–$55 | Full synthetic: $65–$95
• Brake pad replacement (per axle): $150–$300
• Brake rotor replacement (per axle): $250–$450
• Tire rotation: $20–$50
• Battery replacement: $100–$200 parts and labor
• Alternator replacement: $400–$700
• Wheel alignment: $80–$150
• Check engine light diagnostic: $80–$150
• AC recharge: $150–$300
• Coolant flush: $100–$175
• Spark plug replacement: $100–$300 depending on vehicle
• Timing belt/chain service: $400–$1,000+
• Transmission fluid service: $100–$200

BUSINESS HOURS:
{hours_str}

RULES:
• Keep responses to 2–3 sentences — this is a voice call, not a chat
• Never give an exact final price — share the typical range and say the tech will provide a firm quote after seeing the vehicle
• If asked about a service not listed, say you can likely help and a tech will confirm
• Do not diagnose mechanical problems — collect symptoms and let the tech assess
• Do not promise same-day availability — say "we'll do our best" or "the team will confirm"
• If a caller is frustrated, empathize first: "I completely understand, let's get this taken care of for you"
• Do not discuss competitor shops

AFTER HOURS:
If calling outside business hours, acknowledge it warmly, collect their name, phone, vehicle, and issue, and let them know someone will call them back when the shop opens. Never turn a caller away.
"""
def create_agent(shop, webhook_url):
    prompt = build_agent_prompt(shop)
    llm_payload = {"model": "gpt-4o", "general_prompt": prompt, "general_tools": []}
    llm_resp = requests.post(f"{RETELL_BASE_URL}/create-retell-llm", headers=HEADERS, json=llm_payload)
    if llm_resp.status_code not in (200, 201):
        raise Exception(f"Retell LLM error: {llm_resp.text}")
    llm_id = llm_resp.json()["llm_id"]
    agent_payload = {"agent_name": f"{shop['name']} AI Receptionist", "voice_id": "11labs-Adrian", "response_engine": {"type": "retell-llm", "llm_id": llm_id}, "webhook_url": webhook_url, "language": "en-US"}
    agent_resp = requests.post(f"{RETELL_BASE_URL}/create-agent", headers=HEADERS, json=agent_payload)
    if agent_resp.status_code not in (200, 201):
        raise Exception(f"Retell agent error: {agent_resp.text}")
    return agent_resp.json()["agent_id"], llm_id

def update_agent(agent_id, shop):
    prompt = build_agent_prompt(shop)
    agent_resp = requests.get(f"{RETELL_BASE_URL}/get-agent/{agent_id}", headers=HEADERS)
    if agent_resp.status_code == 200:
        llm_id = agent_resp.json().get("response_engine", {}).get("llm_id")
        if llm_id:
            requests.patch(f"{RETELL_BASE_URL}/update-retell-llm/{llm_id}", headers=HEADERS, json={"general_prompt": prompt})

def delete_agent(agent_id):
    requests.delete(f"{RETELL_BASE_URL}/delete-agent/{agent_id}", headers=HEADERS)

def import_twilio_number(phone_number, retell_agent_id):
    payload = {"phone_number": phone_number, "inbound_agent_id": retell_agent_id}
    resp = requests.post(f"{RETELL_BASE_URL}/create-phone-number", headers=HEADERS, json=payload)
    if resp.status_code not in (200, 201):
        raise Exception(f"Retell phone error: {resp.text}")
