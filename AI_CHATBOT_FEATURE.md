# Cricket Coaching AI Chatbot - WhatsApp Integration

Your Teko system now includes an AI-powered cricket coaching chatbot that coaches can access via WhatsApp!

## 🏏 Features

### Cricket Coaching Specialist
- Expert advice on batting, bowling, fielding
- Training drills and practice sessions
- Match strategy and tactics
- Player development guidance
- Fitness and conditioning tips
- Mental preparation advice
- Youth cricket specialization (U10-U19)
- South African cricket context

### Multilingual Support
Responds in all 11 official South African languages:
- Afrikaans, English
- isiNdebele, isiXhosa, isiZulu
- Sepedi, Sesotho, Setswana
- siSwati, Tshivenda, Xitsonga

### Conversation Features
- Maintains conversation context (last 5 messages)
- Remembers previous questions
- Personalized responses using coach's name
- Command system for help and reset

## How It Works

### For Coaches

1. **Send a WhatsApp message** to your WhatsApp Business number
2. **Ask anything about cricket coaching**
3. **Receive AI-powered advice** within seconds
4. **Continue the conversation** - AI remembers context

### Message Flow

```
Coach → WhatsApp → Webhook → AI Processing → Response → WhatsApp → Coach
```

### Example Conversations

**Example 1: Batting Technique**
```
Coach: "How can I help my young batters improve their straight drive?"

AI: "Great question! Here's how to teach the straight drive:

1. Stance & Grip:
   - Balanced stance, weight on balls of feet
   - V-grip with hands together
   - Relaxed shoulders

2. Key Steps:
   - Watch the ball onto bat
   - Small front foot stride
   - High elbow on downswing
   - Follow through towards target

3. Drill: The Corridor
   - Place cones creating a corridor
   - Bowler feeds on middle stump
   - Batter hits straight through corridor
   - Start slow, build to game pace

Start with 10 reps, then match simulation. Focus on timing over power! 🏏"
```

**Example 2: Bowling (in Afrikaans)**
```
Coach: "Hoe kan ek my spelers help om hulle yorkers te verbeter?"

AI: "Goeie vraag! Hier is wenke vir yorker ontwikkeling:

1. Tegniek:
   - Mikpunt: Basis van paal
   - Vrystelling: Later, laer
   - Pols: Skerp afwaarts
   
2. Oefeninge:
   - Teiken oefening met kegels
   - Stadige tempo eers
   - Geleidelik versnel

3. Wedstryd konteks:
   - Dood overs
   - Toe baan
   - Verrassingswapen

Oefen 30 yorkers per sessie. Akkuraatheid voor spoed! 🏏"
```

**Example 3: Match Strategy**
```
Coach: "What field should I set for a leg-spinner in T20?"

AI: "For leg-spin in T20, here's an attacking field:

Inside the Circle (5):
- Mid-off
- Cover
- Mid-wicket
- Square leg  
- Short third man

Boundary (4):
- Long-off
- Long-on
- Deep mid-wicket
- Deep square leg

Variations:
- Googly: Bring cover finer
- Top-spinner: Push mid-wicket deeper
- Against lefty: Mirror the field

Key: Keep attacking with fielders saving singles. Force big shots! 🏏"
```

## Commands

Coaches can use these commands:

- `/help` or `help` - Show help message
- `/start` - Same as /help
- `/reset` or `reset` - Start fresh conversation

## Technical Implementation

### Backend Components

**1. ConversationService** (`services/conversation_service.py`)
- Processes incoming messages
- Manages conversation history
- Generates AI responses
- Handles commands

**2. Webhook Handler** (`app.py`)
- Receives WhatsApp messages
- Routes to ConversationService
- Sends responses back

**3. Firestore Structure**
```
conversations/
  └─ {phone_number}/
      └─ messages/
          ├─ {message_id_1}
          │   ├─ role: "user"
          │   ├─ content: "How to improve batting?"
          │   ├─ timestamp: 2025-11-03T14:30:00Z
          │   └─ message_id: "uuid"
          └─ {message_id_2}
              ├─ role: "assistant"
              ├─ content: "Here are batting tips..."
              ├─ timestamp: 2025-11-03T14:30:05Z
              └─ message_id: "uuid"
```

## Testing the Chatbot

### Option 1: Real WhatsApp Test

