"""One-time script to create the session_reminder WhatsApp template via Meta API.

Usage:
    cd backend
    python scripts/create_reminder_template.py

The template will be submitted for Meta review. Once approved, set:
    REMINDER_TEMPLATE_NAME=session_reminder
in your environment variables.
"""
import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

WABA_ID = os.getenv('WHATSAPP_WABA_ID')
API_KEY = os.getenv('WHATSAPP_API_KEY', '').strip()
API_URL = os.getenv('WHATSAPP_API_URL', 'https://graph.facebook.com/v18.0').strip()

if not WABA_ID or not API_KEY:
    print("Missing WHATSAPP_WABA_ID or WHATSAPP_API_KEY in .env")
    sys.exit(1)

url = f"{API_URL}/{WABA_ID}/message_templates"
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

payload = {
    "name": "session_reminder",
    "language": "en_US",
    "category": "UTILITY",
    "components": [
        {
            "type": "BODY",
            "text": (
                "Hi {{1}}! Your coaching session starts at {{2}} at {{3}}. "
                "Please share your location in this chat to check in "
                "(tap + or the paperclip icon, then Location, then Send your current location)."
            ),
            "example": {
                "body_text": [["Coach Tim", "14:00", "UWC Sports Ground"]]
            },
        }
    ],
}

print(f"Submitting template to WABA {WABA_ID}...")
resp = requests.post(url, json=payload, headers=headers)

if resp.ok:
    data = resp.json()
    print(f"Template submitted successfully! ID: {data.get('id')}")
    print(f"Status: {data.get('status', 'PENDING')}")
    print("\nOnce approved by Meta, add to your env:")
    print("  REMINDER_TEMPLATE_NAME=session_reminder")
else:
    print(f"Error {resp.status_code}: {resp.text}")
    sys.exit(1)
