from services.firebase_service import FirebaseService
from services.gemini_service import GeminiService
from services.whatsapp_service import WhatsAppService
from datetime import datetime, date
import uuid
import re

class ConversationService:
    """Service for managing AI conversations with coaches via WhatsApp"""
    
    CRICKET_COACHING_PROMPT = """You are a professional cricket coaching specialist assistant helping coaches in South Africa.

EXPERTISE:
- Cricket techniques: Batting (grip, stance, footwork, shots), Bowling (grip, action, variations), Fielding (catching, throwing, positioning)
- Coaching methodologies and player development
- Training drills and practice sessions
- Match strategy, tactics, and field placements
- Physical fitness and conditioning for cricket
- Mental preparation and sports psychology
- Youth cricket development (U10 to U19)
- South African cricket context (facilities, weather, conditions)

YOUR ROLE:
- Provide practical, actionable coaching advice
- Suggest specific drills and exercises
- Explain techniques clearly and simply
- Consider the coach's level and resources
- Be encouraging and supportive

COMMUNICATION STYLE:
- Professional but friendly
- Concise responses (suitable for WhatsApp)
- Use bullet points and numbered lists
- Include practical examples
- Ask clarifying questions when needed

LANGUAGE:
- Detect and respond in the SAME language the coach uses
- Support all 11 official South African languages:
  * Afrikaans, English
  * isiNdebele, isiXhosa, isiZulu
  * Sepedi, Sesotho, Setswana
  * siSwati, Tshivenda, Xitsonga

CONSTRAINTS:
- Keep responses under 1000 characters when possible
- Focus on cricket coaching and the coach's team/schedule
- If asked about non-cricket topics, politely redirect
- When the coach asks about their team, players, or schedule, use the data provided
- Don't provide medical advice, refer to professionals

Remember: You're helping coaches develop their skills and help their players improve."""

    @classmethod
    def get_conversation_history(cls, coach_phone, limit=10):
        """Get recent conversation history for a coach"""
        db = FirebaseService.get_db()
        
        # Format phone number
        phone_key = coach_phone.replace('+', '').replace(' ', '').replace('-', '')
        
        try:
            # Get messages from Firestore
            messages_ref = db.collection('conversations').document(phone_key).collection('messages')
            messages = messages_ref.order_by('timestamp', direction='DESCENDING').limit(limit).stream()
            
            history = []
            for msg in messages:
                msg_data = msg.to_dict()
                history.append({
                    'role': msg_data.get('role'),
                    'content': msg_data.get('content'),
                    'timestamp': msg_data.get('timestamp')
                })
            
            # Reverse to get chronological order (oldest first)
            history.reverse()
            return history
        except Exception as e:
            print(f"Error loading conversation history: {e}")
            return []
    
    @classmethod
    def strip_markdown(cls, text):
        """Remove markdown formatting from text for WhatsApp
        
        Args:
            text: Text with markdown formatting
            
        Returns:
            str: Plain text without markdown
        """
        # Remove bold/italic markers (* or **)
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # **bold**
        text = re.sub(r'\*([^*]+)\*', r'\1', text)      # *italic*
        text = re.sub(r'__([^_]+)__', r'\1', text)      # __bold__
        text = re.sub(r'_([^_]+)_', r'\1', text)        # _italic_
        
        # Convert markdown bullet points to simple dashes
        text = re.sub(r'^\s*[\*\-\+]\s+', '- ', text, flags=re.MULTILINE)
        
        # Remove markdown headers (##, ###, etc.) but keep the text
        text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
        
        # Convert numbered lists (1., 2., etc.) to consistent format
        text = re.sub(r'^\s*(\d+)\.\s+', r'\1. ', text, flags=re.MULTILINE)
        
        return text.strip()
    
    @classmethod
    def save_message(cls, coach_phone, role, content):
        """Save a message to conversation history"""
        db = FirebaseService.get_db()
        
        # Format phone number
        phone_key = coach_phone.replace('+', '').replace(' ', '').replace('-', '')
        
        try:
            message_data = {
                'role': role,  # 'user' or 'assistant'
                'content': content,
                'timestamp': datetime.utcnow(),
                'message_id': str(uuid.uuid4())
            }
            
            db.collection('conversations').document(phone_key).collection('messages').add(message_data)
            print(f"💾 Saved {role} message to conversation history")
        except Exception as e:
            print(f"Error saving message: {e}")
    
    @classmethod
    def load_rag_context(cls):
        """Load all content and URLs from Firestore for RAG context"""
        try:
            content_items = FirebaseService.get_all_content()
            url_items = FirebaseService.get_all_urls()

            sections = []

            # Add text content
            for item in content_items:
                text = (item.get('content_text') or '').strip()
                if not text:
                    continue
                title = item.get('title', 'Untitled')
                topic = item.get('topic', '')
                header = f"[Document: {title}]"
                if topic:
                    header += f" (Topic: {topic})"
                # Truncate very long content to keep prompt manageable
                if len(text) > 3000:
                    text = text[:3000] + '... (truncated)'
                sections.append(f"{header}\n{text}")

            # Add URL resources
            for item in url_items:
                title = item.get('title', '')
                url = item.get('url', '')
                desc = item.get('description', '')
                instructions = item.get('instructions', '')
                parts = [f"[URL Resource: {title}]"]
                if url:
                    parts.append(f"Link: {url}")
                if desc:
                    parts.append(f"Description: {desc}")
                if instructions:
                    parts.append(f"Usage instructions: {instructions}")
                sections.append('\n'.join(parts))

            if not sections:
                return ''

            return (
                "KNOWLEDGE BASE (use this information to help answer questions):\n"
                + "\n\n---\n\n".join(sections)
                + "\n\nEND OF KNOWLEDGE BASE\n"
            )
        except Exception as e:
            print(f"⚠️ Error loading RAG context: {e}")
            return ''

    @classmethod
    def load_coach_context(cls, coach_id):
        """Load coach-specific context: their teams, players, and upcoming sessions."""
        if not coach_id:
            return ''
        try:
            from datetime import date as _date
            sections = []

            # Teams this coach belongs to
            all_teams = FirebaseService.get_all_teams()
            coach_teams = [t for t in all_teams if coach_id in (t.get('coach_ids') or [])]

            if coach_teams:
                lines = ["YOUR TEAMS:"]
                for team in coach_teams:
                    team_name = team.get('name', 'Unnamed')
                    age_group = team.get('age_group', '')
                    lines.append(f"- {team_name} ({age_group})" if age_group else f"- {team_name}")

                    # Players in this team
                    players = FirebaseService.get_all_players(team_id=team.get('id'))
                    if players:
                        for p in players:
                            pname = (p.get('first_name', '') + ' ' + p.get('last_name', '')).strip() or p.get('name', 'Unknown')
                            lines.append(f"  - {pname}")
                    else:
                        lines.append("  (no players registered yet)")
                sections.append('\n'.join(lines))

            # Upcoming sessions (today and future)
            today_str = _date.today().strftime('%Y-%m-%d')
            sessions = FirebaseService.get_all_sessions(coach_id=coach_id, start_date=today_str)
            if sessions:
                sessions.sort(key=lambda s: (s.get('date', ''), s.get('start_time', '')))
                lines = ["YOUR UPCOMING SESSIONS:"]
                for s in sessions[:5]:
                    s_date = s.get('date', '')
                    s_time = s.get('start_time', '')
                    s_type = s.get('type', 'practice').capitalize()
                    s_status = s.get('status', '')
                    location = s.get('address', '') or s.get('location_name', '')
                    line = f"- {s_date} {s_time} | {s_type}"
                    if location:
                        line += f" at {location}"
                    if s_status:
                        line += f" [{s_status}]"
                    lines.append(line)
                sections.append('\n'.join(lines))

            if not sections:
                return ''
            return '\n\n'.join(sections) + '\n'
        except Exception as e:
            print(f"Error loading coach context: {e}")
            return ''

    @classmethod
    def generate_response(cls, coach_phone, user_message, coach_name=None, coach_id=None):
        """Generate AI response to coach's message using RAG context"""
        try:
            # Get conversation history
            history = cls.get_conversation_history(coach_phone, limit=5)

            # Load RAG content
            rag_context = cls.load_rag_context()

            # Load coach-specific context (teams, players, sessions)
            coach_context = cls.load_coach_context(coach_id)

            # Build context for Gemini
            context = cls.CRICKET_COACHING_PROMPT + "\n\n"

            if rag_context:
                context += rag_context + "\n"
                context += (
                    "IMPORTANT: When answering questions, use the knowledge base above "
                    "as your primary source. If a URL resource is relevant, share the link. "
                    "If the knowledge base doesn't cover the topic, use your general knowledge.\n\n"
                )

            if coach_name:
                context += f"You are chatting with Coach {coach_name}.\n\n"

            if coach_context:
                context += coach_context + "\n"
                context += (
                    "Use the coach's team, player, and session information above to give "
                    "personalised answers. When the coach asks about their team or players, "
                    "refer to this data.\n\n"
                )

            context += "Recent conversation:\n"
            for msg in history:
                role_label = "Coach" if msg['role'] == 'user' else "You"
                context += f"{role_label}: {msg['content']}\n"

            context += f"\nCoach: {user_message}\nYou:"

            # Generate response using Gemini
            response = GeminiService.generate_custom_message(context)

            # Strip markdown formatting for WhatsApp
            clean_response = cls.strip_markdown(response)

            # Save both messages to history
            cls.save_message(coach_phone, 'user', user_message)
            cls.save_message(coach_phone, 'assistant', clean_response)

            return clean_response

        except Exception as e:
            print(f"Error generating response: {e}")
            return "I apologize, I'm having trouble responding right now. Please try again in a moment. 🏏"
    
    # ── Attendance via WhatsApp ──────────────────────────────────────────

    @classmethod
    def _phone_key(cls, phone):
        return phone.replace('+', '').replace(' ', '').replace('-', '')

    @classmethod
    def get_pending_attendance(cls, coach_phone):
        """Check if a coach has a pending attendance request"""
        db = FirebaseService.get_db()
        key = cls._phone_key(coach_phone)
        try:
            doc = db.collection('pending_attendance').document(key).get()
            if doc.exists:
                data = doc.to_dict()
                # Expire after 30 minutes
                created = data.get('created_at')
                if created:
                    from datetime import timezone
                    now = datetime.now(timezone.utc)
                    if hasattr(created, 'timestamp'):
                        created_ts = created.timestamp()
                    else:
                        created_ts = created.replace(tzinfo=timezone.utc).timestamp()
                    if (now.timestamp() - created_ts) > 1800:
                        cls.clear_pending_attendance(coach_phone)
                        return None
                return data
            return None
        except Exception as e:
            print(f"⚠️ Error reading pending attendance: {e}")
            return None

    @classmethod
    def set_pending_attendance(cls, coach_phone, session_id, players):
        """Store pending attendance state for a coach"""
        db = FirebaseService.get_db()
        key = cls._phone_key(coach_phone)
        db.collection('pending_attendance').document(key).set({
            'session_id': session_id,
            'players': players,  # [{id, name, number}, ...]
            'created_at': datetime.utcnow()
        })

    @classmethod
    def clear_pending_attendance(cls, coach_phone):
        """Clear pending attendance state"""
        db = FirebaseService.get_db()
        key = cls._phone_key(coach_phone)
        try:
            db.collection('pending_attendance').document(key).delete()
        except Exception:
            pass

    @classmethod
    def handle_attendance_command(cls, coach):
        """Handle /attendance command — find today's session and send player list"""
        try:
            return cls._handle_attendance_command_inner(coach)
        except Exception as e:
            print(f"❌ Attendance command error: {e}")
            import traceback
            traceback.print_exc()
            return f"Something went wrong loading attendance. Please try again or contact your administrator."

    @classmethod
    def _handle_attendance_command_inner(cls, coach):
        coach_id = coach.get('id')
        today_str = date.today().strftime('%Y-%m-%d')
        print(f"📋 Attendance command from coach {coach.get('name')} (id={coach_id}) for {today_str}")

        # Query by coach_id only to avoid Firestore composite index requirement,
        # then filter by date in Python
        all_coach_sessions = FirebaseService.get_all_sessions(coach_id=coach_id)
        sessions = [s for s in all_coach_sessions if s.get('date') == today_str and s.get('team_id')]
        print(f"📋 Found {len(sessions)} session(s) with teams for today (out of {len(all_coach_sessions)} total)")

        if not sessions:
            return "You don't have any sessions with a team scheduled for today. 📋"

        # Pick the session (if multiple, pick the earliest by start_time)
        sessions.sort(key=lambda s: s.get('start_time', ''))
        session = sessions[0]
        team_id = session['team_id']

        # Check if attendance already recorded
        if session.get('attended_player_ids') is not None and len(session.get('attended_player_ids', [])) > 0:
            return (
                "Attendance has already been recorded for today's session. ✅\n\n"
                "Send /attendance-redo to record it again."
            )

        team = FirebaseService.get_team(team_id)
        team_name = team.get('name', 'your team') if team else 'your team'

        players = FirebaseService.get_all_players(team_id=team_id)
        if not players:
            return f"No players found for {team_name}. Please contact your administrator."

        # Sort players alphabetically
        players.sort(key=lambda p: (p.get('first_name', '') + ' ' + p.get('last_name', '')).strip().lower())

        # Build numbered list
        player_list = []
        for i, p in enumerate(players, 1):
            name = (p.get('first_name', '') + ' ' + p.get('last_name', '')).strip() or p.get('name', f'Player {i}')
            player_list.append({'id': p['id'], 'name': name, 'number': i})

        # Store pending state
        cls.set_pending_attendance(
            coach.get('phone_number', ''),
            session['id'],
            player_list
        )

        # Build message
        session_time = session.get('start_time', '')
        session_type = session.get('type', 'practice').capitalize()
        lines = [f"📋 *{team_name}* — {session_type} ({today_str}, {session_time})\n"]
        lines.append("Reply with the *numbers of ABSENT players*.")
        lines.append("Example: 2 5 8\n")
        for p in player_list:
            lines.append(f"{p['number']}. {p['name']}")
        lines.append("")
        lines.append("Or reply *all* if everyone is present.")
        lines.append("Reply *cancel* to abort.")

        return '\n'.join(lines)

    @classmethod
    def handle_attendance_response(cls, coach_phone, message_text, pending):
        """Process coach's reply with absent player numbers"""
        text = message_text.strip().lower()
        players = pending['players']
        session_id = pending['session_id']

        if text == 'cancel':
            cls.clear_pending_attendance(coach_phone)
            return "Attendance cancelled. ❌"

        if text in ['all', 'all present', 'none absent', '0']:
            # Everyone present
            attended_ids = [p['id'] for p in players]
            absent_names = []
            present_names = [p['name'] for p in players]
        else:
            # Parse absent numbers
            absent_numbers = set()
            for part in re.split(r'[\s,]+', text):
                part = part.strip()
                if part.isdigit():
                    absent_numbers.add(int(part))

            if not absent_numbers:
                return (
                    "I didn't understand that. Please reply with:\n"
                    "- Numbers of absent players (e.g. 2 5 8)\n"
                    "- *all* if everyone is present\n"
                    "- *cancel* to abort"
                )

            # Validate numbers
            max_num = len(players)
            invalid = [n for n in absent_numbers if n < 1 or n > max_num]
            if invalid:
                return f"Invalid number(s): {', '.join(str(n) for n in invalid)}. Please use numbers 1-{max_num}."

            attended_ids = []
            absent_names = []
            present_names = []
            for p in players:
                if p['number'] in absent_numbers:
                    absent_names.append(p['name'])
                else:
                    attended_ids.append(p['id'])
                    present_names.append(p['name'])

        # Save to Firestore
        try:
            FirebaseService.update_session(session_id, {
                'attended_player_ids': attended_ids
            })
        except Exception as e:
            print(f"❌ Error saving attendance: {e}")
            return "Failed to save attendance. Please try again. 🏏"

        cls.clear_pending_attendance(coach_phone)

        # Build confirmation
        total = len(players)
        present_count = len(present_names)
        absent_count = len(absent_names)
        lines = [f"✅ Attendance recorded! ({present_count}/{total} present)\n"]
        if absent_names:
            lines.append(f"Absent ({absent_count}):")
            for name in absent_names:
                lines.append(f"  ✗ {name}")
        else:
            lines.append("Everyone is present! 🎉")

        return '\n'.join(lines)

    @classmethod
    def handle_attendance_redo(cls, coach):
        """Allow re-recording attendance for today's session"""
        coach_id = coach.get('id')
        today_str = date.today().strftime('%Y-%m-%d')
        all_coach_sessions = FirebaseService.get_all_sessions(coach_id=coach_id)
        sessions = [s for s in all_coach_sessions if s.get('date') == today_str]
        if not sessions:
            return "You don't have any sessions scheduled for today. 📋"

        sessions.sort(key=lambda s: s.get('start_time', ''))
        session = sessions[0]

        # Clear existing attendance so the command proceeds
        FirebaseService.update_session(session['id'], {'attended_player_ids': []})

        # Now run the normal attendance flow
        return cls.handle_attendance_command(coach)

    # ── WhatsApp location check-in ───────────────────────────────────────

    @classmethod
    def handle_location_check_in(cls, from_number, latitude, longitude, message_id=None):
        """Handle a shared WhatsApp location for coach check-in"""
        from utils.geolocation import verify_location, format_location, extract_coords_from_maps_url, geocode_address
        try:
            print(f"📍 Location received from {from_number}: lat={latitude}, lng={longitude}")

            coach = cls.get_coach_by_phone(from_number)
            if not coach:
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text="Hello! To use Teko check-in, you need to be registered as a coach. Please contact your administrator."
                )
                return

            coach_id = coach.get('id')
            coach_name = coach.get('name', 'Coach')
            today_str = date.today().strftime('%Y-%m-%d')

            # Find today's sessions for this coach
            all_sessions = FirebaseService.get_all_sessions(coach_id=coach_id)
            sessions = [s for s in all_sessions if s.get('date') == today_str]
            print(f"📍 Found {len(sessions)} session(s) for {coach_name} today")

            if not sessions:
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text="You don't have a session scheduled for today. 📋"
                )
                return

            # Pick the best session: prefer not-yet-checked-in, earliest start time
            unchecked = [s for s in sessions if s.get('status') not in ('checked_in', 'missed')]
            if unchecked:
                unchecked.sort(key=lambda s: s.get('start_time', ''))
                session = unchecked[0]
            else:
                # All sessions already checked in
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text="You've already checked in for today's session. ✅"
                )
                return

            # Resolve expected location from location_id
            location_id = session.get('location_id')
            expected_location = {}
            allowed_radius = 100  # default

            if location_id:
                loc_record = FirebaseService.get_location(location_id)
                if loc_record:
                    lat = loc_record.get('latitude')
                    lng = loc_record.get('longitude')
                    if lat is not None and lng is not None:
                        expected_location = {'latitude': float(lat), 'longitude': float(lng)}
                    else:
                        # Try geocoding from google_maps_link or address
                        coords = extract_coords_from_maps_url(loc_record.get('google_maps_link', ''))
                        if not coords:
                            coords = geocode_address(loc_record.get('address', ''))
                        if coords:
                            expected_location = coords
                            # Save back so we don't geocode every time
                            try:
                                FirebaseService.update_location(location_id, {
                                    'latitude': coords['latitude'],
                                    'longitude': coords['longitude']
                                })
                                print(f"📍 Backfilled coordinates for location {location_id}")
                            except Exception as e:
                                print(f"⚠️ Failed to save backfilled coords: {e}")
                    loc_radius = loc_record.get('radius')
                    if loc_radius is not None:
                        allowed_radius = int(loc_radius)

            actual_location = format_location(latitude, longitude)

            if not expected_location:
                # No GPS on the venue — still check in but can't verify distance
                FirebaseService.check_in_session(session['id'], {
                    'location': actual_location,
                    'location_verified': True,  # give benefit of the doubt
                })
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text=f"✅ Checked in, {coach_name}! (Location GPS not configured for this venue, so distance wasn't verified.)"
                )
                return

            # Verify distance
            verification = verify_location(actual_location, expected_location, allowed_radius)
            distance = verification.get('distance')
            within = verification.get('within_radius', False)

            FirebaseService.check_in_session(session['id'], {
                'location': actual_location,
                'location_verified': within,
            })

            if within:
                dist_str = f"{distance:.0f}m" if distance < 1000 else f"{distance/1000:.1f}km"
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text=f"✅ Checked in! You're {dist_str} from the venue. Have a great session, {coach_name}! 🏏"
                )
            else:
                dist_str = f"{distance:.0f}m" if distance < 1000 else f"{distance/1000:.1f}km"
                radius_str = f"{allowed_radius}m" if allowed_radius < 1000 else f"{allowed_radius/1000:.1f}km"
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text=f"📍 You're {dist_str} from the venue (need to be within {radius_str}). This has been recorded as missed."
                )

            print(f"📍 Check-in result for {coach_name}: within={within}, distance={distance:.1f}m")

        except Exception as e:
            print(f"❌ Location check-in error: {e}")
            import traceback
            traceback.print_exc()
            try:
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text="Sorry, something went wrong with your check-in. Please try again. 🏏"
                )
            except:
                pass

    # ── Message handler ──────────────────────────────────────────────────

    @classmethod
    def handle_incoming_message(cls, from_number, message_text, message_id):
        """Handle an incoming WhatsApp message from a coach"""
        try:
            print(f"📨 Processing message from {from_number}: {message_text[:50]}...")

            # Check if this is from a registered coach
            coach = cls.get_coach_by_phone(from_number)

            if not coach:
                print(f"⚠️ Message from unregistered number: {from_number}")
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text="Hello! To use the Teko Cricket Coaching Assistant, you need to be registered as a coach. Please contact your administrator. 🏏"
                )
                return

            print(f"✅ Identified coach: {coach.get('name', 'Unknown')}")

            text_lower = message_text.strip().lower()
            print(f"🔍 Command check: text_lower='{text_lower}'")

            # Check for pending attendance response first
            pending = cls.get_pending_attendance(from_number)
            if pending and text_lower not in ['/help', '/start', '/attendance', '/attendance-redo']:
                print(f"📋 Routing to pending attendance response handler")
                response = cls.handle_attendance_response(from_number, message_text, pending)
            # Check for commands
            elif text_lower in ['/help', 'help', '/start']:
                response = cls.get_help_message(coach.get('name'))
            elif text_lower in ['/reset', 'reset']:
                cls.clear_pending_attendance(from_number)
                response = "Your conversation has been reset. Feel free to ask me anything about cricket coaching! 🏏"
            elif text_lower in ['/attendance', 'attendance']:
                print(f"📋 Matched /attendance command")
                response = cls.handle_attendance_command(coach)
            elif text_lower in ['/attendance-redo', 'attendance-redo']:
                print(f"📋 Matched /attendance-redo command")
                response = cls.handle_attendance_redo(coach)
            else:
                # Generate AI response
                response = cls.generate_response(
                    coach_phone=from_number,
                    user_message=message_text,
                    coach_name=coach.get('name'),
                    coach_id=coach.get('id'),
                )

            # Send response via WhatsApp
            result = WhatsAppService.send_message(
                phone_number=from_number,
                message_text=response
            )

            if result.get('success'):
                print(f"✅ Response sent successfully to {coach.get('name')}")
            else:
                print(f"❌ Failed to send response: {result.get('error')}")

        except Exception as e:
            print(f"❌ Error handling incoming message: {e}")
            try:
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text="Sorry, I encountered an error. Please try again. 🏏"
                )
            except:
                pass
    
    @classmethod
    def get_coach_by_phone(cls, phone_number):
        """Find a coach by their phone number"""
        try:
            # Format phone number for comparison
            formatted_phone = phone_number.replace('+', '').replace(' ', '').replace('-', '')
            
            coaches = FirebaseService.get_all_coaches()
            for coach in coaches:
                coach_phone = coach.get('phone_number', '').replace('+', '').replace(' ', '').replace('-', '')
                if coach_phone == formatted_phone:
                    return coach
            return None
        except Exception as e:
            print(f"Error finding coach: {e}")
            return None
    
    @classmethod
    def get_help_message(cls, coach_name=None):
        """Generate help message"""
        greeting = f"Hi Coach {coach_name}! 👋\n\n" if coach_name else "Hi Coach! 👋\n\n"
        
        return greeting + """I'm your Cricket Coaching Assistant! 🏏

I can help you with:
• Batting techniques & drills
• Bowling tips & variations
• Fielding exercises
• Match tactics & strategy
• Player development
• Fitness training
• Mental preparation

Just ask me anything about cricket coaching!

Commands:
/attendance - Mark player attendance for today's session
/help - Show this message
/reset - Start fresh conversation

To check in, just send your location! 📍

I speak all 11 SA languages - just message me in your preferred language!"""
