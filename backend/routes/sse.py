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


def push_event(event_type, coach_name=None, preview=None, extra=None):
    """Push an activity event into the SSE buffer.

    Args:
        event_type: message_received | response_sent | attendance | check_in
        coach_name: Name of the coach involved
        preview: Short text preview (first ~80 chars of message)
        extra: Optional dict with additional data
    """
    global _trim_offset
    event = {
        'type': event_type,
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


def _stream_generator():
    """Generator that yields SSE events from the buffer."""
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
                new_events = list(_event_list[start_idx:])
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
    """SSE endpoint streaming real-time coach Q&A activity.

    Requires a valid JWT token via query parameter (EventSource does not support headers).
    Usage: /api/sse/coach-activity?token=<jwt>
    """
    import jwt as _jwt
    from config import Config as _Cfg
    token = request.args.get('token', '')
    if not token:
        return Response('Unauthorized', status=401)
    try:
        _jwt.decode(token, _Cfg.SECRET_KEY, algorithms=["HS256"])
    except Exception:
        return Response('Unauthorized', status=401)

    return Response(
        _stream_generator(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )
