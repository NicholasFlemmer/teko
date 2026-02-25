import requests
from config import Config

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
        
        # Debug: print token info
        token = Config.WHATSAPP_API_KEY
        print(f"🔑 Token length: {len(token)}, First 20 chars: {token[:20]}, Last 20: {token[-20:]}")
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # Format phone number (remove + and spaces)
        formatted_phone = phone_number.replace('+', '').replace(' ', '').replace('-', '')
        
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
        """Send check-in reminder to coach
        
        Args:
            coach_phone: Coach's phone number
            coach_name: Coach's name
            session_time: Session time
            location_address: Location address
            check_in_url: Check-in URL
            
        Returns:
            dict: Send result
        """
        from services.gemini_service import GeminiService
        
        # Generate personalized message using Gemini
        message_text = GeminiService.generate_check_in_message(
            coach_name=coach_name,
            session_time=session_time,
            location_address=location_address
        )
        
        # Send WhatsApp message
        return cls.send_message(
            phone_number=coach_phone,
            message_text=message_text,
            check_in_url=check_in_url
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
        
        formatted_phone = phone_number.replace('+', '').replace(' ', '').replace('-', '')
        
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
