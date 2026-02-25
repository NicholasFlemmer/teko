from services.firebase_service import FirebaseService
from services.gemini_service import GeminiService
from services.whatsapp_service import WhatsAppService
from datetime import datetime
import uuid
import re

class ConversationService:
    """Service for managing AI conversations with coaches via WhatsApp"""
    
    CRICKET_COACHING_PROMPT = """You are a professional cricket coaching specialist assistant helping coaches in South Africa.

EXPERTISE:
- Cricket techniques: Batting (grip, stance, footwork, shots), Bowling (grip, action, variations), Fielding (catching, throwing, positioning)
- Coaching methodologies and player development
- Training drills and practice sessions
- Match strategy, tactics, and field placements
- Physical fitness and conditioning for cricket
- Mental preparation and sports psychology
- Youth cricket development (U10 to U19)
- South African cricket context (facilities, weather, conditions)

YOUR ROLE:
- Provide practical, actionable coaching advice
- Suggest specific drills and exercises
- Explain techniques clearly and simply
- Consider the coach's level and resources
- Be encouraging and supportive

COMMUNICATION STYLE:
- Professional but friendly
- Concise responses (suitable for WhatsApp)
- Use bullet points and numbered lists
- Include practical examples
- Ask clarifying questions when needed

LANGUAGE:
- Detect and respond in the SAME language the coach uses
- Support all 11 official South African languages:
  * Afrikaans, English
  * isiNdebele, isiXhosa, isiZulu
  * Sepedi, Sesotho, Setswana
  * siSwati, Tshivenda, Xitsonga

CONSTRAINTS:
- Keep responses under 1000 characters when possible
- Focus on cricket coaching only
- If asked about non-cricket topics, politely redirect
- Don't provide medical advice, refer to professionals

Remember: You're helping coaches develop their skills and help their players improve."""

    @classmethod
    def get_conversation_history(cls, coach_phone, limit=10):
        """Get recent conversation history for a coach"""
        db = FirebaseService.get_db()
        
        # Format phone number
        phone_key = coach_phone.replace('+', '').replace(' ', '').replace('-', '')
        
        try:
            # Get messages from Firestore
            messages_ref = db.collection('conversations').document(phone_key).collection('messages')
            messages = messages_ref.order_by('timestamp', direction='DESCENDING').limit(limit).stream()
            
            history = []
            for msg in messages:
                msg_data = msg.to_dict()
                history.append({
                    'role': msg_data.get('role'),
                    'content': msg_data.get('content'),
                    'timestamp': msg_data.get('timestamp')
                })
            
            # Reverse to get chronological order (oldest first)
            history.reverse()
            return history
        except Exception as e:
            print(f"Error loading conversation history: {e}")
            return []
    
    @classmethod
    def strip_markdown(cls, text):
        """Remove markdown formatting from text for WhatsApp
        
        Args:
            text: Text with markdown formatting
            
        Returns:
            str: Plain text without markdown
        """
        # Remove bold/italic markers (* or **)
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # **bold**
        text = re.sub(r'\*([^*]+)\*', r'\1', text)      # *italic*
        text = re.sub(r'__([^_]+)__', r'\1', text)      # __bold__
        text = re.sub(r'_([^_]+)_', r'\1', text)        # _italic_
        
        # Convert markdown bullet points to simple dashes
        text = re.sub(r'^\s*[\*\-\+]\s+', '- ', text, flags=re.MULTILINE)
        
        # Remove markdown headers (##, ###, etc.) but keep the text
        text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
        
        # Convert numbered lists (1., 2., etc.) to consistent format
        text = re.sub(r'^\s*(\d+)\.\s+', r'\1. ', text, flags=re.MULTILINE)
        
        return text.strip()
    
    @classmethod
    def save_message(cls, coach_phone, role, content):
        """Save a message to conversation history"""
        db = FirebaseService.get_db()
        
        # Format phone number
        phone_key = coach_phone.replace('+', '').replace(' ', '').replace('-', '')
        
        try:
            message_data = {
                'role': role,  # 'user' or 'assistant'
                'content': content,
                'timestamp': datetime.utcnow(),
                'message_id': str(uuid.uuid4())
            }
            
            db.collection('conversations').document(phone_key).collection('messages').add(message_data)
            print(f"💾 Saved {role} message to conversation history")
        except Exception as e:
            print(f"Error saving message: {e}")
    
    @classmethod
    def generate_response(cls, coach_phone, user_message, coach_name=None):
        """Generate AI response to coach's message"""
        try:
            # Get conversation history
            history = cls.get_conversation_history(coach_phone, limit=5)
            
            # Build context for Gemini
            context = cls.CRICKET_COACHING_PROMPT + "\n\n"
            
            if coach_name:
                context += f"You are chatting with Coach {coach_name}.\n\n"
            
            context += "Recent conversation:\n"
            for msg in history:
                role_label = "Coach" if msg['role'] == 'user' else "You"
                context += f"{role_label}: {msg['content']}\n"
            
            context += f"\nCoach: {user_message}\nYou:"
            
            # Generate response using Gemini
            response = GeminiService.generate_custom_message(context)
            
            # Strip markdown formatting for WhatsApp
            clean_response = cls.strip_markdown(response)
            
            # Save both messages to history
            cls.save_message(coach_phone, 'user', user_message)
            cls.save_message(coach_phone, 'assistant', clean_response)
            
            return clean_response
            
        except Exception as e:
            print(f"Error generating response: {e}")
            return "I apologize, I'm having trouble responding right now. Please try again in a moment. 🏏"
    
    @classmethod
    def handle_incoming_message(cls, from_number, message_text, message_id):
        """Handle an incoming WhatsApp message from a coach"""
        try:
            print(f"📨 Processing message from {from_number}: {message_text[:50]}...")
            
            # Check if this is from a registered coach
            coach = cls.get_coach_by_phone(from_number)
            
            if not coach:
                print(f"⚠️ Message from unregistered number: {from_number}")
                # Send a message explaining they need to be registered
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text="Hello! To use the Teko Cricket Coaching Assistant, you need to be registered as a coach. Please contact your administrator. 🏏"
                )
                return
            
            print(f"✅ Identified coach: {coach.get('name', 'Unknown')}")
            
            # Check for commands
            if message_text.strip().lower() in ['/help', 'help', '/start']:
                response = cls.get_help_message(coach.get('name'))
            elif message_text.strip().lower() in ['/reset', 'reset']:
                response = "Your conversation has been reset. Feel free to ask me anything about cricket coaching! 🏏"
                # Note: We keep history, don't actually delete it
            else:
                # Generate AI response
                response = cls.generate_response(
                    coach_phone=from_number,
                    user_message=message_text,
                    coach_name=coach.get('name')
                )
            
            # Send response via WhatsApp
            result = WhatsAppService.send_message(
                phone_number=from_number,
                message_text=response
            )
            
            if result.get('success'):
                print(f"✅ Response sent successfully to {coach.get('name')}")
            else:
                print(f"❌ Failed to send response: {result.get('error')}")
            
        except Exception as e:
            print(f"❌ Error handling incoming message: {e}")
            # Try to send error message to user
            try:
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text="Sorry, I encountered an error. Please try again. 🏏"
                )
            except:
                pass
    
    @classmethod
    def get_coach_by_phone(cls, phone_number):
        """Find a coach by their phone number"""
        try:
            # Format phone number for comparison
            formatted_phone = phone_number.replace('+', '').replace(' ', '').replace('-', '')
            
            coaches = FirebaseService.get_all_coaches()
            for coach in coaches:
                coach_phone = coach.get('phone_number', '').replace('+', '').replace(' ', '').replace('-', '')
                if coach_phone == formatted_phone:
                    return coach
            return None
        except Exception as e:
            print(f"Error finding coach: {e}")
            return None
    
    @classmethod
    def get_help_message(cls, coach_name=None):
        """Generate help message"""
        greeting = f"Hi Coach {coach_name}! 👋\n\n" if coach_name else "Hi Coach! 👋\n\n"
        
        return greeting + """I'm your Cricket Coaching Assistant! 🏏

I can help you with:
• Batting techniques & drills
• Bowling tips & variations
• Fielding exercises
• Match tactics & strategy
• Player development
• Fitness training
• Mental preparation

Just ask me anything about cricket coaching!

Commands:
/help - Show this message
/reset - Start fresh conversation

I speak all 11 SA languages - just message me in your preferred language!"""
