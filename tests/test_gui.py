"""Opt-in GUI contracts with fake sessions; never controls the game."""
from types import SimpleNamespace
import threading
from unittest.mock import Mock, patch
import tkinter as tk
import pytest
import main_ui
from app_locale import LANGUAGES

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def fake_global_listener(monkeypatch):
    # GUI tests must not register real desktop shortcuts or start a controller.
    monkeypatch.setattr(main_ui,'GlobalHotkey',lambda *_:SimpleNamespace(
        start=Mock(), configure=Mock(), close=Mock()))


@pytest.fixture(scope='module')
def tk_runtime():
    # Repeated Tk() interpreters in one process intermittently lose Tcl's
    # library loader on this Python/Tk build. The app creates one interpreter;
    # use the same lifecycle here, with an isolated Toplevel for each case.
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def root(tk_runtime):
    return tk.Toplevel(tk_runtime)


def dispose(root, app):
    app.hotkey.close()
    app.logger.removeHandler(app.log_handler)
    for callback in root.tk.splitlist(root.tk.call('after','info')):
        root.after_cancel(callback)
    root.destroy()


@pytest.mark.parametrize('dpi', [96,120,144,192])
def test_translated_controls_fit_at_supported_dpis(dpi, root):
    root.withdraw()
    root.maxsize(3840,2160)
    with patch('main_ui.window_dpi',return_value=dpi), patch('main_ui.window_work_area',return_value=(3840,2160)):
        app = main_ui.JumpRopeApp(root)
    try:
        root.deiconify()
        root.update()
        for language in LANGUAGES:
            app.language.set(language)
            app.apply_language()
            root.update()
            assert app.start_button.winfo_height() == app.stop_button.winfo_height()
            # An odd available pixel count splits equally with a 1px remainder.
            assert abs(app.start_button.winfo_width() - app.stop_button.winfo_width()) <= 1
            assert app.log.winfo_height() >= 40
            assert app.log.winfo_rooty()+app.log.winfo_height() <= root.winfo_rooty()+root.winfo_height()
            assert app.language_choice.winfo_rootx()+app.language_choice.winfo_width() <= root.winfo_rootx()+root.winfo_width()
    finally:
        dispose(root, app)


def test_start_resets_count_and_running_start_does_not_duplicate_session(root):
    root.withdraw()
    factory = Mock(side_effect=lambda config,**kw:SimpleNamespace(config=config,completed_rounds=0,
        inputs=0,stop_reason='round_finished',directory=None,run=Mock(),stop=Mock()))
    app = main_ui.JumpRopeApp(root,session_factory=factory)
    try:
        app.target.set('7')
        app.stop_key.set('Ctrl+Alt+Q')
        with patch('main_ui.threading.Thread') as thread:
            thread.return_value.is_alive.return_value = False
            app.start()
            assert factory.call_count == 1
            assert factory.call_args.args[0].rounds == 7
            assert factory.call_args.args[0].stop_hotkey == 'Ctrl+Alt+Q'
            app.session.completed_rounds = 3
            app.session.inputs = 100
            app.refresh_counts()
            thread.return_value.is_alive.return_value = True
            app.start()
            assert factory.call_count == 1
            assert app.session.completed_rounds == 3
            assert app.session.inputs == 100
            app.close()
            app.session.stop.assert_called_once()
            app.finish_close()
            assert root.winfo_exists()
            thread.return_value.is_alive.return_value = False
            app._closing = False
            app.start()
            assert factory.call_count == 2
            assert app.session.completed_rounds == app.session.inputs == 0
    finally:
        dispose(root, app)


def test_shortcut_capture_requires_click_and_locks_while_running(root):
    root.withdraw()
    app = main_ui.JumpRopeApp(root)
    try:
        key = SimpleNamespace(keysym='q',state=0x20004,keycode=0x51)
        app.capture_key(key)
        assert app.stop_key.get() == 'F9'
        app.begin_capture()
        assert app.capture_key(key) == 'break'
        assert app.stop_key.get() == 'Ctrl+Alt+Q'
        assert not app._capturing
        app.set_controls(True)
        app.begin_capture()
        app.capture_key(SimpleNamespace(keysym='F8',state=0,keycode=0x77))
        assert app.stop_key.get() == 'Ctrl+Alt+Q'
    finally:
        dispose(root, app)


def test_start_shortcut_cannot_conflict_with_stop_and_never_runs_during_capture(root):
    root.withdraw()
    factory = Mock()
    app = main_ui.JumpRopeApp(root,session_factory=factory)
    try:
        app.begin_start_capture()
        app.start()
        factory.assert_not_called()
        app.capture_key(SimpleNamespace(keysym='F9',state=0,keycode=0x78))
        assert app.start_key.get() == 'F8'
        app.capture_key(SimpleNamespace(keysym='F7',state=0,keycode=0x76))
        assert app.start_key.get() == 'F7'
        assert not app._capturing
        app.stop_key.set('F6')
        app.begin_start_capture()
        app.capture_key(SimpleNamespace(keysym='F9',state=0,keycode=0x78))
        assert app.start_key.get() == 'F9'
        app.set_controls(True)
        app.hotkey.configure.assert_called_with(value='F9',enabled=False)
    finally:
        dispose(root,app)


