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
    WHO_AUTOMATION,
    WHO_CEN,
    WHO_CEN_PLUS,
    WHO_ENERGY,
    WHO_HEATING,
    WHO_LIGHTING,
    WHO_LOAD_CONTROL,
    WHO_SCENARIO,
    WHO_SOUND,
    WHO_SOUND_DIFFUSION,
    _PROFILES,
    F452Profile,
    F452VProfile,
    F453Profile,
    F453AVProfile,
    F454Profile,
    F455Profile,
    GatewayProfile,
    H4684Profile,
    H4890Profile,
    MH200NProfile,
    MH200Profile,
    MH202Profile,
    canonical_profiles,
    get_gateway_profile,
    parse_firmware_version,
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
    # Legrand WHO 25 spec (2010, p. 13): MH200 lacks WHO 25 (CEN+ / dry contact & IR); MH200N supports it.
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
    """Sound is labelled iff a profile supports WHO 16 or audio, and measured only when audio_measured."""
    for profile in _PROFILES.values():
        has_sound = profile.supports_who(WHO_SOUND) or profile.supports_audio
        summary = profile.features_summary
        assert ("Sound system (WHO 16)" in summary) is (
            has_sound and profile.audio_measured
        )
        assert ("Sound unmeasured" in summary) is (
            has_sound and not profile.audio_measured
        )


