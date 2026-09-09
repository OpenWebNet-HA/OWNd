"""Small public-API smoke tests for the pre-hardening baseline."""

from OWNd.message import OWNLightingEvent, OWNMessage, OWNSignaling


def test_ack_frame_is_parsed_as_signaling() -> None:
    """An ACK frame remains available through the public parser."""
    message = OWNMessage.parse("*#*1##")

    assert isinstance(message, OWNSignaling)
    assert message.is_ack


def test_lighting_frame_is_parsed_as_event() -> None:
    """A basic lighting frame remains available through the public parser."""
    message = OWNMessage.parse("*1*1*12##")

    assert isinstance(message, OWNLightingEvent)
    assert message.is_on
