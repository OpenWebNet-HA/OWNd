#!/usr/bin/env python3
"""Update README.md hardware gateway profiles table from OWNd.profiles.

Maintains live, automated documentation of gateway capabilities, pacing,
and hardware constraints.
Called locally, by git hooks, and by CI / test verification.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

# Ensure OWNd package can be imported from parent directory
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from OWNd.profiles import canonical_profiles  # noqa: E402

README_MD = REPO_ROOT / "README.md"
START_MARKER = "<!-- START_GATEWAY_PROFILES_TABLE -->"
END_MARKER = "<!-- END_GATEWAY_PROFILES_TABLE -->"


def build_profiles_table() -> str:
    """Generate Markdown table representing canonical gateway profiles."""
    lines = [
        "| Gateway Model | Concurrency | Queue Delay | Keepalive | Features |",
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


def sync_readme_profiles(check_only: bool = False) -> bool:
    """Check or update the gateway profiles table in README.md."""
    if not README_MD.is_file():
        print(f"Error: {README_MD} not found.", file=sys.stderr)
        return False

    content = README_MD.read_text(encoding="utf-8").replace("\r\n", "\n")
    table_block = build_profiles_table()

    if START_MARKER not in content or END_MARKER not in content:
        print(
            f"Error: Markers '{START_MARKER}' or '{END_MARKER}' not found in {README_MD}.",
            file=sys.stderr,
        )
        return False

    pattern = re.compile(
        rf"{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}",
        re.DOTALL,
    )
    replacement = f"{START_MARKER}\n{table_block}\n{END_MARKER}"

    current_match = pattern.search(content)
    if not current_match:
        return False

    is_in_sync = current_match.group(0) == replacement

    if check_only:
        return is_in_sync

    if not is_in_sync:
        updated_content = pattern.sub(replacement, content).replace("\r\n", "\n")
        with README_MD.open("w", encoding="utf-8", newline="\n") as f:
            f.write(updated_content)
        print(f"Updated gateway profiles table in {README_MD} ({len(canonical_profiles())} models).")
    else:
        print(f"Gateway profiles table in {README_MD} is already up-to-date.")

    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check whether README.md is in sync without modifying it (exit 1 if out-of-sync).",
    )
    args = parser.parse_args()

    if args.check:
        in_sync = sync_readme_profiles(check_only=True)
        if not in_sync:
            print(
                "Error: README.md gateway profiles table is out of date with OWNd.profiles.\n"
                "Run 'python scripts/update_readme_profiles.py' to update it.",
                file=sys.stderr,
            )
            return 1
        print("Gateway profiles table in README.md is in sync.")
        return 0

    success = sync_readme_profiles(check_only=False)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
