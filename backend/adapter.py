"""Translation layer between web protocol JSON and the reasoning engine.

This module is a *framework only*. It defines the adapter contract that the web
backend will use, classifies a protocol request into engine-ready buckets, and
provides a placeholder adapter that clearly reports that rule translation and
engine execution are not implemented yet.

Nothing here depends on Z3 or any concrete BOTC rule model.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

API_VERSION = "1.0"

PLACEHOLDER_MODE = "placeholder"
PLACEHOLDER_ACCEPTED_FACT_TYPES = ["role", "alignment"]

_UNIMPLEMENTED_REASON = (
    "规则转换未实现、未运行推理引擎：本适配器仅为框架占位，"
    "尚未将请求转换为约束，也未做任何一致性判断。"
)


@dataclass(frozen=True)
class PreparedRequest:
    """A protocol request split into engine-ready buckets.

    All values are deep copies of the input request, so callers may freely
    mutate the result without touching the original request object.
    """

    game: dict[str, Any]
    options: dict[str, Any]
    confirmed_facts: list[dict[str, Any]]
    reported_facts: list[dict[str, Any]]
    disabled_facts: list[dict[str, Any]]
    enabled_assumptions: list[dict[str, Any]]
    disabled_assumptions: list[dict[str, Any]]
    queries: list[dict[str, Any]]
    api_version: str
    request_id: str


def _is_enabled(item: dict[str, Any]) -> bool:
    return bool(item.get("enabled", True))


def _classify_fact(fact: dict[str, Any]) -> str:
    if not _is_enabled(fact):
        return "disabled"
    if fact.get("status") == "reported":
        return "reported"
    return "confirmed"


def prepare_request(request: dict[str, Any]) -> PreparedRequest:
    """Split a protocol request into classified buckets of deep-copied data.

    Facts are grouped into enabled confirmed facts (hard constraints), enabled
    reported facts (soft claims), and disabled facts. Assumptions are split into
    enabled and disabled. Queries, game, and options are copied as-is.

    The input ``request`` is never modified.
    """
    if not isinstance(request, dict):
        raise TypeError("request must be a mapping")

    game = copy.deepcopy(request.get("game") or {})
    options = copy.deepcopy(request.get("options") or {})

    confirmed_facts: list[dict[str, Any]] = []
    reported_facts: list[dict[str, Any]] = []
    disabled_facts: list[dict[str, Any]] = []

    for fact in request.get("facts") or []:
        fact = copy.deepcopy(fact)
        bucket = _classify_fact(fact)
        if bucket == "disabled":
            disabled_facts.append(fact)
        elif bucket == "reported":
            reported_facts.append(fact)
        else:
            confirmed_facts.append(fact)

    enabled_assumptions: list[dict[str, Any]] = []
    disabled_assumptions: list[dict[str, Any]] = []
    for assumption in request.get("assumptions") or []:
        assumption = copy.deepcopy(assumption)
        (enabled_assumptions if _is_enabled(assumption) else disabled_assumptions).append(
            assumption
        )

    queries = copy.deepcopy(list(request.get("queries") or []))

    return PreparedRequest(
        game=game,
        options=options,
        confirmed_facts=confirmed_facts,
        reported_facts=reported_facts,
        disabled_facts=disabled_facts,
        enabled_assumptions=enabled_assumptions,
        disabled_assumptions=disabled_assumptions,
        queries=queries,
        api_version=str(request.get("api_version", "")),
        request_id=str(request.get("request_id", "")),
    )


@runtime_checkable
class ReasoningAdapter(Protocol):
    """Contract for translating protocol requests into reasoning results."""

    def capabilities(self) -> dict[str, Any]:
        """Return capability metadata for ``GET /api/v1/capabilities``."""
        ...

    def reason(self, request: dict[str, Any]) -> dict[str, Any]:
        """Process a ``POST /api/v1/reason`` request and return a response."""
        ...


class PlaceholderAdapter:
    """Framework-only adapter: no rule translation, no engine execution.

    ``capabilities`` advertises an empty (but valid) capability surface, and
    ``reason`` echoes request identity while reporting ``unknown`` for global
    consistency and every query, because no reasoning was performed.
    """

    def capabilities(self) -> dict[str, Any]:
        return {
            "api_version": API_VERSION,
            "supported_fact_types": [],
            "query_types": [],
            "scripts": [],
            "extensions": {
                "adapter:mode": PLACEHOLDER_MODE,
                "adapter:accepted_fact_types": list(PLACEHOLDER_ACCEPTED_FACT_TYPES),
            },
        }

    def reason(self, request: dict[str, Any]) -> dict[str, Any]:
        prepared = prepare_request(request)
        game = prepared.game
        results = [
            {
                "id": query.get("id"),
                "status": "unknown",
                "reason": _UNIMPLEMENTED_REASON,
            }
            for query in prepared.queries
        ]
        return {
            "api_version": API_VERSION,
            "request_id": prepared.request_id,
            "game_id": game.get("id"),
            "revision": game.get("revision"),
            "consistency": "unknown",
            "reason": _UNIMPLEMENTED_REASON,
            "results": results,
            "extensions": {
                "adapter:mode": PLACEHOLDER_MODE,
            },
        }
