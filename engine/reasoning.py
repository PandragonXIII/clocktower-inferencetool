"""A small, reusable constraint engine backed by Z3."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence

from z3 import FreshBool, Not, Solver, sat, unknown, unsat


class CheckStatus(str, Enum):
    SAT = "sat"
    UNSAT = "unsat"
    UNKNOWN = "unknown"


class QueryStatus(str, Enum):
    POSSIBLE = "possible"
    NECESSARY = "necessary"
    IMPOSSIBLE = "impossible"
    UNKNOWN = "unknown"
    INCONSISTENT = "inconsistent"


@dataclass(frozen=True)
class CheckResult:
    status: CheckStatus
    model: Optional[object] = None
    conflict_labels: tuple[str, ...] = ()
    reason_unknown: Optional[str] = None


@dataclass(frozen=True)
class QueryResult:
    status: QueryStatus
    model: Optional[object] = None
    conflict_labels: tuple[str, ...] = ()
    reason_unknown: Optional[str] = None


class ReasoningEngine:
    """Store named constraints and query them without retaining assumptions."""

    def __init__(self, timeout_ms: int = 1000) -> None:
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms <= 0:
            raise ValueError("timeout_ms must be a positive integer")
        self.timeout_ms = timeout_ms
        self._constraints: list[tuple[object, str]] = []
        self._labels: set[str] = set()

    def add_constraint(self, expr: object, label: Optional[str] = None) -> str:
        """Add a Z3 Boolean expression and return its unique diagnostic label."""
        if label is None:
            index = 1
            while f"constraint_{index}" in self._labels:
                index += 1
            label = f"constraint_{index}"
        if label in self._labels:
            raise ValueError(f"constraint label already exists: {label}")
        self._labels.add(label)
        self._constraints.append((expr, label))
        return label

    def check(self, assumptions: Sequence[object] = ()) -> CheckResult:
        """Check base constraints plus temporary assumptions."""
        solver = self._solver()
        if assumptions:
            solver.add(*assumptions)
        status = solver.check()
        if status == sat:
            return CheckResult(CheckStatus.SAT, model=solver.model())
        if status == unsat:
            return CheckResult(
                CheckStatus.UNSAT,
                conflict_labels=self._conflict_labels(solver),
            )
        return CheckResult(
            CheckStatus.UNKNOWN,
            reason_unknown=solver.reason_unknown() or str(unknown),
        )

    def query(self, expr: object, assumptions: Sequence[object] = ()) -> QueryResult:
        """Determine whether expr is possible, necessary, or impossible."""
        base = self.check(assumptions)
        if base.status == CheckStatus.UNSAT:
            return QueryResult(
                QueryStatus.INCONSISTENT, conflict_labels=base.conflict_labels
            )
        if base.status == CheckStatus.UNKNOWN:
            return QueryResult(
                QueryStatus.UNKNOWN, reason_unknown=base.reason_unknown
            )

        possible = self._solver()
        if assumptions:
            possible.add(*assumptions)
        possible.add(expr)
        possible_status = possible.check()
        if possible_status == unknown:
            return QueryResult(QueryStatus.UNKNOWN, reason_unknown=possible.reason_unknown())
        if possible_status == unsat:
            return QueryResult(QueryStatus.IMPOSSIBLE)

        impossible = self._solver()
        if assumptions:
            impossible.add(*assumptions)
        impossible.add(Not(expr))
        impossible_status = impossible.check()
        if impossible_status == unknown:
            return QueryResult(QueryStatus.UNKNOWN, reason_unknown=impossible.reason_unknown())
        if impossible_status == unsat:
            return QueryResult(QueryStatus.NECESSARY, model=possible.model())
        return QueryResult(QueryStatus.POSSIBLE, model=possible.model())

    def _solver(self) -> Solver:
        solver = Solver()
        solver.set(timeout=self.timeout_ms)
        tracker_labels = {}
        for expr, label in self._constraints:
            tracker = FreshBool("constraint_tracker")
            tracker_labels[tracker.get_id()] = label
            solver.assert_and_track(expr, tracker)
        self._tracker_labels = tracker_labels
        return solver

    def _conflict_labels(self, solver: Solver) -> tuple[str, ...]:
        # Z3's unsat core is a useful subset, not necessarily a minimal core.
        return tuple(
            self._tracker_labels[item.get_id()] for item in solver.unsat_core()
        )
