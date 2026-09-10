"""Exhaustive tests targeting every remaining branch and dimension in OWNd.message."""
from __future__ import annotations

import datetime
from unittest.mock import patch
import pytest

from OWNd.message import (
    CLIMATE_MODE_AUTO,
    CLIMATE_MODE_COOL,
    CLIMATE_MODE_HEAT,
    CLIMATE_MODE_OFF,
    MESSAGE_TYPE_MAIN_HUMIDITY,
    MESSAGE_TYPE_MODE_TARGET,
    OWNAlarmEvent,
    OWNAutomationCommand,
    OWNAutomationEvent,
    OWNAuxEvent,
    OWNAVCommand,
    OWNCENEvent,
    OWNCENPlusEvent,
    OWNCommand,
    OWNDryContactEvent,
    OWNEnergyCommand,
    OWNEnergyEvent,
    OWNEvent,
    OWNGatewayCommand,
    OWNGatewayEvent,
    OWNHeatingCommand,
    OWNHeatingEvent,
    OWNLightingCommand,
    OWNLightingEvent,
    OWNMessage,
    OWNScenarioEvent,
    OWNSceneEvent,
    OWNSoundCommand,
    OWNSoundEvent,
)


class TestMessageExhaustiveCoverage:
    """Cover all remaining protocol branches in OWNd.message."""

    def test_own_event_factory_routing(self) -> None:
        # Scenario event factory routing (WHO 0)
        ev_scenario = OWNEvent.parse("*0*1*11##")
        assert isinstance(ev_scenario, OWNScenarioEvent)
        assert ev_scenario.scenario == 1
        assert ev_scenario.control_panel == "11"

        # CEN event factory routing (WHO 15)
        ev_cen = OWNEvent.parse("*15*1*12##")
        assert isinstance(ev_cen, OWNCENEvent)

        # Invalid frame returns None
        assert OWNEvent.parse("invalid") is None
        assert OWNScenarioEvent.parse("invalid") is None

    def test_lighting_dimmer_presets_and_sensors(self) -> None:
        # Dimmed preset values: WHAT in 2..10
        for preset in range(2, 11):
            msg = OWNLightingEvent(f"*1*{preset}*21##")
            assert msg.is_on is True
            assert msg.brightness_preset == preset
            assert f"brightness level {preset}" in msg.human_readable_log

        # Timed states: 11..18
        for what_code, expected_sec in [
            (11, 60),
            (12, 120),
            (13, 180),
            (14, 240),
            (15, 300),
            (16, 900),
            (17, 30),
            (18, 0.5),
        ]:
            msg_timer = OWNLightingEvent(f"*1*{what_code}*21##")
            assert f"for {expected_sec}s" in msg_timer.human_readable_log

        # Blinking states: 20..29
        msg_blink_ev = OWNLightingEvent("*1*20*21##")
        assert msg_blink_ev.blinker == 0.5

        # Motion detected state 34
        msg_mot = OWNLightingEvent("*1*34*21##")
        assert msg_mot.motion is True

        # PIR sensor dimensions: sensitivity (5), timeout (7), illuminance (6), blinker (1)
        msg_sens = OWNLightingEvent("*#1*21*5*3##")
        assert msg_sens.pir_sensitivity == 3
        assert "sensitivity" in msg_sens.human_readable_log

        msg_timeout = OWNLightingEvent("*#1*21*7*0*1*0##")
        assert msg_timeout.motion_timeout == datetime.timedelta(minutes=1)
        assert "timeout" in msg_timeout.human_readable_log

        msg_lux = OWNLightingEvent("*#1*21*6*450##")
        assert msg_lux.illuminance == 450
        assert "illuminance" in msg_lux.human_readable_log

        msg_blink = OWNLightingEvent("*#1*21*1*1##")
        assert msg_blink.brightness == -99 or msg_blink.is_on is not None

        # Brightness 0 setting state 0 (lines 497-498)
        msg_b0 = OWNLightingEvent("*#1*21*1*100##")
        assert msg_b0.brightness == 0
        assert msg_b0.is_on is False

    def test_lighting_command_builders(self) -> None:
        # status and brightness getters
        cmd_status = OWNLightingCommand.status("21")
        assert str(cmd_status) == "*#1*21##"

        cmd_b = OWNLightingCommand.get_brightness("21")
        assert str(cmd_b) == "*#1*21*1##"

        cmd_sens = OWNLightingCommand.get_pir_sensitivity("21")
        assert str(cmd_sens) == "*#1*21*5##"

        cmd_lux = OWNLightingCommand.get_illuminance("21")
        assert str(cmd_lux) == "*#1*21*6##"

        cmd_time = OWNLightingCommand.get_motion_timeout("21")
        assert str(cmd_time) == "*#1*21*7##"

        # timed switch on & off
        cmd_on_timed = OWNLightingCommand.switch_on("21", _transition=15)
        assert str(cmd_on_timed) == "*1*1#15*21##"

        cmd_off_timed = OWNLightingCommand.switch_off("21", _transition=10)
        assert str(cmd_off_timed) == "*1*0#10*21##"

    def test_automation_states_and_commands(self) -> None:
        # Opening (WHAT=1), Closing (WHAT=2), Stopped (WHAT=0)
        ev_up = OWNAutomationEvent("*2*1*31##")
        assert ev_up.is_opening is True
        assert ev_up.is_closing is False

        ev_down = OWNAutomationEvent("*2*2*31##")
        assert ev_down.is_closing is True
        assert ev_down.is_opening is False

        ev_stop = OWNAutomationEvent("*2*0*31##")
        assert ev_stop.state == 0
        assert ev_stop.is_opening is False
        assert ev_stop.is_closing is False

        # Dimension 10 (intermediate position: state=10, position=0 -> closed)
        ev_pos = OWNAutomationEvent("*#2*31*10*10*0##")
        assert ev_pos.is_closed is True

        # Automation commands
        assert str(OWNAutomationCommand.status("31")) == "*#2*31##"
        assert str(OWNAutomationCommand.raise_shutter("31")) == "*2*1*31##"
        assert str(OWNAutomationCommand.lower_shutter("31")) == "*2*2*31##"
        assert str(OWNAutomationCommand.stop_shutter("31")) == "*2*0*31##"
        assert str(OWNAutomationCommand.set_shutter_level("31", 50)) == "*#2*31*#11#001*50##"

    def test_heating_dimensions_and_commands(self) -> None:
        # Mode Target with temperature string (WHAT=1#0215)
        ev_target = OWNHeatingEvent("*4*1#0215*1##")
        assert ev_target.message_type == MESSAGE_TYPE_MODE_TARGET
        assert ev_target.set_temperature == 21.5
        assert "21.5" in ev_target.human_readable_log

        # Fan coil / valves state (dimension 19 requires 2 values)
        ev_valves = OWNHeatingEvent("*#4*1*19*0*0##")
        assert ev_valves.message_type is not None

        # Main humidity sensor (dimension 60)
        ev_hum = OWNHeatingEvent("*#4*1*60*55##")
        assert ev_hum.message_type == MESSAGE_TYPE_MAIN_HUMIDITY
        assert ev_hum.main_humidity == 55.0

        # Measured temperature
        ev_temp = OWNHeatingEvent("*#4*1*0*0220##")
        assert ev_temp.main_temperature == 22.0

        # Heating command builders
        assert str(OWNHeatingCommand.status("1")) == "*#4*1##"

        # set_mode off & auto
        cmd_off = OWNHeatingCommand.set_mode("1", mode=CLIMATE_MODE_OFF)
        assert cmd_off is not None
        cmd_auto = OWNHeatingCommand.set_mode("1", mode=CLIMATE_MODE_AUTO)
        assert cmd_auto is not None

        # set_temperature edge clamping (<5.0 and >40.0 and zone 0)
        cmd_low = OWNHeatingCommand.set_temperature("1", 2.0, mode=CLIMATE_MODE_HEAT)
        assert "0050" in str(cmd_low)

        cmd_high = OWNHeatingCommand.set_temperature("1", 45.0, mode=CLIMATE_MODE_HEAT)
        assert "0400" in str(cmd_high)

        cmd_zone0 = OWNHeatingCommand.set_temperature("0", 21.0, mode=CLIMATE_MODE_HEAT)
        assert "*#4*#0*" in str(cmd_zone0)

        cmd_heat_mode = OWNHeatingCommand.set_temperature("1", 22.0, mode=CLIMATE_MODE_HEAT)
        assert "*#4*#1*#14*0220*1##" == str(cmd_heat_mode)

        cmd_cool_mode = OWNHeatingCommand.set_temperature("1", 22.0, mode=CLIMATE_MODE_COOL)
        assert "*#4*#1*#14*0220*2##" == str(cmd_cool_mode)

    def test_burglar_alarm_subsystem(self) -> None:
        # Alarm events: maintenance (0), activation (1), engage (8), technical alarm (12), intrusion alarm (15)
        ev_maint = OWNAlarmEvent("*5*0*0##")
        assert ev_maint.state_code == 0
        assert ev_maint.is_disarmed is True
        assert ev_maint.state_name == "maintenance"

        ev_eng = OWNAlarmEvent("*5*8*0##")
        assert ev_eng.state_code == 8
        assert ev_eng.is_engaged is True
        assert ev_eng.is_armed_away is True

        ev_tech = OWNAlarmEvent("*5*12*0##")
        assert ev_tech.state_code == 12
        assert ev_tech.is_alarm is True

        ev_int = OWNAlarmEvent("*5*15*0##")
        assert ev_int.state_code == 15
        assert ev_int.is_alarm is True

        ev_act = OWNAlarmEvent("*5*11*0##")
        assert ev_act.is_armed_home is True
        assert ev_act.general is True

        # Sensor in non-zero zone reporting (where="12" -> zone 1, sensor 2)
        ev_sensor = OWNAlarmEvent("*5*1*12##")
        assert ev_sensor.zone == 1
        assert ev_sensor.sensor == 2
        assert "Sensor 2 in zone 1 is reporting" in ev_sensor.human_readable_log

    def test_auxiliary_and_dry_contact(self) -> None:
        # Auxiliary (WHO 9): WHAT 1 ('ON') and WHAT 0 ('OFF')
        aux_on = OWNAuxEvent("*9*1*1##")
        assert "is set to 'ON'" in aux_on.human_readable_log

        aux_off = OWNAuxEvent("*9*0*1##")
        assert "is set to 'OFF'" in aux_off.human_readable_log

        # Dry contact (WHO 25)
        dc_ev = OWNDryContactEvent("*25*31*1##")
        assert dc_ev.where == "1"

    def test_gateway_diagnostics_dimensions(self) -> None:
        # Dimension 1: Date (*#13**1*day_of_week*day*month*year##)
        gw_date = OWNGatewayEvent("*#13**1*4*10*09*2026##")
        assert gw_date._date.year == 2026
        assert gw_date._date.month == 9
        assert gw_date._date.day == 10

        # Dimension 10: IP Address
        gw_ip = OWNGatewayEvent("*#13**10*192*168*1*50##")
        assert gw_ip._ip_address == "192.168.1.50"

        # Dimension 11: Netmask
        gw_mask = OWNGatewayEvent("*#13**11*255*255*255*0##")
        assert gw_mask._netmask == "255.255.255.0"

        # Dimension 12: MAC Address
        gw_mac = OWNGatewayEvent("*#13**12*0*3*80*0*18*52##")
        assert "00:03:50:00:12:34" in str(gw_mac._mac_address)

        # Dimension 15: Model Name
        gw_model = OWNGatewayEvent("*#13**15*4##")
        assert gw_model._device_type == "MH200"

        # Dimension 16: Firmware version
        gw_fw = OWNGatewayEvent("*#13**16*2*0*1##")
        assert gw_fw._firmware_version == "2.0.1"

        # Dimension 19: Uptime (days*hours*minutes*seconds)
        gw_uptime = OWNGatewayEvent("*#13**19*1*2*30*45##")
        assert gw_uptime._uptime is not None
        assert gw_uptime._uptime.days == 1

        # Malformed / incomplete uptime triggers (IndexError, TypeError, ValueError)
        with patch("OWNd.message.datetime.timedelta", side_effect=ValueError("bad timedelta")):
            gw_bad_uptime = OWNGatewayEvent("*#13**19*1*2*3*4##")
            assert gw_bad_uptime._uptime is None

        # Dimension 23: Kernel version
        gw_kern = OWNGatewayEvent("*#13**23*3*10*0##")
        assert gw_kern._kernel_version == "3.10.0"

        # Dimension 24: Distribution version
        gw_dist = OWNGatewayEvent("*#13**24*1*2*3##")
        assert gw_dist._distribution_version == "1.2.3"

        # Gateway request dimension check
        gw_req = OWNGatewayCommand("*#13**0##")
        assert gw_req.is_request is True

        # Gateway set_datetime, set_date, set_time with timezone
        gw_set_time = OWNGatewayCommand.set_datetime_to_now("UTC")
        assert "*#13**#22*" in str(gw_set_time)

        gw_set_date = OWNGatewayCommand.set_date_to_today("UTC")
        assert "*#13**#1*" in str(gw_set_date)

        gw_set_t = OWNGatewayCommand.set_time_to_now("UTC")
        assert "*#13**#0*" in str(gw_set_t)

    def test_cen_and_scene_events(self) -> None:
        # CEN Event: states None (press), 1 (short release), 2 (long release), 3 (held)
        cen_press = OWNCENEvent("*15*1*11##")
        assert cen_press.is_pressed is True

        cen_short = OWNCENEvent("*15*1#1*11##")
        assert cen_short.is_released_after_short_press is True

        cen_long = OWNCENEvent("*15*1#2*11##")
        assert cen_long.is_released_after_long_press is True

        cen_held = OWNCENEvent("*15*1#3*11##")
        assert cen_held.is_held is True

        # Scene Event: states 1 (started), 2 (stopped), 3 (enabled), 4 (disabled)
        sc_start = OWNSceneEvent("*17*1*1##")
        assert sc_start.is_on is True

        sc_stop = OWNSceneEvent("*17*2*1##")
        assert sc_stop.is_on is False

        sc_en = OWNSceneEvent("*17*3*1##")
        assert sc_en.is_enabled is True

        sc_dis = OWNSceneEvent("*17*4*1##")
        assert sc_dis.is_enabled is False

    def test_cenplus_rotary_and_button_ranges(self) -> None:
        # Rotary states: 22 (slow CW), 23 (fast CW), 24 (slow CCW)
        ev_rot22 = OWNCENPlusEvent("*25*22#1*212##")
        assert ev_rot22.is_held is True

        ev_rot23 = OWNCENPlusEvent("*25*23#1*212##")
        assert ev_rot23.is_still_held is True

        ev_rot24 = OWNCENPlusEvent("*25*24#1*212##")
        assert ev_rot24.is_released is True

        # Button ranges for human readable log
        ev_btn10 = OWNCENPlusEvent("*25*21#10*212##")
        assert "Button 10" in ev_btn10.human_readable_log

        ev_btn20 = OWNCENPlusEvent("*25*21#20*212##")
        assert "Button 20" in ev_btn20.human_readable_log

        ev_btn30 = OWNCENPlusEvent("*25*21#30*212##")
        assert "Button 30" in ev_btn30.human_readable_log

    def test_sound_diffusion_commands(self) -> None:
        # Stereo on / off commands
        cmd_turn_on = OWNSoundCommand.turn_on("21")
        assert str(cmd_turn_on) == "*16*3*21##"

        cmd_turn_off = OWNSoundCommand.turn_off("21")
        assert str(cmd_turn_off) == "*16*13*21##"

        # Volume up / down commands
        cmd_vol_up = OWNSoundCommand.volume_up("21")
        assert str(cmd_vol_up) == "*16*1001*21##"

        cmd_vol_down = OWNSoundCommand.volume_down("21")
        assert str(cmd_vol_down) == "*16*1000*21##"

        # Zone validation error (where must not be empty)
        with pytest.raises(ValueError, match="where must identify an audio zone"):
            OWNSoundCommand.select_source("", 1)

    def test_command_factory_specialized_dispatch(self) -> None:
        # OWNCommand.parse dispatching specialized classes
        assert isinstance(OWNCommand.parse("*1*1*11##"), OWNLightingCommand)
        assert isinstance(OWNCommand.parse("*2*1*31##"), OWNAutomationCommand)
        assert isinstance(OWNCommand.parse("*4*1*1##"), OWNHeatingCommand)
        assert isinstance(OWNCommand.parse("*16*1*21##"), OWNSoundCommand)
        assert isinstance(OWNCommand.parse("*#18*1*113##"), OWNEnergyCommand)
        assert OWNCommand.parse("invalid") is None

        # Audio visual camera command
        cam_cmd = OWNAVCommand.receive_video("1")
        assert cam_cmd is not None
        assert "*7*" in str(cam_cmd)

        cam_off = OWNAVCommand.close_video()
        assert str(cam_off) == "*7*9**##"

    def test_message_remaining_branches(self) -> None:
        # Message event_content without where
        msg_no_where = OWNMessage("*#13**0##")
        assert "where" not in msg_no_where.event_content

        # Lighting unknown dimension & properties
        msg_unk = OWNLightingEvent("*#1*21*99*1##")
        assert msg_unk.message_type is None
        assert msg_unk.is_on is None
        assert msg_unk.is_sensor is False
        assert OWNLightingEvent("*1*34*21##").is_sensor is True

        # Heating remote control disabled & enabled (mode 20 & 21)
        ev_dis = OWNHeatingEvent("*4*20*1##")
        assert "disabled" in ev_dis.human_readable_log
        ev_en = OWNHeatingEvent("*4*21*1##")
        assert "enabled" in ev_en.human_readable_log

        # Heating fan off when fan mode >= 4
        ev_fan_off = OWNHeatingEvent("*#4*1*11*4##")
        assert ev_fan_off.fan_on is False

        # Heating cooling valve fan
        ev_c_fan0 = OWNHeatingEvent("*#4*1*19*5*0##")
        assert ev_c_fan0._cooling_fan_on is False
        ev_c_fan1 = OWNHeatingEvent("*#4*1*19*6*0##")
        assert ev_c_fan1._cooling_fan_on is True

        # Heating heating valve fan
        ev_h_fan0 = OWNHeatingEvent("*#4*1*19*0*5##")
        assert ev_h_fan0.fan_on is False
        ev_h_fan1 = OWNHeatingEvent("*#4*1*19*0*6##")
        assert ev_h_fan1.fan_on is True

        # Heating actuator fan
        ev_act_fan0 = OWNHeatingEvent("*#4*1#1*20*5##")
        assert ev_act_fan0.fan_on is False
        ev_act_fan1 = OWNHeatingEvent("*#4*1#1*20*6##")
        assert ev_act_fan1.fan_on is True
        ev_act_fan_auto = OWNHeatingEvent("*#4*1#1*20*9##")
        assert "Auto" in ev_act_fan_auto.human_readable_log

        # Secondary temperature
        ev_sec = OWNHeatingEvent("*#4*101*0*0220##")
        assert ev_sec.secondary_temperature == [1, 22.0]

        # Alarm input zone & stop programming state
        ev_al_in = OWNAlarmEvent("*5*1*01##")
        assert ev_al_in.zone == 0
        assert ev_al_in.sensor == 1
        ev_al_stop = OWNAlarmEvent("*5*27*0##")
        assert ev_al_stop.state_name == "stop programming"

        # Aux toggle, reset_tri, channel and is_on
        aux_tog = OWNAuxEvent("*9*2*1##")
        assert "TOGGLE" in aux_tog.human_readable_log
        aux_tri = OWNAuxEvent("*9*10*1##")
        assert "RESET_TRI" in aux_tri.human_readable_log
        assert aux_tri.channel == "1"
        assert aux_tri.is_on is False

        # Gateway uptime bad format ignored
        gw_up_err = OWNGatewayEvent("*#13**19*a*b*c*d##")
        assert gw_up_err._uptime is None

        # Energy where not starting with 1, 5, 7
        ev_en_bad = OWNEnergyEvent("*#18*2*113##")
        assert ev_en_bad.message_type is None

        # Energy 513/514 short values
        ev_en_short = OWNEnergyEvent("*#18*1*513*1##")
        assert ev_en_short.message_type is None

        # Energy dimension 53 (partial current month)
        ev_en53 = OWNEnergyEvent("*#18*1*53*500##")
        assert ev_en53.current_month_partial_consumption == 500

        # Sound volume event and properties
        ev_vol = OWNSoundEvent("*#16*1*1*25##")
        assert ev_vol.volume == 25
        assert ev_vol.zone == "1"

        # OWNCommand parse WHO 0 and WHO > 1000
        cmd_who0 = OWNCommand.parse("*0*1*11##")
        assert cmd_who0 is not None and cmd_who0.who == 0
        cmd_who2000 = OWNCommand.parse("*2000*1*11##")
        assert cmd_who2000 is not None and cmd_who2000.who == 2000

        # Lighting flash keyword spelling
        cmd_fl = OWNLightingCommand.flash("21", _freqency=1.0)
        assert "*1*21*21##" in str(cmd_fl)

        # Heating command getters and mode fallbacks
        assert OWNHeatingCommand.get_temperature("1") is not None
        assert OWNHeatingCommand.set_mode("1", "unknown") is None
        assert OWNHeatingCommand.turn_off("1") is not None
        assert OWNHeatingCommand.set_fan_speed("#0#1", 1) is not None
        assert OWNHeatingCommand.set_fan_speed("1", 1, standalone=True) is not None

        # Gateway command dimension 22
        gw_cmd22 = OWNGatewayCommand("*#13**22*12*30*00*001*0*10*09*2026##")
        assert gw_cmd22._datetime is not None

        # Sound command status
        assert str(OWNSoundCommand.status("21")) == "*#16*21##"

