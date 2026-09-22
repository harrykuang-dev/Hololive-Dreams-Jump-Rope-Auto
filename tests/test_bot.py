import pytest

from jump_rope_bot import BotConfig, JumpRopeBot


def test_default_config_is_valid():
    BotConfig().validate()


@pytest.mark.parametrize("interval", [0, 0.01, 0.501])
def test_invalid_interval(interval):
    with pytest.raises(ValueError):
        BotConfig(tap_interval=interval).validate()


def test_key_down_must_be_shorter_than_interval():
    with pytest.raises(ValueError):
        BotConfig(tap_interval=0.04, key_down_time=0.04).validate()


def test_non_positive_duration_is_rejected():
    bot = JumpRopeBot()
    with pytest.raises(ValueError):
        bot.run(0)

