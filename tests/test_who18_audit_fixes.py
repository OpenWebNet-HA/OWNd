"""WHO 18 audit fixes (report 21 rows E1..E12, 2026-11-03).

Evidence: Encyclopedia ``encyclopedia_functional/who-18-energy-management/``
(``dimensions.md``, ``what.md``, ``addressing.md``), the firmware oracle rows in
``tests/golden/firmware_oracle.json`` (suite ``energy-ts10``) and the
confirmation pass recorded in the review session (ORACLE_CONFIRM E1..E3).
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from OWNd.message import (
    ENERGY_SERIES_CURRENT_YEAR,
    ENERGY_SERIES_DAILY,
    ENERGY_SERIES_MONTHLY_AVERAGE,
    ENERGY_SERIES_PREVIOUS_YEAR,
    HISTORICAL_SERIES_DIMENSIONS,
    MESSAGE_TYPE_ACTIVE_POWER,
    MESSAGE_TYPE_ACTUATOR_ENABLED,
    MESSAGE_TYPE_ACTUATOR_FORCED,
    MESSAGE_TYPE_ACTUATOR_FORCING_ENDED,
    MESSAGE_TYPE_ACTUATOR_STATUS,
    MESSAGE_TYPE_DAILY_CONSUMPTION,
    MESSAGE_TYPE_DIFFERENTIAL_CURRENT_LEVEL,
    MESSAGE_TYPE_HISTORICAL_SERIES_START,
    MESSAGE_TYPE_HOURLY_CONSUMPTION,
    MESSAGE_TYPE_MONTHLY_AVERAGE_CONSUMPTION,
    MESSAGE_TYPE_MONTHLY_CONSUMPTION,
    MESSAGE_TYPE_TOTALIZER_RESET,
    MESSAGE_TYPE_TOTALIZER_STATE,
    STOP_AND_GO_DIM_CHECK_OFF,
    STOP_AND_GO_LINE_MAX,
    OWNCommand,
    OWNEnergyCommand,
    OWNEnergyEvent,
    OWNEvent,
    OWNMessage,
    OWNStopAndGoCommand,
    OWNStopAndGoEvent,
    stop_and_go_line,
)

_ORACLE = Path(__file__).parent / "golden" / "firmware_oracle.json"


def _oracle_out(frame: str) -> set[str]:
    verdicts = json.loads(_ORACLE.read_text(encoding="utf-8"))["verdicts"]
    return {row["product"] for row in verdicts[frame] if row["verdict"] == "out"}


# ---------------------------------------------------------------------------
# E1: DIMENSION 52 needs #YY#M (dimensions.md "DIMENSION 52 - monthly
# energy/unit totalizer"; ORACLE_CONFIRM E1: *#18*51*52*100## refused on 11/12,
# the four-digit year crashes the emulated F460 020012 / F461 020011, the
# two-digit *#18*51*52#26#9## goes out on nine).
# ---------------------------------------------------------------------------


def test_e1_report_current_month_energy_emits_two_digit_year() -> None:
    assert (
        str(OWNEnergyCommand.report_current_month_energy("51", 100, 2026, 9))
        == "*#18*51*52#26#9*100##"
    )
    today = datetime.date.today()
    default = OWNEnergyCommand.report_current_month_energy("51", 100)
    assert str(default) == f"*#18*51*52#{today.year % 100:02d}#{today.month}*100##"
    assert "*52*" not in str(default)
    assert "#2026#" not in str(
        OWNEnergyCommand.report_current_month_energy("51", 100, 2026, 10)
    )
    assert _oracle_out("*#18*51*52#26#9##") >= {"F460", "F461", "MyHomeServer1"}


def test_e1_report_current_month_energy_validation_unchanged() -> None:
    with pytest.raises(ValueError, match="both be provided or both omitted"):
        OWNEnergyCommand.report_current_month_energy("51", 100, year=2026)
    with pytest.raises(ValueError, match="year and month must be integers"):
        OWNEnergyCommand.report_current_month_energy("51", 100, 2026.5, 10)
    with pytest.raises(ValueError, match="year must be between 2000 and 2099"):
        OWNEnergyCommand.report_current_month_energy("51", 100, 1999, 10)
    with pytest.raises(ValueError, match="month must be between 1 and 12"):
        OWNEnergyCommand.report_current_month_energy("51", 100, 2026, 13)


def test_e1_parser_decodes_year_month_value() -> None:
    event = OWNMessage.parse("*#18*51*52#26#9*100##")
    assert isinstance(event, OWNEnergyEvent)
    assert event.message_type == MESSAGE_TYPE_MONTHLY_CONSUMPTION
    assert event.monthly_consumption == {
        "date": datetime.date(2026, 9, 1),
        "year": 2026,
        "month": 9,
        "value": 100,
    }
    assert event.human_readable_log == (
        "Sensor 51 is reporting a power consumption of 100 Wh for September 2026."
    )


@pytest.mark.parametrize("frame", ["*#18*51*52*12345##", "*#18*51*52#24#99*12345##"])
def test_e1_parser_without_valid_year_month_returns_none_fields(frame: str) -> None:
    event = OWNMessage.parse(frame)
    assert isinstance(event, OWNEnergyEvent)
    assert event.message_type == MESSAGE_TYPE_MONTHLY_CONSUMPTION
    assert event.monthly_consumption == {
        "date": None,
        "year": None,
        "month": None,
        "value": 12345,
    }
    assert event.monthly_consumption["value"] == 12345
    assert "unspecified month" in event.human_readable_log


# ---------------------------------------------------------------------------
# E2: Stop&Go WHERE 1N, N = 1..127 (addressing.md "Published WHERE forms";
# ORACLE_CONFIRM E2: *18*21*110##, *18*21*120##, *18*21*1127## and *18*22*120##
# are forwarded by the same nine emulated gateways as *18*21*11##).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("where", "expected"),
    [
        (1, "*18*21*11##"),
        ("9", "*18*21*19##"),
        (10, "*18*21*110##"),
        ("11", "*18*21*11##"),
        ("19", "*18*21*19##"),
        (20, "*18*21*120##"),
        (99, "*18*21*199##"),
        (109, "*18*21*1109##"),
        ("110", "*18*21*110##"),
        ("120", "*18*21*120##"),
        ("127", "*18*21*127##"),
        ("1110", "*18*21*1110##"),
        ("1127", "*18*21*1127##"),
        (" 1127 ", "*18*21*1127##"),
    ],
)
def test_e2_stop_and_go_builders_accept_full_1n_domain(where: str | int, expected: str) -> None:
    assert str(OWNStopAndGoCommand.open_breaker(where)) == expected
    assert str(OWNStopAndGoCommand.close_breaker(where)) == expected.replace("*21*", "*22*")


@pytest.mark.parametrize("where", [0, "1128", "1000", "10000", "invalid", "", "-1"])
def test_e2_stop_and_go_builders_refuse_outside_1n(where: str | int) -> None:
    with pytest.raises(ValueError, match="line must be 1..127 or address 11..1127"):
        OWNStopAndGoCommand.set_auto_reset(where, True)


def test_e2_stop_and_go_builders_oracle_rows() -> None:
    # The repository index holds the *18*21*11## / *18*22*11## rows (nine
    # gateways forward them); the review-session run recorded in
    # ORACLE_CONFIRM E2 forwarded *18*21*110##, *18*21*120##, *18*21*1127##
    # and *18*22*120## on the same nine, with address bytes 0A / 14 / 7F.
    nine = {"F453", "F453AV", "F454", "F459", "F460", "F461", "MH200N", "MH202", "MyHomeServer1"}
    assert _oracle_out("*18*21*11##") == nine
    assert _oracle_out("*18*22*11##") == nine


@pytest.mark.parametrize(
    ("frame", "line"),
    [
        ("*#18*11*250*0000000000001##", 1),
        ("*#18*19*251*1##", 9),
        ("*#18*110*250*0000000000001##", 10),
        ("*#18*120*250*0000000000001##", 20),
        ("*18*21*1127##", 127),
        ("*18*22*1100##", 100),
        ("*#18*1128*251*1##", None),
        ("*#18*101*251*1##", None),
        ("*#18*10*251*1##", None),
        ("*18*21*51##", None),
    ],
)
def test_e2_stop_and_go_events_decode_line(frame: str, line: int | None) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNStopAndGoEvent)
    assert event.line == line


def test_e2_stop_and_go_line_helper() -> None:
    assert STOP_AND_GO_LINE_MAX == 127
    assert stop_and_go_line("11") == 1
    assert stop_and_go_line("1127") == 127
    assert stop_and_go_line("1128") is None
    assert stop_and_go_line("") is None
    assert stop_and_go_line(None) is None
    assert OWNStopAndGoEvent("not a frame").line is None


# ---------------------------------------------------------------------------
# E3: DIMENSION 212 DAYS = 1..180 (dimensions.md "Stop&Go self-test interval";
# ORACLE_CONFIRM E3: *#18*11*#212*200## nack/silent on 12/12, #212*180 out on 9).
# ---------------------------------------------------------------------------


def test_e3_test_frequency_range_is_1_to_180() -> None:
    assert str(OWNStopAndGoCommand.set_test_frequency("1127", 180)) == "*#18*1127*#212*180##"
    assert str(OWNStopAndGoCommand.set_test_frequency(11, 1)) == "*#18*11*#212*1##"
    for days in (0, 181, 200, 255):
        with pytest.raises(ValueError, match="between 1 and 180"):
            OWNStopAndGoCommand.set_test_frequency(11, days)


# ---------------------------------------------------------------------------
# E4: DIMENSION 512#M*Tag*Val and WHAT 58#M (dimensions.md "DIMENSION 512 -
# monthly-average hourly series"; what.md "Historical-series commands").
# ---------------------------------------------------------------------------


def test_e4_dimension_512_hourly_average() -> None:
    event = OWNMessage.parse("*#18*51*512#10*1*100##")
    assert isinstance(event, OWNEnergyEvent)
    assert event.message_type == MESSAGE_TYPE_MONTHLY_AVERAGE_CONSUMPTION
    assert event.monthly_average_consumption == {
        "month": 10,
        "tag": 1,
        "hour": 0,
        "value": 100,
    }
    assert event.human_readable_log == (
        "Sensor 51 is reporting an average power consumption of 100 Wh at hour 0 of month 10."
    )
    last = OWNMessage.parse("*#18*51*512#10*24*7##")
    assert last.monthly_average_consumption["hour"] == 23


def test_e4_dimension_512_monthly_total() -> None:
    event = OWNMessage.parse("*#18*51*512#10*25*2400##")
    assert event.message_type == MESSAGE_TYPE_MONTHLY_AVERAGE_CONSUMPTION
    assert event.monthly_average_consumption == {
        "month": 10,
        "tag": 25,
        "hour": None,
        "value": 2400,
    }
    assert "monthly-average power consumption of 2400 Wh for month 10" in event.human_readable_log


@pytest.mark.parametrize(
    "frame",
    [
        "*#18*51*512#10*26*100##",  # tag outside 1..25
        "*#18*51*512#10*0*100##",
        "*#18*51*512#13*1*100##",  # month outside 1..12
        "*#18*51*512*1*100##",  # no month
        "*#18*51*512#10#5*1*100##",  # two parameters
        "*#18*51*512#10*1##",  # no value
        "*#18*51*512#10**100##",  # empty tag
        "*#18*51*512#10*1*100*5##",  # extra value
    ],
)
def test_e4_dimension_512_other_shapes_have_no_type(frame: str) -> None:
    event = OWNMessage.parse(frame)
    assert isinstance(event, OWNEnergyEvent)
    assert event.message_type is None
    assert event.monthly_average_consumption == {}


def test_e4_series_builders() -> None:
    assert str(OWNEnergyCommand.start_daily_series("51", 10, 1)) == "*18*57#10#1*51##"
    assert str(OWNEnergyCommand.start_monthly_average_series(51, 10)) == "*18*58#10*51##"
    assert str(OWNEnergyCommand.get_monthly_average_consumption("51", 10)) == "*#18*51*512#10##"
    assert OWNEnergyCommand.start_daily_series("51", 10, 1).human_readable_log
    assert OWNEnergyCommand.start_monthly_average_series(51, 10).human_readable_log
    assert OWNEnergyCommand.get_monthly_average_consumption("51", 10).human_readable_log
    for frame in ("*18*57#10#1*51##", "*18*58#10*51##", "*#18*51*512#10##"):
        assert len(_oracle_out(frame)) == 8, frame
    with pytest.raises(ValueError, match="month must be between 1 and 12"):
        OWNEnergyCommand.start_monthly_average_series(51, 13)
    with pytest.raises(ValueError, match="day must be between 1 and 31"):
        OWNEnergyCommand.start_daily_series(51, 10, 0)
    for bad in (True, 10.5, "x", None):
        with pytest.raises(ValueError, match="month must be between 1 and 12"):
            OWNEnergyCommand.get_monthly_average_consumption(51, bad)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("frame", "dimension", "month", "day"),
    [
        ("*18*57#10#5*51##", 511, 10, 5),
        ("*18*58#10*51##", 512, 10, None),
        ("*18*59#2*51##", 513, 2, None),
        ("*18*510#12*51##", 514, 12, None),
    ],
)
def test_e4_series_start_events(frame: str, dimension: int, month: int, day: int | None) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNEnergyEvent)
    assert event.message_type == MESSAGE_TYPE_HISTORICAL_SERIES_START
    assert event.series_dimension == dimension
    assert event.series_month == month
    assert event.series_day == day
    assert f"DIMENSION {dimension} series" in event.human_readable_log


@pytest.mark.parametrize(
    "frame",
    [
        "*18*57#10*51##",  # 57 needs M and D
        "*18*58#10#5*51##",  # 58 takes M only
        "*18*58*51##",
        "*18*57#13#1*51##",
        "*18*57#10#32*51##",
        "*18*59#0*51##",
        "*18*56#10*51##",  # older graph WHAT, not in the enumerated set
    ],
)
def test_e4_series_start_other_shapes_have_no_type(frame: str) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNEnergyEvent)
    assert event.message_type is None
    assert event.series_dimension is None


def test_e4_series_constants() -> None:
    assert HISTORICAL_SERIES_DIMENSIONS == {
        ENERGY_SERIES_DAILY: 511,
        ENERGY_SERIES_MONTHLY_AVERAGE: 512,
        ENERGY_SERIES_CURRENT_YEAR: 513,
        ENERGY_SERIES_PREVIOUS_YEAR: 514,
    }


# ---------------------------------------------------------------------------
# E5: DIMENSION 71 / 72#Tot_N / 73 and WHATs 71 / 73[#Time] / 74 / 75#Tot_N
# (dimensions.md "Energy Management actuator information"; what.md "Actuator
# commands", "Reset totalizer"; firmware oracle energy-ts10 rows).
# ---------------------------------------------------------------------------


def test_e5_dimension_71_actuator_status() -> None:
    event = OWNMessage.parse("*#18*71#0*71*0*1*0*0*1*1##")
    assert isinstance(event, OWNEnergyEvent)
    assert event.message_type == MESSAGE_TYPE_ACTUATOR_STATUS
    assert event.is_actuator is True
    assert event.address == "71#0"
    assert event.actuator_status == {
        "disabled": False,
        "forced": True,
        "below_threshold": False,
        "protection": False,
        "local_phase_disabled": True,
        "advanced": True,
    }
    assert event.human_readable_log == "Actuator 71#0 is enabled, forced."
    basic = OWNMessage.parse("*#18*71#0*71*1*0*1*1*0*2##")
    assert basic.actuator_status == {
        "disabled": True,
        "forced": False,
        "below_threshold": True,
        "protection": True,
        "local_phase_disabled": False,
        "advanced": False,
    }
    assert basic.human_readable_log == "Actuator 71#0 is disabled."


@pytest.mark.parametrize(
    "frame",
    [
        "*#18*71#0*71*0*1*0*0*1##",  # five fields
        "*#18*71#0*71*0*1*0*0*1*1*0##",  # seven fields
        "*#18*71#0*71*2*1*0*0*1*1##",  # flag outside 0/1
        "*#18*71#0*71*0*1*0*0*1*3##",  # advanced outside 1/2
        "*#18*71#0*71##",  # the request itself
    ],
)
def test_e5_dimension_71_other_shapes_have_no_type(frame: str) -> None:
    event = OWNMessage.parse(frame)
    assert getattr(event, "message_type", None) is None
    if isinstance(event, OWNEnergyEvent):
        assert event.actuator_status == {}


def test_e5_dimension_72_totalizer_state() -> None:
    event = OWNMessage.parse("*#18*71#0*72#1*12345*5*10*26*12*30##")
    assert isinstance(event, OWNEnergyEvent)
    assert event.message_type == MESSAGE_TYPE_TOTALIZER_STATE
    assert event.totalizer_number == 1
    assert event.totalizer == {
        "number": 1,
        "value": 12345,
        "reset": datetime.datetime(2026, 10, 5, 12, 30),
        "day": 5,
        "month": 10,
        "year": 2026,
        "hour": 12,
        "minute": 30,
    }
    assert event.human_readable_log == (
        "Actuator 71#0 totalizer 1 is 12345 Wh since 2026-10-05 12:30."
    )
    four_digit = OWNMessage.parse("*#18*71#0*72#2*7*1*1*2025*0*0##")
    assert four_digit.totalizer["reset"] == datetime.datetime(2025, 1, 1, 0, 0)
    assert four_digit.totalizer_number == 2
    invalid_stamp = OWNMessage.parse("*#18*71#0*72#2*7*31*2*26*0*0##")
    assert invalid_stamp.message_type == MESSAGE_TYPE_TOTALIZER_STATE
    assert invalid_stamp.totalizer["reset"] is None
    assert invalid_stamp.totalizer["day"] == 31
    assert invalid_stamp.human_readable_log == "Actuator 71#0 totalizer 2 is 7 Wh."


@pytest.mark.parametrize(
    "frame",
    [
        "*#18*71#0*72*12345*5*10*26*12*30##",  # no Tot_N
        "*#18*71#0*72#3*12345*5*10*26*12*30##",  # Tot_N outside 1..2
        "*#18*71#0*72#1*12345*5*10*26*12##",  # five values
        "*#18*71#0*72#1*12345**10*26*12*30##",  # empty field
        "*#18*71#0*72#1#2*12345*5*10*26*12*30##",  # two parameters
    ],
)
def test_e5_dimension_72_other_shapes_have_no_type(frame: str) -> None:
    event = OWNMessage.parse(frame)
    assert isinstance(event, OWNEnergyEvent)
    assert event.message_type is None
    assert event.totalizer == {}
    assert event.totalizer_number is None


@pytest.mark.parametrize("level", [1, 2, 3])
def test_e5_dimension_73_level(level: int) -> None:
    event = OWNMessage.parse(f"*#18*71#0*73*{level}##")
    assert isinstance(event, OWNEnergyEvent)
    assert event.message_type == MESSAGE_TYPE_DIFFERENTIAL_CURRENT_LEVEL
    assert event.differential_current_level == level
    assert event.human_readable_log == f"Actuator 71#0 differential-current level is {level}."


@pytest.mark.parametrize("frame", ["*#18*71#0*73*0##", "*#18*71#0*73*4##", "*#18*71#0*73*1*2##", "*#18*71#0*73*##"])
def test_e5_dimension_73_other_values_have_no_type(frame: str) -> None:
    event = OWNMessage.parse(frame)
    assert isinstance(event, OWNEnergyEvent)
    assert event.message_type is None
    assert event.differential_current_level is None


@pytest.mark.parametrize(
    ("frame", "message_type", "forcing_time", "totalizer_number", "log"),
    [
        ("*18*71*71#0##", MESSAGE_TYPE_ACTUATOR_ENABLED, None, None, "Actuator 71#0 is enabled."),
        ("*18*73#15*71#0##", MESSAGE_TYPE_ACTUATOR_FORCED, 15, None, "Actuator 71#0 is forced for 150 minutes."),
        ("*18*73*71#0##", MESSAGE_TYPE_ACTUATOR_FORCED, None, None, "Actuator 71#0 is forced for the default time."),
        ("*18*74*71#0##", MESSAGE_TYPE_ACTUATOR_FORCING_ENDED, None, None, "Actuator 71#0 forcing ended."),
        ("*18*75#1*71#0##", MESSAGE_TYPE_TOTALIZER_RESET, None, 1, "Actuator 71#0 totalizer 1 reset."),
        ("*18*75#2*71#0##", MESSAGE_TYPE_TOTALIZER_RESET, None, 2, "Actuator 71#0 totalizer 2 reset."),
    ],
)
def test_e5_actuator_what_events(
    frame: str,
    message_type: str,
    forcing_time: int | None,
    totalizer_number: int | None,
    log: str,
) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNEnergyEvent)
    assert event.message_type == message_type
    assert event.forcing_time == forcing_time
    assert event.totalizer_number == totalizer_number
    assert event.human_readable_log == log
    assert event.is_actuator is True


@pytest.mark.parametrize(
    "frame",
    [
        "*18*71#1*71#0##",  # 71 takes no parameter
        "*18*73#0*71#0##",  # Time outside 1..254
        "*18*73#255*71#0##",
        "*18*73#15#1*71#0##",  # two parameters
        "*18*74#1*71#0##",  # 74 takes no parameter
        "*18*75*71#0##",  # 75 needs Tot_N
        "*18*75#3*71#0##",  # Tot_N outside 1..2
        "*18*76*71#0##",  # not a documented WHAT
    ],
)
def test_e5_actuator_what_other_shapes_have_no_type(frame: str) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNEnergyEvent)
    assert event.message_type is None
    assert event.forcing_time is None
    assert event.totalizer_number is None


def test_e5_actuator_builders() -> None:
    assert str(OWNEnergyCommand.enable_actuator(71)) == "*18*71*71#0##"
    assert str(OWNEnergyCommand.force_actuator("71#0", 15)) == "*18*73#15*71#0##"
    assert str(OWNEnergyCommand.force_actuator("71")) == "*18*73*71#0##"
    assert str(OWNEnergyCommand.end_actuator_forcing("71#0")) == "*18*74*71#0##"
    assert str(OWNEnergyCommand.reset_totalizer(71, 1)) == "*18*75#1*71#0##"
    assert str(OWNEnergyCommand.reset_totalizer(71, 2)) == "*18*75#2*71#0##"
    assert str(OWNEnergyCommand.request_actuator_status(71)) == "*#18*71#0*71##"
    assert str(OWNEnergyCommand.request_totalizer(71, 1)) == "*#18*71#0*72#1##"
    assert str(OWNEnergyCommand.request_totalizer("71#0", 2)) == "*#18*71#0*72#2##"
    assert str(OWNEnergyCommand.request_differential_current_level(71)) == "*#18*71#0*73##"
    for builder in (
        OWNEnergyCommand.enable_actuator(71),
        OWNEnergyCommand.force_actuator(71, 1),
        OWNEnergyCommand.force_actuator(71),
        OWNEnergyCommand.end_actuator_forcing(71),
        OWNEnergyCommand.reset_totalizer(71, 1),
        OWNEnergyCommand.request_actuator_status(71),
        OWNEnergyCommand.request_totalizer(71, 1),
        OWNEnergyCommand.request_differential_current_level(71),
    ):
        assert builder.human_readable_log
        assert isinstance(OWNCommand.parse(str(builder)), OWNEnergyCommand)


def test_e5_actuator_builders_oracle_rows() -> None:
    nine = {"F453", "F453AV", "F454", "F459", "F460", "F461", "MH200N", "MH202", "MyHomeServer1"}
    for frame in ("*18*71*71#0##", "*18*73#15*71#0##", "*18*73*71#0##", "*18*74*71#0##"):
        assert _oracle_out(frame) == nine, frame
    eight = nine - {"F453"}
    for frame in (
        "*18*75#1*71#0##",
        "*18*75#2*71#0##",
        "*#18*71#0*71##",
        "*#18*71#0*72#1##",
        "*#18*71#0*72#2##",
        "*#18*71#0*73##",
    ):
        assert _oracle_out(frame) == eight, frame


def test_e5_actuator_builders_validation() -> None:
    for where in ("51", "11", 56):
        with pytest.raises(ValueError, match="expected 7N#0"):
            OWNEnergyCommand.enable_actuator(where)
    with pytest.raises(ValueError, match="time must be between 1 and 254"):
        OWNEnergyCommand.force_actuator(71, 0)
    with pytest.raises(ValueError, match="time must be between 1 and 254"):
        OWNEnergyCommand.force_actuator(71, 255)
    for number in (0, 3, True, 1.5):
        with pytest.raises(ValueError, match="number must be between 1 and 2"):
            OWNEnergyCommand.reset_totalizer(71, number)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="number must be between 1 and 2"):
            OWNEnergyCommand.request_totalizer(71, number)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# E6: DIMENSION 511 tags 1..24 hourly, 25 daily total, nothing else
# (dimensions.md "DIMENSION 511 - daily hourly series").
# ---------------------------------------------------------------------------


def test_e6_dimension_511_tag_range() -> None:
    first = OWNMessage.parse("*#18*51*511#10#5*1*100##")
    assert first.message_type == MESSAGE_TYPE_HOURLY_CONSUMPTION
    assert first.hourly_consumption["hour"] == 0
    last = OWNMessage.parse("*#18*51*511#10#5*24*100##")
    assert last.message_type == MESSAGE_TYPE_HOURLY_CONSUMPTION
    assert last.hourly_consumption["hour"] == 23
    total = OWNMessage.parse("*#18*51*511#10#5*25*100##")
    assert total.message_type == MESSAGE_TYPE_DAILY_CONSUMPTION
    assert total.daily_consumption["value"] == 100
    for tag in (0, 26, 99):
        event = OWNMessage.parse(f"*#18*51*511#10#5*{tag}*100##")
        assert isinstance(event, OWNEnergyEvent)
        assert event.message_type is None
        assert event.hourly_consumption == {}
        assert event.daily_consumption == {}


# ---------------------------------------------------------------------------
# E7: DIMENSION 53 / 54 are parameter-less scalars (dimensions.md "DIMENSION
# 53 - current-month partial totalizer", "DIMENSION 54 - current-day partial
# totalizer"; captures *#18*52*53*1## and *#18*51*54*13165##).
# ---------------------------------------------------------------------------


def test_e7_partial_report_builders_have_no_parameter() -> None:
    assert str(OWNEnergyCommand.report_partial_month_energy("52", 1)) == "*#18*52*53*1##"
    assert str(OWNEnergyCommand.report_partial_day_energy("51", 13165)) == "*#18*51*54*13165##"
    with pytest.raises(TypeError):
        OWNEnergyCommand.report_partial_month_energy("51", 100, 10)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        OWNEnergyCommand.report_partial_day_energy("51", 100, 5)  # type: ignore[call-arg]
    assert str(OWNEnergyCommand.get_partial_monthly_consumption("51")) == "*#18*51*53##"
    assert str(OWNEnergyCommand.get_partial_daily_consumption("51")) == "*#18*51*54##"


# ---------------------------------------------------------------------------
# E8: Wh, not kWh (dimensions.md "DIMENSION 72 - totalizer state";
# README.md "Measurement model").
# ---------------------------------------------------------------------------


def test_e8_documentation_says_wh() -> None:
    root = Path(__file__).resolve().parent.parent
    readme_row = next(
        line for line in (root / "README.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| **18** |")
    )
    matrix_row = next(
        line
        for line in (root / "docs" / "protocol_conformance_matrix.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| **18** |")
    )
    for row in (readme_row, matrix_row):
        assert "kWh" not in row
        assert "(Wh)" in row


# ---------------------------------------------------------------------------
# E9: DIMENSION 1200 Time is the report-on-change parameter (dimensions.md
# "DIMENSION 1200 - automatic active-power updates").
# ---------------------------------------------------------------------------


def test_e9_dimension_1200_docstrings_describe_report_on_change() -> None:
    for doc in (
        OWNEnergyEvent.update_interval.__doc__,
        OWNEnergyCommand.start_sending_instant_power.__doc__,
        OWNEnergyCommand.stream_duration.__doc__,
    ):
        assert doc is not None
        assert "report-on-change" in doc
        assert "stream duration" not in doc
    assert "report-on-change" in (OWNEnergyEvent.stream_duration.__doc__ or "")
    event = OWNMessage.parse("*#18*56*1200#1*2##")
    assert event.update_interval == 2
    assert event.stream_duration == 2
    assert event.is_streaming_active is True


# ---------------------------------------------------------------------------
# E10: the family prefix is part of the WHERE (addressing.md "preserve the
# complete syntactic form"); ``sensor`` stays for compatibility.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("frame", "address", "sensor", "log"),
    [
        ("*#18*51*113*572##", "51", "1", "Sensor 51 is reporting an active power draw of 572 W."),
        ("*#18*77#0*113*161##", "77#0", "7", "Sensor 77#0 is reporting an active power draw of 161 W."),
        ("*#18*51*51*23791364##", "51", "1", "Sensor 51 is reporting a total power consumption of 23791364 Wh."),
        ("*#18*52*53*1##", "52", "2", "Sensor 52 is reporting a power consumption of 1 Wh up to now this month."),
        ("*#18*51*54*13165##", "51", "1", "Sensor 51 is reporting a power consumption of 13165 Wh up to now today."),
        ("*#18*56*1200#1*2##", "56", "6", "Sensor 56 automatic updates for 2 minutes."),
    ],
)
def test_e10_logs_keep_the_family_prefix(frame: str, address: str, sensor: str, log: str) -> None:
    event = OWNMessage.parse(frame)
    assert isinstance(event, OWNEnergyEvent)
    assert event.address == address
    assert event.target_address == address
    assert event.sensor == sensor
    assert event.human_readable_log == log


def test_e10_event_without_what_or_dimension_keeps_defaults() -> None:
    event = OWNEnergyEvent("*#18*51##")
    assert event.address == "51"
    assert event.message_type is None
    assert event.monthly_consumption == {}


def test_e10_address_of_series_logs() -> None:
    hourly = OWNMessage.parse("*#18*51*511#10#5*3*100##")
    assert hourly.human_readable_log.startswith("Sensor 51 is reporting a power consumption of 100 Wh for ")
    daily = OWNMessage.parse("*#18*51*513#10*5*250##")
    assert daily.human_readable_log.startswith("Sensor 51 is reporting a power consumption of 250 Wh for ")


# ---------------------------------------------------------------------------
# E11: DIMENSION 259 is "Check off/on" (dimensions.md "Individual Stop&Go
# flags"); WHAT 28/29 are the tracking controls (what.md "Historical Stop&Go
# controls"). The two are no longer equated.
# ---------------------------------------------------------------------------


def test_e11_dimension_259_is_check_not_tracking() -> None:
    off = OWNEvent.parse("*#18*11*259*1##")
    assert isinstance(off, OWNStopAndGoEvent)
    assert off.flag_dimension == STOP_AND_GO_DIM_CHECK_OFF
    assert off.is_check_active is False
    assert off.is_tracking_active is None
    on = OWNEvent.parse("*#18*11*259*0##")
    assert on.is_check_active is True
    assert on.is_tracking_active is None
    tracking = OWNEvent.parse("*18*28*11##")
    assert tracking.is_tracking_active is True
    assert tracking.is_check_active is None


# ---------------------------------------------------------------------------
# E12: the `*#18*1*1##` / `*#18*1*11*...##` fixtures are grammar-only
# (dimensions.md "Identifier table": no DIMENSION 1, active power is 113;
# zigbee-variant.md "Dimension table": 11 is Voltage; no kWh on the wire).
# ---------------------------------------------------------------------------


def test_e12_golden_fixtures_are_not_labelled_as_spec() -> None:
    corpus = json.loads((Path(__file__).parent / "golden" / "corpus.json").read_text(encoding="utf-8"))
    records = {r["id"]: r for r in corpus}
    for fixture_id in (
        "energy.req.active_power.meter1",
        "energy.resp.active_power.meter1.1450",
        "energy.req.lifetime.meter1",
        "energy.resp.lifetime.meter1.45230",
    ):
        record = records[fixture_id]
        assert record["source"] == "conflict", fixture_id
        assert "kWh" not in record["mcp_notes"]
        assert "message_type None" in record["mcp_notes"]
        parsed = OWNMessage.parse(record["frame"])
        assert getattr(parsed, "message_type", None) is None
    assert records["energy.resp.active_power.meter51.572"]["source"] == "community-plant-capture"
    assert OWNMessage.parse("*#18*51*113*572##").message_type == MESSAGE_TYPE_ACTIVE_POWER
