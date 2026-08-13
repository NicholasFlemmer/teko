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
from routes.broadcasts import update_pricing, get_pricing, DEFAULT_PRICING  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402

app = Flask(__name__)


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
