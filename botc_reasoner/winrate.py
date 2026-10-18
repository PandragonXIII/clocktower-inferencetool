"""从当前局面估计善良与邪恶的胜率。

身份样本来自 ``joint_assignment_particles``，和 ``estimate_role_probabilities`` 用同一套联合权重。
已结束的夜晚如果没有写死亡，视为无人死亡；已结束的白天如果没有写处决，视为无人被处决。
玩家编号从 0 开始。``counts`` 是男爵修正前的配置 ``(镇民, 外来者, 爪牙, 恶魔)``。

示例::

    {"n_players": 5, "counts": [3, 0, 1, 1], "phase": "day", "day": 1,
     "propositions": [
        {"reliable": false, "kind": "role", "player": 0, "role": "chef"}]}
"""

from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations

from z3 import And, Not, Solver, sat

from botc_reasoner.agent_probability import AgentReasoner
from botc_reasoner.parallel_support import (
    bind_slot,
    group_budget_for,
    map_in_order,
    slot,
    worker_count,
)
from botc_reasoner.engine import NightChoices, Report, Table
from botc_reasoner.probability import (
    AbilityObservation,
    _identity_matches,
    _resolve_drunk_mask,
    estimate_role_probabilities,
    joint_assignment_particles,
    trusted_activation,
)
from botc_reasoner.roles import (
    EVIL_ROLES,
    GOOD_ROLES,
    TOWNSFOLK,
    Alignment,
    Role,
    alignment_of,
    role_from_name,
)
from botc_reasoner.rules import ability_role, add_game_rules
from botc_reasoner.variables import Ability, TroubleBrewingVars, declare_variables

_ACTIONABLE = {
    Role.WASHERWOMAN,
    Role.LIBRARIAN,
    Role.INVESTIGATOR,
    Role.CHEF,
    Role.EMPATH,
    Role.FORTUNE_TELLER,
    Role.UNDERTAKER,
    Role.MONK,
    Role.RAVENKEEPER,
    Role.VIRGIN,
    Role.SLAYER,
    Role.SOLDIER,
    Role.MAYOR,
    Role.BUTLER,
}
_INFO = {
    Role.WASHERWOMAN,
    Role.LIBRARIAN,
    Role.INVESTIGATOR,
    Role.CHEF,
    Role.EMPATH,
    Role.FORTUNE_TELLER,
    Role.UNDERTAKER,
    Role.RAVENKEEPER,
}
_REPEAT = 0.02


@dataclass(frozen=True)
class Proposition:
    reliable: bool
    kind: str
    player: int | None = None
    role: Role | None = None
    ability: str | None = None
    when: int | None = None
    targets: tuple[int, ...] = ()
    yes: bool | None = None
    number: int | None = None
    none: bool = False
    players: tuple[int, ...] = ()


@dataclass(frozen=True)
class GameInput:
    """一场已经进行到某个阶段的暗流涌动局面。"""

    n_players: int
    counts: tuple[int, int, int, int]
    phase: str
    day: int
    night: int
    propositions: tuple[Proposition, ...] = ()
    nominate_threshold: float = 0.6
    vote_threshold: float = 0.6

    @staticmethod
    def from_dict(data: dict) -> GameInput:
        counts = data.get("counts", data.get("setup"))
        if isinstance(counts, dict):
            counts = (
                int(counts["townsfolk"]),
                int(counts["outsider"] if "outsider" in counts else counts["outsiders"]),
                int(counts["minion"] if "minion" in counts else counts["minions"]),
                int(counts["demon"] if "demon" in counts else counts["demons"]),
            )
        else:
            counts = tuple(int(item) for item in counts)
        phase = str(data.get("phase", "day"))
        day = int(data.get("day", 1 if phase == "day" else 0))
        night = int(data.get("night", day if phase == "day" else 1))
        props = tuple(_proposition(item) for item in data.get("propositions", ()))
        return GameInput(
            n_players=int(data["n_players"]),
            counts=(int(counts[0]), int(counts[1]), int(counts[2]), int(counts[3])),
            phase=phase,
            day=day,
            night=night,
            propositions=props,
            nominate_threshold=float(data.get("nominate_threshold", 0.6)),
            vote_threshold=float(data.get("vote_threshold", 0.6)),
        )


@dataclass(frozen=True)
class WinRates:
    good: float
    evil: float
    samples: int
    weight: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "good": self.good,
            "evil": self.evil,
            "samples": self.samples,
            "weight": self.weight,
        }


@dataclass
class Mind:
    player: int
    believed: Role
    private: list[Report] = field(default_factory=list)
    published: set[tuple] = field(default_factory=set)
    claimed: Role | None = None
    cover: dict = field(default_factory=dict)
    info_uses: dict[tuple, int] = field(default_factory=dict)


