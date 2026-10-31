"""Build the DirectML program; optional NVIDIA libraries stay outside the core."""
from pathlib import Path
import argparse,subprocess,sys

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--distpath',default='dist')
    parser.add_argument('--name',default='HololiveDreamsJumpRopeAuto-1.3.3')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    # Optional TensorRT imports stdlib modules dynamically. Keep the interpreter
    # complete without embedding training frameworks or NVIDIA libraries.
    excluded_stdlib={'antigravity','this','idlelib','turtledemo','turtle','ensurepip','venv','test'}
    standard=[]
    for name in sorted(sys.stdlib_module_names):
        if name not in excluded_stdlib and not name.startswith(('_test','__')):
            standard.extend(['--hidden-import',name])
    models=[]
    for file in (root/'models').iterdir():
        if file.suffix in ('.onnx','.json','.txt') and file.name!='engine-device.json':
            models.extend(['--add-data',str(file)+';models'])
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--windowed',
        '--distpath',args.distpath,'--name',args.name,'--hidden-import','win32timezone',
        '--hidden-import','dxcam','--collect-binaries','onnxruntime',
        '--exclude-module','torch','--exclude-module','tensorrt',
        '--exclude-module','tensorrt_bindings','--exclude-module','tensorrt_libs',
        '--exclude-module','ultralytics',
        '--exclude-module','onnx','--exclude-module','pandas','--exclude-module','scipy',
        '--exclude-module','matplotlib','--exclude-module','IPython',
        '--icon','assets/jump-rope.ico','--version-file','assets/version_info.txt',
        '--add-data','assets;assets',*models,'--add-data','LICENSE;.',
        '--add-data','NOTICE.md;.','--add-data','third_party;third_party',
        *standard,'main_ui.py'],cwd=root,check=True)
if __name__=='__main__':main()
