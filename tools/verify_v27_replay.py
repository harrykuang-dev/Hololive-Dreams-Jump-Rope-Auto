"""Verify promotion and replay exact saved columns; no capture or live input."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from v27_detector import VisualPassDetector


def verify_promotion():
    frozen = ROOT/'work/baselines/v27'
    manifest = json.loads((frozen/'baseline-manifest.json').read_text(encoding='utf-8'))
    sources = {}
    for name in ('baseline_v25.py','candidate_tracker.py','candidates.py','priority.py','repair_detector.py'):
        actual = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        assert actual == manifest['source_sha256'][name], name
        sources[name] = actual
    # Exact adaptations: recording/import wiring and removal of the fixed F9 stop.
    controller = (ROOT/'jump_rope_bot.py').read_text(encoding='utf-8')
    controller = controller.replace('from v27_detector import VisualPassDetector','from rope_track import VisualPassDetector')
    controller = controller.replace('from diagnostics import RoundDiagnostics as EvidenceRecorder','from evidence import EvidenceRecorder')
    controller = ''.join(line for line in controller.splitlines(keepends=True) if 'self.diagnostic_recorder =' not in line)
    original = (frozen/'controller/suite_bot.py').read_text(encoding='utf-8')
    original = original.replace("        if win32api.GetAsyncKeyState(win32con.VK_F9) & 0x8000:\n            self.stop_reason = 'F9'\n            return False\n",'')
    original = original.replace('                if win32api.GetAsyncKeyState(win32con.VK_F9) & 0x8000:\n                    self.stop_reason = "F9"\n                    break\n','')
    original = original.replace('Original input cooldown, F9, focus and visibility guards remain.',
                                'Original input cooldown, configured stop, focus and visibility guards remain.')
    original = original.replace('按 F9 或 Ctrl+C 停止。','按 Ctrl+C 停止。')
    assert controller == original
    # Only the menu recognizer changed in vision; capture, RoundGate and navigator are identical.
    def without_startup(s):
        a=s.index('class StartupScreen:'); b=s.index('class StartupNavigator:',a)
        return s[:a]+s[b:]
    assert without_startup((ROOT/'vision.py').read_text(encoding='utf-8')) == without_startup((frozen/'controller/vision.py').read_text(encoding='utf-8'))
    return sources


def replay(session, stems):
    cv2.setNumThreads(1)
    reports = []
    dummy = np.zeros((1440,2560,3),np.uint8)
    for stem in stems:
        events = json.loads((session/(stem+'.events.json')).read_text(encoding='utf-8'))
        pixels = json.loads((session/(stem+'.pixels.json')).read_text(encoding='utf-8'))
        detector = VisualPassDetector()
        candidates = 0
        mismatches = []
        with zipfile.ZipFile(session/(stem+'.pixels.zip')) as archive:
            for n,pixel in enumerate(pixels['frames']):
                columns = np.frombuffer(archive.read(pixel['entry']),np.uint8).reshape(pixel['shape'])
                detector.tracker._sample_columns = lambda _frame, value=columns: value
                candidate = detector.observe(dummy, pixel['measurement_time'])
                candidates += int(candidate)
                old = events['frames'][pixel['video_frame']]
                if candidate != old['candidate'] or detector.last_reason != old['decision']:
                    mismatches.append({'t':pixel['t'],'old':old['decision'],'new':detector.last_reason})
                if (n+1)%1500 == 0:
                    print(stem,n+1,len(pixels['frames']),flush=True)
        report = {'stem':stem,'observations':len(pixels['frames']),
                  'candidate_count':candidates,'mismatches':mismatches}
        assert not mismatches, report
        reports.append(report)
    return reports


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--stems',nargs='+',default=['snap_clock-02','snap_clock-04','snap_clock-10'])
    args=parser.parse_args()
    sources=verify_promotion()
    rounds=replay(args.session,args.stems)
    report={'baseline':'V27','key_down_ms':25,'core_sha256':sources,
            'controller_matches_frozen_baseline':True,'capture_and_gameplay_gate_unchanged':True,
            'rounds':rounds,'total_observations':sum(r['observations'] for r in rounds),
            'scope':'Exact saved sampled columns reproduce candidate/reason decisions. Offline evidence does not measure live scores or new-language game pages.'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('core_sha256','rounds')},indent=2))


if __name__=='__main__':
    main()
