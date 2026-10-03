from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from OWNd.profiles import (
    CANONICAL_PROFILE_ORDER,
    DEFAULT_SUPPORTED_WHO,
    WHO_ALARM,
    WHO_CEN,
    WHO_CEN_PLUS,
    WHO_LIGHTING,
    WHO_LOAD_CONTROL,
    WHO_SOUND,
    WHO_SOUND_DIFFUSION,
    _PROFILES,
    GatewayProfile,
    H4890Profile,
    MH200NProfile,
    MH200Profile,
    MH202Profile,
    canonical_profiles,
    get_gateway_profile,
)


@pytest.mark.parametrize("name", ["MH200", "mh200", "MH-200", "MH 200"])
def test_mh200_is_not_the_mh200n(name: str) -> None:
    """A live MH200 answers *#16*0*5## with every amplifier and source (#53)."""
    profile = get_gateway_profile(name)

    assert isinstance(profile, MH200Profile)
    assert profile.model_name == "MH200"
    assert profile.supports_audio is True
    assert profile.supports_who(WHO_SOUND)


def test_mh200_keeps_the_mh200n_pacing() -> None:
    mh200 = get_gateway_profile("MH200")
    mh200n = get_gateway_profile("MH200N")

    assert isinstance(mh200n, MH200NProfile)
    assert mh200.max_command_sessions == mh200n.max_command_sessions == 1
    assert mh200.command_queue_delay == mh200n.command_queue_delay
    assert mh200.max_queue_size == mh200n.max_queue_size
    assert mh200.event_keepalive_interval == mh200n.event_keepalive_interval
    # TiMH200N release notes: MH200N added CEN+ (WHO 25); legacy MH200 only supports classic CEN (WHO 15)
    assert set(mh200n.supported_who) - set(mh200.supported_who) == {WHO_CEN_PLUS}
    assert mh200.supports_who(WHO_CEN) is True
    assert not mh200.supports_who(WHO_CEN_PLUS)
    assert mh200n.supports_who(WHO_CEN) is True
    assert mh200n.supports_who(WHO_CEN_PLUS) is True


def test_mh200n_audio_enabled_and_verified() -> None:
    """MH200N verified answering *#16*0*5## without NACK (MyHOME#427 comment 5848181845)."""
    profile = get_gateway_profile("MH200N")

    assert profile.supports_audio is True
    assert profile.supports_who(WHO_SOUND)


def test_profile_lookup_accepts_common_name_variants() -> None:
    profile = get_gateway_profile("MyHome Server 1")

    assert profile.model_name == "MyHomeServer1"
    assert profile.supports_session_count(4)
    assert profile.supports_who(WHO_SOUND)


def test_f461_profile_lookup() -> None:
    profile = get_gateway_profile("F461")

    assert profile.model_name == "F461"
    assert profile.supports_session_count(4)
    assert profile.supports_hmac is True
    assert profile.command_queue_delay == 0.05
    assert profile.supports_native_transitions is True


def test_f455_basic_gateway_has_no_audio() -> None:
    """F455 Basic Gateway has a single SCS bus and no audio hardware (RA00125AB / MyHOME#466)."""
    f455 = get_gateway_profile("F455")
    assert f455.supports_audio is False
    assert not f455.supports_who(WHO_SOUND)
    assert not f455.supports_who(WHO_SOUND_DIFFUSION)
    assert f455.event_keepalive_interval is None
    assert f455.max_command_sessions == 4
    assert f455.default_command_sessions == 2


def test_unknown_gateway_uses_conservative_limits() -> None:
    profile = get_gateway_profile("Future gateway")

    assert profile.model_name == "Future gateway"
    assert profile.max_command_sessions == 1
    assert profile.event_keepalive_interval is None


def test_v2_profile_compatibility_aliases() -> None:
    profile = get_gateway_profile("MH201")

    assert profile.max_workers == profile.max_command_sessions
    assert profile.default_workers == profile.default_command_sessions
    assert profile.command_delay == profile.command_queue_delay
    assert profile.can_support_workers(1)


def test_load_control_and_sound_diffusion_have_distinct_who_codes() -> None:
    assert WHO_LOAD_CONTROL == 3
    assert WHO_SOUND_DIFFUSION == 22
    assert WHO_LOAD_CONTROL in DEFAULT_SUPPORTED_WHO
    assert WHO_SOUND_DIFFUSION in DEFAULT_SUPPORTED_WHO


@pytest.mark.parametrize("name", ["H4890", "h4890", "AM4890", "LN4890", "LN4890A", "4890"])
def test_4890_family_carries_the_burglar_alarm(name: str) -> None:
    """The H4890 relays the alarm bus: WHO 5 frames are in the MyHOME#466 and #564 captures."""
    profile = get_gateway_profile(name)

    assert isinstance(profile, H4890Profile)
    assert profile.model_name == "H4890"
    assert profile.supports_who(WHO_ALARM)
    # Class default plus WHO 5: absence in a trace is not inferred.
    assert set(profile.supported_who) == {*DEFAULT_SUPPORTED_WHO, WHO_ALARM}
    assert "Burglar alarm (WHO 5)" in profile.features_summary


def test_h4890_does_not_claim_a_measured_auth_scheme() -> None:
    summary = get_gateway_profile("H4890").features_summary
    assert "Auth unmeasured" in summary
    assert "HMAC" not in summary and "Legacy password" not in summary


