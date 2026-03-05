from flask import Blueprint, request, jsonify
from services.firebase_service import FirebaseService
from services.whatsapp_service import WhatsAppService
from routes.auth import token_required

broadcasts_bp = Blueprint('broadcasts', __name__)

@broadcasts_bp.route('', methods=['POST'])
@token_required
def send_broadcast(current_user):
    """Send a broadcast message via whatsapp or email"""
    try:
        data = request.get_json()

        # Validate required fields
        required_fields = ['channel', 'recipient_ids']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }), 400

        # Either message or template_name is required
        if not data.get('message') and not data.get('template_name'):
            return jsonify({
                'success': False,
                'error': 'Either message or template_name is required'
            }), 400

        # Validate channel
        channel = data['channel']
        if channel not in ['whatsapp', 'email']:
            return jsonify({
                'success': False,
                'error': 'Channel must be either "whatsapp" or "email"'
            }), 400

        # Validate recipient_ids is a non-empty list
        if not isinstance(data['recipient_ids'], list) or len(data['recipient_ids']) == 0:
            return jsonify({
                'success': False,
                'error': 'recipient_ids must be a non-empty list'
            }), 400

        # Actually send messages via WhatsApp
        send_results = []
        failed_count = 0
        template_name = data.get('template_name')
        template_language = data.get('template_language', 'en_US')

        if channel == 'whatsapp':
            for coach_id in data['recipient_ids']:
                coach = FirebaseService.get_coach(coach_id)
                if coach:
                    phone = coach.get('phone_number') or coach.get('phone', '')
                    coach_name = coach.get('name') or f"{coach.get('first_name', '')} {coach.get('last_name', '')}".strip() or 'Coach'
                    if phone:
                        if template_name:
                            # Build template components with coach name + custom message
                            components = data.get('template_components')
                            if components is None:
                                # Auto-fill: first param = coach name, second = message body
                                body_params = [{"type": "text", "text": coach_name}]
                                if data.get('message'):
                                    body_params.append({"type": "text", "text": data['message']})
                                components = [{"type": "body", "parameters": body_params}]
                            result = WhatsAppService.send_template_message(
                                phone_number=phone,
                                template_name=template_name,
                                language_code=template_language,
                                components=components
                            )
                        else:
                            result = WhatsAppService.send_message(
                                phone_number=phone,
                                message_text=data['message']
                            )
                        send_results.append({
                            'coach_id': coach_id,
                            'name': coach_name,
                            'success': result.get('success', False)
                        })
                        if not result.get('success'):
                            failed_count += 1
                    else:
                        send_results.append({
                            'coach_id': coach_id,
                            'success': False,
                            'error': 'No phone number'
                        })
                        failed_count += 1

        # Create broadcast record
        broadcast = FirebaseService.create_broadcast({
            'channel': channel,
            'subject': data.get('subject', ''),
            'message': data.get('message', ''),
            'template_name': template_name or '',
            'recipient_ids': data['recipient_ids'],
            'sent_by': current_user,
            'send_results': send_results,
            'failed_count': failed_count
        })

        return jsonify({
            'success': True,
            'broadcast': broadcast,
            'send_results': send_results,
            'message': f'Broadcast sent to {len(send_results) - failed_count}/{len(send_results)} recipients'
        }), 201
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@broadcasts_bp.route('', methods=['GET'])
@token_required
def get_broadcasts(current_user):
    """Get broadcast history"""
    try:
        broadcasts = FirebaseService.get_all_broadcasts()
        return jsonify({
            'success': True,
            'broadcasts': broadcasts
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@broadcasts_bp.route('/templates', methods=['GET'])
@token_required
def get_templates(current_user):
    """Fetch approved WhatsApp message templates from Meta"""
    try:
        result = WhatsAppService.get_message_templates()
        if result.get('success'):
            return jsonify({
                'success': True,
                'templates': result['templates']
            }), 200
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Failed to fetch templates')
            }), 500
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
