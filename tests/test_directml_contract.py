"""No hidden CPU model execution, same weights and exact output-head arithmetic."""
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
import detector
import gpu_adapters
from model_runtime import DirectMLRopeDetector


def test_cpu_backend_is_explicitly_rejected():
    with pytest.raises(ValueError,match='Only TensorRT or DirectML'):
        detector.FullFrameDetector(backend='cpu')


def test_force_directml_skips_optional_nvidia_components(monkeypatch):
    monkeypatch.setenv('JUMPROPE_BACKEND','directml')
    monkeypatch.setattr(detector,'create_gpu_runtime',lambda *_:pytest.fail('NVIDIA probe'))
    monkeypatch.setattr(detector,'DirectMLRopeDetector',lambda *_:SimpleNamespace(backend='onnx-directml'))
    monkeypatch.setattr(detector.FullFrameDetector,'_warmup',lambda *_:None)
    assert detector.FullFrameDetector().backend=='onnx-directml'


def test_missing_directml_never_uses_cpu_provider(monkeypatch):
    import onnxruntime as ort
    monkeypatch.setattr(ort,'get_available_providers',lambda:['CPUExecutionProvider'])
    monkeypatch.setattr(ort,'InferenceSession',lambda *_a,**_k:pytest.fail('CPU session'))
    with pytest.raises(RuntimeError,match='CPU inference is disabled'):DirectMLRopeDetector('unused')


def test_no_hardware_gpu_stops_before_session_creation(monkeypatch):
    import onnxruntime as ort
    monkeypatch.setattr(ort,'get_available_providers',lambda:['DmlExecutionProvider','CPUExecutionProvider'])
    monkeypatch.setattr(gpu_adapters,'hardware_adapters',lambda:[])
    monkeypatch.setattr(ort,'InferenceSession',lambda *_a,**_k:pytest.fail('software/CPU session'))
    with pytest.raises(RuntimeError,match='No DirectX 12 hardware GPU'):DirectMLRopeDetector('unused')


def test_directml_session_disallows_cpu_placement_and_runtime_retry(monkeypatch):
    import onnxruntime as ort
    sessions=[]
    class Session:
        def __init__(self,path,sess_options,providers):
            sessions.append((sess_options,providers));self.disabled=False
        def disable_fallback(self):self.disabled=True
        def get_providers(self):return ['DmlExecutionProvider','CPUExecutionProvider']
        def get_inputs(self):return [SimpleNamespace(name='images',shape=[1,3,640,640],type='tensor(float)')]
        def get_outputs(self):return [SimpleNamespace(name='output0')]
    monkeypatch.setattr(ort,'get_available_providers',lambda:['DmlExecutionProvider','CPUExecutionProvider'])
    monkeypatch.setattr(gpu_adapters,'hardware_adapters',lambda:[dict(device_id=1,name='AMD GPU')])
    monkeypatch.setattr(ort,'InferenceSession',Session)
    d=DirectMLRopeDetector('unused');o,providers=sessions[0]
    assert not o.enable_mem_pattern and o.execution_mode==ort.ExecutionMode.ORT_SEQUENTIAL
    assert o.get_session_config_entry('session.disable_cpu_ep_fallback')=='1'
    assert d.session.disabled and providers==[('DmlExecutionProvider',{'device_id':1})]


def test_actual_directml_provider_must_be_present_after_initialization(monkeypatch):
    import onnxruntime as ort
    monkeypatch.setattr(ort,'get_available_providers',lambda:['DmlExecutionProvider','CPUExecutionProvider'])
    monkeypatch.setattr(gpu_adapters,'hardware_adapters',lambda:[dict(device_id=0,name='GPU')])
    monkeypatch.setattr(ort,'InferenceSession',lambda *_a,**_k:SimpleNamespace(
        disable_fallback=lambda:None,get_providers=lambda:['CPUExecutionProvider']))
    with pytest.raises(RuntimeError,match='refusing CPU inference'):DirectMLRopeDetector('unused')


def test_directml_head_preserves_every_weight_initializer():
    import onnx
    root=Path(__file__).resolve().parents[1]/'models'
    a,b=[onnx.load(str(root/name)) for name in ['rope.onnx','rope.directml.onnx']]
    assert [x.SerializeToString() for x in a.graph.initializer]==[x.SerializeToString() for x in b.graph.initializer]
    assert len(a.graph.initializer)==204
    assert not any(n.op_type=='Mod' for n in b.graph.node)
    assert json.loads((root/'directml-graph.json').read_text())['all_initializer_bytes_equal']


def test_remainder_conversion_is_exact_for_entire_index_domain():
    indices=np.arange(16800,dtype=np.int64);floats=indices.astype(np.float32)
    actual=(floats-np.floor(floats/np.float32(2))*np.float32(2)).astype(np.int64)
    assert np.array_equal(actual,indices%2)


@pytest.mark.parametrize('broken',[False,True])
def test_cuda_mask_isolated_only_for_dml_session_creation_and_restored(monkeypatch,broken):
    import os,onnxruntime as ort
    monkeypatch.setenv('CUDA_VISIBLE_DEVICES','-1')
    monkeypatch.setattr(gpu_adapters,'hardware_adapters',lambda:[dict(device_id=0,name='GPU')])
    def session(*_a,**_k):
        assert 'CUDA_VISIBLE_DEVICES' not in os.environ
        if broken:raise RuntimeError('GPU init failed')
        return SimpleNamespace(disable_fallback=lambda:None,get_providers=lambda:['DmlExecutionProvider'],
            get_inputs=lambda:[SimpleNamespace(name='images',shape=[1,3,640,640],type='tensor(float)')],
            get_outputs=lambda:[SimpleNamespace(name='output0')])
    monkeypatch.setattr(ort,'get_available_providers',lambda:['DmlExecutionProvider','CPUExecutionProvider'])
    monkeypatch.setattr(ort,'InferenceSession',session)
    if broken:
        with pytest.raises(RuntimeError):DirectMLRopeDetector('unused')
    else:DirectMLRopeDetector('unused')
    assert os.environ['CUDA_VISIBLE_DEVICES']=='-1'