def estimate_win_rates(
    state: GameInput,
    *,
    samples: int = 8,
    seed: int = 0,
    horizon: int | None = None,
    attempts: int = 24,
    agent_samples: int = 40,
    agent_trials: int = 80,
) -> WinRates:
    """对局面做加权采样并模拟，返回两个阵营的胜率。"""

    if state.phase not in {"day", "night"}:
        raise ValueError("phase 只能是 day 或 night")
    if sum(state.counts) != state.n_players:
        raise ValueError("身份数量之和必须等于玩家人数")
    if samples <= 0:
        raise ValueError("samples 必须为正")
    horizon = state.n_players if horizon is None else horizon
    nights = _history_nights(state)
    world = declare_variables(state.n_players, n_nights=nights, tag=f"win{seed}")
    solver = world.build_solver()
    add_game_rules(solver, world, *state.counts)
    _pin_public_history(solver, world, state)
    particles = joint_assignment_particles(
        state.n_players,
        state.counts,
        beliefs=_beliefs(state),
        pinned_roles=_reliable_roles(state),
        soft_roles=_soft_roles(state),
        soft_abilities=_soft_observations(world, state),
        solver=solver,
        world=world,
        seed=seed,
        target_accepted=max(samples, 4),
        max_trials=max(samples * 40, 80),
    )
    if not particles:
        raise RuntimeError("在已知信息下没有合法的身份分配")
    rng = random.Random(seed)
    drawn = _draw_particles(rng, particles, samples)
    good = 0.0
    evil = 0.0
    used = 0.0
    accepted = 0
    bind_slot(
        drawn=drawn,
        seed=seed,
        state=state,
        world=world,
        solver=solver,
        attempts=attempts,
        horizon=horizon,
        agent_samples=agent_samples,
        agent_trials=agent_trials,
    )
    world_workers = worker_count(len(drawn))
    outcomes = map_in_order(
        _run_drawn_world,
        list(range(len(drawn))),
        world_workers,
        child_budget=group_budget_for(world_workers),
    )
    for _index, good_mass, evil_mass, used_mass, accepted_flag in sorted(outcomes):
        good += good_mass
        evil += evil_mass
        used += used_mass
        accepted += accepted_flag
    if used <= 0.0:
        raise RuntimeError("采样都与已知死亡或技能声明矛盾，没有可模拟的世界")
    return WinRates(good / used, evil / used, accepted, used)


def _run_drawn_world(index: int) -> tuple[int, float, float, float, int]:
    """推演一个已经抽好的隐藏世界。随机种子只由世界编号决定。"""

    data = slot()
    bag, role_weight, trusted = data["drawn"][index]
    seed = data["seed"]
    realized = None
    for trial in range(data["attempts"]):
        trial_rng = random.Random(seed + 10007 * (index + 1) + trial)
        realized = _realize(
            data["state"],
            data["world"],
            data["solver"],
            bag,
            trusted,
            role_weight,
            trial_rng,
        )
        if realized is not None:
            break
    if realized is None:
        return index, 0.0, 0.0, 0.0, 0
    table, minds, weight, bluffs = realized
    if table.winner is None:
        _play(
            table,
            minds,
            bluffs,
            data["state"],
            data["world"],
            data["solver"],
            random.Random(seed + 50021 * (index + 1)),
            data["horizon"],
            data["agent_samples"],
            data["agent_trials"],
        )
    if table.winner == "good":
        return index, weight, 0.0, weight, 1
    if table.winner == "evil":
        return index, 0.0, weight, weight, 1
    return index, 0.0, 0.0, 0.0, 0


def _play(
    table: Table,
    minds: list[Mind],
    bluffs: tuple[Role, ...],
    state: GameInput,
    world: TroubleBrewingVars,
    solver: Solver,
    rng: random.Random,
    horizon: int,
    agent_samples: int,
    agent_trials: int,
) -> None:
    public_roles = list(_soft_roles(state))
    public_reports = list(_ability_reports(state))
    solver.push()
    try:
        session = AgentReasoner(
            solver,
            world,
            table.n,
            state.counts,
            target_accepted=agent_samples,
            max_trials=agent_trials,
        )
        for mind in minds:
            if not _evil(table, mind.player) and mind.claimed is None:
                mind.claimed = mind.believed
                public_roles.append((mind.player, mind.believed))
        while table.winner is None and table.night <= horizon and table.day <= horizon:
            phase, night, day = table.phase, table.night, table.day
            if table.phase == "day":
                _day(
                    table, minds, bluffs, public_roles, public_reports, state, session, rng,
                )
            else:
                _night(
                    table, minds, public_roles, public_reports, state, session, rng,
                )
            _note_transition(session, table, phase, night, day)
            _sync_minds(table, minds, bluffs)
    finally:
        solver.pop()


def _day(
    table, minds, bluffs, public_roles, public_reports, state, session, rng,
) -> None:
    for mind in minds:
        if _evil(table, mind.player):
            _evil_announce(table, mind, bluffs, public_roles, public_reports, rng)
        else:
            _good_share(mind, public_roles, public_reports)
    estimates = {
        mind.player: _estimate(
            table, mind, public_roles, public_reports, state, session, rng,
        )
        for mind in minds
        if table.alive[mind.player]
    }
    for mind in minds:
        if table.alive[mind.player] and mind.believed is Role.SLAYER and not table.slayer_used[mind.player]:
            target = _good_target(estimates.get(mind.player), table, state.nominate_threshold)
            if target is not None and not _evil(table, mind.player):
                table.slay(mind.player, target)
                if table.winner:
                    return
    nominations: list[tuple[int, int]] = []
    nominated: set[int] = set()
    nominators: set[int] = set()
    for player in range(table.n):
        if not table.alive[player] or player in nominators:
            continue
        if _evil(table, player):
            options = [seat for seat in table.alive_ids() if seat not in table.teammates_of(player)]
            options = [seat for seat in options if seat not in nominated] or options
            if not options:
                continue
            target = rng.choice(options)
        else:
            target = _good_target(estimates.get(player), table, state.nominate_threshold)
            if target is None or target in nominated:
                continue
        nominations.append((player, target))
        nominators.add(player)
        nominated.add(target)
    votes: dict[int, dict[int, bool]] = defaultdict(dict)
    for _nominator, nominee in nominations:
        for voter in range(table.n):
            if _evil(table, voter):
                votes[nominee][voter] = _nominator_of(nominations, nominee) in table.teammates_of(voter)
            else:
                probs = estimates.get(voter) or _estimate(
                    table, minds[voter], public_roles, public_reports, state, session, rng,
                )
                votes[nominee][voter] = _evil_probability(probs, nominee) > state.vote_threshold
    table.resolve_day(nominations, votes)


