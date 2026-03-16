import logging
from flask import Blueprint, request, jsonify
from services.firebase_service import FirebaseService
from services.whatsapp_service import WhatsAppService
from routes.auth import token_required

logger = logging.getLogger(__name__)

broadcasts_bp = Blueprint('broadcasts', __name__)

# Default WhatsApp Business API pricing (USD per message)
DEFAULT_PRICING = {
    'marketing': 0.0625,
    'utility': 0.0200,
    'service': 0.0,       # free within 24h window
    'usd_to_zar': 18.50,  # approximate conversion rate
}


def _get_pricing():
    """Load pricing from Firestore settings, falling back to defaults."""
    try:
        settings = FirebaseService.get_settings()
        if settings:
            return settings.get('whatsapp_pricing', DEFAULT_PRICING)
        return DEFAULT_PRICING
    except Exception:
        return DEFAULT_PRICING


@broadcasts_bp.route('', methods=['POST'])
@token_required
def send_broadcast(current_user):
    """Send a broadcast message via whatsapp or email"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

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
        if channel not in ['whatsapp']:
            return jsonify({
                'success': False,
                'error': 'Only "whatsapp" channel is currently supported'
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
            # Batch-fetch all coaches upfront to avoid N+1 queries
            all_coaches = FirebaseService.get_all_coaches()
            coaches_by_id = {c['id']: c for c in all_coaches}

            for coach_id in data['recipient_ids']:
                coach = coaches_by_id.get(coach_id)
                if not coach:
                    send_results.append({'coach_id': coach_id, 'success': False, 'error': 'Coach not found'})
                    failed_count += 1
                    continue

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

        # Calculate estimated cost
        pricing = _get_pricing()
        message_type = data.get('message_type', 'utility' if template_name else 'service')
        rate = pricing.get(message_type, 0.0)
        successful_count = len(send_results) - failed_count
        cost_usd = round(rate * successful_count, 4)
        cost_zar = round(cost_usd * pricing.get('usd_to_zar', 18.50), 2)

        # Create broadcast record
        broadcast = FirebaseService.create_broadcast({
            'channel': channel,
            'subject': data.get('subject', ''),
            'message': data.get('message', ''),
            'template_name': template_name or '',
            'recipient_ids': data['recipient_ids'],
            'sent_by': current_user,
            'send_results': send_results,
            'failed_count': failed_count,
            'estimated_cost': {
                'cost_usd': cost_usd,
                'cost_zar': cost_zar,
                'message_type': message_type,
                'rate_per_message_usd': rate,
                'successful_count': successful_count,
            },
        })

        return jsonify({
            'success': True,
            'broadcast': broadcast,
            'send_results': send_results,
            'estimated_cost': {
                'cost_usd': cost_usd,
                'cost_zar': cost_zar,
            },
            'message': f'Broadcast sent to {successful_count}/{len(send_results)} recipients'
        }), 201
    except Exception as e:
        logger.exception("Error in send_broadcast")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500


@broadcasts_bp.route('/estimate-cost', methods=['POST'])
@token_required
def estimate_cost(current_user):
    """Estimate cost of a broadcast before sending.

    Body: {recipient_count: int, message_type: "marketing"|"utility"|"service"}
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400
        recipient_count = data.get('recipient_count', 0)
        message_type = data.get('message_type', 'utility')

        if recipient_count < 0:
            return jsonify({'success': False, 'error': 'recipient_count must be >= 0'}), 400
        if message_type not in ('marketing', 'utility', 'service'):
            return jsonify({'success': False, 'error': 'message_type must be marketing, utility, or service'}), 400

        pricing = _get_pricing()
        rate = pricing.get(message_type, 0.0)
        cost_usd = round(rate * recipient_count, 4)
        usd_to_zar = pricing.get('usd_to_zar', 18.50)
        cost_zar = round(cost_usd * usd_to_zar, 2)

        return jsonify({
            'success': True,
            'recipient_count': recipient_count,
            'message_type': message_type,
            'rate_per_message_usd': rate,
            'cost_usd': cost_usd,
            'cost_zar': cost_zar,
            'usd_to_zar_rate': usd_to_zar,
        }), 200
    except Exception as e:
        logger.exception("Error in estimate_cost")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@broadcasts_bp.route('/pricing', methods=['GET'])
@token_required
def get_pricing(current_user):
    """Get current WhatsApp pricing configuration."""
    return jsonify({'success': True, 'pricing': _get_pricing()}), 200


@broadcasts_bp.route('/pricing', methods=['PUT'])
@token_required
def update_pricing(current_user):
    """Update WhatsApp pricing configuration.

    Body: {marketing: float, utility: float, service: float, usd_to_zar: float}
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400
        current_pricing = _get_pricing()
        import math
        for key in ('marketing', 'utility', 'service', 'usd_to_zar'):
            if key in data:
                try:
                    val = float(data[key])
                except (ValueError, TypeError):
                    return jsonify({'success': False, 'error': f'Invalid value for {key}'}), 400
                if math.isnan(val) or math.isinf(val) or val < 0:
                    return jsonify({'success': False, 'error': f'{key} must be a non-negative finite number'}), 400
                current_pricing[key] = val

        FirebaseService.update_settings({'whatsapp_pricing': current_pricing})
        return jsonify({'success': True, 'pricing': current_pricing}), 200
    except Exception as e:
        logger.exception("Error in update_pricing")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


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
        logger.exception("Error in get_broadcasts")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
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
        logger.exception("Error in get_templates")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500


@broadcasts_bp.route('/templates/<template_name>', methods=['GET'])
@token_required
def get_template_preview(current_user, template_name):
    """Get a specific template's details for preview."""
    try:
        result = WhatsAppService.get_message_templates()
        if not result.get('success'):
            return jsonify({'success': False, 'error': 'Failed to fetch templates'}), 500

        template = None
        for t in result.get('templates', []):
            if t.get('name') == template_name:
                template = t
                break

        if not template:
            return jsonify({'success': False, 'error': f'Template "{template_name}" not found'}), 404

        # Extract body text and parameters
        body_text = ''
        parameters = []
        for comp in template.get('components', []):
            if comp.get('type') == 'BODY':
                body_text = comp.get('text', '')
                # Count {{N}} placeholders
                import re
                params = re.findall(r'\{\{(\d+)\}\}', body_text)
                parameters = [f'{{{{{{p}}}}}}' for p in params]

        return jsonify({
            'success': True,
            'template': {
                'name': template.get('name'),
                'language': template.get('language'),
                'category': template.get('category'),
                'status': template.get('status'),
                'body_text': body_text,
                'parameter_count': len(parameters),
                'components': template.get('components', []),
            },
        }), 200
    except Exception as e:
        logger.exception("Error in get_template_preview")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500
