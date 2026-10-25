"""Optional component activation must not be required by the DirectML core."""
import json,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
import optional_accelerator as module


@pytest.fixture
def root(tmp_path,monkeypatch):
    monkeypatch.setattr(module,'_activated',None)
    monkeypatch.setattr(module,'_dll_handles',[])
    monkeypatch.setattr(module,'_registered',set())
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    monkeypatch.setattr(sys,'executable',str(tmp_path/'app.exe'))
    return tmp_path


def test_missing_component_is_optional(root):
    assert module.activate_tensorrt_component() is None


def test_incompatible_component_is_rejected_before_dll_loading(root,monkeypatch):
    folder=root/'accelerators/tensorrt';folder.mkdir(parents=True)
    (folder/'component.json').write_text(json.dumps(dict(format=1,python=[3,12],architecture='win_amd64')))
    monkeypatch.setattr(module.os,'add_dll_directory',lambda _:pytest.fail('DLL before ABI check'))
    with pytest.raises(RuntimeError,match='incompatible'):module.activate_tensorrt_component()


def test_partial_dll_registration_is_closed_on_failure(root,monkeypatch):
    folder=root/'accelerators/tensorrt';(folder/'tensorrt_libs').mkdir(parents=True)
    (folder/'tensorrt_bindings').mkdir()
    (folder/'component.json').write_text(json.dumps(dict(format=2,python=list(sys.version_info[:2]),architecture='win_amd64',versions={'tensorrt-cu12':'10.13.3.9.post1'})))
    closed=[];calls=[]
    def add(path):
        calls.append(path)
        if len(calls)==2:raise OSError('component unavailable')
        return SimpleNamespace(close=lambda:closed.append(path))
    monkeypatch.setattr(module.os,'add_dll_directory',add)
    with pytest.raises(OSError):module.activate_tensorrt_component()
    assert len(closed)==1 and not module._dll_handles and module._activated is None
