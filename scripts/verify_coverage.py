#!/usr/bin/env python3
"""Strict Test Coverage Enforcer for OWNd.

Ensures that core modules within OWNd maintain 100.0% statement and 100.0%
branch coverage. Any module that falls below threshold, misses a statement, or
leaves a partial branch will cause CI to report detailed line numbers, branch
targets, source snippets, and GitHub Actions inline annotations.
"""
from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OWND_DIR = os.path.join(REPO_ROOT, "OWNd")
COVERAGE_XML = os.path.join(REPO_ROOT, "coverage.xml")

# Standalone interactive or CLI modules excluded from coverage enforcement
EXCLUDED_MODULES = {
    "OWNd/__main__.py",
}


def collapse_line_ranges(line_numbers: list[str]) -> str:
    """Convert a list of string line numbers into compact human-readable ranges.

    e.g. ['667', '668', '670'] -> '667-668, 670'
    """
    if not line_numbers:
        return ""
    nums = sorted(set(int(n) for n in line_numbers))
    ranges = []
    start = nums[0]
    prev = nums[0]

    for n in nums[1:]:
        if n == prev + 1:
            prev = n
        else:
            ranges.append(f"{start}-{prev}" if start != prev else f"{start}")
            start = n
            prev = n
    ranges.append(f"{start}-{prev}" if start != prev else f"{start}")
    return ", ".join(ranges)


def format_partial_branches(partial_branches: list[tuple[str, str]]) -> str:
    """Format ``(line_number, missing_branches)`` pairs into ``line->target`` labels."""
    items: list[str] = []
    for line_no, missing in partial_branches:
        if not line_no or not missing:
            continue
        for target in missing.split(","):
            target = target.strip()
            if target:
                items.append(f"{line_no}->{target}")
    return ", ".join(items)


def get_source_snippet(file_path: str, line_no: int) -> str:
    """Retrieve source code line content for context."""
    full_path = os.path.join(REPO_ROOT, file_path) if not os.path.isabs(file_path) else file_path
    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            for idx, line in enumerate(f, 1):
                if idx == line_no:
                    return line.rstrip()
    except Exception:
        pass
    return ""


def normalize_coverage_filename(fn: str) -> str:
    """Normalize filenames from coverage.xml to OWNd/... paths."""
    fn = fn.replace("\\", "/")
    if os.path.isabs(fn):
        try:
            fn = os.path.relpath(fn, REPO_ROOT).replace("\\", "/")
        except ValueError:
            pass
    if not fn.startswith("OWNd/"):
        fn = f"OWNd/{fn}"
    return fn


