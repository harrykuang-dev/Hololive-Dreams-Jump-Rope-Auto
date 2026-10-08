"""Verify frozen code/resources against source without launching the application."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import marshal
from pathlib import Path
import sys

from PyInstaller.archive.readers import CArchiveReader
import win32api


def verify(executable: Path, root: Path) -> dict:
    archive = CArchiveReader(str(executable))
    modules = archive.open_embedded_archive('PYZ.pyz')
    sources = {}
    for name in ('app_locale', 'app_settings', 'batch_session', 'jump_rope_bot',
                 'v27_detector', 'baseline_v25', 'candidate_tracker', 'candidates',
                 'priority', 'repair_detector', 'shared_gate', 'global_hotkey',
                 'diagnostics', 'vision', 'session_flow', 'main_ui'):
        path = root / (name.replace('.', '/')+'.py')
        frozen = marshal.loads(archive.extract(name)) if name == 'main_ui' else modules.extract(name)
        expected = compile(path.read_text(encoding='utf-8'), frozen.co_filename, 'exec', dont_inherit=True)
        if frozen != expected:
            raise ValueError(f'Frozen code differs from source: {name}')
        # Git archives normalize tracked text to LF; source semantics are
        # already compared above. Hash that canonical form, not checkout CRLF.
        sources[path.relative_to(root).as_posix()] = hashlib.sha256(
            path.read_text(encoding='utf-8').encode('utf-8')).hexdigest()
    excluded = ('experiments', 'curve_checks', 'experiment_detector', 'variants',
                'UnityPy', 'hololive_toolkit', 'imageio_ffmpeg')
    if any(any(name == prefix or name.startswith(prefix+'.') for prefix in excluded) for name in modules.toc):
        raise ValueError('Archived candidate was accidentally bundled')
    if any(any(token in name.lower() for token in ('gameassembly','unityplayer','resources.assets','globalgamemanagers')) for name in archive.toc):
        raise ValueError('Game content was accidentally bundled')
    resources = ['LICENSE', 'third_party/fishing-auto-MIT.txt', 'assets/jump-rope.ico',
                 'assets/hopping-rope-logo.png']
    for name in resources:
        if archive.extract(name.replace('/', '\\')) != (root/name).read_bytes():
            raise ValueError(f'Bundled resource differs from source: {name}')
    if any(name.startswith('media\\') for name in archive.toc):
        raise ValueError('Unused video encoder was bundled')
    version = win32api.GetFileVersionInfo(str(executable), '\\')
    ms, ls = version['FileVersionMS'], version['FileVersionLS']
    return {'executable': executable.name,
            'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
            'file_version': '.'.join(map(str, (ms >> 16, ms & 65535, ls >> 16, ls & 65535))),
            'python': sys.version.split()[0],
            'packages': {name: importlib.metadata.version(name) for name in
                         ('PyInstaller', 'pywin32', 'numpy', 'opencv-python', 'dxcam')},
            'compiled_source_matches': sources,
            'source_hash_format': 'UTF-8 text with CRLF normalized to LF',
            'bundled_resources_match': resources,
            'archived_candidate_bundled': False,
            'gameplay_assets_bundled': False,
            'display_only_branding': ['assets/hopping-rope-logo.png', 'assets/jump-rope.ico'],
            'scope': 'Static archive verification; does not launch or control the game'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.executable, Path(__file__).resolve().parents[1])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f"Verified {len(report['compiled_source_matches'])} frozen source modules and "
          f"{len(report['bundled_resources_match'])} resources; archived candidate excluded")


if __name__ == '__main__':
    main()
