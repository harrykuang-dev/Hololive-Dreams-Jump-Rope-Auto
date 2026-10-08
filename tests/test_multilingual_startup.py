"""Synthetic lettering variation plus real page fixtures; no live game input."""
import cv2
import numpy as np
import pytest
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from tests.test_startup import frame
from vision import StartupScreen

WORDS = ['下一步', '下一步', 'Next', '次へ', '다음', 'Lanjut']


@pytest.mark.parametrize('page,expected', [('next','next'),('ok','ok'),
    ('event-next','event_next'),('play','play'),('play-resting','play')])
@pytest.mark.parametrize('word', WORDS + ['', '//////////'])
def test_button_lettering_does_not_change_page_recognition(page, expected, word):
    image = cv2.resize(frame(page), (960, 540))
    center = round(StartupScreen.BUTTONS[expected][0]*960)
    image[475:506, center-60:center+65] = (234, 180, 45)
    pil = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    font_path = next((p for p in ('C:/Windows/Fonts/msyh.ttc','C:/Windows/Fonts/arial.ttf') if Path(p).exists()),None)
    font = ImageFont.truetype(font_path, 18) if font_path else ImageFont.load_default()
    draw = ImageDraw.Draw(pil)
    draw.text((center, 490), word, font=font, anchor='mm', fill='white')
    edited = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    assert StartupScreen().identify(edited) == expected


@pytest.mark.parametrize('page', ['next', 'ok', 'event-next', 'play'])
def test_missing_or_moved_button_does_not_authorize_input(page):
    image = cv2.resize(frame(page), (960, 540))
    roi = image[455:525, 700:950].copy()
    image[455:525, 700:950] = 0
    assert StartupScreen().identify(image) is None
    image[380:450, 700:950] = roi
    assert StartupScreen().identify(image) is None


def test_button_alone_without_known_page_cannot_start():
    image = np.zeros((540,960,3), np.uint8)
    image[455:525,700:950] = cv2.resize(frame('play'),(960,540))[455:525,700:950]
    assert StartupScreen().identify(image) is None


@pytest.mark.parametrize('page,expected',[('next','next'),('ok','ok'),('event-next','event_next'),('play','play')])
@pytest.mark.parametrize('scale',[.8,.85,.9,1.,1.05])
def test_button_resting_and_hover_geometry(page,expected,scale):
    image=cv2.resize(frame(page),(960,540))
    button=cv2.resize(image[455:525,700:950],None,fx=scale,fy=scale)
    image[450:530,680:965] = (20,30,20)
    h,w=button.shape[:2]
    y,x=490-h//2,825-w//2
    image[y:y+h,x:x+w] = button
    assert StartupScreen().identify(image) == expected
