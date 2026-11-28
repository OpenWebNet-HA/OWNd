"""Tests for bt_termo P0 and P1 protocol refinements (own-firmware-oracle findings/bt-termo.md)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from OWNd.connection import OWNCommandSession, OWNGateway
from OWNd.connection.command_session import destructive_frame_reason
from OWNd.exceptions import OWNProtocolError
from OWNd.message import (
    CLIMATE_MODE_AUTO,
    CLIMATE_MODE_COOL,
    CLIMATE_MODE_HEAT,
    CLIMATE_MODE_OFF,
    MESSAGE_TYPE_ACTION,
    MESSAGE_TYPE_MAIN_TEMPERATURE,
    MESSAGE_TYPE_MODE,
    MESSAGE_TYPE_MODE_TARGET,
    MESSAGE_TYPE_SECONDARY_TEMPERATURE,
    MESSAGE_TYPE_ZONE_STATE,
    OWNEvent,
    OWNHeatingCommand,
    OWNHeatingEvent,
    OWNMessage,
    SEASON_CONDITIONING,
    SEASON_HEATING,
    ZONE_STATE_EXTENDED_31,
    ZONE_STATE_EXTENDED_32,
    ZONE_STATE_MANUAL,
    who4_bt_termo_crash_reason,
    who4_temperature,
)
from OWNd.profiles import (
    Bticino3488Profile,
    WHO_CEN_PLUS,
    WHO_ENERGY,
    WHO_HEATING,
    WHO_LOAD_CONTROL,
    WHO_SCENARIO,
    WHO_SOUND,
    WHO_SOUND_DIFFUSION,
    get_gateway_profile,
)
from OWNd.transport.serial import AsyncSerialTransport


# ── P0-1: Comfort / Eco, CU timed manual (104/204/304), extended 4xx/5xx ──


@pytest.mark.parametrize(
    ("frame", "mode", "season"),
    [
        ("*4*104*#1##", CLIMATE_MODE_HEAT, SEASON_HEATING),
        ("*4*107*2##", CLIMATE_MODE_HEAT, SEASON_HEATING),
        ("*4*108*2##", CLIMATE_MODE_HEAT, SEASON_HEATING),
        ("*4*204*#1##", CLIMATE_MODE_COOL, SEASON_CONDITIONING),
        ("*4*207*2##", CLIMATE_MODE_COOL, SEASON_CONDITIONING),
        ("*4*208*2##", CLIMATE_MODE_COOL, SEASON_CONDITIONING),
        ("*4*304*#1##", CLIMATE_MODE_AUTO, None),
        ("*4*402*2##", CLIMATE_MODE_OFF, None),
        ("*4*502*2##", CLIMATE_MODE_OFF, None),
        ("*4*407*2##", CLIMATE_MODE_AUTO, None),
        ("*4*408*2##", CLIMATE_MODE_AUTO, None),
        ("*4*410*2##", CLIMATE_MODE_AUTO, None),
        ("*4*507*2##", CLIMATE_MODE_AUTO, None),
        ("*4*508*2##", CLIMATE_MODE_AUTO, None),
        ("*4*510*2##", CLIMATE_MODE_AUTO, None),
    ],
)
def test_p0_1_comfort_eco_timed_manual_and_extended_modes(
    frame: str, mode: str, season: str | None
) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNHeatingEvent)
    assert event.message_type == MESSAGE_TYPE_MODE
    assert event.mode == mode
    assert event.season == season
    assert "unknown" not in event.human_readable_log


# ── P0-2: Gen B supports_general_heating_status=False ──


@pytest.mark.parametrize("model", ["F453", "F453AV", "MH200N", "573992", "03565"])
def test_p0_2_gen_b_disables_general_heating_status(model: str) -> None:
    profile = get_gateway_profile(model)
    assert profile.supports_general_heating_status is False


# ── P0-3: DIM 19 single-side empty field ──


@pytest.mark.parametrize(
    ("frame", "is_cooling", "is_heating", "is_active", "cfan", "hfan", "cspeed", "hspeed"),
    [
        ("*#4*2*19**1##", None, True, True, None, None, None, None),
        ("*#4*2*19**0##", None, False, None, None, None, None, None),
        ("*#4*2*19**6##", None, True, True, None, True, None, 1),
        ("*#4*2*19**5##", None, False, None, None, False, None, None),
        ("*#4*2*19**100##", None, False, None, None, None, None, None),
        ("*#4*2*19**150##", None, True, True, None, None, None, None),
        ("*#4*2*19*1*##", True, None, True, None, None, None, None),
        ("*#4*2*19*0*##", False, None, None, None, None, None, None),
        ("*#4*2*19*7*##", True, None, True, True, None, 2, None),
        ("*#4*2*19*14*##", False, None, None, False, None, None, None),
    ],
)
def test_p0_3_dim19_single_side_empty_decodes_known_side(
    frame: str,
    is_cooling: bool | None,
    is_heating: bool | None,
    is_active: bool | None,
    cfan: bool | None,
    hfan: bool | None,
    cspeed: int | None,
    hspeed: int | None,
) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNHeatingEvent)
    assert event.message_type == MESSAGE_TYPE_ACTION
    assert event.is_cooling() is is_cooling
    assert event.is_heating() is is_heating
    assert event.is_active() is is_active
    assert event.cooling_fan_on is cfan
    assert event.fan_on is hfan
    assert event.cooling_fan_speed == cspeed
    assert event.fan_speed == hspeed


@pytest.mark.parametrize("frame", ["*#4*2*19**##", "*#4*2*19*999*##", "*#4*2*19**23##", "*#4*2*19*##"])
def test_p0_3_dim19_both_empty_or_unmapped_stays_untyped(frame: str) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNHeatingEvent)
    assert event.message_type is None
    assert event.is_active() is None
    assert event.is_cooling() is None
    assert event.is_heating() is None


# ── P0-5: DIM 7 states 0, 31, 32 ──


@pytest.mark.parametrize(
    ("frame", "context", "state"),
    [
        ("*#4*2*7*1*0##", "heating", ZONE_STATE_MANUAL),
        ("*#4*2*7*2*0##", "cooling", ZONE_STATE_MANUAL),
        ("*#4*2*7*3*0##", "automatic", ZONE_STATE_MANUAL),
        ("*#4*2*7*1*31##", "heating", ZONE_STATE_EXTENDED_31),
        ("*#4*2*7*1*32##", "heating", ZONE_STATE_EXTENDED_32),
    ],
)
def test_p0_5_dim7_manual_and_extended_states(frame: str, context: str, state: str) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNHeatingEvent)
    assert event.message_type == MESSAGE_TYPE_ZONE_STATE
    assert event.zone_context == context
    assert event.zone_state == state
    assert event.set_temperature is None


# ── P0-6: Gen A sub-10 °C 2/3-digit temperature format ──


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("00", 0.0),
        ("05", 0.5),
        ("005", 0.5),
        ("085", 8.5),
        ("099", 9.9),
        ("0000", 0.0),
        ("0215", 21.5),
        ("1055", -5.5),
    ],
)
def test_p0_6_gen_a_short_temperatures_decode(raw: str, expected: float) -> None:
    assert who4_temperature(raw) == expected
    ev = OWNEvent.parse(f"*#4*1*0*{raw}##")
    assert isinstance(ev, OWNHeatingEvent)
    assert ev.message_type == MESSAGE_TYPE_MAIN_TEMPERATURE
    assert ev.main_temperature == expected


@pytest.mark.parametrize("raw", ["0", "1", "12", "99", "100", "215", "00215", "2000", "0215\n", "085\n"])
def test_p0_6_malformed_temperatures_still_rejected(raw: str) -> None:
    assert who4_temperature(raw) is None


# ── P0-7: Multi-CU #0#C off-by-one (*00) and symmetric 1..16 programs ──


@pytest.mark.parametrize(
    ("frame", "mode", "season", "program", "scenario"),
    [
        ("*4*1100*#0#1##", CLIMATE_MODE_HEAT, SEASON_HEATING, None, None),
        ("*4*2100*#0#1##", CLIMATE_MODE_COOL, SEASON_CONDITIONING, None, None),
        ("*4*1200*#0#1##", CLIMATE_MODE_HEAT, SEASON_HEATING, None, None),
        ("*4*2200*#0#1##", CLIMATE_MODE_COOL, SEASON_CONDITIONING, None, None),
        ("*4*1104*#0##", CLIMATE_MODE_HEAT, SEASON_HEATING, 4, None),
        ("*4*1116*#0##", CLIMATE_MODE_HEAT, SEASON_HEATING, 16, None),
        ("*4*2104*#0##", CLIMATE_MODE_COOL, SEASON_CONDITIONING, 4, None),
        ("*4*2116*#0##", CLIMATE_MODE_COOL, SEASON_CONDITIONING, 16, None),
    ],
)
def test_p0_7_program_and_scenario_ranges(
    frame: str,
    mode: str,
    season: str,
    program: int | None,
    scenario: int | None,
) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNHeatingEvent)
    assert event.message_type == MESSAGE_TYPE_MODE
    assert event.mode == mode
    assert event.season == season
    assert event.program == program
    assert event.scenario == scenario


# ── P0-8: External probe 100..900 unique_id does not collide with 4-#0 ──


@pytest.mark.parametrize(
    ("frame", "expected_uid", "expected_zone"),
    [
        ("*#4*100*0*0215##", "4-100", 0),
        ("*#4*500*0*0185##", "4-500", 0),
        ("*#4*900*0*0050##", "4-900", 0),
        ("*#4*100*20*0##", "4-100", 0),
        ("*#4*100*15*1*0200*0001##", "4-100", 0),
        ("*#4*100*15**0200##", "4-100", 0),
        ("*#4*105*0*0296##", "4-105", 5),
        ("*#4*#0*0*0215##", "4-#0", 0),
        ("*#4*0*0*0215##", "4-#0", 0),
        ("*#4*0#2*20*1##", "4-#0", 0),
        ("*#4*0*15*1*0200*0001##", "4-#0", 0),
        ("*#4*00*15*1*0200*0001##", "4-#0", 0),
        ("*#4*000*15*1*0200*0001##", "4-#0", 0),
        ("*#4*2*15*1*0215##", "4-2", 2),
        ("*#4*02*15*1*0215##", "4-02", 2),
        ("*4*1**##", "4-#0", 0),
    ],
)
def test_p0_8_external_probe_unique_id(frame: str, expected_uid: str, expected_zone: int) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNHeatingEvent)
    assert event.unique_id == expected_uid
    assert event.zone == expected_zone


# ── P1-9: bt_termo crash guards (CRASH-01, CRASH-03, CRASH-04) ──


@pytest.mark.parametrize(
    ("frame", "tag"),
    [
        # CRASH-01: bare # in WHERE
        ("*#4*###", "CRASH-01"),
        ("*4*1*###", "CRASH-01"),
        ("*#4*#*0##", "CRASH-01"),
        ("*#4*#*#14*0215*1##", "CRASH-01"),
        ("*1*1*11##*#4*###", "CRASH-01"),
        ("*##*#4*#*#14*0215*1##", "CRASH-01"),
        ("*#4*#", "CRASH-01"),
        ("*#04*###", "CRASH-01"),
        # CRASH-03: len(WHO) >= 5 (Extract_chi) or len(Extract_dove()) >= 10
        ("*#00004*1*0##", "CRASH-03"),
        ("*00004*1*1##", "CRASH-03"),
        ("*#4*1234567890*0##", "CRASH-03"),
        ("*4*1*#012345678##", "CRASH-03"),
        # CRASH-03: dim write len(V0) >= 5
        ("*#4*1*#14*00215*1##", "CRASH-03"),
        ("*#4*1*#0*12345##", "CRASH-03"),
        ("*#4*1*#7*12345*1##", "CRASH-03"),
        ("*#4*1*#14* 0200*1##", "CRASH-03"),
        # CRASH-04: #14 < 2 args (including trailing ### bypass)
        ("*#4*1*#14##", "CRASH-04"),
        ("*#4*1*#14*0200##", "CRASH-04"),
        ("*#4*1*#14*0200*##", "CRASH-04"),
        ("*#4*1*#14*0200*###", "CRASH-04"),
        ("*#4*#0*#14*0200##", "CRASH-04"),
        # CRASH-04: #7 setpoint M*F without 3rd arg (including trailing ### and atoi()==0 bypasses)
        ("*#4*1*#7*0*1##", "CRASH-04"),
        ("*#4*1*#7*1*1##", "CRASH-04"),
        ("*#4*1*#7*2*1##", "CRASH-04"),
        ("*#4*1*#7*3*1##", "CRASH-04"),
        ("*#4*1*#7*0*31##", "CRASH-04"),
        ("*#4*1*#7*1*1*##", "CRASH-04"),
        ("*#4*1*#7*1*1*###", "CRASH-04"),
        ("*#4*1*#7*abc*1##", "CRASH-04"),
        ("*#4*1*#7*abc*31##", "CRASH-04"),
        ("*#4*1*#7**1##", "CRASH-04"),
        ("*#4*1*#7**31##", "CRASH-04"),
    ],
)
def test_p1_9_bt_termo_crash_frames_refused(frame: str, tag: str) -> None:
    reason = who4_bt_termo_crash_reason(frame)
    assert reason is not None and tag in reason
    assert destructive_frame_reason(frame) == reason
    assert who4_bt_termo_crash_reason(frame.encode("latin-1")) == reason


@pytest.mark.parametrize(
    "frame",
    [
        "*#4*#0##",
        "*#4*#0#1##",
        "*#4*1*0##",
        "*#4*0#0*20##",
        "*#4*0*60##",
        "*#4*99#9#4#99##"[:12] + "##",  # safe shorter frame
        str(OWNHeatingCommand.actuators_status("#10#1#4#01")),  # 10-char routed WHERE (Extract_dove == '#10')
        "*#4*11#4#01#12##",  # QEMU-verified non-crashing (Extract_dove == '11')
        "*#4*1*#14*0215*1##",
        "*#4*#1*#14*0215*3##",
        "*#4*#23#1*#14*0250*3##",
        "*#4*1*#11*3##",
        "*#4*1*#7*1*1*0215##",
        "*#4*1*#7*1*3##",
        "*#4*1*#7*1*4##",
        "*#4*1*#7*0*5##",
        "*#4*1*#7*1*0##",
        "*#4*1*#7*1*31##",
        "*#4*1*#7*1*32##",
        "*#4*#0*#30*25*12*2026##",
        "*#4*#0*#31*14*30##",
        "*#4*#0*#32*02*00##",
        "*#4*3#2#1*22##",
        "*#4*3#45#1*#22*3**1*1##",
        "*#1*11*#4*01##",
        "*1*1*11##",
        "*##",
    ],
)
def test_p1_9_valid_frames_not_refused(frame: str) -> None:
    assert who4_bt_termo_crash_reason(frame) is None
    assert destructive_frame_reason(frame) is None


@pytest.mark.asyncio
async def test_p1_9_command_session_and_serial_block_bt_termo_crashes() -> None:
    gw = OWNGateway({"address": "127.0.0.1", "port": 20000})
    for bad in ("*#4*###", "*#4*1*#14*0200##", "*#4*1*#14*00215*1##", "*#4*1*#7*1*1##"):
        with pytest.raises(OWNProtocolError) as exc:
            await OWNCommandSession.send_to_gateway(bad, gw, raise_on_error=True)
        assert exc.value.reason == "destructive_frame"

    transport = AsyncSerialTransport("/dev/null")
    transport._connected = True
    transport._writer = MagicMock()
    transport._writer.write = MagicMock()
    transport._writer.drain = AsyncMock()
    with pytest.raises(OWNProtocolError) as exc:
        await transport.send("*#4*1*#14*0200##", raise_on_error=True)
    assert exc.value.reason == "destructive_frame"
    transport._writer.write.assert_not_called()


# ── P1-10: Bticino 3488 profile ──


@pytest.mark.parametrize("name", ["3488", "BTicino 3488", "067259", "67259"])
def test_p1_10_bticino_3488_profile(name: str) -> None:
    profile = get_gateway_profile(name)
    assert isinstance(profile, Bticino3488Profile)
    assert profile.model_name == "3488"
    assert profile.supports_hmac is True
    assert profile.auth_measured is True
    assert profile.audio_measured is False
    assert profile.supports_audio is True
    assert profile.supports_general_heating_status is False
    assert profile.supports_heating_zone_status is True
    assert profile.supports_heating_actuator_status is True
    assert profile.supports_heating_humidity_request is True
    assert profile.supports_interface_zone_requests is False
    assert profile.supports_who(WHO_HEATING) is True
    assert profile.supports_who(WHO_ENERGY) is True
    assert profile.supports_who(WHO_SOUND_DIFFUSION) is True
    assert profile.supports_who(WHO_CEN_PLUS) is True
    assert profile.supports_who(WHO_LOAD_CONTROL) is False
    assert profile.supports_who(WHO_SOUND) is False
    assert profile.supports_who(WHO_SCENARIO) is False


def test_p1_10_bticino_3488_who1013_model_128() -> None:
    """Live 3488 fw 3.2.5 reports *#1013**1*128*15*1*0## alongside *#13**27*51#52#56#56## ('3488')."""
    from OWNd.message import OWNGatewayDiagnosticEvent

    ev = OWNEvent.parse("*#1013**1*128*15*1*0##")
    assert isinstance(ev, OWNGatewayDiagnosticEvent)
    assert ev.device_type == "3488"


