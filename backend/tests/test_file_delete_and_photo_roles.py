"""Tests for:
  - DELETE /api/uploads/<path> being limited to the file's own organisation
    (super_admin excepted), with identical "not found" for other-org, missing
    and unresolvable paths;
  - dashboard session-photo add/delete being limited to super_admin and
    location_admin;
  - a failed photo-link refresh logging the session ID and error but never
    the storage path.

Storage is a stand-in set of paths -- the real bucket is never touched. Pure
unit tests: Firestore getters are stubbed.

Usage:
    cd backend
    pytest tests/test_file_delete_and_photo_roles.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import logging  # noqa: E402

import pytest  # noqa: E402
from flask import Flask, g  # noqa: E402
from google.api_core.exceptions import NotFound  # noqa: E402

from routes import uploads as uploads_routes  # noqa: E402
from routes import sessions as sessions_routes  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402
from services.storage_service import StorageService  # noqa: E402

TEAM_FILE = 'team_photos/team-a1/2026-10-19_sess-1.jpg'
ADMIN_FILE = 'content/org-a/abc123.pdf'
OTHER_ORG_FILE = 'team_photos/team-b1/2026-10-19_sess-9.jpg'
OLD_STYLE_FILE = 'photos/abc123.jpg'


@pytest.fixture
def storage(monkeypatch):
    """Stand-in bucket: a set of paths, with a record of what was deleted."""
    store = {'files': {TEAM_FILE, ADMIN_FILE, OTHER_ORG_FILE, OLD_STYLE_FILE}, 'deleted': []}

    def fake_delete(cls, file_path):
        if file_path not in store['files']:
            raise NotFound('missing')
        store['files'].discard(file_path)
        store['deleted'].append(file_path)
        return True
    monkeypatch.setattr(StorageService, 'delete_file', classmethod(fake_delete))
    teams = {'team-a1': {'org_id': 'org-a'}, 'team-b1': {'org_id': 'org-b'}}
    monkeypatch.setattr(FirebaseService, 'get_team', lambda team_id, org_id: teams.get(team_id))
    monkeypatch.setattr(FirebaseService, 'get_organisation',
                        lambda org_id: {'id': org_id} if org_id in ('org-a', 'org-b') else None)
    return store


def _delete(path, role, org):
    app = Flask(__name__)
    with app.test_request_context():
        g.current_user_role = role
        g.current_user_org_id = org
        res = uploads_routes.delete_file.__wrapped__({'id': 'u'}, path)
        body, status = res
        return status, body.get_json()


def test_other_orgs_admin_gets_not_found_and_nothing_is_deleted(storage):
    status, body = _delete(OTHER_ORG_FILE, 'location_admin', 'org-a')
    assert status == 404 and body['error'] == 'File not found'
    assert storage['deleted'] == []


def test_not_found_is_identical_for_other_org_file_and_missing_file(storage):
    other = _delete(OTHER_ORG_FILE, 'location_admin', 'org-a')
    missing = _delete('team_photos/team-a1/never-existed.jpg', 'location_admin', 'org-a')
    assert other == missing


def test_own_org_admin_can_delete_whatsapp_photo_and_dashboard_upload(storage):
    assert _delete(TEAM_FILE, 'location_admin', 'org-a')[0] == 200
    assert _delete(ADMIN_FILE, 'location_admin', 'org-a')[0] == 200
    assert storage['deleted'] == [TEAM_FILE, ADMIN_FILE]


def test_unresolvable_path_is_refused_for_non_super_admin(storage):
    for path in (OLD_STYLE_FILE, 'photos/not-an-org/abc.jpg', 'something/else/entirely/x.jpg'):
        status, body = _delete(path, 'location_admin', 'org-a')
        assert status == 404 and body['error'] == 'File not found'
    assert storage['deleted'] == []


def test_coach_with_no_org_cannot_delete_anything(storage):
    assert _delete(TEAM_FILE, 'coach', None)[0] == 404
    assert storage['deleted'] == []


def test_super_admin_can_delete_any_file_including_unresolvable(storage):
    assert _delete(OTHER_ORG_FILE, 'super_admin', None)[0] == 200
    assert _delete(OLD_STYLE_FILE, 'super_admin', None)[0] == 200
    assert storage['deleted'] == [OTHER_ORG_FILE, OLD_STYLE_FILE]


# ── session photo add/delete roles ───────────────────────────────────────

@pytest.fixture
def photo_env(monkeypatch):
    session = {'id': 'sess-1', 'org_id': 'org-a', 'photos': [{'id': 'p1', 'url': 'u', 'file_path': 'x'}]}
    updates = []
    monkeypatch.setattr(FirebaseService, 'get_session', lambda sid, org_id: dict(session))
    monkeypatch.setattr(FirebaseService, 'update_session', lambda sid, data: updates.append(data))
    return updates


def _call(view, role, *args, json=None):
    app = Flask(__name__)
    with app.test_request_context(json=json):
        g.current_user_role = role
        g.current_user_org_id = 'org-a'
        res = view.__wrapped__({'id': 'u'}, *args)
        body, status = res
        return status


@pytest.mark.parametrize('role,expected_add,expected_delete', [
    ('coach', 403, 403),
    ('location_admin', 201, 200),
    ('super_admin', 201, 200),
])
def test_session_photo_add_and_delete_roles(photo_env, role, expected_add, expected_delete):
    assert _call(sessions_routes.add_session_photo_admin, role, 'sess-1', json={'url': 'https://x/y'}) == expected_add
    assert _call(sessions_routes.delete_session_photo, role, 'sess-1', 'p1') == expected_delete
    if role == 'coach':
        assert photo_env == []  # nothing written


# ── failed refresh logging ───────────────────────────────────────────────

def test_failed_refresh_logs_session_id_and_error_but_no_path(monkeypatch, caplog):
    path = 'team_photos/team-a1/2026-10-19_sess-1.jpg'

    def boom(cls, file_path, minutes=60):
        raise RuntimeError(f'cannot sign {file_path}')
    monkeypatch.setattr(StorageService, 'get_signed_url', classmethod(boom))
    with caplog.at_level(logging.WARNING):
        out = StorageService.with_fresh_photo_link({'url': 'old', 'file_path': path}, 'sess-1')
    assert out['url'] == 'old'  # falls back to the stored link
    assert 'sess-1' in caplog.text and 'RuntimeError' in caplog.text
    assert path not in caplog.text and 'team_photos' not in caplog.text
