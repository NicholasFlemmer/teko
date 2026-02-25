from flask import Blueprint, request, jsonify
import jwt
from datetime import datetime, timedelta
from config import Config
from functools import wraps

auth_bp = Blueprint('auth', __name__)

# Simple admin credentials (In production, use proper user management)
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"  # Change this in production!

def token_required(f):
    """Decorator to require JWT token for protected routes"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Get token from header
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]  # Bearer <token>
            except IndexError:
                return jsonify({'error': 'Invalid token format'}), 401
        
        if not token:
            return jsonify({'error': 'Token is missing'}), 401
        
        try:
            # Decode token
            data = jwt.decode(token, Config.SECRET_KEY, algorithms=["HS256"])
            current_user = data['username']
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        
        return f(current_user, *args, **kwargs)
    
    return decorated

@auth_bp.route('/login', methods=['POST'])
def login():
    """Admin login endpoint"""
    data = request.get_json()
    
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({'error': 'Username and password required'}), 400
    
    username = data.get('username')
    password = data.get('password')
    
    # Simple authentication (in production, use proper user management with hashed passwords)
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        # Generate JWT token
        token = jwt.encode({
            'username': username,
            'exp': datetime.utcnow() + timedelta(hours=Config.JWT_EXPIRY_HOURS)
        }, Config.SECRET_KEY, algorithm="HS256")
        
        return jsonify({
            'token': token,
            'username': username,
            'expires_in': Config.JWT_EXPIRY_HOURS * 3600  # seconds
        }), 200
    
    return jsonify({'error': 'Invalid credentials'}), 401

@auth_bp.route('/verify', methods=['GET'])
@token_required
def verify_token(current_user):
    """Verify if token is valid"""
    return jsonify({
        'valid': True,
        'username': current_user
    }), 200

@auth_bp.route('/refresh', methods=['POST'])
@token_required
def refresh_token(current_user):
    """Refresh JWT token"""
    # Generate new token
    token = jwt.encode({
        'username': current_user,
        'exp': datetime.utcnow() + timedelta(hours=Config.JWT_EXPIRY_HOURS)
    }, Config.SECRET_KEY, algorithm="HS256")
    
    return jsonify({
        'token': token,
        'expires_in': Config.JWT_EXPIRY_HOURS * 3600
    }), 200
