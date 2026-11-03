"""WHO 7 receive_video builds the four-digit camera WHERE (WHO 7 PDF WHERE table)."""

import pytest

from OWNd.message import OWNAVCommand


@pytest.mark.parametrize(
    ("where", "frame"),
    [
        (5, "*7*0*4005##"),  # single digit is zero-padded: Camera 05
        ("5", "*7*0*4005##"),
        (0, "*7*0*4000##"),  # Camera 00
        (12, "*7*0*4012##"),
        (99, "*7*0*4099##"),  # Camera 99, top of the table
        (4005, "*7*0*4005##"),  # already a WHERE
        ("4005", "*7*0*4005##"),
        ("04005", "*7*0*4005##"),  # non-canonical strings normalise from the parsed value
        ("+4005", "*7*0*4005##"),
        (4100, "*7*0*4100##"),  # 4000..4999 stays accepted (decision D20, OWNd#128)
        (4999, "*7*0*4999##"),
    ],
)
def test_receive_video_zero_pads_the_camera_number(where, frame: str) -> None:
    command = OWNAVCommand.receive_video(where)
    assert command is not None
    assert str(command) == frame


@pytest.mark.parametrize("bad", [100, 3999, 5000, -1, "x", None])
def test_receive_video_refuses_values_outside_the_where_table(bad) -> None:
    assert OWNAVCommand.receive_video(bad) is None


@pytest.mark.parametrize(
    ("where", "camera"),
    [(5, "05"), ("5", "05"), (0, "00"), (12, "12"), (4005, "05"), ("04005", "05"), (4099, "99")],
)
def test_receive_video_log_names_the_camera_with_two_digits(where, camera: str) -> None:
    # Both branches describe the camera the same way (decision D13: the log is pinned).
    command = OWNAVCommand.receive_video(where)
    assert command is not None
    assert command.human_readable_log == f"Opening video stream for camera {camera}."
