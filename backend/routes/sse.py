import json
import time
import threading
import collections
from datetime import datetime, timezone
from flask import Blueprint, Response, request

sse_bp = Blueprint('sse', __name__)

# In-memory event list with a monotonic sequence number.
# The _trim_offset tracks how many items have been removed from the front,
# so that stream generators can maintain valid absolute positions even after trims.
_event_list = []
_event_lock = threading.Lock()
_trim_offset = 0  # total items ever trimmed from front
_MAX_EVENTS = 200


def push_event(event_type, org_id, coach_name=None, preview=None, extra=None):
    """Push an activity event into the SSE buffer.

    Args:
        event_type: message_received | response_sent | attendance | check_in
        org_id: The organisation this event belongs to. Required -- every
            event must be scoped to an org so the stream generator can
            filter it to only that org's readers. There is no cross-org
            event on this feed; unlike FirebaseService's org_id=None
            super_admin escape hatch, there is no unscoped read here.
        coach_name: Name of the coach involved
        preview: Short text preview (first ~80 chars of message)
        extra: Optional dict with additional data
    """
    global _trim_offset
    event = {
        'type': event_type,
        'org_id': org_id,
        'coach_name': coach_name or 'Unknown',
        'preview': (preview or '')[:80],
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        event.update(extra)
    with _event_lock:
        _event_list.append(event)
        if len(_event_list) > _MAX_EVENTS * 2:
            trim_count = _MAX_EVENTS
            del _event_list[:trim_count]
            _trim_offset += trim_count


def _stream_generator(reader_org_id):
    """Generator that yields SSE events from the buffer, filtered to only
    events belonging to reader_org_id -- readers must never see another
    org's events on this feed."""
    global _trim_offset
    with _event_lock:
        # Start at the current absolute position (offset + list length)
        last_abs = _trim_offset + len(_event_list)
    keepalive_interval = 15
    last_keepalive = time.time()

    while True:
        with _event_lock:
            current_abs = _trim_offset + len(_event_list)
            if current_abs > last_abs:
                # Convert absolute position to list index
                start_idx = last_abs - _trim_offset
                if start_idx < 0:
                    start_idx = 0  # events were trimmed past our position
                # Position tracking (last_abs) advances over the full,
                # unfiltered list -- only what gets yielded is filtered by
                # org, so a busy other org can never cause this reader's
                # own org's events to be skipped or re-delivered.
                new_events = [e for e in _event_list[start_idx:] if e.get('org_id') == reader_org_id]
            else:
                new_events = []

        for event in new_events:
            yield f"data: {json.dumps(event)}\n\n"
        last_abs = current_abs

        now = time.time()
        if now - last_keepalive >= keepalive_interval:
            yield ": keepalive\n\n"
            last_keepalive = now

        time.sleep(1)


@sse_bp.route('/coach-activity', methods=['GET'])
def coach_activity_stream():
    """SSE endpoint streaming real-time coach Q&A activity, scoped to the
    reader's own organisation.

    Requires a valid JWT token via query parameter (EventSource does not support headers).
    Usage: /api/sse/coach-activity?token=<jwt>

    Only super_admin and location_admin may read this feed -- a coach
    token, or a token with no role claim at all, is rejected the same way
    role_required() in routes/auth.py fails closed: no role defaults to
    denied, never to a working role. A token with no org_id claim is
    rejected too rather than falling through to an unscoped read -- there
    is no cross-org read path on this feed for anyone, super_admin
    included.
    """
    import jwt as _jwt
    from config import Config as _Cfg
    token = request.args.get('token', '')
    if not token:
        return Response('Unauthorized', status=401)
    try:
        decoded = _jwt.decode(token, _Cfg.SECRET_KEY, algorithms=["HS256"])
    except Exception:
        return Response('Unauthorized', status=401)

    role = decoded.get('role')
    org_id = decoded.get('org_id')

    if role not in ('super_admin', 'location_admin'):
        return Response('Forbidden', status=403)
    if org_id is None:
        return Response('Forbidden', status=403)

    return Response(
        _stream_generator(org_id),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )
