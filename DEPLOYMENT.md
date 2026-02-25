# Teko Deployment Guide

This guide covers deploying Teko to Google Cloud Platform (Google Cloud Run for backend, Firebase Hosting for frontend).

## Prerequisites

1. **Google Cloud Project**: Create a project in Google Cloud Console
2. **Firebase Project**: Set up a Firebase project (can be the same as GCP project)
3. **APIs**: Enable required APIs in Google Cloud Console:
   - Cloud Run API
   - Cloud Scheduler API
   - Pub/Sub API
   - Firebase Admin SDK

4. **CLI Tools**:
   ```bash
   # Install gcloud CLI
   # Follow: https://cloud.google.com/sdk/docs/install

   # Install Firebase CLI
   npm install -g firebase-tools

   # Login to both
   gcloud auth login
   firebase login
   ```

## Step 1: Firebase Setup

### 1.1 Create Firebase Project

1. Go to [Firebase Console](https://console.firebase.google.com/)
2. Create a new project or select existing
3. Enable Firestore Database in production mode
4. Create service account credentials:
   - Go to Project Settings > Service Accounts
   - Click "Generate new private key"
   - Save as `backend/firebase-credentials.json`

### 1.2 Configure Firestore Security Rules

In Firebase Console > Firestore > Rules:

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // Allow read/write access only to authenticated users
    match /{document=**} {
      allow read, write: if false;  // Backend only access
    }
  }
}
```

## Step 2: Environment Configuration

### 2.1 Backend Environment Variables

Create `backend/.env`:

```bash
SECRET_KEY=your-random-secret-key-here
FLASK_ENV=production

FIREBASE_PROJECT_ID=your-firebase-project-id
FIREBASE_CREDENTIALS_PATH=firebase-credentials.json

WHATSAPP_API_URL=https://graph.facebook.com/v18.0
WHATSAPP_API_KEY=your-whatsapp-business-api-key
WHATSAPP_PHONE_NUMBER_ID=your-phone-number-id

GEMINI_API_KEY=your-gemini-api-key

FRONTEND_URL=https://your-domain.web.app

CHECK_IN_TOKEN_EXPIRY_MINUTES=30
GEOLOCATION_RADIUS_METERS=100
REMINDER_MINUTES_BEFORE=10

JWT_EXPIRY_HOURS=24
```

### 2.2 Frontend Environment Variables

Create `frontend/.env.production`:

```bash
REACT_APP_API_URL=https://your-cloud-run-url
```

## Step 3: Deploy Backend to Cloud Run

### 3.1 Configure Cloud Run

```bash
cd backend

# Set your GCP project
gcloud config set project YOUR_PROJECT_ID

# Deploy to Cloud Run
gcloud run deploy teko-backend \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars SECRET_KEY="your-secret-key" \
  --set-env-vars FIREBASE_PROJECT_ID="your-project-id" \
  --set-env-vars WHATSAPP_API_KEY="your-key" \
  --set-env-vars WHATSAPP_PHONE_NUMBER_ID="your-id" \
  --set-env-vars GEMINI_API_KEY="your-key" \
  --set-env-vars FRONTEND_URL="your-frontend-url"
```

Note the service URL provided after deployment.

### 3.2 Set Up Cloud Scheduler for Reminders

#### Create Pub/Sub Topic

```bash
gcloud pubsub topics create teko-reminders
```

#### Create Cloud Scheduler Jobs

**Reminder Job** (runs every minute to check for sessions needing reminders):

```bash
gcloud scheduler jobs create http teko-send-reminders \
  --location=us-central1 \
  --schedule="* * * * *" \
  --uri="https://your-cloud-run-url/api/scheduler/run-reminders" \
  --http-method=POST \
  --oidc-service-account-email="your-service-account@your-project.iam.gserviceaccount.com"
```

**Mark Missed Sessions Job** (runs every hour):

```bash
gcloud scheduler jobs create http teko-mark-missed \
  --location=us-central1 \
  --schedule="0 * * * *" \
  --uri="https://your-cloud-run-url/api/scheduler/mark-missed" \
  --http-method=POST \
  --oidc-service-account-email="your-service-account@your-project.iam.gserviceaccount.com"
