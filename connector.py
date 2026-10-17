"""把网页协议请求转成命题，并调用已有的暗流涌动求解器。

不修改前端或占位后台。本程序可以：

- 直接求解一份请求 JSON：``.venv/bin/python connector.py 请求.json``
- 同时提供网页和真实推理 API：``.venv/bin/python connector.py serve --port 8000``

``开始推理`` 会把当前快照 POST 到 ``/api/v1/reason``。本服务读取该请求。
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from typing import Any

from z3 import And, BoolRef, Not, Or, Solver, is_true, sat, unknown, unsat

from botc_reasoner import (
    Role,
    add_game_rules,
    declare_variables,
    minimal_unsatisfiable_subset,
    role_from_name,
)
from botc_reasoner.roles import BASE_SETUP, EVIL_ROLES, GOOD_ROLES, OUTSIDERS, TOWNSFOLK
from botc_reasoner.variables import Ability, Moment, TroubleBrewingVars

_OBSERVATION = "botc:ability_observation"
_NIGHT_DEATHS = "botc:night_deaths"
_DAY_VOTE = "botc:day_vote"
_EXTENSIONS = {_OBSERVATION, _NIGHT_DEATHS, _DAY_VOTE}


class TroubleBrewingAdapter:
    """无状态适配器：每次请求单独建一局求解器。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def capabilities(self) -> dict[str, Any]:
        return {
            "api_version": "1.0",
            "supported_fact_types": ["role", "alignment", *_EXTENSIONS],
            "query_types": ["role", "alignment"],
            "scripts": ["trouble_brewing"],
            "extensions": {"adapter:mode": "trouble_brewing"},
        }

    def reason(self, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            return _reason(request)


def _reason(request: dict[str, Any]) -> dict[str, Any]:
    game = request.get("game") or {}
    response = {
        "api_version": "1.0",
        "request_id": request.get("request_id"),
        "game_id": game.get("id"),
        "revision": game.get("revision"),
        "results": [],
        "extensions": {"adapter:mode": "trouble_brewing"},
    }
    try:
        world, solver, propositions = _prepare(request)
    except ValueError as error:
        response["consistency"] = "unknown"
        response["reason"] = str(error)
        response["results"] = [
            {"id": query.get("id"), "status": "unknown", "reason": str(error)}
            for query in request.get("queries") or []
            if isinstance(query, dict)
        ]
        return response

    timeout = (request.get("options") or {}).get("timeout_ms")
    if isinstance(timeout, int) and not isinstance(timeout, bool) and timeout > 0:
        solver.set("timeout", timeout)

    solver.push()
    for expr, _label in propositions:
        solver.add(expr)
    status = solver.check()
    if status == unknown:
        response["consistency"] = "unknown"
        response["reason"] = solver.reason_unknown() or "求解超时"
        response["results"] = [
            {"id": query.get("id"), "status": "unknown", "reason": response["reason"]}
            for query in request.get("queries") or []
            if isinstance(query, dict)
        ]
        return response
    if status == unsat:
        solver.pop()
        labels = minimal_unsatisfiable_subset(solver, propositions)
        response["consistency"] = "unsat"
        response["results"] = [
            {"id": query.get("id"), "status": "inconsistent"}
            for query in request.get("queries") or []
            if isinstance(query, dict)
        ]
        response["conflicts"] = [{"input_ids": list(labels), "rule_ids": []}]
        return response

    response["consistency"] = "sat"
    response["model"] = {"assignments": _setup_model(solver, world, game)}
    response["extensions"]["trouble_brewing:possible_roles"] = _possible_roles(solver, world, game)
    response["results"] = [
        _query_result(solver, world, game, query)
        for query in request.get("queries") or []
        if isinstance(query, dict)
    ]
    return response


def _prepare(request: dict[str, Any]) -> tuple[TroubleBrewingVars, Solver, list[tuple[BoolRef, str]]]:
    game = request.get("game") or {}
    if game.get("script_id") not in (None, "", "trouble_brewing"):
        raise ValueError("连接器目前只求解暗流涌动")
    players = list(game.get("players") or [])
    count = len(players)
    if count not in BASE_SETUP:
        raise ValueError(f"暗流涌动配置表只覆盖 5–15 人，收到 {count}")
    seats = _seats(players)
    nights = _horizon(request)
    world = declare_variables(count, n_nights=nights, tag="web")
    solver = world.build_solver()
    add_game_rules(solver, world, *BASE_SETUP[count])
    propositions = _propositions(request, world, seats)
    return world, solver, propositions


def _seats(players: list[dict[str, Any]]) -> dict[str, int]:
    seats: dict[str, int] = {}
    for player in players:
        seat = player.get("seat")
        player_id = player.get("id")
        if not isinstance(player_id, str) or not isinstance(seat, int) or isinstance(seat, bool):
            raise ValueError("玩家需要字符串 id 和整数座位")
        if seat < 1 or seat > len(players) or player_id in seats or (seat - 1) in seats.values():
            raise ValueError(f"座位或玩家 id 无效：{player_id}")
        seats[player_id] = seat - 1
    return seats


def _horizon(request: dict[str, Any]) -> int:
    nights = 1
    times = [(request.get("game") or {}).get("time")]
    for collection in ("facts", "assumptions", "queries"):
        for item in request.get(collection) or []:
            if not isinstance(item, dict):
                continue
            proposition = item.get("proposition") or {}
            times.append(proposition.get("time") if isinstance(proposition, dict) else None)
            data = item.get("data") or {}
            times.append(data.get("time") if isinstance(data, dict) else None)
    for time in times:
        if isinstance(time, dict) and time.get("phase") in {"night", "day"}:
            number = time.get("number")
            if isinstance(number, int) and not isinstance(number, bool):
                nights = max(nights, number)
    return nights


def _propositions(
    request: dict[str, Any],
    world: TroubleBrewingVars,
    seats: dict[str, int],
) -> list[tuple[BoolRef, str]]:
    propositions: list[tuple[BoolRef, str]] = []
    for fact in request.get("facts") or []:
        if not isinstance(fact, dict):
            continue
        expr = _fact_expr(fact, world, seats)
        if expr is not None:
            propositions.append((expr, str(fact.get("id") or "fact")))
    for assumption in request.get("assumptions") or []:
        if not isinstance(assumption, dict) or assumption.get("enabled", True) is False:
            continue
        expr = _proposition_expr(assumption.get("proposition"), world, seats, claimed=False)
        if expr is not None:
            propositions.append((expr, str(assumption.get("id") or "assumption")))
    return propositions


def _fact_expr(
    fact: dict[str, Any],
    world: TroubleBrewingVars,
    seats: dict[str, int],
) -> BoolRef | None:
    if fact.get("enabled", True) is False:
        return None
    if fact.get("type") in _EXTENSIONS:
        return _extension_expr(fact, world, seats)
    return _proposition_expr(
        fact.get("proposition"),
        world,
        seats,
        claimed=fact.get("status") == "reported",
    )


def _proposition_expr(
    proposition: Any,
    world: TroubleBrewingVars,
    seats: dict[str, int],
    *,
    claimed: bool,
) -> BoolRef | None:
    if not isinstance(proposition, dict):
        return None
    player = seats.get(proposition.get("player_id"))
    if player is None:
        raise ValueError(f"未知玩家 {proposition.get('player_id')}")
    time = proposition.get("time") or {"phase": "setup"}
    kind = proposition.get("kind")
    if kind == "role":
        role = _role(proposition.get("role_id"))
        if claimed:
            return _belief_bit(world, player, role, time)
        return _role_bit(world, player, role, time)
    if kind == "alignment":
        roles = EVIL_ROLES if proposition.get("alignment") == "evil" else GOOD_ROLES
        return Or([_role_bit(world, player, role, time) for role in roles])
    return None


def _extension_expr(
    fact: dict[str, Any],
    world: TroubleBrewingVars,
    seats: dict[str, int],
) -> BoolRef | None:
    data = fact.get("data") or {}
    fact_type = fact.get("type")
    if fact_type == _NIGHT_DEATHS:
        return _night_deaths(world, seats, data)
    if fact_type == _DAY_VOTE:
        return _execution(world, seats, data)
    if fact_type == _OBSERVATION:
        return _ability(world, seats, data)
    return None


def _night_deaths(
    world: TroubleBrewingVars,
    seats: dict[str, int],
    data: dict[str, Any],
) -> BoolRef | None:
    time = data.get("time") or {}
    if time.get("phase") != "night":
        return None
    night = time.get("number")
    if not isinstance(night, int) or night < 2:
        return None
    dead = {seats[player_id] for player_id in data.get("player_ids") or []}
    if data.get("result") == "none":
        dead = set()
    return And(
        [
            world.night_death[night][player] if player in dead else Not(world.night_death[night][player])
            for player in world.player_ids
        ]
    )


def _execution(
    world: TroubleBrewingVars,
    seats: dict[str, int],
    data: dict[str, Any],
) -> BoolRef | None:
    if data.get("stage") != "settled":
        return None
    time = data.get("time") or {}
    if time.get("phase") != "day":
        return None
    day = time.get("number")
    if not isinstance(day, int) or day < 1:
        return None
    execution = data.get("execution") or {}
    chosen = execution.get("player_id")
    chosen_index = None if chosen is None else seats[chosen]
    return And(
        [
            world.executed[day][player]
            if player == chosen_index
            else Not(world.executed[day][player])
            for player in world.player_ids
        ]
    )


def _ability(
    world: TroubleBrewingVars,
    seats: dict[str, int],
    data: dict[str, Any],
) -> BoolRef | None:
    result = data.get("result") or {}
    if result.get("kind") == "unobserved":
        return None
    try:
        role = _role(data.get("role_id"))
    except ValueError:
        return None
    actor = seats.get(data.get("actor_id"))
    if actor is None:
        return None
    targets = [seats[player_id] for player_id in data.get("targets") or [] if player_id in seats]
    time = data.get("time") or {}
    phase = time.get("phase")
    number = time.get("number") if isinstance(time.get("number"), int) else None
    if role is Role.WASHERWOMAN and phase == "night" and number == 1 and len(targets) == 2:
        shown = _role(result.get("role_id"))
        return And(
            world.washerwoman_role[actor][shown],
            world.washerwoman_first[actor][targets[0]],
            world.washerwoman_second[actor][targets[1]],
        )
    if role is Role.LIBRARIAN and result.get("kind") == "no_outsiders":
        return world.librarian_none[actor]
    if role is Role.LIBRARIAN and phase == "night" and number == 1 and len(targets) == 2:
        shown = _role(result.get("role_id"))
        return And(
            world.librarian_role[actor][shown],
            world.librarian_first[actor][targets[0]],
            world.librarian_second[actor][targets[1]],
        )
    if role is Role.INVESTIGATOR and phase == "night" and number == 1 and len(targets) == 2:
        shown = _role(result.get("role_id"))
        return And(
            world.investigator_role[actor][shown],
            world.investigator_first[actor][targets[0]],
            world.investigator_second[actor][targets[1]],
        )
    if role is Role.CHEF and result.get("kind") == "number":
        return world.chef_number[actor][int(result["value"])]
    if role is Role.EMPATH and phase == "night" and number is not None and result.get("kind") == "number":
        return world.empath_number[number][actor][int(result["value"])]
    if role is Role.FORTUNE_TELLER and phase == "night" and number is not None and len(targets) == 2:
        answer = result.get("value")
        if answer not in {"yes", "no"}:
            return None
        return And(
            world.fortune_first[number][actor][targets[0]],
            world.fortune_second[number][actor][targets[1]],
            world.fortune_yes[number][actor] if answer == "yes" else Not(world.fortune_yes[number][actor]),
        )
    if role is Role.UNDERTAKER and phase == "night" and isinstance(number, int) and number >= 2:
        return world.undertaker_role[number][actor][_role(result.get("role_id"))]
    if role is Role.MONK and phase == "night" and isinstance(number, int) and number >= 2 and targets:
        return world.monk_choice[number][targets[0]]
    if role is Role.POISONER and phase == "night" and isinstance(number, int) and targets:
        return world.poison_choice[number][targets[0]]
    if role is Role.IMP and phase == "night" and isinstance(number, int) and number >= 2 and targets:
        choice = world.imp_choice[number][targets[0]]
        if result.get("value") == "died":
            return And(choice, world.night_death[number][targets[0]])
        return choice
    if role is Role.BUTLER and phase == "night" and isinstance(number, int) and targets:
        return world.butler_master[number][targets[0]]
    if role is Role.SLAYER and phase == "day" and isinstance(number, int) and targets:
        shot = world.ability_target[Ability.SLAYER][number][actor][targets[0]]
        if result.get("value") == "died":
            return And(shot, world.slayer_kill[number][targets[0]])
        return shot
    if role is Role.RAVENKEEPER and phase == "night" and isinstance(number, int) and number >= 2 and targets:
        return And(
            world.ability_target[Ability.RAVENKEEPER][number][actor][targets[0]],
            world.ravenkeeper_role[number][actor][_role(result.get("role_id"))],
        )
    return None


def _role(role_id: Any) -> Role:
    if not isinstance(role_id, str):
        raise ValueError(f"未知角色：{role_id}")
    return role_from_name(role_id)


def _role_bit(world: TroubleBrewingVars, player: int, role: Role, time: dict[str, Any]) -> BoolRef:
    phase = time.get("phase")
    if phase in (None, "setup"):
        return world.start_is(player, role)
    number = int(time["number"])
    if phase == "night":
        return world.is_role(player, role, Moment.DAWN, number)
    return world.role_after_day(number, player, role)


def _belief_bit(world: TroubleBrewingVars, player: int, role: Role, time: dict[str, Any]) -> BoolRef:
    phase = time.get("phase")
    if phase in (None, "setup"):
        return world.believes_at_start(player, role)
    number = int(time["number"])
    if phase == "night":
        return world.believed_role(player, role, Moment.DAWN, number)
    if number < world.n_nights:
        return world.believed_night_start[number + 1][player][role]
    return world.believed_end[player][role]


def _setup_model(solver: Solver, world: TroubleBrewingVars, game: dict[str, Any]) -> list[dict[str, Any]]:
    model = solver.model()
    assignments = []
    for player in game.get("players") or []:
        index = player["seat"] - 1
        role = next(
            candidate
            for candidate in Role
            if is_true(model.eval(world.start_is(index, candidate), model_completion=True))
        )
        assignments.append(
            {
                "player_id": player["id"],
                "role_id": role.value,
                "alignment": "evil" if role in EVIL_ROLES else "good",
                "time": {"phase": "setup"},
            }
        )
    return assignments


def _possible_roles(solver: Solver, world: TroubleBrewingVars, game: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for player in game.get("players") or []:
        index = player["seat"] - 1
        roles: list[str] = []
        solver.push()
        while solver.check() == sat:
            model = solver.model()
            role = next(
                candidate
                for candidate in Role
                if is_true(model.eval(world.start_is(index, candidate), model_completion=True))
            )
            roles.append(role.value)
            solver.add(Not(world.start_is(index, role)))
        solver.pop()
        rows.append({"player_id": player["id"], "seat": player["seat"], "role_ids": roles})
    return rows


def _query_result(
    solver: Solver,
    world: TroubleBrewingVars,
    game: dict[str, Any],
    query: dict[str, Any],
) -> dict[str, Any]:
    seats = _seats(list(game.get("players") or []))
    expr = _proposition_expr(query.get("proposition"), world, seats, claimed=False)
    result = {"id": query.get("id")}
    if expr is None:
        result["status"] = "unknown"
        result["reason"] = "连接器不能解释这条查询"
        return result
    positive = _assume(solver, expr)
    negative = _assume(solver, Not(expr))
    if positive == unknown or negative == unknown:
        result["status"] = "unknown"
        result["reason"] = "求解超时"
    elif positive == sat and negative == unsat:
        result["status"] = "necessary"
    elif positive == unsat and negative == sat:
        result["status"] = "impossible"
    elif positive == sat and negative == sat:
        result["status"] = "possible"
    else:
        result["status"] = "inconsistent"
    return result


def _assume(solver: Solver, expr: BoolRef):
    solver.push()
    solver.add(expr)
    status = solver.check()
    solver.pop()
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把前端推理请求交给暗流涌动求解器")
    parser.add_argument("request", nargs="?", help="协议请求 JSON 文件；省略则从标准输入读取")
    parser.add_argument("--serve", action="store_true", help="提供网页和 /api/v1/reason")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if args.request == "serve":
        args.serve = True
        args.request = None
    if args.serve:
        from backend.http_server import create_server

        server = create_server(args.host, args.port, adapter=TroubleBrewingAdapter())
        print(f"推理服务：http://{args.host}:{args.port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止", flush=True)
        return 0
    raw = sys.stdin.read() if args.request is None else open(args.request, encoding="utf-8").read()
    response = TroubleBrewingAdapter().reason(json.loads(raw))
    json.dump(response, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
