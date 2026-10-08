"""SCHEDULER_JOBS: which of the app's three in-process jobs start at boot.

Unset: all three, exactly as before. 'end_prompts': only the end-of-session
prompts. DISABLE_SCHEDULER wins over it and starts none. A typo fails safe:
unrecognised names are ignored (and logged as an ERROR), so a typo can never
switch ON a job that wasn't asked for; if nothing valid is left, no job
starts and nothing can be sent.

A real BackgroundScheduler is never created: it is replaced by a recording
stand-in, same convention as test_scheduler_disable_switch.py.

Usage:
    cd backend
    pytest tests/test_scheduler_jobs_setting.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import logging  # noqa: E402
import subprocess  # noqa: E402

import apscheduler.schedulers.background as bg  # noqa: E402
import pytest  # noqa: E402
from flask import Flask  # noqa: E402

from config import Config  # noqa: E402
from services.scheduler_service import SchedulerService  # noqa: E402


class FakeScheduler:
    instances = []

    def __init__(self):
        self.jobs = {}
        self.started = False
        FakeScheduler.instances.append(self)

    def add_job(self, func, trigger, minutes, id, replace_existing):
        self.jobs[id] = (func.__name__, minutes)

    def start(self):
        self.started = True

    def shutdown(self):
        pass


@pytest.fixture(autouse=True)
def fake_scheduler(monkeypatch):
    FakeScheduler.instances = []
    monkeypatch.setattr(bg, 'BackgroundScheduler', FakeScheduler)
    monkeypatch.setattr(Config, 'DISABLE_SCHEDULER', False)


def _start(monkeypatch, setting):
    monkeypatch.setattr(Config, 'SCHEDULER_JOBS', setting)
    return SchedulerService.start_background_scheduler(Flask(__name__))


ALL_THREE = {
    'check_reminders': ('check_and_send_reminders', 1),
    'end_session_prompts': ('send_end_session_prompts', 5),
    'mark_missed': ('mark_missed_sessions', 30),
}


@pytest.mark.parametrize('unset', [None, '', '   '])
def test_unset_or_blank_runs_all_three_exactly_as_before(monkeypatch, unset):
    sched = _start(monkeypatch, unset)
    assert sched.started and sched.jobs == ALL_THREE


def test_end_prompts_only_runs_just_that_one(monkeypatch):
    sched = _start(monkeypatch, 'end_prompts')
    assert sched.started
    assert sched.jobs == {'end_session_prompts': ('send_end_session_prompts', 5)}


def test_any_subset_and_spacing_and_case(monkeypatch):
    sched = _start(monkeypatch, ' Reminders , MISSED ')
    assert set(sched.jobs) == {'check_reminders', 'mark_missed'}


def test_disable_scheduler_wins_and_runs_none(monkeypatch):
    monkeypatch.setattr(Config, 'DISABLE_SCHEDULER', True)
    assert _start(monkeypatch, 'end_prompts') is None
    assert FakeScheduler.instances == []


def test_typo_only_fails_safe_nothing_starts_and_error_logged(monkeypatch, caplog):
    with caplog.at_level(logging.ERROR):
        assert _start(monkeypatch, 'end_prompt') is None          # missing the final 's'
    assert FakeScheduler.instances == []
    assert any('unrecognised' in r.message and r.levelno == logging.ERROR for r in caplog.records)


def test_typo_alongside_a_valid_name_ignores_only_the_typo(monkeypatch, caplog):
    with caplog.at_level(logging.ERROR):
        sched = _start(monkeypatch, 'end_prompts,remindres')
    assert set(sched.jobs) == {'end_session_prompts'}              # the typo did not turn reminders on
    assert any('remindres' in r.message for r in caplog.records)


def test_only_started_once_per_app(monkeypatch):
    monkeypatch.setattr(Config, 'SCHEDULER_JOBS', 'end_prompts')
    app = Flask(__name__)
    assert SchedulerService.start_background_scheduler(app) is not None
    assert SchedulerService.start_background_scheduler(app) is None
    assert len(FakeScheduler.instances) == 1


@pytest.mark.parametrize('raw,expected', [(None, 'None'), ('end_prompts', "'end_prompts'")])
def test_env_value_is_read_raw(raw, expected):
    env = {k: v for k, v in os.environ.items() if k != 'SCHEDULER_JOBS'}
    if raw is not None:
        env['SCHEDULER_JOBS'] = raw
    out = subprocess.run(
        [sys.executable, '-c', 'from config import Config; print(repr(Config.SCHEDULER_JOBS))'],
        cwd=os.path.join(os.path.dirname(__file__), '..'), env=env, capture_output=True, text=True, check=True)
    assert out.stdout.strip().splitlines()[-1] == expected
