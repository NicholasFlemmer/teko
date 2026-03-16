import logging
from flask import Blueprint, request, jsonify
from services.storage_service import StorageService
from routes.auth import token_required
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