def _night(
    table, minds, public_roles, public_reports, state, session, rng,
) -> None:
    choices = NightChoices()
    estimates: dict[int, list[dict[Role, float]] | None] = {}

    def probs(player: int):
        if player not in estimates:
            estimates[player] = _estimate(
                table, minds[player], public_roles, public_reports, state, session, rng,
            )
        return estimates[player]

    poisoner = table._find(Role.POISONER)
    if poisoner is not None and table.alive[poisoner]:
        choices.poison = _harm(table, poisoner, probs(poisoner), rng)
    monk = table._find(Role.MONK)
    if table.night > 1 and monk is not None and table.alive[monk]:
        choices.monk = _help(table, monk, probs(monk), rng, avoid=table.last_monk)
    imp = table._find(Role.IMP)
    if table.night > 1 and imp is not None and table.alive[imp]:
        choices.imp = _harm(table, imp, probs(imp), rng)
    fortune = table._find(Role.FORTUNE_TELLER)
    if fortune is not None and table.alive[fortune]:
        choices.fortune = _info_pair(table, minds[fortune], probs(fortune), rng)
    raven = table._find(Role.RAVENKEEPER)
    if table.night > 1 and raven is not None and table.alive[raven]:
        choices.ravenkeeper = _info_one(table, minds[raven], probs(raven), rng)
    butler = table._find(Role.BUTLER)
    if butler is not None and table.alive[butler]:
        choices.butler = _help(table, butler, probs(butler), rng, avoid=None)
    for player, mind in enumerate(minds):
        if table.roles[player] is Role.DRUNK and table.alive[player]:
            _drunk_imagine(table, mind, probs(player), rng)
    learned = table.resolve_night(choices)
    for report in learned:
        minds[report.actor].private.append(report)


def _good_share(mind: Mind, public_roles: list[tuple[int, Role]], public_reports: list[Report]) -> None:
    if mind.claimed is None:
        mind.claimed = mind.believed
        public_roles.append((mind.player, mind.believed))
    for report in mind.private:
        key = (report.actor, report.ability, report.when, report.targets)
        if key in mind.published:
            continue
        mind.published.add(key)
        public_reports.append(report)


def _evil_announce(table, mind, bluffs, public_roles, public_reports, rng) -> None:
    if mind.claimed is None:
        towns = [role for role in bluffs if role in TOWNSFOLK]
        mind.claimed = rng.choice(towns or list(bluffs) or list(TOWNSFOLK))
        public_roles.append((mind.player, mind.claimed))
    role = mind.claimed
    nights = range(1, table.day + (1 if table.phase == "day" else 0))
    for night in nights:
        if not _role_acts(role, night):
            continue
        key = (role, night)
        if key in mind.cover:
            continue
        report = _fake_report(table, mind, role, night, rng)
        mind.cover[key] = report
        public_reports.append(report)


def _fake_report(table, mind, role: Role, night: int, rng: random.Random) -> Report:
    actor = mind.player
    known_demons = {player for player in table.teammates_of(actor) if table.roles[player] is Role.IMP}
    if table.roles[actor] is Role.IMP:
        known_demons.add(actor)
    if role is Role.FORTUNE_TELLER:
        pool = [player for player in range(table.n) if player != actor]
        pairs = [pair for pair in combinations(pool, 2) if mind.info_uses.get(tuple(sorted(pair)), 0) < 2]
        if not pairs:
            pairs = list(combinations(pool, 2))
        rng.shuffle(pairs)
        chosen = pairs[0]
        for pair in pairs:
            if mind.info_uses.get(tuple(sorted(pair)), 0) == 0:
                chosen = pair
                break
        pair = tuple(sorted(chosen))
        mind.info_uses[pair] = mind.info_uses.get(pair, 0) + 1
        yes = False if (mind_is_minion(table, actor) and any(player in known_demons for player in pair)) else rng.random() < 0.5
        stored = mind.cover.get(("fortune", pair))
        if stored is not None:
            yes = stored
        else:
            mind.cover[("fortune", pair)] = yes
        return Report(actor, "fortune_teller", night, pair, yes=yes)
    if role is Role.EMPATH:
        if any(_adjacent(actor, demon, table.n) for demon in known_demons) and mind_is_minion(table, actor):
            number = 0
        else:
            number = int(mind.cover.get(("empath", night), rng.randrange(3)))
        mind.cover[("empath", night)] = number
        return Report(actor, "empath", night, (), number=number)
    if role is Role.CHEF:
        number = int(mind.cover.get(("chef", 1), rng.randrange(table.n + 1)))
        mind.cover[("chef", 1)] = number
        return Report(actor, "chef", night, (), number=number)
    if role in {Role.WASHERWOMAN, Role.LIBRARIAN, Role.INVESTIGATOR}:
        ability = role.value
        stored = mind.cover.get((ability, 1))
        if stored is not None:
            return stored
        pool = [player for player in range(table.n) if player != actor and player not in known_demons]
        if len(pool) < 2:
            pool = [player for player in range(table.n) if player != actor]
        pair = tuple(sorted(rng.sample(pool, 2)))
        catalog = {
            Role.WASHERWOMAN: TOWNSFOLK,
            Role.LIBRARIAN: tuple(role for role in Role if role in GOOD_ROLES and role not in TOWNSFOLK),
            Role.INVESTIGATOR: tuple(role for role in EVIL_ROLES if role is not Role.IMP),
        }[role]
        shown = rng.choice(list(catalog))
        report = Report(actor, ability, night, pair, role=shown)
        mind.cover[(ability, 1)] = report
        return report
    if role is Role.MONK:
        options = [player for player in table.alive_ids() if player != actor]
        target = rng.choice(options or table.alive_ids())
        return Report(actor, "monk", night, (target,))
    if role is Role.BUTLER:
        options = [player for player in table.alive_ids() if player != actor]
        target = rng.choice(options or [actor])
        return Report(actor, "butler", night, (target,))
    if role is Role.UNDERTAKER:
        shown = rng.choice(list(TOWNSFOLK))
        return Report(actor, "undertaker", night, (), role=shown)
    return Report(actor, role.value, night)


