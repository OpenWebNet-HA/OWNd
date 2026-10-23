"""WHO 1 commands libqtdevices TS10_1_0_23 sends (lighting_device.cpp:34-39
FIXED_TIMING_MIN/MAX = 11/18, DIMMER_INC/DEC = 30/31; :110-124 fixedTiming,
variableTiming; :131-134 requestVariableTiming; :230-245 increase/decrease/
setLevel100; :409-417 Dimmer100 increaseLevel100/decreaseLevel100).
Firmware replay on bt_luci (MyHomeServer1, F454, F459): *1*2*11## ACK bus
11 00 12 1D, *1*5*11## 4D, *1*10*11## 9D, *1*30*11## 03, *1*31*11## 04,
*1*30#20#1*11## D1 11 01 42 0D 03 14 01, *1*31#20#255*11## ... 0D 04 14 FF,
*1*11*11## 16, *1*18*11## 86, *#1*11*#2*0*1*0## D1 11 01 42 06 00 01 00,
*#1*11*2## request frame D1 11 01 43 06 00 00 00."""

import pytest

from OWNd.message import OWNLightingCommand


def test_presets():
    assert str(OWNLightingCommand.set_brightness_preset(11, 2)) == "*1*2*11##"
    assert str(OWNLightingCommand.set_brightness_preset(11, 10)) == "*1*10*11##"
    with pytest.raises(ValueError):
        OWNLightingCommand.set_brightness_preset(11, 1)
    with pytest.raises(ValueError):
        OWNLightingCommand.set_brightness_preset(11, 11)


def test_steps():
    assert str(OWNLightingCommand.step_up(11)) == "*1*30*11##"
    assert str(OWNLightingCommand.step_down(11)) == "*1*31*11##"
    assert str(OWNLightingCommand.step_up(11, 20, 1)) == "*1*30#20#1*11##"
    assert str(OWNLightingCommand.step_down(11, 20, 255)) == "*1*31#20#255*11##"
    with pytest.raises(ValueError):
        OWNLightingCommand.step_up(11, 0)
    with pytest.raises(ValueError):
        OWNLightingCommand.step_up(11, 10, 256)


def test_fixed_timers():
    assert str(OWNLightingCommand.switch_on_timed(11, 11)) == "*1*11*11##"
    assert str(OWNLightingCommand.switch_on_timed(11, 18)) == "*1*18*11##"
    with pytest.raises(ValueError):
        OWNLightingCommand.switch_on_timed(11, 19)


def test_variable_timer():
    assert str(OWNLightingCommand.set_variable_timer(11, 0, 1, 0)) == "*#1*11*#2*0*1*0##"
    assert str(OWNLightingCommand.get_variable_timer(11)) == "*#1*11*2##"
    with pytest.raises(ValueError):
        OWNLightingCommand.set_variable_timer(11, 0, 60, 0)


def test_apl_addressing_helpers():
    from OWNd.message import area_of_where, is_apl_address, normalize_where

    assert is_apl_address("02") is True
    assert is_apl_address("15") is True
    assert is_apl_address("0015") is True
    assert is_apl_address("0115") is True
    assert is_apl_address("1015") is True
    assert is_apl_address("00") is False
    assert is_apl_address("100") is False
    assert is_apl_address("#6") is False
    assert is_apl_address("1101") is False

    assert area_of_where("02") == "00"
    assert area_of_where("15") == "1"
    assert area_of_where("0015") == "00"
    assert area_of_where("0115") == "1"
    assert area_of_where("1015") == "100"
    assert area_of_where("#6") is None
    assert area_of_where(None) is None

    assert normalize_where("02") == "02"
    assert normalize_where("0015") == "0015"
    assert normalize_where("0021") == "21"
    assert normalize_where("0109") == "0109"
    assert normalize_where("15#4#01") == "15#4#01"
    assert normalize_where("#5") == "#5"
    assert normalize_where(None) == ""
    assert normalize_where("   ") == ""


