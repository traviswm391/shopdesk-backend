from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from app.config import settings
import logging

logger = logging.getLogger(__name__)
client = Client(settings.twilio_account_sid, settings.twilio_auth_token)

def provision_phone_number(area_code="415"):
    # Reuse existing number if one exists (handles trial account limits)
    existing = client.incoming_phone_numbers.list(limit=1)
    if existing:
        logger.info(f"Reusing existing Twilio number: {existing[0].phone_number}")
        return existing[0].phone_number
    # Buy a new number
    available = client.available_phone_numbers("US").local.list(area_code=area_code, sms_enabled=True, voice_enabled=True, limit=1)
    if not available:
        available = client.available_phone_numbers("US").local.list(sms_enabled=True, voice_enabled=True, limit=1)
    if not available:
        raise Exception("No available phone numbers")
    purchased = client.incoming_phone_numbers.create(phone_number=available[0].phone_number)
    return purchased.phone_number

def configure_number_for_retell(phone_number, retell_webhook_url):
    numbers = client.incoming_phone_numbers.list(phone_number=phone_number)
    if not numbers:
        raise Exception(f"Phone {phone_number} not found")
    numbers[0].update(voice_url=retell_webhook_url, voice_method="POST")

def send_sms(to, from_, body):
    try:
        msg = client.messages.create(body=body, from_=from_, to=to)
        return msg.sid
    except TwilioRestException as e:
        logger.error(f"SMS failed: {e}")
        raise
