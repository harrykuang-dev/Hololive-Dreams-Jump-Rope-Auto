"""Regression coverage for physical shortcut capture on Windows Tk."""
import pytest

from app_settings import captured_hotkey


@pytest.mark.parametrize('locks', [0, 0x8, 0x2, 0x20, 0x2A, 0x40008])
@pytest.mark.parametrize('keysym,keycode,expected', [
    ('F8', 0x77, 'F8'),
    ('q', 0x51, 'Q'),
    ('KP_1', 0x61, 'Num1'),
])
def test_windows_lock_states_do_not_add_alt(locks, keysym, keycode, expected):
    assert captured_hotkey(keysym, locks, keycode) == expected
    assert captured_hotkey(keysym, locks | 0x4, keycode) == 'Ctrl+' + expected
    assert captured_hotkey(keysym, locks | 0x20000, keycode) == 'Alt+' + expected
    assert captured_hotkey(keysym, locks | 0x20005, keycode) == 'Ctrl+Alt+Shift+' + expected


def test_num_lock_preserves_shifted_physical_key():
    assert captured_hotkey('exclam', 0x9, 0x31) == 'Shift+1'
    assert captured_hotkey('colon', 0x9, 0xBA) == 'Shift+Semicolon'


@pytest.mark.parametrize('keysym,keycode', [
    ('Alt_L', 0x12), ('Alt_R', 0x12), ('Control_L', 0x11), ('Shift_L', 0x10),
])
def test_modifier_only_keypress_is_not_a_shortcut(keysym, keycode):
    assert captured_hotkey(keysym, 0x2000D, keycode) is None
