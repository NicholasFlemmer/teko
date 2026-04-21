import logging
from flask import Blueprint, request, jsonify
from services.storage_service import StorageService
from services.firebase_service import FirebaseService
from routes.auth import token_required
from datetime import datetime, timezone
import os

logger = logging.getLogger(__name__)

uploads_bp = Blueprint('uploads', __name__)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.webp',  # images
    '.pdf', '.csv', '.xlsx', '.xls',            # documents
    '.doc', '.docx', '.txt',                    # text
}


@uploads_bp.route('', methods=['POST'])
@token_required
def upload_file(current_user):
    """Upload a file to Firebase Storage"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400

        file = request.files['file']
        if not file.filename:
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        # Validate file extension
        _, ext = os.path.splitext(file.filename)
        if ext.lower() not in ALLOWED_EXTENSIONS:
            return jsonify({
                'success': False,
                'error': f'File type not allowed. Accepted: {", ".join(sorted(ALLOWED_EXTENSIONS))}'
            }), 400

        # Validate file size (read content length or stream check)
        file.seek(0, 2)  # seek to end
        size = file.tell()
        file.seek(0)     # reset to start
        if size > MAX_FILE_SIZE:
            return jsonify({
                'success': False,
                'error': f'File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)} MB'
            }), 400

        # Get optional folder path — whitelist allowed prefixes
        folder = request.form.get('folder', 'uploads').strip()
        ALLOWED_FOLDERS = {'uploads', 'photos', 'profile-pictures', 'content', 'coach-documents'}
        if folder not in ALLOWED_FOLDERS:
            return jsonify({'success': False, 'error': f'Invalid folder. Allowed: {", ".join(sorted(ALLOWED_FOLDERS))}'}), 400

        # Upload to Firebase Storage
        result = StorageService.upload_file(file, folder)

        return jsonify({
            'success': True,
            'file': result,
            'message': 'File uploaded successfully'
        }), 201
    except Exception as e:
        logger.exception("Error in upload_file")
        return jsonify({'success': False, 'error': 'Upload failed'}), 500

@uploads_bp.route('/check-in/<token>', methods=['POST'])
def upload_via_check_in_token(token):
    """Upload a session photo using a check-in token (public).

    The check-in token authenticates which session the photo belongs to.
    Only image extensions are accepted on this public endpoint.
    Expired tokens are rejected; used tokens are accepted so coaches can
    add photos after they've checked in.
    """
    try:
        token_data = FirebaseService.get_check_in_token(token)
        if not token_data:
            return jsonify({'success': False, 'error': 'Invalid token'}), 404

        expires_at = token_data.get('expires_at')
        if expires_at:
            if hasattr(expires_at, 'tzinfo') and expires_at.tzinfo is not None:
                expires_at = expires_at.replace(tzinfo=None)
            if datetime.now(timezone.utc) > expires_at:
                return jsonify({'success': False, 'error': 'Check-in link has expired'}), 400

        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400

        file = request.files['file']
        if not file.filename:
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        _, ext = os.path.splitext(file.filename)
        image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
        if ext.lower() not in image_exts:
            return jsonify({
                'success': False,
                'error': f'Only images allowed: {", ".join(sorted(image_exts))}'
            }), 400

        file.seek(0, 2)
        size = file.tell()
        file.seek(0)
        if size > MAX_FILE_SIZE:
            return jsonify({
                'success': False,
                'error': f'File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)} MB'
            }), 400

        result = StorageService.upload_file(file, 'photos')
        return jsonify({'success': True, 'file': result}), 201
    except Exception as e:
        logger.exception("Error in upload_via_check_in_token")
        return jsonify({'success': False, 'error': 'Upload failed'}), 500


@uploads_bp.route('/<path:file_path>', methods=['DELETE'])
@token_required
def delete_file(current_user, file_path):
    """Delete a file from Firebase Storage"""
    try:
        # Prevent directory traversal — normalize and check
        normalized = os.path.normpath(file_path)
        if '..' in normalized or normalized.startswith('/') or normalized.startswith('\\'):
            return jsonify({'success': False, 'error': 'Invalid file path'}), 400
        StorageService.delete_file(normalized)
        return jsonify({'success': True, 'message': 'File deleted'}), 200
    except Exception as e:
        logger.exception("Error in delete_file")
        return jsonify({'success': False, 'error': 'Delete failed'}), 500
