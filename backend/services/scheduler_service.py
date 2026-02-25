from services.firebase_service import FirebaseService
from services.whatsapp_service import WhatsAppService
from datetime import datetime, timedelta
from config import Config
import uuid

class SchedulerService:
    """Service for scheduling and sending session reminders"""
    
    @classmethod
    def check_and_send_reminders(cls):
        """Check for sessions that need reminders and send them
        
        This should be called periodically (e.g., every minute) by a scheduler
        like Cloud Scheduler or a cron job.
        """
        try:
            # Get current time
            now = datetime.utcnow()
            
            # Calculate target time (X minutes from now)
            target_time = now + timedelta(minutes=Config.REMINDER_MINUTES_BEFORE)
            
            # Get all scheduled sessions
            sessions = FirebaseService.get_sessions_for_reminder(target_time)
            
            reminders_sent = 0
            errors = []
            
            for session in sessions:
                try:
                    # Parse session date and time
                    session_datetime_str = f"{session['date']} {session['start_time']}"
                    session_datetime = datetime.strptime(session_datetime_str, "%Y-%m-%d %H:%M")
                    
                    # Check if session is approximately X minutes away
                    time_diff = (session_datetime - now).total_seconds() / 60
                    
                    # If within the reminder window (e.g., 9-11 minutes before)
                    if Config.REMINDER_MINUTES_BEFORE - 1 <= time_diff <= Config.REMINDER_MINUTES_BEFORE + 1:
                        # Get coach information
                        coach = FirebaseService.get_coach(session['coach_id'])
                        
                        if not coach:
                            errors.append(f"Coach not found for session {session['id']}")
                            continue
                        
                        # Generate check-in token
                        token = str(uuid.uuid4())
                        expires_at = now + timedelta(minutes=Config.CHECK_IN_TOKEN_EXPIRY_MINUTES)
                        
                        FirebaseService.create_check_in_token(token, session['id'], expires_at)
                        
                        # Generate check-in URL
                        check_in_url = f"{Config.FRONTEND_URL}/check-in/{token}"
                        
                        # Send WhatsApp reminder
                        result = WhatsAppService.send_check_in_reminder(
                            coach_phone=coach['phone_number'],
                            coach_name=coach['name'],
                            session_time=session['start_time'],
                            location_address=session['address'],
                            check_in_url=check_in_url
                        )
                        
                        if result.get('success'):
                            # Update session status to 'reminded'
                            FirebaseService.update_session(session['id'], {'status': 'reminded'})
                            reminders_sent += 1
                        else:
                            errors.append(f"Failed to send reminder for session {session['id']}: {result.get('error')}")
                
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
            now = datetime.utcnow()
            
            # Get all reminded sessions
            sessions = FirebaseService.get_all_sessions()
            
            updated = 0
            
            for session in sessions:
                if session.get('status') == 'reminded':
                    # Parse session end time
                    session_datetime_str = f"{session['date']} {session['end_time']}"
                    session_end_time = datetime.strptime(session_datetime_str, "%Y-%m-%d %H:%M")
                    
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
