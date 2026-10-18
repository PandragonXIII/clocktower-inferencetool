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
from time import perf_counter
from typing import Any

from z3 import And, BoolRef, BoolVal, If, Implies, Not, Or, Solver, Sum, is_true, sat, unknown, unsat

from botc_reasoner import Role, declare_variables, role_from_name
from botc_reasoner.analysis import Budget, build_solver
from botc_reasoner.inputs import compile_inputs
from botc_reasoner.pipeline import analyze
from botc_reasoner.roles import BASE_SETUP, EVIL_ROLES, GOOD_ROLES, OUTSIDERS, TOWNSFOLK
from botc_reasoner.rules import collect_game_rules
from botc_reasoner.variables import Ability, Moment, TroubleBrewingVars

_OBSERVATION = "botc:ability_observation"
_NIGHT_DEATHS = "botc:night_deaths"
_DAY_VOTE = "botc:day_vote"
_GLOBAL = "botc:global_assumption"
_EXTENSIONS = {_OBSERVATION, _NIGHT_DEATHS, _DAY_VOTE, _GLOBAL}


class TroubleBrewingAdapter:
    """无状态适配器：每次请求单独建一局求解器。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def capabilities(self) -> dict[str, Any]:
        return {
            "api_version": "1.0",
            "supported_fact_types": ["role", "alignment", *_EXTENSIONS],
            "query_types": ["role", "alignment"],
            "scripts": [{"id": "trouble_brewing", "name": "暗流涌动"}],
            "extensions": {"adapter:mode": "trouble_brewing"},
        }

    def reason(self, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            return _reason(request)


def _reason(request: dict[str, Any]) -> dict[str, Any]:
    game = request.get("game") or {}
    started = perf_counter()
    try:
        world, collector, inputs, seats = _prepare_context(request)
        built = perf_counter()
        response = analyze(
            request,
            world,
            collector,
            inputs,
            query_expr=lambda proposition: _proposition_expr(
                proposition, world, seats, claimed=False
            ),
            model_assignments=lambda solver: _setup_model(solver, world, game),
            projection=_projection(world, game),
        )
        analyzed = perf_counter()
        if request.get("options", {}).get("probability_mode", False):
            from botc_reasoner.probability_adapter import analyze_probabilities
            options = request.get("options", {})
            response["extensions"]["reasoner:probabilities"] = analyze_probabilities(
                request, world, collector, inputs, seats,
                Budget(options.get("probability_timeout_ms", 120000), options.get("timeout_ms", 1000)))
        finished = perf_counter()
        response["extensions"]["reasoner:timings"] = {
            "build_ms": round((built - started) * 1000, 1),
            "analysis_ms": round((analyzed - built) * 1000, 1),
            "probability_ms": round((finished - analyzed) * 1000, 1),
            "total_ms": round((finished - started) * 1000, 1),
            "excludes": ["adapter_lock_wait", "http_transport"],
        }
        return response
    except (ValueError, KeyError) as error:
        return {
            "api_version": "1.0",
            "request_id": request.get("request_id"),
            "game_id": game.get("id"),
            "revision": game.get("revision"),
            "consistency": "unknown",
            "reason": str(error),
            "results": [
                {"id": query.get("id"), "status": "unknown", "reason": str(error)}
                for query in request.get("queries") or []
                if isinstance(query, dict)
            ],
            "extensions": {"adapter:mode": "trouble_brewing"},
        }


def _prepare_context(
    request: dict[str, Any],
) -> tuple[TroubleBrewingVars, Any, list[Any], dict[str, int]]:
    """一次建好世界、规则收集器与编译后的输入，供 :func:`analyze` 使用。"""

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
    collector = collect_game_rules(world, *BASE_SETUP[count])
    inputs = compile_inputs(request, world, seats, _fact_expr, _proposition_expr)
    return world, collector, inputs, seats


def _prepare(request: dict[str, Any]) -> tuple[TroubleBrewingVars, Solver, list[tuple[BoolRef, str]]]:
    """旧测试用接口：在 :func:`_prepare_context` 之上装规则与域公理，不装输入。"""

    world, collector, inputs, _seats_map = _prepare_context(request)
    solver = build_solver(list(world.encoding_axioms()), collector.records)
    propositions = [(item.expr, item.id) for item in inputs]
    return world, solver, propositions


def _projection(world: TroubleBrewingVars, game: dict[str, Any]) -> list[tuple[str, list[tuple[str, BoolRef]]]]:
    """初始投影：每位玩家在每个 :class:`Role` 上的 ``start_is``。"""

    return [
        (
            player["id"],
            [(role.value, world.start_is(player["seat"] - 1, role)) for role in Role],
        )
        for player in game.get("players") or []
    ]


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
            if collection != "queries" and item.get("enabled", True) is False:
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
    if fact_type == _GLOBAL:
        if data.get("kind") != "role_absent":
            raise ValueError("未知全局假设")
        role = _role(data["role_id"])
        return And([Not(_role_bit(world, player, role, data["time"])) for player in world.player_ids])
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
    if night == 1:
        return BoolVal(not data.get("player_ids"))
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
    time = data.get("time") or {}
    if time.get("phase") != "day":
        return None
    day = time.get("number")
    if not isinstance(day, int) or day < 1:
        return None
    execution = data.get("execution") or {}
    chosen = execution.get("player_id")
    chosen_index = None if chosen is None else seats[chosen]
    constraints = []
    nominations = data.get("nominations", [])
    if len(nominations) > world.max_nominations:
        raise ValueError("提名数量超过当日模型槽数")
    for index, nomination in enumerate(nominations, 1):
        constraints.extend([world.nomination_happened[day][index],
                            world.nominator[day][index][seats[nomination["nominator_id"]]],
                            world.nominee[day][index][seats[nomination["nominee_id"]]]])
        voters = set(nomination["voter_ids"])
        constraints.extend(world.voted[day][index][player] if pid in voters
                           else Not(world.voted[day][index][player]) for pid, player in seats.items())
    # Only settled records are complete: unfinished voting leaves later slots unknown.
    if data.get("stage") != "settled":
        return And(constraints)
    if "nominations" in data:
        constraints.extend(Not(world.nomination_happened[day][index])
                           for index in world.nomination_ids if index > len(nominations))
    if "alive_count" in data:
        constraints.append(Sum([If(world.alive_dawn[day][p], 1, 0) for p in world.player_ids]) == data["alive_count"])
    constraints.append(And(
        [
            world.executed[day][player]
            if player == chosen_index
            else Not(world.executed[day][player])
            for player in world.player_ids
        ]
    ))
    return And(constraints)


def _ability(
    world: TroubleBrewingVars,
    seats: dict[str, int],
    data: dict[str, Any],
) -> BoolRef | None:
    result = data.get("result") or {}
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
    if result.get("kind") == "unobserved":
        if role in {Role.SLAYER, Role.IMP} and targets:
            return world.ability_target[Ability(role.value)][number][actor][targets[0]]
        return None

    def targeted(ability, actual):
        claim = world.ability_target[ability][number][actor][targets[0]]
        healthy_actor = And(world.role_night_start[number][actor][role],
                            world.alive_night_start[number][actor], Not(world.is_droisoned(actor, number)))
        return And(claim, Implies(healthy_actor, actual))
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
        observed = world.undertaker_role[number][actor][_role(result.get("role_id"))]
        return And(observed, world.executed[number - 1][targets[0]]) if targets else observed
    if role is Role.MONK and phase == "night" and isinstance(number, int) and number >= 2 and targets:
        return targeted(Ability.MONK, world.monk_choice[number][targets[0]])
    if role is Role.POISONER and phase == "night" and isinstance(number, int) and targets:
        return targeted(Ability.POISONER, world.poison_choice[number][targets[0]])
    if role is Role.IMP and phase == "night" and isinstance(number, int) and number >= 2 and targets:
        choice = targeted(Ability.IMP, world.imp_choice[number][targets[0]])
        if result.get("value") == "died":
            return And(choice, world.night_death[number][targets[0]])
        return And(choice, Not(world.night_death[number][targets[0]]))
    if role is Role.BUTLER and phase == "night" and isinstance(number, int) and targets:
        return targeted(Ability.BUTLER, world.butler_master[number][targets[0]])
    if role is Role.SLAYER and phase == "day" and isinstance(number, int) and targets:
        shot = world.ability_target[Ability.SLAYER][number][actor][targets[0]]
        if result.get("value") == "died":
            return And(shot, world.slayer_kill[number][targets[0]])
        return And(shot, Not(world.slayer_kill[number][targets[0]]))
    if role is Role.RAVENKEEPER and phase == "night" and isinstance(number, int) and number >= 2 and targets:
        return And(
            world.ability_target[Ability.RAVENKEEPER][number][actor][targets[0]],
            world.ravenkeeper_role[number][actor][_role(result.get("role_id"))],
        )
    if role is Role.DRUNK and result.get("kind") == "role":
        return And(world.is_drunk[actor], world.drunk_mask[_role(result["role_id"])])
    if role is Role.BARON and result.get("kind") == "number":
        return Sum([If(world.start_is(p, r), 1, 0) for p in world.player_ids for r in OUTSIDERS]) == result["value"]
    if role is Role.SOLDIER:
        alive = world.alive_dawn[number][actor] if phase == "night" else world.alive_after_day(number, actor)
        return Not(alive) if result.get("value") == "died" else alive
    if role is Role.SCARLET_WOMAN:
        before = world.role_night_start[number][actor][Role.SCARLET_WOMAN] if phase == "night" else world.role_dawn[number][actor][Role.SCARLET_WOMAN]
        changed = And(before, _role_bit(world, actor, Role.IMP, time))
        return Not(changed) if result.get("value") == "not_occurred" else changed
    if role is Role.MAYOR:
        if result.get("value") == "suspected_redirect":
            # Suspicion does not assert a hidden cause or target.
            return None
        alive = world.alive_dawn[number] if phase == "night" else {p: world.alive_after_day(number, p) for p in world.player_ids}
        if phase != "day":
            return None
        return And(Sum([If(alive[p], 1, 0) for p in world.player_ids]) == 3,
                   *[Not(world.executed[number][p]) for p in world.player_ids])
    if role is Role.SAINT:
        # No victory-state variable exists: record the observable execution only.
        return world.executed[number][actor] if phase == "day" else None
    if role is Role.VIRGIN and phase == "day" and targets:
        nominator = targets[0]
        nominated = Or([And(world.nomination_happened[number][i],
                             world.nominator[number][i][nominator], world.nominee[number][i][actor])
                        for i in world.nomination_ids])
        executed = world.executed[number][nominator]
        return And(nominated, executed if result.get("value") == "executed" else Not(executed))
    # Free-text grimoire and unspecified registration notes carry no structured proposition.
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
    """旧单轨路径的候选角色枚举，**已不再被 :func:`_reason` 调用**。

    新管道经 :func:`botc_reasoner.pipeline.analyze` 的 ``reasoner:role_ranges`` 输出候选，
    本函数仅保留供旧调用方/测试使用，不代表当前实现的语义。
    """

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