def _harm(table: Table, actor: int, probs, rng: random.Random) -> int:
    legal = [player for player in table.alive_ids() if player not in _true_evil(table) or player == actor]
    legal = [player for player in legal if player != actor or table.roles[actor] is Role.IMP]
    if table.roles[actor] is Role.POISONER:
        legal = [player for player in table.alive_ids() if player not in _true_evil(table)]
    if not legal:
        legal = table.alive_ids()
    if table.evil(actor):
        weights = [_actionable_good(probs, player) for player in legal]
        if sum(weights) <= 0:
            return rng.choice(legal)
        return rng.choices(legal, weights=weights, k=1)[0]
    return max(legal, key=lambda player: _evil_probability(probs, player))


def _help(table, actor, probs, rng, avoid: int | None) -> int | None:
    options = [player for player in table.alive_ids() if player != actor and player != avoid]
    if not options:
        return None
    if table.evil(actor):
        friends = [player for player in options if player in table.teammates_of(actor)]
        return rng.choice(friends or options)
    return max(options, key=lambda player: _good_probability(probs, player))


def _info_one(table, mind: Mind, probs, rng: random.Random) -> int | None:
    options = [player for player in range(table.n) if player != mind.player]
    fresh = [player for player in options if mind.info_uses.get((player,), 0) == 0]
    once = [player for player in options if mind.info_uses.get((player,), 0) == 1]
    if fresh:
        chosen = min(fresh, key=lambda player: abs(_evil_probability(probs, player) - 0.5))
    elif once and rng.random() < _REPEAT:
        chosen = min(once, key=lambda player: abs(_evil_probability(probs, player) - 0.5))
    else:
        return None
    mind.info_uses[(chosen,)] = mind.info_uses.get((chosen,), 0) + 1
    return chosen


def _info_pair(table, mind: Mind, probs, rng: random.Random) -> tuple[int, int] | None:
    pool = [player for player in table.alive_ids() if player != mind.player]
    pairs = list(combinations(pool, 2))
    if not pairs:
        return None
    fresh = [pair for pair in pairs if mind.info_uses.get(tuple(sorted(pair)), 0) == 0]
    once = [pair for pair in pairs if mind.info_uses.get(tuple(sorted(pair)), 0) == 1]
    if fresh:
        chosen = min(fresh, key=lambda pair: _pair_score(probs, pair))
    elif once and rng.random() < _REPEAT:
        chosen = min(once, key=lambda pair: _pair_score(probs, pair))
    else:
        return None
    key = tuple(sorted(chosen))
    mind.info_uses[key] = mind.info_uses.get(key, 0) + 1
    return key


def _drunk_imagine(table, mind, probs, rng) -> None:
    role = mind.believed
    if not _role_acts(role, table.night):
        return
    if any(report.when == table.night and report.ability == role.value for report in mind.private):
        return
    report = _fake_report(table, mind, role, table.night, rng)
    mind.private.append(report)


def _estimate(table, mind, public_roles, public_reports, state, session: AgentReasoner, rng):
    pinned = list(_reliable_roles(state))
    if _evil(table, mind.player):
        if table.n >= 7:
            pinned.extend((player, table.roles[player]) for player in table.teammates_of(mind.player))
        else:
            pinned.append((mind.player, table.roles[mind.player]))
        if table.roles[mind.player] is Role.SPY:
            pinned = [(player, table.roles[player]) for player in range(table.n)]
    beliefs = [] if _evil(table, mind.player) else [(mind.player, mind.believed)]
    return session.estimate(
        beliefs=beliefs,
        pinned_roles=pinned,
        soft_roles=public_roles,
        soft_abilities=_observations(session.world, public_reports),
        private_abilities=_observations(session.world, mind.private),
        seed=rng.randrange(1_000_000_000),
    )


