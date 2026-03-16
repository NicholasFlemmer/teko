import os
import atexit
import hmac
import hashlib
import collections as _collections
import logging
from flask import Flask, jsonify
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from config import Config

logger = logging.getLogger(__name__)
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
from routes.sse import sse_bp
from services.firebase_service import FirebaseService
from services.scheduler_service import SchedulerService

app = Flask(__name__)
app.config.from_object(Config)
Config.validate()

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
app.register_blueprint(sse_bp, url_prefix='/api/sse')

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
    logger.info("Automated reminder scheduler started (every 1 min)")

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

def _check_scheduler_auth():
    """Validate scheduler endpoint auth via JWT token or SCHEDULER_SECRET header."""
    from flask import request
    import jwt
    # Accept JWT auth (admin dashboard triggering manually)
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        try:
            jwt.decode(auth_header.split(' ')[1], Config.SECRET_KEY, algorithms=["HS256"])
            return True
        except Exception:
            pass
    # Accept shared secret (Cloud Scheduler) — constant-time comparison
    secret = os.environ.get('SCHEDULER_SECRET')
    if secret and hmac.compare_digest(request.headers.get('X-Scheduler-Secret', ''), secret):
        return True
    return False


@app.route('/api/scheduler/run-reminders', methods=['POST'])
def run_reminders():
    """Endpoint to trigger reminder checks (called by Cloud Scheduler or admin)."""
    if not _check_scheduler_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        result = SchedulerService.check_and_send_reminders()
        return jsonify(result), 200
    except Exception as e:
        logger.exception("Error in run_reminders")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@app.route('/api/scheduler/mark-missed', methods=['POST'])
def mark_missed():
    """Endpoint to mark missed sessions (called by Cloud Scheduler or admin)."""
    if not _check_scheduler_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        result = SchedulerService.mark_missed_sessions()
        return jsonify(result), 200
    except Exception as e:
        logger.exception("Error in mark_missed")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500


# WhatsApp webhook signature verification

def _verify_webhook_signature(request):
    """Verify the X-Hub-Signature-256 header from WhatsApp webhook.

    Returns True if signature is valid or if WHATSAPP_APP_SECRET is not configured
    (to avoid breaking existing deployments that haven't set the secret yet).
    """
    app_secret = Config.WHATSAPP_APP_SECRET
    if not app_secret:
        # Not configured — skip verification (log warning in production)
        if not Config.DEBUG:
            logger.warning("WHATSAPP_APP_SECRET not set — webhook signature verification skipped")
        return True

    signature_header = request.headers.get('X-Hub-Signature-256', '')
    if not signature_header.startswith('sha256='):
        logger.warning("Missing or malformed X-Hub-Signature-256 header")
        return False

    expected_sig = signature_header[7:]  # strip 'sha256='
    body = request.get_data()
    computed_sig = hmac.new(
        app_secret.encode('utf-8'),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(computed_sig, expected_sig):
        logger.warning("Webhook signature mismatch — request rejected")
        return False

    return True


# Simple in-memory dedup for WhatsApp webhook messages (LRU-style)
_processed_message_ids = _collections.OrderedDict()
_DEDUP_MAX = 500

def _is_duplicate_message(message_id):
    """Return True if we've already processed this message_id (within last 500 messages)."""
    if not message_id:
        return False
    if message_id in _processed_message_ids:
        return True
    _processed_message_ids[message_id] = True
    if len(_processed_message_ids) > _DEDUP_MAX:
        _processed_message_ids.popitem(last=False)
    return False


@app.route('/api/whatsapp-cloud-webhook', methods=['GET', 'POST'])
def whatsapp_webhook():
    """WhatsApp webhook endpoint for receiving messages and status updates"""
    from flask import request

    if request.method == 'GET':
        # Webhook verification
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')

        if mode == 'subscribe' and Config.WHATSAPP_VERIFY_TOKEN and hmac.compare_digest(token or '', Config.WHATSAPP_VERIFY_TOKEN):
            logger.info("WhatsApp webhook verified")
            return challenge, 200
        else:
            logger.warning("WhatsApp webhook verification failed")
            return 'Forbidden', 403

    elif request.method == 'POST':
        # Verify webhook signature before processing
        if not _verify_webhook_signature(request):
            return jsonify({'status': 'ok'}), 200  # Still 200 to prevent retries

        # IMPORTANT: Always return 200 to prevent WhatsApp retry storms.
        # Errors are logged but must not cause a non-200 response.
        try:
            data = request.get_json(force=True, silent=True)
            if not data:
                return jsonify({'status': 'ok'}), 200

            # Process webhook data
            if data.get('object') == 'whatsapp_business_account':
                for entry in data.get('entry', []):
                    for change in entry.get('changes', []):
                        if change.get('field') == 'messages':
                            value = change.get('value', {})

                            # Handle message statuses (sent, delivered, read, failed)
                            if 'statuses' in value:
                                for status in value['statuses']:
                                    logger.debug("Message %s status: %s", status.get('id'), status.get('status'))

                            # Handle incoming messages
                            if 'messages' in value:
                                from services.conversation_service import ConversationService
                                from services.whatsapp_service import WhatsAppService
                                for message in value['messages']:
                                    from_number = message.get('from')
                                    message_id = message.get('id')
                                    message_type = message.get('type')

                                    # Dedup: WhatsApp may deliver the same webhook multiple times
                                    if _is_duplicate_message(message_id):
                                        logger.debug("Skipping duplicate message %s", message_id)
                                        continue

                                    logger.info("Received %s message from %s", message_type, from_number)

                                    # Immediately mark as read (blue ticks) and show typing
                                    # Best-effort: failures must not block message processing
                                    try:
                                        WhatsAppService.mark_as_read(message_id)
                                    except Exception as e:
                                        logger.debug("mark_as_read failed: %s", e)

                                    try:
                                        WhatsAppService.send_typing_indicator(message_id)
                                    except Exception as e:
                                        logger.debug("typing indicator failed: %s", e)

                                    try:
                                        # Handle text messages with AI
                                        if message_type == 'text':
                                            message_text = message.get('text', {}).get('body', '')
                                            if message_text:
                                                ConversationService.handle_incoming_message(
                                                    from_number=from_number,
                                                    message_text=message_text,
                                                    message_id=message_id
                                                )
                                        elif message_type == 'image':
                                            image_data = message.get('image', {})
                                            ConversationService.handle_image_message(
                                                from_number=from_number,
                                                image_info=image_data,
                                                message_id=message_id
                                            )
                                        elif message_type == 'location':
                                            location_data = message.get('location', {})
                                            lat = location_data.get('latitude')
                                            lng = location_data.get('longitude')
                                            if lat is not None and lng is not None:
                                                ConversationService.handle_location_check_in(
                                                    from_number=from_number,
                                                    latitude=lat,
                                                    longitude=lng,
                                                    message_id=message_id
                                                )
                                            else:
                                                logger.warning("Location message missing coordinates")
                                        else:
                                            logger.debug("Skipping %s message (not supported)", message_type)
                                    except Exception as e:
                                        logger.exception("Error processing %s message from %s", message_type, from_number)

            return jsonify({'status': 'ok'}), 200
        except Exception as e:
            logger.exception("Error processing webhook")
            # Still return 200 to prevent retry storms
            return jsonify({'status': 'ok'}), 200

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
        debug=Config.DEBUG
    )
