import google.generativeai as genai
import logging
from config import Config

logger = logging.getLogger(__name__)

# Timeout for Gemini API calls in seconds
GEMINI_TIMEOUT = 30

class GeminiService:
    """Service for Google Gemini AI operations"""
    
    _model = None
    
    @classmethod
    def initialize(cls):
        """Initialize Gemini AI"""
        api_key = Config.GEMINI_API_KEY
        if not api_key:
            logger.error("GEMINI_API_KEY not configured — AI features will not work")
            cls._model = None
            return None
        genai.configure(api_key=api_key)
        cls._model = genai.GenerativeModel('gemini-2.5-flash')
        return cls._model
    
    @classmethod
    def get_model(cls):
        """Get Gemini model instance"""
        if cls._model is None:
            cls.initialize()
        return cls._model
    
    @classmethod
    def generate_check_in_message(cls, coach_name, session_time, location_address):
        """Generate a personalized check-in message for WhatsApp
        
        Args:
            coach_name: Name of the coach
            session_time: Time of the session (e.g., "14:30")
            location_address: Address of the session location
            
        Returns:
            str: Generated message text
        """
        model = cls.get_model()
        if model is None:
            return f"Hi {coach_name}! 👋 Your session at {location_address} starts at {session_time}. Please share your location here to check in 📍 (tap + → Location → Send current location)."

        prompt = f"""Generate a friendly, professional WhatsApp message to remind a coach about their upcoming session.

Coach Name: {coach_name}
Session Time: {session_time}
Location: {location_address}

The message should:
- Be warm and professional
- Include an emoji or two for friendliness
- Ask them to share their location in this chat to check in (tap the + or 📎 button → Location → Send current location)
- Be concise (2-3 sentences maximum)
- Use a casual but respectful tone

Generate ONLY the message text, without any additional formatting or explanations."""
        
        try:
            response = model.generate_content(prompt)
            text = getattr(response, 'text', None)
            if not text:
                raise ValueError("Empty response from Gemini")
            return text.strip()
        except Exception as e:
            logger.warning(f"Gemini check-in message failed: {e}")
            return f"Hi {coach_name}! 👋 Your session at {location_address} starts at {session_time}. Please share your location here to check in 📍 (tap + → Location → Send current location)."

    @classmethod
    def generate_custom_message(cls, prompt):
        """Generate custom message based on prompt

        Args:
            prompt: Custom prompt for message generation

        Returns:
            str: Generated text
        """
        model = cls.get_model()
        if model is None:
            return "Sorry, the AI assistant is not configured. Please contact your administrator."

        try:
            response = model.generate_content(prompt)
            text = getattr(response, 'text', None)
            if not text:
                raise ValueError("Empty response from Gemini")
            return text.strip()
        except Exception as e:
            logger.warning(f"Gemini custom message failed: {e}")
            return "Sorry, I couldn't generate a response right now. Please try again."