def test_sound_is_measured_only_where_a_reply_is_captured() -> None:
    """Only MH200, MH200N and H4890 have captured WHO 16/22 replies (MyHOME#53, #427, #466)."""
    measured = {
        key
        for key, profile in _PROFILES.items()
        if "Sound system (WHO 16)" in profile.features_summary
    }
    assert measured == {"mh200", "mh200n", "h4890"}
    for key in (
        "f452",
        "f452v",
        "f453",
        "f453av",
        "f454",
        "f461",
        "mh201",
        "mh202",
        "myhomeserver1",
    ):
        profile = _PROFILES[key]
        assert profile.supports_audio is True
        assert profile.audio_measured is False
        assert "Sound unmeasured" in profile.features_summary
    assert get_gateway_profile("F453AV", "2.1.7").audio_measured is False


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
        == "HMAC-SHA2, Native transitions, Extended frames, Sound unmeasured"
    )

    f454 = get_gateway_profile("F454")
    assert f454.concurrency_summary == "4 sessions"
    assert f454.queue_delay_summary == "50 ms"
    assert f454.keepalive_summary == "90 s"
    assert (
        f454.features_summary
        == "HMAC-SHA2, Native transitions, Extended frames, Sound unmeasured"
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


def test_parse_firmware_version_normalization_and_edges() -> None:
    """Verify parse_firmware_version normalizes inputs and prevents comparison flaws."""
    # None and empty
    assert parse_firmware_version(None) == (0, 0, 0)
    assert parse_firmware_version("") == (0, 0, 0)
    assert parse_firmware_version([]) == (0, 0, 0)
    assert parse_firmware_version(()) == (0, 0, 0)

    # Standard dotted strings
    assert parse_firmware_version("2.1.7") == (2, 1, 7)
    assert parse_firmware_version("1.0.19") == (1, 0, 19)
    assert parse_firmware_version("3.0.0") == (3, 0, 0)

    # Shorter strings / tuples zero-padded to at least 3 parts (V, R, B)
    assert parse_firmware_version("2.1") == (2, 1, 0)
    assert parse_firmware_version("2") == (2, 0, 0)
    assert parse_firmware_version((2, 1)) == (2, 1, 0)
    assert parse_firmware_version([2, 1]) == (2, 1, 0)
    assert parse_firmware_version((2,)) == (2, 0, 0)

    # Integer inputs
    assert parse_firmware_version(2) == (2, 0, 0)

    # Lists / tuples of strings
    assert parse_firmware_version(["2", "1", "7"]) == (2, 1, 7)
    assert parse_firmware_version(("2", "1")) == (2, 1, 0)
    assert parse_firmware_version(["v2", "1"]) == (2, 1, 0)
    assert parse_firmware_version([2, None, 1]) == (2, 1, 0)

    # Longer tuples preserved
    assert parse_firmware_version("2.1.7.4") == (2, 1, 7, 4)
    assert parse_firmware_version((2, 1, 7, 4)) == (2, 1, 7, 4)

    # Prefixed strings
    assert parse_firmware_version("v1.0.19") == (1, 0, 19)
    assert parse_firmware_version("FW 2.1.7") == (2, 1, 7)

    # Non-digit string or unparseable fallback
    assert parse_firmware_version("unknown") == (0, 0, 0)
    assert parse_firmware_version(3.14) == (0, 0, 0)

    # Crucial tuple comparison bug prevention:
    assert parse_firmware_version((2, 1)) >= (2, 1, 0)
    assert parse_firmware_version("2.1") >= (2, 1, 0)
    assert parse_firmware_version("2.1") < (2, 1, 7)


def test_f452_and_f452v_profiles() -> None:
    """F452/F452V drop only WHO 25, the one subsystem Legrand documents (as NO)."""
    for model, cls in (("F452", F452Profile), ("F452V", F452VProfile)):
        profile = get_gateway_profile(model)
        assert isinstance(profile, cls)
        assert profile.model_name == model
        assert profile.max_command_sessions == 1
        # Nothing is measured: pacing copied from the MH200, auth unmeasured.
        assert profile.command_queue_delay == MH200Profile().command_queue_delay
        assert profile.auth_measured is False
        assert "Auth unmeasured" in profile.features_summary
        assert "Legacy password auth" not in profile.features_summary
        # WHO_25.pdf p. 13 / WHO_15-25.pdf p. 24: F452 and F452V NO.
        assert not profile.supports_who(WHO_CEN_PLUS)
        assert profile.supports_who(WHO_CEN)
        # Everything else is the undocumented class default, not an exclusion.
        dropped = set(DEFAULT_SUPPORTED_WHO) - set(profile.supported_who)
        assert dropped == {WHO_CEN_PLUS}
        assert profile.supports_audio is GatewayProfile("X").supports_audio


def test_f453_profile() -> None:
    """F453 keeps the class default: WHO 25 is documented YES, nothing is dropped."""
    f453 = get_gateway_profile("F453")
    assert isinstance(f453, F453Profile)
    assert f453.model_name == "F453"
    assert f453.max_command_sessions == 1
    assert f453.command_queue_delay == MH200Profile().command_queue_delay
    assert f453.supported_who == DEFAULT_SUPPORTED_WHO
    assert f453.supports_who(WHO_CEN_PLUS)
    assert f453.supports_who(WHO_ENERGY)
    # The TiF453 guide offers only an OPEN password; no handshake is captured.
    assert f453.supports_hmac is False
    assert f453.auth_measured is False
    assert "Auth unmeasured" in f453.features_summary


def test_f453av_profile_firmware_discrimination() -> None:
    """F453AV adds WHO 25 from firmware 2.1.7, the first version Legrand lists as YES."""
    note = "CEN+ documented from FW 2.1.7"

    # 1. Unknown firmware: conservative, without CEN+.
    f453av_default = get_gateway_profile("F453AV")
    assert isinstance(f453av_default, F453AVProfile)
    assert f453av_default.firmware_version is None
    assert f453av_default.supports_who(WHO_CEN) is True
    assert f453av_default.supports_who(WHO_CEN_PLUS) is False
    assert set(DEFAULT_SUPPORTED_WHO) - set(f453av_default.supported_who) == {
        WHO_CEN_PLUS
    }
    assert note in f453av_default.extra_features
    assert note in f453av_default.features_summary
    assert f453av_default.auth_measured is False
    assert f453av_default.supports_hmac is False
    assert f453av_default.command_queue_delay == MH200Profile().command_queue_delay

    # 2. 1.0.19 is documented NO; versions between 1.0.19 and 2.1.7 are not
    # documented and are treated conservatively as without CEN+.
    for old_fw in ["1.0.19", "2.1.0", (2, 1), [1, 0, 19]]:
        profile = get_gateway_profile("F453AV", firmware_version=old_fw)
        assert isinstance(profile, F453AVProfile)
        assert profile.supports_who(WHO_CEN_PLUS) is False
        assert note in profile.extra_features

    # 3. 2.1.7 is documented YES; later versions keep it.
    for new_fw in ["2.1.7", "3.0.14", (2, 1, 7), [2, 1, 7]]:
        profile = get_gateway_profile("F453AV", firmware_version=new_fw)
        assert isinstance(profile, F453AVProfile)
        assert profile.supported_who == DEFAULT_SUPPORTED_WHO
        assert note not in profile.extra_features

    # Direct F453AVProfile construction with tuple/list
    profile_list = F453AVProfile(firmware_version=[2, 1, 7])
    assert profile_list.firmware_version == "2.1.7"
    assert profile_list.supports_who(WHO_CEN_PLUS) is True

    # Empty inputs resolve to None firmware_version and conservative profile
    for empty_fw in ["", [], (), None]:
        empty_prof = F453AVProfile(firmware_version=empty_fw)
        assert empty_prof.firmware_version is None
        assert empty_prof.supports_who(WHO_CEN_PLUS) is False
        assert note in empty_prof.extra_features


def test_firmware_version_is_keyword_only() -> None:
    """Adding firmware_version must not shift positional profile construction."""
    profile = GatewayProfile("X", 4)
    assert profile.max_command_sessions == 4
    assert profile.firmware_version is None
    assert GatewayProfile("X", firmware_version="1.0").firmware_version == "1.0"


def test_catalog_aliases_resolution() -> None:
    """Item numbers resolve to the gateway that shares their MHCatalogue.db item."""
    # 573992 (Arteor F453AV): WHO_25.pdf p. 13
    f453av_cat = get_gateway_profile("573992")
    assert isinstance(f453av_cat, F453AVProfile)
    assert not f453av_cat.supports_who(WHO_CEN_PLUS)

    f453av_cat_fw = get_gateway_profile("573992", "2.1.7")
    assert isinstance(f453av_cat_fw, F453AVProfile)
    assert f453av_cat_fw.supports_who(WHO_CEN_PLUS) is True

    # Named Arteor variants
    assert isinstance(get_gateway_profile("Arteor 573992", "2.1.7"), F453AVProfile)
    assert isinstance(get_gateway_profile("Arteor F453AV"), F453AVProfile)

    # 003598 / 03598 (F454): MyHOME_Suite Version History
    assert isinstance(get_gateway_profile("003598"), F454Profile)
    assert isinstance(get_gateway_profile("03598"), F454Profile)
    assert isinstance(get_gateway_profile("0 035 98"), F454Profile)

    # 003594 / 03594 (F455): MyHOME_Suite Version History
    assert isinstance(get_gateway_profile("003594"), F455Profile)
    assert isinstance(get_gateway_profile("03594"), F455Profile)
    assert isinstance(get_gateway_profile("0 035 94"), F455Profile)

    # 03565 / 003565 (MH200N): WHO_25.pdf p. 13, MyHOME_Suite Version History
    assert isinstance(get_gateway_profile("03565"), MH200NProfile)
    assert isinstance(get_gateway_profile("003565"), MH200NProfile)

    # 003535 / 03535 (MH202): MHCatalogue.db EN_DEVICE id_item 1902 only;
    # no public page shows the pair.
    assert isinstance(get_gateway_profile("003535"), MH202Profile)
    assert isinstance(get_gateway_profile("03535"), MH202Profile)


def test_owngateway_reactive_profile_upgrade_on_firmware() -> None:
    """OWNGateway dynamically upgrades profile when firmware is updated or supplied at discovery."""
    from OWNd.connection import OWNGateway

    # Initialize without firmware: conservative F453AV
    gw = OWNGateway({"address": "192.168.1.50", "modelName": "F453AV"})
    assert gw.firmware is None
    assert gw.profile.supports_who(WHO_CEN_PLUS) is False
    assert "CEN+ documented from FW 2.1.7" in gw.profile.features_summary

    # Reactive update when firmware is learned
    gw.firmware = "2.1.7"
    assert gw.firmware == "2.1.7"
    assert gw.profile.supports_who(WHO_CEN_PLUS) is True
    assert "CEN+ documented from FW 2.1.7" not in gw.profile.features_summary

    # Downgrade / older firmware
    gw.firmware = "1.0.19"
    assert gw.profile.supports_who(WHO_CEN_PLUS) is False

    # Empty string resets firmware to None and conservative profile
    gw.firmware = ""
    assert gw.firmware is None
    assert gw.profile.supports_who(WHO_CEN_PLUS) is False

    # Initialize with firmware in discovery_info
    gw_with_fw = OWNGateway({
        "address": "192.168.1.50",
        "modelName": "F453AV",
        "modelNumber": "2.1.7",
    })
    assert gw_with_fw.firmware == "2.1.7"
    assert gw_with_fw.profile.supports_who(WHO_CEN_PLUS) is True

    # Initialize with empty string in discovery_info
    gw_empty_fw = OWNGateway({
        "address": "192.168.1.50",
        "modelName": "F453AV",
        "modelNumber": "",
    })
    assert gw_empty_fw.firmware is None
    assert gw_empty_fw.profile.supports_who(WHO_CEN_PLUS) is False


def test_owngateway_event_properties() -> None:
    """OWNGatewayEvent exposes public firmware_version and device_type properties."""
    from OWNd.message.gateway import OWNGatewayEvent

    evt_fw = OWNGatewayEvent("*#13**16*2*1*7##")
    assert evt_fw.firmware_version == "2.1.7"
    assert evt_fw.device_type is None

    evt_dev = OWNGatewayEvent("*#13**15*200##")
    assert evt_dev.device_type == "F454"
    assert evt_dev.firmware_version is None


def test_profile_no_auth_features() -> None:
    """A profile with neither HMAC nor password auth reports neither in features_summary."""
    profile = GatewayProfile(
        model_name="OpenGateway",
        supports_hmac=False,
        requires_password=False,
        supports_audio=False,
    )
    assert "Legacy password auth" not in profile.features_summary
    assert "HMAC-SHA2" not in profile.features_summary


@pytest.mark.parametrize("name", ["H4684", "h4684", "L4684", "N4684", "NT4684", "LGRH4684", "LGR4684"])
def test_h4684_profile(name: str) -> None:
    """H4684 colour touch screen and brand variants resolve to H4684Profile."""
    profile = get_gateway_profile(name)
    assert isinstance(profile, H4684Profile)
    assert profile.model_name == "H4684"



