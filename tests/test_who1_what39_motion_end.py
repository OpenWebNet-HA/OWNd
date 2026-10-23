"""WHO 1 WHAT 39: end of movement reported by a motion detector.

Firmware evidence (F461 ``bt_luci`` SCS -> OWN translator, ``oracle2/hex2own_corpus.tsv``):
the SCS presence-status frame of class ``0x1D`` decodes to ``*1*34*31##`` for value
``00`` (``B8 31 1D 00``) and to ``*1*39*31##`` for value ``01`` (``B8 31 1D 01``).
A Legrand 067226 detector driving an F411 channel at its own address emits both on
that address (OpenWebNet-HA/MyHOME#777).
"""

from OWNd.message import (
    MESSAGE_TYPE_MOTION,
    OWNEvent,
    OWNLightingEvent,
)


def test_what_39_is_the_end_of_movement():
    msg = OWNLightingEvent("*1*39*31##")
    assert msg.message_type == MESSAGE_TYPE_MOTION
    assert msg.motion is False
    assert msg.motion_end is True
    assert msg.is_sensor is True
    assert msg.is_on is None
    assert msg.unknown_state is None
    assert "no longer detects motion" in msg.human_readable_log


def test_what_34_still_means_motion():
    msg = OWNLightingEvent("*1*34*31##")
    assert msg.message_type == MESSAGE_TYPE_MOTION
    assert msg.motion is True
    assert msg.motion_end is False
    assert msg.is_sensor is True
    assert msg.is_on is None


def test_what_39_parses_through_the_factory_with_a_bus_interface():
    msg = OWNEvent.parse("*1*39*52#4#01##")
    assert isinstance(msg, OWNLightingEvent)
    assert msg.where == "52"
    assert msg.interface == "01"
    assert msg.motion_end is True
    assert msg.is_on is None


def test_plain_light_frames_are_not_motion_end():
    for frame in ("*1*0*52##", "*1*1*52##", "*1*19*52##"):
        msg = OWNLightingEvent(frame)
        assert msg.motion_end is False
        assert msg.message_type != MESSAGE_TYPE_MOTION
