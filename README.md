# Teko - Coach Check-In System

A WhatsApp-based check-in application for coaches, delivered through WhatsApp with geolocation verification.

## Architecture

- **Backend**: Flask (Python) on Google Cloud Run
- **Frontend**: React web application
- **Database**: Firebase Firestore
- **Messaging**: WhatsApp Business API
- **AI**: Google Gemini API for message generation

## Features

- Admin dashboard with calendar view
- Coach management
- Session scheduling and assignment
- Automated WhatsApp reminders 10 minutes before sessions
- Geolocation-based check-in verification
- Real-time status updates

## Project Structure

```
teko/
├── backend/          # Flask API server
├── frontend/         # React admin dashboard
├── .env.example      # Environment variables template
└── README.md
```

## Setup Instructions

### Prerequisites

- Python 3.9+
- Node.js 16+
- Firebase project
- WhatsApp Business API access
- Google Gemini API key

### Backend Setup

1. Navigate to backend directory:
```bash
cd backend
```

2. Create virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. **Authenticate with Google Cloud** (for Firebase access):
```bash
# Login with your Google account
gcloud auth application-default login

# Set your Firebase project
gcloud config set project your-firebase-project-id
```

5. Copy `.env.example` to `.env` and configure:
```bash
cp .env.example .env
# Edit .env and set your API keys (WhatsApp, Gemini, etc.)
# Note: FIREBASE_CREDENTIALS_PATH is optional - ADC is used by default
```

6. Run the development server:
```bash
python app.py
```

**Note:** The backend uses Application Default Credentials (ADC) for Firebase authentication, which is more secure than service account keys. No JSON credential files are needed.

### Frontend Setup

1. Navigate to frontend directory:
```bash
cd frontend
```

2. Install dependencies:
```bash
npm install
```

3. Copy `.env.example` to `.env` and fill in your credentials

4. Start development server:
```bash
npm start
```

## Deployment

### Backend (Google Cloud Run)

```bash
cd backend
gcloud run deploy teko-backend \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated
```

### Frontend (Firebase Hosting)

```bash
cd frontend
npm run build
firebase deploy --only hosting
```

## Environment Variables

See `.env.example` files in backend and frontend directories for required environment variables.

## License

MIT
