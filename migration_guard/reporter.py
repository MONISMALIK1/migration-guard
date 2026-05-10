"""Reporter — terminal output + JSON + GitHub Actions annotations."""

import json
import os
import sys
from datetime import datetime
from typing import Optional
from .rules import Severity
from .scorer import MigrationScore


# ANSI colors
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
GRAY   = "\033[90m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

_NO_COLOR = not sys.stdout.isatty() or os.environ.get("NO_COLOR")


def _c(code: str, text: str) -> str:
    return text if _NO_COLOR else f"{code}{text}{RESET}"


def _ok(s):     return _c(GREEN, s)
def _err(s):    return _c(RED, s)
def _warn(s):   return _c(YELLOW, s)
def _gray(s):   return _c(GRAY, s)
def _bold(s):   return _c(BOLD, s)
def _blue(s):   return _c(BLUE, s)


SEVERITY_COLOR = {
    Severity.CRITICAL: RED + BOLD,
    Severity.HIGH:     RED,
    Severity.MEDIUM:   YELLOW,
    Severity.LOW:      BLUE,
}

SEVERITY_ICON = {
    Severity.CRITICAL: "✗",
    Severity.HIGH:     "✗",
    Severity.MEDIUM:   "⚠",
    Severity.LOW:      "ℹ",
}


def _sev(severity: Severity, text: str) -> str:
    return _c(SEVERITY_COLOR[severity], text)


def print_score(score: MigrationScore, verbose: bool = False) -> None:
    line = "─" * 60

    print()
    print(_bold("migration-guard — Risk Report"))
    print(_gray(f"File    : {score.filename}"))
    print(_gray(f"Format  : {score.path.rsplit('.', 1)[-1].upper()}"))
    print(_gray(line))
    print()

    if score.passed:
        bar = _ok(score.risk_bar)
        level = _ok("CLEAN")
    else:
        bar = _sev(score.overall, score.risk_bar)
        level = _sev(score.overall, str(score.overall))

    print(f"  Risk Level: {bar} {_bold(level)}")
    print()

    if score.passed:
        print(f"  {_ok('✓')}  {_bold('No issues found. Safe to run.')}")
        print()
        return

    # Print violations grouped by severity
    for sev in [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]:
        group = [v for v in score.violations if v.severity == sev]
        if not group:
            continue
        for v in group:
            icon = SEVERITY_ICON[sev]
            print(f"  {_sev(sev, icon)}  {_bold(v.message)}")
            if v.line:
                print(_gray(f"     Line {v.line}"))
            print(_gray(f"     {v.detail}"))
            if verbose:
                print(_blue(f"     → {v.suggestion}"))
            print()

    if not verbose and score.violations:
        print(_gray("  Run with --verbose for fix suggestions."))

    print(_gray(line))
    print()
    if score.critical:
        print(f"  Result: {_err(_bold(f'BLOCKED ({len(score.critical)} critical issue(s))'))}  — fix before merging")
    else:
        print(f"  Result: {_warn(_bold(f'{score.overall} risk'))}  — review before merging")
    print()


def print_scan_summary(scores: list[MigrationScore], fail_on: Severity) -> None:
    line = "─" * 60
    total = len(scores)
    clean = sum(1 for s in scores if s.passed)
    flagged = total - clean

    print()
    print(_bold("migration-guard — Scan Summary"))
    print(_gray(line))
    print()
    print(f"  Files scanned : {_bold(str(total))}")
    print(f"  Clean         : {_ok(str(clean))}")
    print(f"  Flagged       : {_err(str(flagged)) if flagged else _ok('0')}")
    print()
    print(_gray(line))
    print()

    for s in scores:
        if s.passed:
            print(f"  {_ok('✓')}  {_gray(s.filename)}")
        else:
            level_str = _sev(s.overall, str(s.overall))
            print(f"  {_sev(s.overall, SEVERITY_ICON[s.overall])}  {s.filename}  [{level_str}]  "
                  f"{_gray(str(len(s.violations)) + ' issue(s)')}")
            for v in s.violations:
                icon = SEVERITY_ICON[v.severity]
                print(f"       {_sev(v.severity, icon)}  {v.message}")

    print()
    print(_gray(line))
    print()

    blocked = [s for s in scores if s.overall >= fail_on and not s.passed]
    if blocked:
        print(f"  Result: {_err(_bold('FAILED'))}  — {len(blocked)} migration(s) exceed {fail_on} threshold")
    else:
        print(f"  Result: {_ok(_bold('PASSED'))}")
    print()


def write_json(scores: list[MigrationScore], path: str) -> None:
    def _v_dict(v):
        return {
            "rule_id": v.rule_id,
            "severity": str(v.severity),
            "message": v.message,
            "detail": v.detail,
            "suggestion": v.suggestion,
            "line": v.line,
        }

    data = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "summary": {
            "total": len(scores),
            "clean": sum(1 for s in scores if s.passed),
            "flagged": sum(1 for s in scores if not s.passed),
        },
        "files": [
            {
                "path": s.path,
                "filename": s.filename,
                "overall_risk": str(s.overall),
                "passed": s.passed,
                "violations": [_v_dict(v) for v in s.violations],
            }
            for s in scores
        ],
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def emit_github_annotations(scores: list[MigrationScore]) -> None:
    """Emit GitHub Actions annotations for each violation."""
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    for s in scores:
        for v in s.violations:
            level = "error" if v.severity >= Severity.HIGH else "warning"
            loc = f",line={v.line}" if v.line else ""
            print(f"::{level} file={s.path}{loc},title=migration-guard [{v.rule_id}]::{v.message} — {v.detail}")
