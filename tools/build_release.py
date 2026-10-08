"""Reproducible windowed Windows release entry point; never starts the game."""
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable,str(root/'tools'/'make_icon.py')],cwd=root,check=True)
    subprocess.run([sys.executable,'-m','PyInstaller','--clean','--noconfirm','--onefile','--windowed',
        '--name','HololiveDreamsJumpRopeAuto-V27','--hidden-import','win32timezone',
        '--hidden-import','dxcam','--paths','.', '--icon','assets/jump-rope.ico',
        '--version-file','assets/version_info.txt',
        '--add-data','assets/jump-rope.ico;assets',
        '--add-data','LICENSE;.',
        '--add-data','third_party/fishing-auto-MIT.txt;third_party',
        'main_ui.py'],cwd=root,check=True)


if __name__ == '__main__':
    main()
