#!/usr/bin/env python3
"""Unified Documentation Synchronization & Anti-Drift Sentinel for OWNd.

Maintains live, automated synchronization between the OWNd codebase, profiles,
coverage reports, and README.md:
1. Gateway Profiles table (<!-- START_GATEWAY_PROFILES_TABLE -->)
   Cross-referenced against OWNd.profiles.canonical_profiles().
2. Supported Subsystems (WHO Catalog) table (<!-- START_WHO_CATALOG_TABLE -->)
   Dynamically inspected from OWNd.message exports and WHO registries.
3. Code Coverage table (<!-- START_COVERAGE_TABLE -->) and coverage.svg badge
   Derived from coverage.xml test execution reports.

Modes:
- python scripts/sync_documentation.py: Updates README.md and coverage.svg in place.
- python scripts/sync_documentation.py --check: Verifies README.md is in sync,
  exits 0 if in sync, or 1 with unified diff if drifted.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import difflib
import os
from pathlib import Path
import re
import sys
from typing import Any
import xml.etree.ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from OWNd.profiles import canonical_profiles  # noqa: E402

README_MD = REPO_ROOT / "README.md"
COVERAGE_XML = REPO_ROOT / "coverage.xml"
COVERAGE_SVG = REPO_ROOT / "coverage.svg"

# Sentinel block markers
GATEWAY_START_MARKER = "<!-- START_GATEWAY_PROFILES_TABLE -->"
GATEWAY_END_MARKER = "<!-- END_GATEWAY_PROFILES_TABLE -->"

WHO_START_MARKER = "<!-- START_WHO_CATALOG_TABLE -->"
WHO_END_MARKER = "<!-- END_WHO_CATALOG_TABLE -->"

COVERAGE_START_MARKER = "<!-- START_COVERAGE_TABLE -->"
COVERAGE_END_MARKER = "<!-- END_COVERAGE_TABLE -->"

COMPONENT_NOTES: dict[str, str] = {
    "OWNd/connection/__init__.py": "Hardened dual-session TCP engine & connection package exports",
    "OWNd/connection/auth.py": "Pure cryptographic routines: Open password, HMAC-SHA1/SHA256, hex/dec conversions",
    "OWNd/connection/command_session.py": "Command queue pacing, synchronized send, and request/reply tracking",
    "OWNd/connection/event_session.py": "Long-lived event bus session, keepalives, and automatic reconnection",
    "OWNd/connection/gateway.py": "Gateway configuration container, endpoint discovery, and profile mapping",
    "OWNd/connection/session.py": "Base TCP transport, negotiation state machine, and frame buffering",
    "OWNd/discovery.py": "SSDP multicast and UPnP XML gateway discovery and descriptor parsing",
    "OWNd/message/__init__.py": "OpenWebNet message package exports & WHO subsystem registries",
    "OWNd/message/alarm.py": "WHO 5: Intrusion and technical alarm subsystem events and commands",
    "OWNd/message/automation.py": "WHO 2: Automation and motorized shutter events and commands",
    "OWNd/message/base.py": "Base message, signaling, and protocol dispatcher registries",
    "OWNd/message/cen.py": "WHO 15 & WHO 25: CEN, CEN+, and dry contact control events/commands",
    "OWNd/message/energy.py": "WHO 18: Energy management, power, and diagnostic pulse events/commands",
    "OWNd/message/gateway.py": "WHO 13: Gateway management, clock/date configuration, and model telemetry",
    "OWNd/message/heating.py": "WHO 4: Thermoregulation, heating/cooling zone control, and temperature decoders",
    "OWNd/message/lighting.py": "WHO 1: Lighting controls, dimming, RGB/HSV color, and motion/PIR sensors",
    "OWNd/message/scenario.py": "WHO 0, WHO 9, WHO 17: Scenario activation, auxiliary commands, and MH200/MH202 scenes",
    "OWNd/message/sound.py": "WHO 16: Sound system and audio/video matrix routing (WHO 22 is not implemented)",
    "OWNd/profiles.py": "Declarative hardware gateway models across 14 canonical hardware profiles",
    "OWNd/transport/base.py": "Abstract transport layer and event listener notification contracts",
    "OWNd/transport/serial.py": "Async Serial/USB transport for Legrand 3578 interface with in-band demux",
    "OWNd/transport/tcp.py": "Dual-session TCP transport linking event and command channels",
    "OWNd/transport/__init__.py": "Transport subpackage exports",
    "OWNd/__init__.py": "Package initialization and version metadata",
}


@dataclass(frozen=True)
class WhoCatalogDefinition:
    who: str
    name: str
    description: str
    dispatch_who_keys: tuple[int, ...]
    explicit_classes: tuple[str, ...] = ()


WHO_DEFINITIONS: tuple[WhoCatalogDefinition, ...] = (
    WhoCatalogDefinition(
        who="**0**",
        name="Scenarios",
        description="Basic scenario execution (1–32) from control panels, scenario module programming and memory lock states",
        dispatch_who_keys=(0,),
    ),
    WhoCatalogDefinition(
        who="**1**",
        name="Lighting",
        description="On/off switching, dimming level (0–100%), DALI Tunable White (Dimension 14, 2000K–6535K / mireds), status queries",
        dispatch_who_keys=(1,),
    ),
    WhoCatalogDefinition(
        who="**2**",
        name="Automation",
        description="Shutters, blinds, motorized curtains, tilt angles, short & full replies",
        dispatch_who_keys=(2,),
    ),
    WhoCatalogDefinition(
        who="**3**",
        name="Load Control",
        description="Load shedding status, circuit priority management",
        dispatch_who_keys=(),
        explicit_classes=("OWNCommand", "OWNEvent"),
    ),
    WhoCatalogDefinition(
        who="**4**",
        name="Thermoregulation / Climate",
        description="Multi-zone temperature readouts, target adjustments, HVAC modes (Heat/Cool/Auto/Off), local offsets, fan coil speeds, valve states, Central Unit 3550/4695 master coordination",
        dispatch_who_keys=(4,),
    ),
    WhoCatalogDefinition(
        who="**5**",
        name="Burglar Alarm",
        description="Zone status, system arming / disarming states",
        dispatch_who_keys=(5,),
    ),
    WhoCatalogDefinition(
        who="**9**",
        name="Auxiliary",
        description="Auxiliary channel status (aux 1–9) for remote relays and inter-system signaling",
        dispatch_who_keys=(9,),
    ),
    WhoCatalogDefinition(
        who="**13**",
        name="Gateway Diagnostics & Clock",
        description="Gateway date/time synchronization, timezone offsets, firmware metadata",
        dispatch_who_keys=(13,),
    ),
    WhoCatalogDefinition(
        who="**15**",
        name="CEN Scenarios",
        description="Scenario control, pushbutton push/release/extended press events, strongly typed command builders",
        dispatch_who_keys=(15,),
    ),
    WhoCatalogDefinition(
        who="**16** / **22**",
        name="Sound Diffusion",
        description="Multi-source selection, zone activation, volume adjustment, F441 matrix",
        dispatch_who_keys=(16,),
        explicit_classes=("OWNAVCommand",),
    ),
    WhoCatalogDefinition(
        who="**17**",
        name="Scenario Programmer",
        description="MH200N / MH202 scenario activation and state monitoring",
        dispatch_who_keys=(17,),
    ),
    WhoCatalogDefinition(
        who="**18**",
        name="Energy Management",
        description="Active power (W), hourly/daily/monthly consumption (kWh), Stop & Go breaker diagnostics",
        dispatch_who_keys=(18,),
    ),
    WhoCatalogDefinition(
        who="**25**",
        name="CEN+ & Dry Contacts",
        description="32-button keypads, rotary knob encoders (CW/CCW), dry contacts, PIR sensors, strongly typed command builders",
        dispatch_who_keys=(25,),
        explicit_classes=(
            "OWNCenPlusCommand",
            "OWNCENPlusEvent",
            "OWNDryContactCommand",
            "OWNDryContactEvent",
        ),
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Gateway Profiles Table Builder
# ─────────────────────────────────────────────────────────────────────────────

def build_gateway_profiles_table() -> str:
    """Generate Markdown table representing canonical gateway profiles."""
    lines = [
        "| Gateway Model | Concurrency | Queue Delay | Event keepalive | Features |",
        "|:---|:---:|:---:|:---:|:---|",
    ]
    for profile in canonical_profiles():
        model_name = (
            "Generic Gateway"
            if profile.model_name in ("Generic", "Generic Gateway")
            else profile.model_name
        )
        lines.append(
            f"| **{model_name}** | {profile.concurrency_summary} | "
            f"{profile.queue_delay_summary} | {profile.keepalive_summary} | "
            f"{profile.features_summary} |"
        )
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 2. WHO Subsystems Catalog Table Builder
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_subsystem_classes(defn: WhoCatalogDefinition) -> list[str]:
    """Dynamically resolve and verify command/event classes for a subsystem."""
    import OWNd.message as message_pkg
    from OWNd.message.base import (
        _COMMAND_DISPATCH,
        _EVENT_DISPATCH,
        _ensure_all_subsystems_registered,
    )

    _ensure_all_subsystems_registered()

    discovered_commands: list[str] = []
    discovered_events: list[str] = []

    for who_key in defn.dispatch_who_keys:
        cmd_parser = _COMMAND_DISPATCH.get(who_key)
        if cmd_parser is not None and hasattr(cmd_parser, "__name__"):
            name = cmd_parser.__name__
            if not name.startswith("_") and name not in discovered_commands:
                discovered_commands.append(name)

        evt_parser = _EVENT_DISPATCH.get(who_key)
        if evt_parser is not None and hasattr(evt_parser, "__name__"):
            name = evt_parser.__name__
            if not name.startswith("_") and name not in discovered_events:
                discovered_events.append(name)

    # Combine discovered with any explicit classes (sorted Commands first, then Events)
    combined = list(discovered_commands) + list(discovered_events)
    for extra in defn.explicit_classes:
        if extra not in combined:
            combined.append(extra)

    # Validate that every class exists and is exported in OWNd.message
    for cls_name in combined:
        if not hasattr(message_pkg, cls_name):
            raise AttributeError(f"Class '{cls_name}' is not found in OWNd.message.")
        if cls_name not in message_pkg.__all__:
            raise ValueError(f"Class '{cls_name}' is not exported in OWNd.message.__all__.")

    return combined


def build_who_catalog_table() -> str:
    """Dynamically generate Markdown table of supported WHO subsystems."""
    lines = [
        "| WHO | Subsystem | Description & Capabilities | Event / Command Classes |",
        "|:---:|:---|:---|:---|",
    ]
    for defn in WHO_DEFINITIONS:
        classes = _resolve_subsystem_classes(defn)
        formatted_classes = ", ".join(f"`{cls_name}`" for cls_name in classes)
        lines.append(
            f"| {defn.who} | {defn.name} | {defn.description} | {formatted_classes} |"
        )
    return "\n".join(lines)


def verify_who_catalog_coverage() -> list[str]:
    """Verify that all WHO subsystems registered in dispatch registries are accounted for."""
    from OWNd.message.base import (
        _COMMAND_DISPATCH,
        _EVENT_DISPATCH,
        _ensure_all_subsystems_registered,
    )

    _ensure_all_subsystems_registered()
    covered_who: set[int] = set()
    for defn in WHO_DEFINITIONS:
        covered_who.update(defn.dispatch_who_keys)

    all_registered = set(_COMMAND_DISPATCH.keys()) | set(_EVENT_DISPATCH.keys())
    missing_who = [
        who for who in sorted(all_registered)
        if who not in covered_who
    ]
    violations: list[str] = []
    for who in missing_who:
        in_cmd = who in _COMMAND_DISPATCH
        in_evt = who in _EVENT_DISPATCH
        if in_cmd and in_evt:
            registry = "_COMMAND_DISPATCH and _EVENT_DISPATCH"
        elif in_cmd:
            registry = "_COMMAND_DISPATCH"
        else:
            registry = "_EVENT_DISPATCH"
        violations.append(
            f"WHO {who} registered in {registry} but not mapped in WHO_DEFINITIONS."
        )
    return violations


# ─────────────────────────────────────────────────────────────────────────────
# 3. Coverage Table Builder & SVG Generator
# ─────────────────────────────────────────────────────────────────────────────

def _safe_float(val: Any, default: float = 0.0) -> float:
    """Safely convert value to float, returning default on ValueError/TypeError."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def normalize_coverage_filename(fn: str, repo_root: Path = REPO_ROOT) -> str | None:
    """Normalize filenames from coverage.xml to OWNd/... paths, or None if outside OWNd."""
    if not fn or not fn.strip():
        return None
    fn = fn.strip().replace("\\", "/")
    if os.path.isabs(fn):
        try:
            fn = str(Path(fn).relative_to(repo_root)).replace("\\", "/")
        except ValueError:
            pass
    if fn.startswith(("tests/", "scripts/", "setup.py", ".venv/")):
        return None
    if not fn.startswith("OWNd/"):
        fn = f"OWNd/{fn}"
    if not fn.endswith(".py"):
        return None
    return fn


