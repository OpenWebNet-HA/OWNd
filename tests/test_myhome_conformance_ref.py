"""The MyHOME ref the "MyHOME conformance" workflow tests against (scripts/myhome_conformance_ref.py)."""
from __future__ import annotations

import io
import json
from pathlib import Path
import urllib.error

import pytest
import yaml

from scripts import myhome_conformance_ref as mod
from scripts.myhome_conformance_ref import RefError, Resolution, read_ref_file, resolve

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "myhome-conformance.yml"


def api(answers: dict[str, object]):
    """A stand-in for the GitHub API: path -> answer; a path that is not listed must not be asked."""
    asked: list[str] = []

    def fetch(path: str) -> object:
        asked.append(path)
        return answers[path]

    fetch.asked = asked  # type: ignore[attr-defined]
    return fetch


def pull(state: str, *, merged: bool = False, base: str = "master", sha: str = "0123456789abcdef") -> dict[str, object]:
    return {"state": state, "merged": merged, "base": {"ref": base}, "head": {"sha": sha}}


# --- the file ---------------------------------------------------------------------------------


def test_ref_file_holds_one_value_besides_comments(tmp_path):
    path = tmp_path / "myhome-conformance-ref"
    path.write_text("# what this is\n\n  pull/12   # the companion\n", encoding="utf-8")
    assert read_ref_file(path) == "pull/12"


@pytest.mark.parametrize("text", ["# only a comment\n", "master\npull/3\n"])
def test_ref_file_with_no_value_or_two_is_refused(tmp_path, text):
    path = tmp_path / "myhome-conformance-ref"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(RefError, match="exactly one ref"):
        read_ref_file(path)


def test_missing_ref_file_is_refused(tmp_path):
    with pytest.raises(RefError, match="cannot be read"):
        read_ref_file(tmp_path / "absent")


def test_committed_ref_file_is_the_default_or_a_companion_pull_request():
    value = read_ref_file(mod.REF_FILE)
    assert value == mod.DEFAULT_REF or mod._PULL.fullmatch(value), value


# --- plain refs -------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["master", "chore/release-2.0.1", "v2.0.1", "a7f0bf20", "refs/pull/7/head"])
def test_a_branch_tag_or_commit_is_used_as_it_is(value):
    fetch = api({})
    assert resolve(f" {value}\n", fetch).ref == value
    assert fetch.asked == []


@pytest.mark.parametrize(
    "value", ["", "a b", "a..b", "-x", "x/", "x.lock", "x.", "$(id)", "a;b", "pull/0", "pull/x", "pull/12/head", "a" * 201]
)
def test_anything_else_is_refused_before_github_is_asked(value):
    fetch = api({})
    with pytest.raises(RefError):
        resolve(value, fetch)
    assert fetch.asked == []


# --- a companion pull request through its life ------------------------------------------------


def test_open_pull_request_is_tested_at_its_head():
    result = resolve("pull/12", api({"pulls/12": pull("open")}))
    assert result == Resolution("refs/pull/12/head", "companion MyHOME pull request 12 (open, head 01234567)")


def test_merged_pull_request_falls_back_to_the_branch_it_went_into_with_a_warning():
    fetch = api({"pulls/12": pull("closed", merged=True, base="chore/release-2.0.1"), "branches/chore/release-2.0.1": {}})
    result = resolve("pull/12", fetch)
    assert result.ref == "chore/release-2.0.1"
    assert result.warning == "MyHOME pull request 12 is merged: set .github/myhome-conformance-ref back to master."
    assert fetch.asked == ["pulls/12", "branches/chore/release-2.0.1"]


def test_merged_pull_request_whose_branch_is_gone_falls_back_to_the_default():
    fetch = api({"pulls/12": pull("closed", merged=True, base="chore/release-2.0.1"), "branches/chore/release-2.0.1": None})
    result = resolve("pull/12", fetch)
    assert result.ref == "master" and result.warning is not None


def test_merged_into_the_default_branch_asks_nothing_more():
    fetch = api({"pulls/12": pull("closed", merged=True)})
    assert resolve("pull/12", fetch).ref == "master"
    assert fetch.asked == ["pulls/12"]


def test_pull_request_closed_without_merging_is_an_error():
    with pytest.raises(RefError, match="closed without merging"):
        resolve("pull/12", api({"pulls/12": pull("closed")}))


@pytest.mark.parametrize("answer", [None, [], {"message": "Not Found"}])
def test_unknown_pull_request_is_an_error(answer):
    with pytest.raises(RefError, match="no pull request 12"):
        resolve("pull/12", api({"pulls/12": answer}))


def test_base_branch_name_from_github_is_validated_too():
    with pytest.raises(RefError):
        resolve("pull/12", api({"pulls/12": pull("closed", merged=True, base="x y")}))


# --- the command ------------------------------------------------------------------------------


