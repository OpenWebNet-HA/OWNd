#!/usr/bin/env python3
"""Extract WHO 4 firmware facts from the own-firmware-oracle verdict index.

The oracle (OpenWebNet-HA/own-firmware-oracle) replays OpenWebNet frames on the
emulated firmware of up to ten BTicino/Legrand gateways and records the serial
lines each one sends to its SCS bus interface. An ACKed WHO 4 command becomes
one line in one of two dialects:

  $06 D1 <addr> 03 02 <class> <b1> <b2> <b3>   (all gateways)
  $04 <class> <zone> 30 <value>                (plain-zone frames on some)

This script keeps, per WHO 4 frame, every telegram that at least two gateways
agree on (the gateway ACKed and sent exactly that one line), and records the
rest as dissent. tests/test_firmware_contract.py checks OWNd's decoding of each
frame against those bytes.

Usage:
  python scripts/oracle_who4_facts.py --ref <oracle commit> [--index PATH]
                                      [-o tests/oracle/who4_facts.json]

Without --index the index of --ref is downloaded from GitHub. Standard library
only; the output is sorted and stable, so a changed fixture means changed
firmware facts.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

ORACLE_REPO = "OpenWebNet-HA/own-firmware-oracle"
RAW_INDEX = "https://raw.githubusercontent.com/{repo}/{ref}/results/mcp_index.json"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "tests" / "oracle" / "who4_facts.json"
REF = re.compile(r"^[0-9a-f]{40}$")
LONG = re.compile(r"^\$06D1([0-9A-F]{2})0302([0-9A-F]{2})([0-9A-F]{2})([0-9A-F]{2})([0-9A-F]{2})$")
SHORT = re.compile(r"^\$04([0-9A-F]{2})([0-9A-F]{2})30([0-9A-F]{2})$")


def load_index(index: str | None, ref: str) -> dict[str, Any]:
    if index:
        return json.loads(Path(index).read_text(encoding="utf-8"))
    url = RAW_INDEX.format(repo=ORACLE_REPO, ref=ref)
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 - fixed https host
        return json.loads(resp.read().decode("utf-8"))


def telegram(bus_frame: str) -> tuple[str, ...] | None:
    """The fields of one recorded bus line, or None if it is not a WHO 4 telegram.

    Long:  ("06", addr, class, b1, b2, b3)
    Short: ("04", class, zone, value)
    """
    try:
        line = bytes.fromhex(bus_frame.replace(" ", "")).decode("ascii").strip()
    except (ValueError, UnicodeDecodeError):
        return None
    if m := LONG.match(line):
        return ("06", *m.groups())
    if m := SHORT.match(line):
        return ("04", *m.groups())
    return None


def extract(index: dict[str, Any]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for frame, entries in sorted(index["verdicts"].items()):
        if not frame.startswith(("*4*", "*#4*")):
            continue
        seen: dict[tuple[str, ...], set[str]] = defaultdict(set)
        for e in entries:
            if e.get("direction") != "down" or e.get("reply") != "ack":
                continue
            frames = e.get("bus_frames", [])
            t = telegram(frames[0]) if len(frames) == 1 else None
            if t is not None:
                seen[t].add(f"{e['product']} {e['version']}")
        agreed = sorted(t for t, gws in seen.items() if len(gws) >= 2)
        dissent = {" ".join(t): sorted(gws) for t, gws in sorted(seen.items()) if len(gws) < 2}
        for t in agreed:
            facts.append(
                {
                    "frame": frame,
                    "telegram": list(t),
                    "gateways": sorted(seen[t]),
                    "dissent": dissent,
                }
            )
    return facts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ref", required=True, help="oracle commit (40 hex digits)")
    ap.add_argument("--index", help="local mcp_index.json of that commit")
    ap.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    if not REF.match(args.ref):
        ap.error("--ref must be a full 40-digit commit")
    index = load_index(args.index, args.ref)
    doc = {
        "source": {
            "repo": ORACLE_REPO,
            "ref": args.ref,
            "verdicts_sha256": index.get("verdicts_sha256"),
            "generator": "scripts/oracle_who4_facts.py",
        },
        "facts": extract(index),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(doc['facts'])} WHO 4 facts -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