def build_coverage_table(coverage_xml_path: Path, repo_root: Path = REPO_ROOT) -> tuple[str, int, str]:
    """Parse coverage.xml and return (markdown_table, rounded_total_rate, hex_color)."""
    if not coverage_xml_path.is_file():
        raise FileNotFoundError(f"{coverage_xml_path} does not exist.")

    try:
        tree = ET.parse(coverage_xml_path)
    except ET.ParseError as exc:
        raise ValueError(f"Failed to parse coverage XML from {coverage_xml_path}: {exc}") from exc

    root = tree.getroot()

    file_rates: dict[str, float] = {}
    for p in root.findall(".//package"):
        for c in p.findall(".//class"):
            raw_fn = c.attrib.get("filename", "")
            fn = normalize_coverage_filename(raw_fn, repo_root)
            if fn is None or fn in ("OWNd/__main__.py",):
                continue
            cr = _safe_float(c.attrib.get("line-rate", 0)) * 100
            file_rates[fn] = cr

    total_rate = _safe_float(root.attrib.get("line-rate", 0)) * 100
    rate_round = round(total_rate)
    color = "#4c1" if rate_round >= 80 else ("#dfb317" if rate_round >= 60 else "#e05d44")

    sorted_files = sorted(file_rates.items(), key=lambda item: (-round(item[1], 1), item[0]))

    table_lines = [
        "| Component / Module | Coverage | Notes |",
        "|---|:---:|---|",
    ]
    for fn, rate in sorted_files:
        notes = COMPONENT_NOTES.get(fn, "Core OWNd library component")
        rate_str = f"**{round(rate)}%**" if round(rate) >= 90 else f"{round(rate)}%"
        table_lines.append(f"| [`{fn}`]({fn}) | {rate_str} | {notes} |")

    return "\n".join(table_lines), rate_round, color


