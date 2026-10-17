"""候选世界枚举与投影（对应 DESIGN.md §8）。

本模块在调用方已备好的 Z3 ``Solver`` 上，逐模型枚举**联合世界**，并把每个模型投影到
调用方指定的角色断面（``projection``）。它**不声明变量、不装载规则、不做概率推断**，
只负责：

- 逐模型读取投影：一次读出一整套角色赋值（一个合法世界）；
- 用 blocking clause 阻断**已枚举的完整投影**，避免「隐藏变量不同但投影相同」的重复计数；
- 在 :class:`botc_reasoner.analysis.Budget` 下限制时间、在 ``max_worlds`` 下限制数量；
- 用 ``complete`` / ``total`` / ``truncated_reason`` 诚实标注枚举是否完整。

枚举始终在 ``solver.push()`` / ``solver.pop()`` 之间进行；blocking clause 只加在压栈层，
**不会污染**调用方的求解器。``total`` 是**计数**，仅在 ``complete=True`` 时精确，不是概率，
也不代表每种世界等可能。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from z3 import BoolRef, Not, Or, is_true, unknown, unsat

from botc_reasoner.analysis import Budget

TRUNCATED_MAX_WORLDS = "max_worlds"
"""达到 ``max_worlds`` 数量上限而停止。"""

TRUNCATED_SOLVER_UNKNOWN = "solver_unknown"
"""单次求解在预算内返回 unknown 而停止。"""

TRUNCATED_DEADLINE = "deadline"
"""总时间预算耗尽而停止。"""

__all__ = [
    "TRUNCATED_DEADLINE",
    "TRUNCATED_MAX_WORLDS",
    "TRUNCATED_SOLVER_UNKNOWN",
    "enumerate_worlds",
]


def enumerate_worlds(
    solver,
    projection: Sequence[tuple[Any, Sequence[tuple[Any, BoolRef]]]],
    budget: Budget,
    max_worlds: int = 20,
    base_status: str = "sat",
) -> dict[str, Any]:
    """逐模型枚举联合世界，并按 ``projection`` 投影。

    :param solver: 已装载背景约束的 Z3 ``Solver``，本函数不会修改其长期状态。
    :param projection: ``[(player_id, [(role_id, BoolRef), ...]), ...]``；每一位玩家预期
        **恰有一个** BoolRef 为真（one-hot）。``player_id`` 与 ``role_id`` 由调用方提供，
        原样出现在结果中。
    :param budget: 时间预算，见 :class:`botc_reasoner.analysis.Budget`。
    :param max_worlds: 最多返回的世界数；它是**上限**，不是下限。达到上限即停并标注
        ``truncated_reason="max_worlds"``（若能再 check 确认无更多投影，则判为完整）。
    :param base_status: 背景的已知状态（``"sat"`` / ``"unsat"`` / ``"unknown"``）。背景
        ``unsat`` 直接返回空枚举且 ``complete=True``；``unknown`` 返回
        ``complete=False`` 且 ``truncated_reason="solver_unknown"``。

    返回::

        {
          "worlds": [{"roles": {player_id: role_id}}, ...],
          "complete": bool,
          "returned_count": int,
          "total": int | None,          # 仅 complete=True 时精确
          "truncated_reason": str | None,
        }

    结果不含任何 Z3 对象；``total`` 只用于计数，不表达概率。
    """

    normalized = _normalize_projection(projection)
    if max_worlds < 0:
        raise ValueError("max_worlds 不能为负数")

    base = str(base_status)
    if base == "unsat":
        return _result([], True, None, total=0)
    if base == "unknown":
        return _result([], False, TRUNCATED_SOLVER_UNKNOWN)

    worlds: list[dict[str, Any]] = []
    complete = False
    total: int | None = None
    truncated_reason: str | None = None

    solver.push()
    try:
        while True:
            if len(worlds) >= max_worlds:
                status = budget.check(solver)
                if status == unsat:
                    complete = True
                    total = len(worlds)
                elif status == unknown:
                    truncated_reason = _truncated_from_budget(budget)
                else:
                    truncated_reason = TRUNCATED_MAX_WORLDS
                break

            status = budget.check(solver)
            if status == unsat:
                complete = True
                total = len(worlds)
                break
            if status == unknown:
                truncated_reason = _truncated_from_budget(budget)
                break

            model = solver.model()
            roles, true_bits = _read_projection(model, normalized)
            worlds.append({"roles": roles})
            solver.add(Or([Not(bit) for bit in true_bits]))
    finally:
        solver.pop()

    return _result(worlds, complete, truncated_reason, total)


def _normalize_projection(
    projection: Sequence[tuple[Any, Sequence[tuple[Any, BoolRef]]]],
) -> list[tuple[Any, list[tuple[Any, BoolRef]]]]:
    """把投影整理成 ``[(player_id, [(role_id, BoolRef), ...]), ...]``。"""

    normalized: list[tuple[Any, list[tuple[Any, BoolRef]]]] = []
    for player_id, roles in projection:
        entries = list(roles)
        for role_id, bit in entries:
            if not isinstance(bit, BoolRef):
                raise TypeError(
                    f"投影 {(player_id, role_id)!r} 的位不是 BoolRef：{bit!r}"
                )
        normalized.append((player_id, entries))
    return normalized


def _read_projection(
    model,
    normalized: Sequence[tuple[Any, list[tuple[Any, BoolRef]]]],
) -> tuple[dict[Any, Any], list[BoolRef]]:
    """从模型读出一整套角色赋值，并返回参与 blocking 的「为真」位。

    投影去重只阻断**本次投影中为真的位**，因此隐藏变量取值不同但投影相同的模型
    会被视作同一世界，不会重复计数。
    """

    roles: dict[Any, Any] = {}
    true_bits: list[BoolRef] = []
    for player_id, entries in normalized:
        chosen: Any = None
        for role_id, bit in entries:
            if is_true(model.eval(bit, model_completion=True)):
                chosen = role_id
                true_bits.append(bit)
                break
        roles[player_id] = chosen
    return roles, true_bits


def _truncated_from_budget(budget: Budget) -> str:
    if budget.deadline_exhausted():
        return TRUNCATED_DEADLINE
    return TRUNCATED_SOLVER_UNKNOWN


def _result(
    worlds: list[dict[str, Any]],
    complete: bool,
    truncated_reason: str | None,
    total: int | None = None,
) -> dict[str, Any]:
    return {
        "worlds": worlds,
        "complete": complete,
        "returned_count": len(worlds),
        "total": total,
        "truncated_reason": truncated_reason,
    }
