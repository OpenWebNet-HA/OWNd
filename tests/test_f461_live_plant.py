"""Findings from a physical BTicino F461 (firmware 2.0.11), captured 2026-10-15.

The plant: one standalone thermostat zone (2) with a heating valve on actuator 1 and a
cooling fan coil on actuator 2, no central unit, two F411 relay lights at WHERE 01 and
04 (Home + Project, area 0). The frames below are the distinct ones the gateway sent or
accepted during the capture; the WHO 13 IP and MAC replies carry the documentation IP
``192.0.2.92`` and a synthetic MAC in place of the plant's own. The full multi-session
capture is archived in the MyHOME trace corpus (OpenWebNet-HA/MyHOME, PR #714).

Three OWNd behaviours were wrong against that plant:

1. ``*#4*Z*19*5*1##`` (cooling side "fan coil off", heating valve ON) parsed as *not active*,
   because the fan-coil branch of the dimension 19 parser overwrote ``_is_active`` after the
   valve states had set it. The plant reports this frame on every heating-season read.
2. ``set_mode(zone, "protection" | "antifreeze" | "thermal_protection", standalone=True)``
   produced the ``#Z`` form, which the gateway forwards to a central unit (emulated
   ``bt_termo``: ``*4*302*#23##`` -> ``D1 00 03 02 C2 17 07 00``) and which a standalone
   thermostat ignores; the plain form (``93 17 30 04``) is the one that works. Only
   ``311`` (automatic) is a central-unit-only command (``*4*311*Z##`` is NACKed).
3. WHO 13 device type ``200`` was labelled ``F454`` although F454, MyHomeServer1, MH202,
   F461 and H4890 all answer it.
"""
from __future__ import annotations

import pytest

from OWNd.message import OWNCommand, OWNEvent, OWNHeatingCommand, OWNMessage

# Every distinct frame the gateway sent (command replies and event session), sanitised.
GATEWAY_FRAMES = (
    # WHO 13 replies and the gateway's own pushes (clock broadcasts, WHO 1013 object model)
    "*#13**0*09*16*32*999##",
    "*#13**1*04*15*10*2026##",
    "*#13**22*09*16*33*999*04*15*10*2026##",
    "*#13**10*192*0*2*92##",
    "*#13**11*255*255*255*0##",
    "*#13**12*0*3*80*0*4*97##",
    "*#13**15*200##",
    "*#1013**1*134*15*5*0##",
    "*#13**16*2*0*11##",
    "*#13**17*4*2*0##",
    "*#13**19*0*8*33*56##",
    "*#13**23*5*10*35##",
    "*#13**24*2*26*4##",
    "*#13**#0*09*20*00*##",
    "*#13**#1*04*15*10*2026##",
    # WHO 1: point, area 0 ("00"), area 1/4, group, general, interface, blinker, timer read-back
    "*1*1*01##", "*1*0*01##", "*1*1*04##", "*1*0*04##",
    "*1*1*00##", "*1*0*00##", "*1*1*1##", "*1*0*1##", "*1*1*4##", "*1*0*4##",
    "*1*1*#1##", "*1*0*#1##", "*1*1*0##", "*1*0*0##",
    "*1*1*1#4#01##", "*1*0*1#4#01##",
    "*1*20*01##", "*1*20*04##",
    "*#1*01*2*0*0*0##", "*#1*04*2*0*0*0##",
    # WHO 4 zone 2: the five frames answering *#4*2##, then everything else it reported
    "*#4*2*0*0241##", "*#4*2*12*0245*3##", "*4*1*2##", "*#4*2*14*0245*3##", "*#4*2*13*00##",
    "*#4*2*0*0243##", "*4*0*2##", "*4*303*2##", "*4*202*2##",
    "*#4*2*12*0180*3##", "*#4*2*12*0200*3##", "*#4*2*12*0210*3##", "*#4*2*12*0220*3##",
    "*#4*2*12*0230*3##", "*#4*2*12*0250*3##", "*#4*2*12*0350*3##",
    "*#4*2*14*0200*3##", "*#4*2*14*0210*3##", "*#4*2*14*0220*3##", "*#4*2*14*0230*3##", "*#4*2*14*0250*3##",
    "*#4*2*11*0##", "*#4*2*11*1##", "*#4*2*11*2##", "*#4*2*11*3##",
    "*#4*2*19*5*1##", "*#4*2*19*5*0##", "*#4*2*19*8*0##",
    "*#4*2#1*20*1##", "*#4*2#1*20*0##", "*#4*2#2*20*5##", "*#4*2#2*20*8##",
    "*#4*2#1*#20*1##", "*#4*2#1*#20*0##", "*#4*2#2*#20*5##", "*#4*2#2*#20*8##",
    "*#4*2*60*34##",
    "*#4*2*2*0350##", "*#4*2*3*0070##", "*#4*2*4*0##", "*#4*2*6*0##",
)

