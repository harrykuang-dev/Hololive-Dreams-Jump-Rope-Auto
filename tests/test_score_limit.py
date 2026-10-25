from dataclasses import replace
from types import SimpleNamespace
import cv2,numpy as np,pytest
from score_limit import HudScoreReader,ScoreLimit
from batch_session import SessionConfig,BatchSession
from window_control import BotConfig
from tests.test_event_controller import simulated
from tests.test_session import mutex


def render(value):
    reader=HudScoreReader();frame=np.zeros((540,960,3),np.uint8)
    for i,c in enumerate(str(value)):
        glyph=reader.templates[int(c)][0].astype(np.uint8)*255
        frame[55:91,40+i*29:64+i*29]=glyph[:,:,None]
    return frame


@pytest.mark.parametrize('value',[0,1,7,10,99,100,150,200,999])
def test_numeric_hud_examples(value):assert HudScoreReader().read(render(value))==value


def test_unknown_or_occluded_hud_never_invents_a_score():
    r=HudScoreReader();assert r.read(np.zeros((540,960,3),np.uint8)) is None
    image=render(150);image[45:125,35:155]=255
    assert r.read(image) is None


@pytest.mark.parametrize('value',[0,-1,1000,True,1.2,'100'])
def test_invalid_score_limits(value):
    for factory in [SessionConfig,BotConfig]:
        with pytest.raises(ValueError):factory(score_limit=value).validate()
    with pytest.raises(ValueError):ScoreLimit(value)


def monitor(values,target=100):
    values=iter(values)
    return ScoreLimit(target,reader=SimpleNamespace(read=lambda _frame:next(values)))


def test_needs_fresh_repeated_readings_and_stays_latched():
    guard=monitor([99,99,100,None,100,100])
    results=[guard.observe(None,i*100_000_000) for i in range(6)]
    assert results==[False,False,False,False,False,True]
    assert guard.observe(None,900_000_000) and guard.score==100


def test_implausible_jump_does_not_stop_the_round():
    guard=monitor([10,10,900,900,11,11])
    assert not any(guard.observe(None,i*100_000_000) for i in range(6))
    assert guard.score==11


def test_unknown_near_limit_does_not_return_to_slow_polling():
    guard=monitor([99,None,100,100])
    assert not guard.observe(None,1_000_000_000)
    assert not guard.observe(None,1_016_000_000)
    assert not guard.observe(None,1_032_000_000)
    assert guard.observe(None,1_048_000_000)


def test_repeated_timestamp_cannot_confirm_or_consume_next_reading():
    guard=monitor([100,100])
    assert not guard.observe(None,1_000_000_000)
    assert not guard.observe(None,1_000_000_000)
    assert guard.observe(None,1_016_000_000)


def test_threshold_stops_inputs_but_keeps_capturing_until_result(simulated,monkeypatch):
    import score_limit
    bot,native,seen=simulated;bot.config=replace(bot.config,score_limit=100)
    reads=[];notifications=[];bot.score_notify=notifications.append
    bot.gate_type.normalized=staticmethod(lambda f:f)
    class Guard:
        score=100
        def __init__(self,limit):assert limit==100
        def observe(self,*_):reads.append(1);return True
    monkeypatch.setattr(score_limit,'ScoreLimit',Guard)
    bot.detector.observe=lambda *_a,**_k:pytest.fail('model inference after score limit')
    bot.run()
    assert bot.stop_reason=='round_finished' and len(seen)==7
    assert not native and bot.tap_count==0 and notifications==[100]
    assert bot.score_limit_reached and not bot._stop.is_set()


def test_unlimited_never_constructs_or_runs_score_reader(simulated,monkeypatch):
    import score_limit
    monkeypatch.setattr(score_limit,'ScoreLimit',lambda *_:pytest.fail('OCR in unlimited mode'))
    bot,native,_=simulated;bot.run()
    assert bot.tap_count==1 and len(native)==2


def test_same_limit_applies_to_each_round_and_batch_still_completes(mutex):
    configs=[]
    def factory(config,**_):
        configs.append(config)
        return SimpleNamespace(run=lambda:None,tap_count=5,stop_reason='round_finished',round_started_at=1,_hwnd=123)
    session=BatchSession(SessionConfig(rounds=3,score_limit=100),bot_factory=factory,
                         get_key_state=lambda _:0,result_wait=lambda *_a,**_k:True)
    session.run()
    assert session.completed_rounds==3 and session.inputs==15
    assert len(configs)==3 and all(c.score_limit==100 for c in configs)
