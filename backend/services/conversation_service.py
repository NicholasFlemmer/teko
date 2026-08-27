import logging
from services.firebase_service import FirebaseService
from services.gemini_service import GeminiService
from services.whatsapp_service import WhatsAppService
from services.person_service import PersonService, PersonCacheUnavailableError
from services.safeguarding_service import detect_safeguarding_matches, record_safeguarding_flag, send_safeguarding_alert
from routes.sse import push_event
from utils.phone import mask_phone
from datetime import datetime, date, timezone
import uuid
import re

logger = logging.getLogger(__name__)


class PendingStateReadError(Exception):
    """Raised by get_pending_attendance/get_pending_photo when the
    Firestore read itself fails.

    Deliberately NOT the same outcome as a None return, which means "no
    pending request exists". Conflating the two lets a coach's numeric
    attendance reply (or their photo) fall through as if there were never
    anything pending — silently misrouted into the AI chat, or into a "no
    pending request" reply — instead of surfacing as a fixable, worth-
    telling-someone failure. Both call sites are already wrapped by an
    outer try/except that logs at ERROR and asks the coach to retry, so
    letting this propagate is enough; neither call site needs its own
    handling.
    """
    pass

def format_maps_link(lat, lng):
    """Return a Google Maps pin URL for the given coordinates, or None if invalid."""
    try:
        lat_f, lng_f = float(lat), float(lng)
        if not (-90 <= lat_f <= 90 and -180 <= lng_f <= 180):
            return None
        return f"https://maps.google.com/?q={lat_f},{lng_f}"
    except (TypeError, ValueError):
        return None


def _sanitize_for_prompt(text, max_length=200):
    """Sanitize user-sourced text before embedding in AI prompt.

    Strips control characters and prompt injection patterns,
    and truncates to max_length to prevent token stuffing.
    """
    if not text:
        return text
    # Remove common prompt injection markers
    text = re.sub(r'(ignore|disregard|forget)\s+(all\s+)?(previous|above|prior)\s+(instructions?|context|rules)', '[removed]', text, flags=re.IGNORECASE)
    # Remove attempts to impersonate system/assistant roles
    text = re.sub(r'^(system|assistant|you):\s*', '', text, flags=re.IGNORECASE | re.MULTILINE)
    # Strip control characters (keep newlines and tabs)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text[:max_length]


