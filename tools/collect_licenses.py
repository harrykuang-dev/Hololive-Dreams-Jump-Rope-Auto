"""Collect installed runtime notices without importing or bundling model tools."""
import importlib.metadata as metadata
from pathlib import Path
import shutil,sys

def main():
    root=Path(__file__).resolve().parents[1]/'third_party/runtime'
    root.mkdir(parents=True,exist_ok=True)
    for name in ('numpy','opencv-python','Pillow','dxcam','onnxruntime-directml','pywin32','pyinstaller'):
        dist=metadata.distribution(name)
        for file in dist.files or []:
            if not any(word in Path(file).name.lower() for word in ('license','licence','copyright','notice','copying')):continue
            if file.suffix.lower() in ('.py','.pyc'):continue
            source=Path(dist.locate_file(file))
            if source.is_file():
                target=root/name/Path(*[p for p in file.parts if p not in ('..','.')])
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    for relative in ('LICENSE.txt','tcl/tcl8.6/license.terms','tcl/tk8.6/license.terms'):
        source=Path(sys.base_prefix)/relative
        if source.exists():
            target=root/'Python'/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)

if __name__=='__main__':main()
