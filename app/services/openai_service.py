from openai import OpenAI
from app.config import settings
import json

client = OpenAI(api_key=settings.openai_api_key)

def extract_appointment_from_transcript(transcript: str, shop_name: str) -> dict:
    prompt = f"""You are an assistant that extracts appointment information from phone call transcripts for an auto mechanic shop called "{shop_name}".

Given the transcript below, extract the following details if mentioned:
- customer_name, customer_phone, vehicle_info, service_requested
- preferred_date, preferred_time, notes
- appointment_booked: true if appointment was successfully scheduled
- summary: 1-2 sentence summary of the call

Return ONLY a valid JSON object. Use null for missing fields.

Transcript:
{transcript}"""
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0
    )
    return json.loads(response.choices[0].message.content)


def generate_sms_confirmation(appointment_details: dict, shop_name: str, shop_phone: str) -> str:
    details_str = json.dumps(appointment_details, indent=2)
    prompt = f"""Write a brief SMS confirmation (max 160 chars) for: {shop_name}. Details: {details_str}. End with shop phone: {shop_phone}"""
    response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}], temperature=0.3)
    return response.choices[0].message.content.strip()
