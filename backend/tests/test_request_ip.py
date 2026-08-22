"""Tests for utils/request_ip.py: get_trusted_client_ip().

Pins the fix for the bug where taking the FIRST X-Forwarded-For entry
let an attacker get a fresh, self-chosen rate-limit key on every request
(the first entry is whatever the client put there; Google's
infrastructure only appends after it, at the end). The trustworthy
value is the SECOND-TO-LAST entry -- the one Google's own front end
appended -- never the first, and never remote_addr on Cloud Run.

Pure unit tests: a plain dict stands in for request.headers (Werkzeug's
Headers.get() and a dict's .get() behave the same for this purpose), so
nothing here touches Flask or Firestore.

Usage:
    cd backend
    pytest tests/test_request_ip.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Staging-project enforcement (FIREBASE_PROJECT_ID) now lives in
# tests/conftest.py, which runs before any test module in this directory
# is imported.

from utils.request_ip import get_trusted_client_ip, UNRESOLVED_IP_KEY  # noqa: E402


def test_normal_two_entry_header_takes_second_to_last():
    # No client-supplied prefix: Google appended exactly <client-ip>,<gfe-ip>.
    headers = {'X-Forwarded-For': '203.0.113.5,169.254.1.1'}
    assert get_trusted_client_ip(headers) == '203.0.113.5'


def test_forged_first_entry_is_ignored():
    headers = {'X-Forwarded-For': '1.2.3.4, 203.0.113.5, 169.254.1.1'}
    assert get_trusted_client_ip(headers) == '203.0.113.5'
    assert get_trusted_client_ip(headers) != '1.2.3.4'


def test_different_forged_prefixes_same_real_ip_yield_the_same_value():
    real_ip = '203.0.113.5'
    gfe_ip = '169.254.1.1'
    forged_values = ['1.2.3.4', '9.9.9.9', 'not-even-an-ip', '::1']

    results = {
        get_trusted_client_ip({'X-Forwarded-For': f'{forged},{real_ip},{gfe_ip}'})
        for forged in forged_values
    }
    assert results == {real_ip}, f"expected every forged prefix to resolve to the same key, got {results}"


def test_fewer_than_two_entries_returns_sentinel_not_the_lone_entry():
    headers = {'X-Forwarded-For': '1.2.3.4'}
    assert get_trusted_client_ip(headers) == UNRESOLVED_IP_KEY
    assert get_trusted_client_ip(headers) != '1.2.3.4'


def test_missing_header_returns_sentinel_without_fallback():
    assert get_trusted_client_ip({}) == UNRESOLVED_IP_KEY


def test_empty_header_returns_sentinel_without_fallback():
    assert get_trusted_client_ip({'X-Forwarded-For': ''}) == UNRESOLVED_IP_KEY


def test_remote_addr_fallback_requires_explicit_opt_in():
    headers = {}
    assert get_trusted_client_ip(headers, remote_addr='127.0.0.1') == UNRESOLVED_IP_KEY
    assert get_trusted_client_ip(headers, remote_addr='127.0.0.1', allow_remote_addr_fallback=True) == '127.0.0.1'


def test_remote_addr_fallback_never_used_when_xff_present_but_short():
    # Even with fallback allowed, a short/malformed XFF must not leak its
    # lone attacker-suppliable entry -- falls through to remote_addr, not
    # to that entry.
    headers = {'X-Forwarded-For': '1.2.3.4'}
    result = get_trusted_client_ip(headers, remote_addr='127.0.0.1', allow_remote_addr_fallback=True)
    assert result == '127.0.0.1'
    assert result != '1.2.3.4'


def test_whitespace_around_entries_is_stripped():
    headers = {'X-Forwarded-For': ' 1.2.3.4 , 203.0.113.5 , 169.254.1.1 '}
    assert get_trusted_client_ip(headers) == '203.0.113.5'