def run(monkeypatch, tmp_path, *, file_text="master\n", argv=(), answers=None):
    ref_file = tmp_path / "ref"
    ref_file.write_text(file_text, encoding="utf-8")
    output = tmp_path / "out"
    output.unlink(missing_ok=True)
    monkeypatch.delenv("MYHOME_REF_INPUT", raising=False)
    monkeypatch.setattr(mod, "github_fetch", lambda repo, token: api(answers or {}))
    code = mod.main(["--ref-file", str(ref_file), "--github-output", str(output), *argv])
    return code, output.read_text(encoding="utf-8") if output.exists() else ""


def test_command_writes_the_ref_of_the_file(monkeypatch, tmp_path, capsys):
    assert run(monkeypatch, tmp_path) == (0, "ref=master\n")
    assert "::notice title=MyHOME conformance ref::testing against MyHOME ref master" in capsys.readouterr().out


def test_a_ref_given_by_hand_wins_over_the_file(monkeypatch, tmp_path):
    assert run(monkeypatch, tmp_path, file_text="pull/12\n", argv=["--input", "v2.0.1"]) == (0, "ref=v2.0.1\n")


def test_command_warns_after_the_merge_and_fails_on_a_closed_pull_request(monkeypatch, tmp_path, capsys):
    code, out = run(monkeypatch, tmp_path, file_text="pull/12\n", answers={"pulls/12": pull("closed", merged=True)})
    assert (code, out) == (0, "ref=master\n")
    assert "::warning title=MyHOME conformance ref::MyHOME pull request 12 is merged" in capsys.readouterr().out
    code, out = run(monkeypatch, tmp_path, file_text="pull/12\n", answers={"pulls/12": pull("closed")})
    assert (code, out) == (1, "")
    assert "::error title=MyHOME conformance ref::" in capsys.readouterr().out


def test_command_without_an_output_file_prints_the_ref(monkeypatch, tmp_path, capsys):
    ref_file = tmp_path / "ref"
    ref_file.write_text("master\n", encoding="utf-8")
    monkeypatch.delenv("MYHOME_REF_INPUT", raising=False)
    assert mod.main(["--ref-file", str(ref_file)]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "master"


# --- the GitHub reader ------------------------------------------------------------------------


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://api.github.com/x", code, "x", {}, None)  # type: ignore[arg-type]


def test_reader_asks_the_repository_with_the_token(monkeypatch):
    seen = []

    def urlopen(request, timeout):
        seen.append((request.full_url, request.get_header("Authorization"), timeout))
        return Reply(json.dumps({"state": "open"}).encode())

    monkeypatch.setattr(mod.urllib.request, "urlopen", urlopen)
    assert mod.github_fetch("o/r", "tok")("pulls/3") == {"state": "open"}
    assert seen == [("https://api.github.com/repos/o/r/pulls/3", "Bearer tok", 30)]


@pytest.mark.parametrize("code", [401, 403])
def test_reader_asks_again_without_a_token_that_is_refused(monkeypatch, code):
    auths = []

    def urlopen(request, timeout):
        auths.append(request.get_header("Authorization"))
        if len(auths) == 1:
            raise http_error(code)
        return Reply(b"{}")

    monkeypatch.setattr(mod.urllib.request, "urlopen", urlopen)
    assert mod.github_fetch("o/r", "tok")("pulls/3") == {}
    assert auths == ["Bearer tok", None]


def test_reader_returns_none_for_404_and_fails_on_other_answers(monkeypatch):
    codes = iter([404, 500, 403])

    def urlopen(request, timeout):
        raise http_error(next(codes))

    monkeypatch.setattr(mod.urllib.request, "urlopen", urlopen)
    fetch = mod.github_fetch("o/r", None)
    assert fetch("branches/x") is None
    with pytest.raises(RefError, match="HTTP 500"):
        fetch("pulls/3")
    with pytest.raises(RefError, match="HTTP 403"):
        fetch("pulls/3")


def test_reader_fails_when_github_cannot_be_reached(monkeypatch):
    def urlopen(request, timeout):
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(mod.urllib.request, "urlopen", urlopen)
    with pytest.raises(RefError, match="could not be asked"):
        mod.github_fetch("o/r", None)("pulls/3")


# --- the workflow -----------------------------------------------------------------------------


def test_workflow_checks_out_the_resolved_ref_in_both_jobs():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert "v2-phase1-architecture" not in WORKFLOW.read_text(encoding="utf-8")
    assert set(workflow["jobs"]) == {"corpus", "suite"}
    for job in workflow["jobs"].values():
        steps = job["steps"]
        resolver = next(i for i, step in enumerate(steps) if step.get("id") == "myhome")
        assert steps[resolver]["run"] == 'python3 scripts/myhome_conformance_ref.py --github-output "$GITHUB_OUTPUT"'
        assert steps[resolver]["working-directory"] == "OWNd"
        # The ref never reaches a shell: it is read from the file and handed to the checkout action.
        checkout = steps[resolver + 1]
        assert checkout["with"] == {
            "repository": "OpenWebNet-HA/MyHOME",
            "ref": "${{ steps.myhome.outputs.ref }}",
            "path": "MyHOME",
        }
        assert steps[resolver - 1]["with"] == {"path": "OWNd"}
