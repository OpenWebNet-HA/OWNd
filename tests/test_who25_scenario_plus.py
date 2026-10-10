"""WHO 25 WHAT 11-15 are scenario-plus commands (libqtdevices TS10_1_0_23
scenario_device.cpp:37-41 and :163-186). Firmware replay on bt_luci
(MyHomeServer1, F454, F459): all five ACK with a bus frame (B1 01 93 00,
94 00, 95 40, 96 40, 97 00) and are echoed on the monitor port."""

from OWNd.message import OWNCommand, OWNEvent, OWNScenarioPlusCommand, OWNScenarioPlusEvent


def test_builders_send_the_ts10_frames():
    assert str(OWNScenarioPlusCommand.turn_on(11)) == "*25*11#0*11##"
    assert str(OWNScenarioPlusCommand.turn_off(11)) == "*25*12*11##"
    assert str(OWNScenarioPlusCommand.increase(11)) == "*25*13#0#5*11##"
    assert str(OWNScenarioPlusCommand.decrease(11)) == "*25*14#0#5*11##"
    assert str(OWNScenarioPlusCommand.stop(11)) == "*25*15*11##"


def test_commands_and_events_are_routed():
    for frame, action in [
        ("*25*11#0*11##", "on"),
        ("*25*12*11##", "off"),
        ("*25*13#0#5*11##", "increase"),
        ("*25*14#0#5*11##", "decrease"),
        ("*25*15*11##", "stop"),
    ]:
        cmd = OWNCommand.parse(frame)
        assert isinstance(cmd, OWNScenarioPlusCommand)
        assert cmd.action == action
        assert cmd.object == "11"
        assert cmd.human_readable_log == f"Scenario plus 11: {action}."

        event = OWNEvent.parse(frame)
        assert isinstance(event, OWNScenarioPlusEvent)
        assert event.action == action
        assert event.object == "11"


def test_classes_exported_in_all():
    import OWNd.message as message_mod

    assert "OWNScenarioPlusCommand" in message_mod.__all__
    assert "OWNScenarioPlusEvent" in message_mod.__all__


def test_firmware_emitted_forms_parse():
    # bt_luci prints WHERE 1xx for these events (64 corpus lines for 12 and 15)
    event = OWNEvent.parse("*25*12*131##")
    assert isinstance(event, OWNScenarioPlusEvent)
    assert event.action == "off"
    event = OWNEvent.parse("*25*11#121*10##")
    assert event.action == "on"


def test_other_who25_whats_stay_bare_events_and_commands():
    """WHATs outside 11-15, 21-28 and 31/32 keep the PR 82 rule: a bare event / command."""
    assert type(OWNEvent.parse("*25*16*1##")) is OWNEvent
    assert type(OWNCommand.parse("*25*16*1##")) is OWNCommand