# ── P1-11: timed_manual_hours parsed from 112/212/312#TTTT#HH ──


@pytest.mark.parametrize(
    ("frame", "mode", "season", "temp", "hours"),
    [
        ("*4*112#0210#05*#0##", CLIMATE_MODE_HEAT, SEASON_HEATING, 21.0, 5),
        ("*4*212#0245#12*#0#1##", CLIMATE_MODE_COOL, SEASON_CONDITIONING, 24.5, 12),
        ("*4*312#0215#2*#0##", CLIMATE_MODE_AUTO, None, 21.5, 2),
        ("*4*312#0215*#0##", CLIMATE_MODE_AUTO, None, 21.5, None),
        ("*4*110#0215*#0##", CLIMATE_MODE_HEAT, SEASON_HEATING, 21.5, None),
    ],
)
def test_p1_11_timed_manual_hours_parsed(
    frame: str,
    mode: str,
    season: str | None,
    temp: float,
    hours: int | None,
) -> None:
    event = OWNMessage.parse(frame)
    assert isinstance(event, OWNHeatingEvent)
    assert event.message_type == MESSAGE_TYPE_MODE_TARGET
    assert event.mode == mode
    assert event.season == season
    assert event.set_temperature == temp
    assert event.timed_manual_hours == hours
    if hours is not None:
        assert f"for {hours}h." in event.human_readable_log