class ConversationService:
    """Service for managing AI conversations with coaches via WhatsApp"""

    # Default AI persona prompts, keyed by Organisation.type, then by
    # person_type ('coach' or 'participant'). An org can override its
    # prompt entirely via Organisation.ai_persona_prompt — for BOTH person
    # types at once, since that override is a single free-text field, not
    # itself split by person_type; see get_ai_persona_prompt().
    #
    # {coach_word}/{coach_word_lower}/{coach_word_plural_lower},
    # {player_word_lower}/{player_word_plural_lower}, and
    # {country}/{language_list} are filled in at render time (see
    # _render_persona_template) from the org's own terminology/locale
    # config, falling back to the org type's defaults exactly like
    # generate_response's own role_word resolution does. sports/events
    # coach personas already correctly say "coach" (their terminology
    # default IS "Coach"), so those two templates use the literal word
    # rather than the placeholder — only ngo/corporate (whose terminology
    # default is "Facilitator") use {coach_word...} in their coach persona.
    # Domain-specific phrases like "cricket coaching" or "corporate
    # coaching methodologies" are deliberately left as literal text — those
    # name a subject-matter discipline, not the role of the person
    # messaging, so they aren't part of this substitution.
    #
    # The participant personas are deliberately a different SHAPE, not
    # just a reworded coach persona: no EXPERTISE section (that section
    # exists to give the AI coaching/facilitation domain knowledge, which
    # a participant persona must never draw on — see the CONSTRAINTS
    # block's explicit refusal), oriented to the participant's own
    # sessions/schedule/expectations rather than running anything. Every
    # participant persona keeps the same safeguarding-referral sentence
    # the coach personas have — arguably more important here, since
    # participants may be young people.
    DEFAULT_AI_PERSONA_PROMPTS = {
        "sports": {
            "coach": """You are a professional cricket coaching specialist assistant helping coaches in {country}.

EXPERTISE:
- Cricket techniques: Batting (grip, stance, footwork, shots), Bowling (grip, action, variations), Fielding (catching, throwing, positioning)
- Coaching methodologies and player development
- Training drills and practice sessions
- Match strategy, tactics, and field placements
- Physical fitness and conditioning for cricket
- Mental preparation and sports psychology
- Youth cricket development (U10 to U19)
- {country} cricket context (facilities, weather, conditions)

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
- Support these languages: {language_list}

CONSTRAINTS:
- Keep responses under 1000 characters when possible
- Focus on cricket coaching and the coach's team/schedule
- If asked about non-cricket topics, politely redirect
- When the coach asks about their team, players, or schedule, use the data provided
- Don't provide medical advice, refer to professionals

Remember: You're helping coaches develop their skills and help their players improve.""",

            "participant": """You are a friendly assistant for {player_word_plural_lower} in {country}.

YOUR ROLE:
- Answer questions about their own upcoming sessions and schedule
- Explain what to bring or wear, and what to expect at a session
- Answer general questions about the programme
- Be encouraging, warm, and patient — {player_word_plural_lower} range from young children to adults

COMMUNICATION STYLE:
- Friendly and simple, suitable for WhatsApp
- Concise responses
- Avoid technical coaching jargon

LANGUAGE:
- Detect and respond in the SAME language the {player_word_lower} uses
- Support these languages: {language_list}

CONSTRAINTS:
- Keep responses under 1000 characters when possible
- Do NOT give coaching methodology, drills, or session-planning advice, and don't offer guidance on managing other {player_word_plural_lower} — that's for the {coach_word_lower}, not you to give here
- If asked something a {coach_word_lower} would normally handle, gently suggest they check with their {coach_word_lower}
- Don't provide medical advice, refer to professionals
- Don't provide legal or safeguarding-incident advice beyond general awareness — refer serious concerns to the organisation's designated safeguarding contact

Remember: You're here to support {player_word_plural_lower}, not to coach them — keep it simple and encouraging.""",
        },

        "ngo": {
            "coach": """You are a program support assistant helping {coach_word_plural_lower} at a community or non-profit organisation in {country}.

EXPERTISE:
- Facilitating group sessions and activities for community programs
- Youth and community development methodologies
- Session planning, structure, and pacing
- Participant engagement and inclusive facilitation techniques
- Attendance tracking and session logistics
- Safeguarding awareness and creating a safe, supportive environment
- Working with volunteers and community stakeholders

YOUR ROLE:
- Provide practical, actionable facilitation advice
- Suggest activities and exercises suited to the program's goals
- Explain techniques clearly and simply
- Consider the {coach_word_lower}'s experience level and available resources
- Be encouraging and supportive

COMMUNICATION STYLE:
- Professional but friendly
- Concise responses (suitable for WhatsApp)
- Use bullet points and numbered lists
- Include practical examples
- Ask clarifying questions when needed

LANGUAGE:
- Detect and respond in the SAME language the {coach_word_lower} uses
- Support these languages: {language_list}

CONSTRAINTS:
- Keep responses under 1000 characters when possible
- Focus on program facilitation and the {coach_word_lower}'s group/schedule
- If asked about unrelated topics, politely redirect
- When the {coach_word_lower} asks about their group, participants, or schedule, use the data provided
- Don't provide medical, legal, or safeguarding-incident advice beyond general awareness — refer serious concerns to the organisation's designated safeguarding contact

Remember: You're helping {coach_word_plural_lower} run great sessions and support their participants.""",

            "participant": """You are a friendly support assistant for {player_word_plural_lower} in a community or non-profit programme in {country}.

YOUR ROLE:
- Answer questions about their own upcoming sessions and schedule
- Explain what to bring or expect at a session
- Answer general questions about the programme
- Be warm, encouraging, and patient — {player_word_plural_lower} may be young people or new to the programme

COMMUNICATION STYLE:
- Friendly and simple, suitable for WhatsApp
- Concise responses
- Avoid jargon; explain things plainly

LANGUAGE:
- Detect and respond in the SAME language the {player_word_lower} uses
- Support these languages: {language_list}

CONSTRAINTS:
- Keep responses under 1000 characters when possible
- Do NOT give facilitation advice, session-planning guidance, or anything about managing other {player_word_plural_lower} — that's for the {coach_word_lower}, not you to give here
- If asked something a {coach_word_lower} would normally handle, gently suggest they check with their {coach_word_lower}
- Don't provide medical, legal, or safeguarding-incident advice beyond general awareness — refer serious concerns to the organisation's designated safeguarding contact

Remember: You're here to support {player_word_plural_lower}, not to run the programme — keep it simple and encouraging.""",
        },

        "events": {
            "coach": """You are a session support assistant helping coaches and crew leads coordinate activities and sessions at events in {country}.

EXPERTISE:
- Running activity sessions, workshops, and event-day programming
- Session and shift planning, timing, and logistics
- Participant and attendee engagement techniques
- Team and volunteer coordination on event day
- Attendance and check-in tracking
- Troubleshooting common on-the-day event issues (venue, timing, equipment)

YOUR ROLE:
- Provide practical, actionable guidance for running sessions smoothly
- Suggest ways to keep activities on schedule and engaging
- Explain processes clearly and simply
- Consider the coach's experience level and the resources on hand
- Be encouraging and supportive

COMMUNICATION STYLE:
- Professional but friendly
- Concise responses (suitable for WhatsApp)
- Use bullet points and numbered lists
- Include practical examples
- Ask clarifying questions when needed

LANGUAGE:
- Detect and respond in the SAME language the coach uses
- Support these languages: {language_list}

CONSTRAINTS:
- Keep responses under 1000 characters when possible
- Focus on event sessions and the coach's team/schedule
- If asked about unrelated topics, politely redirect
- When the coach asks about their team, participants, or schedule, use the data provided
- Don't provide medical advice, refer to professionals

Remember: You're helping coaches deliver smooth, well-run sessions at every event.""",

            "participant": """You are a friendly support assistant for {player_word_plural_lower} at events in {country}.

YOUR ROLE:
- Answer questions about their own upcoming sessions and schedule
- Explain what to bring or expect, timing, and venue details
- Answer general questions about the event
- Be warm and helpful

COMMUNICATION STYLE:
- Friendly and simple, suitable for WhatsApp
- Concise responses
- Avoid jargon; explain things plainly

LANGUAGE:
- Detect and respond in the SAME language the {player_word_lower} uses
- Support these languages: {language_list}

CONSTRAINTS:
- Keep responses under 1000 characters when possible
- Do NOT give guidance on running sessions, coordinating crew, or managing other {player_word_plural_lower} — that's for the {coach_word_lower}, not you to give here
- If asked something a {coach_word_lower} would normally handle, gently suggest they check with their {coach_word_lower}
- Don't provide medical advice, refer to professionals
- Don't provide legal or safeguarding-incident advice beyond general awareness — refer serious concerns to the organisation's designated safeguarding contact

Remember: You're here to support {player_word_plural_lower}, not to run the event — keep it simple and encouraging.""",
        },

        "corporate": {
            "coach": """You are a training and session support assistant helping {coach_word_plural_lower} run corporate learning and development sessions in {country}.

EXPERTISE:
- Facilitating workplace training sessions and workshops
- Adult learning principles and corporate coaching methodologies
- Session planning, structure, and pacing
- Participant engagement and group facilitation techniques
- Attendance tracking and session logistics
- Giving and structuring constructive feedback

YOUR ROLE:
- Provide practical, actionable coaching and facilitation advice
- Suggest exercises and activities suited to the session's objectives
- Explain concepts clearly and simply
- Consider the {coach_word_lower}'s experience level and the resources available
- Be encouraging and professional

COMMUNICATION STYLE:
- Professional but approachable
- Concise responses (suitable for WhatsApp)
- Use bullet points and numbered lists
- Include practical examples
- Ask clarifying questions when needed

LANGUAGE:
- Detect and respond in the SAME language the {coach_word_lower} uses
- Support these languages: {language_list}

CONSTRAINTS:
- Keep responses under 1000 characters when possible
- Focus on session facilitation and the {coach_word_lower}'s team/schedule
- If asked about unrelated topics, politely redirect
- When the {coach_word_lower} asks about their team, participants, or schedule, use the data provided
- Don't provide HR, legal, or performance-management advice — refer to HR or the appropriate department

Remember: You're helping {coach_word_plural_lower} run effective sessions and support their team's development.""",

            "participant": """You are a friendly support assistant for {player_word_plural_lower} attending corporate learning and development sessions in {country}.

YOUR ROLE:
- Answer questions about their own upcoming sessions and schedule
- Explain what to bring, prepare, or expect at a session
- Answer general questions about the training programme
- Be professional, warm, and helpful

COMMUNICATION STYLE:
- Professional but approachable, suitable for WhatsApp
- Concise responses
- Avoid jargon; explain things plainly

LANGUAGE:
- Detect and respond in the SAME language the {player_word_lower} uses
- Support these languages: {language_list}

CONSTRAINTS:
- Keep responses under 1000 characters when possible
- Do NOT give facilitation advice, session-planning guidance, or anything about managing other {player_word_plural_lower} — that's for the {coach_word_lower}, not you to give here
- If asked something a {coach_word_lower} would normally handle, gently suggest they check with their {coach_word_lower}
- Don't provide HR, legal, or performance-management advice — refer to HR or the appropriate department
- Don't provide safeguarding-incident advice beyond general awareness — refer serious concerns to the organisation's designated safeguarding contact

Remember: You're here to support {player_word_plural_lower}, not to run the sessions — keep it simple and encouraging.""",
        },
    }

    @classmethod
    def _render_persona_template(cls, template, org_id):
        """Fill a DEFAULT_AI_PERSONA_PROMPTS template's {coach_word...}/
        {player_word...}/{country}/{language_list} placeholders from the
        org's own terminology/locale config
        (FirebaseService.get_org_terminology/get_org_locale), falling back
        to the sports/South-Africa defaults for a missing org_id exactly
        like generate_response's role_word resolution does. A template
        that doesn't reference a given placeholder (e.g. coach templates
        don't use {player_word_lower}) simply ignores the extra kwarg.
        """
        terminology = (FirebaseService.get_org_terminology(org_id) if org_id
                       else FirebaseService.DEFAULT_TERMINOLOGY)
        locale = (FirebaseService.get_org_locale(org_id) if org_id
                  else {'country': FirebaseService.DEFAULT_COUNTRY,
                        'supported_languages': FirebaseService.DEFAULT_SUPPORTED_LANGUAGES})
        return template.format(
            coach_word=terminology['coach_singular'],
            coach_word_lower=terminology['coach_singular'].lower(),
            coach_word_plural_lower=terminology['coach_plural'].lower(),
            player_word_lower=terminology['player_singular'].lower(),
            player_word_plural_lower=terminology['player_plural'].lower(),
            country=locale['country'],
            language_list=', '.join(locale['supported_languages']),
        )

    @classmethod
    def get_ai_persona_prompt(cls, org_id, person_type='coach'):
        """Resolve the AI system persona prompt to use for a given org and
        person_type ('coach' or 'participant').

        Priority:
        1. The org's own Organisation.ai_persona_prompt override, if set —
           returned verbatim, exactly as the admin wrote it, for BOTH
           person types. It's a single free-text field, not split by
           person_type, so there's no separate participant override to
           prefer — the org's own words win regardless of who's messaging.
           Never passed through _render_persona_template; that's only for
           filling in the placeholders in OUR default templates below.
        2. The default prompt for the org's Organisation.type AND
           person_type, rendered with that org's own terminology/country/
           language config (Phase 1's org-configurable terminology/persona
           system already supported per-org overrides for everything else
           in this prompt — this makes the default TEXT respect that too,
           instead of hardcoding "coach" and "South Africa" regardless of
           the org — and Phase 2 step 4 adds a genuinely different
           participant persona, not just a reworded coach one).
        3. The sports default for this person_type, as a defensive
           fallback — this shouldn't be reachable once every org has a
           valid type post-migration, so it's logged as a warning if hit.
        """
        org = FirebaseService.get_organisation(org_id) if org_id else None

        if org:
            custom_prompt = (org.get('ai_persona_prompt') or '').strip()
            if custom_prompt:
                return custom_prompt

            org_type = org.get('type')
            default_prompt = cls.DEFAULT_AI_PERSONA_PROMPTS.get(org_type, {}).get(person_type)
            if default_prompt:
                return cls._render_persona_template(default_prompt, org_id)

        logger.warning(
            "No org/type found for org_id=%s when resolving AI persona prompt "
            "(org=%s, person_type=%s) — falling back to the sports default.",
            org_id, 'found' if org else 'not found', person_type
        )
        sports_defaults = cls.DEFAULT_AI_PERSONA_PROMPTS['sports']
        fallback_template = sports_defaults.get(person_type, sports_defaults['coach'])
        return cls._render_persona_template(fallback_template, org_id)

    @classmethod
    def get_conversation_history(cls, coach_phone, limit=10):
        """Get recent conversation history for a coach.

        On failure, returns a single degradation-note entry instead of []
        — an empty list is indistinguishable from a genuinely fresh
        conversation, and would let the model confidently treat this as a
        first-ever message when history actually exists but couldn't be
        read. See _context_degraded_note (same pattern as
        load_rag_context/load_coach_context); generate_response's history
        loop renders this note's 'role' specially rather than as a chat
        turn.
        """
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
            logger.error("Error loading conversation history for %s: %s", coach_phone, e)
            return [{
                'role': 'system_note',
                'content': cls._context_degraded_note("Recent conversation history"),
                'timestamp': None,
            }]
    
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
                'timestamp': datetime.now(timezone.utc),
                'message_id': str(uuid.uuid4())
            }
            
            db.collection('conversations').document(phone_key).collection('messages').add(message_data)
            logger.debug("Saved %s message to conversation history", role)
        except Exception as e:
            logger.error("Error saving message: %s", e)
    
    @classmethod
    def _context_degraded_note(cls, what):
        """A short, honest note to embed in assembled context when a query
        for it fails, instead of silently returning empty context.

        This is a SYSTEM-level signal in the prompt, not a user-facing
        error — the person messaging still gets a normal, helpful reply.
        The point is that the AI must not treat "context failed to load"
        the same as "there is nothing there": without this, a query error
        looks identical to a coach genuinely having no teams/sessions, and
        the AI would confidently (and wrongly) tell them so.
        """
        return (
            f"[SYSTEM NOTE: {what} could not be loaded right now due to a "
            f"data error. This does NOT mean there is none — do not tell "
            f"the user there's nothing there. If it's relevant to their "
            f"question, say you're unable to check right now instead.]"
        )

    @classmethod
    def load_rag_context(cls, org_id):
        """Load all content and URLs from Firestore for RAG context, scoped
        to org_id.

        Content and URLs are fetched independently (separate try/except)
        so a failure in one can never silently discard data the other
        already fetched successfully. A failed fetch is never silently
        dropped — it's logged at ERROR level and turned into an explicit
        note in the returned context; see _context_degraded_note.
        """
        sections = []

        try:
            content_items = FirebaseService.get_all_content(org_id)
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
        except Exception as e:
            logger.error("Error loading RAG content items (org_id=%s): %s", org_id, e)
            sections.append(cls._context_degraded_note("Some knowledge base documents"))

        try:
            url_items = FirebaseService.get_all_urls(org_id)
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
        except Exception as e:
            logger.error("Error loading RAG URL resources (org_id=%s): %s", org_id, e)
            sections.append(cls._context_degraded_note("Some knowledge base URL resources"))

        if not sections:
            return ''

        return (
            "KNOWLEDGE BASE (use this information to help answer questions):\n"
            + "\n\n---\n\n".join(sections)
            + "\n\nEND OF KNOWLEDGE BASE\n"
        )

    @classmethod
    def load_coach_context(cls, coach_id, org_id):
        """Load coach-specific context: their teams, players, and upcoming
        sessions, scoped to org_id.

        Teams/players and sessions are fetched independently (separate
        try/except) so a failure in one can never silently discard data
        the other already fetched successfully — e.g. a sessions query
        error must not wipe out a team list that already loaded fine. A
        failed fetch is never silently dropped — it's logged at ERROR
        level and turned into an explicit note in the returned context;
        see _context_degraded_note.
        """
        if not coach_id:
            return ''
        sections = []

        try:
            all_teams = FirebaseService.get_all_teams(org_id)
            coach_teams = [t for t in all_teams if coach_id in (t.get('coach_ids') or [])]

            if coach_teams:
                lines = ["YOUR TEAMS:"]
                for team in coach_teams:
                    team_name = _sanitize_for_prompt(team.get('name', 'Unnamed'), 100)
                    age_group = _sanitize_for_prompt(team.get('age_group', ''), 50)
                    lines.append(f"- {team_name} ({age_group})" if age_group else f"- {team_name}")

                    # Players in this team
                    players = FirebaseService.get_all_players(org_id, team_id=team.get('id'))
                    if players:
                        for p in players:
                            pname = _sanitize_for_prompt(
                                (p.get('first_name', '') + ' ' + p.get('last_name', '')).strip() or p.get('name', 'Unknown'),
                                100
                            )
                            lines.append(f"  - {pname}")
                    else:
                        lines.append("  (no players registered yet)")
                sections.append('\n'.join(lines))
        except Exception as e:
            logger.error(
                "Error loading team/player context (coach_id=%s, org_id=%s): %s",
                coach_id, org_id, e,
            )
            sections.append(cls._context_degraded_note("Your teams and players"))

        try:
            from datetime import date as _date
            today_str = _date.today().strftime('%Y-%m-%d')
            sessions = FirebaseService.get_all_sessions(org_id, coach_id=coach_id, start_date=today_str)
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
        except Exception as e:
            logger.error(
                "Error loading session context (coach_id=%s, org_id=%s): %s",
                coach_id, org_id, e,
            )
            sections.append(cls._context_degraded_note("Your upcoming sessions"))

        if not sections:
            return ''
        return '\n\n'.join(sections) + '\n'

    @classmethod
    def load_participant_context(cls, participant_id, org_id):
        """Load participant-specific context.

        Participants have no roster relationship (team/session assignment)
        yet — that's later work — so there's nothing to add beyond their
        own identity, which the persona line in generate_response already
        surfaces. Kept as a real function (returning '') rather than
        skipped entirely so load_person_context's dispatch stays explicit
        and this is a single, obvious place to extend once participants
        gain a roster relationship.
        """
        return ''

    @classmethod
    def load_person_context(cls, person_id, org_id, person_type):
        """Load context for whoever is messaging: full team/session context
        for a coach (identical to the original load_coach_context), or
        minimal context for a participant."""
        if person_type == 'coach':
            return cls.load_coach_context(person_id, org_id)
        return cls.load_participant_context(person_id, org_id)

    @classmethod
    def _terminology_for(cls, org_id):
        """Resolve org terminology, always safe to mutate.

        get_org_terminology(org_id) already returns a fresh dict, but the
        no-org_id fallback used to bind FirebaseService.DEFAULT_TERMINOLOGY
        directly — the literal class-level dict (itself the same object as
        DEFAULT_TERMINOLOGY_BY_TYPE["sports"]), not a copy. Nothing mutates
        it today, but that's exactly the shape of the DEFAULT_PRICING
        aliasing bug fixed in routes/broadcasts.py, one stray
        `terminology[key] = ...` away from corrupting the sports defaults
        for every org in the process. Copying here closes that off before
        it can happen.
        """
        if org_id:
            return FirebaseService.get_org_terminology(org_id)
        return dict(FirebaseService.DEFAULT_TERMINOLOGY)

    @classmethod
    def generate_response(cls, phone, user_message, org_id, person_name=None, person_id=None, person_type='coach'):
        """Generate an AI response to the sender's message using RAG context.

        org_id, person_name, person_id, and person_type are resolved by the
        caller (via PersonService) and passed straight in — this no longer
        re-derives org_id from a coach-only phone lookup like the original
        coach_phone-only version did, which is what made this path unusable
        for participants (their phone doesn't exist in the coaches
        collection, so that lookup always returned None).
        """
        try:
            # Get conversation history
            history = cls.get_conversation_history(phone, limit=5)

            # Load RAG content — org-scoped exactly as before; Phase 0 org
            # scoping is untouched, and load_rag_context was already
            # person-type-agnostic (it only ever took org_id).
            rag_context = cls.load_rag_context(org_id)

            # Load person-specific context (teams/sessions for a coach,
            # unchanged; minimal for a participant — see load_person_context).
            person_context = cls.load_person_context(person_id, org_id, person_type)

            # Org terminology (Phase 1) decides what to call this person —
            # "Coach" for a sports org, "Facilitator" for an NGO, etc. — and
            # what to call a participant ("Player", "Participant",
            # "Attendee"...). Falls back to the sports defaults exactly like
            # get_ai_persona_prompt does if org_id is missing.
            terminology = cls._terminology_for(org_id)
            role_word = terminology['coach_singular'] if person_type == 'coach' else terminology['player_singular']
            role_word_lower = role_word.lower()

            # Build context for Gemini. The org's configured persona prompt
            # (Phase 1's get_ai_persona_prompt — default-by-type-and-
            # person_type, or the org's own override) always comes first
            # and is only ever appended to below, never replaced or
            # reordered.
            context = cls.get_ai_persona_prompt(org_id, person_type) + "\n\n"

            if rag_context:
                context += rag_context + "\n"
                context += (
                    "IMPORTANT: When answering questions, use the knowledge base above "
                    "as your primary source. If a URL resource is relevant, share the link. "
                    "If the knowledge base doesn't cover the topic, use your general knowledge.\n\n"
                )

            if person_name:
                context += f"You are chatting with {role_word} {_sanitize_for_prompt(person_name, 100)}.\n\n"

            if person_context:
                context += person_context + "\n"
                context += (
                    f"Use the {role_word_lower}'s team, player, and session information above to give "
                    f"personalised answers. When the {role_word_lower} asks about their team or players, "
                    "refer to this data.\n\n"
                )

            context += "Recent conversation:\n"
            for msg in history:
                if msg['role'] == 'system_note':
                    context += f"{msg['content']}\n"
                    continue
                role_label = role_word if msg['role'] == 'user' else "You"
                context += f"{role_label}: {msg['content']}\n"

            context += (
                f"\nIMPORTANT: Always respond in the same language as the {role_word_lower}'s LATEST message below. "
                f"If the {role_word_lower} switches language, you must switch with them.\n"
            )
            context += f"\n{role_word}: {_sanitize_for_prompt(user_message, max_length=1000)}\nYou:"

            # Generate response using Gemini
            response = GeminiService.generate_custom_message(context)

            # Strip markdown formatting for WhatsApp
            clean_response = cls.strip_markdown(response)

            # Save both messages to history
            cls.save_message(phone, 'user', user_message)
            cls.save_message(phone, 'assistant', clean_response)

            return clean_response

        except Exception as e:
            logger.error("Error generating response: %s", e)
            return "I apologize, I'm having trouble responding right now. Please try again in a moment."
    
    # ── Attendance via WhatsApp ──────────────────────────────────────────

    @classmethod
    def _phone_key(cls, phone):
        return phone.replace('+', '').replace(' ', '').replace('-', '')

    @classmethod
    def get_pending_attendance(cls, coach_phone):
        """Check if a coach has a pending attendance request.

        Raises PendingStateReadError if the Firestore read itself fails —
        must stay distinguishable from a None return (no pending request).
        See PendingStateReadError for why: callers are already wrapped in
        an outer try/except that logs at ERROR and asks the coach to retry,
        so letting this propagate is the fix.
        """
        db = FirebaseService.get_db()
        key = cls._phone_key(coach_phone)
        try:
            doc = db.collection('pending_attendance').document(key).get()
            if doc.exists:
                data = doc.to_dict()
                # Expire after 30 minutes
                created = data.get('created_at')
                if created:

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
            logger.error("Error reading pending attendance for %s: %s", coach_phone, e)
            raise PendingStateReadError(str(e)) from e

    @classmethod
    def set_pending_attendance(cls, coach_phone, session_id, players):
        """Store pending attendance state for a coach"""
        db = FirebaseService.get_db()
        key = cls._phone_key(coach_phone)
        db.collection('pending_attendance').document(key).set({
            'session_id': session_id,
            'players': players,  # [{id, name, number}, ...]
            'created_at': datetime.now(timezone.utc)
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
            logger.error("Attendance command error: %s", e, exc_info=True)
            return f"Something went wrong loading attendance. Please try again or contact your administrator."

    @classmethod
    def _handle_attendance_command_inner(cls, coach):
        coach_id = coach.get('id')
        org_id = coach.get('org_id')
        today_str = date.today().strftime('%Y-%m-%d')
        terminology = cls._terminology_for(org_id)
        logger.info("Attendance command from coach id=%s for %s", coach_id, today_str)

        # Query by coach_id only to avoid Firestore composite index requirement,
        # then filter by date in Python
        all_coach_sessions = FirebaseService.get_all_sessions(org_id, coach_id=coach_id)
        sessions = [s for s in all_coach_sessions if s.get('date') == today_str and s.get('team_id')]
        logger.info("Found %d session(s) with teams for today (out of %d total)", len(sessions), len(all_coach_sessions))

        if not sessions:
            return "You don't have any sessions with a team scheduled for today. 📋"

        # Pick the session (if multiple, pick the earliest by start_time)
        sessions.sort(key=lambda s: s.get('start_time', ''))
        session = sessions[0]
        team_id = session['team_id']

        # Check if attendance already recorded
        if session.get('attended_player_ids') is not None and len(session.get('attended_player_ids', [])) > 0:
            attended_ids = set(session['attended_player_ids'])
            players = FirebaseService.get_all_players(org_id, team_id=team_id)
            total = len(players)
            present_count = 0
            absent_names = []
            for p in players:
                pname = (p.get('first_name', '') + ' ' + p.get('last_name', '')).strip() or p.get('name', 'Unknown')
                if p['id'] in attended_ids:
                    present_count += 1
                else:
                    absent_names.append(pname)

            lines = [f"✅ Attendance already recorded for today's session.\n"]
            lines.append(f"{present_count}/{total} present")
            if absent_names:
                lines.append(f"\nAbsent ({len(absent_names)}):")
                for name in absent_names:
                    lines.append(f"  ✗ {name}")
            else:
                lines.append("Everyone is present! 🎉")
            lines.append("\nSend /attendance-redo to record it again.")
            return '\n'.join(lines)

        team = FirebaseService.get_team(team_id, org_id)
        default_team_name = f"your {terminology['team_singular'].lower()}"
        team_name = team.get('name', default_team_name) if team else default_team_name

        players = FirebaseService.get_all_players(org_id, team_id=team_id)
        if not players:
            return f"No {terminology['player_plural'].lower()} found for {team_name}. Please contact your administrator."

        # Sort players alphabetically
        players.sort(key=lambda p: (p.get('first_name', '') + ' ' + p.get('last_name', '')).strip().lower())

        # Build numbered list
        player_list = []
        for i, p in enumerate(players, 1):
            name = (p.get('first_name', '') + ' ' + p.get('last_name', '')).strip() or p.get('name', f"{terminology['player_singular']} {i}")
            player_list.append({'id': p['id'], 'name': name, 'number': i})

        # Store pending state
        cls.set_pending_attendance(
            coach.get('phone_number', ''),
            session['id'],
            player_list
        )

        # Build message
        session_time = session.get('start_time', '')
        session_type = session.get('type', terminology['session_singular']).capitalize()
        lines = [f"📋 *{team_name}* — {session_type} ({today_str}, {session_time})\n"]
        lines.append(f"Reply with the *numbers of ABSENT {terminology['player_plural'].upper()}*.")
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
        players = pending.get('players')
        session_id = pending.get('session_id')
        if not players or not session_id:
            cls.clear_pending_attendance(coach_phone)
            return "Something went wrong with your attendance session. Please send /attendance to start again."

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
            logger.error("Error saving attendance: %s", e)
            return "Failed to save attendance. Please try again."

        cls.clear_pending_attendance(coach_phone)
        # Dashboard display name only — non-critical, so a cache-unavailable
        # failure here just falls back to 'Unknown' rather than blocking the
        # attendance confirmation that's already been saved.
        try:
            _person = PersonService.resolve(coach_phone)
        except PersonCacheUnavailableError:
            _person = None

        # This handler only has session_id (from `pending`), not an org_id
        # in scope, so org_id=None here is a deliberate unscoped
        # single-document lookup to resolve which org this event belongs
        # to for the dashboard feed — it is not a scoping bug and not an
        # authorization check (the attendance write above already
        # happened by session doc id, same as everywhere else in this
        # handler). Do not add an org_id filter to this call. Reused below
        # for team_id (pending-photo state) so the session is fetched once.
        session_data = FirebaseService.get_session(session_id, None)
        _event_org_id = session_data.get('org_id') if session_data else None
        if _event_org_id is None:
            logger.warning(
                "Skipping attendance dashboard event for session_id=%s: %s",
                session_id,
                "session not found" if not session_data else "session has no org_id",
            )
        else:
            push_event('attendance', org_id=_event_org_id,
                       coach_name=(_person.get('name') if _person else None) or 'Unknown',
                       preview=f"{len(attended_ids)}/{len(players)} present")

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
        lines.append("\n📸 Please send a group photo of the team!")
        lines.append("Reply /end to mark this session as completed.")

        # Set pending photo state so next image is linked to this session.
        team_id = session_data.get('team_id', '') if session_data else ''
        cls.set_pending_photo(coach_phone, session_id, team_id)

        return '\n'.join(lines)

    @classmethod
    def handle_attendance_redo(cls, coach):
        """Allow re-recording attendance for today's session"""
        coach_id = coach.get('id')
        org_id = coach.get('org_id')
        today_str = date.today().strftime('%Y-%m-%d')
        all_coach_sessions = FirebaseService.get_all_sessions(org_id, coach_id=coach_id)
        sessions = [s for s in all_coach_sessions if s.get('date') == today_str and s.get('team_id')]
        if not sessions:
            return "You don't have any sessions scheduled for today. 📋"

        sessions.sort(key=lambda s: s.get('start_time', ''))
        session = sessions[0]

        # Clear existing attendance so the command proceeds
        FirebaseService.update_session(session['id'], {'attended_player_ids': []})

        # Now run the normal attendance flow
        return cls.handle_attendance_command(coach)

    # ── Group photo upload ─────────────────────────────────────────────

    @classmethod
    def get_pending_photo(cls, coach_phone):
        """Check if a coach has been asked to send a group photo.

        Raises PendingStateReadError if the Firestore read itself fails —
        must stay distinguishable from a None return (no pending request).
        See PendingStateReadError: handle_image_message's outer try/except
        already logs at ERROR and asks the coach to retry, so letting this
        propagate is the fix.
        """
        db = FirebaseService.get_db()
        key = cls._phone_key(coach_phone)
        try:
            doc = db.collection('pending_photo').document(key).get()
            if doc.exists:
                data = doc.to_dict()
                # Expire after 60 minutes
                created = data.get('created_at')
                if created:

                    now = datetime.now(timezone.utc)
                    ts = created.timestamp() if hasattr(created, 'timestamp') else created.replace(tzinfo=timezone.utc).timestamp()
                    if (now.timestamp() - ts) > 3600:
                        cls.clear_pending_photo(coach_phone)
                        return None
                return data
            return None
        except Exception as e:
            logger.error("Error reading pending photo for %s: %s", coach_phone, e)
            raise PendingStateReadError(str(e)) from e

    @classmethod
    def set_pending_photo(cls, coach_phone, session_id, team_id):
        """Store pending photo state for a coach after attendance."""
        db = FirebaseService.get_db()
        key = cls._phone_key(coach_phone)
        db.collection('pending_photo').document(key).set({
            'session_id': session_id,
            'team_id': team_id,
            'created_at': datetime.now(timezone.utc),
        })

    @classmethod
    def clear_pending_photo(cls, coach_phone):
        """Clear pending photo state."""
        db = FirebaseService.get_db()
        key = cls._phone_key(coach_phone)
        try:
            db.collection('pending_photo').document(key).delete()
        except Exception:
            pass

    @classmethod
    def handle_image_message(cls, from_number, image_info, message_id=None):
        """Handle an image sent by a coach via WhatsApp.

        If the coach has a pending photo request (after attendance), download the
        image from WhatsApp, upload to Cloud Storage, and save the reference on
        both the session and the team.
        """
        try:
            try:
                person = PersonService.resolve(from_number)
            except PersonCacheUnavailableError:
                logger.error("Identity cache unavailable — cannot resolve image sender %s", mask_phone(from_number))
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text=cls.TRANSIENT_ERROR_MESSAGE
                )
                return
            if not person:
                logger.warning("Image from unrecognised number: %s", mask_phone(from_number))
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text=cls.UNRECOGNISED_SENDER_MESSAGE
                )
                return

            if not cls._is_allowed('photo_upload', person.get('person_type')):
                logger.info("Image from %s %s — declined (not permitted)", person.get('person_type'), person.get('id'))
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text=cls._command_declined_message(person.get('name'), person.get('org_id'))
                )
                return

            coach = person
            coach_name = coach.get('name', 'Coach')
            pending = cls.get_pending_photo(from_number)

            if not pending:
                # No pending photo request — let them know
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text="📸 Got your photo! To save a group photo, first run /attendance for today's session."
                )
                return

            media_id = image_info.get('id')
            if not media_id:
                logger.warning("Image message has no media id")
                return

            # Download image from WhatsApp
            image_bytes, content_type = cls._download_whatsapp_media(media_id)
            if not image_bytes:
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text="Sorry, I couldn't download that image. Please try sending it again. 📸"
                )
                return

            # Upload to Cloud Storage
            from services.storage_service import StorageService
            ext = '.jpg'
            if content_type and 'png' in content_type:
                ext = '.png'
            elif content_type and 'webp' in content_type:
                ext = '.webp'

            session_id = pending['session_id']
            team_id = pending.get('team_id', '')
            today_str = date.today().strftime('%Y-%m-%d')
            file_name = f"{today_str}_{session_id}{ext}"
            blob_path = f"team_photos/{team_id}/{file_name}"

            bucket = StorageService.get_bucket()
            blob = bucket.blob(blob_path)
            blob.upload_from_string(image_bytes, content_type=content_type or 'image/jpeg')
            # Use signed URL (7 day expiry) instead of making blob public
            from datetime import timedelta
            public_url = blob.generate_signed_url(expiration=timedelta(days=7), method='GET')

            # Save reference on the session
            photo_data = {
                'group_photo': {
                    'url': public_url,
                    'file_path': blob_path,
                    'uploaded_at': datetime.now(timezone.utc).isoformat(),
                    'uploaded_by': coach.get('id'),
                }
            }
            FirebaseService.update_session(session_id, photo_data)

            # Also save on the team as latest group photo
            if team_id:
                try:
                    FirebaseService.update_team(team_id, {
                        'latest_group_photo': {
                            'url': public_url,
                            'file_path': blob_path,
                            'session_id': session_id,
                            'date': today_str,
                        }
                    })
                except Exception as e:
                    logger.warning("Failed to update team photo: %s", e)

            cls.clear_pending_photo(from_number)
            push_event('photo_uploaded', org_id=coach.get('org_id'), coach_name=coach_name,
                       preview=f"Group photo for session {today_str}")

            WhatsAppService.send_message(
                phone_number=from_number,
                message_text=f"📸 Group photo saved! Great work, {coach_name}!\nReply /end to mark this session as completed."
            )
            logger.info("Group photo saved for session %s by coach id=%s", session_id, coach.get('id'))

        except Exception as e:
            logger.error("Image handling error: %s", e, exc_info=True)
            try:
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text="Sorry, something went wrong saving your photo. Please try again. 📸"
                )
            except Exception:
                pass

    @classmethod
    def _download_whatsapp_media(cls, media_id):
        """Download media from WhatsApp Cloud API.

        Returns (bytes, content_type) or (None, None) on failure.
        """
        import requests
        from config import Config
        try:
            # Step 1: Get the media URL
            url = f"{Config.WHATSAPP_API_URL}/{media_id}"
            headers = {"Authorization": f"Bearer {Config.WHATSAPP_API_KEY}"}
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            media_url = resp.json().get('url')
            if not media_url:
                logger.warning("No URL in media metadata response")
                return None, None

            # Step 2: Download the actual binary
            resp2 = requests.get(media_url, headers=headers, timeout=30)
            resp2.raise_for_status()
            return resp2.content, resp2.headers.get('Content-Type', 'image/jpeg')
        except Exception as e:
            logger.error("Failed to download WhatsApp media %s: %s", media_id, e)
            return None, None

    # ── WhatsApp location check-in ───────────────────────────────────────

    @classmethod
    def handle_location_check_in(cls, from_number, latitude, longitude, message_id=None):
        """Handle a shared WhatsApp location for coach check-in"""
        from utils.geolocation import verify_location, format_location, extract_coords_from_maps_url, geocode_address
        try:
            logger.info("Location received from %s", mask_phone(from_number))

            try:
                person = PersonService.resolve(from_number)
            except PersonCacheUnavailableError:
                logger.error("Identity cache unavailable — cannot resolve location sender %s", mask_phone(from_number))
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text=cls.TRANSIENT_ERROR_MESSAGE
                )
                return
            if not person:
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text=cls.UNRECOGNISED_SENDER_MESSAGE
                )
                return

            if not cls._is_allowed('location_checkin', person.get('person_type')):
                logger.info("Location from %s %s — declined (not permitted)", person.get('person_type'), person.get('id'))
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text=cls._command_declined_message(person.get('name'), person.get('org_id'))
                )
                return

            coach = person
            coach_id = coach.get('id')
            org_id = coach.get('org_id')
            coach_name = coach.get('name', 'Coach')
            today_str = date.today().strftime('%Y-%m-%d')

            # Find today's sessions for this coach
            all_sessions = FirebaseService.get_all_sessions(org_id, coach_id=coach_id)
            sessions = [s for s in all_sessions if s.get('date') == today_str]
            logger.info("Found %d session(s) for coach id=%s today", len(sessions), coach_id)

            if not sessions:
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text="You don't have a session scheduled for today. 📋"
                )
                return

            # Pick the best session: prefer ones this coach hasn't checked into yet
            unchecked = [s for s in sessions
                         if s.get('status') != 'cancelled'
                         and coach_id not in (s.get('coach_check_ins') or {})]
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
            from config import Config
            expected_location = {}
            allowed_radius = Config.GEOLOCATION_RADIUS_METERS

            if location_id:
                loc_record = FirebaseService.get_location(location_id, org_id)
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
                                logger.info("Backfilled coordinates for location %s", location_id)
                            except Exception as e:
                                logger.warning("Failed to save backfilled coords: %s", e)
                    loc_radius = loc_record.get('radius')
                    if loc_radius is not None:
                        allowed_radius = int(loc_radius)

            actual_location = format_location(latitude, longitude)

            if not expected_location:
                # No GPS on the venue — still check in but can't verify distance
                FirebaseService.check_in_session(session['id'], {
                    'location': actual_location,
                    'location_verified': False,  # can't verify without venue coordinates
                }, coach_id=coach_id, org_id=org_id)
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
            }, coach_id=coach_id, org_id=org_id)

            venue_link = format_maps_link(expected_location.get('latitude'), expected_location.get('longitude'))
            venue_ref = f"\n📍 {venue_link}" if venue_link else ""

            dist_str = "unknown distance"
            if distance is not None:
                dist_str = f"{distance:.0f}m" if distance < 1000 else f"{distance/1000:.1f}km"

            if within:
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text=f"✅ Checked in! You're {dist_str} from the venue. Have a great session, {coach_name}!{venue_ref}"
                )
            else:
                radius_str = f"{allowed_radius}m" if allowed_radius < 1000 else f"{allowed_radius/1000:.1f}km"
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text=f"📍 You're {dist_str} from the venue (need to be within {radius_str}). Please try again when you're closer, or contact your administrator if this seems wrong.{venue_ref}"
                )

            push_event('check_in', org_id=org_id, coach_name=coach_name,
                       preview=f"{'✅' if within else '❌'} {dist_str} from venue")
            logger.info("Check-in result for coach id=%s: within=%s", coach_id, within)

        except Exception as e:
            logger.error("Location check-in error: %s", e, exc_info=True)
            try:
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text="Sorry, something went wrong with your check-in. Please try again."
                )
            except Exception:
                pass

    # ── End session command ─────────────────────────────────────────────

    @classmethod
    def handle_end_session_command(cls, coach):
        """Mark today's active session as completed."""
        from firebase_admin import firestore as _firestore
        coach_id = coach.get('id')
        org_id = coach.get('org_id')
        today_str = date.today().strftime('%Y-%m-%d')
        terminology = cls._terminology_for(org_id)

        all_coach_sessions = FirebaseService.get_all_sessions(org_id, coach_id=coach_id)
        sessions = [s for s in all_coach_sessions if s.get('date') == today_str]

        if not sessions:
            return "You don't have any sessions scheduled for today. 📋"

        # Pick the first session this coach checked into that isn't completed/cancelled
        active = [s for s in sessions
                  if s.get('status') not in ('completed', 'cancelled')
                  and coach_id in (s.get('coach_check_ins') or {})]
        if not active:
            return "All of today's sessions are already completed or missed. ✅"

        active.sort(key=lambda s: s.get('start_time', ''))
        session = active[0]

        # Build summary
        session_time = session.get('start_time', '')
        session_type = session.get('type', terminology['session_singular']).capitalize()
        attended = session.get('attended_player_ids', [])

        FirebaseService.update_session(session['id'], {
            'status': 'completed',
            'completed_at': _firestore.SERVER_TIMESTAMP,
        })

        # Clear any pending photo request since session is done
        cls.clear_pending_photo(coach.get('phone_number', ''))

        lines = [f"✅ Session completed! ({session_type} at {session_time})"]
        if attended:
            lines.append(f"Attendance: {len(attended)} {terminology['player_plural'].lower()} recorded")
        else:
            lines.append("No attendance was recorded for this session.")
        lines.append(f"\nGreat work, {terminology['coach_singular']}! 🎉")
        return '\n'.join(lines)

    # ── Players command ────────────────────────────────────────────────

    PLAYER_INTENT_RE = re.compile(
        r'(my players|player list|who.{0,10}(my|the|our) (team|players|squad)'
        r'|show.{0,10}(team|players|squad)|list.{0,10}(players|team|squad))',
        re.IGNORECASE,
    )

    @classmethod
    def handle_players_command(cls, coach):
        """Return a formatted list of the coach's players grouped by team."""
        coach_id = coach.get('id')
        org_id = coach.get('org_id')
        terminology = cls._terminology_for(org_id)
        player_singular = terminology['player_singular']
        player_plural_lower = terminology['player_plural'].lower()
        team_plural_lower = terminology['team_plural'].lower()

        all_teams = FirebaseService.get_all_teams(org_id)
        coach_teams = [t for t in all_teams if coach_id in (t.get('coach_ids') or [])]

        if not coach_teams:
            return f"You don't have any {team_plural_lower} assigned yet. Please contact your administrator. 📋"

        lines = []
        total_players = 0
        for team in coach_teams:
            team_name = team.get('name', 'Unnamed')
            age_group = team.get('age_group', '')
            header = f"*{team_name}*"
            if age_group:
                header += f" ({age_group})"
            lines.append(header)

            players = FirebaseService.get_all_players(org_id, team_id=team.get('id'))
            if not players:
                lines.append(f"  (no {player_plural_lower} registered)")
            else:
                total_players += len(players)
                players.sort(key=lambda p: (p.get('first_name', '') + ' ' + p.get('last_name', '')).strip().lower())
                for i, p in enumerate(players, 1):
                    name = (p.get('first_name', '') + ' ' + p.get('last_name', '')).strip() or p.get('name', f'{player_singular} {i}')
                    lines.append(f"  {i}. {name}")
            lines.append("")  # blank line between teams

        lines.append(f"Total: {total_players} {player_plural_lower} across {len(coach_teams)} {team_plural_lower}")
        return '\n'.join(lines)

    # ── Command permissions ──────────────────────────────────────────────
    #
    # Single source of truth for "who can do what". Both message routers
    # below (the coach path in handle_incoming_message and the participant
    # path in _handle_participant_message), plus handle_image_message and
    # handle_location_check_in, all check COMMAND_PERMISSIONS instead of
    # each keeping their own scattered person_type if-checks. To open an
    # action up to a new person type later, edit ONE line here — nothing
    # else in the file needs to change.
    #
    # COMMAND_TOKENS maps an action name to the literal text tokens that
    # trigger it — the single place command spelling/aliases are defined
    # (previously duplicated across two separate elif chains, one per
    # person type, which is exactly the kind of drift this replaces).
    COMMAND_TOKENS = {
        'help': ['/help', 'help', '/start'],
        'reset': ['/reset', 'reset'],
        'attendance': ['/attendance', 'attendance'],
        'attendance_redo': ['/attendance-redo', 'attendance-redo'],
        'end_session': ['/end', 'end session'],
        'players': ['/players', 'players'],
    }

    # action -> the set of person_types allowed to use it. 'qa' is the free
    # -text AI Q&A fallback; 'attendance_reply' is a numeric reply to a
    # pending /attendance request; 'photo_upload' and 'location_checkin'
    # are triggered by WhatsApp message type, not a text token — see
    # handle_image_message/handle_location_check_in. location_checkin
    # stays coach-only here; participant self check-in is Phase 2 step 5.
    COMMAND_PERMISSIONS = {
        'help': {'coach', 'participant'},
        'reset': {'coach', 'participant'},
        'qa': {'coach', 'participant'},
        'attendance': {'coach'},
        'attendance_redo': {'coach'},
        'attendance_reply': {'coach'},
        'end_session': {'coach'},
        'players': {'coach'},
        'photo_upload': {'coach'},
        'location_checkin': {'coach'},
    }

    # Preserves the exact original pending-attendance carve-out: while a
    # coach has a pending /attendance request, only these exact tokens are
    # treated as commands rather than as the absent-player-numbers reply.
    # Deliberately NOT derived from COMMAND_TOKENS's full alias lists
    # (which also include bare-word aliases like 'players'/'end session',
    # and would add /reset) — widening this is a real behavioural change
    # to message routing during an active attendance flow, out of scope
    # for this step.
    _PENDING_ATTENDANCE_EXEMPT_TOKENS = {'/help', '/start', '/attendance', '/attendance-redo', '/end', '/players'}

    @classmethod
    def _classify_command(cls, text_lower):
        """Return the action name this text maps to. Free text (anything
        that isn't a known command token or the player-intent phrasing)
        always classifies as 'qa', the AI Q&A fallback."""
        for action, tokens in cls.COMMAND_TOKENS.items():
            if text_lower in tokens:
                return action
        if cls.PLAYER_INTENT_RE.search(text_lower):
            return 'players'
        return 'qa'

    @classmethod
    def _is_allowed(cls, action, person_type):
        return person_type in cls.COMMAND_PERMISSIONS.get(action, set())

    @classmethod
    def _command_declined_message(cls, name, org_id):
        """Friendly, org-terminology-driven decline for an action this
        person type isn't permitted to use (see COMMAND_PERMISSIONS).

        Deliberately generic rather than naming the specific command that
        was attempted — a participant typing /attendance doesn't need to
        be told "/attendance is a coach-only command", just that this
        isn't something they can do, plus a plain pointer to who to ask.
        Naming the exact command/feature would be the "leak facilitator
        functions in a confusing way" failure mode this is written to
        avoid; not mentioning it at all wouldn't read as unhelpful, either.
        """
        terminology = cls._terminology_for(org_id)
        greeting = f"Hi {name}! " if name else "Hi! "
        return greeting + (
            "That's not something you're able to do here. If you think you "
            f"should have access to this, please check with your "
            f"{terminology['coach_singular'].lower()}."
        )

    # ── Message handler ──────────────────────────────────────────────────

    @classmethod
    def handle_incoming_message(cls, from_number, message_text, message_id):
        """Handle an incoming WhatsApp message from a coach"""
        try:
            logger.debug("Processing message from %s: %d chars", mask_phone(from_number), len(message_text))

            # Resolve the sender to a person (coach or participant), across
            # both collections — see PersonService for details.
            try:
                person = PersonService.resolve(from_number)
            except PersonCacheUnavailableError:
                logger.error("Identity cache unavailable — cannot resolve message sender %s", mask_phone(from_number))
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text=cls.TRANSIENT_ERROR_MESSAGE
                )
                return

            if not person:
                logger.warning("Message from unrecognised number: %s", mask_phone(from_number))
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text=cls.UNRECOGNISED_SENDER_MESSAGE
                )
                return

            # Safeguarding keyword detection -- runs on every inbound
            # coach/participant message, before any command classification
            # or AI call, so it covers both branches below identically.
            # Detection-only: never touches `response`, never runs on the
            # AI's outbound text. Wrapped so a detection/recording failure
            # can never block the reply (constraint 1) but is never
            # swallowed silently either -- logged at ERROR with enough
            # context to investigate (constraint 2).
            #
            # safeguarding_flag holds record_safeguarding_flag()'s return
            # value (or None) -- the only way a flag can ever reach
            # send_safeguarding_alert(), which is dispatched below AFTER
            # the reply is sent, in both the coach and participant
            # branches. See send_safeguarding_alert()'s docstring for why
            # this also means a pre-existing flag can never be alerted on.
            safeguarding_flag = None
            try:
                safeguarding_matches = detect_safeguarding_matches(message_text)
                if safeguarding_matches:
                    safeguarding_flag = record_safeguarding_flag(
                        org_id=person.get('org_id'),
                        person_id=person.get('id'),
                        person_type=person.get('person_type'),
                        person_name=person.get('name'),
                        phone_number=from_number,
                        message_text=message_text,
                        message_id=message_id,
                        matches=safeguarding_matches,
                    )
            except Exception as safeguarding_error:
                logger.error(
                    "Safeguarding detection/recording failed for org_id=%s person_id=%s "
                    "message_id=%s: %s",
                    person.get('org_id'), person.get('id'), message_id, safeguarding_error,
                    exc_info=True,
                )

            if person.get('person_type') != 'coach':
                cls._handle_participant_message(from_number, message_text, person, safeguarding_flag)
                return

            coach = person
            coach_name = coach.get('name', 'Unknown')
            logger.info("Identified coach id=%s", coach.get('id'))

            # Push SSE event for incoming message
            push_event('message_received', org_id=coach.get('org_id'), coach_name=coach_name, preview=message_text)

            text_lower = message_text.strip().lower()
            logger.debug("Command check: text_lower='%s'", text_lower)

            # Check for pending attendance response first
            pending = cls.get_pending_attendance(from_number)
            if pending and text_lower not in cls._PENDING_ATTENDANCE_EXEMPT_TOKENS:
                logger.info("Routing to pending attendance response handler")
                response = cls.handle_attendance_response(from_number, message_text, pending)
            else:
                action = cls._classify_command(text_lower)
                logger.debug("Classified as action=%s", action)
                # A coach is permitted for every coach-reachable action —
                # COMMAND_PERMISSIONS is consulted here too (rather than
                # skipped) so a future action that's opened up unevenly
                # can't silently bypass the single source of truth.
                if not cls._is_allowed(action, 'coach'):
                    response = cls._command_declined_message(coach.get('name'), coach.get('org_id'))
                elif action == 'help':
                    response = cls.get_help_message(coach.get('name'), coach.get('org_id'))
                elif action == 'reset':
                    cls.clear_pending_attendance(from_number)
                    response = "Your conversation has been reset. Feel free to ask me anything!"
                elif action == 'attendance':
                    logger.info("Matched /attendance command")
                    response = cls.handle_attendance_command(coach)
                elif action == 'attendance_redo':
                    logger.info("Matched /attendance-redo command")
                    response = cls.handle_attendance_redo(coach)
                elif action == 'end_session':
                    logger.info("Matched /end command")
                    response = cls.handle_end_session_command(coach)
                elif action == 'players':
                    logger.info("Matched /players command")
                    response = cls.handle_players_command(coach)
                else:
                    # action == 'qa' — generate an AI response
                    response = cls.generate_response(
                        phone=from_number,
                        user_message=message_text,
                        org_id=coach.get('org_id'),
                        person_name=coach.get('name'),
                        person_id=coach.get('id'),
                        person_type='coach',
                    )

            # Send response via WhatsApp
            result = WhatsAppService.send_message(
                phone_number=from_number,
                message_text=response
            )

            if result.get('success'):
                logger.info("Response sent successfully to coach id=%s", coach.get('id'))
                push_event('response_sent', org_id=coach.get('org_id'), coach_name=coach_name, preview=response)
            else:
                logger.error("Failed to send response: %s", result.get('error'))
                push_event('response_sent', org_id=coach.get('org_id'), coach_name=coach_name, preview="[send failed]")

            # Safeguarding alert -- deliberately after the reply above,
            # win or lose, so a slow/failing send can never delay or
            # block it. See _dispatch_safeguarding_alert().
            cls._dispatch_safeguarding_alert(safeguarding_flag)

        except Exception as e:
            logger.error("Error handling incoming message: %s", e)
            try:
                WhatsAppService.send_message(
                    phone_number=from_number,
                    message_text="Sorry, I encountered an error. Please try again."
                )
            except Exception:
                pass

    # Sent when an inbound phone number doesn't resolve to any known person
    # (coach or participant). Deliberately person-type-neutral — it used to
    # say "you need to be registered as a coach", which actively misled
    # anyone who wasn't a coach.
    UNRECOGNISED_SENDER_MESSAGE = (
        "Hello! This number isn't registered with Teko. Please contact your "
        "administrator to get set up."
    )

    # Sent instead of UNRECOGNISED_SENDER_MESSAGE when PersonService can't
    # tell whether this phone is registered at all (PersonCacheUnavailableError)
    # — a real coach or participant must never be told they aren't
    # registered just because the identity cache failed to load. Also
    # reused for pending-attendance/pending-photo read failures, which are
    # the same "we don't know, don't guess" situation.
    TRANSIENT_ERROR_MESSAGE = (
        "Sorry, something's not quite right on our side right now. Please "
        "try again in a moment."
    )

    @classmethod
    def get_participant_help_message(cls, name=None):
        """Person-type-neutral /help reply for a participant."""
        greeting = f"Hi {name}! 👋\n\n" if name else "Hi! 👋\n\n"
        return greeting + (
            "I can answer questions — just ask me anything.\n\n"
            "Commands:\n"
            "/help - Show this message\n"
            "/reset - Start a fresh conversation"
        )

    @classmethod
    def _dispatch_safeguarding_alert(cls, safeguarding_flag):
        """Fire the safeguarding alert email for a just-recorded flag, if
        any — called AFTER the participant/coach's normal reply has
        already been sent (both call sites), so a slow or failing send
        can never delay or block it.

        send_safeguarding_alert() is documented to never raise on its
        own, but this is still wrapped: it runs after the reply in the
        coach path too, inside the same try/except as the rest of
        handle_incoming_message, and an uncaught exception there would
        hit that method's outer except block and send the caller a
        spurious "Sorry, I encountered an error" WhatsApp message *after*
        they already got their real, successful reply.
        """
        if not safeguarding_flag:
            return
        try:
            send_safeguarding_alert(safeguarding_flag)
        except Exception:
            logger.error(
                "Safeguarding alert dispatch raised unexpectedly for flag_id=%s",
                safeguarding_flag.get('id'), exc_info=True,
            )

    @classmethod
    def _handle_participant_message(cls, from_number, message_text, person, safeguarding_flag=None):
        """Route a text message from an identified participant, using the
        same COMMAND_PERMISSIONS map the coach path in
        handle_incoming_message consults — see that map for the full
        allocation. /help and /reset get simple participant-appropriate
        replies; anything gated to coach-only gets a friendly decline via
        _command_declined_message; everything else reaches the AI Q&A
        fallback exactly like a coach's free-text message would.
        """
        text_lower = message_text.strip().lower()
        person_name = person.get('name')
        org_id = person.get('org_id')
        action = cls._classify_command(text_lower)

        if not cls._is_allowed(action, 'participant'):
            response = cls._command_declined_message(person_name, org_id)
        elif action == 'help':
            response = cls.get_participant_help_message(person_name)
        elif action == 'reset':
            response = "Your conversation has been reset. Feel free to ask me anything!"
        else:
            # action == 'qa' — generate an AI response
            response = cls.generate_response(
                phone=from_number,
                user_message=message_text,
                org_id=org_id,
                person_name=person_name,
                person_id=person.get('id'),
                person_type='participant',
            )

        result = WhatsAppService.send_message(phone_number=from_number, message_text=response)
        if not result.get('success'):
            logger.error("Failed to send response to participant: %s", result.get('error'))

        # Safeguarding alert -- deliberately after the reply above, win or
        # lose, so a slow/failing send can never delay or block it.
        cls._dispatch_safeguarding_alert(safeguarding_flag)

    @classmethod
    def get_help_message(cls, coach_name=None, org_id=None):
        """Generate the /help reply for a coach, using the org's own
        terminology (Coach/Facilitator, Player/Participant/Attendee,
        Team/Group, Session) instead of hardcoding sports/cricket-specific
        wording that doesn't fit every org type."""
        terminology = cls._terminology_for(org_id)
        role = terminology['coach_singular']
        player = terminology['player_singular'].lower()
        players_plural = terminology['player_plural'].lower()
        team = terminology['team_singular'].lower()
        session = terminology['session_singular'].lower()

        greeting = f"Hi {role} {coach_name}! 👋\n\n" if coach_name else f"Hi {role}! 👋\n\n"

        return greeting + (
            f"I'm your coaching assistant! I can help with planning drills, "
            f"session ideas, and supporting your {players_plural} — ask me "
            f"anything, any time.\n\n"
            "Commands:\n"
            f"/attendance - Mark {player} attendance for today's {session}\n"
            f"/players - Show your {team}'s {player} list\n"
            f"/end - Mark today's {session} as completed\n"
            "/help - Show this message\n"
            "/reset - Start fresh conversation\n\n"
            "To check in, just send your location! 📍\n\n"
            "I'll respond in whichever language you message me in!"
        )