def test_lighting_dimension_properties():
    from OWNd.message import OWNLightingEvent, OWNMessage

    cmd_b = OWNMessage.parse("*#1*#6*#1*150*0##")
    assert isinstance(cmd_b, OWNLightingCommand)
    assert cmd_b.brightness == 50
    assert cmd_b.dimension_value == ["150", "0"]
    assert cmd_b.where_param == []
    assert cmd_b.dimension_param == []
    assert cmd_b.what is None
    assert cmd_b.what_param == []
    assert cmd_b.color_temp is None
    assert cmd_b.color_temp_kelvin is None
    assert cmd_b.hs is None

    cmd_b_bad = OWNMessage.parse("*#1*#6*#1*50*0##")
    assert isinstance(cmd_b_bad, OWNLightingCommand)
    assert cmd_b_bad.brightness is None

    cmd_b._dimension_value = ["abc"]
    assert cmd_b.brightness is None

    cmd_ct = OWNMessage.parse("*#1*#6*#14*153##")
    assert isinstance(cmd_ct, OWNLightingCommand)
    assert cmd_ct.color_temp == 153
    assert cmd_ct.color_temp_kelvin == int(1000000 / 153)
    assert cmd_ct.brightness is None

    cmd_ct._dimension_value = ["1"]
    assert cmd_ct.color_temp is None
    cmd_ct._dimension_value = ["abc"]
    assert cmd_ct.color_temp is None

    cmd_hs = OWNMessage.parse("*#1*#6*#12*120*50*80##")
    assert isinstance(cmd_hs, OWNLightingCommand)
    assert cmd_hs.hs == (120, 50)
    assert cmd_hs.hs_color == (120, 50)

    cmd_hs._dimension_value = ["511", "127", "255"]
    assert cmd_hs.hs is None
    cmd_hs._dimension_value = ["-1", "50", "80"]
    assert cmd_hs.hs is None
    cmd_hs._dimension_value = ["120", "-1", "80"]
    assert cmd_hs.hs is None
    cmd_hs._dimension_value = ["120", "101", "80"]
    assert cmd_hs.hs is None
    cmd_hs._dimension_value = ["abc", "50", "80"]
    assert cmd_hs.hs is None

    ev_ct = OWNMessage.parse("*#1*#6*14*153##")
    assert isinstance(ev_ct, OWNLightingEvent)
    assert ev_ct.color_temp_kelvin == int(1000000 / 153)

    ev_hs = OWNMessage.parse("*#1*#6*12*120*50*80##")
    assert isinstance(ev_hs, OWNLightingEvent)
    assert ev_hs.hs_color == (120, 50)
    assert ev_hs.color_temp_kelvin is None
    assert ev_hs.brightness_preset_percent is None


