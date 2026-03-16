import logging
from flask import Blueprint, request, jsonify
from services.firebase_service import FirebaseService
from routes.auth import token_required

logger = logging.getLogger(__name__)

content_bp = Blueprint('content', __name__)

# --- Content Items ---

@content_bp.route('', methods=['GET'])
@token_required
def get_content(current_user):
    """Get all content items"""
    try:
        content = FirebaseService.get_all_content()
        return jsonify({
            'success': True,
            'content': content
        }), 200
    except Exception as e:
        logger.exception("Error in get_content")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@content_bp.route('', methods=['POST'])
@token_required
def create_content(current_user):
    """Create a new content item"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        # Validate required fields
        required_fields = ['title', 'type']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }), 400

        # Create content
        content_data = {
            'title': data['title'],
            'type': data['type'],
            'topic': data.get('topic', ''),
            'language': data.get('language', 'English'),
            'content_text': data.get('content_text', ''),
            'file_name': data.get('file_name', ''),
            'file_url': data.get('file_url', ''),
            'file_path': data.get('file_path', ''),
        }

        # If a file was uploaded but no content_text, try to extract text
        if content_data['file_path'] and not content_data['content_text']:
            try:
                from services.content_extraction import ContentExtraction
                extracted = ContentExtraction.extract_from_storage(
                    content_data['file_path'], content_data['type']
                )
                if extracted:
                    content_data['content_text'] = extracted
            except Exception as ex:
                logger.warning(f"Text extraction failed: {ex}")

        content = FirebaseService.create_content(content_data)

        return jsonify({
            'success': True,
            'content': content,
            'message': 'Content created successfully'
        }), 201
    except Exception as e:
        logger.exception("Error in create_content")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@content_bp.route('/<content_id>', methods=['PUT'])
@token_required
def update_content(current_user, content_id):
    """Update a content item"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        # Check if content exists
        content = FirebaseService.get_content(content_id)
        if not content:
            return jsonify({
                'success': False,
                'error': 'Content not found'
            }), 404

        # Update allowed fields
        update_data = {}
        allowed_fields = ['title', 'type', 'topic', 'language', 'content_text', 'file_name', 'file_url', 'file_path']
        for field in allowed_fields:
            if field in data:
                update_data[field] = data[field]

        if not update_data:
            return jsonify({
                'success': False,
                'error': 'No valid fields to update'
            }), 400

        # Update content
        updated_content = FirebaseService.update_content(content_id, update_data)

        return jsonify({
            'success': True,
            'content': updated_content,
            'message': 'Content updated successfully'
        }), 200
    except Exception as e:
        logger.exception("Error in update_content")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@content_bp.route('/<content_id>', methods=['DELETE'])
@token_required
def delete_content(current_user, content_id):
    """Delete a content item"""
    try:
        # Check if content exists
        content = FirebaseService.get_content(content_id)
        if not content:
            return jsonify({
                'success': False,
                'error': 'Content not found'
            }), 404

        # Delete content
        FirebaseService.delete_content(content_id)

        return jsonify({
            'success': True,
            'message': 'Content deleted successfully'
        }), 200
    except Exception as e:
        logger.exception("Error in delete_content")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

# --- URL Resources ---

@content_bp.route('/urls', methods=['GET'])
@token_required
def get_urls(current_user):
    """Get all URL resources"""
    try:
        urls = FirebaseService.get_all_urls()
        return jsonify({
            'success': True,
            'urls': urls
        }), 200
    except Exception as e:
        logger.exception("Error in get_urls")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@content_bp.route('/urls', methods=['POST'])
@token_required
def create_url(current_user):
    """Create a new URL resource"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        # Validate required fields
        required_fields = ['url', 'title']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }), 400

        # Create URL resource
        url = FirebaseService.create_url({
            'url': data['url'],
            'title': data['title'],
            'description': data.get('description', ''),
            'instructions': data.get('instructions', '')
        })

        return jsonify({
            'success': True,
            'url': url,
            'message': 'URL resource created successfully'
        }), 201
    except Exception as e:
        logger.exception("Error in create_url")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@content_bp.route('/urls/<url_id>', methods=['PUT'])
@token_required
def update_url(current_user, url_id):
    """Update a URL resource"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        # Check if URL exists
        url = FirebaseService.get_url(url_id)
        if not url:
            return jsonify({
                'success': False,
                'error': 'URL resource not found'
            }), 404

        # Update allowed fields
        update_data = {}
        allowed_fields = ['url', 'title', 'description', 'instructions']
        for field in allowed_fields:
            if field in data:
                update_data[field] = data[field]

        if not update_data:
            return jsonify({
                'success': False,
                'error': 'No valid fields to update'
            }), 400

        # Update URL
        updated_url = FirebaseService.update_url(url_id, update_data)

        return jsonify({
            'success': True,
            'url': updated_url,
            'message': 'URL resource updated successfully'
        }), 200
    except Exception as e:
        logger.exception("Error in update_url")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500

@content_bp.route('/urls/<url_id>', methods=['DELETE'])
@token_required
def delete_url(current_user, url_id):
    """Delete a URL resource"""
    try:
        # Check if URL exists
        url = FirebaseService.get_url(url_id)
        if not url:
            return jsonify({
                'success': False,
                'error': 'URL resource not found'
            }), 404

        # Delete URL
        FirebaseService.delete_url(url_id)

        return jsonify({
            'success': True,
            'message': 'URL resource deleted successfully'
        }), 200
    except Exception as e:
        logger.exception("Error in delete_url")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500
