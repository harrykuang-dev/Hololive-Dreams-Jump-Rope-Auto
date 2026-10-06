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


def verify_research_boundary(module_names, archive_names) -> None:
    """Research remains local; shipped assets are explicitly named UI assets."""
    research_modules = {'unitypy', 'octodb_pb2', 'crypto_utils', 'extractor',
                        'classification', 'manifest', 'downloader',
                        'audio_converter', 'media_converter', 'cridecoder',
                        'wannacri', 'capstone', 'crypto'}
    for name in module_names:
        if (name.split('.', 1)[0].lower() in research_modules
                or name.lower() == 'google.protobuf'
                or name.lower().startswith('google.protobuf.')):
            raise ValueError(f'Research dependency was accidentally bundled: {name}')
    ui_assets = {'assets/jump-rope.ico', 'assets/startup/next.png',
                 'assets/startup/ok.png', 'assets/startup/play.png'}
    for name in archive_names:
        normalized = name.replace('\\', '/').lower()
        parts = normalized.split('/')
        if 'work' in parts or 'hololive-toolkit-research' in parts:
            raise ValueError(f'Local research file was accidentally bundled: {name}')
        if normalized.startswith('assets/') and normalized not in ui_assets:
            raise ValueError(f'Unapproved product asset was bundled: {name}')
        if (normalized.endswith(('.unity3d', '.assetbundle', '.fbx', '.acb', '.awb', '.usm'))
                or parts[-1] in {'gameassembly.dll', 'global-metadata.dat', 'octocacheevai'}):
            raise ValueError(f'Game resource was accidentally bundled: {name}')


def verify(executable: Path, root: Path) -> dict:
    archive = CArchiveReader(str(executable))
    modules = archive.open_embedded_archive('PYZ.pyz')
    verify_research_boundary(modules.toc, archive.toc)
    sources = {}
    for name in ('app_locale', 'app_settings', 'batch_session', 'jump_rope_bot',
                 'rope_track', 'vision', 'tools.run_round_test', 'main_ui'):
        path = root / (name.replace('.', '/')+'.py')
        frozen = marshal.loads(archive.extract(name)) if name == 'main_ui' else modules.extract(name)
        expected = compile(path.read_text(encoding='utf-8'), frozen.co_filename, 'exec', dont_inherit=True)
        if frozen != expected:
            raise ValueError(f'Frozen code differs from source: {name}')
        # Git archives normalize tracked text to LF; source semantics are
        # already compared above. Hash that canonical form, not checkout CRLF.
        sources[path.relative_to(root).as_posix()] = hashlib.sha256(
            path.read_text(encoding='utf-8').encode('utf-8')).hexdigest()
    if any(name == 'experiments' or name.startswith('experiments.') for name in modules.toc):
        raise ValueError('Archived candidate was accidentally bundled')
    resources = ['LICENSE', 'third_party/fishing-auto-MIT.txt', 'assets/jump-rope.ico']
    resources.extend(f'assets/startup/{name}.png' for name in ('next', 'ok', 'play'))
    for name in resources:
        if archive.extract(name.replace('/', '\\')) != (root/name).read_bytes():
            raise ValueError(f'Bundled resource differs from source: {name}')
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
            'research_boundary_check_passed': True,
            'research_boundary_scope': 'Module denylist, game resource extensions, local research paths and explicit UI asset allowlist; not a semantic inspection of every dependency byte',
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
