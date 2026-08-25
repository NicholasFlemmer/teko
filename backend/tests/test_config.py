"""Tests for FRONTEND_BASE_URL (config.py) -- the single-value link base
derived from FRONTEND_URL.

FRONTEND_URL may be a comma-separated list (app.py's CORS setup needs the
full allow-list), but the link builders in routes/auth.py, routes/sessions.py,
and services/scheduler_service.py need exactly one origin. FRONTEND_BASE_URL
exists so those call sites never see a raw multi-value string.

Config attributes are read from the environment once, at class-attribute
definition time (see tests/conftest.py's own note on this), so these tests
use importlib.reload after monkeypatch.setenv to exercise the real
derivation in config.py rather than re-implementing the split/strip logic
by hand -- same pattern as
test_messaging_safeguards.py::test_sending_enabled_by_default_when_env_var_absent.

Usage:
    cd backend
    pytest tests/test_config.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import importlib  # noqa: E402

import config as config_module  # noqa: E402


def test_frontend_base_url_single_value(monkeypatch):
    monkeypatch.setenv('FRONTEND_URL', 'https://app.useteko.com')
    importlib.reload(config_module)
    try:
        assert config_module.Config.FRONTEND_BASE_URL == 'https://app.useteko.com'
    finally:
        importlib.reload(config_module)


def test_frontend_base_url_takes_first_of_comma_separated_list(monkeypatch):
    monkeypatch.setenv('FRONTEND_URL', 'https://app.useteko.com, https://staging-xyz.run.app')
    importlib.reload(config_module)
    try:
        assert config_module.Config.FRONTEND_BASE_URL == 'https://app.useteko.com'
    finally:
        importlib.reload(config_module)


def test_frontend_base_url_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv('FRONTEND_URL', 'https://app.useteko.com/')
    importlib.reload(config_module)
    try:
        assert config_module.Config.FRONTEND_BASE_URL == 'https://app.useteko.com'
    finally:
        importlib.reload(config_module)