def generate_coverage_svg(rate_round: int, color: str | None = None) -> str:
    """Generate SVG badge string for test coverage percentage."""
    if color is None:
        color = "#4c1" if rate_round >= 80 else ("#dfb317" if rate_round >= 60 else "#e05d44")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="98" height="20">'
        f'<linearGradient id="b" x2="0" y2="100%">'
        f'<stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
        f'<stop offset="1" stop-opacity=".1"/>'
        f'</linearGradient>'
        f'<mask id="a"><rect width="98" height="20" rx="3" fill="#fff"/></mask>'
        f'<g mask="url(#a)">'
        f'<path fill="#555" d="M0 0h61v20H0z"/>'
        f'<path fill="{color}" d="M61 0h37v20H61z"/>'
        f'<path fill="url(#b)" d="M0 0h98v20H0z"/>'
        f'</g>'
        f'<g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">'
        f'<text x="30.5" y="15" fill="#010101" fill-opacity=".3">coverage</text>'
        f'<text x="30.5" y="14">coverage</text>'
        f'<text x="79.5" y="15" fill="#010101" fill-opacity=".3">{rate_round}%</text>'
        f'<text x="79.5" y="14">{rate_round}%</text>'
        f'</g>'
        f'</svg>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Marker Block Replacement & Synchronization Routine
