"""WHO 1 WHAT 39: end of movement reported by a motion detector.

Evidence:

- specified: the ZigBee OpenWebNet WHO 1 table defines WHAT 34 "movement detected"
  and WHAT 39 "end of movement detected";
- observed on SCS: an F454 with a Legrand 067226 driving an F411 channel at its own
  address 52 sends ``*1*39*52##`` about 45 s (its DIMENSION 7 timeout) after the last
  ``*1*34*52##``, followed by the detector's ``*1*1000#0*52##`` and the F411's
  ``*1*0*52##`` (OpenWebNet-HA/MyHOME#777);
- firmware-observed (OpenWebNet-HA/own-firmware-oracle#56, merged; suite ``who1-motion-detector``,
  emulated F454 2.0.51, F459, F460, F461, MH200N, MH202 and MyHomeServer1): the gateway
  translator turns the SCS presence status frame ``B8 52 1D 00`` into ``*1*34*52##`` and
  ``B8 52 1D 01`` into ``*1*39*52##``. F453 / F453AV decode WHAT 34 but not 39.
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


def test_reporter_trace_end_of_movement_cycle():
    """MyHOME#777 F454 capture: end of movement, detector command, F411 state."""
    end, command, state = (OWNEvent.parse(f) for f in ("*1*39*52##", "*1*1000#0*52##", "*1*0*52##"))
    assert end.motion_end is True and end.is_on is None
    assert command.motion_end is False and command.is_sensor is False
    assert state.motion_end is False and state.is_on is False and state.is_sensor is False


def test_what_39_is_not_motion_for_consumers_that_check_motion():
    """Consumers that act on ``message_type == motion_detected and motion`` keep ignoring WHAT 39."""
    msg = OWNLightingEvent("*1*39*52##")
    assert not (msg.message_type == MESSAGE_TYPE_MOTION and msg.motion)
    assert msg.is_anomaly is False
    assert msg.brightness is None and msg.timer is None
