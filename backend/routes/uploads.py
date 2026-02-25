from flask import Blueprint, request, jsonify
from services.firebase_service import FirebaseService
from services.storage_service import StorageService
from routes.auth import token_required

uploads_bp = Blueprint('uploads', __name__)

@uploads_bp.route('', methods=['POST'])
@token_required
def upload_file(current_user):
    """Upload a file to Firebase Storage"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        # Get optional folder path
        folder = request.form.get('folder', 'uploads')

        # Upload to Firebase Storage
        result = StorageService.upload_file(file, folder)

        return jsonify({
            'success': True,
            'file': result,
            'message': 'File uploaded successfully'
        }), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@uploads_bp.route('/<path:file_path>', methods=['DELETE'])
@token_required
def delete_file(current_user, file_path):
    """Delete a file from Firebase Storage"""
    try:
        StorageService.delete_file(file_path)
        return jsonify({'success': True, 'message': 'File deleted'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
