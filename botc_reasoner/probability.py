"""按采信组合加权，再在组内抽样。

每名有自称的玩家有可信度，默认 0.7。一个组确定哪些自称被采信。
组权重是三项的乘积：置信度 ``0.7^采信人数 × 0.3^忽略人数``；忽略人数 ``i`` 大于邪恶人数
``E`` 时再乘 ``1/3^(i-E)``。被忽略的技能信息先把写法数乘成 ``M``，再乘
``1/(1+log2(M))``。只自称身份时 ``M = 1``，乘数是 1。忽略人数不能超过 ``E + floor(G/5) - O``。

玩家是某身份的概率，等于各组里「组权重 × 该局干扰乘数」之和，再除以全部这样的乘积。
只有逻辑上没有合法世界的组才不进入分母。投毒取消当夜信息时，该夜乘
``1/当夜入夜时仍存活的善良人数``，再乘当夜写法数的 ``1/(1+log2(M))``。
酒鬼取消信息时，把他各夜的写法数合成一个 ``M``，再乘一次 ``1/(1+log2(M))``。
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations, product

from z3 import And, BoolRef, Implies, Not, Or, Solver, is_true, sat, unsat

from botc_reasoner.roles import DEMONS, EVIL_ROLES, MINIONS, OUTSIDERS, TOWNSFOLK, Role
from botc_reasoner.rules import ability_role
from botc_reasoner.variables import Ability, TroubleBrewingVars

# 其他玩家自称身份的默认可信度。采信时其技能信息也采信，但仍可能是酒鬼或中毒。
DEFAULT_PLAYER_CREDIBILITY = 0.7
# 只在旧的单句惩罚测试里保留。正式抽样按玩家可信度分组。
GOOD_CLAIM_MISMATCH = 0.05
EVIL_CLAIM_MISMATCH = 1.0 / 3.0

_SAMPLE_ACCEPTED = 500
_SAMPLE_TRIALS = 2000


@dataclass(frozen=True)
class AbilityObservation:
    """一次技能声明。`claim` 是这次声明对应的布尔式。"""

    actor: int
    ability: Ability
    when: int
    claim: BoolRef
    target: int | None = None


def trusted_activation(world: TroubleBrewingVars, observation: AbilityObservation) -> BoolRef:
    """本人发动技能时的确定前提。

    镇民技能钉住开局自认：真实身份要么就是该角色，要么是拿着这枚标记的酒鬼。
    爪牙、外来者和当夜小恶魔不能被酒鬼伪装，因此钉住真实身份。
    猎手射击是公开动作，只记录射击，不由此认定射手的身份。
    健康的小恶魔、僧侣、投毒者、管家若声明了目标，该目标就是规则里的实际选择。
    """

    claim = observation.claim
    if observation.ability is Ability.SLAYER:
        return claim
    actor = observation.actor
    when = observation.when
    role = ability_role(observation.ability)
    if observation.ability is Ability.IMP:
        is_imp = world.role_night_start[when][actor][Role.IMP]
        parts: list[BoolRef] = [claim, is_imp]
        if observation.target is not None:
            parts.append(
                Implies(
                    And(
                        is_imp,
                        world.alive_night_start[when][actor],
                        Not(world.is_droisoned(actor, when)),
                    ),
                    world.imp_choice[when][observation.target],
                )
            )
        return And(*parts)
    parts = [claim, world.believes_at_start(actor, role)]
    target = observation.target
    if target is None:
        return And(*parts)
    healthy = And(
        world.role_night_start[when][actor][role],
        world.alive_night_start[when][actor],
        Not(world.is_droisoned(actor, when)),
    )
    if observation.ability is Ability.MONK:
        parts.append(Implies(healthy, world.monk_choice[when][target]))
    elif observation.ability is Ability.POISONER:
        parts.append(Implies(healthy, world.poison_choice[when][target]))
    elif observation.ability is Ability.BUTLER:
        parts.append(Implies(healthy, world.butler_master[when][target]))
    return And(*parts)


def estimate_role_probabilities(
    n_players: int,
    counts: tuple[int, int, int, int],
    *,
    beliefs: Sequence[tuple[int, Role]] = (),
    pinned_roles: Sequence[tuple[int, Role]] = (),
    absent_roles: Sequence[Role] = (),
    drunk_players: Sequence[int] = (),
    soft_roles: Sequence[tuple[int, Role]] = (),
    soft_abilities: Sequence[AbilityObservation] = (),
    trusted_abilities: Sequence[AbilityObservation] = (),
    solver: Solver | None = None,
    world: TroubleBrewingVars | None = None,
    seed: int = 0,
    target_accepted: int | None = None,
    max_trials: int | None = None,
) -> list[dict[Role, float]] | None:
    """返回每名玩家的 ``角色 -> 概率``。没有任何可行组时返回 None。

    每名有自称的其他玩家可信度默认 0.7。分组决定采信哪些自称；
    被忽略的自称不能超过 ``E + floor(G/5) - O``。忽略数 ``i`` 大于邪恶人数时，
    该组权重再乘 ``1/3^(i-E)``。被忽略的技能信息先合并写法数 ``M``，再乘 ``1/(1+log2(M))``。
    采信后，其技能信息在清醒时必须成立。
    组内按抽样频率把这一组的权重分给每个座位。逻辑上无解的组权重为 0。
    ``trusted_abilities`` 已作为确定前提写进求解器。
    """

    particles = joint_assignment_particles(
        n_players,
        counts,
        beliefs=beliefs,
        pinned_roles=pinned_roles,
        absent_roles=absent_roles,
        drunk_players=drunk_players,
        soft_roles=soft_roles,
        soft_abilities=soft_abilities,
        solver=solver,
        world=world,
        seed=seed,
        target_accepted=target_accepted,
        max_trials=max_trials,
    )
    if not particles:
        return None
    weight_total = sum(weight for _bag, weight, _trusted in particles)
    if weight_total <= 0.0:
        return None
    totals: list[dict[Role, float]] = [{} for _ in range(n_players)]
    for bag, weight, _trusted in particles:
        for player, role in enumerate(bag):
            totals[player][role] = totals[player].get(role, 0.0) + weight
    return [
        {role: mass / weight_total for role, mass in row.items() if mass > 0.0}
        for row in totals
    ]


def joint_assignment_particles(
    n_players: int,
    counts: tuple[int, int, int, int],
    *,
    beliefs: Sequence[tuple[int, Role]] = (),
    pinned_roles: Sequence[tuple[int, Role]] = (),
    absent_roles: Sequence[Role] = (),
    drunk_players: Sequence[int] = (),
    soft_roles: Sequence[tuple[int, Role]] = (),
    soft_abilities: Sequence[AbilityObservation] = (),
    solver: Solver | None = None,
    world: TroubleBrewingVars | None = None,
    seed: int = 0,
    target_accepted: int | None = None,
    max_trials: int | None = None,
) -> list[tuple[tuple[Role, ...], float, tuple[tuple[int, Role], ...]]] | None:
    """按与 :func:`estimate_role_probabilities` 相同的联合权重返回身份样本。

    每项是 ``(座位身份, 未归一化权重, 该组采信的自称)``。权重已经乘过组权重和干扰乘数。
    """

    if n_players <= 0:
        return None
    use_solver = solver is not None and world is not None
    if target_accepted is None:
        target_accepted = _SAMPLE_ACCEPTED if use_solver else 2000
    if max_trials is None:
        max_trials = _SAMPLE_TRIALS if use_solver else 80_000
    claims = _claimed_roles(soft_roles, soft_abilities)
    groups = _credibility_groups(n_players, counts, claims, soft_abilities)
    if not groups:
        return None
    raw_total = sum(weight for _trusted, weight in groups)
    particles: list[tuple[tuple[Role, ...], float, tuple[tuple[int, Role], ...]]] = []
    for index, (trusted, group_weight) in enumerate(groups):
        share = group_weight / raw_total
        group_target = max(1, round(target_accepted * share))
        group_trials = max(1, round(max_trials * share))
        if use_solver:
            assert solver is not None and world is not None
            solver.push()
        try:
            if use_solver:
                _assert_group(
                    solver,
                    world,
                    (*beliefs, *trusted),
                    trusted,
                    soft_abilities,
                    pinned_roles,
                    absent_roles,
                    drunk_players,
                )
                if solver.check() == unsat:
                    continue
            samples: list[tuple[Role, ...]] = []
            if max_trials > 0:
                samples = _sample_worlds(
                    n_players,
                    counts,
                    beliefs=(*beliefs, *trusted),
                    pinned_roles=pinned_roles,
                    absent_roles=absent_roles,
                    drunk_players=drunk_players,
                    trusted_claims=trusted,
                    soft_abilities=soft_abilities,
                    solver=solver,
                    world=world,
                    seed=seed + index,
                    target_accepted=group_target,
                    max_trials=group_trials,
                    use_solver=use_solver,
                    claims_loaded=use_solver,
                )
            if not samples and use_solver:
                samples = _conditional_bags(
                    solver,
                    world,
                    beliefs=(*beliefs, *trusted),
                    trusted_claims=trusted,
                    soft_abilities=soft_abilities,
                    pinned_roles=pinned_roles,
                    absent_roles=absent_roles,
                    drunk_players=drunk_players,
                    seed=seed + index + 1009,
                    limit=min(16, max(8, group_target)),
                )
            if not samples:
                continue
            weighted = [
                (
                    bag,
                    _interference_factor(
                        solver,
                        world,
                        bag,
                        beliefs=(*beliefs, *trusted),
                        trusted_claims=trusted,
                        soft_abilities=soft_abilities,
                    )
                    if use_solver
                    else 1.0,
                )
                for bag in samples
            ]
            piece = group_weight / len(weighted)
            for bag, factor in weighted:
                if factor <= 0.0:
                    continue
                particles.append((bag, piece * factor, trusted))
        finally:
            if use_solver:
                solver.pop()
    if not particles:
        return None
    return particles


def _credibility_groups(
    n_players: int,
    counts: tuple[int, int, int, int],
    claims: Sequence[tuple[int, Role]],
    observations: Sequence[AbilityObservation] = (),
) -> list[tuple[tuple[tuple[int, Role], ...], float]]:
    """返回 ``(采信的自称, 组权重)``。忽略过多自称的组不出现。

    权重是置信度乘积、忽略过多善良玩家时的 ``1/3^(i-E)``，以及被忽略技能信息的 ``1/(1+log2(M))``。
    """

    _towns, _outsiders, minions, demons = counts
    evil = minions + demons
    good = n_players - evil
    claimers = list(claims)
    unclaimed = n_players - len({player for player, _role in claimers})
    ignore_limit = max(0, evil + good // 5 - unclaimed)
    groups = []
    for mask in range(1 << len(claimers)):
        trusted = tuple(claim for index, claim in enumerate(claimers) if mask & (1 << index))
        ignored_claims = [claim for claim in claimers if claim not in trusted]
        ignored = len(ignored_claims)
        if ignored > ignore_limit:
            continue
        weight = (DEFAULT_PLAYER_CREDIBILITY ** len(trusted)) * (
            (1.0 - DEFAULT_PLAYER_CREDIBILITY) ** ignored
        )
        if ignored > evil:
            weight *= (1.0 / 3.0) ** (ignored - evil)
        for player, role in ignored_claims:
            weight *= _info_multiplier(_info_options(player, role, observations, n_players))
        groups.append((trusted, weight))
    return groups


def _group_is_possible(
    solver: Solver | None,
    world: TroubleBrewingVars | None,
    *,
    beliefs: Sequence[tuple[int, Role]],
    trusted_claims: Sequence[tuple[int, Role]],
    soft_abilities: Sequence[AbilityObservation],
    pinned_roles: Sequence[tuple[int, Role]],
    absent_roles: Sequence[Role],
    drunk_players: Sequence[int],
) -> bool:
    """这组前提在酒鬼、中毒和登记方式下还有没有合法世界。"""

    if solver is None or world is None:
        return True
    solver.push()
    try:
        _assert_group(
            solver,
            world,
            beliefs,
            trusted_claims,
            soft_abilities,
            pinned_roles,
            absent_roles,
            drunk_players,
        )
        return solver.check() != unsat
    finally:
        solver.pop()


def _conditional_bags(
    solver: Solver,
    world: TroubleBrewingVars,
    *,
    beliefs: Sequence[tuple[int, Role]],
    trusted_claims: Sequence[tuple[int, Role]],
    soft_abilities: Sequence[AbilityObservation],
    pinned_roles: Sequence[tuple[int, Role]],
    absent_roles: Sequence[Role],
    drunk_players: Sequence[int],
    seed: int,
    limit: int,
) -> list[tuple[Role, ...]]:
    """在组前提已经成立的世界里取若干局。拒绝抽样落空时用它保住组权重。"""

    rng = random.Random(seed)
    solver.push()
    try:
        _assert_group(
            solver,
            world,
            beliefs,
            trusted_claims,
            soft_abilities,
            pinned_roles,
            absent_roles,
            drunk_players,
        )
        found: list[tuple[Role, ...]] = []
        for _ in range(limit):
            bag = _one_conditional_bag(solver, world, beliefs, rng)
            if bag is None:
                break
            found.append(bag)
            solver.add(
                Or([Not(world.start_is(player, role)) for player, role in enumerate(bag)])
            )
        return found
    finally:
        solver.pop()


def _one_conditional_bag(
    solver: Solver,
    world: TroubleBrewingVars,
    beliefs: Sequence[tuple[int, Role]],
    rng: random.Random,
) -> tuple[Role, ...] | None:
    townsfolk_players: list[int] = []
    seen: set[int] = set()
    for player, role in beliefs:
        if role in TOWNSFOLK and player not in seen:
            seen.add(player)
            townsfolk_players.append(player)
    for prefer_split in ((True, False) if townsfolk_players else (False,)):
        solver.push()
        try:
            if prefer_split:
                if rng.random() < 0.75:
                    for player in townsfolk_players:
                        solver.add(Not(world.is_drunk[player]))
                else:
                    solver.add(world.is_drunk[rng.choice(townsfolk_players)])
            if solver.check() == unsat:
                continue
            _add_random_imp(solver, world, rng)
            if solver.check() != sat:
                continue
            bag = _read_bag(solver.model(), world)
            if bag is not None:
                return bag
        finally:
            solver.pop()
    return None


def _add_random_imp(solver: Solver, world: TroubleBrewingVars, rng: random.Random) -> None:
    order = list(world.player_ids)
    rng.shuffle(order)
    for player in order:
        solver.push()
        solver.add(world.start_is(player, Role.IMP))
        status = solver.check()
        solver.pop()
        if status == sat:
            solver.add(world.start_is(player, Role.IMP))
            return


def _read_bag(model, world: TroubleBrewingVars) -> tuple[Role, ...] | None:
    bag: list[Role] = []
    for player in world.player_ids:
        found = None
        for role in Role:
            if is_true(model.eval(world.start_is(player, role), model_completion=True)):
                found = role
                break
        if found is None:
            return None
        bag.append(found)
    if len(set(bag)) != len(bag):
        return None
    return tuple(bag)


def _assert_group(
    solver: Solver,
    world: TroubleBrewingVars,
    beliefs: Sequence[tuple[int, Role]],
    trusted_claims: Sequence[tuple[int, Role]],
    soft_abilities: Sequence[AbilityObservation],
    pinned_roles: Sequence[tuple[int, Role]],
    absent_roles: Sequence[Role],
    drunk_players: Sequence[int],
) -> None:
    for player, role in pinned_roles:
        solver.add(world.start_is(player, role))
    for player in drunk_players:
        solver.add(world.start_is(player, Role.DRUNK))
    for role in absent_roles:
        for player in world.player_ids:
            solver.add(Not(world.start_is(player, role)))
        if role in TOWNSFOLK:
            solver.add(Not(world.drunk_mask[role]))
    for player, role in beliefs:
        if role is Role.DRUNK:
            solver.add(world.start_is(player, Role.DRUNK))
        else:
            solver.add(world.believes_at_start(player, role))
    trusted = set(trusted_claims)
    for observation in soft_abilities:
        if observation.ability is Ability.SLAYER:
            continue
        if (observation.actor, ability_role(observation.ability)) not in trusted:
            continue
        solver.add(observation.claim)


def _interference_factor(
    solver: Solver | None,
    world: TroubleBrewingVars | None,
    bag: tuple[Role, ...],
    *,
    beliefs: Sequence[tuple[int, Role]],
    trusted_claims: Sequence[tuple[int, Role]],
    soft_abilities: Sequence[AbilityObservation],
) -> float:
    """这一局里，干扰刚好使被采信的信息失效的概率。

    投毒只取消当夜：该夜乘 ``1/入夜存活善良人数``，再乘当夜写法数的 ``1/(1+log2(M))``。
    酒鬼取消他的全部信息：各夜写法数合成一个 ``M``，再乘一次 ``1/(1+log2(M))``。
    红鲱鱼整局只有一名善良玩家：乘上仍能解释全部清醒占卜结果的善良玩家比例。
    洗衣妇、图书管理员、调查员的信息若清醒属实，陪衬人数与在场该类角色人数
    先相乘，再取 ``1/(1+log2(...))``。
    """

    if solver is None or world is None:
        return 1.0
    mask = _mask_of(bag, beliefs, trusted_claims)
    matched = _matched_abilities(bag, mask, trusted_claims, soft_abilities)
    speakers: dict[int, list[int]] = {}
    for observation in matched:
        if bag[observation.actor] is Role.DRUNK:
            continue
        if observation.when not in world.poisoned or observation.when not in world.alive_dawn:
            continue
        night_speakers = speakers.setdefault(observation.when, [])
        if observation.actor not in night_speakers:
            night_speakers.append(observation.actor)
    drunk_factor = _drunk_info_factor(bag, matched, len(bag))
    if not speakers:
        return drunk_factor
    choices = [[(night, None), *((night, actor) for actor in actors)] for night, actors in speakers.items()]
    plans = sorted(
        product(*choices),
        key=lambda plan: sum(actor is not None for _night, actor in plan),
    )
    best: int | None = None
    factor = 1.0
    for plan in plans:
        cost = sum(actor is not None for _night, actor in plan)
        if best is not None and cost > best:
            break
        poisoned = {(night, actor) for night, actor in plan if actor is not None}
        plan_factor = _poison_plan_factor(
            solver, world, bag, beliefs, trusted_claims, soft_abilities, speakers, poisoned
        )
        if plan_factor is None:
            continue
        best = cost
        factor = plan_factor
        break
    if best is None:
        return drunk_factor
    return factor * drunk_factor


def _mask_of(
    bag: tuple[Role, ...],
    beliefs: Sequence[tuple[int, Role]],
    trusted_claims: Sequence[tuple[int, Role]],
) -> Role | None:
    _feasible, mask, _fixed = _resolve_drunk_mask(bag, beliefs, trusted_claims)
    return mask


def _poison_plan_factor(
    solver: Solver,
    world: TroubleBrewingVars,
    bag: tuple[Role, ...],
    beliefs: Sequence[tuple[int, Role]],
    trusted_claims: Sequence[tuple[int, Role]],
    soft_abilities: Sequence[AbilityObservation],
    speakers: dict[int, list[int]],
    poisoned: set[tuple[int, int]],
) -> float | None:
    """这个投毒方案若成立，返回各夜选人概率和当夜信息乘数的乘积。"""

    feasible, mask, mask_fixed = _resolve_drunk_mask(bag, beliefs, trusted_claims)
    if not feasible:
        return None
    solver.push()
    try:
        _pin_bag(solver, world, bag, mask, mask_fixed)
        for observation in _matched_abilities(bag, mask, trusted_claims, soft_abilities):
            solver.add(observation.claim)
        for night, actors in speakers.items():
            for actor in actors:
                solver.add(world.alive_dawn[night][actor])
                if (night, actor) in poisoned:
                    solver.add(world.poisoned[night][actor])
                else:
                    solver.add(Not(world.poisoned[night][actor]))
        if solver.check() != sat:
            return None
        matched = _matched_abilities(bag, mask, trusted_claims, soft_abilities)
        factor = 1.0
        for night, actor in poisoned:
            alive = _max_alive_good(solver, world, bag, night)
            if alive <= 0:
                return 0.0
            factor /= alive
            factor *= _voided_info_factor(
                [
                    observation
                    for observation in matched
                    if observation.actor == actor and observation.when == night
                ],
                len(bag),
            )
        factor *= _healthy_decoy_factor(bag, matched, poisoned, world)
        factor *= _red_herring_factor(solver, world, bag)
        return factor
    finally:
        solver.pop()


def _max_alive_good(
    solver: Solver,
    world: TroubleBrewingVars,
    bag: tuple[Role, ...],
    night: int,
) -> int:
    """在已经写好的前提下，这一夜入夜时最多能有多少善良玩家同时存活。"""

    good = [
        player
        for player, role in enumerate(bag)
        if role in TOWNSFOLK or role in OUTSIDERS
    ]
    for size in range(len(good), 0, -1):
        for subset in combinations(good, size):
            solver.push()
            try:
                for player in subset:
                    solver.add(world.alive_night_start[night][player])
                if solver.check() == sat:
                    return size
            finally:
                solver.pop()
    return 0


def _red_herring_factor(solver: Solver, world: TroubleBrewingVars, bag: tuple[Role, ...]) -> float:
    """红鲱鱼在全部善良玩家中选取，且整局是同一人。返回仍符合占卜结果的比例。"""

    if not any(role is Role.FORTUNE_TELLER for role in bag):
        return 1.0
    good = [
        player
        for player, role in enumerate(bag)
        if role in TOWNSFOLK or role in OUTSIDERS
    ]
    if not good:
        return 0.0
    eligible = 0
    for player in good:
        solver.push()
        try:
            solver.add(world.red_herring[player])
            if solver.check() == sat:
                eligible += 1
        finally:
            solver.pop()
    return eligible / len(good)


_DECOY_CATEGORIES = {
    Ability.WASHERWOMAN: TOWNSFOLK,
    Ability.LIBRARIAN: OUTSIDERS,
    Ability.INVESTIGATOR: MINIONS,
}


def _healthy_decoy_factor(
    bag: tuple[Role, ...],
    matched: Sequence[AbilityObservation],
    poisoned: set[tuple[int, int]],
    world: TroubleBrewingVars,
) -> float:
    """清醒属实的洗衣妇、图书管理员、调查员：陪衬和展示哪一个在场角色。"""

    n_players = len(bag)
    if n_players <= 1:
        return 1.0
    factor = 1.0
    for observation in matched:
        category = _DECOY_CATEGORIES.get(observation.ability)
        if category is None or bag[observation.actor] is Role.DRUNK:
            continue
        if (observation.when, observation.actor) in poisoned or _is_none_report(observation, world):
            continue
        choices = max(n_players - 1, 1)
        present = sum(role in category for role in bag)
        if present > 0:
            choices *= present
        factor *= _info_multiplier(choices)
    return factor


def _is_none_report(observation: AbilityObservation, world: TroubleBrewingVars) -> bool:
    actor = observation.actor
    if observation.ability is Ability.LIBRARIAN:
        return observation.claim.get_id() == world.librarian_none[actor].get_id()
    if observation.ability is Ability.INVESTIGATOR:
        return observation.claim.get_id() == world.investigator_none[actor].get_id()
    return False


def _drunk_info_factor(
    bag: tuple[Role, ...],
    matched: Sequence[AbilityObservation],
    n_players: int,
) -> float:
    """酒鬼整局信息作废，各夜写法数合成一个 ``M`` 后乘一次。"""

    factor = 1.0
    seen: set[int] = set()
    for observation in matched:
        if bag[observation.actor] is not Role.DRUNK or observation.actor in seen:
            continue
        seen.add(observation.actor)
        factor *= _voided_info_factor(
            [item for item in matched if item.actor == observation.actor],
            n_players,
        )
    return factor


def _voided_info_factor(observations: Sequence[AbilityObservation], n_players: int) -> float:
    options = 1
    for observation in observations:
        if observation.ability is Ability.SLAYER:
            continue
        options *= _ability_option_count(observation.ability, n_players)
    return _info_multiplier(options)


def _sample_worlds(
    n_players: int,
    counts: tuple[int, int, int, int],
    *,
    beliefs: Sequence[tuple[int, Role]],
    pinned_roles: Sequence[tuple[int, Role]],
    absent_roles: Sequence[Role],
    drunk_players: Sequence[int],
    trusted_claims: Sequence[tuple[int, Role]],
    soft_abilities: Sequence[AbilityObservation],
    solver: Solver | None,
    world: TroubleBrewingVars | None,
    seed: int,
    target_accepted: int,
    max_trials: int,
    use_solver: bool,
    claims_loaded: bool = False,
) -> list[tuple[Role, ...]]:
    rng = random.Random(seed)
    accepted: list[tuple[Role, ...]] = []
    trials = 0
    while len(accepted) < target_accepted and trials < max_trials:
        trials += 1
        if beliefs:
            drawn = _draw_with_beliefs(rng, n_players, counts, beliefs)
        else:
            drawn = draw_setup(rng, n_players, counts)
        if drawn is None:
            continue
        bag, preset_mask = drawn
        feasible, mask, mask_fixed = _resolve_drunk_mask(bag, beliefs, trusted_claims)
        if not feasible:
            continue
        if not _matches_setup(bag, mask, beliefs, pinned_roles, absent_roles, drunk_players):
            continue
        if use_solver:
            assert solver is not None and world is not None
            solver.push()
            try:
                _pin_bag(solver, world, bag, mask, mask_fixed)
                if solver.check() != sat:
                    continue
                # 组前提里已经有技能声明时，不必再加一遍。
                if not claims_loaded:
                    for observation in _matched_abilities(bag, mask, trusted_claims, soft_abilities):
                        solver.add(observation.claim)
                    if solver.check() != sat:
                        continue
            finally:
                solver.pop()
        accepted.append(bag)
    return accepted


def _draw_with_beliefs(
    rng: random.Random,
    n_players: int,
    counts: tuple[int, int, int, int],
    beliefs: Sequence[tuple[int, Role]],
) -> tuple[tuple[Role, ...], Role | None] | None:
    """在自认已经被锁定的前提下抽一局合法座位。镇民自认最多有一人改由酒鬼承担。"""

    belief: dict[int, Role] = {}
    for player, role in beliefs:
        if player in belief and belief[player] is not role:
            return None
        belief[player] = role
    townsfolk_count, outsider_count, minion_count, demon_count = counts
    forced_minions = {role for role in belief.values() if role in MINIONS}
    if len(forced_minions) > minion_count:
        return None
    minion_pool = [role for role in MINIONS if role not in forced_minions]
    if minion_count - len(forced_minions) > len(minion_pool):
        return None
    minions = list(forced_minions) + rng.sample(minion_pool, minion_count - len(forced_minions))
    baron = Role.BARON in minions
    seated_townsfolk = townsfolk_count - (2 if baron else 0)
    seated_outsiders = outsider_count + (2 if baron else 0)
    if (
        seated_townsfolk < 0
        or seated_outsiders < 0
        or seated_outsiders > len(OUTSIDERS)
        or seated_townsfolk > len(TOWNSFOLK)
    ):
        return None

    townsfolk_believers = [player for player, role in belief.items() if role in TOWNSFOLK]
    claimed_drunk = [player for player, role in belief.items() if role is Role.DRUNK]
    if len(claimed_drunk) > 1:
        return None
    if claimed_drunk:
        drunk_player = claimed_drunk[0]
    elif townsfolk_believers:
        drunk_player = rng.choices(
            [None, *townsfolk_believers],
            weights=[0.75, *([0.25 / len(townsfolk_believers)] * len(townsfolk_believers))],
        )[0]
    else:
        drunk_player = None
    mask: Role | None = belief[drunk_player] if drunk_player is not None else None
    real_towns = [
        belief[player]
        for player in townsfolk_believers
        if player != drunk_player
    ]
    if len(set(real_towns)) != len(real_towns) or (mask is not None and mask in real_towns):
        return None
    if len(real_towns) > seated_townsfolk:
        return None
    town_pool = [role for role in TOWNSFOLK if role not in real_towns and role is not mask]
    if seated_townsfolk - len(real_towns) > len(town_pool):
        return None
    towns = real_towns + rng.sample(town_pool, seated_townsfolk - len(real_towns))

    forced_outsiders = {role for role in belief.values() if role in OUTSIDERS and role is not Role.DRUNK}
    if drunk_player is not None:
        forced_outsiders.add(Role.DRUNK)
    if len(forced_outsiders) > seated_outsiders:
        return None
    outsider_pool = [role for role in OUTSIDERS if role not in forced_outsiders]
    if seated_outsiders - len(forced_outsiders) > len(outsider_pool):
        return None
    outsiders = list(forced_outsiders) + rng.sample(outsider_pool, seated_outsiders - len(forced_outsiders))

    forced_demons = {role for role in belief.values() if role in DEMONS}
    if len(forced_demons) > demon_count:
        return None
    demon_pool = [role for role in DEMONS if role not in forced_demons]
    if demon_count - len(forced_demons) > len(demon_pool):
        return None
    demons = list(forced_demons) + rng.sample(demon_pool, demon_count - len(forced_demons))

    tokens = towns + outsiders + minions + demons
    if len(tokens) != n_players or len(set(tokens)) != n_players:
        return None
    seat: list[Role | None] = [None] * n_players
    used: set[Role] = set()
    for player, role in belief.items():
        seated = Role.DRUNK if player == drunk_player else role
        if seated in used or seated not in tokens:
            return None
        seat[player] = seated
        used.add(seated)
    rest_tokens = [token for token in tokens if token not in used]
    rest_seats = [index for index, role in enumerate(seat) if role is None]
    if len(rest_tokens) != len(rest_seats):
        return None
    rng.shuffle(rest_tokens)
    for index, token in zip(rest_seats, rest_tokens):
        seat[index] = token
    if any(role is None for role in seat):
        return None
    return tuple(role for role in seat if role is not None), mask


def draw_setup(
    rng: random.Random,
    n_players: int,
    counts: tuple[int, int, int, int],
) -> tuple[tuple[Role, ...], Role | None] | None:
    """按「先爪牙、再外来者、再镇民」抽取座位上的身份。

    抽不出合法袋子时返回 None。酒鬼的自认面具不在这里抽，返回的面具恒为 None。
    """

    townsfolk_count, outsider_count, minion_count, demon_count = counts
    if (
        minion_count < 0
        or demon_count < 0
        or minion_count > len(MINIONS)
        or demon_count > len(DEMONS)
    ):
        return None
    minions = rng.sample(list(MINIONS), minion_count)
    baron = Role.BARON in minions
    seated_townsfolk = townsfolk_count - (2 if baron else 0)
    seated_outsiders = outsider_count + (2 if baron else 0)
    if (
        seated_townsfolk < 0
        or seated_outsiders < 0
        or seated_outsiders > len(OUTSIDERS)
        or seated_townsfolk > len(TOWNSFOLK)
    ):
        return None
    outsiders = rng.sample(list(OUTSIDERS), seated_outsiders)
    townsfolk = rng.sample(list(TOWNSFOLK), seated_townsfolk)
    demons = rng.sample(list(DEMONS), demon_count)
    bag = townsfolk + outsiders + minions + demons
    if len(bag) != n_players or len(set(bag)) != n_players:
        return None
    rng.shuffle(bag)
    return tuple(bag), None


def _claimed_roles(
    soft_roles: Sequence[tuple[int, Role]],
    soft_abilities: Sequence[AbilityObservation],
) -> list[tuple[int, Role]]:
    claimed: list[tuple[int, Role]] = []
    seen: set[tuple[int, Role]] = set()
    for player, role in soft_roles:
        if (player, role) not in seen:
            seen.add((player, role))
            claimed.append((player, role))
    for observation in soft_abilities:
        if observation.ability is Ability.SLAYER:
            continue
        item = (observation.actor, ability_role(observation.ability))
        if item not in seen:
            seen.add(item)
            claimed.append(item)
    return claimed


def _matches_setup(
    bag: tuple[Role, ...],
    mask: Role | None,
    beliefs: Sequence[tuple[int, Role]],
    pinned_roles: Sequence[tuple[int, Role]],
    absent_roles: Sequence[Role],
    drunk_players: Sequence[int],
) -> bool:
    for player, role in pinned_roles:
        if bag[player] is not role:
            return False
    for player in drunk_players:
        if bag[player] is not Role.DRUNK:
            return False
    for role in absent_roles:
        if role in bag or (role in TOWNSFOLK and mask is role):
            return False
    for player, role in beliefs:
        if _presented_role(bag, mask, player) is not role:
            return False
    return True


def _presented_role(bag: tuple[Role, ...], mask: Role | None, player: int) -> Role | None:
    """善良玩家用真实身份；酒鬼用自认的镇民标记。"""

    if bag[player] is Role.DRUNK:
        return mask
    return bag[player]


def _claim_weight(
    bag: tuple[Role, ...],
    mask: Role | None,
    claims: Sequence[tuple[int, Role]],
    observations: Sequence[AbilityObservation] = (),
    n_players: int = 0,
) -> float:
    weight = 1.0
    for player, role in claims:
        if _identity_matches(bag, mask, player, role):
            continue
        options = _info_options(player, role, observations, n_players or len(bag))
        base = EVIL_CLAIM_MISMATCH if bag[player] in EVIL_ROLES else GOOD_CLAIM_MISMATCH
        weight *= base / options
    return weight


def _info_multiplier(options: int) -> float:
    """被忽略技能信息的乘数。同一人的写法数先合并为 ``M``，再取 ``1/(1+log2(M))``。"""

    if options <= 1:
        return 1.0
    return 1.0 / (1.0 + math.log2(options))


def _info_options(
    player: int,
    role: Role,
    observations: Sequence[AbilityObservation],
    n_players: int,
) -> int:
    """这名玩家就该身份说出的技能信息有多少种写法。没有技能信息时为 1。"""

    options = 1
    for observation in observations:
        if observation.actor != player or observation.ability is Ability.SLAYER:
            continue
        if ability_role(observation.ability) is not role:
            continue
        options *= _ability_option_count(observation.ability, n_players)
    return options


def _ability_option_count(ability: Ability, n_players: int) -> int:
    pairs = n_players * (n_players - 1) // 2
    if ability is Ability.EMPATH:
        return 3
    if ability is Ability.CHEF:
        return n_players + 1
    if ability is Ability.FORTUNE_TELLER:
        return pairs * 2
    if ability is Ability.INVESTIGATOR:
        return len(MINIONS) * pairs
    if ability is Ability.WASHERWOMAN:
        return len(TOWNSFOLK) * pairs
    if ability is Ability.LIBRARIAN:
        return 1 + len(OUTSIDERS) * pairs
    if ability is Ability.UNDERTAKER:
        return len(Role)
    if ability is Ability.RAVENKEEPER:
        return n_players * len(Role)
    if ability in {Ability.MONK, Ability.POISONER, Ability.IMP, Ability.BUTLER, Ability.SLAYER}:
        return n_players
    return 1


def _resolve_drunk_mask(
    bag: tuple[Role, ...],
    beliefs: Sequence[tuple[int, Role]],
    claims: Sequence[tuple[int, Role]],
) -> tuple[bool, Role | None, bool]:
    """确定酒鬼面具。返回 ``(可行, 面具, 是否钉死)``。

    没有酒鬼时钉死为「没有面具」。酒鬼若被确定或自称了一名镇民，面具就是该镇民，
    且这名镇民不能已经坐在座位上。没有镇民自认时，面具留给求解器。
    """

    drunks = [player for player, role in enumerate(bag) if role is Role.DRUNK]
    if not drunks:
        return True, None, True
    player = drunks[0]
    named = [
        role
        for owner, role in (*beliefs, *claims)
        if owner == player and role in TOWNSFOLK
    ]
    if not named:
        return True, None, False
    if len(set(named)) != 1 or named[0] in bag:
        return False, None, False
    return True, named[0], True


def _identity_matches(
    bag: tuple[Role, ...],
    mask: Role | None,
    player: int,
    role: Role,
) -> bool:
    if bag[player] is Role.DRUNK:
        if role is Role.DRUNK:
            return True
        if role not in TOWNSFOLK:
            return False
        return mask is role
    return bag[player] is role


def _matched_abilities(
    bag: tuple[Role, ...],
    mask: Role | None,
    claims: Sequence[tuple[int, Role]],
    observations: Sequence[AbilityObservation],
) -> list[AbilityObservation]:
    matched = {
        (player, role)
        for player, role in claims
        if _identity_matches(bag, mask, player, role)
    }
    return [
        observation
        for observation in observations
        if observation.ability is not Ability.SLAYER
        and (observation.actor, ability_role(observation.ability)) in matched
    ]


def _pin_bag(
    solver: Solver,
    world: TroubleBrewingVars,
    bag: tuple[Role, ...],
    mask: Role | None,
    mask_fixed: bool,
) -> None:
    for player, role in enumerate(bag):
        solver.add(world.start_is(player, role))
    if not mask_fixed:
        return
    if mask is None:
        for role in TOWNSFOLK:
            solver.add(Not(world.drunk_mask[role]))
    else:
        solver.add(world.drunk_mask[mask])

