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
    return f"""You are the AI receptionist for {shop_name}{", located at " + address if address else ""}.
Your job: 1. Greet warmly 2. Understand service needed 3. Collect: name, phone, vehicle make/model/year, service, preferred date/time 4. Confirm details 5. Tell them text confirmation is coming.
Hours: {', '.join(hours_lines)}
Services: {services_str}
Rules: Be friendly and concise. If asked price, say team provides quote. Afwer hours: take info, say we'll call back next business day.
Greet: "{greeting}"""

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