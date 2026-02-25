# Teko Backend - Quick Start Guide

Get your backend running in 5 minutes using Application Default Credentials (ADC).

## 🚀 Quick Setup

### 1. Install Prerequisites

```bash
# Check if gcloud is installed
gcloud --version

# If not installed, get it from: https://cloud.google.com/sdk/docs/install
```

### 2. Authenticate with Google Cloud

```bash
# Login with your Google account (opens browser)
gcloud auth application-default login

# Set your Firebase project
gcloud config set project teko-236ad
```

### 3. Set Up Backend

```bash
# Navigate to backend
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
```

### 4. Configure .env File

Edit `backend/.env` with your API keys:

```bash
SECRET_KEY=your-random-secret-key-here
FLASK_ENV=development

FIREBASE_PROJECT_ID=teko-236ad
# Leave FIREBASE_CREDENTIALS_PATH unset to use ADC

WHATSAPP_API_KEY=your-whatsapp-api-key
WHATSAPP_PHONE_NUMBER_ID=your-phone-number-id
GEMINI_API_KEY=your-gemini-api-key

FRONTEND_URL=http://localhost:3000
```

### 5. Run the Backend

```bash
python app.py
```

Expected output:
```
🔐 Using Application Default Credentials (ADC)
✅ Firebase Admin SDK initialized successfully
✅ Firestore client connected successfully
 * Running on http://0.0.0.0:5001
```

### 6. Test the Backend

```bash
# Health check
curl http://localhost:5001/health

# Should return: {"status":"healthy"}
```

## ✅ You're Ready!

Your backend is now running with secure Firebase authentication.

## 📚 Next Steps

1. **Set up Frontend**: Follow instructions in `frontend/README.md`
2. **Deploy to Cloud Run**: See `DEPLOYMENT.md` for production deployment
3. **Configure WhatsApp**: Set up WhatsApp Business API credentials
4. **Get Gemini API Key**: Visit Google AI Studio

## 🔧 Troubleshooting

### "Could not determine credentials"
Run: `gcloud auth application-default login`

### "Permission denied" 
Verify your account has Owner/Editor role in Firebase Console

### "Project not found"
Check your project ID: `gcloud projects list`

## 📖 Full Documentation

- **Firebase Setup**: See `FIREBASE_SETUP.md` for detailed ADC guide
- **Deployment**: See `DEPLOYMENT.md` for Cloud Run deployment
- **API Reference**: See `README.md` for full API documentation

## 🆘 Need Help?

1. Check `FIREBASE_SETUP.md` for detailed troubleshooting
2. Review logs in the terminal
3. Verify all prerequisites are installed
