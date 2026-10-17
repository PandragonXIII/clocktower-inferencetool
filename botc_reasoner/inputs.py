"""把网页协议请求的 ``facts`` / ``assumptions`` 编译为 ``analysis.InputConstraint``。

本模块只做**分类与元数据整理**：把每条启用条目按 ``DESIGN.md`` §1.2 的 ``scope``
（``public`` / ``conditional``）、§1.3 的 ``source`` 与 ``owner`` 归桶，产出
:class:`botc_reasoner.analysis.InputConstraint`。它**不**声明变量、**不**装载规则、
**不**求解，也不构造或包装求解器。

表达式通过 ``fact_expr`` / ``proposition_expr`` 两个 callable 注入，避免与
``connector`` 相互 import（循环依赖）。调用方（连接器）提供真正的 Z3 表达式构造：

- ``fact_expr(fact, world, seats) -> BoolRef | None``：把一条 fact 转成约束；
- ``proposition_expr(proposition, world, seats, *, claimed) -> BoolRef | None``。

分类规则（对应 ``DESIGN.md`` §1）：

- **scope 默认分类**：``confirmed`` 的公开死亡公布（``botc:night_deaths``）与**已结算**
  的白天处决（``botc:day_vote`` 且 ``stage == "settled"``）归 ``public``，其余归
  ``conditional``。显式 ``extensions["reasoner:scope"]`` 优先；``reported`` **强制**
  ``conditional``，不允许升级为 public（公开说了不等于内容为真）。
- **source**：显式 ``extensions["reasoner:source"]`` 优先；``reported`` 记
  ``self_claim``，确认的技能观察（``botc:ability_observation``）记 ``received``，
  其余确认条目记 ``observation``。source 仅用于展示与修复追溯，不是语义轴。
- **owner**：显式 ``extensions["reasoner:owner_id"]`` 优先；否则取 role/alignment 命题的
  ``player_id``，或技能观察 ``data.actor_id``。
- **identity_claim**：fact ``type == "role"`` 为真；假设命题 ``kind == "role"`` 为真。

scope 分类与「映射真实命题还是 belief」是两件独立的事：本模块**不**因
``scope=conditional`` 就把已确认 role 改写成 belief；映射由注入的 ``fact_expr`` 负责。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Callable

from z3 import BoolRef

from botc_reasoner import analysis
from botc_reasoner.analysis import SCOPE_CONDITIONAL, SCOPE_PUBLIC

FACT_TYPE_ROLE = "role"
FACT_TYPE_ALIGNMENT = "alignment"

EXT_OBSERVATION = "botc:ability_observation"
EXT_NIGHT_DEATHS = "botc:night_deaths"
EXT_DAY_VOTE = "botc:day_vote"

EXT_KEY_SCOPE = "reasoner:scope"
EXT_KEY_SOURCE = "reasoner:source"
EXT_KEY_OWNER = "reasoner:owner_id"

SOURCE_RECEIVED = "received"
SOURCE_SELF_CLAIM = "self_claim"
SOURCE_OBSERVATION = "observation"
SOURCE_ASSUMPTION = "assumption"

FactExpr = Callable[[dict[str, Any], Any, dict[str, int]], "BoolRef | None"]
PropositionExpr = Callable[..., "BoolRef | None"]

__all__ = [
    "EXT_DAY_VOTE",
    "EXT_KEY_OWNER",
    "EXT_KEY_SCOPE",
    "EXT_KEY_SOURCE",
    "EXT_NIGHT_DEATHS",
    "EXT_OBSERVATION",
    "SOURCE_ASSUMPTION",
    "SOURCE_OBSERVATION",
    "SOURCE_RECEIVED",
    "SOURCE_SELF_CLAIM",
    "compile_inputs",
    "input_metadata",
]


def compile_inputs(
    request: dict[str, Any],
    world: Any,
    seats: dict[str, int],
    fact_expr: FactExpr,
    proposition_expr: PropositionExpr,
) -> list[analysis.InputConstraint]:
    """把一次请求编译成输入约束列表。

    遍历启用的 ``facts`` 与 ``assumptions``，调注入的表达式构造函数；返回 ``None``
    或 ``enabled:false`` 的条目被跳过。不做协议校验（那由 ``backend.validation``
    负责），对非字典条目一概忽略。
    """

    constraints: list[analysis.InputConstraint] = []
    constraints.extend(_compile_facts(request.get("facts"), world, seats, fact_expr))
    constraints.extend(
        _compile_assumptions(request.get("assumptions"), world, seats, proposition_expr)
    )
    return constraints


def input_metadata(
    inputs: Iterable[analysis.InputConstraint],
) -> list[dict[str, Any]]:
    """把输入约束投影为可 JSON 序列化的元数据（**不含** ``expr``）。"""

    return [
        {
            "id": item.id,
            "scope": item.scope,
            "source": item.source,
            "owner_id": item.owner_id,
            "identity_claim": item.identity_claim,
            "description": item.description,
        }
        for item in inputs
    ]


def _compile_facts(
    facts: Any,
    world: Any,
    seats: dict[str, int],
    fact_expr: FactExpr,
) -> list[analysis.InputConstraint]:
    out: list[analysis.InputConstraint] = []
    for fact in _iter_dicts(facts):
        if fact.get("enabled", True) is False:
            continue
        expr = fact_expr(fact, world, seats)
        if expr is None:
            continue
        out.append(
            analysis.InputConstraint(
                id=str(fact.get("id")),
                expr=expr,
                scope=_fact_scope(fact),
                owner_id=_fact_owner(fact),
                source=_fact_source(fact),
                identity_claim=fact.get("type") == FACT_TYPE_ROLE,
                description=_fact_description(fact),
            )
        )
    return out


def _compile_assumptions(
    assumptions: Any,
    world: Any,
    seats: dict[str, int],
    proposition_expr: PropositionExpr,
) -> list[analysis.InputConstraint]:
    out: list[analysis.InputConstraint] = []
    for assumption in _iter_dicts(assumptions):
        if assumption.get("enabled", True) is False:
            continue
        proposition = assumption.get("proposition")
        expr = proposition_expr(proposition, world, seats, claimed=False)
        if expr is None:
            continue
        out.append(
            analysis.InputConstraint(
                id=str(assumption.get("id")),
                expr=expr,
                scope=_scope_from_extensions(assumption) or SCOPE_CONDITIONAL,
                owner_id=_owner_from_extensions(assumption) or _proposition_player_id(proposition),
                source=_source_from_extensions(assumption) or SOURCE_ASSUMPTION,
                identity_claim=_proposition_kind(proposition) == FACT_TYPE_ROLE,
                description=_assumption_description(assumption),
            )
        )
    return out


def _fact_scope(fact: dict[str, Any]) -> str:
    explicit = _scope_from_extensions(fact)
    reported = fact.get("status") == "reported"
    if reported:
        return SCOPE_CONDITIONAL
    if explicit is not None:
        return explicit
    if fact.get("status") != "confirmed":
        return SCOPE_CONDITIONAL
    fact_type = fact.get("type")
    if fact_type == EXT_NIGHT_DEATHS:
        return SCOPE_PUBLIC
    if fact_type == EXT_DAY_VOTE:
        data = fact.get("data")
        if isinstance(data, dict) and data.get("stage") == "settled":
            return SCOPE_PUBLIC
    return SCOPE_CONDITIONAL


def _fact_source(fact: dict[str, Any]) -> str:
    explicit = _source_from_extensions(fact)
    if explicit is not None:
        return explicit
    if fact.get("status") == "reported":
        return SOURCE_SELF_CLAIM
    if fact.get("type") == EXT_OBSERVATION:
        return SOURCE_RECEIVED
    return SOURCE_OBSERVATION


def _fact_owner(fact: dict[str, Any]) -> str | None:
    explicit = _owner_from_extensions(fact)
    if explicit is not None:
        return explicit
    owner = _proposition_player_id(fact.get("proposition"))
    if owner is not None:
        return owner
    data = fact.get("data")
    if isinstance(data, dict):
        actor = data.get("actor_id")
        if isinstance(actor, str) and actor:
            return actor
    return None


def _scope_from_extensions(item: dict[str, Any]) -> str | None:
    value = _extension(item, EXT_KEY_SCOPE)
    if value in (SCOPE_PUBLIC, SCOPE_CONDITIONAL):
        return value
    return None


def _source_from_extensions(item: dict[str, Any]) -> str | None:
    value = _extension(item, EXT_KEY_SOURCE)
    if isinstance(value, str) and value:
        return value
    return None


def _owner_from_extensions(item: dict[str, Any]) -> str | None:
    value = _extension(item, EXT_KEY_OWNER)
    if isinstance(value, str) and value:
        return value
    return None


def _extension(item: dict[str, Any], key: str) -> Any:
    extensions = item.get("extensions")
    if isinstance(extensions, dict):
        return extensions.get(key)
    return None


def _proposition_player_id(proposition: Any) -> str | None:
    if isinstance(proposition, dict):
        player_id = proposition.get("player_id")
        if isinstance(player_id, str) and player_id:
            return player_id
    return None


def _proposition_kind(proposition: Any) -> str | None:
    if isinstance(proposition, dict):
        return proposition.get("kind")
    return None


def _fact_description(fact: dict[str, Any]) -> str:
    parts = [f"事实 {fact.get('id')}", f"type={fact.get('type')}"]
    parts.append(f"status={fact.get('status')}")
    _append_proposition(parts, fact.get("proposition"))
    data = fact.get("data")
    if data is not None:
        parts.append("data=" + _json(data))
    return "；".join(parts)


def _assumption_description(assumption: dict[str, Any]) -> str:
    parts = [f"假设 {assumption.get('id')}"]
    _append_proposition(parts, assumption.get("proposition"))
    return "；".join(parts)


def _append_proposition(parts: list[str], proposition: Any) -> None:
    if not isinstance(proposition, dict):
        return
    kind = proposition.get("kind")
    parts.append(f"kind={kind}")
    if proposition.get("role_id"):
        parts.append(f"role_id={proposition.get('role_id')}")
    if proposition.get("alignment"):
        parts.append(f"alignment={proposition.get('alignment')}")
    if proposition.get("player_id"):
        parts.append(f"player_id={proposition.get('player_id')}")
    if "time" in proposition:
        parts.append("time=" + _json(proposition.get("time")))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _iter_dicts(items: Any) -> Iterable[dict[str, Any]]:
    if not isinstance(items, list):
        return
    for item in items:
        if isinstance(item, dict):
            yield item