def test_coarse_dimmer_conversion_and_detection():
    from OWNd.message import (
        COARSE_PRESET_TO_PERCENT,
        DIMMER_SPEED_COARSE_ONLY,
        OWNCommand,
        OWNEvent,
        OWNLightingEvent,
        OWNMessage,
        brightness_preset_to_percent,
        clear_coarse_dimmer_wheres,
        is_coarse_dimmer_where,
        percent_to_brightness_preset,
        register_coarse_dimmer_where,
    )

    assert DIMMER_SPEED_COARSE_ONLY == 240
    for preset, expected_pct in COARSE_PRESET_TO_PERCENT.items():
        assert brightness_preset_to_percent(preset) == expected_pct

    for bad_preset in (True, False, 7.9, float("inf"), float("-inf"), float("nan")):
        with pytest.raises(ValueError, match="integer between 2 and 10"):
            brightness_preset_to_percent(bad_preset)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="integer between 2 and 10"):
            OWNLightingCommand.set_brightness_preset("61", bad_preset)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        brightness_preset_to_percent(1)
    with pytest.raises(ValueError):
        brightness_preset_to_percent(11)

    for bad_level in (True, False, 50.9, float("inf"), float("-inf"), float("nan")):
        with pytest.raises(ValueError, match="level must be an integer"):
            percent_to_brightness_preset(bad_level)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="must be integers"):
            OWNLightingCommand.set_brightness("61", bad_level, 0)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="must be integers"):
            OWNLightingCommand.set_brightness("61", 50, bad_level)  # type: ignore[arg-type]

    assert percent_to_brightness_preset(-5) == 0
    assert percent_to_brightness_preset(0) == 0
    for pct, expected_preset in [
        (1, 2),
        (4, 2),
        (5, 3),
        (15, 3),
        (16, 4),
        (25, 4),
        (26, 5),
        (35, 5),
        (36, 6),
        (45, 6),
        (46, 7),
        (50, 7),
        (53, 7),
        (54, 8),
        (67, 8),
        (68, 9),
        (75, 9),
        (85, 9),
        (86, 10),
        (100, 10),
        (120, 10),
    ]:
        assert percent_to_brightness_preset(pct) == expected_preset

    clear_coarse_dimmer_wheres()
    register_coarse_dimmer_where(None, True)
    register_coarse_dimmer_where("", True)
    assert is_coarse_dimmer_where(None) is False
    assert is_coarse_dimmer_where("") is False
    assert is_coarse_dimmer_where("61") is False

    # Unlearned address keeps brightness=None on preset events and uses Dimension 1
    ev_unlearned = OWNEvent.parse("*1*5*21##")
    assert isinstance(ev_unlearned, OWNLightingEvent)
    assert ev_unlearned.is_coarse_dimmer is False
    assert ev_unlearned.brightness_preset == 5
    assert ev_unlearned.brightness_preset_percent == 30
    assert ev_unlearned.brightness is None
    assert str(OWNLightingCommand.set_brightness("21", 50, 0)) == "*#1*21*#1*150*0##"

    # Explicit coarse=True override works even on unlearned addresses
    cmd_coarse_21 = OWNLightingCommand.set_brightness("21", 50, 5, coarse=True)
    assert str(cmd_coarse_21) == "*1*7*21##"
    assert cmd_coarse_21.is_coarse_dimmer is True
    assert cmd_coarse_21.brightness_preset == 7
    assert cmd_coarse_21.brightness == 50
    cmd_preset_21 = OWNLightingCommand.set_brightness_preset("21", 7)
    assert cmd_preset_21.is_coarse_dimmer is False
    assert cmd_preset_21.brightness_preset == 7
    assert cmd_preset_21.brightness is None
    cmd_off_21 = OWNLightingCommand.set_brightness("21", 0, 5, coarse=True)
    assert str(cmd_off_21) == "*1*0*21##"
    assert cmd_off_21.brightness_preset is None

    # Legacy pre-09W29 F414 reports speed 240 (0xF0) in Dimension 1 (MyHOME#767)
    ev_f414_old = OWNEvent.parse("*#1*61*1*130*240##")
    assert isinstance(ev_f414_old, OWNLightingEvent)
    assert ev_f414_old.brightness == 30
    assert ev_f414_old.transition == 240
    assert ev_f414_old.is_coarse_dimmer is True
    assert is_coarse_dimmer_where("61") is True

    # Subsequent set_brightness on 61 automatically emits coarse WHAT 2..10 frames
    assert str(OWNLightingCommand.set_brightness("61", 50, 0)) == "*1*7*61##"
    assert str(OWNLightingCommand.set_brightness("61", 75, 5)) == "*1*9*61##"
    assert str(OWNLightingCommand.set_brightness("61", 0, 5)) == "*1*0*61##"
    # Explicit coarse=False can still force Dimension 1 if desired
    assert (
        str(OWNLightingCommand.set_brightness("61", 50, 0, coarse=False))
        == "*#1*61*#1*150*0##"
    )

    # Preset event on learned coarse dimmer populates canonical fine brightness %
    ev_preset_61 = OWNEvent.parse("*1*7*61##")
    assert isinstance(ev_preset_61, OWNLightingEvent)
    assert ev_preset_61.is_coarse_dimmer is True
    assert ev_preset_61.brightness_preset == 7
    assert ev_preset_61.brightness_preset_percent == 50
    assert ev_preset_61.brightness == 50

    # Private riser address (61#4#01) is tracked independently
    ev_riser = OWNEvent.parse("*#1*61#4#01*1*130*240##")
    assert isinstance(ev_riser, OWNLightingEvent)
    assert ev_riser.is_coarse_dimmer is True
    assert is_coarse_dimmer_where("61#4#01") is True
    cmd_riser = OWNLightingCommand.set_brightness("61#4#01", 30)
    assert str(cmd_riser) == "*1*5*61#4#01##"
    assert cmd_riser.brightness == 30
    parsed_cmd_riser = OWNCommand.parse("*1*5*61#4#01##")
    assert isinstance(parsed_cmd_riser, OWNLightingCommand)
    assert parsed_cmd_riser.brightness == 30

    # Replacing dimmer at 61 with a modern F418U2 / post-09W29 F414 (speed 2) clears coarse flag
    ev_f418u2 = OWNEvent.parse("*#1*61*1*200*2##")
    assert isinstance(ev_f418u2, OWNLightingEvent)
    assert ev_f418u2.is_coarse_dimmer is False
    assert is_coarse_dimmer_where("61") is False
    assert str(OWNLightingCommand.set_brightness("61", 50, 0)) == "*#1*61*#1*150*0##"

    # Multi-gateway / multi-plant isolation: identical WHERE=61 on two different gateways
    from OWNd.connection import OWNGateway

    clear_coarse_dimmer_wheres()
    gw_a = OWNGateway({"address": "192.168.1.40", "serialNumber": "00:03:50:AA:BB:01"})
    gw_b = OWNGateway({"address": "192.168.1.41"})  # falls back to host when serial is None

    # Blank/unidentifiable gateway objects fall back to unscoped (None)
    assert is_coarse_dimmer_where("61", gateway="   ") is False
    assert is_coarse_dimmer_where("61", gateway=object()) is False
    clear_coarse_dimmer_wheres(gateway="   ")

    # Plant A learns WHERE=61 is coarse (speed 240)
    ev_gw_a = OWNMessage.parse("*#1*61*1*130*240##", gateway=gw_a)
    assert isinstance(ev_gw_a, OWNLightingEvent)
    assert ev_gw_a.is_coarse_dimmer is True
    assert is_coarse_dimmer_where("61", gateway=gw_a) is True
    assert is_coarse_dimmer_where("61", gateway="00:03:50:aa:bb:01") is True
    # Before Plant B sees WHERE=61, Plant B falls back to (None, "61") -> False,
    # while unscoped lookup sees all known gateways for "61" are coarse -> True
    assert is_coarse_dimmer_where("61", gateway=gw_b) is False
    assert is_coarse_dimmer_where("61") is True

    # Plant B learns its own WHERE=61 is a modern fine dimmer (speed 2)
    ev_gw_b = OWNEvent.parse("*#1*61*1*200*2##", gateway=gw_b)
    assert isinstance(ev_gw_b, OWNLightingEvent)
    assert ev_gw_b.is_coarse_dimmer is False
    # Plant A's coarse state is preserved; Plant B is fine; unscoped ambiguous query is False
    assert is_coarse_dimmer_where("61", gateway=gw_a) is True
    assert is_coarse_dimmer_where("61", gateway=gw_b) is False
    assert is_coarse_dimmer_where("61") is False

    ev_preset_a = OWNMessage.parse("*1*7*61##", gateway=gw_a)
    assert isinstance(ev_preset_a, OWNLightingEvent)
    assert ev_preset_a.is_coarse_dimmer is True
    assert ev_preset_a.brightness == 50

    ev_preset_b = OWNMessage.parse("*1*7*61##", gateway=gw_b)
    assert isinstance(ev_preset_b, OWNLightingEvent)
    assert ev_preset_b.is_coarse_dimmer is False
    assert ev_preset_b.brightness is None

    assert (
        str(OWNLightingCommand.set_brightness("61", 50, 0, gateway=gw_a))
        == "*1*7*61##"
    )
    assert (
        OWNLightingCommand.set_brightness("61", 50, 0, gateway=gw_a).brightness == 50
    )
    assert (
        OWNCommand.parse("*1*7*61##", gateway=gw_a).brightness == 50  # type: ignore[union-attr]
    )
    assert (
        OWNCommand.parse("*1*7*61##", gateway=gw_b).brightness is None  # type: ignore[union-attr]
    )
    assert (
        str(OWNLightingCommand.set_brightness("61", 50, 0, gateway=gw_b))
        == "*#1*61*#1*150*0##"
    )

    # Clearing Plant A only removes Plant A's entries
    clear_coarse_dimmer_wheres(gateway=gw_a)
    assert is_coarse_dimmer_where("61", gateway=gw_a) is False
    assert is_coarse_dimmer_where("61", gateway=gw_b) is False

    clear_coarse_dimmer_wheres()