@pytest.mark.parametrize("name", ["HC4890", "MH4892", "MH4893C", "3488", "3487", "myhometouch", "myhometouch10"])
def test_other_touch_screens_stay_generic_until_captured(name: str) -> None:
    """Only the 3.5" 4890 family is measured; other screens may carry WHO 4 and must not be restricted."""
    profile = get_gateway_profile(name)

    assert not isinstance(profile, H4890Profile)


@pytest.mark.parametrize("name", ["MH202", "mh202", "MH-202", "MH 202"])
def test_mh202_carries_the_burglar_alarm(name: str) -> None:
    """The MH202 relays the alarm bus: WHO 5 frames verified in MyHOME#564 (comment 5917195080)."""
    profile = get_gateway_profile(name)

    assert isinstance(profile, MH202Profile)
    assert profile.model_name == "MH202"
    assert profile.supports_who(WHO_ALARM)
    assert set(DEFAULT_SUPPORTED_WHO) <= set(profile.supported_who)
    assert "Burglar alarm (WHO 5)" in profile.features_summary


def test_only_supported_families_advertise_the_alarm() -> None:
    """Only profiles with verified alarm captures claim WHO 5."""
    assert WHO_ALARM == 5
    assert WHO_ALARM not in DEFAULT_SUPPORTED_WHO
    for key, profile in _PROFILES.items():
        assert profile.supports_who(WHO_ALARM) is (key in {"h4890", "mh202"})


def test_canonical_order_covers_registry() -> None:
    assert set(CANONICAL_PROFILE_ORDER) == set(_PROFILES)


def test_sound_system_feature_matches_capabilities() -> None:
    """Every profile advertises Sound system iff it supports WHO 16 or audio."""
    for profile in _PROFILES.values():
        has_sound = profile.supports_who(WHO_SOUND) or profile.supports_audio
        assert ("Sound system (WHO 16)" in profile.features_summary) is has_sound


def test_hmac_profiles_never_show_legacy_auth() -> None:
    """Profiles with HMAC authentication never advertise legacy password auth."""
    for profile in canonical_profiles():
        if profile.supports_hmac:
            assert "Legacy password auth" not in profile.features_summary


def test_slow_hmac_profile_does_not_pick_up_sound_or_legacy_auth_from_delay() -> None:
    """A 150 ms delay profile does not inherit sound or legacy auth heuristics."""
    custom = GatewayProfile(
        model_name="SlowHMAC",
        command_queue_delay=0.15,
        supports_hmac=True,
        supports_audio=False,
        supported_who=(WHO_LIGHTING,),
    )
    assert custom.features_summary == "Safe pacing, HMAC-SHA2"
    assert "Legacy password auth" not in custom.features_summary
    assert "Sound system (WHO 16)" not in custom.features_summary


def test_mh201_shows_clock_diagnostics() -> None:
    """MH201 includes Clock diagnostics from extra_features."""
    mh201 = get_gateway_profile("MH201")
    assert "Clock diagnostics" in mh201.features_summary


def test_gateway_profile_summary_properties() -> None:
    """Verify summary strings across diverse gateway families."""
    mhs1 = get_gateway_profile("MyHomeServer1")
    assert mhs1.concurrency_summary == "4 sessions (2 default)"
    assert mhs1.queue_delay_summary == "20 ms"
    assert mhs1.keepalive_summary == "OS TCP only"
    assert (
        mhs1.features_summary
        == "HMAC-SHA2, Native transitions, Extended frames, Sound system (WHO 16)"
    )

    f454 = get_gateway_profile("F454")
    assert f454.concurrency_summary == "4 sessions"
    assert f454.queue_delay_summary == "50 ms"
    assert f454.keepalive_summary == "90 s"
    assert (
        f454.features_summary
        == "HMAC-SHA2, Native transitions, Extended frames, Sound system (WHO 16)"
    )

    f455 = get_gateway_profile("F455")
    assert f455.concurrency_summary == "4 sessions (2 default)"
    assert f455.queue_delay_summary == "50 ms"
    assert f455.keepalive_summary == "OS TCP only"
    assert (
        f455.features_summary
        == "HMAC-SHA2, Native transitions, Extended frames"
    )

    mh200 = get_gateway_profile("MH200")
    assert mh200.concurrency_summary == "1 session"
    assert mh200.queue_delay_summary == "150 ms"
    assert mh200.keepalive_summary == "90 s"
    assert (
        mh200.features_summary
        == "Safe pacing, Legacy password auth, Sound system (WHO 16)"
    )

    mh200n = get_gateway_profile("MH200N")
    assert mh200n.concurrency_summary == "1 session"
    assert mh200n.queue_delay_summary == "150 ms"
    assert mh200n.keepalive_summary == "90 s"
    assert (
        mh200n.features_summary
        == "Safe pacing, Legacy password auth, Sound system (WHO 16)"
    )

    generic = get_gateway_profile("Unknown")
    assert generic.keepalive_summary == "OS TCP only"
    assert generic.features_summary == "Conservative fallback"


def test_readme_gateway_profiles_table_is_in_sync() -> None:
    """Verify README.md gateway profiles table matches OWNd.profiles declarations."""
    from scripts.update_readme_profiles import sync_readme_profiles

    assert sync_readme_profiles(check_only=True) is True, (
        "README.md gateway profiles table is out of date. "
        "Run 'python scripts/update_readme_profiles.py' to update it."
    )

