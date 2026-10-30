import json
import logging
from pathlib import Path
import threading
from types import SimpleNamespace
import zipfile

import numpy as np
import pytest

from session_diagnostics import SessionDiagnostics, DiagnosticLogHandler
from diagnostics import RoundDiagnostics


def document(session):
    return json.loads(session.path.read_text(encoding='utf-8'))


def test_single_json_survives_unicode_concurrent_inputs_and_logs(tmp_path):
    session=SessionDiagnostics(tmp_path, {'app_version':'1.3.2'})
    handler=DiagnosticLogHandler(session)
    def write(index):
        for sequence in range(100):
            session.event('focus', title='遊戲／視窗', thread=index, sequence=sequence,monotonic_ns=sequence)
    workers=[threading.Thread(target=write,args=(i,)) for i in range(3)]
    for worker in workers:worker.start()
    for worker in workers:worker.join()
    try:raise RuntimeError('device initialization failed')
    except RuntimeError:
        import sys
        handler.emit(logging.LogRecord('test',logging.ERROR,__file__,1,'初始化失敗',(),sys.exc_info()))
    session.close(stop_reason='error')
    content=document(session)
    assert len([e for e in content['events'] if e['type']=='focus'])==300
    assert 'RuntimeError: device initialization failed' in content['events'][-2]['exception']
    assert content['events'][-1]['stop_reason']=='error'
    assert not list(tmp_path.glob('*.log'))


def test_trace_and_image_budgets_are_explicit_and_do_not_lose_stop_reason(tmp_path):
    session=SessionDiagnostics(tmp_path, trace_limit=0, critical_limit=1000, image_limit=5)
    assert not session.event('observation', trace=True, frame_id=1)
    assert session.image(tmp_path/'early.jpg',b'1234',priority=1)
    assert session.image(tmp_path/'failure.jpg',b'5678',priority=2)
    assert not (tmp_path/'early.jpg').exists()
    assert not session.image(tmp_path/'routine.jpg',b'0000',priority=1)
    session.close(stop_reason='focus_lost')
    final=document(session)['events'][-1]
    assert final['omitted_records']=={'observation':1,'image_evicted':1,'image':1}
    assert set(final['attachments'])=={'failure.jpg'}
    assert final['stop_reason']=='focus_lost'
    with pytest.raises(ValueError,match='outside'):
        session.image(tmp_path.parent/'outside.jpg',b'1')


def test_nonfinite_values_and_user_profile_are_safe_json(tmp_path,monkeypatch):
    monkeypatch.setenv('USERPROFILE',r'C:\Users\private')
    session=SessionDiagnostics(tmp_path)
    session.event('failure',value=float('nan'),other=np.float64(float('inf')),
                  path=r'C:\Users\private\program.exe')
    session.close()
    entry=document(session)['events'][0]
    assert entry['value'] is entry['other'] is None
    assert entry['path']==r'%USERPROFILE%\program.exe'


def test_multi_round_records_and_images_share_only_one_json_and_zip(tmp_path):
    session=SessionDiagnostics(tmp_path,{'app_version':'1.3.2'})
    image=np.zeros((540,960,3),np.uint8)
    for index in (1,2):
        recorder=RoundDiagnostics(tmp_path/f'round-{index:02}.mp4',image,
                                  session=session,round_index=index)
        for frame in range(4):
            recorder.add(image,.2*frame,hud=True,telemetry=dict(phase='round',frame_id=frame+1,
                capture_ns=1_000_000_000+200_000_000*frame,model_ms=180,control_ms=.5,
                rope_xyxy=[1,2,3,4],marker_xyxy=[5,6,7,8],decision='stationary_or_unobserved_motion'))
        recorder.input_event('down',dict(frame_id=4,capture_ns=1_600_000_000,
                                        native_down_begin_ns=1_600_001_000),1_600_002_000)
        recorder.input_event('up',dict(frame_id=4,capture_ns=1_600_000_000,
                                      native_up_begin_ns=1_625_001_000),1_625_002_000,'deadline')
        recorder.close(stop_reason='round_finished',tap_count=1)
        assert recorder.package({'score_limit':None}) is None
        assert recorder.performance['counts']['gaps_over_100ms']==3
        assert recorder.performance['counts']['rope_detected']==4
        assert 'observation_gaps_exceed_motion_history_limit' in recorder.performance['findings']
    session.close(completed_rounds=2)
    archive=session.package()
    with zipfile.ZipFile(archive) as packed:
        assert packed.testzip() is None
        assert [name for name in packed.namelist() if not name.endswith('.jpg')]==['diagnostics.json']
        events=json.loads(packed.read('diagnostics.json'))['events']
        assert len([e for e in events if e['type']=='observation'])==8
        assert len([e for e in events if e['type']=='native_input'])==4
        assert {e['round'] for e in events if e['type']=='round_diagnostics'}=={1,2}
    assert list(tmp_path.rglob('*.json'))==[session.path]
    assert list(tmp_path.rglob('*.zip'))==[session.archive]


def test_zip_failure_retains_readable_json(tmp_path,monkeypatch):
    session=SessionDiagnostics(tmp_path)
    session.event('failure',message='test')
    session.close(stop_reason='error')
    monkeypatch.setattr(session,'_zip',lambda *_:(_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError,match='disk full'):session.package()
    assert document(session)['events'][-1]['stop_reason']=='error'


def test_partial_write_repairs_json_and_retains_original_error(tmp_path):
    session=SessionDiagnostics(tmp_path)
    session.event('first',message='原始記錄')
    stream=session._stream
    class FailOnce:
        fail=True
        def __getattr__(self,key):return getattr(stream,key)
        def write(self,text):
            if self.fail:
                self.fail=False
                stream.write(text[:8])
                raise OSError('disk full')
            return stream.write(text)
    session._stream=FailOnce()
    with pytest.raises(OSError,match='disk full'):
        session.event('second',message='partial')
    session.close(stop_reason='recording_error')
    content=document(session)
    assert [entry['type'] for entry in content['events']]==['first','session_finished']
    assert content['events'][-1]['diagnostic_error']=='disk full'


def test_hardware_inventory_query_failure_is_reported_not_fatal(tmp_path,monkeypatch):
    import hardware_diagnostics as hardware
    import gpu_adapters
    monkeypatch.setattr(hardware,'_windows_hardware',lambda:(_ for _ in ()).throw(TimeoutError('WMI timeout')))
    monkeypatch.setattr(gpu_adapters,'adapter_inventory',lambda:[dict(name='GPU',eligible=False,
                                                                  d3d12_hresult='0x80004005')])
    result=hardware.collect_system(tmp_path)
    assert 'WMI timeout' in result['windows_hardware']['error']
    assert result['dxgi_adapters'][0]['eligible'] is False
    assert 'full_process_list' not in result and 'USERPROFILE' not in result['environment']
