"""Reproducible windowed Windows release entry point; never starts the game."""
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    # Tracked artwork is a release input. Regenerate it explicitly with
    # make_icon.py only when updating the icon, never as a build side effect.
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--onefile','--windowed',
        '--name','HololiveDreamsJumpRopeAuto-1.2.1','--hidden-import','win32timezone',
        '--hidden-import','dxcam','--paths','.', '--icon','assets/jump-rope.ico',
        '--version-file','assets/version_info.txt',
        '--add-data','assets/jump-rope.ico;assets',
        '--add-data','assets/hopping-rope-logo.png;assets',
        '--add-data','LICENSE;.',
        'main_ui.py'],cwd=root,check=True)


if __name__ == '__main__':
    main()
