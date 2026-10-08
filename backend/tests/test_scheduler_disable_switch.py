"""DISABLE_SCHEDULER switch for SchedulerService.start_background_scheduler.

Unset/false: the three background jobs start exactly as before (and only once
per app). Set true: nothing starts. A real BackgroundScheduler is never
created here -- it is replaced by a recording stand-in.

Usage:
    cd backend
    pytest tests/test_scheduler_disable_switch.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import subprocess  # noqa: E402

import apscheduler.schedulers.background as bg  # noqa: E402
import pytest  # noqa: E402
from flask import Flask  # noqa: E402

from config import Config  # noqa: E402
from services.scheduler_service import SchedulerService  # noqa: E402


class FakeScheduler:
    instances = []

    def __init__(self):
        self.jobs = []
        self.started = False
        FakeScheduler.instances.append(self)

    def add_job(self, func, trigger, minutes, id, replace_existing):
        self.jobs.append((id, minutes))

    def start(self):
        self.started = True

    def shutdown(self):
        pass


@pytest.fixture(autouse=True)
def fake_scheduler(monkeypatch):
    FakeScheduler.instances = []
    monkeypatch.setattr(bg, 'BackgroundScheduler', FakeScheduler)


def _parsed_flag(raw):
    """Read Config.DISABLE_SCHEDULER in a fresh interpreter so reloading
    config can't leak into other test modules."""
    env = {k: v for k, v in os.environ.items() if k != 'DISABLE_SCHEDULER'}
    if raw is not None:
        env['DISABLE_SCHEDULER'] = raw
    out = subprocess.run(
        [sys.executable, '-c', 'from config import Config; print(Config.DISABLE_SCHEDULER)'],
        cwd=os.path.join(os.path.dirname(__file__), '..'), env=env,
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip().splitlines()[-1]


def test_default_is_off_when_env_unset():
    assert _parsed_flag(None) == 'False'


@pytest.mark.parametrize('raw,expected', [('true', 'True'), ('1', 'True'), ('TRUE', 'True'), ('false', 'False'), ('0', 'False'), ('', 'False')])
def test_env_parsing(raw, expected):
    assert _parsed_flag(raw) == expected


def test_scheduler_starts_when_not_disabled(monkeypatch):
    monkeypatch.setattr(Config, 'DISABLE_SCHEDULER', False)
    app = Flask(__name__)
    result = SchedulerService.start_background_scheduler(app)
    assert result is FakeScheduler.instances[0] and result.started
    assert sorted(result.jobs) == [('check_reminders', 1), ('end_session_prompts', 5), ('mark_missed', 30)]
    assert app.config['SCHEDULER_STARTED'] is True


def test_scheduler_starts_only_once_per_app(monkeypatch):
    monkeypatch.setattr(Config, 'DISABLE_SCHEDULER', False)
    app = Flask(__name__)
    SchedulerService.start_background_scheduler(app)
    assert SchedulerService.start_background_scheduler(app) is None
    assert len(FakeScheduler.instances) == 1


def test_scheduler_not_started_when_disabled(monkeypatch):
    monkeypatch.setattr(Config, 'DISABLE_SCHEDULER', True)
    app = Flask(__name__)
    assert SchedulerService.start_background_scheduler(app) is None
    assert FakeScheduler.instances == []
    assert not app.config.get('SCHEDULER_STARTED')