```

## Step 4: Deploy Frontend to Firebase Hosting

### 4.1 Initialize Firebase

```bash
cd frontend

# Initialize Firebase (if not already done)
firebase init hosting

# Select your Firebase project
# Choose 'build' as your public directory
# Configure as single-page app: Yes
# Set up automatic builds with GitHub: No (for now)
```

### 4.2 Build and Deploy

```bash
# Build the production app
npm run build

# Deploy to Firebase Hosting
firebase deploy --only hosting
```

Note the hosting URL provided.

### 4.3 Update Backend CORS Settings

Update `FRONTEND_URL` in Cloud Run environment variables to your Firebase Hosting URL:

```bash
gcloud run services update teko-backend \
  --region=us-central1 \
  --set-env-vars FRONTEND_URL="https://your-app.web.app"
```

## Step 5: WhatsApp Business API Setup

1. **Facebook Business Manager**: Create account at business.facebook.com
2. **WhatsApp Business API**: Request access in Business Manager
3. **Phone Number**: Register a phone number for WhatsApp
4. **API Credentials**: Get your API key and Phone Number ID from Business Manager
5. **Test**: Send a test message to verify configuration

## Step 6: Gemini API Setup

1. Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Create an API key
3. Add to your backend environment variables

## Step 7: Testing

### 7.1 Test Backend

```bash
# Health check
curl https://your-cloud-run-url/health

# Test login (should work with admin/admin123)
curl -X POST https://your-cloud-run-url/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}'
```

### 7.2 Test Frontend

1. Open your Firebase Hosting URL
2. Login with admin/admin123
3. Create a test coach
4. Create a test session
5. Send a manual reminder

## Step 8: Monitoring and Logs

### View Backend Logs

```bash
# View logs in real-time
gcloud run services logs tail teko-backend --region=us-central1

# View logs in Cloud Console
# Navigate to Cloud Run > teko-backend > Logs
```

### View Scheduler Logs

```bash
# View Cloud Scheduler job logs
gcloud logging read "resource.type=cloud_scheduler_job" --limit 50
```

## Step 9: Security Hardening (Production)

1. **Change Default Password**: Update admin credentials in `backend/routes/auth.py`
2. **Enable Authentication**: Consider adding proper user management
3. **API Security**: Add rate limiting to prevent abuse
4. **Firestore Rules**: Ensure proper security rules
5. **HTTPS Only**: Ensure all traffic uses HTTPS
6. **Secret Management**: Use Google Secret Manager instead of environment variables

```bash
# Example: Store secrets in Secret Manager
echo -n "your-secret-key" | \
  gcloud secrets create teko-secret-key --data-file=-

# Update Cloud Run to use secrets
gcloud run services update teko-backend \
  --update-secrets=SECRET_KEY=teko-secret-key:latest
```

## Step 10: Custom Domain (Optional)

### For Frontend

```bash
# In Firebase Console
# Hosting > Add Custom Domain
# Follow the instructions to verify and configure DNS
```

### For Backend

```bash
# Map custom domain to Cloud Run
gcloud run domain-mappings create --service teko-backend --domain api.yourdomain.com
```

## Troubleshooting

### Backend not starting
- Check Cloud Run logs
- Verify all environment variables are set
- Check Firebase credentials are correct

### Scheduler not working
- Verify Cloud Scheduler jobs are created
- Check service account has proper permissions
- View Cloud Scheduler logs

### WhatsApp messages not sending
- Verify WhatsApp API credentials
- Check phone number is registered
- View backend logs for errors

### Frontend can't connect to backend
- Verify CORS settings
- Check REACT_APP_API_URL is correct
- Ensure Cloud Run service is publicly accessible

## Maintenance

### Update Backend

```bash
cd backend
gcloud run deploy teko-backend --source .
```

### Update Frontend

```bash
cd frontend
npm run build
firebase deploy --only hosting
```

### View Costs

Monitor costs in Google Cloud Console > Billing

## Support

For issues or questions:
1. Check logs first
2. Review this deployment guide
3. Check Firebase and Cloud Run documentation