def _realize(state, world, solver, bag, trusted, role_weight, rng):
    own_beliefs = _beliefs(state)
    feasible, mask, fixed = _resolve_drunk_mask(bag, (*own_beliefs, *trusted), tuple(trusted))
    if not feasible:
        return None
    factor = 1.0
    if not fixed:
        options = [role for role in TOWNSFOLK if role not in bag]
        if Role.DRUNK in bag and not options:
            return None
        if Role.DRUNK in bag:
            mask = rng.choice(options)
            factor /= len(options)
    herring = None
    if Role.FORTUNE_TELLER in bag:
        goods = [player for player, role in enumerate(bag) if role in GOOD_ROLES]
        herring = rng.choice(goods)
    bluffs = _bluff_tokens(bag, mask, rng)
    table = Table(
        roles=list(bag),
        alive=[True] * len(bag),
        drunk_mask=mask,
        red_herring=herring,
        bluffs=bluffs,
        rng=rng,
        night=1,
        day=0,
        phase="night",
        fixed_registration=True,
    )
    recorded: list[tuple[int, NightChoices]] = []
    reports = _ability_reports(state)
    nights = _completed_nights(state)
    days = _completed_days(state)
    privates: list[list[Report]] = [[] for _ in bag]
    for night in nights:
        sampled = _sample_historical(table, night, bag, mask, reports, _deaths(state, night), rng)
        if sampled is None:
            return None
        choices, piece = sampled
        factor *= piece
        before = set(table.alive_ids())
        learned = table.resolve_night(choices)
        recorded.append((night, choices))
        died = before - set(table.alive_ids())
        if night >= 2 and died != _deaths(state, night):
            return None
        if night == 1 and died:
            return None
        if not _claims_match(table, bag, mask, reports, learned):
            return None
        _store(privates, bag, mask, reports, learned, night)
        if night in days:
            for player in _executions(state, night):
                if table.alive[player]:
                    table._kill(player)
                    table._on_executed(player)
            if table.winner:
                break
            table.phase = "night"
            table.night += 1
            table.poisoned = set()
            table.executed_today = False
        else:
            break
    if not _z3_accepts(solver, world, bag, mask, herring, recorded, reports, state):
        return None
    table.fixed_registration = False
    minds = _blank_minds(table)
    for player, items in enumerate(privates):
        minds[player].private.extend(items)
    return table, minds, role_weight * factor, bluffs


def _sample_historical(table, night, bag, mask, reports, required: set[int], rng):
    factor = 1.0
    choices = NightChoices()
    poisoner = table._find(Role.POISONER)
    if poisoner is not None and table.alive[poisoner]:
        claim = _matched(bag, mask, reports, poisoner, "poisoner", night)
        if claim and claim.targets:
            choices.poison = claim.targets[0]
        else:
            options = [player for player in table.alive_ids() if not table.evil(player)]
            if len(required) == 1:
                victim = next(iter(required))
                if table.roles[victim] is Role.SOLDIER and victim in options:
                    options = [victim]
            if not options:
                options = [player for player in table.alive_ids() if player != poisoner]
            if not options:
                return None
            choices.poison = rng.choice(options)
            factor /= len(options)
    if night > 1:
        monk = table._find(Role.MONK)
        if monk is not None and table.alive[monk]:
            claim = _matched(bag, mask, reports, monk, "monk", night)
            blocked = set(required)
            if claim and claim.targets:
                choices.monk = claim.targets[0]
            else:
                options = [
                    player
                    for player in table.alive_ids()
                    if player != monk and player != table.last_monk and player not in blocked
                ]
                if not options:
                    options = [player for player in table.alive_ids() if player != monk]
                if options:
                    choices.monk = rng.choice(options)
                    factor /= len(options)
        imp = table._find(Role.IMP)
        if imp is not None and table.alive[imp]:
            claim = _matched(bag, mask, reports, imp, "imp", night)
            if claim and claim.targets:
                choices.imp = claim.targets[0]
                choices.bounce = -1
            else:
                picked = _pick_imp(table, imp, required, choices.monk)
                if picked is None:
                    return None
                target, bounce, piece = picked
                choices.imp = target
                choices.bounce = bounce
                factor *= piece
        if required and table._find(Role.RAVENKEEPER) in required:
            raven = table._find(Role.RAVENKEEPER)
            claim = _matched(bag, mask, reports, raven, "ravenkeeper", night) if raven is not None else None
            if claim and claim.targets:
                choices.ravenkeeper = claim.targets[0]
            else:
                options = list(range(table.n))
                choices.ravenkeeper = rng.choice(options)
                factor /= len(options)
    fortune = table._find(Role.FORTUNE_TELLER)
    if fortune is not None and table.alive[fortune]:
        claim = _matched(bag, mask, reports, fortune, "fortune_teller", night)
        if claim and len(claim.targets) == 2:
            choices.fortune = tuple(sorted(claim.targets))
        else:
            pool = [player for player in table.alive_ids() if player != fortune]
            pairs = list(combinations(pool, 2))
            if pairs:
                choices.fortune = tuple(sorted(rng.choice(pairs)))
                factor /= len(pairs)
    butler = table._find(Role.BUTLER)
    if butler is not None and table.alive[butler]:
        claim = _matched(bag, mask, reports, butler, "butler", night)
        if claim and claim.targets:
            choices.butler = claim.targets[0]
        else:
            options = [player for player in table.alive_ids() if player != butler]
            if options:
                choices.butler = rng.choice(options)
                factor /= len(options)
    return choices, factor


def _pick_imp(table, imp, required: set[int], monk_target: int | None):
    if table.droisoned(imp):
        if required:
            return None
        options = [player for player in table.alive_ids() if not table.evil(player)] or table.alive_ids()
        return options[0], -1, 1.0 / len(options)
    if not required:
        soldiers = [
            player
            for player in table.alive_ids()
            if table.roles[player] is Role.SOLDIER and not table.droisoned(player)
        ]
        if soldiers:
            return soldiers[0], -1, 1.0 / len(soldiers)
        monk = table._find(Role.MONK)
        if (
            monk_target is not None
            and monk is not None
            and table.alive[monk_target]
            and not table.droisoned(monk)
        ):
            return monk_target, -1, 1.0
        return None
    if len(required) != 1:
        return None
    victim = next(iter(required))
    if victim == imp:
        return imp, -1, 1.0
    if victim not in table.alive_ids() or table.evil(victim):
        return None
    if table.roles[victim] is Role.SOLDIER and not table.droisoned(victim):
        return None
    monk = table._find(Role.MONK)
    if monk_target == victim and monk is not None and not table.droisoned(monk):
        return None
    return victim, -1, 1.0