# ─────────────────────────────────────────────────────────────────────────────

def _replace_marker_block(
    content: str,
    start_marker: str,
    end_marker: str,
    new_inner_content: str,
    pad_newlines: bool = False,
) -> tuple[str, bool]:
    """Replace content between start_marker and end_marker."""
    if start_marker not in content or end_marker not in content:
        raise ValueError(f"Marker pair '{start_marker}' ... '{end_marker}' not found in content.")

    pattern = re.compile(
        rf"{re.escape(start_marker)}.*?{re.escape(end_marker)}",
        re.DOTALL,
    )
    match = pattern.search(content)
    if not match:
        raise ValueError(f"Could not parse content between '{start_marker}' and '{end_marker}'.")

    sep = "\n\n" if pad_newlines else "\n"
    replacement = f"{start_marker}{sep}{new_inner_content}{sep}{end_marker}"
    if match.group(0) == replacement:
        return content, False

    updated_content = pattern.sub(replacement, content, count=1)
    return updated_content, True


def sync_documentation(
    readme_path: Path = README_MD,
    coverage_xml_path: Path | None = COVERAGE_XML,
    coverage_svg_path: Path | None = COVERAGE_SVG,
    check_only: bool = False,
) -> tuple[bool, str, list[str]]:
    """Verify or synchronize documentation tables in README.md.

    Returns (is_in_sync, unified_diff_str, list_of_messages).
    """
    messages: list[str] = []
    if not readme_path.is_file():
        raise FileNotFoundError(f"{readme_path} not found.")

    raw_bytes = readme_path.read_bytes()
    has_crlf = b"\r" in raw_bytes
    original_content = raw_bytes.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    working_content = original_content

    # 1. Gateway Profiles Table
    gw_table = build_gateway_profiles_table()
    working_content, gw_changed = _replace_marker_block(
        working_content,
        GATEWAY_START_MARKER,
        GATEWAY_END_MARKER,
        gw_table,
        pad_newlines=False,
    )
    if gw_changed:
        messages.append("Gateway Profiles table drifted from canonical profiles.")
    else:
        messages.append("Gateway Profiles table is in sync.")

    # 2. WHO Subsystems Catalog Table & Coverage Check
    coverage_violations = verify_who_catalog_coverage()
    if coverage_violations:
        for violation in coverage_violations:
            messages.append(f"WHO catalog gap: {violation}")
    else:
        messages.append("WHO catalog dispatch coverage is complete.")

    who_table = build_who_catalog_table()
    working_content, who_changed = _replace_marker_block(
        working_content,
        WHO_START_MARKER,
        WHO_END_MARKER,
        who_table,
        pad_newlines=False,
    )
    if who_changed:
        messages.append("WHO Subsystem Catalog table drifted from OWNd.message exports/registries.")
    else:
        messages.append("WHO Subsystem Catalog table is in sync.")

    # 3. Coverage Table & SVG (when coverage.xml is present)
    svg_drifted = False
    if coverage_xml_path and coverage_xml_path.is_file():
        cov_table, rate_round, color = build_coverage_table(
            coverage_xml_path, repo_root=readme_path.parent
        )
        working_content, cov_changed = _replace_marker_block(
            working_content,
            COVERAGE_START_MARKER,
            COVERAGE_END_MARKER,
            cov_table,
            pad_newlines=True,
        )
        if cov_changed:
            messages.append(f"Coverage table drifted from {coverage_xml_path.name} ({rate_round}%).")
        else:
            messages.append(f"Coverage table is in sync ({rate_round}%).")

        if coverage_svg_path:
            expected_svg = generate_coverage_svg(rate_round, color)
            if coverage_svg_path.is_file():
                current_svg = coverage_svg_path.read_text(encoding="utf-8")
                if current_svg.strip() != expected_svg.strip():
                    svg_drifted = True
            else:
                svg_drifted = True

            if svg_drifted:
                messages.append(f"{coverage_svg_path.name} drifted from {coverage_xml_path.name} ({rate_round}%).")
                if not check_only:
                    if coverage_violations:
                        messages.append(
                            f"Refused to update {coverage_svg_path.name} while WHO catalog coverage gaps exist."
                        )
                    else:
                        coverage_svg_path.write_text(expected_svg, encoding="utf-8", newline="\n")
                        messages.append(f"Updated {coverage_svg_path.name} to {rate_round}%.")
            else:
                messages.append(f"{coverage_svg_path.name} is in sync ({rate_round}%).")
    else:
        # Check marker presence without altering existing coverage block
        if COVERAGE_START_MARKER not in working_content or COVERAGE_END_MARKER not in working_content:
            raise ValueError(f"Coverage markers '{COVERAGE_START_MARKER}' not found in {readme_path.name}.")
        messages.append("Coverage table check skipped (coverage.xml not present).")

    if has_crlf:
        if check_only:
            messages.append(f"{readme_path.name} contains CRLF line endings (repository requires LF only).")
        else:
            messages.append(f"Normalized line endings to LF in {readme_path.name}.")

    content_changed = working_content != original_content
    is_in_sync = (
        (not content_changed)
        and (not has_crlf)
        and (not svg_drifted)
        and (not coverage_violations)
    )

    diff_str = ""
    if content_changed:
        diff_lines = list(
            difflib.unified_diff(
                original_content.splitlines(keepends=True),
                working_content.splitlines(keepends=True),
                fromfile=f"a/{readme_path.name}",
                tofile=f"b/{readme_path.name}",
            )
        )
        diff_str = "".join(diff_lines)

    if not check_only and (content_changed or has_crlf):
        if coverage_violations:
            messages.append(
                f"Refused to update {readme_path.name} while WHO catalog coverage gaps exist."
            )
        else:
            readme_path.write_text(working_content, encoding="utf-8", newline="\n")
            messages.append(f"Updated {readme_path.name} in place.")

    return is_in_sync, diff_str, messages


