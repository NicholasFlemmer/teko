import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
from config import Config
import os
import random
import string

class FirebaseService:
    """Service for Firebase Firestore operations
    
    Uses Application Default Credentials (ADC) for authentication.
    This is more secure than service account keys and complies with
    organization security policies.
    
    For local development: Run `gcloud auth application-default login`
    For Cloud Run: Automatically uses the service account
    """
    
    _db = None
    
    @classmethod
    def initialize(cls):
        """Initialize Firebase Admin SDK using Application Default Credentials"""
        if not firebase_admin._apps:
            try:
                # Check if credentials file exists (legacy support)
                cred_path = getattr(Config, 'FIREBASE_CREDENTIALS_PATH', None)
                if cred_path and os.path.exists(cred_path):
                    print(f"📄 Using service account credentials from: {cred_path}")
                    cred = credentials.Certificate(cred_path)
                    firebase_admin.initialize_app(cred)
                else:
                    # Use Application Default Credentials (recommended)
                    print("🔐 Using Application Default Credentials (ADC)")
                    firebase_admin.initialize_app()
                
                print("✅ Firebase Admin SDK initialized successfully")
            except Exception as e:
                print(f"❌ Firebase initialization failed: {e}")
                print("\nTroubleshooting:")
                print("  For local development, run: gcloud auth application-default login")
                print("  For Cloud Run, ensure the service account has Firebase Admin permissions")
                cls._db = None
                return None
            
        try:
            cls._db = firestore.client()
            print("✅ Firestore client connected successfully")
        except Exception as e:
            print(f"❌ Firestore client connection failed: {e}")
            cls._db = None
        return cls._db
    
    @classmethod
    def get_db(cls):
        """Get Firestore database instance"""
        if cls._db is None:
            cls.initialize()
        return cls._db
    
    # Coach operations
    # Supported fields: first_name, last_name, email, phone_number, dob,
    # profile_picture, emergency_name, emergency_relationship, emergency_phone,
    # notes, joined_date
    @classmethod
    def create_coach(cls, data):
        """Create a new coach

        Supported fields: first_name, last_name, email, phone_number, dob,
        profile_picture, emergency_name, emergency_relationship, emergency_phone,
        notes, joined_date
        """
        db = cls.get_db()
        data['created_at'] = firestore.SERVER_TIMESTAMP
        doc_ref = db.collection('coaches').document()
        doc_ref.set(data)
        # Fetch the document back to get the actual timestamp
        return cls.get_coach(doc_ref.id)
    
    @classmethod
    def get_coach(cls, coach_id):
        """Get coach by ID"""
        db = cls.get_db()
        doc = db.collection('coaches').document(coach_id).get()
        if doc.exists:
            return {'id': doc.id, **doc.to_dict()}
        return None
    
    @classmethod
    def get_all_coaches(cls):
        """Get all coaches"""
        db = cls.get_db()
        coaches = []
        docs = db.collection('coaches').stream()
        for doc in docs:
            coaches.append({'id': doc.id, **doc.to_dict()})
        return coaches
    
    @classmethod
    def update_coach(cls, coach_id, data):
        """Update coach

        Allowed fields: first_name, last_name, email, phone_number, dob,
        profile_picture, emergency_name, emergency_relationship, emergency_phone,
        notes, joined_date
        """
        allowed_fields = [
            'first_name', 'last_name', 'email', 'phone_number', 'dob',
            'profile_picture', 'emergency_name', 'emergency_relationship',
            'emergency_phone', 'notes', 'joined_date'
        ]
        filtered_data = {k: v for k, v in data.items() if k in allowed_fields}
        db = cls.get_db()
        doc_ref = db.collection('coaches').document(coach_id)
        doc_ref.update(filtered_data)
        return cls.get_coach(coach_id)
    
    @classmethod
    def delete_coach(cls, coach_id):
        """Delete coach"""
        db = cls.get_db()
        db.collection('coaches').document(coach_id).delete()
        return True
    
    # Session operations
    @classmethod
    def create_session(cls, data):
        """Create a new session"""
        db = cls.get_db()
        data['created_at'] = firestore.SERVER_TIMESTAMP
        data['status'] = 'scheduled'
        doc_ref = db.collection('sessions').document()
        doc_ref.set(data)
        # Fetch the document back to get the actual timestamp
        return cls.get_session(doc_ref.id)
    
    @classmethod
    def get_session(cls, session_id):
        """Get session by ID"""
        db = cls.get_db()
        doc = db.collection('sessions').document(session_id).get()
        if doc.exists:
            return {'id': doc.id, **doc.to_dict()}
        return None
    
    @classmethod
    def get_all_sessions(cls, start_date=None, end_date=None, coach_id=None):
        """Get sessions with optional filters"""
        db = cls.get_db()
        query = db.collection('sessions')
        
        if start_date:
            query = query.where('date', '>=', start_date)
        if end_date:
            query = query.where('date', '<=', end_date)
        if coach_id:
            query = query.where('coach_id', '==', coach_id)
        
        sessions = []
        docs = query.stream()
        for doc in docs:
            sessions.append({'id': doc.id, **doc.to_dict()})
        return sessions
    
    @classmethod
    def update_session(cls, session_id, data):
        """Update session"""
        db = cls.get_db()
        doc_ref = db.collection('sessions').document(session_id)
        doc_ref.update(data)
        return cls.get_session(session_id)
    
    @classmethod
    def delete_session(cls, session_id):
        """Delete session"""
        db = cls.get_db()
        db.collection('sessions').document(session_id).delete()
        return True
    
    @classmethod
    def get_sessions_for_reminder(cls, target_datetime):
        """Get sessions that need reminders at target datetime"""
        db = cls.get_db()
        # Query sessions that are scheduled and haven't been reminded yet
        sessions = []
        docs = db.collection('sessions')\
            .where('status', '==', 'scheduled')\
            .stream()
        
        for doc in docs:
            session_data = doc.to_dict()
            session_data['id'] = doc.id
            sessions.append(session_data)
        
        return sessions
    
    # Check-in token operations
    @classmethod
    def create_check_in_token(cls, token, session_id, expires_at):
        """Create check-in token"""
        db = cls.get_db()
        data = {
            'token': token,
            'session_id': session_id,
            'created_at': firestore.SERVER_TIMESTAMP,
            'expires_at': expires_at,
            'used': False
        }
        doc_ref = db.collection('check_in_tokens').document(token)
        doc_ref.set(data)
        return data
    
    @classmethod
    def get_check_in_token(cls, token):
        """Get check-in token"""
        db = cls.get_db()
        doc = db.collection('check_in_tokens').document(token).get()
        if doc.exists:
            return doc.to_dict()
        return None
    
    @classmethod
    def mark_token_used(cls, token):
        """Mark token as used"""
        db = cls.get_db()
        db.collection('check_in_tokens').document(token).update({'used': True})
        return True
    
    @classmethod
    def check_in_session(cls, session_id, check_in_data):
        """Update session with check-in data"""
        db = cls.get_db()
        update_data = {
            'status': 'checked_in',
            'check_in_time': firestore.SERVER_TIMESTAMP,
            'check_in_location': check_in_data.get('location', {}),
            'location_verified': check_in_data.get('location_verified', False)
        }
        doc_ref = db.collection('sessions').document(session_id)
        doc_ref.update(update_data)
        return cls.get_session(session_id)

    # =========================================================================
    # Team operations
    # =========================================================================
    @classmethod
    def create_team(cls, data):
        """Create a new team

        Fields: name, age_group, location_id, coach_ids (list), created_at
        """
        db = cls.get_db()
        data['created_at'] = firestore.SERVER_TIMESTAMP
        doc_ref = db.collection('teams').document()
        doc_ref.set(data)
        return cls.get_team(doc_ref.id)

    @classmethod
    def get_team(cls, team_id):
        """Get team by ID"""
        db = cls.get_db()
        doc = db.collection('teams').document(team_id).get()
        if doc.exists:
            return {'id': doc.id, **doc.to_dict()}
        return None

    @classmethod
    def get_all_teams(cls, location_id=None):
        """Get all teams with optional location filter"""
        db = cls.get_db()
        query = db.collection('teams')
        if location_id:
            query = query.where('location_id', '==', location_id)
        teams = []
        docs = query.stream()
        for doc in docs:
            teams.append({'id': doc.id, **doc.to_dict()})
        return teams

    @classmethod
    def update_team(cls, team_id, data):
        """Update team"""
        db = cls.get_db()
        doc_ref = db.collection('teams').document(team_id)
        doc_ref.update(data)
        return cls.get_team(team_id)

    @classmethod
    def delete_team(cls, team_id):
        """Delete team"""
        db = cls.get_db()
        db.collection('teams').document(team_id).delete()
        return True

    # =========================================================================
    # Player operations
    # =========================================================================
    @classmethod
    def _generate_player_id(cls):
        """Generate a unique player ID like PLR-XXXXX"""
        chars = string.ascii_uppercase + string.digits
        suffix = ''.join(random.choices(chars, k=5))
        return f"PLR-{suffix}"

    @classmethod
    def create_player(cls, data):
        """Create a new player

        Fields: first_name, last_name, date_of_birth, guardian_name,
        guardian_email, guardian_primary_phone, guardian_secondary_phone,
        special_notes, team_ids (list), player_id (auto-generated), created_at
        """
        db = cls.get_db()
        data['player_id'] = cls._generate_player_id()
        data['created_at'] = firestore.SERVER_TIMESTAMP
        doc_ref = db.collection('players').document()
        doc_ref.set(data)
        return cls.get_player(doc_ref.id)

    @classmethod
    def get_player(cls, player_id):
        """Get player by ID"""
        db = cls.get_db()
        doc = db.collection('players').document(player_id).get()
        if doc.exists:
            return {'id': doc.id, **doc.to_dict()}
        return None

    @classmethod
    def get_all_players(cls, team_id=None):
        """Get all players with optional team filter"""
        db = cls.get_db()
        query = db.collection('players')
        if team_id:
            query = query.where('team_ids', 'array_contains', team_id)
        players = []
        docs = query.stream()
        for doc in docs:
            players.append({'id': doc.id, **doc.to_dict()})
        return players

    @classmethod
    def update_player(cls, player_id, data):
        """Update player"""
        db = cls.get_db()
        doc_ref = db.collection('players').document(player_id)
        doc_ref.update(data)
        return cls.get_player(player_id)

    @classmethod
    def delete_player(cls, player_id):
        """Delete player"""
        db = cls.get_db()
        db.collection('players').document(player_id).delete()
        return True

    # =========================================================================
    # Location operations
    # =========================================================================
    @classmethod
    def create_location(cls, data):
        """Create a new location

        Fields: name, address, google_maps_link, radius, notes, created_at
        """
        db = cls.get_db()
        data['created_at'] = firestore.SERVER_TIMESTAMP
        doc_ref = db.collection('locations').document()
        doc_ref.set(data)
        return cls.get_location(doc_ref.id)

    @classmethod
    def get_location(cls, location_id):
        """Get location by ID"""
        db = cls.get_db()
        doc = db.collection('locations').document(location_id).get()
        if doc.exists:
            return {'id': doc.id, **doc.to_dict()}
        return None

    @classmethod
    def get_all_locations(cls):
        """Get all locations"""
        db = cls.get_db()
        locations = []
        docs = db.collection('locations').stream()
        for doc in docs:
            locations.append({'id': doc.id, **doc.to_dict()})
        return locations

    @classmethod
    def update_location(cls, location_id, data):
        """Update location"""
        db = cls.get_db()
        doc_ref = db.collection('locations').document(location_id)
        doc_ref.update(data)
        return cls.get_location(location_id)

    @classmethod
    def delete_location(cls, location_id):
        """Delete location"""
        db = cls.get_db()
        db.collection('locations').document(location_id).delete()
        return True

    # =========================================================================
    # Broadcast operations
    # =========================================================================
    @classmethod
    def create_broadcast(cls, data):
        """Create a new broadcast

        Fields: channel, subject, message, recipient_ids, recipient_count,
        status, cost, created_at
        """
        db = cls.get_db()
        data['created_at'] = firestore.SERVER_TIMESTAMP
        doc_ref = db.collection('broadcasts').document()
        doc_ref.set(data)
        # Re-read to get the resolved server timestamp
        saved = doc_ref.get().to_dict()
        return {'id': doc_ref.id, **saved}

    @classmethod
    def get_all_broadcasts(cls):
        """Get all broadcasts"""
        db = cls.get_db()
        broadcasts = []
        docs = db.collection('broadcasts').stream()
        for doc in docs:
            broadcasts.append({'id': doc.id, **doc.to_dict()})
        return broadcasts

    # =========================================================================
    # Content operations
    # =========================================================================
    @classmethod
    def create_content(cls, data):
        """Create a new content item

        Fields: title, type, topic, language, content_text, file_name, created_at
        """
        db = cls.get_db()
        data['created_at'] = firestore.SERVER_TIMESTAMP
        doc_ref = db.collection('content').document()
        doc_ref.set(data)
        return cls.get_content(doc_ref.id)

    @classmethod
    def get_content(cls, content_id):
        """Get content by ID"""
        db = cls.get_db()
        doc = db.collection('content').document(content_id).get()
        if doc.exists:
            return {'id': doc.id, **doc.to_dict()}
        return None

    @classmethod
    def get_all_content(cls):
        """Get all content"""
        db = cls.get_db()
        content_list = []
        docs = db.collection('content').stream()
        for doc in docs:
            content_list.append({'id': doc.id, **doc.to_dict()})
        return content_list

    @classmethod
    def update_content(cls, content_id, data):
        """Update content"""
        db = cls.get_db()
        doc_ref = db.collection('content').document(content_id)
        doc_ref.update(data)
        return cls.get_content(content_id)

    @classmethod
    def delete_content(cls, content_id):
        """Delete content"""
        db = cls.get_db()
        db.collection('content').document(content_id).delete()
        return True

    # =========================================================================
    # Content URL operations
    # =========================================================================
    @classmethod
    def create_url(cls, data):
        """Create a new content URL

        Fields: url, title, description, instructions, created_at
        """
        db = cls.get_db()
        data['created_at'] = firestore.SERVER_TIMESTAMP
        doc_ref = db.collection('content_urls').document()
        doc_ref.set(data)
        return cls.get_url(doc_ref.id)

    @classmethod
    def get_url(cls, url_id):
        """Get content URL by ID"""
        db = cls.get_db()
        doc = db.collection('content_urls').document(url_id).get()
        if doc.exists:
            return {'id': doc.id, **doc.to_dict()}
        return None

    @classmethod
    def get_all_urls(cls):
        """Get all content URLs"""
        db = cls.get_db()
        urls = []
        docs = db.collection('content_urls').stream()
        for doc in docs:
            urls.append({'id': doc.id, **doc.to_dict()})
        return urls

    @classmethod
    def update_url(cls, url_id, data):
        """Update content URL"""
        db = cls.get_db()
        doc_ref = db.collection('content_urls').document(url_id)
        doc_ref.update(data)
        return cls.get_url(url_id)

    @classmethod
    def delete_url(cls, url_id):
        """Delete content URL"""
        db = cls.get_db()
        db.collection('content_urls').document(url_id).delete()
        return True

    # =========================================================================
    # Reminder operations
    # =========================================================================
    @classmethod
    def create_reminder(cls, data):
        """Create a new reminder

        Fields: type, timing, enabled, description, created_at
        """
        db = cls.get_db()
        data['created_at'] = firestore.SERVER_TIMESTAMP
        doc_ref = db.collection('reminders').document()
        doc_ref.set(data)
        return cls.get_reminder(doc_ref.id)

    @classmethod
    def get_reminder(cls, reminder_id):
        """Get reminder by ID"""
        db = cls.get_db()
        doc = db.collection('reminders').document(reminder_id).get()
        if doc.exists:
            return {'id': doc.id, **doc.to_dict()}
        return None

    @classmethod
    def get_all_reminders(cls):
        """Get all reminders"""
        db = cls.get_db()
        reminders = []
        docs = db.collection('reminders').stream()
        for doc in docs:
            reminders.append({'id': doc.id, **doc.to_dict()})
        return reminders

    @classmethod
    def update_reminder(cls, reminder_id, data):
        """Update reminder"""
        db = cls.get_db()
        doc_ref = db.collection('reminders').document(reminder_id)
        doc_ref.update(data)
        return cls.get_reminder(reminder_id)

    @classmethod
    def delete_reminder(cls, reminder_id):
        """Delete reminder"""
        db = cls.get_db()
        db.collection('reminders').document(reminder_id).delete()
        return True

    # =========================================================================
    # Admin User operations (collection: 'admin_users')
    # =========================================================================
    @classmethod
    def create_admin(cls, data):
        """Create a new admin user

        Fields: name, email, password_hash, role, status, created_at
        """
        db = cls.get_db()
        data['created_at'] = firestore.SERVER_TIMESTAMP
        doc_ref = db.collection('admin_users').document()
        doc_ref.set(data)
        return cls.get_admin(doc_ref.id)

    @classmethod
    def get_admin(cls, admin_id):
        """Get admin user by ID"""
        db = cls.get_db()
        doc = db.collection('admin_users').document(admin_id).get()
        if doc.exists:
            return {'id': doc.id, **doc.to_dict()}
        return None

    @classmethod
    def get_admin_by_email(cls, email):
        """Get admin user by email"""
        db = cls.get_db()
        docs = db.collection('admin_users').where('email', '==', email).limit(1).stream()
        for doc in docs:
            return {'id': doc.id, **doc.to_dict()}
        return None

    @classmethod
    def get_all_admins(cls):
        """Get all admin users"""
        db = cls.get_db()
        admins = []
        docs = db.collection('admin_users').stream()
        for doc in docs:
            admins.append({'id': doc.id, **doc.to_dict()})
        return admins

    @classmethod
    def update_admin(cls, admin_id, data):
        """Update admin user"""
        db = cls.get_db()
        doc_ref = db.collection('admin_users').document(admin_id)
        doc_ref.update(data)
        return cls.get_admin(admin_id)

    @classmethod
    def delete_admin(cls, admin_id):
        """Delete admin user"""
        db = cls.get_db()
        db.collection('admin_users').document(admin_id).delete()
        return True

    # =========================================================================
    # Settings operations (single document 'app_settings')
    # =========================================================================
    @classmethod
    def get_settings(cls):
        """Get application settings"""
        db = cls.get_db()
        doc = db.collection('settings').document('app_settings').get()
        if doc.exists:
            return {'id': doc.id, **doc.to_dict()}
        return None

    @classmethod
    def update_settings(cls, data):
        """Update application settings (creates if not exists)"""
        db = cls.get_db()
        doc_ref = db.collection('settings').document('app_settings')
        doc_ref.set(data, merge=True)
        return cls.get_settings()

    # =========================================================================
    # Report helpers
    # =========================================================================
    @classmethod
    def get_sessions_by_date_range(cls, start_date, end_date):
        """Get sessions within a date range for reports"""
        db = cls.get_db()
        sessions = []
        docs = db.collection('sessions')\
            .where('date', '>=', start_date)\
            .where('date', '<=', end_date)\
            .stream()
        for doc in docs:
            sessions.append({'id': doc.id, **doc.to_dict()})
        return sessions

    @classmethod
    def count_players(cls):
        """Count total players"""
        db = cls.get_db()
        docs = db.collection('players').stream()
        count = 0
        for _ in docs:
            count += 1
        return count

    @classmethod
    def count_active_coaches(cls):
        """Count active coaches"""
        db = cls.get_db()
        docs = db.collection('coaches').stream()
        count = 0
        for _ in docs:
            count += 1
        return count
