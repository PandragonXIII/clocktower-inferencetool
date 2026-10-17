"""带时间预算的求解、查询与冲突诊断。

本模块是 ``botc_reasoner`` 的分析辅助层：它**不声明变量、不装载规则**，只接收调用方
已经准备好的约束表达式（域公理、规则记录、输入约束），在统一的 :class:`Budget`
下求解，并给出：

- :func:`build_solver`：把三类表达式装进一个普通 Z3 ``Solver``。
- :func:`check_scope`：在预算下做一次可满足性检查。
- :func:`query_status`：分别尝试命题与其否定，给出 ``possible`` / ``necessary`` /
  ``impossible`` / ``inconsistent`` / ``unknown``。
- :func:`diagnose`：把所有约束按「域 / 规则 / 输入」分组为 gate，求不可满足核并做
  inclusion-minimal 收缩，报告冲突涉及的输入与规则。

时间预算语义：``total_ms`` 是整段分析的总时长上限，``per_solve_ms`` 是**每次**求解
的上限；:meth:`Budget.check` 取二者剩余量的最小值作为本次 Z3 ``timeout``。当总预算已
耗尽时，不再求解，直接返回 ``z3.unknown`` 并把 ``reason`` 置为「总时间预算耗尽」。

诊断结论的诚实标注：``minimality`` 只有在核收缩全部完成时才为 ``"inclusion"``；
若中途预算耗尽而无法完成收缩，则为 ``"unverified"`` 且 ``complete=False``，
**不把未验证解释成最小**。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from time import monotonic
from typing import Any

from z3 import And, BoolRef, BoolVal, FreshBool, Not, Solver, unknown, unsat

REASON_BUDGET_EXHAUSTED = "总时间预算耗尽"
"""总预算耗尽时 :meth:`Budget.check` 记下的原因。"""

REASON_SOLVE_TIMEOUT = "单次求解超时"
"""单次求解在 ``per_solve_ms`` 内返回 unknown 时记下的原因。"""

MINIMALITY_INCLUSION = "inclusion"
MINIMALITY_UNVERIFIED = "unverified"

SCOPE_PUBLIC = "public"
SCOPE_CONDITIONAL = "conditional"

DOMAIN_GATE_ID = "tb:domain"
"""域公理分组使用的 gate 编号。"""


@dataclass(frozen=True)
class InputConstraint:
    """一条参与求解的输入约束及其来源元数据。"""

    id: str
    expr: BoolRef
    scope: str = SCOPE_CONDITIONAL
    owner_id: str | None = None
    source: str = "assumption"
    identity_claim: bool = False
    description: str = ""


class Budget:
    """以单调时钟衡量的求解时间预算。

    :param total_ms: 整段分析的总时长上限（毫秒）。
    :param per_solve_ms: 单次求解的时长上限（毫秒）。

    调用 :meth:`check` 后，``reason`` 保存最近一次求解失败（unknown）的原因，成功或
    未耗尽时为 ``None``；``hit`` 表示总预算已被耗尽。
    """

    def __init__(self, total_ms: int = 5000, per_solve_ms: int = 1000) -> None:
        if total_ms <= 0:
            raise ValueError("total_ms 必须为正数")
        if per_solve_ms <= 0:
            raise ValueError("per_solve_ms 必须为正数")
        self.total_ms = total_ms
        self.per_solve_ms = per_solve_ms
        self._deadline = monotonic() + total_ms / 1000.0
        self.reason: str | None = None
        self.hit = False

    def remaining_ms(self) -> float:
        """距离总截止时刻的剩余毫秒数，下限为 0。"""

        return max(0.0, (self._deadline - monotonic()) * 1000.0)

    def deadline_exhausted(self) -> bool:
        """总预算是否已经耗尽。"""

        return self.remaining_ms() <= 0.0

    def check(self, solver: Solver, *assumptions: BoolRef) -> Any:
        """在剩余预算内求解，返回 Z3 的 ``sat`` / ``unsat`` / ``unknown``。

        本次 ``timeout`` 取「总预算剩余」与 ``per_solve_ms`` 的较小值。总预算耗尽时
        不调用求解器，直接返回 ``unknown`` 并把 ``reason`` 置为「总时间预算耗尽」。
        """

        self.reason = None
        remaining = self.remaining_ms()
        if remaining <= 0.0:
            self.hit = True
            self.reason = REASON_BUDGET_EXHAUSTED
            return unknown

        # Z3 interprets timeout=0 as unlimited, so round sub-ms budgets up.
        solver.set("timeout", max(1, int(min(remaining, float(self.per_solve_ms)))))
        result = solver.check(*assumptions)
        if result == unknown:
            if self.deadline_exhausted():
                self.hit = True
                self.reason = REASON_BUDGET_EXHAUSTED
            else:
                self.reason = REASON_SOLVE_TIMEOUT
        return result


def build_solver(
    domain_exprs: Iterable[BoolRef],
    rule_records: Iterable[Any],
    inputs: Iterable[Any] = (),
) -> Solver:
    """把域公理、规则记录与输入约束装进一个普通 ``Solver``。

    ``rule_records`` 中的元素可为带 ``.expr`` 属性的记录（如
    :class:`botc_reasoner.provenance.ConstraintRecord`），也可直接是 ``BoolRef``；
    ``inputs`` 同理（如 :class:`InputConstraint`）。全部表达式按原样 ``add``。
    """

    solver = Solver()
    for expr in _exprs_of(domain_exprs):
        solver.add(expr)
    for record in rule_records:
        solver.add(_expr_of(record))
    for item in inputs:
        solver.add(_expr_of(item))
    return solver


def check_scope(solver: Solver, budget: Budget) -> str:
    """在预算下检查求解器，返回 ``"sat"`` / ``"unsat"`` / ``"unknown"``。"""

    return _status_str(budget.check(solver))


def query_status(
    solver: Solver,
    expr: BoolRef,
    budget: Budget,
    base_status: str = "sat",
) -> dict[str, Any]:
    """判断命题 ``expr`` 在背景下的状态。

    返回字典始终含 ``status``；仅当状态为 ``unknown`` 时附带 ``reason``。

    - 背景 ``unsat`` → ``inconsistent``（不空真爆炸，不对任意命题下结论）。
    - 背景 ``unknown`` → ``unknown``。
    - 背景 ``sat``：分别尝试 ``expr`` 与其否定（各自 ``push`` / ``try`` / ``finally`` /
      ``pop``）。只在正向 ``sat`` 且反向 ``unsat`` 时判 ``necessary``；**不因任一方向
      ``unsat`` 就推 ``necessary``**。
    """

    base = _status_str(base_status)
    if base == "unsat":
        return {"status": "inconsistent"}
    if base == "unknown":
        return {"status": "unknown", "reason": REASON_SOLVE_TIMEOUT}

    positive = _check_added(solver, expr, budget)
    if positive == "unknown":
        return {"status": "unknown", "reason": budget.reason or REASON_SOLVE_TIMEOUT}

    negative = _check_added(solver, Not(expr), budget)
    if negative == "unknown":
        return {"status": "unknown", "reason": budget.reason or REASON_SOLVE_TIMEOUT}

    if positive == "sat" and negative == "sat":
        return {"status": "possible"}
    if positive == "sat" and negative == "unsat":
        return {"status": "necessary"}
    if positive == "unsat" and negative == "sat":
        return {"status": "impossible"}
    return {"status": "inconsistent"}


def diagnose(
    domain_exprs: Iterable[BoolRef],
    rule_records: Iterable[Any],
    inputs: Iterable[InputConstraint],
    budget: Budget,
) -> dict[str, Any]:
    """定位约束集合的不可满足来源。

    分组规则：

    - 域公理合并为一个 gate，编号 :data:`DOMAIN_GATE_ID`。
    - 规则记录按 ``rule_id`` 聚合，每个规则一个 gate，表达式为 ``And(该规则所有表达式)``。
    - 每条输入各自一个 gate，编号为输入 ``id``。

    所有 gate 用 :class:`FreshBool` 作为追踪布尔量，避免与约束内变量冲突。整体
    ``unsat`` 时取不可满足核并做 inclusion-minimal 收缩。

    返回 ``{"status", "input_ids", "rule_ids", "minimality", "complete"}``，``unknown``
    或收缩未完成时附带 ``reason``。``minimality`` 为 ``"inclusion"`` 仅在收缩正常完成时；
    预算耗尽导致未验证时为 ``"unverified"`` 且 ``complete=False``。
    """

    gates: list[_Gate] = []
    domain = list(_exprs_of(domain_exprs))
    if domain:
        gates.append(_Gate(kind="domain", id=DOMAIN_GATE_ID, expr=_and(domain)))
    for rule_id, exprs in _group_by_rule(rule_records):
        gates.append(_Gate(kind="rule", id=rule_id, expr=_and(exprs)))
    for item in inputs:
        gates.append(_Gate(kind="input", id=item.id, expr=item.expr))

    solver = Solver()
    tracker_to_gate: dict[int, int] = {}
    for index, gate in enumerate(gates):
        tracker = FreshBool(f"gate_{gate.id}")
        tracker_to_gate[tracker.get_id()] = index
        solver.assert_and_track(gate.expr, tracker)

    status = _status_str(budget.check(solver))
    if status == "sat":
        return _result("sat", [], [], MINIMALITY_INCLUSION, True)
    if status == "unknown":
        return _result(
            "unknown", [], [], MINIMALITY_UNVERIFIED, False, budget.reason
        )

    core = [
        tracker_to_gate[item.get_id()]
        for item in solver.unsat_core()
        if item.get_id() in tracker_to_gate
    ]
    core = sorted(set(core))

    minimal, verified = _shrink(core, gates, budget)
    result = _result(
        "unsat",
        [gates[i].id for i in minimal if gates[i].kind == "input"],
        [gates[i].id for i in minimal if gates[i].kind in ("rule", "domain")],
        MINIMALITY_INCLUSION if verified else MINIMALITY_UNVERIFIED,
        verified,
    )
    if not verified:
        result["reason"] = budget.reason or REASON_SOLVE_TIMEOUT
    return result


@dataclass(frozen=True)
class _Gate:
    kind: str
    id: str
    expr: BoolRef


def _shrink(
    core: Sequence[int],
    gates: Sequence[_Gate],
    budget: Budget,
) -> tuple[list[int], bool]:
    """把核收缩到 inclusion-minimal；返回 (核, 是否完成验证)。"""

    current = list(core)
    for index in list(current):
        if budget.deadline_exhausted():
            return current, False
        trial = [item for item in current if item != index]
        status = _check_gates(gates, trial, budget)
        if status == "unsat":
            current = trial
        elif status == "unknown":
            return current, False
    return current, True


def _check_gates(
    gates: Sequence[_Gate],
    indices: Sequence[int],
    budget: Budget,
) -> str:
    solver = Solver()
    for index in indices:
        solver.add(gates[index].expr)
    return _status_str(budget.check(solver))


def _check_added(solver: Solver, expr: BoolRef, budget: Budget) -> str:
    solver.push()
    try:
        solver.add(expr)
        return _status_str(budget.check(solver))
    finally:
        solver.pop()


def _result(
    status: str,
    input_ids: list[str],
    rule_ids: list[str],
    minimality: str,
    complete: bool,
    reason: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": status,
        "input_ids": tuple(input_ids),
        "rule_ids": tuple(rule_ids),
        "minimality": minimality,
        "complete": complete,
    }
    if reason is not None:
        result["reason"] = reason
    return result


def _expr_of(item: Any) -> BoolRef:
    if isinstance(item, BoolRef):
        return item
    expr = getattr(item, "expr", item)
    if not isinstance(expr, BoolRef):
        raise TypeError(f"无法从 {item!r} 取得 BoolRef 表达式")
    return expr


def _exprs_of(items: Iterable[Any]) -> list[BoolRef]:
    return [_expr_of(item) for item in items]


def _group_by_rule(rule_records: Iterable[Any]) -> list[tuple[str, list[BoolRef]]]:
    order: list[str] = []
    grouped: dict[str, list[BoolRef]] = {}
    for record in rule_records:
        rule_id = getattr(record, "rule_id", None)
        if not rule_id:
            continue
        if rule_id not in grouped:
            grouped[rule_id] = []
            order.append(rule_id)
        grouped[rule_id].append(_expr_of(record))
    return [(rule_id, grouped[rule_id]) for rule_id in order]


def _and(exprs: Sequence[BoolRef]) -> BoolRef:
    if not exprs:
        return BoolVal(True)
    if len(exprs) == 1:
        return exprs[0]
    return And(*exprs)


def _status_str(status: Any) -> str:
    if isinstance(status, str):
        if status not in ("sat", "unsat", "unknown"):
            raise ValueError(f"invalid solver status: {status}")
        return status
    if status == unsat:
        return "unsat"
    if status == unknown:
        return "unknown"
    return "sat"
