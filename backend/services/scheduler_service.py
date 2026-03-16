from services.firebase_service import FirebaseService
from services.whatsapp_service import WhatsAppService
from datetime import datetime, timedelta, timezone
from config import Config
from utils.phone import normalize_sa_phone
import uuid

# South Africa Standard Time (UTC+2) — sessions are stored in local time
SAST = timezone(timedelta(hours=2))

class SchedulerService:
    """Service for scheduling and sending session reminders"""

    @classmethod
    def check_and_send_reminders(cls):
        """Check for sessions that need reminders and send them

        This should be called periodically (e.g., every minute) by a scheduler
        like Cloud Scheduler or a cron job.
        """
        try:
            # Get current time in SAST (sessions are stored in local SA time)
            now = datetime.now(SAST).replace(tzinfo=None)

            # Calculate target time (X minutes from now)
            target_time = now + timedelta(minutes=Config.REMINDER_MINUTES_BEFORE)

            # Get all scheduled sessions
            sessions = FirebaseService.get_sessions_for_reminder(target_time)

            reminders_sent = 0
            errors = []

            for session in sessions:
                try:
                    # Parse session date and time
                    session_date = session.get('date', '')
                    session_start = session.get('start_time', '')
                    if not session_date or not session_start:
                        errors.append(f"Session {session.get('id', 'unknown')} missing date or start_time — skipped")
                        continue

                    session_datetime_str = f"{session_date} {session_start}"
                    session_datetime = datetime.strptime(session_datetime_str, "%Y-%m-%d %H:%M")

                    # Check if session is within the reminder window
                    time_diff = (session_datetime - now).total_seconds() / 60

                    # Skip sessions already reminded
                    if session.get('status') == 'reminded':
                        continue

                    # Window: from REMINDER_MINUTES_BEFORE down to 0 (session start)
                    # This ensures reminders are sent even if scheduler runs infrequently
                    if 0 <= time_diff <= Config.REMINDER_MINUTES_BEFORE + 1:
                        # Get all coaches for this session
                        coach_ids = FirebaseService.get_session_coach_ids(session)
                        if not coach_ids:
                            errors.append(f"No coach assigned to session {session['id']}")
                            continue

                        # Resolve location — maps link is source of truth
                        location_address = ''
                        location_id = session.get('location_id')
                        if location_id:
                            loc = FirebaseService.get_location(location_id)
                            if loc:
                                from services.conversation_service import format_maps_link
                                maps_link = format_maps_link(loc.get('latitude'), loc.get('longitude'))
                                loc_name = loc.get('name', '')
                                if maps_link:
                                    location_address = f"{loc_name} {maps_link}".strip() if loc_name else maps_link
                                else:
                                    location_address = loc_name or loc.get('address', '') or session.get('address', '')
                        if not location_address:
                            location_address = session.get('address', '') or 'TBC'

                        sent_any = False
                        for coach_id in coach_ids:
                            coach = FirebaseService.get_coach(coach_id)
                            if not coach:
                                errors.append(f"Coach {coach_id} not found for session {session['id']}")
                                continue

                            coach_name = coach.get('name') or f"{coach.get('first_name', '')} {coach.get('last_name', '')}".strip() or 'Coach'
                            phone = normalize_sa_phone(coach.get('phone_number', ''))
                            if not phone:
                                errors.append(f"Invalid/missing phone for coach {coach_name} (session {session['id']})")
                                continue

                            token = str(uuid.uuid4())
                            # Token expiry uses UTC (consistent with check-in verification)
                            expires_at = datetime.now(timezone.utc) + timedelta(minutes=Config.CHECK_IN_TOKEN_EXPIRY_MINUTES)
                            FirebaseService.create_check_in_token(token, session['id'], expires_at)
                            check_in_url = f"{Config.FRONTEND_URL}/check-in/{token}"

                            result = WhatsAppService.send_check_in_reminder(
                                coach_phone=phone,
                                coach_name=coach_name,
                                session_time=session.get('start_time', ''),
                                location_address=location_address,
                                check_in_url=check_in_url
                            )

                            if result.get('success'):
                                sent_any = True
                                reminders_sent += 1
                            else:
                                errors.append(f"Failed to send reminder to {coach_name} for session {session['id']}: {result.get('error')}")

                        if sent_any:
                            FirebaseService.update_session(session['id'], {'status': 'reminded'})

                except Exception as e:
                    errors.append(f"Error processing session {session.get('id', 'unknown')}: {str(e)}")

            return {
                'success': True,
                'reminders_sent': reminders_sent,
                'errors': errors
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'reminders_sent': 0
            }

    @classmethod
    def mark_missed_sessions(cls):
        """Mark sessions as missed if they haven't been checked in after session time

        This should be run periodically (e.g., every hour) to update session statuses.
        """
        try:
            now = datetime.now(SAST).replace(tzinfo=None)

            # Get only reminded sessions (avoids loading entire history)
            db = FirebaseService.get_db()
            docs = db.collection('sessions').where('status', '==', 'reminded').stream()
            sessions = [{'id': doc.id, **doc.to_dict()} for doc in docs]

            updated = 0

            for session in sessions:
                # Parse session end time (fall back to start_time + 2h if no end_time)
                session_date = session.get('date', '')
                session_end = session.get('end_time', '')
                session_start = session.get('start_time', '')
                if not session_date or (not session_end and not session_start):
                    continue

                try:
                    if session_end:
                        session_end_time = datetime.strptime(f"{session_date} {session_end}", "%Y-%m-%d %H:%M")
                    else:
                        # No end time — assume 2 hours after start
                        session_end_time = datetime.strptime(f"{session_date} {session_start}", "%Y-%m-%d %H:%M") + timedelta(hours=2)
                except ValueError:
                    continue

                # If session end time has passed, mark as missed
                if now > session_end_time:
                    FirebaseService.update_session(session['id'], {'status': 'missed'})
                    updated += 1

            return {
                'success': True,
                'sessions_marked_missed': updated
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'sessions_marked_missed': 0
            }
