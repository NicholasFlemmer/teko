# WhatsApp Webhook Setup Guide

This guide explains how to configure WhatsApp webhooks to receive message status updates and incoming messages.

## What is a Webhook?

A webhook is an HTTP callback that allows WhatsApp to notify your backend when:
- Messages are sent, delivered, read, or failed
- You receive incoming messages from users
- Other events occur in your WhatsApp Business account

## Prerequisites

✅ Backend running with webhook endpoint at `/api/webhooks/whatsapp`  
✅ WhatsApp Phone Number ID: `987664324422415`  
✅ WhatsApp Business Account ID: `1380229433818866`  
✅ Webhook verify token: `teko-webhook-verify-token-2024`

## Setup Steps

### Step 1: Expose Your Local Backend (Development Only)

For local development, you need to expose your backend to the internet so Meta can reach it.

#### Option A: Using ngrok (Recommended)

```bash
# Install ngrok if you haven't
brew install ngrok

# Start ngrok tunnel
ngrok http 5001
```

You'll get a public URL like: `https://abc123.ngrok.io`

#### Option B: Using Cloudflare Tunnel

```bash
# Install cloudflared
brew install cloudflared

# Start tunnel
cloudflared tunnel --url http://localhost:5001
```

**Important**: Keep this terminal open while testing webhooks!

### Step 2: Configure Webhook in Meta Developer Dashboard

1. **Go to Meta for Developers**
   - Visit: https://developers.facebook.com/apps
   - Select your app

2. **Navigate to WhatsApp → Configuration**
   - In left menu: WhatsApp → Configuration
   - Scroll to "Webhook" section

3. **Click "Edit"** or "Configure Webhooks"

4. **Enter Webhook Details**:
   - **Callback URL**: `https://your-ngrok-url.ngrok.io/api/webhooks/whatsapp`
     - Example: `https://abc123.ngrok.io/api/webhooks/whatsapp`
   - **Verify Token**: `teko-webhook-verify-token-2024`
     - This must match `WHATSAPP_VERIFY_TOKEN` in your `.env`

5. **Click "Verify and Save"**
   - Meta will send a GET request to verify your endpoint
   - Your backend will respond with the challenge
   - You should see "✅ WhatsApp webhook verified!" in your backend logs

6. **Subscribe to Webhook Fields**
   - After verification, check these boxes:
     - ✅ `messages` (to receive message status updates)
     - ✅ `message_status` (for delivery and read receipts)
   - Click "Save"

### Step 3: Test the Webhook

#### Send a Test Message

```bash
curl -X POST "https://graph.facebook.com/v18.0/987664324422415/messages" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "messaging_product": "whatsapp",
    "to": "YOUR_PHONE_NUMBER",
    "type": "text",
    "text": {
      "body": "Hello from Teko! This is a test message."
    }
  }'
```

#### Check Your Backend Logs

You should see webhook events in your backend terminal:
```
📥 Received WhatsApp webhook: {...}
📊 Message wamid.xxx status: sent
📊 Message wamid.xxx status: delivered
📊 Message wamid.xxx status: read
```

### Step 4: Production Setup (Cloud Run)

Once you deploy to Cloud Run, update the webhook:

1. **Get Cloud Run URL**
   ```bash
   gcloud run services describe teko-backend --region=us-central1 --format="value(status.url)"
   ```
   Example: `https://teko-backend-xxx.run.app`

2. **Update Webhook in Meta Dashboard**
   - Go back to WhatsApp → Configuration
   - Click "Edit" webhook
   - Change Callback URL to: `https://your-cloud-run-url.run.app/api/webhooks/whatsapp`
   - Keep same Verify Token: `teko-webhook-verify-token-2024`
   - Click "Verify and Save"

## Webhook Event Types

Your backend currently handles these webhook events:

### Message Status Updates

