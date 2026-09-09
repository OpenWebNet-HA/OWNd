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
