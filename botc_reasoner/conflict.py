"""从输入命题里抽出极小不可满足子集。"""

from __future__ import annotations

from collections.abc import Sequence

from z3 import BoolRef, FreshBool, Solver, sat, unknown, unsat


def minimal_unsatisfiable_subset(
    solver: Solver,
    propositions: Sequence[tuple[BoolRef, str]],
) -> tuple[str, ...]:
    """返回导致矛盾的一个极小输入命题集。

    ``solver`` 里只放背景规则。这些规则本身应当可满足，函数不会把它们列进结果。
    ``propositions`` 是尚未加入求解器的输入命题，每条配一个不重复的标签。
    调用不会改写求解器里已有的约束。

    返回的标签保持输入顺序。去掉其中任意一条后，剩下的输入命题与背景规则一起即可满足。
    输入命题与背景规则并不矛盾时，返回空元组。
    """

    _validate_labels(propositions)
    if _check(solver, ()) == unsat:
        raise ValueError("背景约束本身不可满足")

    status, core = _unsat_core(solver, propositions)
    if status == sat:
        return ()
    if status == unknown:
        raise TimeoutError("求解超时，未能求出最小不可满足集")

    for index in list(core):
        trial = [item for item in core if item != index]
        trial_status = _check(solver, [propositions[item][0] for item in trial])
        if trial_status == unsat:
            core = trial
    return tuple(propositions[index][1] for index in core)


def _validate_labels(propositions: Sequence[tuple[BoolRef, str]]) -> None:
    labels = []
    for _expr, label in propositions:
        if not isinstance(label, str) or not label:
            raise ValueError("命题标签必须是非空字符串")
        labels.append(label)
    if len(labels) != len(set(labels)):
        raise ValueError("命题标签必须唯一")


def _unsat_core(
    solver: Solver,
    propositions: Sequence[tuple[BoolRef, str]],
) -> tuple[object, list[int]]:
    solver.push()
    tracker_of: dict[int, int] = {}
    try:
        for index, (expr, _label) in enumerate(propositions):
            tracker = FreshBool("input_proposition")
            tracker_of[tracker.get_id()] = index
            solver.assert_and_track(expr, tracker)
        status = solver.check()
        if status != unsat:
            return status, []
        core = {tracker_of[item.get_id()] for item in solver.unsat_core()}
    finally:
        solver.pop()
    if not core:
        raise ValueError("背景约束本身不可满足")
    return status, [index for index in range(len(propositions)) if index in core]


def _check(solver: Solver, formulas: Sequence[BoolRef]) -> object:
    solver.push()
    try:
        for formula in formulas:
            solver.add(formula)
        return solver.check()
    finally:
        solver.pop()
