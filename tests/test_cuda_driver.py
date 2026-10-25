"""Driver resource ownership tests without loading CUDA or touching the game."""
import ctypes as C
from types import SimpleNamespace
import numpy as np
import pytest
from cuda_driver import Buffer,CudaDriver

def test_context_is_popped_on_exception_and_primary_reference_released_once():
    d=object.__new__(CudaDriver);d.context=C.c_void_p(12);d.device=0;d.closed=False
    calls=[];d.call=lambda name,*_:calls.append(name)
    with pytest.raises(ValueError):
        with d.current():raise ValueError('body')
    assert calls==['cuCtxPushCurrent_v2','cuCtxPopCurrent_v2']
    d.close();d.close();assert calls.count('cuDevicePrimaryCtxRelease_v2')==1
    with pytest.raises(RuntimeError,match='closed'):
        with d.current():pass

def test_partial_pinned_allocation_frees_device_buffer():
    calls=[]
    def call(name,*args):
        calls.append(name)
        if name=='cuMemAlloc_v2':args[0]._obj.value=1234
        if name=='cuMemHostAlloc':raise RuntimeError('host allocation failed')
    with pytest.raises(RuntimeError,match='host allocation'):
        Buffer(SimpleNamespace(call=call),(1,3,4,4),np.float32)
    assert calls==['cuMemAlloc_v2','cuMemHostAlloc','cuMemFree_v2']

def test_pinned_numpy_view_dimensions_and_idempotent_free():
    backing=C.create_string_buffer(48);calls=[]
    def call(name,*args):
        calls.append(name)
        if name=='cuMemAlloc_v2':args[0]._obj.value=2345
        if name=='cuMemHostAlloc':args[0]._obj.value=C.addressof(backing)
    b=Buffer(SimpleNamespace(call=call),(2,2,3),np.float32)
    assert b.nbytes==48 and b.array.shape==(2,2,3)
    b.array.fill(.25);assert np.all(b.array==.25)
    b.close();b.close()
    assert calls.count('cuMemFree_v2')==calls.count('cuMemFreeHost')==1

def test_host_buffer_still_freed_if_device_free_fails():
    backing=C.create_string_buffer(12);calls=[]
    def call(name,*args):
        calls.append(name)
        if name=='cuMemAlloc_v2':args[0]._obj.value=2345
        if name=='cuMemHostAlloc':args[0]._obj.value=C.addressof(backing)
        if name=='cuMemFree_v2':raise RuntimeError('free failure')
    b=Buffer(SimpleNamespace(call=call),(12,),np.uint8)
    with pytest.raises(RuntimeError):b.close()
    assert calls[-1]=='cuMemFreeHost'

def test_inference_source_contains_no_torch_imports():
    from pathlib import Path
    import ast
    for name in ('cuda_driver.py','detector.py','model_runtime.py','optional_accelerator.py'):
        tree=ast.parse((Path(__file__).parents[1]/name).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):assert all(x.name.split('.')[0]!='torch' for x in node.names)
            if isinstance(node,ast.ImportFrom):assert not (node.module or '').startswith('torch')
