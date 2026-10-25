"""Create a portable optional acceleration folder from installed dependencies."""
import argparse,importlib.util,importlib.metadata,json,shutil,sys
from pathlib import Path


def build(target):
    if target.exists():raise FileExistsError(target)
    target.mkdir(parents=True)
    names=['tensorrt','tensorrt_bindings','tensorrt_libs','nvidia.cuda_runtime']
    copied=[]
    for name in names:
        spec=importlib.util.find_spec(name)
        if spec is None:raise ImportError(name)
        if spec.submodule_search_locations:
            source=Path(next(iter(spec.submodule_search_locations)))
            shutil.copytree(source,target/Path(*name.split('.')),ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        else:
            source=Path(spec.origin);shutil.copy2(source,target/source.name)
        copied.append(name)
    distributions=['tensorrt-cu12','tensorrt-cu12-bindings','tensorrt-cu12-libs','nvidia-cuda-runtime-cu12']
    versions={}
    for name in distributions:
        d=importlib.metadata.distribution(name);source=Path(d._path)
        if source.is_dir():shutil.copytree(source,target/source.name)
        versions[name]=d.version
    if not versions['tensorrt-cu12'].startswith('10.13.'):raise ValueError('TensorRT 10.13 required')
    record=dict(format=2,python=list(sys.version_info[:2]),architecture='win_amd64',
                implementation='cuda-driver',pytorch_required=False,
                modules=copied,versions=versions,
                bytes=sum(p.stat().st_size for p in target.rglob('*') if p.is_file()))
    (target/'component.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps(record,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('target',type=Path);build(p.parse_args().target)
