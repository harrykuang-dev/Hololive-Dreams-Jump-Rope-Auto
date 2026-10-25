"""Enable an adjacent optional NVIDIA component before lazy GPU imports."""
import json,os,sys
from pathlib import Path
_dll_handles=[]
_activated=None
_dll_modules={}
_registered=set()

def load_builder_library():
    """TRT's delayed LoadLibrary does not use Python's AddDllDirectory flags."""
    import ctypes,importlib.util
    spec=importlib.util.find_spec('tensorrt_libs')
    for root in (spec.submodule_search_locations or []) if spec else []:
        path=Path(root)/'nvinfer_builder_resource_10.dll'
        if path.is_file():
            key=str(path.resolve())
            if key not in _dll_modules:_dll_modules[key]=ctypes.WinDLL(key)
            return
    raise RuntimeError('TensorRT 10.13 builder library is missing')


def activate_tensorrt_component():
    global _activated
    if _activated is not None:return _activated
    base=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
    folder=base/'accelerators/tensorrt';receipt=folder/'component.json'
    record=None
    if receipt.exists():
        record=json.loads(receipt.read_text(encoding='utf-8'))
        if record.get('format')!=2 or record.get('python')!=list(sys.version_info[:2]):
            raise RuntimeError('Optional TensorRT component is incompatible with this Python runtime')
        if record.get('architecture')!='win_amd64':raise RuntimeError('Unsupported accelerator architecture')
        if not record.get('versions',{}).get('tensorrt-cu12','').startswith('10.13.'):
            raise RuntimeError('Optional component must contain TensorRT 10.13')
    handles=[]
    registered=[]
    try:
        roots=[folder] if record else [Path(p) for p in sys.path if p]
        for root in roots:
            for sub in ('tensorrt_libs','tensorrt_bindings','nvidia/cuda_runtime/bin'):
                path=root/sub
                key=str(path.resolve())
                if path.is_dir() and key not in _registered:
                    handles.append(os.add_dll_directory(key));registered.append(key)
    except Exception:
        for handle in handles:handle.close()
        raise
    _dll_handles.extend(handles)
    _registered.update(registered)
    if record:
        sys.path.insert(0,str(folder));_activated=folder
    return folder if record else None
