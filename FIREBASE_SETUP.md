# Firebase Setup Guide - Application Default Credentials (ADC)

This guide explains how to set up Firebase authentication using Application Default Credentials (ADC), which is the recommended and more secure approach compared to service account keys.

## Why Use Application Default Credentials?

✅ **More Secure** - No JSON credential files to manage or accidentally commit to version control  
✅ **Organization Policy Compliant** - Works with policies that block service account key creation  
✅ **Simpler** - No need to download, store, or rotate credential files  
✅ **Works Everywhere** - Supports local development, Cloud Run, Cloud Functions, and more  
✅ **Google Recommended** - Official best practice from Google Cloud  

## Prerequisites

1. **Google Cloud SDK (gcloud)** - Must be installed on your machine
   ```bash
   # Check if installed
   gcloud --version
   
   # If not installed, follow: https://cloud.google.com/sdk/docs/install
   ```

2. **Firebase Project** - You must have a Firebase project created at console.firebase.google.com

3. **Proper Permissions** - Your Google account must have:
   - Owner or Editor role on the Firebase project
   - Firebase Admin SDK permissions

## Setup for Local Development

### Step 1: Authenticate with Google Cloud

```bash
# Login with your Google account (opens browser)
gcloud auth application-default login
```

This command will:
- Open your web browser
- Ask you to sign in with your Google account
- Grant permissions to access Google Cloud resources
- Store credentials locally at: `~/.config/gcloud/application_default_credentials.json`

### Step 2: Set Your Project

```bash
# Replace with your actual Firebase project ID
gcloud config set project teko-236ad
```

You can find your project ID in:
- Firebase Console → Project Settings → General
- Or in the Google Cloud Console URL

### Step 3: Verify Authentication

```bash
# Test authentication
gcloud auth application-default print-access-token
```

If this prints a token, you're authenticated correctly!

### Step 4: Configure Environment Variables

Create or update `backend/.env`:

```bash
# Flask Configuration
SECRET_KEY=your-random-secret-key
FLASK_ENV=development

# Firebase Configuration
FIREBASE_PROJECT_ID=teko-236ad

# DO NOT set FIREBASE_CREDENTIALS_PATH - ADC will be used automatically

# WhatsApp Business API Configuration
WHATSAPP_API_URL=https://graph.facebook.com/v18.0
WHATSAPP_API_KEY=your-whatsapp-api-key
WHATSAPP_PHONE_NUMBER_ID=your-phone-number-id

# Google Gemini API Configuration
GEMINI_API_KEY=your-gemini-api-key

# Frontend URL
FRONTEND_URL=http://localhost:3000

# Other settings...
CHECK_IN_TOKEN_EXPIRY_MINUTES=30
GEOLOCATION_RADIUS_METERS=100
REMINDER_MINUTES_BEFORE=10
JWT_EXPIRY_HOURS=24
```

**Important:** Leave `FIREBASE_CREDENTIALS_PATH` unset or commented out!

### Step 5: Run the Backend

```bash
cd backend
source venv/bin/activate  # or venv\Scripts\activate on Windows
python app.py
```

You should see:
```
🔐 Using Application Default Credentials (ADC)
✅ Firebase Admin SDK initialized successfully
✅ Firestore client connected successfully
```

## Setup for Cloud Run (Production)

When deploying to Cloud Run, ADC works automatically! No additional setup needed.

### Step 1: Deploy to Cloud Run

```bash
cd backend

gcloud run deploy teko-backend \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars FIREBASE_PROJECT_ID=teko-236ad \
  --set-env-vars WHATSAPP_API_KEY=your-key \
  --set-env-vars WHATSAPP_PHONE_NUMBER_ID=your-id \
  --set-env-vars GEMINI_API_KEY=your-key \
  --set-env-vars FRONTEND_URL=https://your-frontend.web.app
```

**Note:** Do NOT set `FIREBASE_CREDENTIALS_PATH` in Cloud Run environment variables.

### Step 2: Verify Permissions

Cloud Run automatically uses a service account. Ensure it has Firebase permissions:

1. Go to Google Cloud Console → IAM & Admin → IAM
2. Find the service account: `PROJECT_ID-compute@developer.gserviceaccount.com`
3. Ensure it has one of these roles:
   - **Firebase Admin** (recommended)
   - **Editor**
   - **Owner**

If not, add the role:
```bash
gcloud projects add-iam-policy-binding teko-236ad \
  --member="serviceAccount:PROJECT_ID-compute@developer.gserviceaccount.com" \
  --role="roles/firebase.admin"
```

## Troubleshooting

### Error: "Could not automatically determine credentials"

**Solution:** Run `gcloud auth application-default login` again

### Error: "Permission denied" or "403 Forbidden"

**Solution:** Verify your Google account has proper permissions on the Firebase project:
1. Go to Firebase Console → Project Settings → Users and permissions
2. Ensure your account has Owner or Editor role
3. Try running `gcloud auth application-default login` again

### Error: "Project not found"

**Solution:** Verify your project ID is correct:
```bash
# List all your projects
gcloud projects list

# Set the correct project
gcloud config set project YOUR_PROJECT_ID
```

### Want to use a different Google account?

```bash
# Logout current account
gcloud auth application-default revoke

# Login with different account
gcloud auth application-default login
```

### Need to use a service account key file anyway?

If you absolutely must use a service account key (not recommended):

1. Create a custom service account (if org policy allows):
   ```bash
   gcloud iam service-accounts create teko-backend \
     --display-name="Teko Backend Service"
   ```

2. Grant Firebase Admin role:
   ```bash
   gcloud projects add-iam-policy-binding teko-236ad \
     --member="serviceAccount:teko-backend@teko-236ad.iam.gserviceaccount.com" \
     --role="roles/firebase.admin"
   ```

3. Try creating a key:
   ```bash
   gcloud iam service-accounts keys create backend/teko-credentials.json \
     --iam-account=teko-backend@teko-236ad.iam.gserviceaccount.com
   ```

4. Update `.env`:
   ```bash
   FIREBASE_CREDENTIALS_PATH=teko-credentials.json
   ```

## How It Works

The Firebase Admin SDK authentication priority:

1. **Check for FIREBASE_CREDENTIALS_PATH** - If set and file exists, use that
2. **Use Application Default Credentials** - If no file, use ADC (recommended)
3. **Fail** - If neither works, show error with troubleshooting steps

The code in `backend/services/firebase_service.py` handles this automatically:

```python
if cred_path and os.path.exists(cred_path):
    # Use service account key file
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)
else:
    # Use Application Default Credentials (ADC)
    firebase_admin.initialize_app()
```

## Security Best Practices

1. ✅ **Use ADC for local development** - More secure than key files
2. ✅ **Never commit credentials to git** - Already in `.gitignore`
3. ✅ **Use Cloud Run's service account** - Automatic in production
4. ✅ **Rotate credentials regularly** - Re-run `gcloud auth` periodically
5. ✅ **Use least privilege** - Only grant necessary Firebase permissions

## Additional Resources

- [Google Cloud ADC Documentation](https://cloud.google.com/docs/authentication/application-default-credentials)
- [Firebase Admin SDK Setup](https://firebase.google.com/docs/admin/setup)
- [Organization Policy Constraints](https://cloud.google.com/resource-manager/docs/organization-policy/org-policy-constraints)

## Support

If you encounter issues:
1. Check the troubleshooting section above
2. Verify all prerequisites are met
3. Review the Firebase Admin SDK logs in the backend console
4. Check Cloud Run logs: `gcloud run services logs tail teko-backend`