def _claims_match(table, bag, mask, reports, learned: list[Report]) -> bool:
    by_key = {(item.actor, item.ability, item.when): item for item in learned}
    for report in reports:
        role = ability_role(Ability(report.ability)) if _known_ability(report.ability) else None
        if role is None or not _identity_matches(bag, mask, report.actor, role):
            continue
        got = by_key.get((report.actor, report.ability, report.when))
        if got is None:
            continue
        if table.droisoned(report.actor):
            continue
        if not _reports_agree(report, got):
            return False
    return True


def _store(privates: list[list[Report]], bag, mask, reports, learned: list[Report], night: int) -> None:
    consumed = set()
    for report in reports:
        if report.when != night or not _known_ability(report.ability):
            continue
        role = ability_role(Ability(report.ability))
        if not _identity_matches(bag, mask, report.actor, role):
            continue
        privates[report.actor].append(report)
        consumed.add((report.actor, report.ability, report.when))
    for report in learned:
        if (report.actor, report.ability, report.when) in consumed:
            continue
        privates[report.actor].append(report)


def _z3_accepts(solver, world, bag, mask, herring, recorded, reports, state) -> bool:
    solver.push()
    try:
        for player, role in enumerate(bag):
            solver.add(world.start_is(player, role))
        if mask is None:
            for role in TOWNSFOLK:
                solver.add(Not(world.drunk_mask[role]))
        else:
            solver.add(world.drunk_mask[mask])
        if herring is None:
            for player in world.player_ids:
                solver.add(Not(world.red_herring[player]))
        else:
            solver.add(world.red_herring[herring])
        for night, choices in recorded:
            if choices.poison is not None:
                solver.add(world.poison_choice[night][choices.poison])
            if choices.monk is not None and night in world.monk_choice:
                solver.add(world.monk_choice[night][choices.monk])
            if choices.imp is not None and night in world.imp_choice:
                solver.add(world.imp_choice[night][choices.imp])
            if choices.butler is not None:
                solver.add(world.butler_master[night][choices.butler])
            if choices.fortune is not None:
                actor = next(player for player, role in enumerate(bag) if role is Role.FORTUNE_TELLER)
                first, second = choices.fortune
                solver.add(world.ability_used[Ability.FORTUNE_TELLER][night][actor])
                solver.add(world.fortune_first[night][actor][first])
                solver.add(world.fortune_second[night][actor][second])
            if night >= 2:
                _pin_group(solver, world.night_death[night], _deaths(state, night))
            if choices.bounce is not None and choices.bounce >= 0 and night in world.mayor_bounce:
                solver.add(world.mayor_bounce[night][choices.bounce])
            elif choices.bounce == -1 and night in world.mayor_bounce:
                for player in world.player_ids:
                    solver.add(Not(world.mayor_bounce[night][player]))
        for report in reports:
            if not _known_ability(report.ability):
                continue
            role = ability_role(Ability(report.ability))
            if _identity_matches(bag, mask, report.actor, role):
                observation = _observation(world, report)
                if observation is not None:
                    solver.add(observation.claim)
        for day in _completed_days(state):
            _pin_group(solver, world.executed[day], _executions(state, day))
        return solver.check() == sat
    finally:
        solver.pop()


def _pin_public_history(solver: Solver, world: TroubleBrewingVars, state: GameInput) -> None:
    for player, role in _reliable_roles(state):
        solver.add(world.start_is(player, role))
    for night in _completed_nights(state):
        if night < 2:
            continue
        _pin_group(solver, world.night_death[night], _deaths(state, night))
    for day in _completed_days(state):
        _pin_group(solver, world.executed[day], _executions(state, day))
        for player in world.player_ids:
            solver.add(Not(world.slayer_kill[day][player]))


def _pin_group(solver, bits: dict[int, object], chosen: set[int]) -> None:
    for player, bit in bits.items():
        solver.add(bit if player in chosen else Not(bit))


def _observations(world: TroubleBrewingVars, reports) -> list[AbilityObservation]:
    found = []
    for report in reports:
        if not _known_ability(report.ability):
            continue
        observation = _observation(world, report)
        if observation is not None:
            found.append(observation)
    return found


def _observation(world: TroubleBrewingVars, report: Report) -> AbilityObservation | None:
    ability = Ability(report.ability)
    actor = report.actor
    when = report.when
    if when not in world.ability_used[ability]:
        return None
    bits = [world.ability_used[ability][when][actor]]
    target = report.targets[0] if len(report.targets) == 1 else None
    if ability is Ability.FORTUNE_TELLER and len(report.targets) == 2:
        first, second = report.targets
        bits.append(world.fortune_first[when][actor][first])
        bits.append(world.fortune_second[when][actor][second])
        if report.yes is True:
            bits.append(world.fortune_yes[when][actor])
        elif report.yes is False:
            bits.append(Not(world.fortune_yes[when][actor]))
    elif ability is Ability.EMPATH and report.number is not None:
        bits.append(world.empath_number[when][actor][report.number])
    elif ability is Ability.CHEF and report.number is not None:
        bits.append(world.chef_number[actor][report.number])
    elif ability is Ability.WASHERWOMAN and report.role is not None and len(report.targets) == 2:
        bits.append(world.washerwoman_role[actor][report.role])
        bits.append(world.washerwoman_first[actor][report.targets[0]])
        bits.append(world.washerwoman_second[actor][report.targets[1]])
    elif ability is Ability.LIBRARIAN and report.none:
        bits.append(world.librarian_none[actor])
    elif ability is Ability.LIBRARIAN and report.role is not None and len(report.targets) == 2:
        bits.append(world.librarian_role[actor][report.role])
        bits.append(world.librarian_first[actor][report.targets[0]])
        bits.append(world.librarian_second[actor][report.targets[1]])
    elif ability is Ability.INVESTIGATOR and report.none:
        bits.append(world.investigator_none[actor])
    elif ability is Ability.INVESTIGATOR and report.role is not None and len(report.targets) == 2:
        bits.append(world.investigator_role[actor][report.role])
        bits.append(world.investigator_first[actor][report.targets[0]])
        bits.append(world.investigator_second[actor][report.targets[1]])
    elif ability is Ability.UNDERTAKER and report.role is not None:
        bits.append(world.undertaker_role[when][actor][report.role])
    elif ability is Ability.RAVENKEEPER and report.role is not None and report.targets:
        bits.append(world.ability_target[ability][when][actor][report.targets[0]])
        bits.append(world.ravenkeeper_role[when][actor][report.role])
    elif target is not None and ability in world.ability_target:
        bits.append(world.ability_target[ability][when][actor][target])
    return AbilityObservation(actor, ability, when, And(*bits), target)


