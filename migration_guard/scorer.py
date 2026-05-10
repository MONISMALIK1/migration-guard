"""Risk scorer — assigns overall risk level to a migration."""

from dataclasses import dataclass, field
from .rules import RuleViolation, Severity


@dataclass
class MigrationScore:
    path: str
    filename: str
    violations: list[RuleViolation]
    overall: Severity

    @property
    def critical(self) -> list[RuleViolation]:
        return [v for v in self.violations if v.severity == Severity.CRITICAL]

    @property
    def high(self) -> list[RuleViolation]:
        return [v for v in self.violations if v.severity == Severity.HIGH]

    @property
    def medium(self) -> list[RuleViolation]:
        return [v for v in self.violations if v.severity == Severity.MEDIUM]

    @property
    def low(self) -> list[RuleViolation]:
        return [v for v in self.violations if v.severity == Severity.LOW]

    @property
    def passed(self) -> bool:
        return len(self.violations) == 0

    @property
    def risk_bar(self) -> str:
        bars = {
            Severity.LOW:      "██░░░░░░░░",
            Severity.MEDIUM:   "████░░░░░░",
            Severity.HIGH:     "███████░░░",
            Severity.CRITICAL: "██████████",
        }
        return bars.get(self.overall, "░░░░░░░░░░")


def score(path: str, filename: str, violations: list[RuleViolation]) -> MigrationScore:
    """Compute the overall risk level from a list of violations."""
    if not violations:
        overall = Severity.LOW
    else:
        overall = max(v.severity for v in violations)

    return MigrationScore(
        path=path,
        filename=filename,
        violations=violations,
        overall=overall,
    )