# Requests and commands the gateway ACKed (a subset relevant to the builders below).
ACKED_FRAMES = {
    "*#4*2##", "*#4*02##", "*#4*2*0##", "*#4*2*12##", "*#4*2*13##", "*#4*2*14##", "*#4*2*19##",
    "*#4*2*20##", "*#4*2*60##", "*#4*2*2##", "*#4*2*3##", "*#4*2*4##", "*#4*2*6##",
    "*#4*2*#14*0210*1##", "*#4*2*#14*0250*2##", "*#4*2*#14*0220*3##", "*#4*2*#14*0245*3##",
    "*4*303*2##", "*4*302*2##", "*4*1*2##", "*4*0*2##",
    "*4*311*#2##", "*4*302*#2##", "*4*102*#2##", "*4*202*#2##", "*4*303*#2##",
    "*#4*2*#11*1##", "*#4*2*#11*2##", "*#4*2*#11*3##", "*#4*2*#11*0##",
    "*#1*01##", "*#1*04##", "*#1*0##", "*#1*00##", "*1*1*01##", "*1*0*01##", "*1*20*01##", "*1*22*01##",
    "*1*11*01##", "*#1*01*#2*0*0*5##", "*#1*01*2##",
}
# Requests and commands the gateway NACKed.
NACKED_FRAMES = {"*#4*0##", "*#4*#2##", "*#4*2#1##", "*4*311*2##", "*#4*2*15##", "*#4*2*30##", "*#4*2*31##", "*#4*2*32##"}

# What the event session showed after each command (zone 2 ON, cooling season, setpoint 20.0).
# A tuple of frames; () means nothing but the usual status snapshot, i.e. no state change.
EVENTS_AFTER = {
    "*4*302*2##": ("*4*202*2##", "*#4*2*12*0350*3##", "*#4*2#2*#20*5##", "*#4*2#2*20*5##"),
    "*4*302*#2##": (),
    "*4*102*#2##": (),
    "*4*202*#2##": (),
    "*4*311*#2##": (),
    "*4*303*#2##": (),
    "*4*303*2##": ("*4*303*2##", "*#4*2*12*0230*3##", "*#4*2#2*#20*5##", "*#4*2#2*20*5##"),
    "*#4*2*#14*0200*3##": ("*4*0*2##", "*#4*2*12*0200*3##", "*#4*2#2*#20*8##", "*#4*2#2*20*8##"),
    "*4*1*2##": ("*4*1*2##", "*#4*2#2*#20*5##", "*#4*2#2*20*5##"),
    "*4*0*2##": ("*4*0*2##", "*#4*2#2*#20*8##", "*#4*2#2*20*8##"),
}


# ---------------------------------------------------------------------- the capture itself

def test_every_frame_the_gateway_sent_parses() -> None:
    unparsed = [raw for raw in GATEWAY_FRAMES if (m := OWNMessage.parse(raw)) is None or not m.is_valid]
    assert unparsed == []


def test_the_zone_status_request_is_answered_and_the_general_one_refused() -> None:
    """``*#4*2##`` is answered with five frames on this F461 (MyHOME #674 says it times out on an F455)."""
    assert str(OWNHeatingCommand.status("2")) in ACKED_FRAMES
    assert GATEWAY_FRAMES[GATEWAY_FRAMES.index("*#4*2*0*0241##"):][:5] == (
        "*#4*2*0*0241##", "*#4*2*12*0245*3##", "*4*1*2##", "*#4*2*14*0245*3##", "*#4*2*13*00##",
    )
    assert "*#4*0##" in NACKED_FRAMES


# ---------------------------------------------------------------------- 1. dimension 19

@pytest.mark.parametrize(
    "frame, active, heating, cooling, cooling_fan_on, fan_on",
    [
        ("*#4*2*19*5*1##", True, True, False, False, None),   # captured: heating season, valve open
        ("*#4*2*19*5*0##", False, False, False, False, None),  # captured: cooling season, idle
        ("*#4*2*19*8*0##", True, False, True, True, None),    # captured: cooling season, fan coil speed 3
        ("*#4*2*19*1*5##", True, False, True, None, False),   # mirror of the first one
        ("*#4*2*19*5*5##", False, False, False, False, False),
        ("*#4*2*19*0*6##", True, True, False, None, True),
        ("*#4*2*19*0*1##", True, True, False, None, None),    # valve-only plants, unchanged
        ("*#4*2*19*1*0##", True, False, True, None, None),
        ("*#4*2*19*0*0##", False, False, False, None, None),
    ],
)
def test_dimension_19_is_active_combines_both_sides(frame, active, heating, cooling, cooling_fan_on, fan_on) -> None:
    msg = OWNEvent.parse(frame)
    assert msg.is_active() is active, msg.human_readable_log
    assert msg.is_heating() is heating
    assert msg.is_cooling() is cooling
    assert msg.cooling_fan_on is cooling_fan_on
    assert msg.fan_on is fan_on


