"""规则来源追踪：把约束与 RuleSpec 元数据绑定起来。

本模块**只收集**约束与规则元数据，不构造或包装求解器，也不引入新的推理引擎。
它记录「哪条约束由哪条规则、在哪个实例下产生」，供冲突解释、修复与候选世界追溯使用。
真正把约束放进 Z3 ``Solver`` 仍由调用方完成。
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, replace
from typing import Any

from z3 import BoolRef, BoolVal

UNCLASSIFIED_RULE_ID = "tb:unclassified"
"""未处于任何 rule context 时所用规则编号。"""


@dataclass(frozen=True)
class RuleSpec:
    """一条规则的来源元数据。"""

    id: str
    title: str
    source: str = ""
    description: str = ""


@dataclass(frozen=True)
class ConstraintRecord:
    """一条被收集的约束及其来源。"""

    expr: BoolRef
    rule_id: str
    instance_id: str
    input_ids: tuple[str, ...] = ()
    scope: str = "rule"
    owner_id: str | None = None


_UNCLASSIFIED_SPEC = RuleSpec(
    id=UNCLASSIFIED_RULE_ID,
    title="未分类约束",
    source="",
    description="不在任何 rule context 内收集到的约束。",
)


class ConstraintCollector:
    """收集约束与 RuleSpec，不做求解。"""

    def __init__(self) -> None:
        self.records: list[ConstraintRecord] = []
        self.catalog: dict[str, RuleSpec] = {UNCLASSIFIED_RULE_ID: _UNCLASSIFIED_SPEC}
        self._stack: list[RuleSpec] = []
        self._counters: dict[str, int] = {}

    def register(self, spec: RuleSpec) -> RuleSpec:
        """登记一份规则元数据，返回合并后的结果。

        同一 ``id`` 可重复登记：空字段会被非空字段补全；两处非空且不一致则视为冲突并拒绝。
        这允许先以默认（可空）元数据登记，之后补全 ``title`` / ``source`` / ``description``。
        """

        if not spec.id:
            raise ValueError("RuleSpec.id 不能为空")
        existing = self.catalog.get(spec.id)
        if existing is None:
            self.catalog[spec.id] = spec
            return spec
        merged = _merge_spec(existing, spec)
        self.catalog[spec.id] = merged
        return merged

    @contextmanager
    def context(
        self,
        rule_id: str,
        title: str = "",
        source: str = "",
        description: str = "",
    ) -> Iterator[RuleSpec]:
        """进入一个规则上下文，退出时恢复上一层。

        嵌套时内层覆盖外层；退出后恢复外层。进入时会把元数据登记进 ``catalog``，
        返回合并后的 :class:`RuleSpec`。未使用本上下文时 ``add`` 记入
        :data:`UNCLASSIFIED_RULE_ID`。
        """

        spec = self.register(
            RuleSpec(id=rule_id, title=title, source=source, description=description)
        )
        self._stack.append(spec)
        try:
            yield spec
        finally:
            self._stack.pop()

    def add(
        self,
        *exprs: Any,
        input_ids: Iterable[str] = (),
        scope: str = "rule",
        owner_id: str | None = None,
    ) -> None:
        """逐条收集约束，兼容 Z3 ``Solver.add`` 的列表嵌套与布尔转换。

        参数可任意嵌套 ``list`` / ``tuple``；Python ``bool`` 会转成 ``BoolVal``。
        每个叶子表达式单独成一条 :class:`ConstraintRecord`，``instance_id`` 形如
        ``"<rule_id>#<n>"``，``n`` 为同一规则内自增的实例计数（从 1 开始）。
        本方法**不**把约束加入任何求解器，仅写入 ``records``。
        """

        rule_id = self._current.id
        for expr in _flatten(exprs):
            count = self._counters.get(rule_id, 0) + 1
            self._counters[rule_id] = count
            self.records.append(
                ConstraintRecord(
                    expr=expr,
                    rule_id=rule_id,
                    instance_id=f"{rule_id}#{count}",
                    input_ids=tuple(input_ids),
                    scope=scope,
                    owner_id=owner_id,
                )
            )

    @property
    def _current(self) -> RuleSpec:
        if self._stack:
            return self._stack[-1]
        return self.catalog[UNCLASSIFIED_RULE_ID]


def rule_context(
    target: Any,
    rule_id: str,
    title: str = "",
    source: str = "",
    description: str = "",
) -> AbstractContextManager[Any]:
    """若 ``target`` 提供 ``context`` 则用之，否则返回 :func:`contextlib.nullcontext`。

    这样同一段规则代码在「启用来源追踪」与「未启用」两种情况下都能运行。
    """

    context = getattr(target, "context", None)
    if callable(context):
        return context(rule_id, title=title, source=source, description=description)
    return nullcontext()


def _flatten(exprs: Iterable[Any]) -> Iterator[BoolRef]:
    for expr in exprs:
        if isinstance(expr, (list, tuple)):
            yield from _flatten(expr)
        elif isinstance(expr, bool):
            yield BoolVal(expr)
        else:
            yield expr


def _merge_spec(existing: RuleSpec, incoming: RuleSpec) -> RuleSpec:
    updates: dict[str, str] = {}
    for name in ("title", "source", "description"):
        current = getattr(existing, name)
        new = getattr(incoming, name)
        if new == current or not new:
            continue
        if not current:
            updates[name] = new
            continue
        raise ValueError(
            f"RuleSpec({existing.id!r}) 元数据冲突：{name} 已为 {current!r}，"
            f"不能再登记为 {new!r}"
        )
    if not updates:
        return existing
    return replace(existing, **updates)
