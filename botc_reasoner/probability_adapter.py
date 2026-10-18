"""Estimate under public facts, weighting alternative conditional premises."""

from itertools import product

from .analysis import build_solver, check_scope
from .probability import AbilityObservation, ProbabilityIncomplete, estimate_role_probabilities
from .roles import BASE_SETUP
from .variables import Ability

TARGET_ACCEPTED_PER_GROUP = 2
MAX_TRIALS_PER_GROUP = 16


def analyze_probabilities(request, world, collector, inputs, seats, budget):
    inputs = list(inputs)
    public = [item for item in inputs if item.scope == "public"]
    conditional = [item for item in inputs if item.scope != "public"]
    result = {"status": "unknown", "method": "weighted_sampling", "scope": "conditional",
              "conditioning": "public_with_soft_conditional_inputs", "credibility": 0.7,
              "target_accepted_per_group": TARGET_ACCEPTED_PER_GROUP,
              "max_trials_per_group": MAX_TRIALS_PER_GROUP,
              "time": {"phase": "setup"}, "complete": False, "seed": 0, "rows": [],
              "input_ids": [item.id for item in inputs],
              "hard_input_ids": [item.id for item in public],
              "soft_input_ids": [item.id for item in conditional],
              "description": "公共信息作为硬条件，其他启用条件按归属组以可信度 0.7 采信；矛盾组合不计入估计。不是精确概率，未采样到不代表不可能。"}
    domain = list(world.encoding_axioms())
    solver = build_solver(domain, collector.records, public)
    status = check_scope(solver, budget)
    if status != "sat":
        result.update(status="inconsistent" if status == "unsat" else "unknown",
                      reason="公共背景矛盾，无法在保留公共信息时估计概率。" if status == "unsat" else budget.reason or "公共背景未判定。")
        return result
    expressions = {item.id: item.expr for item in inputs}
    observations = {}
    for fact in request.get("facts", []):
        if fact.get("type") != "botc:ability_observation" or fact["id"] not in expressions:
            continue
        data = fact["data"]
        try:
            ability = Ability(data["role_id"])
        except ValueError:
            continue
        targets = data.get("targets", [])
        observations[fact["id"]] = AbilityObservation(seats[data["actor_id"]], ability, data["time"]["number"],
                                                     expressions[fact["id"]], seats[targets[0]] if len(targets) == 1 else None)
    groups = {}
    for item in conditional:
        key = ("player", item.owner_id) if item.owner_id else ("input", item.id)
        groups.setdefault(key, []).append(item)
    grouped = list(groups.values())
    # Bounded, deterministic coverage: prioritize high-weight masks, but include
    # the public-only case first so an inconsistent all-trusted set cannot block it.
    count = len(grouped)
    if count <= 6:
        masks = sorted(product((False, True), repeat=count), key=lambda m: -sum(m))
    else:
        import random
        rng = random.Random(0)
        selected = {tuple([True] * count), tuple([False] * count)}
        while len(selected) < 64:
            selected.add(tuple(rng.random() < 0.7 for _ in range(count)))
        masks = sorted(selected, key=lambda m: (-sum(m), m))
    empty = tuple([False] * count)
    masks = [empty, *[m for m in masks if m != empty]]
    totals = [{} for _ in seats]
    total_weight = 0.0
    checked = 0
    result["groups"] = {"total": 2 ** count, "checked": 0, "estimated": 0, "complete": False}
    incomplete = None
    # Classify all visited groups before drawing: never use a solver unknown as
    # an exclusion. The shared budget still caps enumeration and estimation.
    viable = []
    for mask in masks:
        chosen = public + [item for flag, group in zip(mask, grouped) if flag for item in group]
        solver.push()
        try:
            solver.add(*[item.expr for item in chosen if item.scope != "public"])
            status = check_scope(solver, budget)
        finally:
            solver.pop()
        checked += 1
        if status == "unknown":
            incomplete = budget.reason or "采信组合检查未完成。"
            break
        if status == "sat":
            weight = 0.7 ** sum(mask) * 0.3 ** (count - sum(mask))
            viable.append((weight, chosen))
    if incomplete:
        result["reason"] = incomplete
        result["groups"]["checked"] = checked
        return result
    if len(masks) < 2 ** count:
        incomplete = "采信组合数量超过枚举上限，估计只覆盖部分组合。"
    for weight, chosen in sorted(viable, key=lambda item: -item[0]):
        solver.push()
        try:
            solver.add(*[item.expr for item in chosen if item.scope != "public"])
            probabilities = estimate_role_probabilities(
                len(seats), BASE_SETUP[len(seats)], solver=solver, world=world, seed=0,
                target_accepted=TARGET_ACCEPTED_PER_GROUP, max_trials=MAX_TRIALS_PER_GROUP,
                trusted_abilities=[observations[i.id] for i in chosen if i.id in observations], budget=budget)
        except ProbabilityIncomplete as exc:
            # Dropping a feasible group would bias the result without a known
            # mass: return unknown instead of normalizing only successful groups.
            result["reason"] = str(exc)
            result["groups"]["checked"] = checked
            return result
        finally:
            solver.pop()
        if probabilities is None:
            result["reason"] = "可行采信组合未取得样本；不能当作无解后排除。"
            result["groups"]["checked"] = checked
            return result
        result["groups"]["estimated"] += 1
        total_weight += weight
        for row, values in zip(totals, probabilities):
            for role, probability in values.items():
                row[role] = row.get(role, 0.0) + weight * probability
    if not total_weight:
        result["reason"] = "未取得可用采信组合，不代表身份不可能。"
        return result
    probabilities = [{role: value / total_weight for role, value in row.items()} for row in totals]
    result["groups"].update(checked=checked, complete=not incomplete)
    if incomplete:
        result["reason"] = incomplete
    result["status"] = "estimated"
    result["rows"] = [{"player_id": player["id"], "seat": player["seat"],
                       "probabilities": {role.value: value for role, value in probabilities[seats[player["id"]]].items()}}
                      for player in request["game"]["players"]]
    return result
