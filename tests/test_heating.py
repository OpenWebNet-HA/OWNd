"""Regression tests for WHO 4 heating messages."""

from OWNd.message import (
    LOCAL_CONTROL_NORMAL,
    LOCAL_CONTROL_OFF,
    LOCAL_CONTROL_OFFSET,
    LOCAL_CONTROL_OVERRIDE,
    LOCAL_CONTROL_PROTECTION,
    LOCAL_CONTROL_UNKNOWN,
    MESSAGE_TYPE_ACTION,
    MESSAGE_TYPE_LOCAL_TARGET_TEMPERATURE,
    MESSAGE_TYPE_TARGET_TEMPERATURE,
    MESSAGE_TYPE_SECONDARY_TEMPERATURE,
    OWNHeatingCommand,
    OWNHeatingEvent,
)


def test_local_and_central_targets_remain_distinct() -> None:
    local = OWNHeatingEvent("*#4*3*12*0350*3##")
    central = OWNHeatingEvent("*#4*3*14*0250*3##")

    assert local.message_type == MESSAGE_TYPE_LOCAL_TARGET_TEMPERATURE
    assert local.local_set_temperature == 35.0
    assert central.message_type == MESSAGE_TYPE_TARGET_TEMPERATURE
    assert central.set_temperature == 25.0


def test_local_control_states_preserve_raw_values() -> None:
    expected = {
        "00": (0, LOCAL_CONTROL_NORMAL),
        "03": (3, LOCAL_CONTROL_OFFSET),
        "13": (-3, LOCAL_CONTROL_OFFSET),
        "4": (None, LOCAL_CONTROL_OFF),
        "5": (None, LOCAL_CONTROL_PROTECTION),
        "6": (None, LOCAL_CONTROL_OVERRIDE),
        "7": (None, LOCAL_CONTROL_UNKNOWN),
    }

    for raw, state in expected.items():
        event = OWNHeatingEvent(f"*#4*3*13*{raw}##")
        assert (event.local_offset, event.local_control_state) == state
        assert event.local_offset_raw == raw


def test_valve_status_reply_and_request() -> None:
    event = OWNHeatingEvent("*#4*3*19*0*0##")
    command = OWNHeatingCommand.valves_status("3")

    assert event.message_type == MESSAGE_TYPE_ACTION
    assert not event.is_active()
    assert str(command) == "*#4*3*19##"


def test_probe_temperature_dimension_15_events() -> None:
    # Frame 1 from Issue #264: *#4*100*15*1*0200*0001## (probe 1 of zone 0 at 20.0C)
    event1 = OWNHeatingEvent("*#4*100*15*1*0200*0001##")
    assert event1.message_type == MESSAGE_TYPE_SECONDARY_TEMPERATURE
    assert event1.zone == 0
    assert event1.secondary_temperature == [1, 20.0]
    assert event1.probe_temperature == 20.0
    assert "20.0°C" in event1.human_readable_log

    # Frame 2 from Issue #264: *#4*100*15*1*0196*0001## (probe 1 of zone 0 at 19.6C)
    event2 = OWNHeatingEvent("*#4*100*15*1*0196*0001##")
    assert event2.message_type == MESSAGE_TYPE_SECONDARY_TEMPERATURE
    assert event2.secondary_temperature == [1, 19.6]
    assert event2.probe_temperature == 19.6
    assert "19.6°C" in event2.human_readable_log

    # Negative temperature handling
    neg_event = OWNHeatingEvent("*#4*100*15*1*1050*0001##")
    assert neg_event.message_type == MESSAGE_TYPE_SECONDARY_TEMPERATURE
    assert neg_event.secondary_temperature == [1, -5.0]
    assert neg_event.probe_temperature == -5.0

    # Dimension 15 without status parameter
    event_no_status = OWNHeatingEvent("*#4*2*15*1*0215##")
    assert event_no_status.message_type == MESSAGE_TYPE_SECONDARY_TEMPERATURE
    assert event_no_status.secondary_temperature == [1, 21.5]

    # Dimension 15 single value
    event_single = OWNHeatingEvent("*#4*2*15*0215##")
    assert event_single.message_type == MESSAGE_TYPE_SECONDARY_TEMPERATURE
    assert event_single.probe_temperature == 21.5

    # Dimension 15 malformed value
    event_malformed = OWNHeatingEvent("*#4*2*15*9##")
    assert event_malformed.message_type == MESSAGE_TYPE_SECONDARY_TEMPERATURE
    assert event_malformed.probe_temperature is None


def test_probe_temperature_command() -> None:
    cmd = OWNHeatingCommand.get_probe_temperature("100")
    assert str(cmd) == "*#4*100*15##"
    assert "probe temperature" in cmd.human_readable_log