def test_queued_shortcut_from_before_settings_capture_is_discarded(root):
    root.withdraw()
    factory = Mock()
    app = main_ui.JumpRopeApp(root,session_factory=factory)
    try:
        app.messages.put(('start_hotkey',app._hotkey_generation))
        app.begin_start_capture()
        app.end_capture()
        app.poll()
        factory.assert_not_called()
    finally:
        dispose(root,app)


@pytest.mark.parametrize('target,key,expected', [
    ('start', SimpleNamespace(keysym='F7',state=0x8,keycode=0x76), 'F7'),
    ('stop', SimpleNamespace(keysym='F7',state=0x8,keycode=0x76), 'F7'),
    ('start', SimpleNamespace(keysym='q',state=0x2000C,keycode=0x51), 'Ctrl+Alt+Q'),
    ('stop', SimpleNamespace(keysym='q',state=0x2000C,keycode=0x51), 'Ctrl+Alt+Q'),
])
def test_both_shortcut_fields_ignore_num_lock_and_preserve_real_alt(root, target, key, expected):
    root.withdraw()
    app = main_ui.JumpRopeApp(root)
    try:
        if target == 'start':
            app.begin_start_capture()
        else:
            app.begin_capture()
        assert app.capture_key(key) == 'break'
        variable = app.start_key if target == 'start' else app.stop_key
        display = app.start_shortcut_display if target == 'start' else app.shortcut_display
        assert variable.get() == display.get() == expected
        assert not app._capturing
    finally:
        dispose(root, app)


@pytest.mark.parametrize('dpi',[96,120,144])
def test_minimum_window_keeps_translated_log_visible(dpi,root):
    with patch('main_ui.window_dpi',return_value=dpi), patch('main_ui.window_work_area',return_value=(3840,2160)):
        app = main_ui.JumpRopeApp(root)
    try:
        root.geometry(f'{app.px(360)}x{app.px(680)}')
        for language in LANGUAGES:
            app.language.set(language)
            app.apply_language()
            root.update()
            assert app.log.winfo_height() >= app.px(30)
            assert app.logs.winfo_rooty()+app.logs.winfo_height() <= root.winfo_rooty()+root.winfo_height()
            assert app.version_label.winfo_rooty()+app.version_label.winfo_height() <= root.winfo_rooty()+root.winfo_height()
            assert app.shortcut_entry.cget('readonlybackground') == '#FFFFFF'
    finally:
        dispose(root,app)


def test_resize_reuses_theme_images(root):
    app = main_ui.JumpRopeApp(root)
    try:
        images = tuple(app.theme.images)
        for width,height in ((500,860),(640,920),(440,740),(560,900)):
            root.geometry(f'{app.px(width)}x{app.px(height)}')
            root.update()
            assert tuple(app.theme.images) == images
    finally:
        dispose(root,app)


def test_help_is_centered_on_parent_and_reused(root):
    app = main_ui.JumpRopeApp(root)
    try:
        root.geometry('500x860+450+100')
        root.update()
        app.show_help()
        root.update()
        dialog = app.help_dialog
        assert abs((dialog.winfo_rootx()+dialog.winfo_width()/2)
                   -(root.winfo_rootx()+root.winfo_width()/2)) < app.px(24)
        assert abs((dialog.winfo_rooty()+dialog.winfo_height()/2)
                   -(root.winfo_rooty()+root.winfo_height()/2)) < app.px(24)
        app.show_help()
        assert app.help_dialog is dialog
        dialog.destroy()
    finally:
        dispose(root,app)


def test_version_is_in_footer_and_not_window_title(root):
    app = main_ui.JumpRopeApp(root)
    try:
        assert app.version_label.cget('text') == 'v1.1.0'
        assert '1.1.0' not in root.title()
        assert app.status.cget('text') == '等待開始'
        assert app.counter.cget('text') == '已完成：0 / 1 局'
        assert not hasattr(app,'round_hint') and not hasattr(app,'log_title')
    finally:
        dispose(root,app)


def test_startup_failure_releases_controls_for_retry(root):
    def factory(config,**kwargs):
        return SimpleNamespace(config=config,completed_rounds=0,inputs=0,directory=None,
            stop_reason='error',run=Mock(side_effect=RuntimeError('restore timeout')),stop=Mock())
    app = main_ui.JumpRopeApp(root,session_factory=factory)
    try:
        app.start()
        app.worker.join(1)
        app.poll()
        assert app.has_error
        assert not app.start_button.instate(['disabled'])
        assert app.stop_button.instate(['disabled'])
        first = app.session
        app.start()
        app.worker.join(1)
        assert app.session is not first
    finally:
        dispose(root,app)


def test_stop_button_cancels_startup_wait(root):
    stopped = threading.Event()
    def factory(config,**kwargs):
        return SimpleNamespace(config=config,completed_rounds=0,inputs=0,directory=None,
            stop_reason='stopped',run=lambda:stopped.wait(1),stop=stopped.set)
    app = main_ui.JumpRopeApp(root,session_factory=factory)
    try:
        app.start()
        assert not app.stop_button.instate(['disabled'])
        app.stop_button.invoke()
        assert stopped.is_set()
        app.worker.join(1)
        app.poll()
        assert not app.start_button.instate(['disabled'])
    finally:
        stopped.set()
        dispose(root,app)
