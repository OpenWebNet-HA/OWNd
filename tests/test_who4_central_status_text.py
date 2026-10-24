"""``central_status`` deprecation text names the real reason.

``*#4*#0*14##`` is forwarded to the bus by F453, F453AV, F460, F461, MH200N
and MyHomeServer1 in the firmware oracle (``trace-corpus``, ``nack``/``out``)
and refused by the other six; either way it goes unanswered without a
central unit. The frame is unchanged.
"""

from __future__ import annotations

import warnings

from OWNd.message import OWNHeatingCommand


def test_central_status_deprecation_names_the_real_reason() -> None:
    doc = OWNHeatingCommand.central_status.__doc__ or ""
    assert "which gateways refuse" not in doc
    assert "unanswered without a central unit" in doc
    assert "trace-corpus" in doc
    assert "F461" in doc

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        command = OWNHeatingCommand.central_status("#0")
    assert str(command) == "*#4*#0*14##"
    (warning,) = caught
    assert issubclass(warning.category, DeprecationWarning)
    text = str(warning.message)
    assert "refuse" not in text
    assert "unanswered without a central unit" in text
    assert "status('#0')" in text


def test_central_status_frame_and_default_are_unchanged() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert str(OWNHeatingCommand.central_status()) == "*#4*#0*14##"
        assert str(OWNHeatingCommand.central_status("#0#1")) == "*#4*#0#1*14##"
