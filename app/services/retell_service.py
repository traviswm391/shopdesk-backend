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
    agent_resp = requests.post(f"{RETELL_BASE_UR}/create-agent", headers=HEADERS, json=agent_payload)
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