```json
{
  "object": "whatsapp_business_account",
  "entry": [{
    "changes": [{
      "field": "messages",
      "value": {
        "statuses": [{
          "id": "wamid.xxx",
          "status": "delivered",
          "timestamp": "1234567890",
          "recipient_id": "27821234567"
        }]
      }
    }]
  }]
}
```

Status types:
- `sent` - Message sent to WhatsApp servers
- `delivered` - Message delivered to recipient's phone
- `read` - Message read by recipient
- `failed` - Message delivery failed

### Incoming Messages (Future Feature)

```json
{
  "object": "whatsapp_business_account",
  "entry": [{
    "changes": [{
      "field": "messages",
      "value": {
        "messages": [{
          "from": "27821234567",
          "id": "wamid.xxx",
          "type": "text",
          "text": {
            "body": "Hello"
          }
        }]
      }
    }]
  }]
}
```

## Troubleshooting

### Webhook Verification Failed

**Problem**: "❌ WhatsApp webhook verification failed" in logs

**Solutions**:
1. Check verify token matches exactly: `teko-webhook-verify-token-2024`
2. Ensure backend is running and accessible via public URL
3. Check ngrok/cloudflare tunnel is active
4. Verify URL format: `https://your-url/api/webhooks/whatsapp` (no trailing slash)

### No Webhook Events Received

**Problem**: Messages send successfully but no webhook events

**Solutions**:
1. Check webhook subscriptions are enabled (messages, message_status)
2. Verify ngrok/cloudflare tunnel is still running
3. Check backend logs for any errors
4. Ensure WHATSAPP_VERIFY_TOKEN in .env matches Meta configuration

### Webhook Times Out

**Problem**: Meta says webhook verification timed out

**Solutions**:
1. Ensure backend is responding quickly (< 5 seconds)
2. Check no firewall blocking incoming requests
3. Verify public URL is correct and accessible
4. Try a different tunnel service (ngrok vs cloudflare)

## Security Considerations

### Production Best Practices

1. **Validate Webhook Signatures** (not yet implemented)
   ```python
   # Future enhancement: verify signature from Meta
   signature = request.headers.get('X-Hub-Signature-256')
   # Verify signature matches payload
   ```

2. **Use HTTPS Only**
   - Cloud Run automatically uses HTTPS
   - Local dev uses ngrok/cloudflare HTTPS tunnels

3. **Rate Limiting**
   - Consider adding rate limiting to webhook endpoint
   - Prevent abuse from malicious actors

4. **Logging and Monitoring**
   - Log all webhook events for debugging
   - Monitor for unusual patterns or failures

## Environment Variables Summary

```bash
# WhatsApp Configuration
WHATSAPP_API_URL=https://graph.facebook.com/v18.0
WHATSAPP_API_KEY=your-access-token-here
WHATSAPP_PHONE_NUMBER_ID=987664324422415
WHATSAPP_VERIFY_TOKEN=teko-webhook-verify-token-2024
```

## Testing Checklist

- [ ] Backend running on localhost:5001
- [ ] Ngrok/Cloudflare tunnel active and public URL obtained
- [ ] Webhook configured in Meta Developer Dashboard
- [ ] Webhook verification successful (✅ in logs)
- [ ] Subscriptions enabled (messages, message_status)
- [ ] Test message sent
- [ ] Webhook events received in backend logs (📥, 📊)

## Resources

- [WhatsApp Business API Webhooks](https://developers.facebook.com/docs/whatsapp/webhooks)
- [Meta Webhooks Guide](https://developers.facebook.com/docs/graph-api/webhooks)
- [ngrok Documentation](https://ngrok.com/docs)
- [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/)

## Support

If you encounter issues:
1. Check backend terminal logs for errors
2. Verify all environment variables are set correctly
3. Test webhook endpoint directly: `curl https://your-url/api/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=teko-webhook-verify-token-2024&hub.challenge=test`
4. Review Meta Developer Dashboard for error messages