# ─────────────────────────────────────────────────────────────────────────────
# 5. CLI Entrypoint
# ─────────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Unified sentinel & synchronizer for OWNd documentation."
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--check",
        action="store_true",
        help="Check documentation synchronization without modifying files (exits 1 with diff on drift).",
    )
    mode_group.add_argument(
        "--update",
        action="store_true",
        help="Synchronize documentation tables in place (default behavior when --check is omitted).",
    )
    parser.add_argument(
        "--readme",
        type=Path,
        default=README_MD,
        help=f"Path to README.md (default: {README_MD})",
    )
    parser.add_argument(
        "--coverage-xml",
        type=Path,
        default=COVERAGE_XML,
        help=f"Path to coverage.xml (default: {COVERAGE_XML})",
    )
    parser.add_argument(
        "--coverage-svg",
        type=Path,
        default=COVERAGE_SVG,
        help=f"Path to coverage.svg (default: {COVERAGE_SVG})",
    )

    args = parser.parse_args(argv)

    # Determine coverage_xml_path:
    # If default COVERAGE_XML is used, skip gracefully when absent.
    # If the user explicitly provided a path, it must exist.
    coverage_xml_path: Path | None = None
    if args.coverage_xml:
        if args.coverage_xml == COVERAGE_XML:
            if COVERAGE_XML.is_file():
                coverage_xml_path = COVERAGE_XML
        else:
            if not args.coverage_xml.is_file():
                print(f"Error: Coverage XML file not found: {args.coverage_xml}", file=sys.stderr)
                return 1
            coverage_xml_path = args.coverage_xml

    try:
        in_sync, diff, messages = sync_documentation(
            readme_path=args.readme,
            coverage_xml_path=coverage_xml_path,
            coverage_svg_path=args.coverage_svg,
            check_only=args.check,
        )
    except Exception as exc:
        print(f"Error during documentation synchronization: {exc}", file=sys.stderr)
        return 1

    for msg in messages:
        print(f"- {msg}")

    has_catalog_gaps = any(msg.startswith("WHO catalog gap:") for msg in messages)

    if args.check:
        if not in_sync:
            print("\nError: Documentation is out of date!", file=sys.stderr)
            if diff:
                print(diff, file=sys.stderr)
            if has_catalog_gaps:
                print(
                    f"\nRun 'python scripts/sync_documentation.py' after defining missing WHO subsystems in WHO_DEFINITIONS.",
                    file=sys.stderr,
                )
            else:
                print(
                    f"\nRun 'python scripts/sync_documentation.py' to synchronize {args.readme.name}.",
                    file=sys.stderr,
                )
            return 1
        print(f"\nDocumentation in {args.readme.name} is fully synchronized.")
        return 0

    if in_sync:
        print(f"\nDocumentation in {args.readme.name} is already up to date.")
        return 0

    if has_catalog_gaps:
        print(
            "\nError: Incomplete documentation synchronization — unmapped WHO subsystems in WHO_DEFINITIONS.",
            file=sys.stderr,
        )
        return 1

    print(f"\nSuccessfully synchronized documentation in {args.readme.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
