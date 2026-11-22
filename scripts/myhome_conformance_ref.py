#!/usr/bin/env python3
"""Resolve the MyHOME ref the "MyHOME conformance" workflow tests this checkout against.

The ref comes from ``.github/myhome-conformance-ref`` (one value; ``#`` starts a comment), or from the
workflow's manual ``myhome_ref`` input when one is given. A value is either

* a branch, tag or commit of MyHOME (``master`` is the default), used as it is; or
* ``pull/<N>``: the companion MyHOME pull request of an intentional change to what MyHOME pins from
  OWNd (a gateway profile's WHO list, a capability flag). MyHOME's committed discovery table, generated
  documents and tests describe the released OWNd, so such a change cannot pass against them; the
  companion pull request carries their update and lands with the OWNd release and the pin bump.

A companion pull request is followed through its life, so the file does not have to be edited at the
moment it is merged:

* open: its head (``refs/pull/<N>/head``);
* merged: the branch it was merged into, or the default branch when that one is gone, with a warning
  that asks for the file to be set back (once that branch is merged itself, when it is not the default
  branch: until then the change is only there);
* closed without merging: an error, because the change it carried is not coming.

Usage (in the workflow):  python3 scripts/myhome_conformance_ref.py --github-output "$GITHUB_OUTPUT"
"""
from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
import urllib.error
import urllib.request

ROOT_DIR = Path(__file__).resolve().parent.parent
REF_FILE = ROOT_DIR / ".github" / "myhome-conformance-ref"
MYHOME_REPO = "OpenWebNet-HA/MyHOME"
DEFAULT_REF = "master"

_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")
_PULL = re.compile(r"pull/([1-9][0-9]{0,8})")

# (path below https://api.github.com/repos/<repo>/) -> decoded JSON, or None for HTTP 404.
Fetch = Callable[[str], Any]


class RefError(Exception):
    """The configured ref cannot be used; the message says what to change."""


@dataclass(frozen=True)
class Resolution:
    """What to check out, and what to tell the reader of the run."""

    ref: str
    note: str
    warning: str | None = None


def read_ref_file(path: Path) -> str:
    """Return the one value of the ref file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as err:
        raise RefError(f"{path.name} cannot be read: {err}") from err
    values = [line.split("#", 1)[0].strip() for line in text.splitlines()]
    values = [value for value in values if value]
    if len(values) != 1:
        raise RefError(f"{path.name} must hold exactly one ref, found {len(values)}")
    return values[0]


def validate(value: str) -> str:
    """Return ``value`` when it is a plain ref name, raise otherwise."""
    if not _REF.fullmatch(value) or ".." in value or value.endswith(("/", ".", ".lock")):
        raise RefError(f"{value!r} is not a MyHOME branch, tag, commit or pull/<N>")
    return value


def resolve(value: str, fetch: Fetch, *, default: str = DEFAULT_REF) -> Resolution:
    """Turn the configured value into the ref to check out."""
    value = validate(value.strip())
    pull = _PULL.fullmatch(value)
    if pull is None:
        if value.startswith("pull/"):
            raise RefError(f"{value!r} is not pull/<N> with the number of a MyHOME pull request")
        return Resolution(value, f"MyHOME ref {value}")

    number = pull.group(1)
    data = fetch(f"pulls/{number}")
    if not isinstance(data, dict) or "state" not in data:
        raise RefError(f"MyHOME has no pull request {number}")
    if data.get("state") == "open":
        head = str((data.get("head") or {}).get("sha") or "")[:8]
        return Resolution(
            f"refs/pull/{number}/head",
            f"companion MyHOME pull request {number} (open, head {head or 'unknown'})",
        )
    if not data.get("merged"):
        raise RefError(
            f"MyHOME pull request {number} was closed without merging: the companion change is not "
            f"coming. Point .github/myhome-conformance-ref at its replacement, or back at {default}."
        )
    base = validate(str((data.get("base") or {}).get("ref") or default))
    if base != default and fetch(f"branches/{base}") is None:
        base = default
    if base == default:
        warning = f"MyHOME pull request {number} is merged: set .github/myhome-conformance-ref back to {default}."
    else:
        # The change is in ``base`` and not in the default branch yet: going back now would lose it.
        warning = (
            f"MyHOME pull request {number} is merged into {base}: set .github/myhome-conformance-ref "
            f"back to {default} once {base} is merged."
        )
    return Resolution(base, f"MyHOME {base} (companion pull request {number} is merged)", warning)


def github_fetch(repo: str, token: str | None) -> Fetch:
    """Return a reader of the GitHub REST API for ``repo``."""

    def get(path: str, auth: str | None) -> Any:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "OWNd-myhome-conformance"}
        if auth:
            headers["Authorization"] = f"Bearer {auth}"
        request = urllib.request.Request(f"https://api.github.com/repos/{repo}/{path}", headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def fetch(path: str) -> Any:
        try:
            try:
                return get(path, token)
            except urllib.error.HTTPError as err:
                # A workflow token is scoped to its own repository: ask again without it.
                if token and err.code in (401, 403):
                    return get(path, None)
                raise
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return None
            raise RefError(f"GitHub answered HTTP {err.code} for {repo}/{path}") from err
        except (urllib.error.URLError, TimeoutError, ValueError) as err:
            raise RefError(f"GitHub could not be asked about {repo}/{path}: {err}") from err

    return fetch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--ref-file", type=Path, default=REF_FILE)
    parser.add_argument("--repo", default=MYHOME_REPO)
    parser.add_argument(
        "--input",
        default=os.environ.get("MYHOME_REF_INPUT", ""),
        help="a ref given by hand (the workflow's myhome_ref input); wins over the file",
    )
    parser.add_argument("--github-output", type=Path, help="file to append `ref=<ref>` to")
    args = parser.parse_args(argv)

    try:
        value = args.input.strip() or read_ref_file(args.ref_file)
        result = resolve(value, github_fetch(args.repo, os.environ.get("GITHUB_TOKEN") or None))
    except RefError as err:
        print(f"::error title=MyHOME conformance ref::{err}")
        return 1

    print(f"::notice title=MyHOME conformance ref::testing against {result.note}")
    if result.warning:
        print(f"::warning title=MyHOME conformance ref::{result.warning}")
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(f"ref={result.ref}\n")
    else:
        print(result.ref)
    return 0


if __name__ == "__main__":
    sys.exit(main())