def _blank_minds(table: Table) -> list[Mind]:
    minds = []
    for player, role in enumerate(table.roles):
        believed = table.drunk_mask if role is Role.DRUNK and table.drunk_mask is not None else role
        minds.append(Mind(player, believed))
    return minds


def _sync_minds(table: Table, minds: list[Mind], bluffs: tuple[Role, ...]) -> None:
    del bluffs
    for player, mind in enumerate(minds):
        role = table.roles[player]
        if role is Role.DRUNK:
            continue
        if alignment_of(role) is Alignment.EVIL:
            mind.believed = role


def _good_target(probs, table: Table, threshold: float) -> int | None:
    if not probs:
        return None
    ranked = []
    for player in table.alive_ids():
        evil_p = _evil_probability(probs, player)
        if evil_p <= threshold:
            continue
        modal = max(probs[player], key=probs[player].get)
        ranked.append((player, evil_p, probs[player].get(Role.IMP, 0.0), modal is Role.IMP))
    demons = [item for item in ranked if item[3]]
    pool = demons or ranked
    if not pool:
        return None
    if demons:
        pool.sort(key=lambda item: item[2], reverse=True)
    else:
        pool.sort(key=lambda item: item[1], reverse=True)
    return pool[0][0]


def _evil_probability(probs, player: int) -> float:
    if not probs:
        return 0.0
    return sum(probs[player].get(role, 0.0) for role in EVIL_ROLES)


def _good_probability(probs, player: int) -> float:
    if not probs:
        return 0.0
    return sum(probs[player].get(role, 0.0) for role in GOOD_ROLES)


def _actionable_good(probs, player: int) -> float:
    if not probs:
        return 0.0
    return sum(probs[player].get(role, 0.0) for role in _ACTIONABLE)


def _pair_score(probs, pair: tuple[int, int]) -> float:
    return abs(_evil_probability(probs, pair[0]) - 0.5) + abs(_evil_probability(probs, pair[1]) - 0.5)


def _true_evil(table: Table) -> set[int]:
    return {player for player in range(table.n) if table.evil(player)}


def _evil(table: Table, player: int) -> bool:
    return table.evil(player)


def mind_is_minion(table: Table, player: int) -> bool:
    return table.roles[player] in EVIL_ROLES and table.roles[player] is not Role.IMP


def _role_acts(role: Role, night: int) -> bool:
    if role in {Role.WASHERWOMAN, Role.LIBRARIAN, Role.INVESTIGATOR, Role.CHEF}:
        return night == 1
    if role in {Role.MONK, Role.UNDERTAKER, Role.IMP}:
        return night > 1
    if role in {Role.EMPATH, Role.FORTUNE_TELLER, Role.BUTLER, Role.POISONER}:
        return True
    return False


def _adjacent(left: int, right: int, n: int) -> bool:
    return (left - right) % n in {1, n - 1}


def _nominator_of(nominations, nominee: int) -> int:
    for nominator, target in nominations:
        if target == nominee:
            return nominator
    return -1


def _note_transition(session: AgentReasoner, table: Table, phase: str, night: int, day: int) -> None:
    """一个阶段结算后，把新的公开存活写进智能体的求解器。"""

    if table.phase == "day" and phase == "night":
        session.observe_alive("dawn", night, table.alive)
    elif table.phase == "night" and phase == "day":
        session.observe_alive("night_start", table.night, table.alive)
    del day


def _history_nights(state: GameInput) -> int:
    """求解器需要覆盖的夜数：已经发生的夜，以及输入里出现过的技能时间。"""

    seen = [state.day if state.phase == "day" else max(state.night, 1)]
    for item in state.propositions:
        if item.when:
            seen.append(item.when)
    return max(seen)


def _completed_nights(state: GameInput) -> list[int]:
    if state.phase == "day":
        return list(range(1, state.day + 1))
    return list(range(1, state.night))


def _completed_days(state: GameInput) -> list[int]:
    if state.phase == "day":
        return list(range(1, state.day))
    return list(range(1, state.night))


def _deaths(state: GameInput, night: int) -> set[int]:
    found = None
    for item in state.propositions:
        if item.reliable and item.kind == "night_deaths" and item.when == night:
            found = set(item.players)
    return found or set()


def _executions(state: GameInput, day: int) -> set[int]:
    found = None
    for item in state.propositions:
        if item.reliable and item.kind == "executions" and item.when == day:
            found = set(item.players)
    return found or set()


