"""Verify product code and resources without game access."""
import argparse,hashlib,json,marshal
from pathlib import Path
from PyInstaller.archive.readers import CArchiveReader

def verify(executable,root):
    archive=CArchiveReader(str(executable));modules=archive.open_embedded_archive('PYZ.pyz')
    names=['main_ui','app_locale','app_settings','batch_session','jump_rope_bot','window_control',
        'detector','model_runtime','cuda_driver','input_pulse','input_timer','fluent_theme','global_hotkey',
        'timing_control','vision','shared_gate','session_flow','diagnostics','gpu_adapters','optional_accelerator','score_limit',
        'focus_recovery','session_diagnostics','hardware_diagnostics','diagnostic_metrics']
    names += ['controller.'+p.stem for p in (root/'controller').glob('*.py') if p.stem!='__init__']
    hashes={}
    for name in names:
        path=root/(name.replace('.','/')+'.py')
        frozen=marshal.loads(archive.extract(name)) if name=='main_ui' else modules.extract(name)
        expected=compile(path.read_text(encoding='utf-8'),frozen.co_filename,'exec',dont_inherit=True)
        if frozen!=expected:raise ValueError('Bundled code differs: '+name)
        hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    assert not any(n.startswith(('archive.','yolo_rope.','collector.','baseline_next.','ultralytics.')) for n in modules.toc)
    assert not any(n=='torch' or n.startswith(('torch.','tensorrt')) for n in modules.toc)
    internal=executable.parent/'_internal';resources=['models/control.json','models/rope.onnx','models/rope.fp16.onnx',
        'models/rope.directml.onnx','models/directml-graph.json',
        'models/AGPL-3.0.txt','assets/jump-rope.ico','assets/hopping-rope-logo.png','assets/score-digits.npz','LICENSE','NOTICE.md']
    for name in resources:
        assert (internal/name).read_bytes()==(root/name).read_bytes(),name
    assert not (internal/'archive').exists()
    assert not (internal/'annotations').exists() and not (internal/'training').exists()
    assert not (internal/'models/rope.engine').exists() and not (internal/'models/rope.pt').exists()
    assert list((internal/'third_party/runtime').rglob('*LICENSE*')), 'Dependency licenses missing'
    ort=internal/'onnxruntime/capi'
    assert (ort/'onnxruntime_pybind11_state.pyd').exists(), 'ONNX runtime missing'
    assert (ort/'DirectML.dll').exists(), 'DirectML library missing'
    assert not (ort/'onnxruntime_providers_cuda.dll').exists(), 'GPU ONNX package bundled instead of CPU package'
    assert not (internal/'torch').exists() and not (internal/'tensorrt_libs').exists()
    assert not list(internal.rglob('nvcuda.dll')), 'Do not redistribute the system GPU driver'
    return dict(status='verified',directml_bundled=True,cpu_inference=False,tensorrt_optional=True,
        source_modules=hashes,resources=resources,archive_bundled=False,
        research_bundled=False,gameplay_started=False,executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest())
def main():
    p=argparse.ArgumentParser();p.add_argument('executable',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=verify(a.executable,Path(__file__).resolve().parents[1]);a.output.write_text(json.dumps(result,indent=2),encoding='utf-8');print('Verified',len(result['source_modules']),'source modules')
if __name__=='__main__':main()
