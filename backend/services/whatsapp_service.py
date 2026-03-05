import requests
from config import Config
from utils.phone import normalize_sa_phone

class WhatsAppService:
    """Service for WhatsApp Business API operations"""

    @classmethod
    def send_message(cls, phone_number, message_text, check_in_url=None):
        """Send a WhatsApp message

        Args:
            phone_number: Recipient phone number (with country code, e.g., +27821234567)
            message_text: Message content
            check_in_url: Optional check-in URL to include

        Returns:
            dict: API response or error
        """
        url = f"{Config.WHATSAPP_API_URL}/{Config.WHATSAPP_PHONE_NUMBER_ID}/messages"

        token = Config.WHATSAPP_API_KEY

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        formatted_phone = normalize_sa_phone(phone_number)
        if not formatted_phone:
            print(f"Invalid phone number: {phone_number}")
            return {"success": False, "error": f"Invalid phone number: {phone_number}"}
        
        # Construct message body
        full_message = message_text
        if check_in_url:
            full_message += f"\n\n🔗 Check in here: {check_in_url}"
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": formatted_phone,
            "type": "text",
            "text": {
                "preview_url": True,
                "body": full_message
            }
        }
        
        try:
            print(f"📤 Sending WhatsApp message to: {formatted_phone}")
            print(f"📝 Message: {full_message[:50]}...")
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            response_data = response.json()
            print(f"✅ WhatsApp API Response: {response_data}")
            return {
                "success": True,
                "data": response_data,
                "status_code": response.status_code
            }
        except requests.exceptions.RequestException as e:
            error_detail = str(e)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                except:
                    error_detail = e.response.text
            print(f"❌ WhatsApp API Error: {error_detail}")
            return {
                "success": False,
                "error": str(e),
                "error_detail": error_detail,
                "status_code": getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None
            }
    
    @classmethod
    def send_check_in_reminder(cls, coach_phone, coach_name, session_time, location_address, check_in_url):
        """Send check-in reminder using the approved teko_session_reminder template.

        Template body: "Hi Coach {{1}}! Your session at {{2}} starts at {{3}}. ..."
        Button URL:    ".../check-in/{{1}}"

        Falls back to Gemini plain-text if REMINDER_TEMPLATE_NAME is explicitly
        set to empty string.
        """
        template_name = Config.REMINDER_TEMPLATE_NAME
        if template_name:
            # Extract token from check_in_url (last path segment)
            token = check_in_url.rsplit('/', 1)[-1] if check_in_url else ''

            components = [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": coach_name},
                        {"type": "text", "text": location_address or "TBC"},
                        {"type": "text", "text": session_time},
                    ]
                },
                {
                    "type": "button",
                    "sub_type": "url",
                    "index": "0",
                    "parameters": [
                        {"type": "text", "text": token}
                    ]
                },
            ]
            return cls.send_template_message(
                phone_number=coach_phone,
                template_name=template_name,
                language_code=Config.REMINDER_TEMPLATE_LANGUAGE,
                components=components,
            )

        # Fallback: plain-text via Gemini
        from services.gemini_service import GeminiService
        message_text = GeminiService.generate_check_in_message(
            coach_name=coach_name,
            session_time=session_time,
            location_address=location_address,
        )
        return cls.send_message(
            phone_number=coach_phone,
            message_text=message_text,
        )
    
    @classmethod
    def send_template_message(cls, phone_number, template_name, language_code="en", components=None):
        """Send a WhatsApp template message
        
        Args:
            phone_number: Recipient phone number
            template_name: Name of the approved template
            language_code: Template language code
            components: Template components (variables, buttons, etc.)
            
        Returns:
            dict: API response or error
        """
        url = f"{Config.WHATSAPP_API_URL}/{Config.WHATSAPP_PHONE_NUMBER_ID}/messages"
        
        headers = {
            "Authorization": f"Bearer {Config.WHATSAPP_API_KEY}",
            "Content-Type": "application/json"
        }
        
        formatted_phone = normalize_sa_phone(phone_number)
        if not formatted_phone:
            print(f"Invalid phone number for template: {phone_number}")
            return {"success": False, "error": f"Invalid phone number: {phone_number}"}

        payload = {
            "messaging_product": "whatsapp",
            "to": formatted_phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {
                    "code": language_code
                }
            }
        }
        
        if components:
            payload["template"]["components"] = components
        
        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return {
                "success": True,
                "data": response.json(),
                "status_code": response.status_code
            }
        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": str(e),
                "status_code": getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None
            }

    @classmethod
    def mark_as_read(cls, message_id):
        """Mark an incoming WhatsApp message as read (shows blue ticks)

        Args:
            message_id: The wamid of the incoming message

        Returns:
            dict: API response or error
        """
        url = f"{Config.WHATSAPP_API_URL}/{Config.WHATSAPP_PHONE_NUMBER_ID}/messages"

        headers = {
            "Authorization": f"Bearer {Config.WHATSAPP_API_KEY}",
            "Content-Type": "application/json"
        }

        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id
        }

        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            print(f"✅ Marked message {message_id} as read")
            return {"success": True, "data": response.json()}
        except requests.exceptions.RequestException as e:
            error_detail = str(e)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                except:
                    error_detail = e.response.text
            print(f"⚠️ Failed to mark message as read: {error_detail}")
            return {"success": False, "error": str(e), "error_detail": error_detail}

    @classmethod
    def send_typing_indicator(cls, message_id):
        """Show typing indicator to the user (requires Cloud API v21.0+)

        The typing indicator shows for ~25 seconds or until a message is sent,
        whichever comes first.

        Args:
            message_id: The wamid of the message being replied to

        Returns:
            dict: API response or error
        """
        url = f"{Config.WHATSAPP_TYPING_API_URL}/{Config.WHATSAPP_PHONE_NUMBER_ID}/messages"

        headers = {
            "Authorization": f"Bearer {Config.WHATSAPP_API_KEY}",
            "Content-Type": "application/json"
        }

        payload = {
            "messaging_product": "whatsapp",
            "status": "typing",
            "message_id": message_id
        }

        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            print(f"⌨️ Typing indicator sent for message {message_id}")
            return {"success": True, "data": response.json()}
        except requests.exceptions.RequestException as e:
            error_detail = str(e)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                except:
                    error_detail = e.response.text
            print(f"⚠️ Failed to send typing indicator: {error_detail}")
            return {"success": False, "error": str(e), "error_detail": error_detail}

    @classmethod
    def get_message_templates(cls):
        """Fetch approved message templates from the WhatsApp Business Account.

        Returns:
            dict: {success, templates} or {success, error}
        """
        waba_id = Config.WHATSAPP_WABA_ID
        if not waba_id:
            return {"success": False, "error": "WHATSAPP_WABA_ID not configured"}

        url = f"{Config.WHATSAPP_API_URL}/{waba_id}/message_templates"
        headers = {
            "Authorization": f"Bearer {Config.WHATSAPP_API_KEY}",
        }
        params = {
            "fields": "name,status,language,components,category",
            "limit": 100,
        }

        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            templates = [t for t in data.get("data", []) if t.get("status") == "APPROVED"]
            return {"success": True, "templates": templates}
        except requests.exceptions.RequestException as e:
            error_detail = str(e)
            if hasattr(e, "response") and e.response is not None:
                try:
                    error_detail = e.response.json()
                except Exception:
                    error_detail = e.response.text
            print(f"❌ Failed to fetch templates: {error_detail}")
            return {"success": False, "error": str(e), "error_detail": error_detail}
