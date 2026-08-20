import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta, timezone
from config import Config
import os
import random
import string
import secrets
import logging

logger = logging.getLogger(__name__)

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
                # Pin the project explicitly so we never inherit the wrong
                # project from the ADC/gcloud default (e.g. another app).
                project_id = getattr(Config, 'FIREBASE_PROJECT_ID', None)
                options = {'projectId': project_id} if project_id else None

                # Check if credentials file exists (legacy support)
                cred_path = getattr(Config, 'FIREBASE_CREDENTIALS_PATH', None)
                if cred_path and os.path.exists(cred_path):
                    logger.info("Using service account credentials from: %s", cred_path)
                    cred = credentials.Certificate(cred_path)
                    firebase_admin.initialize_app(cred, options)
                else:
                    # Use Application Default Credentials (recommended)
                    logger.info("Using Application Default Credentials (ADC) for project: %s", project_id)
                    firebase_admin.initialize_app(options=options)

                logger.info("Firebase Admin SDK initialized successfully")
            except Exception as e:
                logger.error("Firebase initialization failed: %s", e)
                logger.error("For local dev, run: gcloud auth application-default login")
                cls._db = None
                return None

        try:
            cls._db = firestore.client()
            logger.info("Firestore client connected successfully")
        except Exception as e:
            logger.error("Firestore client connection failed: %s", e)
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
        return cls.get_coach(doc_ref.id, data.get('org_id'))

    @classmethod
    def get_coach(cls, coach_id, org_id):
        """Get coach by ID, scoped to org_id.

        Returns None (treated as not found) if the coach belongs to a
        different org. Pass org_id=None only for the intentional super_admin
        cross-org case, or for internal callers that already verified
        ownership.
        """
        db = cls.get_db()
        doc = db.collection('coaches').document(coach_id).get()
        if not doc.exists:
            return None
        data = {'id': doc.id, **doc.to_dict()}
        if org_id is not None and data.get('org_id') != org_id:
            return None
        return data

    @classmethod
    def get_all_coaches(cls, org_id):
        """Get all coaches for an org. Pass org_id=None only for the
        intentional super_admin cross-org case."""
        db = cls.get_db()
        query = db.collection('coaches')
        if org_id is not None:
            query = query.where('org_id', '==', org_id)
        coaches = []
        docs = query.stream()
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
            'name', 'first_name', 'last_name', 'email', 'phone_number', 'dob',
            'profile_picture', 'emergency_name', 'emergency_relationship',
            'emergency_phone', 'notes', 'joined_date'
        ]
        filtered_data = {k: v for k, v in data.items() if k in allowed_fields}
        db = cls.get_db()
        doc_ref = db.collection('coaches').document(coach_id)
        doc_ref.update(filtered_data)
        # Ownership already verified by the caller before calling update.
        return cls.get_coach(coach_id, None)
    
    @classmethod
    def delete_coach(cls, coach_id):
        """Delete coach"""
        db = cls.get_db()
        db.collection('coaches').document(coach_id).delete()
        return True

    # =========================================================================
    # Participant operations (collection: 'participants')
    # =========================================================================
    # A separate collection from 'players' — players stores a guardian's
    # contact phone for a roster entry, not a self-owned WhatsApp identity.
    # Fields: org_id, name, phone_number (normalized via normalize_sa_phone
    # by the caller before reaching these methods), active, created_at,
    # updated_at.
    @classmethod
    def create_participant(cls, org_id, data):
        """Create a new participant under org_id.

        org_id is stamped from the explicit parameter, not from `data`, so a
        caller can never smuggle in a different org_id via the request body.
        """
        db = cls.get_db()
        now = firestore.SERVER_TIMESTAMP
        participant_data = {
            **data,
            'org_id': org_id,
            'active': data.get('active', True),
            'created_at': now,
            'updated_at': now,
        }
        doc_ref = db.collection('participants').document()
        doc_ref.set(participant_data)
        return cls.get_participant(org_id, doc_ref.id)

    @classmethod
    def get_participant(cls, org_id, participant_id):
        """Get participant by ID, scoped to org_id.

        Returns None (treated as not found) if the participant belongs to a
        different org. Pass org_id=None only for the intentional super_admin
        cross-org case, or for internal callers that already verified
        ownership.
        """
        db = cls.get_db()
        doc = db.collection('participants').document(participant_id).get()
        if not doc.exists:
            return None
        data = {'id': doc.id, **doc.to_dict()}
        if org_id is not None and data.get('org_id') != org_id:
            return None
        return data

    @classmethod
    def get_all_participants(cls, org_id):
        """Get all participants for an org. Pass org_id=None only for the
        intentional super_admin cross-org case."""
        db = cls.get_db()
        query = db.collection('participants')
        if org_id is not None:
            query = query.where('org_id', '==', org_id)
        participants = []
        docs = query.stream()
        for doc in docs:
            participants.append({'id': doc.id, **doc.to_dict()})
        return participants

    @classmethod
    def update_participant(cls, org_id, participant_id, data):
        """Update participant, scoped to org_id.

        Returns None without applying the update if the participant doesn't
        exist or belongs to a different org — ownership is re-verified here,
        not just trusted from the caller.
        """
        existing = cls.get_participant(org_id, participant_id)
        if existing is None:
            return None
        allowed_fields = ['name', 'phone_number', 'active']
        filtered_data = {k: v for k, v in data.items() if k in allowed_fields}
        filtered_data['updated_at'] = firestore.SERVER_TIMESTAMP
        db = cls.get_db()
        doc_ref = db.collection('participants').document(participant_id)
        doc_ref.update(filtered_data)
        return cls.get_participant(org_id, participant_id)

    @classmethod
    def delete_participant(cls, org_id, participant_id):
        """Delete participant, scoped to org_id.

        Returns False without deleting if the participant doesn't exist or
        belongs to a different org.
        """
        existing = cls.get_participant(org_id, participant_id)
        if existing is None:
            return False
        db = cls.get_db()
        db.collection('participants').document(participant_id).delete()
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
        return cls.get_session(doc_ref.id, data.get('org_id'))

    @classmethod
    def get_session(cls, session_id, org_id):
        """Get session by ID, scoped to org_id.

        Returns None (treated as not found) if the session belongs to a
        different org. Pass org_id=None only for the intentional super_admin
        cross-org case, or for internal callers (e.g. check-in-token flows)
        that already established authorization by another means.
        """
        db = cls.get_db()
        doc = db.collection('sessions').document(session_id).get()
        if not doc.exists:
            return None
        data = {'id': doc.id, **doc.to_dict()}
        if org_id is not None and data.get('org_id') != org_id:
            return None
        return data
    
    @staticmethod
    def get_session_coach_ids(session):
        """Get list of coach IDs from a session (handles both coach_id and coach_ids)"""
        coach_ids = session.get('coach_ids') or []
        if not coach_ids:
            single = session.get('coach_id')
            if single:
                coach_ids = [single]
        return coach_ids

    @staticmethod
    def get_session_team_ids(session):
        """Get list of team IDs from a session (handles both team_id and team_ids)"""
        team_ids = session.get('team_ids') or []
        if not team_ids:
            single = session.get('team_id')
            if single:
                team_ids = [single]
        return team_ids

    @classmethod
    def get_all_sessions(cls, org_id, start_date=None, end_date=None, coach_id=None):
        """Get sessions with optional filters, scoped to org_id.

        Pass org_id=None only for the intentional super_admin cross-org case.
        NOTE: combining the org_id equality filter with the date range below
        may require a Firestore composite index (org_id ASC, date ASC) — if
        so, Firestore raises FAILED_PRECONDITION with a direct console link.
        """
        db = cls.get_db()
        query = db.collection('sessions')
        if org_id is not None:
            query = query.where('org_id', '==', org_id)

        if start_date:
            query = query.where('date', '>=', start_date)
        if end_date:
            query = query.where('date', '<=', end_date)

        sessions = []
        docs = query.stream()
        for doc in docs:
            sessions.append({'id': doc.id, **doc.to_dict()})

        # Filter by coach in Python to support both coach_id and coach_ids fields
        if coach_id:
            sessions = [s for s in sessions if coach_id in cls.get_session_coach_ids(s)]

        return sessions
    
    @classmethod
    def update_session(cls, session_id, data):
        """Update session"""
        db = cls.get_db()
        doc_ref = db.collection('sessions').document(session_id)
        doc_ref.update(data)
        # Ownership already verified by the caller before calling update.
        return cls.get_session(session_id, None)
    
    @classmethod
    def delete_session(cls, session_id):
        """Delete session"""
        db = cls.get_db()
        db.collection('sessions').document(session_id).delete()
        return True

    @classmethod
    def get_sessions_by_recurrence_group(cls, group_id):
        """Get all sessions sharing a recurrence_group_id."""
        db = cls.get_db()
        docs = db.collection('sessions').where('recurrence_group_id', '==', group_id).stream()
        return [{'id': doc.id, **doc.to_dict()} for doc in docs]
    
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
    def create_check_in_token(cls, token, session_id, expires_at, coach_id=None, org_id=None):
        """Create check-in token, stamped with the session's own org_id.

        Callers mint a token from an already-fetched session, so org_id is
        the session's org_id -- not looked up again here.
        """
        db = cls.get_db()
        data = {
            'token': token,
            'session_id': session_id,
            'created_at': firestore.SERVER_TIMESTAMP,
            'expires_at': expires_at,
            'used': False
        }
        if coach_id:
            data['coach_id'] = coach_id
        if org_id:
            data['org_id'] = org_id
        doc_ref = db.collection('check_in_tokens').document(token)
        doc_ref.set(data)
        return data

    @classmethod
    def get_check_in_token(cls, token):
        """Get check-in token.

        Deliberately unscoped -- this serves a public magic-link endpoint
        hit by an unauthenticated coach on their own phone, where the
        single-use, time-limited token itself is the authorization, not
        org membership. Do not add an org_id filter here.
        """
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
    def check_in_session(cls, session_id, check_in_data, org_id, coach_id=None):
        """Update session with check-in data, scoped to org_id.

        When coach_id is provided, stores per-coach check-in under
        coach_check_ins.{coach_id} so multi-coach sessions work correctly.

        org_id is threaded straight through to the internal get_session()
        calls below, which determine session-level status and build the
        return value -- it is not re-derived here. Every caller has one:
        the check-in-token flow passes the token's own org_id; the
        WhatsApp-native GPS flow passes the org_id of the already-resolved
        coach. Pass org_id=None only for the intentional super_admin
        cross-org case, matching every other org-scoped getter in this
        class.
        """
        db = cls.get_db()
        location_verified = check_in_data.get('location_verified', False)
        location = check_in_data.get('location', {})

        update_data = {
            'check_in_time': firestore.SERVER_TIMESTAMP,
            'check_in_location': location,
            'location_verified': location_verified,
        }

        if coach_id:
            update_data[f'coach_check_ins.{coach_id}'] = {
                'check_in_time': firestore.SERVER_TIMESTAMP,
                'location': location,
                'location_verified': location_verified,
                'distance': check_in_data.get('distance'),
            }

        # Determine session-level status.
        session = cls.get_session(session_id, org_id)
        all_coach_ids = cls.get_session_coach_ids(session) if session else []

        if len(all_coach_ids) <= 1 or not coach_id:
            # Single-coach or unknown coach — simple status
            update_data['status'] = 'checked_in' if location_verified else 'missed'
        else:
            # Multi-coach: check if all coaches have now checked in
            existing_check_ins = dict(session.get('coach_check_ins', {}) or {})
            existing_check_ins[coach_id] = True  # count this one
            if all(cid in existing_check_ins for cid in all_coach_ids):
                update_data['status'] = 'checked_in'
            else:
                # Not all coaches have checked in yet, but at least one has —
                # this is a real check-in, not a missed session.
                update_data['status'] = 'checked_in'

        doc_ref = db.collection('sessions').document(session_id)
        doc_ref.update(update_data)
        return cls.get_session(session_id, org_id)

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
        return cls.get_team(doc_ref.id, data.get('org_id'))

    @classmethod
    def get_team(cls, team_id, org_id):
        """Get team by ID, scoped to org_id.

        Returns None (treated as not found) if the team belongs to a
        different org. Pass org_id=None only for the intentional super_admin
        cross-org case, or for internal callers that already verified
        ownership.
        """
        db = cls.get_db()
        doc = db.collection('teams').document(team_id).get()
        if not doc.exists:
            return None
        data = {'id': doc.id, **doc.to_dict()}
        if org_id is not None and data.get('org_id') != org_id:
            return None
        return data

    @classmethod
    def get_all_teams(cls, org_id, location_id=None):
        """Get all teams for an org, with optional location filter. Pass
        org_id=None only for the intentional super_admin cross-org case."""
        db = cls.get_db()
        query = db.collection('teams')
        if org_id is not None:
            query = query.where('org_id', '==', org_id)
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
        # Ownership already verified by the caller before calling update.
        return cls.get_team(team_id, None)

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
        return cls.get_player(doc_ref.id, data.get('org_id'))

    @classmethod
    def get_player(cls, player_id, org_id):
        """Get player by ID, scoped to org_id.

        Returns None (treated as not found) if the player belongs to a
        different org. Pass org_id=None only for the intentional super_admin
        cross-org case, or for internal callers that already verified
        ownership.
        """
        db = cls.get_db()
        doc = db.collection('players').document(player_id).get()
        if not doc.exists:
            return None
        data = {'id': doc.id, **doc.to_dict()}
        if org_id is not None and data.get('org_id') != org_id:
            return None
        return data

    @classmethod
    def get_all_players(cls, org_id, team_id=None):
        """Get all players for an org, with optional team filter. Pass
        org_id=None only for the intentional super_admin cross-org case.
        NOTE: combining the org_id equality filter with the team_ids
        array_contains filter may require a Firestore composite index — if
        so, Firestore raises FAILED_PRECONDITION with a direct console link.
        """
        db = cls.get_db()
        query = db.collection('players')
        if org_id is not None:
            query = query.where('org_id', '==', org_id)
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
        # Ownership already verified by the caller before calling update.
        return cls.get_player(player_id, None)

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
        return cls.get_location(doc_ref.id, data.get('org_id'))

    @classmethod
    def get_location(cls, location_id, org_id):
        """Get location by ID, scoped to org_id.

        Returns None (treated as not found) if the location belongs to a
        different org. Pass org_id=None only for the intentional super_admin
        cross-org case, or for internal callers (e.g. check-in-token flows,
        the background scheduler) that already established authorization by
        another means.
        """
        db = cls.get_db()
        doc = db.collection('locations').document(location_id).get()
        if not doc.exists:
            return None
        data = {'id': doc.id, **doc.to_dict()}
        if org_id is not None and data.get('org_id') != org_id:
            return None
        return data

    @classmethod
    def get_all_locations(cls, org_id):
        """Get all locations for an org. Pass org_id=None only for the
        intentional super_admin cross-org case."""
        db = cls.get_db()
        query = db.collection('locations')
        if org_id is not None:
            query = query.where('org_id', '==', org_id)
        locations = []
        docs = query.stream()
        for doc in docs:
            locations.append({'id': doc.id, **doc.to_dict()})
        return locations

    @classmethod
    def update_location(cls, location_id, data):
        """Update location"""
        db = cls.get_db()
        doc_ref = db.collection('locations').document(location_id)
        doc_ref.update(data)
        # Ownership already verified by the caller before calling update.
        return cls.get_location(location_id, None)

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
    def get_all_broadcasts(cls, org_id):
        """Get all broadcasts for an org. Pass org_id=None only for the
        intentional super_admin cross-org case."""
        db = cls.get_db()
        query = db.collection('broadcasts')
        if org_id is not None:
            query = query.where('org_id', '==', org_id)
        broadcasts = []
        docs = query.stream()
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
        return cls.get_content(doc_ref.id, data.get('org_id'))

    @classmethod
    def get_content(cls, content_id, org_id):
        """Get content by ID, scoped to org_id.

        Returns None (treated as not found) if the content belongs to a
        different org. Pass org_id=None only for the intentional super_admin
        cross-org case, or for internal callers that already verified
        ownership.
        """
        db = cls.get_db()
        doc = db.collection('content').document(content_id).get()
        if not doc.exists:
            return None
        data = {'id': doc.id, **doc.to_dict()}
        if org_id is not None and data.get('org_id') != org_id:
            return None
        return data

    @classmethod
    def get_all_content(cls, org_id):
        """Get all content for an org. Pass org_id=None only for the
        intentional super_admin cross-org case."""
        db = cls.get_db()
        query = db.collection('content')
        if org_id is not None:
            query = query.where('org_id', '==', org_id)
        content_list = []
        docs = query.stream()
        for doc in docs:
            content_list.append({'id': doc.id, **doc.to_dict()})
        return content_list

    @classmethod
    def update_content(cls, content_id, data):
        """Update content"""
        db = cls.get_db()
        doc_ref = db.collection('content').document(content_id)
        doc_ref.update(data)
        # Ownership already verified by the caller before calling update.
        return cls.get_content(content_id, None)

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
        return cls.get_url(doc_ref.id, data.get('org_id'))

    @classmethod
    def get_url(cls, url_id, org_id):
        """Get content URL by ID, scoped to org_id.

        Returns None (treated as not found) if the URL belongs to a
        different org. Pass org_id=None only for the intentional super_admin
        cross-org case, or for internal callers that already verified
        ownership.
        """
        db = cls.get_db()
        doc = db.collection('content_urls').document(url_id).get()
        if not doc.exists:
            return None
        data = {'id': doc.id, **doc.to_dict()}
        if org_id is not None and data.get('org_id') != org_id:
            return None
        return data

    @classmethod
    def get_all_urls(cls, org_id):
        """Get all content URLs for an org. Pass org_id=None only for the
        intentional super_admin cross-org case."""
        db = cls.get_db()
        query = db.collection('content_urls')
        if org_id is not None:
            query = query.where('org_id', '==', org_id)
        urls = []
        docs = query.stream()
        for doc in docs:
            urls.append({'id': doc.id, **doc.to_dict()})
        return urls

    @classmethod
    def update_url(cls, url_id, data):
        """Update content URL"""
        db = cls.get_db()
        doc_ref = db.collection('content_urls').document(url_id)
        doc_ref.update(data)
        # Ownership already verified by the caller before calling update.
        return cls.get_url(url_id, None)

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
        return cls.get_reminder(doc_ref.id, data.get('org_id'))

    @classmethod
    def get_reminder(cls, reminder_id, org_id):
        """Get reminder by ID, scoped to org_id.

        Returns None (treated as not found) if the reminder belongs to a
        different org. Pass org_id=None only for the intentional super_admin
        cross-org case, or for internal callers that already verified
        ownership.
        """
        db = cls.get_db()
        doc = db.collection('reminders').document(reminder_id).get()
        if not doc.exists:
            return None
        data = {'id': doc.id, **doc.to_dict()}
        if org_id is not None and data.get('org_id') != org_id:
            return None
        return data

    @classmethod
    def get_all_reminders(cls, org_id):
        """Get all reminders for an org. Pass org_id=None only for the
        intentional super_admin cross-org case."""
        db = cls.get_db()
        query = db.collection('reminders')
        if org_id is not None:
            query = query.where('org_id', '==', org_id)
        reminders = []
        docs = query.stream()
        for doc in docs:
            reminders.append({'id': doc.id, **doc.to_dict()})
        return reminders

    @classmethod
    def update_reminder(cls, reminder_id, data):
        """Update reminder"""
        db = cls.get_db()
        doc_ref = db.collection('reminders').document(reminder_id)
        doc_ref.update(data)
        # Ownership already verified by the caller before calling update.
        return cls.get_reminder(reminder_id, None)

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
        return cls.get_admin(doc_ref.id, data.get('org_id'))

    @staticmethod
    def _strip_admin_password(admin_dict):
        """Remove password from admin dict before returning to callers."""
        if admin_dict:
            admin_dict.pop('password', None)
            admin_dict.pop('password_hash', None)
        return admin_dict

    @classmethod
    def get_admin(cls, admin_id, org_id):
        """Get admin user by ID (password stripped), scoped to org_id.

        Returns None (treated as not found) if the admin belongs to a
        different org. Pass org_id=None only for the intentional super_admin
        cross-org case, or for internal callers that already verified
        ownership.
        """
        db = cls.get_db()
        doc = db.collection('admin_users').document(admin_id).get()
        if not doc.exists:
            return None
        data = {'id': doc.id, **doc.to_dict()}
        if org_id is not None and data.get('org_id') != org_id:
            return None
        return cls._strip_admin_password(data)

    @classmethod
    def get_admin_by_email(cls, email, include_password=False):
        """Get admin user by email. Set include_password=True for auth checks only."""
        db = cls.get_db()
        docs = db.collection('admin_users').where('email', '==', email).limit(1).stream()
        for doc in docs:
            data = {'id': doc.id, **doc.to_dict()}
            return data if include_password else cls._strip_admin_password(data)
        return None

    @classmethod
    def get_all_admins(cls):
        """Get all admin users (passwords stripped)"""
        db = cls.get_db()
        admins = []
        docs = db.collection('admin_users').stream()
        for doc in docs:
            admins.append(cls._strip_admin_password({'id': doc.id, **doc.to_dict()}))
        return admins

    @classmethod
    def update_admin(cls, admin_id, data):
        """Update admin user"""
        db = cls.get_db()
        doc_ref = db.collection('admin_users').document(admin_id)
        doc_ref.update(data)
        # Ownership already verified by the caller before calling update.
        return cls.get_admin(admin_id, None)

    @classmethod
    def delete_admin(cls, admin_id):
        """Delete admin user"""
        db = cls.get_db()
        db.collection('admin_users').document(admin_id).delete()
        return True

    @classmethod
    def get_all_admins_by_org(cls, org_id):
        """Get all admin users for a given org (passwords stripped)."""
        db = cls.get_db()
        admins = []
        docs = db.collection('admin_users').where('org_id', '==', org_id).stream()
        for doc in docs:
            admins.append(cls._strip_admin_password({'id': doc.id, **doc.to_dict()}))
        return admins

    @classmethod
    def create_admin_invite(cls, data):
        """Create a pending admin invite in the `invites` collection.

        Generates a single-use token and a 48-hour expiry. Expects
        email, role, org_id and invited_by in `data`. Returns the created
        invite (including its token) so the caller can build the invite link.
        """
        db = cls.get_db()
        invite = {
            'email': data.get('email'),
            'role': data.get('role'),
            'org_id': data.get('org_id'),
            'invited_by': data.get('invited_by'),
            'token': secrets.token_hex(16),  # 32-char hex string
            'expires_at': (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat(),
            'accepted': False,
            'created_at': firestore.SERVER_TIMESTAMP,
        }
        doc_ref = db.collection('invites').document()
        doc_ref.set(invite)
        return {'id': doc_ref.id, **invite}

    # =========================================================================
    # Organisation operations (collection: 'organisations')
    # =========================================================================
    # Default terminology per org type, mirrors DEFAULT_TERMINOLOGY_BY_TYPE on
    # the frontend (frontend/src/types/Organisation.ts) and the
    # DEFAULT_AI_PERSONA_PROMPTS pattern in ConversationService — each org
    # type gets labels that don't read as sports-specific.
    DEFAULT_TERMINOLOGY_BY_TYPE = {
        "sports": {
            "coach_singular": "Coach",
            "coach_plural": "Coaches",
            "player_singular": "Player",
            "player_plural": "Players",
            "team_singular": "Team",
            "team_plural": "Teams",
            "session_singular": "Session",
            "session_plural": "Sessions",
            "location_singular": "Location",
            "location_plural": "Locations",
        },
        "ngo": {
            "coach_singular": "Facilitator",
            "coach_plural": "Facilitators",
            "player_singular": "Participant",
            "player_plural": "Participants",
            "team_singular": "Group",
            "team_plural": "Groups",
            "session_singular": "Session",
            "session_plural": "Sessions",
            "location_singular": "Venue",
            "location_plural": "Venues",
        },
        "events": {
            "coach_singular": "Coach",
            "coach_plural": "Coaches",
            "player_singular": "Attendee",
            "player_plural": "Attendees",
            "team_singular": "Team",
            "team_plural": "Teams",
            "session_singular": "Session",
            "session_plural": "Sessions",
            "location_singular": "Venue",
            "location_plural": "Venues",
        },
        "corporate": {
            "coach_singular": "Facilitator",
            "coach_plural": "Facilitators",
            "player_singular": "Participant",
            "player_plural": "Participants",
            "team_singular": "Team",
            "team_plural": "Teams",
            "session_singular": "Session",
            "session_plural": "Sessions",
            "location_singular": "Venue",
            "location_plural": "Venues",
        },
    }

    # Final catch-all fallback for a missing/unrecognized org type.
    DEFAULT_TERMINOLOGY = DEFAULT_TERMINOLOGY_BY_TYPE["sports"]

    # Default country + supported-language set, used by
    # ConversationService.DEFAULT_AI_PERSONA_PROMPTS so the AI persona
    # doesn't hardcode South Africa for every org. These are exactly the
    # values every org implicitly had before country/supported_languages
    # existed as org fields, so an org that hasn't set its own (e.g. CATCH
    # Trust) sees no change in behaviour — see get_org_locale.
    DEFAULT_COUNTRY = "South Africa"
    DEFAULT_SUPPORTED_LANGUAGES = [
        "Afrikaans", "English", "isiNdebele", "isiXhosa", "isiZulu",
        "Sepedi", "Sesotho", "Setswana", "siSwati", "Tshivenda", "Xitsonga",
    ]

    @classmethod
    def get_organisation(cls, org_id):
        """Get a single organisation by ID."""
        db = cls.get_db()
        doc = db.collection('organisations').document(org_id).get()
        if doc.exists:
            return {'id': doc.id, **doc.to_dict()}
        return None

    @classmethod
    def get_organisation_by_slug(cls, slug):
        """Get an organisation by its slug field."""
        db = cls.get_db()
        docs = db.collection('organisations').where('slug', '==', slug).limit(1).stream()
        for doc in docs:
            return {'id': doc.id, **doc.to_dict()}
        return None

    @classmethod
    def get_all_organisations(cls):
        """Get all organisations."""
        db = cls.get_db()
        orgs = []
        for doc in db.collection('organisations').stream():
            orgs.append({'id': doc.id, **doc.to_dict()})
        return orgs

    @classmethod
    def create_organisation(cls, data):
        """Create a new organisation document.

        Fields: name, slug, type, terminology, ai_persona_prompt, country,
        supported_languages, is_active, created_at. ai_persona_prompt is
        optional — when empty/absent, the AI system prompt falls back to
        the default for the org's type (see
        ConversationService.get_ai_persona_prompt). country/
        supported_languages are also optional and fall back to the South
        African defaults (see get_org_locale) — same shape as terminology.
        """
        db = cls.get_db()
        data['created_at'] = firestore.SERVER_TIMESTAMP
        doc_ref = db.collection('organisations').document()
        doc_ref.set(data)
        return cls.get_organisation(doc_ref.id)

    @classmethod
    def update_organisation(cls, org_id, data):
        """Update organisation fields."""
        db = cls.get_db()
        doc_ref = db.collection('organisations').document(org_id)
        doc_ref.update(data)
        return cls.get_organisation(org_id)

    @classmethod
    def get_org_terminology(cls, org_id):
        """Get the terminology for an org, falling back to defaults.

        Priority: saved org terminology > default for the org's type >
        the sports default as a final catch-all (org missing or type
        unrecognized). Any key missing from the saved terminology is filled
        from the applicable default so callers always receive the full set
        of 10 labels.
        """
        org = cls.get_organisation(org_id)
        org_type = org.get('type') if org else None
        type_default = cls.DEFAULT_TERMINOLOGY_BY_TYPE.get(org_type, cls.DEFAULT_TERMINOLOGY)
        if org and org.get('terminology'):
            return {**type_default, **org['terminology']}
        return dict(type_default)

    @classmethod
    def get_org_locale(cls, org_id):
        """Get the country + supported-languages config for an org, falling
        back to DEFAULT_COUNTRY/DEFAULT_SUPPORTED_LANGUAGES (the South
        African values every org implicitly had before these were
        configurable) when the org hasn't set its own. Same fallback shape
        as get_org_terminology: saved org value > default.

        Always returns a fresh list for supported_languages — never the
        literal DEFAULT_SUPPORTED_LANGUAGES object — so a caller can never
        mutate the shared module-level default in place (the exact bug
        class fixed in routes/broadcasts.py's pricing defaults).
        """
        org = cls.get_organisation(org_id) if org_id else None
        country = (org.get('country') if org else None) or cls.DEFAULT_COUNTRY
        languages = (org.get('supported_languages') if org else None) or cls.DEFAULT_SUPPORTED_LANGUAGES
        return {'country': country, 'supported_languages': list(languages)}

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
    def get_sessions_by_date_range(cls, org_id, start_date, end_date):
        """Get sessions within a date range for reports, scoped to org_id.

        Pass org_id=None only for the intentional super_admin cross-org case.
        NOTE: combining the org_id equality filter with the date range below
        may require a Firestore composite index (org_id ASC, date ASC) — if
        so, Firestore raises FAILED_PRECONDITION with a direct console link.
        This is the same shape of query as get_all_sessions' date-range
        filter, so a single composite index should cover both.
        """
        db = cls.get_db()
        query = db.collection('sessions')
        if org_id is not None:
            query = query.where('org_id', '==', org_id)
        sessions = []
        docs = query.where('date', '>=', start_date).where('date', '<=', end_date).stream()
        for doc in docs:
            sessions.append({'id': doc.id, **doc.to_dict()})
        return sessions

    @classmethod
    def count_players(cls, org_id):
        """Count total players for an org. Pass org_id=None only for the
        intentional super_admin cross-org case."""
        db = cls.get_db()
        query = db.collection('players')
        if org_id is not None:
            query = query.where('org_id', '==', org_id)
        count = 0
        for _ in query.stream():
            count += 1
        return count

    @classmethod
    def count_active_coaches(cls, org_id):
        """Count active coaches for an org. Pass org_id=None only for the
        intentional super_admin cross-org case."""
        db = cls.get_db()
        query = db.collection('coaches')
        if org_id is not None:
            query = query.where('org_id', '==', org_id)
        count = 0
        for _ in query.stream():
            count += 1
        return count
