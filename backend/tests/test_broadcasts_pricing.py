"""Unit tests for Phase 2 step 3c item 3: routes/broadcasts.py pricing.

update_pricing() does a read-merge-write. Before this fix, a failed read
silently fell back to DEFAULT_PRICING, which then got merged with the
incoming change and written back — permanently overwriting whatever
pricing was actually saved. This is data loss, not just a hidden error.

Pure unit tests: FirebaseService.get_settings/update_settings are stubbed
via monkeypatch, so nothing here touches Firestore. The view function is
called directly via its __wrapped__ (the raw function @token_required
wraps with functools.wraps) inside a bare Flask test_request_context, so
these tests don't need a real JWT or the full app.py (which would trigger
Firebase initialization at import time).

Usage:
    cd backend
    pytest tests/test_broadcasts_pricing.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv

STAGING_ENV_PATH = os.path.join(os.path.dirname(__file__), '..', '.env.staging')
if os.path.exists(STAGING_ENV_PATH):
    load_dotenv(dotenv_path=STAGING_ENV_PATH, override=True)
    os.environ['FIREBASE_CREDENTIALS_PATH'] = ''

import pytest  # noqa: E402
from flask import Flask  # noqa: E402
from routes.broadcasts import update_pricing, get_pricing, _get_pricing, _get_pricing_or_raise, DEFAULT_PRICING  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402

app = Flask(__name__)


@pytest.fixture(autouse=True)
def _snapshot_default_pricing():
    """DEFAULT_PRICING is a module-level dict shared across the whole
    process. If any test in this file leaves it mutated, every later test
    (and the real app) would see corrupted defaults — restore it after
    every test regardless of pass/fail, on top of the aliasing fix itself
    being under test here."""
    original = dict(DEFAULT_PRICING)
    yield
    DEFAULT_PRICING.clear()
    DEFAULT_PRICING.update(original)


def test_update_pricing_read_failure_never_writes_defaults_over_saved_pricing(monkeypatch):
    """The core data-loss guard: if the pre-update read fails, update_settings
    must NEVER be called — proving a transient read blip cannot result in
    DEFAULT_PRICING being merged and written over real saved pricing."""
    monkeypatch.setattr(FirebaseService, 'get_settings',
                         lambda: (_ for _ in ()).throw(Exception("simulated Firestore outage")))

    write_calls = []
    monkeypatch.setattr(FirebaseService, 'update_settings', lambda data: write_calls.append(data))

    with app.test_request_context('/api/broadcasts/pricing', method='PUT', json={'marketing': 0.99}):
        response, status = update_pricing.__wrapped__('test-admin')

    assert write_calls == [], (
        "A failed pricing read must never result in a write — this is the exact data-loss bug being fixed."
    )
    assert status == 503
    body = response.get_json()
    assert body['success'] is False


def test_update_pricing_succeeds_and_writes_when_read_succeeds(monkeypatch):
    """Regression guard: the happy path must still work — a successful read
    merges the change and writes it."""
    saved_pricing = {'marketing': 0.05, 'utility': 0.02, 'service': 0.0, 'usd_to_zar': 18.0}
    monkeypatch.setattr(FirebaseService, 'get_settings',
                         lambda: {'whatsapp_pricing': dict(saved_pricing)})

    write_calls = []
    monkeypatch.setattr(FirebaseService, 'update_settings', lambda data: write_calls.append(data))

    with app.test_request_context('/api/broadcasts/pricing', method='PUT', json={'marketing': 0.10}):
        response, status = update_pricing.__wrapped__('test-admin')

    assert status == 200
    body = response.get_json()
    assert body['success'] is True
    assert body['pricing']['marketing'] == 0.10
    # The rest of the previously-saved pricing survives the merge untouched.
    assert body['pricing']['utility'] == 0.02
    assert body['pricing']['usd_to_zar'] == 18.0
    assert len(write_calls) == 1
    assert write_calls[0] == {'whatsapp_pricing': body['pricing']}


def test_get_pricing_read_only_endpoint_still_falls_back_to_defaults_on_failure(monkeypatch, caplog):
    """The read-only display endpoint (get_pricing/estimate-cost) is NOT
    the data-loss risk — it never writes anything — so it's fine for it to
    keep degrading to DEFAULT_PRICING on failure, as long as that failure
    is now logged (previously silent)."""
    monkeypatch.setattr(FirebaseService, 'get_settings',
                         lambda: (_ for _ in ()).throw(Exception("simulated Firestore outage")))

    with caplog.at_level('ERROR'):
        with app.test_request_context('/api/broadcasts/pricing', method='GET'):
            response, status = get_pricing.__wrapped__('test-admin')

    assert status == 200
    body = response.get_json()
    assert body['pricing'] == DEFAULT_PRICING
    assert any(r.levelname == 'ERROR' for r in caplog.records), (
        "A failed pricing read must be logged now, even on the best-effort read path."
    )


# ---------------------------------------------------------------------------
# Phase 2 step 3d item 1: DEFAULT_PRICING aliasing. settings.get('whatsapp_
# pricing', DEFAULT_PRICING) used to return the literal module-level dict
# when the key was missing; update_pricing then mutated it in place
# (`current_pricing[key] = val`), corrupting the process-global default for
# every later request/org. _get_pricing/_get_pricing_or_raise must now
# always return a fresh copy.
# ---------------------------------------------------------------------------

def test_get_pricing_or_raise_never_returns_the_literal_default_object(monkeypatch):
    monkeypatch.setattr(FirebaseService, 'get_settings', lambda: {})  # no whatsapp_pricing key
    result = _get_pricing_or_raise()
    assert result == DEFAULT_PRICING
    assert result is not DEFAULT_PRICING, "Must return a copy, not the literal module-level dict."


def test_get_pricing_never_returns_the_literal_default_object(monkeypatch):
    monkeypatch.setattr(FirebaseService, 'get_settings', lambda: None)  # settings doc absent entirely
    result = _get_pricing()
    assert result == DEFAULT_PRICING
    assert result is not DEFAULT_PRICING, "Must return a copy, not the literal module-level dict."


def test_update_pricing_with_missing_whatsapp_pricing_key_does_not_corrupt_module_default(monkeypatch):
    """The exact bug: settings exists but has no 'whatsapp_pricing' key yet
    (an org that's never touched pricing before). Before the fix, the
    merge-in-place mutated DEFAULT_PRICING itself, so this PUT would
    silently corrupt every other org's pricing defaults for the rest of
    the process."""
    monkeypatch.setattr(FirebaseService, 'get_settings', lambda: {'id': 'app_settings'})  # no whatsapp_pricing key
    monkeypatch.setattr(FirebaseService, 'update_settings', lambda data: None)

    with app.test_request_context('/api/broadcasts/pricing', method='PUT', json={'marketing': 0.99}):
        response, status = update_pricing.__wrapped__('test-admin')

    assert status == 200
    body = response.get_json()
    assert body['pricing']['marketing'] == 0.99

    assert DEFAULT_PRICING['marketing'] == 0.0625, (
        "update_pricing's merge must never mutate the module-level DEFAULT_PRICING dict — "
        f"got {DEFAULT_PRICING['marketing']}, corruption would leak into every subsequent request."
    )


def test_repeated_updates_with_missing_key_never_accumulate_on_module_default(monkeypatch):
    """Belt-and-suspenders: several PUTs in a row, each hitting the missing-
    key path, must never let DEFAULT_PRICING drift at all — proving the fix
    holds across repeated calls within the same worker, not just once."""
    monkeypatch.setattr(FirebaseService, 'get_settings', lambda: {})
    monkeypatch.setattr(FirebaseService, 'update_settings', lambda data: None)

    for rate in (0.11, 0.22, 0.33):
        with app.test_request_context('/api/broadcasts/pricing', method='PUT', json={'marketing': rate}):
            update_pricing.__wrapped__('test-admin')

    assert DEFAULT_PRICING['marketing'] == 0.0625
