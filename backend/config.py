import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Application configuration"""
    
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    FLASK_ENV = os.getenv('FLASK_ENV', 'development')
    
    # Firebase
    # Note: FIREBASE_CREDENTIALS_PATH is optional. If not provided, the app will use
    # Application Default Credentials (ADC), which is the recommended approach.
    # For local dev: Run `gcloud auth application-default login`
    # For Cloud Run: Automatically uses the service account
    FIREBASE_PROJECT_ID = os.getenv('FIREBASE_PROJECT_ID')
    FIREBASE_CREDENTIALS_PATH = os.getenv('FIREBASE_CREDENTIALS_PATH')  # Optional, leave empty to use ADC
    FIREBASE_STORAGE_BUCKET = os.getenv('FIREBASE_STORAGE_BUCKET', 'teko-236ad.firebasestorage.app')
    
    # WhatsApp Business API
    WHATSAPP_API_URL = os.getenv('WHATSAPP_API_URL', 'https://graph.facebook.com/v18.0').strip()
    WHATSAPP_TYPING_API_URL = os.getenv('WHATSAPP_TYPING_API_URL', 'https://graph.facebook.com/v21.0').strip()
    WHATSAPP_API_KEY = os.getenv('WHATSAPP_API_KEY', '').strip()
    WHATSAPP_PHONE_NUMBER_ID = os.getenv('WHATSAPP_PHONE_NUMBER_ID', '').strip()
    WHATSAPP_VERIFY_TOKEN = os.getenv('WHATSAPP_CLOUD_VERIFY_TOKEN', 'teko-webhook-verify-token-2024').strip()
    
    # Gemini AI
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

    # Google Maps
    GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')

    # WhatsApp Business Account ID (for fetching templates)
    WHATSAPP_WABA_ID = os.getenv('WHATSAPP_WABA_ID')
    
    # Frontend URL (for CORS)
    FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:8080')
    
    # Check-in settings
    CHECK_IN_TOKEN_EXPIRY_MINUTES = int(os.getenv('CHECK_IN_TOKEN_EXPIRY_MINUTES', '30'))
    GEOLOCATION_RADIUS_METERS = int(os.getenv('GEOLOCATION_RADIUS_METERS', '100'))
    REMINDER_MINUTES_BEFORE = int(os.getenv('REMINDER_MINUTES_BEFORE', '10'))

    # Reminder template (approved WhatsApp template name for session reminders)
    REMINDER_TEMPLATE_NAME = os.getenv('REMINDER_TEMPLATE_NAME', 'session_reminder')
    REMINDER_TEMPLATE_LANGUAGE = os.getenv('REMINDER_TEMPLATE_LANGUAGE', 'en_US')
    
    # JWT
    JWT_EXPIRY_HOURS = int(os.getenv('JWT_EXPIRY_HOURS', '24'))