def _beliefs(state: GameInput) -> list[tuple[int, Role]]:
    """「我是」：自己看到的身份。真实身份就是它，或者是拿着这枚标记的酒鬼。"""

    return [
        (item.player, item.role)
        for item in state.propositions
        if item.kind == "belief" and item.player is not None and item.role is not None
    ]


def _reliable_roles(state: GameInput) -> list[tuple[int, Role]]:
    return [
        (item.player, item.role)
        for item in state.propositions
        if item.reliable and item.kind == "role" and item.player is not None and item.role is not None
    ]


def _soft_roles(state: GameInput) -> list[tuple[int, Role]]:
    roles: list[tuple[int, Role]] = []
    seen: set[tuple[int, Role]] = set()
    for item in state.propositions:
        if item.reliable or item.player is None:
            continue
        role = None
        if item.kind == "role":
            role = item.role
        elif item.kind == "ability" and _known_ability(item.ability):
            role = ability_role(Ability(item.ability))
        if role is None or (item.player, role) in seen:
            continue
        seen.add((item.player, role))
        roles.append((item.player, role))
    return roles


def _ability_reports(state: GameInput) -> list[Report]:
    reports = []
    for item in state.propositions:
        if item.kind != "ability" or item.player is None or item.ability is None or item.when is None:
            continue
        reports.append(
            Report(
                item.player,
                item.ability,
                item.when,
                tuple(sorted(item.targets)) if item.ability == "fortune_teller" else item.targets,
                yes=item.yes,
                number=item.number,
                role=item.role,
                none=item.none,
            )
        )
    return reports


def _known_ability(name: str | None) -> bool:
    if name is None:
        return False
    try:
        Ability(name)
    except ValueError:
        return False
    return True


def _soft_observations(world, state: GameInput) -> list[AbilityObservation]:
    return [
        observation
        for report in _ability_reports(state)
        if not _report_reliable(state, report) and _known_ability(report.ability)
        if (observation := _observation(world, report)) is not None
    ]


def _report_reliable(state: GameInput, report: Report) -> bool:
    for item in state.propositions:
        if (
            item.kind == "ability"
            and item.player == report.actor
            and item.ability == report.ability
            and item.when == report.when
        ):
            return item.reliable
    return False


def _matched(bag, mask, reports: list[Report], actor: int, ability: str, night: int) -> Report | None:
    if not _known_ability(ability):
        return None
    role = ability_role(Ability(ability))
    if not _identity_matches(bag, mask, actor, role):
        return None
    for report in reports:
        if report.actor == actor and report.ability == ability and report.when == night:
            return report
    return None


def _reports_agree(claim: Report, learned: Report) -> bool:
    if claim.none or learned.none:
        return claim.none == learned.none
    if claim.yes is not None and claim.yes != learned.yes:
        return False
    if claim.number is not None and claim.number != learned.number:
        return False
    if claim.role is not None and claim.role is not learned.role:
        return False
    if claim.targets and tuple(sorted(claim.targets)) != tuple(sorted(learned.targets)):
        return False
    return True


def _bluff_tokens(bag: tuple[Role, ...], mask: Role | None, rng: random.Random) -> tuple[Role, ...]:
    blocked = set(bag)
    if mask is not None:
        blocked.add(mask)
    towns = [role for role in TOWNSFOLK if role not in blocked]
    others = [role for role in GOOD_ROLES if role not in TOWNSFOLK and role not in blocked]
    rng.shuffle(towns)
    rng.shuffle(others)
    picked = (towns + others)[:3]
    return tuple(picked)


def _draw_particles(rng: random.Random, particles, samples: int):
    weights = [max(weight, 0.0) for _bag, weight, _trusted in particles]
    if sum(weights) <= 0:
        return particles[:samples]
    drawn = []
    pool = list(particles)
    pool_weights = list(weights)
    for _ in range(min(samples, len(pool))):
        choice = rng.choices(range(len(pool)), weights=pool_weights, k=1)[0]
        drawn.append(pool.pop(choice))
        pool_weights.pop(choice)
        if not pool:
            break
    return drawn


def _proposition(data: dict) -> Proposition:
    role = role_from_name(data["role"]) if data.get("role") else None
    players = tuple(int(player) for player in data.get("players", ()))
    targets = tuple(int(player) for player in data.get("targets", ()))
    when = data.get("when", data.get("night", data.get("day")))
    return Proposition(
        reliable=bool(data.get("reliable", False)),
        kind=str(data["kind"]),
        player=None if data.get("player") is None else int(data["player"]),
        role=role,
        ability=None if data.get("ability") is None else str(data["ability"]),
        when=None if when is None else int(when),
        targets=targets,
        yes=None if data.get("yes") is None else bool(data["yes"]),
        number=None if data.get("number") is None else int(data["number"]),
        none=bool(data.get("none", False)),
        players=players,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="估计暗流涌动当前局面的阵营胜率")
    parser.add_argument("path", nargs="?", help="局面 JSON；省略时从标准输入读取")
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--horizon", type=int, default=None)
    parser.add_argument("--agent-samples", type=int, default=40)
    parser.add_argument("--agent-trials", type=int, default=80)
    args = parser.parse_args(argv)
    raw = sys.stdin.read() if not args.path else open(args.path, encoding="utf-8").read()
    state = GameInput.from_dict(json.loads(raw))
    result = estimate_win_rates(
        state,
        samples=args.samples,
        seed=args.seed,
        horizon=args.horizon,
        agent_samples=args.agent_samples,
        agent_trials=args.agent_trials,
    )
    json.dump(result.as_dict(), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