**Prerequisites:**
- Webhook must be configured in Meta Developer Dashboard
- Use ngrok/cloudflare to expose localhost to internet

**Steps:**
1. Send WhatsApp message to your business number
2. Watch backend logs for processing
3. Receive AI response

### Option 2: Simulate Webhook (Local Testing)

```bash
curl -X POST http://localhost:5001/api/webhooks/whatsapp \
  -H "Content-Type: application/json" \
  -d '{
    "object": "whatsapp_business_account",
    "entry": [{
      "changes": [{
        "field": "messages",
        "value": {
          "messages": [{
            "from": "27795169916",
            "id": "test123",
            "type": "text",
            "text": {
              "body": "How can I improve my players batting technique?"
            }
          }]
        }
      }]
    }]
  }'
```

This will:
1. Process the message
2. Generate AI response
3. Send WhatsApp to that number (must be registered coach)

### Option 3: Test via Webhook in Production

Once deployed to Cloud Run, configure webhook in Meta:
1. Callback URL: `https://your-cloud-run-url/api/webhooks/whatsapp`
2. Send real WhatsApp messages
3. Receive AI responses

## Monitoring Conversations

### View Conversation History

You can query conversation history in Firestore:
1. Go to Firebase Console → Firestore
2. Navigate to `conversations` collection
3. See all coach conversations
4. View message exchanges

### Backend Logs

Watch the backend terminal for:
```
📨 Processing message from 27795169916: How can I improve...
✅ Identified coach: Nic
🤖 Generating AI response...
💾 Saved user message to conversation history
💾 Saved assistant message to conversation history
📤 Sending WhatsApp message to: 27795169916
✅ WhatsApp API Response: {...}
✅ Response sent successfully to Nic
```

## Features

✅ **Intelligent Responses** - Cricket coaching expertise  
✅ **Context Aware** - Remembers last 5 messages  
✅ **Multilingual** - All 11 SA languages  
✅ **Personalized** - Uses coach's name  
✅ **Command System** - /help, /reset  
✅ **History Tracking** - All conversations stored  
✅ **Error Handling** - Graceful fallbacks  
✅ **Security** - Only registered coaches  

## Conversation Limits

- **History**: Last 5 messages kept in context
- **Storage**: All messages stored indefinitely in Firestore
- **Rate Limit**: None currently (can add if needed)
- **Message Length**: Responses under 1000 characters

## Security

- Only registered coaches (in Firestore) can use the chatbot
- Unregistered numbers receive a "please register" message
- All conversations logged for monitoring
- No sensitive data shared

## Cost Estimation

**Gemini API Costs** (very affordable):
- ~$0.001 per message exchange
- 1000 conversations = ~$1
- Well within free tier for moderate usage

## South African Languages Examples

**English**: "How can I improve bowling accuracy?"

**Afrikaans**: "Hoe kan ek my rollery se akkuraatheid verbeter?"

**isiZulu**: "Ngingasiza kanjani abadlali bami ukuthuthukisa ukuphonsa?"

**Sesotho**: "Nka thusa jwang bakwi baka ho ntlafatsa bokgoni ba bona?"

The AI will detect the language and respond accordingly!

## Troubleshooting

### No Response Received

1. Check backend logs for errors
2. Verify webhook is configured in Meta
3. Ensure coach is registered in system
4. Check WhatsApp API token is valid

### Wrong Language Response

The AI should auto-detect language. If it responds in wrong language:
- Try being more explicit: "Respond in Afrikaans please"
- The AI will adapt

### Rate Limiting

If you get too many messages:
- Add rate limiting in `conversation_service.py`
- Set max messages per coach per day
- Example: 50 messages/day limit

## Future Enhancements

Potential additions:
- Voice message transcription
- Image analysis (technique review from photos/videos)
- Daily cricket tips broadcast
- Coaching resource library
- Team management features
- Performance analytics integration

## Admin Monitoring

View coach conversations:
1. Firebase Console → Firestore → conversations
2. See message history by phone number
3. Monitor AI quality and coach satisfaction
4. Identify common questions for FAQ

## Support

If coaches have issues:
1. They can send `/help` for instructions
2. Admin can view conversation in Firestore
3. Backend logs show all processing steps
4. Can manually test with curl commands

---

**The AI Cricket Coaching Assistant is now live!** 🏏🤖

Coaches can start chatting immediately by sending a WhatsApp message.
