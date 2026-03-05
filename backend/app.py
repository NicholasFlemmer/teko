import os
import atexit
from flask import Flask, jsonify
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from config import Config
from routes.auth import auth_bp
from routes.coaches import coaches_bp
from routes.sessions import sessions_bp
from routes.teams import teams_bp
from routes.players import players_bp
from routes.locations import locations_bp
from routes.broadcasts import broadcasts_bp
from routes.content import content_bp
from routes.reports import reports_bp
from routes.reminders import reminders_bp
from routes.admin import admin_bp
from routes.uploads import uploads_bp
from services.firebase_service import FirebaseService
from services.scheduler_service import SchedulerService

app = Flask(__name__)
app.config.from_object(Config)

# Configure CORS
cors_origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3002",
    "http://localhost:8080",
    "http://localhost:5173",
]
# Add configured frontend URL(s) - supports comma-separated list
if Config.FRONTEND_URL:
    for url in Config.FRONTEND_URL.split(","):
        url = url.strip().rstrip("/")
        if url and url not in cors_origins:
            cors_origins.append(url)

CORS(app, resources={
    r"/api/*": {
        "origins": cors_origins,
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

# Initialize Firebase
FirebaseService.initialize()

# Register blueprints
app.register_blueprint(auth_bp, url_prefix='/api/auth')
app.register_blueprint(coaches_bp, url_prefix='/api/coaches')
app.register_blueprint(sessions_bp, url_prefix='/api/sessions')
app.register_blueprint(teams_bp, url_prefix='/api/teams')
app.register_blueprint(players_bp, url_prefix='/api/players')
app.register_blueprint(locations_bp, url_prefix='/api/locations')
app.register_blueprint(broadcasts_bp, url_prefix='/api/broadcasts')
app.register_blueprint(content_bp, url_prefix='/api/content')
app.register_blueprint(reports_bp, url_prefix='/api/reports')
app.register_blueprint(reminders_bp, url_prefix='/api/reminders')
app.register_blueprint(admin_bp, url_prefix='/api/admin')
app.register_blueprint(uploads_bp, url_prefix='/api/uploads')

# Background scheduler for automated reminders & missed-session marking.
# Guard: only start once (avoid duplicate jobs when gunicorn preloads or reloads).
if not app.config.get('SCHEDULER_STARTED'):
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=SchedulerService.check_and_send_reminders,
        trigger='interval',
        minutes=1,
        id='check_reminders',
        replace_existing=True,
    )
    scheduler.add_job(
        func=SchedulerService.mark_missed_sessions,
        trigger='interval',
        minutes=30,
        id='mark_missed',
        replace_existing=True,
    )
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())
    app.config['SCHEDULER_STARTED'] = True
    print("Automated reminder scheduler started (every 1 min)")

@app.route('/')
def index():
    """Health check endpoint"""
    return jsonify({
        'name': 'Teko API',
        'version': '1.0.0',
        'status': 'running'
    }), 200

@app.route('/health')
def health():
    """Health check endpoint for monitoring"""
    return jsonify({'status': 'healthy'}), 200

@app.route('/api/scheduler/run-reminders', methods=['POST'])
def run_reminders():
    """Endpoint to trigger reminder checks (called by Cloud Scheduler)
    
    This endpoint should be secured in production or called only from
    Cloud Scheduler with proper authentication.
    """
    try:
        result = SchedulerService.check_and_send_reminders()
        return jsonify(result), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/scheduler/mark-missed', methods=['POST'])
def mark_missed():
    """Endpoint to mark missed sessions (called by Cloud Scheduler)"""
    try:
        result = SchedulerService.mark_missed_sessions()
        return jsonify(result), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/whatsapp-cloud-webhook', methods=['GET', 'POST'])
def whatsapp_webhook():
    """WhatsApp webhook endpoint for receiving messages and status updates"""
    from flask import request
    
    if request.method == 'GET':
        # Webhook verification
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        
        if mode == 'subscribe' and token == Config.WHATSAPP_VERIFY_TOKEN:
            print(f"✅ WhatsApp webhook verified!")
            return challenge, 200
        else:
            print(f"❌ WhatsApp webhook verification failed")
            return 'Forbidden', 403
    
    elif request.method == 'POST':
        # Handle incoming webhook events
        try:
            data = request.get_json()
            print(f"📥 Received WhatsApp webhook: {data}")
            
            # Process webhook data
            if data.get('object') == 'whatsapp_business_account':
                for entry in data.get('entry', []):
                    for change in entry.get('changes', []):
                        # Handle message status updates
                        if change.get('field') == 'messages':
                            value = change.get('value', {})
                            
                            # Handle message statuses (sent, delivered, read, failed)
                            if 'statuses' in value:
                                for status in value['statuses']:
                                    message_id = status.get('id')
                                    status_type = status.get('status')
                                    print(f"📊 Message {message_id} status: {status_type}")
                            
                            # Handle incoming messages
                            if 'messages' in value:
                                from services.conversation_service import ConversationService
                                from services.whatsapp_service import WhatsAppService
                                for message in value['messages']:
                                    from_number = message.get('from')
                                    message_id = message.get('id')
                                    message_type = message.get('type')

                                    print(f"📨 Received {message_type} message from {from_number}")

                                    # Immediately mark as read (blue ticks) and show typing
                                    # Best-effort: failures must not block message processing
                                    try:
                                        WhatsAppService.mark_as_read(message_id)
                                    except Exception as e:
                                        print(f"⚠️ mark_as_read exception: {e}")

                                    try:
                                        WhatsAppService.send_typing_indicator(message_id)
                                    except Exception as e:
                                        print(f"⚠️ typing indicator exception: {e}")

                                    # Handle text messages with AI
                                    if message_type == 'text':
                                        message_text = message.get('text', {}).get('body', '')
                                        if message_text:
                                            ConversationService.handle_incoming_message(
                                                from_number=from_number,
                                                message_text=message_text,
                                                message_id=message_id
                                            )
                                    elif message_type == 'location':
                                        location_data = message.get('location', {})
                                        ConversationService.handle_location_check_in(
                                            from_number=from_number,
                                            latitude=location_data.get('latitude'),
                                            longitude=location_data.get('longitude'),
                                            message_id=message_id
                                        )
                                    else:
                                        print(f"⏭️ Skipping {message_type} message (not supported yet)")
            
            return jsonify({'status': 'success'}), 200
        except Exception as e:
            print(f"❌ Error processing webhook: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify({
        'error': 'Not found',
        'message': 'The requested resource was not found'
    }), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    return jsonify({
        'error': 'Internal server error',
        'message': 'An unexpected error occurred'
    }), 500

if __name__ == '__main__':
    # Run the Flask development server
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5002)),
        debug=Config.FLASK_ENV == 'development'
    )
