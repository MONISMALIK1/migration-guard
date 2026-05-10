"""Config loader — .migration-guard.yaml support."""

import os
from dataclasses import dataclass, field
from typing import Optional
from .rules import Severity


@dataclass
class GuardConfig:
    fail_on: Severity = Severity.CRITICAL
    skip_rules: list[str] = field(default_factory=list)
    ignore_paths: list[str] = field(default_factory=list)
    verbose: bool = False


def _parse_severity(s: str) -> Severity:
    mapping = {
        "low": Severity.LOW,
        "medium": Severity.MEDIUM,
        "high": Severity.HIGH,
        "critical": Severity.CRITICAL,
    }
    return mapping.get(str(s).lower(), Severity.CRITICAL)


def load_config(path: str) -> GuardConfig:
    """Load .migration-guard.yaml config file."""
    try:
        import yaml
    except ImportError:
        raise RuntimeError(
            "PyYAML is required for config files. "
            "Install with: pip install 'migration-guard[yaml]'"
        )
    with open(path) as f:
        data = yaml.safe_load(f) or {}

    return GuardConfig(
        fail_on=_parse_severity(data.get("fail_on", "critical")),
        skip_rules=data.get("skip_rules", []),
        ignore_paths=data.get("ignore_paths", []),
        verbose=data.get("verbose", False),
    )


def find_config(start_dir: str = ".") -> Optional[str]:
    """Search upward for .migration-guard.yaml."""
    candidates = [".migration-guard.yaml", ".migration-guard.yml", "migration-guard.yaml"]
    directory = os.path.abspath(start_dir)
    for _ in range(5):
        for name in candidates:
            path = os.path.join(directory, name)
            if os.path.exists(path):
                return path
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent
    return None
