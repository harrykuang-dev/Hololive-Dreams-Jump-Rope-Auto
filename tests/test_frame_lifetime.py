"""GPU observations must survive normal inference, without renewing capture age."""
from types import SimpleNamespace
import numpy as np
import pytest
from controller.policy import ArcCarryPolicy
from jump_rope_bot import JumpRopeBot
from timing_control import control_config


def observation(policy):
    return SimpleNamespace(features=policy.templates[0,40].copy(),
                           marker_xyxy=(470,180,490,195))


def test_backends_share_timing_without_fixed_frame_age_cutoff():
    dml=control_config(.73,backend='onnx-directml')
    gpu=control_config(.73,backend='tensorrt-fp16')
    assert dml==gpu and gpu['frame_validity_ms'] is None
    assert {k:v for k,v in dml.items() if k!='frame_validity_ms'}=={
        k:v for k,v in gpu.items() if k!='frame_validity_ms'}
    assert gpu==control_config(.73)


def test_actual_backend_is_wired_into_bot_controller():
    for backend,lifetime in [('onnx-directml',None),('tensorrt-fp16',None)]:
        bot=JumpRopeBot(detector=SimpleNamespace(backend=backend))
        assert bot.control.config['frame_validity_ms']==lifetime


@pytest.mark.parametrize('backend',['onnx-directml','tensorrt-fp16'])
@pytest.mark.parametrize('age',[19,29,31,40,60,80,200])
def test_slow_processing_is_not_rejected_only_for_age(backend,age):
    p=ArcCarryPolicy('test',control_config(backend=backend));stamp=1_000_000_000
    d=p.observe(observation(p),stamp,(540,960),now_ns=stamp+age*1_000_000)
    assert d.reason!='expired_frame'
    assert d.capture_ns==stamp
    assert d.valid_until_ns is None


def test_explicit_bounded_policy_still_expires():
    p=ArcCarryPolicy('bounded',dict(control_config(),frame_validity_ms=30))
    stamp=1_000_000_000
    d=p.observe(observation(p),stamp,(540,960),now_ns=stamp+31_000_000)
    assert not d.jump and d.reason=='expired_frame'
    assert d.valid_until_ns==stamp+30_000_000


def test_dml_elapsed_inference_is_subtracted_from_crossing_eta():
    a=ArcCarryPolicy('a',control_config(backend='onnx-directml'))
    b=ArcCarryPolicy('b',control_config(backend='onnx-directml'))
    stamp=1_000_000_000
    first=a.observe(observation(a),stamp,(540,960),now_ns=stamp+10_000_000)
    delayed=b.observe(observation(b),stamp,(540,960),now_ns=stamp+20_000_000)
    assert a.last_diagnostic['event_center_ms']-b.last_diagnostic['event_center_ms']==pytest.approx(10)
    assert first.valid_until_ns is None and delayed.valid_until_ns is None
    assert np.array_equal(a.weights,b.weights)


def test_stop_with_dml_backend_never_starts_capture(monkeypatch):
    bot=JumpRopeBot(detector=SimpleNamespace(backend='onnx-directml'))
    bot.stop()
    monkeypatch.setattr(bot,'focus_game',lambda:pytest.fail('focus after stop'))
    bot.run()
    assert bot.stop_reason=='stopped' and bot.tap_count==0
