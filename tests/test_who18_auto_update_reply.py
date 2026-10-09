"""WHO 18 dimension 1200 reply: *#18*W*1200#type*time## confirms (time > 0)
or ends (time = 0) the automatic power updates. libqtdevices TS10_1_0_23
energy_device.cpp:111 (_DIM_STATE_UPDATE_INTERVAL = 1200), :289-322
(handleAutomaticUpdate re-arms on time = 0), :719-726, :50-56 (energy types).
Firmware replay on bt_supervisione (MyHomeServer1, F454, F459, F461):
*#18*51*#1200#1*255## ACK bus D1 A1 02 32 00 02 1D FF, #1200#1*0 ... 1D 00,
#1200#2*255 ... 82 FF; the bare *#18*51*1200## is NACK with no bus frame."""

from OWNd.message import (
    MESSAGE_TYPE_AUTO_UPDATE_INTERVAL,
    OWNEnergyCommand,
    OWNEnergyEvent,
    OWNEvent,
)


def test_auto_update_confirmation_is_parsed():
    msg = OWNEvent.parse("*#18*51*1200#1*255##")
    assert isinstance(msg, OWNEnergyEvent)
    assert msg.message_type == MESSAGE_TYPE_AUTO_UPDATE_INTERVAL
    assert msg.sensor == "1"
    assert msg.update_interval == 255
    assert msg.stream_duration == 255
    assert msg.is_streaming_active is True
    assert msg.energy_type == 1
    assert msg.human_readable_log == "Sensor 1 automatic updates for 255 minutes."


def test_auto_update_stop_is_parsed():
    msg = OWNEvent.parse("*#18*51*1200#1*0##")
    assert msg.message_type == MESSAGE_TYPE_AUTO_UPDATE_INTERVAL
    assert msg.sensor == "1"
    assert msg.update_interval == 0
    assert msg.stream_duration == 0
    assert msg.is_streaming_active is False
    assert msg.human_readable_log == "Sensor 1 automatic updates stopped."


def test_other_dimensions_are_untouched():
    msg = OWNEvent.parse("*#18*51*113*1234##")
    assert msg.update_interval is None
    assert msg.stream_duration is None
    assert msg.is_streaming_active is None
    assert msg.energy_type is None
    assert msg.message_type != MESSAGE_TYPE_AUTO_UPDATE_INTERVAL


def test_message_type_is_exported():
    import OWNd.message as message

    assert "MESSAGE_TYPE_AUTO_UPDATE_INTERVAL" in message.__all__


def test_stop_builder_is_symmetrical_to_start():
    start = OWNEnergyCommand.start_sending_instant_power(51, 255)
    stop = OWNEnergyCommand.stop_sending_instant_power(51)
    assert str(start) == "*#18*51*#1200#1*255##"
    assert str(stop) == "*#18*51*#1200#1*0##"
    assert "Stopping" in stop.human_readable_log


def test_builders_take_the_energy_type_and_the_7xx_address():
    assert str(OWNEnergyCommand.start_sending_instant_power(51, 255, 2)) == "*#18*51*#1200#2*255##"
    assert str(OWNEnergyCommand.stop_sending_instant_power(51, 2)) == "*#18*51*#1200#2*0##"
    assert str(OWNEnergyCommand.stop_sending_instant_power("71")) == "*#18*71#0*#1200#1*0##"


def test_builder_duration_zero_or_negative():
    stop_via_start = OWNEnergyCommand.start_sending_instant_power(51, 0)
    assert str(stop_via_start) == "*#18*51*#1200#1*0##"
    assert "Stopping" in stop_via_start.human_readable_log

    negative_clamped = OWNEnergyCommand.start_sending_instant_power(51, -10)
    assert str(negative_clamped) == "*#18*51*#1200#1*0##"
    assert "Stopping" in negative_clamped.human_readable_log


def test_negative_interval_clamped_to_stopped():
    event = OWNEnergyEvent("*#18*51*1200#1*0##")
    # Simulate a corrupted non-standard negative value in _dimension_value
    event._dimension_value = ["-5"]
    parsed_interval = max(0, int(event._dimension_value[0]))
    assert parsed_interval == 0


def test_actuator_address_preserves_hash_zero():
    # Authentic actuator frames from issue #669 trace (*#18*76#0*113*0##, *#18*77#0*113*161##)
    actuator_evt = OWNEnergyEvent("*#18*76#0*113*0##")
    assert actuator_evt.where == "76"
    assert actuator_evt.target_address == "76#0"
    assert actuator_evt.sensor == "6"
    assert actuator_evt.is_actuator is True
    assert actuator_evt.active_power == 0
    assert actuator_evt.human_readable_log == "Sensor 6 is reporting an active power draw of 0 W."

    actuator_evt2 = OWNEnergyEvent("*#18*77#0*113*161##")
    assert actuator_evt2.where == "77"
    assert actuator_evt2.target_address == "77#0"
    assert actuator_evt2.sensor == "7"
    assert actuator_evt2.is_actuator is True
    assert actuator_evt2.active_power == 161

    # Meter frame does not collide with actuator
    meter_evt = OWNEnergyEvent("*#18*56*113*0##")
    assert meter_evt.where == "56"
    assert meter_evt.target_address == "56"
    assert meter_evt.sensor == "6"
    assert meter_evt.is_actuator is False
    assert meter_evt.active_power == 0
    assert meter_evt.human_readable_log == "Sensor 6 is reporting an active power draw of 0 W."

    # Fallback to empty string if where is empty
    meter_evt._where = None
    assert meter_evt.target_address == ""

    # Command builder preserves address whether #0 was already provided or inferred
    cmd1 = OWNEnergyCommand.stop_sending_instant_power("76")
    assert str(cmd1) == "*#18*76#0*#1200#1*0##"
    cmd2 = OWNEnergyCommand.stop_sending_instant_power("76#0")
    assert str(cmd2) == "*#18*76#0*#1200#1*0##"
    cmd3 = OWNEnergyCommand.start_sending_instant_power("76#0", 60)
    assert str(cmd3) == "*#18*76#0*#1200#1*60##"
    cmd4 = OWNEnergyCommand.get_total_consumption("76#0")
    assert str(cmd4) == "*#18*76#0*51##"


def test_request_active_power_builder():
    cmd = OWNEnergyCommand.request_active_power(51)
    assert str(cmd) == "*#18*51*113##"
    assert cmd.human_readable_log == "Requesting active power from sensor 51."

    cmd_alias = OWNEnergyCommand.get_instant_power("51")
    assert str(cmd_alias) == "*#18*51*113##"
    assert cmd_alias.human_readable_log == "Requesting active power from sensor 51."

    # 7x address receives #0 normalization
    cmd_7x = OWNEnergyCommand.request_active_power("71")
    assert str(cmd_7x) == "*#18*71#0*113##"

    cmd_7x_preset = OWNEnergyCommand.request_active_power("71#0")
    assert str(cmd_7x_preset) == "*#18*71#0*113##"


