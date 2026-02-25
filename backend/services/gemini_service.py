import google.generativeai as genai
from config import Config

class GeminiService:
    """Service for Google Gemini AI operations"""
    
    _model = None
    
    @classmethod
    def initialize(cls):
        """Initialize Gemini AI"""
        genai.configure(api_key=Config.GEMINI_API_KEY)
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
        
        prompt = f"""Generate a friendly, professional WhatsApp message to remind a coach about their upcoming session. 
        
Coach Name: {coach_name}
Session Time: {session_time}
Location: {location_address}

The message should:
- Be warm and professional
- Include an emoji or two for friendliness
- Mention that they need to check in using a link (don't include the actual link, just mention it)
- Be concise (2-3 sentences maximum)
- Use a casual but respectful tone

Generate ONLY the message text, without any additional formatting or explanations."""
        
        try:
            response = model.generate_content(prompt)
            message = response.text.strip()
            return message
        except Exception as e:
            # Fallback to a default message if Gemini fails
            return f"Hi {coach_name}! 👋 Your session at {location_address} starts at {session_time} (in 10 minutes). Please check in using the link below to confirm your attendance."
    
    @classmethod
    def generate_custom_message(cls, prompt):
        """Generate custom message based on prompt
        
        Args:
            prompt: Custom prompt for message generation
            
        Returns:
            str: Generated text
        """
        model = cls.get_model()
        
        try:
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"Error generating message: {str(e)}"