def verify_all_coverage(xml_path: str = COVERAGE_XML, min_threshold: float = 100.0) -> int:
    """Validate that OWNd modules satisfy statement and branch coverage requirements."""
    if not os.path.exists(xml_path):
        print(f"[ERROR] Coverage report '{xml_path}' not found. Run pytest with --cov-report=xml first.")
        return 1

    tree = ET.parse(xml_path)
    root = tree.getroot()

    coverage_data: dict[
        str, tuple[int, float, list[str], float, list[tuple[str, str]]]
    ] = {}
    for pkg in root.findall(".//package"):
        for cls in pkg.findall(".//class"):
            raw_fn = cls.attrib.get("filename", "")
            fn = normalize_coverage_filename(raw_fn)
            lines = cls.findall(".//line")
            total_stmts = len(lines)
            rate = float(cls.attrib.get("line-rate", 0)) * 100.0
            uncovered = [
                line.attrib.get("number", "")
                for line in lines
                if line.attrib.get("hits") == "0"
            ]
            raw_branch_rate = cls.attrib.get("branch-rate")
            branch_rate = (
                float(raw_branch_rate) * 100.0
                if raw_branch_rate is not None
                else 100.0
            )
            partial_branches = [
                (line.attrib.get("number", ""), line.attrib.get("missing-branches", ""))
                for line in lines
                if line.attrib.get("missing-branches")
            ]
            coverage_data[fn] = (
                total_stmts,
                rate,
                uncovered,
                branch_rate,
                partial_branches,
            )

    disk_files = []
    for root_dir, _, files in os.walk(OWND_DIR):
        for f in files:
            if f.endswith(".py"):
                full_path = os.path.join(root_dir, f)
                rel_path = os.path.relpath(full_path, REPO_ROOT).replace("\\", "/")
                if rel_path not in EXCLUDED_MODULES:
                    disk_files.append(rel_path)

    disk_files.sort()

    print(f"[CHECK] Verifying test coverage across {len(disk_files)} module(s)...")
    errors: list[
        tuple[str, int, float, list[str], float, list[tuple[str, str]], str]
    ] = []
    report_rows: list[tuple[str, int, int, str, str, str, str]] = []
    total_stmts_checked = 0
    total_uncovered_checked = 0

    for rel in disk_files:
        if rel not in coverage_data:
            errors.append(
                (
                    rel,
                    0,
                    0.0,
                    [],
                    0.0,
                    [],
                    f"[FAIL] {rel}: Missing from coverage report (untested or omitted)",
                )
            )
            report_rows.append((rel, 0, 0, "0.0%", "0.0%", "Untested / omitted", ""))
            continue

        stmts, rate, uncovered, branch_rate, partial_branches = coverage_data[rel]
        total_stmts_checked += stmts
        total_uncovered_checked += len(uncovered)

        ranges = collapse_line_ranges(uncovered)
        branch_summary = format_partial_branches(partial_branches)
        report_rows.append(
            (
                rel,
                stmts,
                len(uncovered),
                f"{rate:.1f}%",
                f"{branch_rate:.1f}%",
                ranges,
                branch_summary,
            )
        )

        if (
            rate < min_threshold
            or uncovered
            or branch_rate < min_threshold
            or partial_branches
        ):
            details: list[str] = []
            if uncovered:
                details.append(f"Missing {len(uncovered)} line(s): {ranges}")
            if partial_branches:
                details.append(
                    f"Partial {len(partial_branches)} branch(es): {branch_summary}"
                )
            elif branch_rate < min_threshold:
                details.append(f"Branch rate {branch_rate:.1f}% < {min_threshold:.1f}%")
            detail_str = "; ".join(details) if details else "Below threshold"
            errors.append(
                (
                    rel,
                    stmts,
                    rate,
                    uncovered,
                    branch_rate,
                    partial_branches,
                    f"[FAIL] {rel}: {rate:.1f}% lines, {branch_rate:.1f}% branches ({detail_str})",
                )
            )
        else:
            print(
                f"  [OK] {rel}: {rate:.1f}% lines ({stmts - len(uncovered)}/{stmts} statements), "
                f"{branch_rate:.1f}% branches"
            )

    summary_path = os.getenv("GITHUB_STEP_SUMMARY")

    if errors:
        print("\n" + "=" * 78)
        print(
            f"[CRITICAL] TEST COVERAGE ENFORCEMENT FAILED "
            f"(Threshold: {min_threshold:.1f}% statements & branches):"
        )
        print("=" * 78)
        for rel, _stmts, _rate, uncovered, _br_rate, partial_branches, msg in errors:
            print(f"\n{msg}")
            for line_str in uncovered:
                if not line_str:
                    continue
                line_no = int(line_str)
                snippet = get_source_snippet(rel, line_no)
                print(f"    Line {line_no:4d}: {snippet}")
                print(
                    f"::error file={rel},line={line_no}::"
                    f"Statement not covered by tests (line {line_no})"
                )
            for line_str, missing in partial_branches:
                if not line_str:
                    continue
                line_no = int(line_str)
                snippet = get_source_snippet(rel, line_no)
                print(f"    Line {line_no:4d} [missing branch -> {missing}]: {snippet}")
                print(
                    f"::error file={rel},line={line_no}::"
                    f"Branch not fully covered by tests (line {line_no}, missing: {missing})"
                )

        print("\n" + "=" * 78)
        print(
            f"All core modules in 'OWNd' must meet minimum {min_threshold:.1f}% "
            f"statement and branch coverage."
        )
        print("Please add automated unit tests covering the missing line(s)/branch(es) before merging.")
        print("=" * 78)

        if summary_path:
            try:
                with open(summary_path, "a", encoding="utf-8") as f:
                    f.write("\n## ❌ Test Coverage Enforcement Failed\n\n")
                    f.write(
                        f"**{len(errors)}** module(s) dropped below {min_threshold:.1f}% "
                        f"statement/branch coverage:\n\n"
                    )
                    f.write(
                        "| Component / Module | Statements | Missing | Line Coverage | "
                        "Branch Coverage | Missing Lines | Partial Branches |\n"
                    )
                    f.write("|---|:---:|:---:|:---:|:---:|---|---|\n")
                    for rel, stmts, miss_cnt, cr, br, ranges, br_summary in report_rows:
                        f.write(
                            f"| `{rel}` | {stmts} | {miss_cnt} | **{cr}** | "
                            f"**{br}** | `{ranges}` | `{br_summary}` |\n"
                        )
            except Exception:
                pass

        return 1

    covered_count = total_stmts_checked - total_uncovered_checked
    overall_pct = (covered_count / total_stmts_checked * 100) if total_stmts_checked > 0 else 0.0
    branches_valid = int(root.attrib.get("branches-valid", 0))
    branches_covered = int(root.attrib.get("branches-covered", 0))
    branch_pct = (
        (branches_covered / branches_valid * 100.0)
        if branches_valid > 0
        else float(root.attrib.get("branch-rate", 1.0)) * 100.0
    )
    print(f"\n[SUCCESS] All {len(disk_files)} OWNd module(s) passed coverage verification!")
    print(
        f"[SUCCESS] {covered_count:,} / {total_stmts_checked:,} statements ({overall_pct:.1f}%), "
        f"{branches_covered:,} / {branches_valid:,} branches ({branch_pct:.1f}%)."
    )

    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write("\n## 🎯 Test Coverage Enforced\n\n")
                f.write(f"All **{len(disk_files)}** library modules satisfied coverage requirements ")
                f.write(
                    f"(**{covered_count:,} / {total_stmts_checked:,}** statements, "
                    f"**{overall_pct:.1f}%** line rate; "
                    f"**{branches_covered:,} / {branches_valid:,}** branches, "
                    f"**{branch_pct:.1f}%** branch rate).\n\n"
                )
                f.write("| Component / Module | Statements | Missing | Line Coverage | Branch Coverage |\n")
                f.write("|---|:---:|:---:|:---:|:---:|\n")
                for rel, stmts, miss_cnt, cr, br, _, _ in report_rows:
                    f.write(f"| `{rel}` | {stmts} | {miss_cnt} | **{cr}** | **{br}** |\n")
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    coverage_file = sys.argv[1] if len(sys.argv) > 1 else COVERAGE_XML
    # Enforce strict 100.0% statement and branch coverage across all OWNd modules
    threshold = float(sys.argv[2]) if len(sys.argv) > 2 else 100.0
    sys.exit(verify_all_coverage(coverage_file, min_threshold=threshold))
