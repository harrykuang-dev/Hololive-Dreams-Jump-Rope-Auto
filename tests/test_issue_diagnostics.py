import gzip
import json
import subprocess
import sys
import time
import zipfile

import cv2
import numpy as np
import pytest

from diagnostics import RoundDiagnostics, ISSUE_LIMIT
from tests.test_startup import frame


def small_round(tmp_path):
    image = frame('game')
    recorder = RoundDiagnostics(tmp_path/'round.mp4', image)
    for i in range(12):
        recorder.add(image.copy(), i/30, hud=True, ready=True, candidate=i==5,
                     clicked=i==5, detector_score=.8, input_elapsed=.17 if i==5 else None,
                     telemetry={'phase':'round'})
        time.sleep(.01)
    recorder.add(frame('next'), .4, hud=False, ready=False, candidate=False, clicked=False,
                 detector_score=0, telemetry={'phase':'result'})
    recorder.close(stop_reason='round_finished', tap_count=1)
    return recorder


def test_issue_zip_has_screenshots_and_all_observations_without_video(tmp_path):
    recorder = small_round(tmp_path)
    archive = recorder.package({'key_down_ms':25}, limit=2*1024*1024)
    assert archive.stat().st_size < 2*1024*1024 < ISSUE_LIMIT
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        names = z.namelist()
        assert 'performance.json' in names
        assert not any(name.endswith(('.mp4','.avi')) for name in names)
        frames = [json.loads(line) for line in gzip.decompress(z.read('frames.jsonl.gz')).decode().splitlines()]
        assert len(frames) == 13
        assert [f['observation'] for f in frames] == list(range(13))
        assert sum(f['clicked'] for f in frames) == 1
        assert frames[-1]['phase'] == 'result'
        manifest = json.loads(z.read('manifest.json'))
        assert manifest['baseline'] == 'V27' and manifest['key_down_ms'] == 25
        assert manifest['video'] is None and manifest['failure_window']
        for row in manifest['failure_window']:
            assert row['path'] in names
            assert row['t'] == frames[row['observation']]['t']
            assert cv2.imdecode(np.frombuffer(z.read(row['path']),np.uint8),1).shape == (540,960,3)
        assert len({s['observation'] for s in manifest['screenshots']}) == len(manifest['screenshots'])
        for shot in manifest['screenshots']:
            assert all(name in names for name in shot['files'])
            for name in shot['files']:
                if name.endswith('.jpg'):
                    assert cv2.imdecode(np.frombuffer(z.read(name),np.uint8),1).shape == (540,960,3)
    assert not list(recorder.directory.rglob('*.mp4'))


def test_compression_failure_preserves_original(tmp_path, monkeypatch):
    recorder = small_round(tmp_path)
    monkeypatch.setattr(recorder, '_zip', lambda *_: (_ for _ in ()).throw(RuntimeError('zip failed')))
    with pytest.raises(RuntimeError, match='zip failed'):
        recorder.package()
    assert (recorder.directory/'frames.jsonl.gz').exists()
    assert list(recorder.screens.glob('*.jpg'))
    assert not recorder.archive.exists()


def test_frontend_does_not_import_disabled_diagnostics():
    code = "import main_ui,sys; assert 'diagnostics' not in sys.modules; assert 'imageio_ffmpeg' not in sys.modules"
    subprocess.run([sys.executable,'-c',code], check=True)
