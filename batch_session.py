"""Bounded graphical sessions using the same single-round visual controller."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import win32api
import win32event
import winerror

from app_settings import parse_stop_hotkey
from jump_rope_bot import BotConfig, JumpRopeBot
from session_flow import wait_for_result_page
from vision import GameCapture
from timing_control import DEFAULT_TIMING_POSITION, offset_ms, validate_timing_position

APP_VERSION = '1.3.1'
LOG = logging.getLogger('jump-rope-auto')


def diagnostic_base() -> Path:
    return Path(os.environ.get('LOCALAPPDATA', str(Path.cwd()))) / 'HololiveJumpRopeAuto' / 'sessions'


@dataclass(frozen=True)
class SessionConfig:
    rounds: int = 1
    stop_hotkey: str = 'F9'
    diagnostics: bool = False
    timing_position: float = DEFAULT_TIMING_POSITION
    score_limit: int | None = None

    def validate(self):
        if type(self.rounds) is not int or not 1 <= self.rounds <= 999:
            raise ValueError('Round limit must be an integer from 1 to 999')
        parse_stop_hotkey(self.stop_hotkey)
        validate_timing_position(self.timing_position)
        if self.score_limit is not None and (type(self.score_limit) is not int or not 1<=self.score_limit<=999):
            raise ValueError('Score limit must be an integer from 1 to 999 or None')


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
        from focus_recovery import FocusRecovery
        self.focus_recovery=FocusRecovery(diagnostics=config.diagnostics,sink=self._focus_event)

    def _focus_event(self,event):
        if self.directory:
            with (self.directory/'focus-events.jsonl').open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(event,ensure_ascii=False)+'\n')

    def _session_package(self):
        """Always available, including zero-frame initialization/focus failures."""
        if not self.directory:return
        payload={'limit':3,'attempts':self.focus_recovery.attempts,
                 'successes':self.focus_recovery.successes,'events':self.focus_recovery.events}
        (self.directory/'focus.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        archive=self.directory/'session-diagnostics.zip'
        temporary=archive.with_suffix('.zip.tmp')
        with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED) as output:
            for path in sorted(self.directory.iterdir()):
                if path.is_file() and path.suffix in ('.json','.jsonl','.log'):
                    output.write(path,path.name)
        with zipfile.ZipFile(temporary) as output:
            if output.testzip() is not None:raise RuntimeError('Session diagnostic ZIP verification failed')
        temporary.replace(archive)
        self.notify('archive',str(archive))

    @property
    def inputs(self):
        with self._count_lock:
            return self.completed_inputs + (self.current_bot.tap_count if self.current_bot else 0)

    def _stopped(self):
        pressed = lambda key: bool(self._get_key_state(key) & 0x8000)
        return (self.stop_event.is_set() or
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
                            'key_down_ms': 25,
                            'timing_position': self.config.timing_position,
                            'timing_offset_ms': offset_ms(self.config.timing_position),
                            'score_limit':self.config.score_limit,
                            'startup_recognizer': 'pill_geometry_v1', 'detector': 'yolo26n-whole-rope-marker',
                            'capture_backend': 'dxgi', 'target_fps': 60,
                            'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest() if executable else None}
                (self.directory / 'session.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
                handler = logging.FileHandler(self.directory / 'session.log', encoding='utf-8')
                handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
                LOG.addHandler(handler)
                self.notify('diagnostics', str(self.directory))
            self.focus_recovery.note('session_started')
            detector = None
            if self._bot_factory is JumpRopeBot:
                from detector import FullFrameDetector
                LOG.info('正在準備辨識模型')
                self.focus_recovery.note('model_initialization_begin')
                detector = FullFrameDetector(stopped=self._stopped)
                self.focus_recovery.note('model_initialization_ready',backend=detector.backend)
                if self.directory:
                    manifest['inference_backend'] = detector.backend
                    manifest['backend_fallback_reason'] = detector.fallback_reason
                    manifest['gpu_adapter'] = getattr(detector.runtime,'adapter',None)
                    manifest['cpu_inference'] = False
                    from timing_control import control_config
                    manifest['frame_validity_ms'] = control_config(
                        self.config.timing_position,backend=detector.backend)['frame_validity_ms']
                    (self.directory / 'session.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
                if self._stopped():
                    self.stop_reason = 'stopped'
                    return
            for index in range(1, self.config.rounds+1):
                if self._stopped():
                    self.stop_reason = 'stopped'
                    break
                self.current_round = index
                self.notify('round', (index, self.config.rounds))
                path = self.directory / f'round-{index:02d}.mp4' if self.directory else None
                bot = self._bot_factory(BotConfig(
                    record_path=path,
                    wait_for_round=True, auto_start=True,
                    capture_backend='dxgi', target_fps=60, startup_timeout=120,
                    key_down_time=.025, diagnostics_enabled=self.config.diagnostics,
                    timing_position=self.config.timing_position,
                    score_limit=self.config.score_limit,
                    round_timeout=900,
                    result_postroll=3 if self.config.rounds > 1 else 1), stop_requested=self._stopped,
                    **({'detector':detector,'score_notify':lambda score:self.notify('score_limit',score),
                        'focus_recovery':self.focus_recovery} if detector is not None else {}))
                with self._count_lock:
                    self.current_bot = bot
                try:
                    bot.run()
                finally:
                    self.stop_reason = bot.stop_reason
                    # Clear the bot before packaging, so an encoder failure
                    # cannot double-count inputs or leave the UI at an old round.
                    with self._count_lock:
                        self.completed_inputs += bot.tap_count
                        self.current_bot = None
                    finished = bot.stop_reason == 'round_finished' and bot.round_started_at is not None
                    if finished:
                        self.completed_rounds += 1
                    self.notify('round_done', (index, bot.stop_reason, bot.tap_count))
                    recorder = getattr(bot, 'diagnostic_recorder', None)
                    if recorder is not None and hasattr(recorder, 'result'):
                        self.notify('packing', index)
                        if handler:
                            handler.flush()
                            (recorder.directory / 'session.log').write_bytes((self.directory / 'session.log').read_bytes()[-1024*1024:])
                            (recorder.directory / 'session.json').write_bytes((self.directory / 'session.json').read_bytes())
                            (recorder.directory/'focus.json').write_text(json.dumps({
                                'attempts':self.focus_recovery.attempts,'limit':3,
                                'events':self.focus_recovery.events},ensure_ascii=False,indent=2),encoding='utf-8')
                        archive = recorder.package({
                            'performance': getattr(bot, 'basic_performance', {}),
                            'input_pulses': getattr(bot, 'input_pulses', []),
                            'score_limit':self.config.score_limit,
                            'score_limit_reached':getattr(bot,'score_limit_reached',False),
                            'confirmed_stop_score':getattr(bot,'confirmed_score',None) if getattr(bot,'score_limit_reached',False) else None,
                            'app_version': APP_VERSION})
                        self.notify('archive', str(archive))
                if not finished or index == self.config.rounds or self._stopped():
                    if self._stopped():
                        self.stop_reason = 'stopped'
                    break
                if not self._result_wait(bot._hwnd, stop_requested=self._stopped,
                        ensure_foreground=lambda:self.focus_recovery.ensure(bot._hwnd,stopped=self._stopped),
                        capture_factory=lambda hwnd: GameCapture(hwnd, backend='dxgi')):
                    self.stop_reason = ('stopped' if self._stopped() else
                                        'focus_lost' if self.focus_recovery.attempts>=3 else 'result_not_confirmed')
                    break
            self.notify('finished', self.stop_reason)
        except InterruptedError:
            self.stop_reason = 'stopped'
            self.notify('finished', self.stop_reason)
        except Exception:
            self.stop_reason = 'error'
            LOG.exception('執行已停止')
            raise
        finally:
            try:
                if self.directory:
                    (self.directory / 'summary.json').write_text(json.dumps({
                        'app_version': APP_VERSION,
                        'completed_rounds': self.completed_rounds,
                        'round_limit': self.config.rounds, 'inputs': self.inputs,
                        'stop_reason': self.stop_reason,
                        'focus_recovery_attempts':self.focus_recovery.attempts,
                        'focus_recovery_limit':3,
                    }, indent=2), encoding='utf-8')
            finally:
                try:
                    self.focus_recovery.note('session_finished',stop_reason=self.stop_reason)
                    if handler:handler.flush()
                    self._session_package()
                except Exception:
                    LOG.exception('診斷ZIP建立失敗；原始執行資料保留')
                finally:
                    if handler:
                        LOG.removeHandler(handler)
                        handler.close()
                    win32api.CloseHandle(mutex)
