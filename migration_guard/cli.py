"""Click CLI — check / scan commands."""

import os
import sys

import click

from .rules import Severity
from .scanner import check_file, scan_directory
from .reporter import print_score, print_scan_summary, write_json, emit_github_annotations
from .config import load_config, find_config


def _parse_severity(s: str) -> Severity:
    mapping = {"low": Severity.LOW, "medium": Severity.MEDIUM,
               "high": Severity.HIGH, "critical": Severity.CRITICAL}
    v = mapping.get(s.lower())
    if v is None:
        raise click.BadParameter(f"Must be one of: low, medium, high, critical")
    return v


@click.group()
@click.version_option(package_name="migration-guard")
def cli():
    """migration-guard — catch dangerous database migrations before they reach production."""


@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--fail-on", default="critical", show_default=True,
              help="Minimum severity to exit 1 (low/medium/high/critical)")
@click.option("--skip-rule", "skip_rules", multiple=True,
              help="Rule IDs to skip (e.g. --skip-rule NO_ROLLBACK)")
@click.option("--verbose", "-v", is_flag=True, default=False,
              help="Show fix suggestions for each issue")
@click.option("--json-report", default=None, help="Write report to JSON file")
@click.option("--config", "config_path", default=None,
              help="Path to .migration-guard.yaml config")
def check(path, fail_on, skip_rules, verbose, json_report, config_path):
    """Check a single migration file for risks."""
    # Load config file if present
    cfg_path = config_path or find_config(os.path.dirname(os.path.abspath(path)))
    if cfg_path and os.path.exists(cfg_path):
        try:
            cfg = load_config(cfg_path)
            fail_on = fail_on if fail_on != "critical" else str(cfg.fail_on).lower()
            skip_rules = list(skip_rules) or cfg.skip_rules
            verbose = verbose or cfg.verbose
        except Exception as e:
            click.echo(f"Warning: could not load config: {e}", err=True)

    fail_severity = _parse_severity(fail_on)

    result = check_file(path, skip_rules=list(skip_rules))
    print_score(result, verbose=verbose)

    if json_report:
        write_json([result], json_report)
        click.echo(f"JSON report written to {json_report}")

    emit_github_annotations([result])

    if not result.passed and result.overall >= fail_severity:
        sys.exit(1)


@cli.command()
@click.argument("directory", type=click.Path(exists=True, file_okay=False))
@click.option("--fail-on", default="critical", show_default=True,
              help="Minimum severity to exit 1 (low/medium/high/critical)")
@click.option("--skip-rule", "skip_rules", multiple=True,
              help="Rule IDs to skip")
@click.option("--verbose", "-v", is_flag=True, default=False,
              help="Show fix suggestions")
@click.option("--no-recursive", is_flag=True, default=False,
              help="Don't recurse into subdirectories")
@click.option("--json-report", default=None, help="Write report to JSON file")
@click.option("--config", "config_path", default=None,
              help="Path to .migration-guard.yaml config")
def scan(directory, fail_on, skip_rules, verbose, no_recursive, json_report, config_path):
    """Scan a directory for all migration files and report risks."""
    cfg_path = config_path or find_config(directory)
    if cfg_path and os.path.exists(cfg_path):
        try:
            cfg = load_config(cfg_path)
            fail_on = fail_on if fail_on != "critical" else str(cfg.fail_on).lower()
            skip_rules = list(skip_rules) or cfg.skip_rules
            verbose = verbose or cfg.verbose
        except Exception as e:
            click.echo(f"Warning: could not load config: {e}", err=True)

    fail_severity = _parse_severity(fail_on)

    scores = scan_directory(
        directory,
        skip_rules=list(skip_rules),
        recursive=not no_recursive,
    )

    if not scores:
        click.echo(f"No migration files found in '{directory}'.")
        return

    print_scan_summary(scores, fail_on=fail_severity)

    if json_report:
        write_json(scores, json_report)
        click.echo(f"JSON report written to {json_report}")

    emit_github_annotations(scores)

    blocked = [s for s in scores if s.overall >= fail_severity and not s.passed]
    if blocked:
        sys.exit(1)


def main():
    cli()


if __name__ == "__main__":
    main()
