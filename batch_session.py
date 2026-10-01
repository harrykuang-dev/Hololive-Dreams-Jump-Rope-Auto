"""Bounded graphical sessions using the same single-round visual controller."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import win32api
import win32event
import winerror

from app_settings import parse_stop_hotkey
from jump_rope_bot import BotConfig, JumpRopeBot
from tools.run_round_test import wait_for_result_page
from vision import GameCapture

APP_VERSION = '0.1.0'
LOG = logging.getLogger('jump-rope-auto')


def diagnostic_base() -> Path:
    return Path(os.environ.get('LOCALAPPDATA', str(Path.cwd()))) / 'HololiveJumpRopeAuto' / 'sessions'


@dataclass(frozen=True)
class SessionConfig:
    rounds: int = 1
    stop_hotkey: str = 'F9'
    diagnostics: bool = False
    observe_only: bool = False

    def validate(self):
        if type(self.rounds) is not int or not 1 <= self.rounds <= 7:
            raise ValueError('Round limit must be an integer from 1 to 7')
        if self.observe_only and self.rounds != 1:
            raise ValueError('Observation is limited to one manually started round')
        parse_stop_hotkey(self.stop_hotkey)


class BatchSession:
    def __init__(self, config: SessionConfig, *, notify=lambda _kind, _value: None,
                 bot_factory=JumpRopeBot, result_wait=wait_for_result_page,
                 get_key_state=win32api.GetAsyncKeyState, base=None):
        config.validate()
        self.config = config
        self.notify = notify
        self._bot_factory = bot_factory
        self._result_wait = result_wait
        self._get_key_state = get_key_state
        self._modifiers, self._key = parse_stop_hotkey(config.stop_hotkey)
        self._base = base
        self.stop_event = threading.Event()
        self._count_lock = threading.Lock()
        self.current_bot = None
        self.current_round = self.completed_rounds = self.completed_inputs = 0
        self.stop_reason = 'not_started'
        self.directory = None

    @property
    def inputs(self):
        with self._count_lock:
            return self.completed_inputs + (self.current_bot.tap_count if self.current_bot else 0)

    def _stopped(self):
        pressed = lambda key: bool(self._get_key_state(key) & 0x8000)
        return (self.stop_event.is_set() or pressed(0x78) or
                (pressed(self._key) and all(pressed(m) for m in self._modifiers)))

    def stop(self):
        self.stop_event.set()
        if self.current_bot:
            self.current_bot.stop()

    def run(self):
        mutex = win32event.CreateMutex(None, False, 'Local\\HololiveJumpRopeAutoSingleRound')
        if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
            win32api.CloseHandle(mutex)
            raise RuntimeError('Another jump-rope controller is already running')
        handler = None
        try:
            if self._stopped():
                self.stop_reason = 'stopped'
                return
            if self.config.diagnostics:
                self.directory = (self._base or diagnostic_base()) / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
                self.directory.mkdir(parents=True, exist_ok=False)
                executable = Path(sys.executable) if getattr(sys, 'frozen', False) else None
                manifest = {'app_version': APP_VERSION, 'round_limit': self.config.rounds,
                            'capture_backend': 'dxgi', 'target_fps': 60,
                            'observe_only': self.config.observe_only,
                            'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest() if executable else None}
                (self.directory / 'session.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
                handler = logging.FileHandler(self.directory / 'session.log', encoding='utf-8')
                handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
                LOG.addHandler(handler)
                self.notify('diagnostics', str(self.directory))
            for index in range(1, self.config.rounds+1):
                if self._stopped():
                    self.stop_reason = 'stopped'
                    break
                self.current_round = index
                self.notify('round', (index, self.config.rounds))
                path = self.directory / f'round-{index:02d}.mp4' if self.directory else None
                bot = self._bot_factory(BotConfig(
                    record_path=path, observe_only=self.config.observe_only,
                    wait_for_round=True, auto_start=not self.config.observe_only,
                    capture_backend='dxgi', target_fps=60, startup_timeout=120,
                    round_timeout=10 if self.config.observe_only else 180,
                    result_postroll=3 if self.config.rounds > 1 else 1), stop_requested=self._stopped)
                with self._count_lock:
                    self.current_bot = bot
                bot.run()
                self.stop_reason = bot.stop_reason
                # The UI must never briefly count this finished bot twice.
                with self._count_lock:
                    self.completed_inputs += bot.tap_count
                    self.current_bot = None
                finished = bot.stop_reason == 'round_finished' and bot.round_started_at is not None
                if finished:
                    self.completed_rounds += 1
                self.notify('round_done', (index, bot.stop_reason, bot.tap_count))
                if not finished or index == self.config.rounds or self._stopped():
                    if self._stopped():
                        self.stop_reason = 'stopped'
                    break
                if not self._result_wait(bot._hwnd, stop_requested=self._stopped,
                        capture_factory=lambda hwnd: GameCapture(hwnd, backend='dxgi')):
                    self.stop_reason = 'result_not_confirmed'
                    break
            self.notify('finished', self.stop_reason)
        finally:
            if handler:
                LOG.removeHandler(handler)
                handler.close()
            win32api.CloseHandle(mutex)
