import logging
from flask import Blueprint, request, jsonify, g
from services.storage_service import StorageService
from services.firebase_service import FirebaseService
from routes.auth import token_required
from google.api_core.exceptions import NotFound
from datetime import datetime, timezone
import os

logger = logging.getLogger(__name__)

uploads_bp = Blueprint('uploads', __name__)

# Dashboard upload folders. New files go under <folder>/<org_id>/<name> so the
# owning organisation can be read back from the path (see _file_org_id).
ADMIN_UPLOAD_FOLDERS = {'uploads', 'photos', 'profile-pictures', 'content', 'coach-documents'}

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
        if folder not in ADMIN_UPLOAD_FOLDERS:
            return jsonify({'success': False, 'error': f'Invalid folder. Allowed: {", ".join(sorted(ADMIN_UPLOAD_FOLDERS))}'}), 400

        # Keep the owning organisation in the path so the file can later be
        # tied back to it. A super_admin with no org uploads under 'platform'.
        org_id = getattr(g, 'current_user_org_id', None)
        result = StorageService.upload_file(file, f"{folder}/{org_id or 'platform'}")

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


def _file_org_id(normalized_path):
    """The organisation that owns a storage path, or None if it can't be
    resolved. Two shapes are recognised:
      - team_photos/<team_id>/<file>  (WhatsApp photos): the team's org_id
      - <admin folder>/<org_id>/<file> (dashboard uploads): the org_id segment,
        only if it is a real organisation
    Anything else (including old-style <folder>/<file>) resolves to None.
    """
    parts = normalized_path.split('/')
    if len(parts) != 3 or not all(parts):
        return None
    if parts[0] == StorageService.PRIVATE_PHOTO_PREFIX.rstrip('/'):
        team = FirebaseService.get_team(parts[1], None)
        return (team or {}).get('org_id')
    if parts[0] in ADMIN_UPLOAD_FOLDERS:
        org = FirebaseService.get_organisation(parts[1])
        return (org or {}).get('id')
    return None


@uploads_bp.route('/<path:file_path>', methods=['DELETE'])
@token_required
def delete_file(current_user, file_path):
    """Delete a file from Firebase Storage.

    super_admin may delete any file. Anyone else may delete only a file whose
    path resolves to their own organisation; another organisation's file, a
    path that resolves to no organisation, and a missing file all get the same
    "File not found" so nothing reveals that a file exists.
    """
    try:
        # Prevent directory traversal — normalize and check
        normalized = os.path.normpath(file_path)
        if '..' in normalized or normalized.startswith('/') or normalized.startswith('\\'):
            return jsonify({'success': False, 'error': 'Invalid file path'}), 400

        not_found = (jsonify({'success': False, 'error': 'File not found'}), 404)
        if getattr(g, 'current_user_role', None) != 'super_admin':
            caller_org = getattr(g, 'current_user_org_id', None)
            owner_org = _file_org_id(normalized)
            if caller_org is None or owner_org is None or owner_org != caller_org:
                return not_found

        try:
            StorageService.delete_file(normalized)
        except NotFound:
            return not_found
        return jsonify({'success': True, 'message': 'File deleted'}), 200
    except Exception as e:
        logger.exception("Error in delete_file")
        return jsonify({'success': False, 'error': 'Delete failed'}), 500
