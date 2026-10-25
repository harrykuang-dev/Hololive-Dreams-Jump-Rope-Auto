"""Startup fallback only; no device switch is allowed during gameplay."""
from types import SimpleNamespace
import subprocess,sys
from pathlib import Path
import pytest
import numpy as np
import detector as module


@pytest.fixture
def runtimes(monkeypatch):
    calls=[]
    gpu=SimpleNamespace(backend='tensorrt-fp16')
    dml=SimpleNamespace(backend='onnx-directml')
    monkeypatch.setattr(module,'create_gpu_runtime',lambda *_:calls.append('gpu') or gpu)
    monkeypatch.setattr(module,'DirectMLRopeDetector',lambda *_:calls.append('dml') or dml)
    monkeypatch.setattr(module.FullFrameDetector,'_warmup',lambda self,stopped:calls.append('warm-'+self.runtime.backend))
    return calls,gpu,dml


def test_available_nvidia_keeps_original_gpu_path(runtimes):
    calls,gpu,_=runtimes
    d=module.FullFrameDetector()
    assert d.runtime is gpu and d.backend=='tensorrt-fp16'
    assert calls==['gpu','warm-tensorrt-fp16']


@pytest.mark.parametrize('error',[RuntimeError('no GPU'),ImportError('no torch'),
    ImportError('no TensorRT'),OSError('driver/DLL unavailable'),ValueError('incompatible engine'),
    AttributeError('incompatible TensorRT API'),TypeError('incompatible component API')])
def test_missing_gpu_or_runtime_falls_back_before_any_capture(runtimes,monkeypatch,error):
    calls,_,dml=runtimes
    def fail(*_):raise error
    monkeypatch.setattr(module,'create_gpu_runtime',fail)
    d=module.FullFrameDetector()
    assert d.runtime is dml and d.backend=='onnx-directml' and d.fallback_reason
    assert calls==['dml','warm-onnx-directml']


def test_gpu_warmup_failure_falls_back_once(runtimes,monkeypatch):
    calls,_,dml=runtimes
    def warm(self,_):
        if self.runtime.backend=='tensorrt-fp16':raise RuntimeError('GPU execution failed')
        calls.append('dml-warm')
    monkeypatch.setattr(module.FullFrameDetector,'_warmup',warm)
    d=module.FullFrameDetector()
    assert d.runtime is dml and calls==['gpu','dml','dml-warm']

def test_cancelled_warmup_releases_cuda_runtime_before_propagating(runtimes,monkeypatch):
    calls,gpu,_=runtimes
    gpu.close=lambda:calls.append('closed-gpu')
    def cancel(*_):raise InterruptedError('stop during warmup')
    monkeypatch.setattr(module.FullFrameDetector,'_warmup',cancel)
    with pytest.raises(InterruptedError):module.FullFrameDetector()
    assert calls==['gpu','closed-gpu']

def test_failed_warmup_closes_gpu_before_directml_starts(runtimes,monkeypatch):
    calls,gpu,dml=runtimes;gpu.close=lambda:calls.append('closed-gpu')
    def warm(self,_):
        if self.runtime is gpu:raise RuntimeError('warm failure')
        calls.append('dml-warm')
    monkeypatch.setattr(module.FullFrameDetector,'_warmup',warm)
    assert module.FullFrameDetector().runtime is dml
    assert calls==['gpu','closed-gpu','dml','dml-warm']


def test_explicit_dml_does_not_probe_or_import_gpu(runtimes,monkeypatch):
    calls,_,dml=runtimes
    monkeypatch.setattr(module,'create_gpu_runtime',lambda *_:pytest.fail('GPU probe'))
    assert module.FullFrameDetector(backend='directml').runtime is dml
    assert calls==['dml','warm-onnx-directml']


def test_user_stop_cannot_be_mistaken_for_gpu_failure(runtimes,monkeypatch):
    calls,_,_=runtimes
    def stopped(*_):raise InterruptedError('user stop')
    monkeypatch.setattr(module,'create_gpu_runtime',stopped)
    with pytest.raises(InterruptedError):module.FullFrameDetector()
    assert calls==[]
    with pytest.raises(InterruptedError):module.FullFrameDetector(stopped=lambda:True)
    assert calls==[]


def test_dml_failure_is_reported_and_not_retried_forever(runtimes,monkeypatch):
    def broken(*_):raise RuntimeError('invalid DirectML model')
    monkeypatch.setattr(module,'DirectMLRopeDetector',broken)
    with pytest.raises(RuntimeError,match='invalid DirectML model'):module.FullFrameDetector(backend='directml')


def test_inference_error_after_start_does_not_switch_device(runtimes,monkeypatch):
    calls,gpu,_=runtimes
    def broken(*_a,**_kw):raise RuntimeError('execution interrupted')
    gpu.observe=broken
    d=module.FullFrameDetector()
    with pytest.raises(RuntimeError):d.observe(np.zeros((10,10,3),np.uint8))
    assert 'dml' not in calls


def test_real_dml_initializes_even_when_gpu_imports_are_blocked():
    code='''
import sys,importlib.abc
class NoGpu(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,*args):
        if fullname.split('.')[0] in ('torch','tensorrt','tensorrt_bindings','tensorrt_libs'):
            raise ImportError('GPU package intentionally unavailable')
sys.meta_path.insert(0,NoGpu())
from detector import FullFrameDetector
d=FullFrameDetector()
assert d.backend=='onnx-directml'
assert 'DmlExecutionProvider' in d.runtime.session.get_providers()
assert d.runtime.session.get_session_options().get_session_config_entry('session.disable_cpu_ep_fallback')=='1'
assert 'torch' not in sys.modules and 'tensorrt' not in sys.modules
'''
    subprocess.run([sys.executable,'-X','utf8','-B','-c',code],cwd=Path(__file__).resolve().parents[1],check=True)