def test_captured_dimension_19_frames_are_active_whenever_a_valve_or_fan_is_on() -> None:
    seen = [raw for raw in GATEWAY_FRAMES if raw.startswith("*#4*2*19*")]
    assert sorted(seen) == ["*#4*2*19*5*0##", "*#4*2*19*5*1##", "*#4*2*19*8*0##"]
    for raw in seen:
        cooling_value, heating_value = (int(v) for v in raw[:-2].split("*")[4:6])
        # 1 on, 2 opened, 6/7/8 fan coil running: anything else on both sides is idle
        expected = any(v in (1, 2, 6, 7, 8) for v in (cooling_value, heating_value))
        assert OWNEvent.parse(raw).is_active() is expected, raw


# ---------------------------------------------------------------------- 2. protection addressing

def test_protection_follows_standalone_but_automatic_stays_central() -> None:
    assert str(OWNHeatingCommand.set_mode("2", "protection", standalone=True)) == "*4*302*2##"
    assert str(OWNHeatingCommand.set_mode("2", "antifreeze", standalone=True)) == "*4*102*2##"
    assert str(OWNHeatingCommand.set_mode("2", "thermal_protection", standalone=True)) == "*4*202*2##"
    assert str(OWNHeatingCommand.set_protection("2", standalone=True)) == "*4*302*2##"
    # a zone under a central unit keeps the #Z form
    assert str(OWNHeatingCommand.set_mode("2", "protection")) == "*4*302*#2##"
    assert str(OWNHeatingCommand.set_mode("#2#1", "protection")) == "*4*302*#2#1##"
    # automatic is the central unit's program whatever the flag says
    assert str(OWNHeatingCommand.set_mode("2", "auto", standalone=True)) == "*4*311*#2##"
    assert str(OWNHeatingCommand.set_mode("2", "off", standalone=True)) == "*4*303*2##"


def test_capture_shows_only_the_plain_protection_form_acts() -> None:
    """The plant ACKs both forms; only the plain one changes the zone (``*4*202*2##`` follows)."""
    plain = str(OWNHeatingCommand.set_mode("2", "protection", standalone=True))
    assert plain in ACKED_FRAMES and "*4*202*2##" in EVENTS_AFTER[plain]
    for hashed in ("*4*302*#2##", "*4*102*#2##", "*4*202*#2##", "*4*311*#2##"):
        assert hashed in ACKED_FRAMES and EVENTS_AFTER[hashed] == (), hashed
    assert "*4*311*2##" in NACKED_FRAMES
    # the way out of OFF / protection on a standalone thermostat is a setpoint write
    assert "*4*0*2##" in EVENTS_AFTER["*#4*2*#14*0200*3##"]
    assert OWNEvent.parse("*4*202*2##").mode == "off"  # OWNd still folds protection into off


# ---------------------------------------------------------------------- 3. WHO 13 device type 200

def test_device_type_200_is_not_a_single_model() -> None:
    msg = OWNEvent.parse("*#13**15*200##")
    assert msg.device_type_code == "200"
    assert "F454" in msg.device_type and "F461" in msg.device_type
    assert msg.human_readable_log == f"Gateway device type is: {msg.device_type}."
    assert OWNEvent.parse("*#13**15*2##").device_type == "MHServer"
    assert OWNEvent.parse("*#13**16*2*0*11##").device_type_code is None
    assert OWNEvent.parse("*#1013**1*134*15*5*0##") is not None


def test_capture_identity_sequence() -> None:
    i = GATEWAY_FRAMES.index("*#13**15*200##")
    assert GATEWAY_FRAMES[i + 1] == "*#1013**1*134*15*5*0##"  # pushed on the event session right after
    firmware = OWNEvent.parse("*#13**16*2*0*11##")
    assert firmware.firmware_version == "2.0.11"
    assert OWNEvent.parse("*#13**12*0*3*80*0*4*97##").mac_address == "00:03:50:00:04:61"


# ---------------------------------------------------------------------- what still works

def test_builders_used_by_myhome_match_frames_the_plant_accepted() -> None:
    for cmd in (
        OWNHeatingCommand.set_temperature("2", 21.0, "heat", standalone=True),
        OWNHeatingCommand.set_temperature("2", 25.0, "cool", standalone=True),
        OWNHeatingCommand.set_temperature("2", 22.0, "auto", standalone=True),
        OWNHeatingCommand.set_mode("2", "off", standalone=True),
        OWNHeatingCommand.set_fan_speed("2", 1),
        OWNCommand.parse("*#1*01##"),
        OWNCommand.parse("*1*1*01##"),
        OWNCommand.parse("*1*20*01##"),
        OWNCommand.parse("*#1*00##"),
    ):
        assert str(cmd) in ACKED_FRAMES, str(cmd)


def test_season_frames_and_area_zero_lights_parse_as_before() -> None:
    assert OWNEvent.parse("*4*1*2##").season == "heating" and OWNEvent.parse("*4*0*2##").season == "conditioning"
    area0 = OWNEvent.parse("*1*1*00##")
    assert area0.is_area and area0.area == 0
    point = OWNEvent.parse("*1*1*01##")
    assert point.is_on and not point.is_area and not point.is_general
    assert OWNEvent.parse("*1*1*1##").is_area  # a single digit is area 1, never the point 01
