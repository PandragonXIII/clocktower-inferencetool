"""智能体用的概率估计。

分组、抽样和干扰乘数与 ``estimate_role_probabilities`` 相同，平时的概率分析仍走原函数。
这里多做四件事：组前提留在求解器里再验证身份；同一批公开信息只求解一次，
每个智能体用自己的身份和已知队友筛样本；私密读数只复查已有样本，整组都不成立才重抽该组；
硬事实（死亡、处决、存活）则在旧样本上增量复查。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from z3 import Not, Solver, sat, unsat

from botc_reasoner.parallel_support import bind_slot, map_in_order, slot, worker_count
from botc_reasoner.probability import (
    AbilityObservation,
    _SAMPLE_ACCEPTED,
    _SAMPLE_TRIALS,
    _assert_group,
    _claimed_roles,
    _conditional_bags,
    _credibility_groups,
    _interference_factor,
    _matches_setup,
    _pin_bag,
    _resolve_drunk_mask,
    _sample_worlds,
    trusted_activation,
)
from botc_reasoner.roles import Role
from botc_reasoner.rules import ability_role
from botc_reasoner.variables import TroubleBrewingVars


@dataclass
class _GroupCache:
    sat: bool
    samples: list[tuple[Role, ...]] = field(default_factory=list)
    factors: list[float] = field(default_factory=list)


class AgentReasoner:
    """一场模拟里的增量概率估计。求解器里应已装好规则和开局已知的公开事实。"""

    def __init__(
        self,
        solver: Solver,
        world: TroubleBrewingVars,
        n_players: int,
        counts: tuple[int, int, int, int],
        *,
        target_accepted: int | None = None,
        max_trials: int | None = None,
    ) -> None:
        self.solver = solver
        self.world = world
        self.n_players = n_players
        self.counts = counts
        self.target_accepted = _SAMPLE_ACCEPTED if target_accepted is None else target_accepted
        self.max_trials = _SAMPLE_TRIALS if max_trials is None else max_trials
        self.hard_rev = 0
        self._cache: dict[tuple, _GroupCache] = {}
        self._public_key: tuple | None = None
        self._public_particles: list[tuple[tuple[Role, ...], float]] = []

    def observe_alive(self, moment: str, number: int, alive: Sequence[bool]) -> None:
        """把某一黎明或某一夜开始时的存活写成硬事实，并让旧样本接受复查。"""

        frame = self.world.alive_dawn if moment == "dawn" else self.world.alive_night_start
        if number not in frame:
            return
        for player, living in enumerate(alive):
            bit = frame[number][player]
            self.solver.add(bit if living else Not(bit))
        self.hard_rev += 1
        self._public_key = None

    def estimate(
        self,
        *,
        beliefs: Sequence[tuple[int, Role]] = (),
        pinned_roles: Sequence[tuple[int, Role]] = (),
        soft_roles: Sequence[tuple[int, Role]] = (),
        soft_abilities: Sequence[AbilityObservation] = (),
        private_abilities: Sequence[AbilityObservation] = (),
        seed: int = 0,
    ) -> list[dict[Role, float]] | None:
        """返回该智能体视角下每个座位的角色概率。"""

        if len(pinned_roles) >= self.n_players and not beliefs and not private_abilities:
            pinned = dict(pinned_roles)
            if len(pinned) == self.n_players:
                bag = tuple(pinned[player] for player in range(self.n_players))
                return [{bag[player]: 1.0} for player in range(self.n_players)]
        if private_abilities:
            # 公开组已经抽过。私密读数只复查采信了该玩家的那些组。
            self._ensure_public(soft_roles, soft_abilities, seed)
            base = self._reuse_private(
                soft_roles,
                soft_abilities,
                beliefs,
                pinned_roles,
                seed,
                private_abilities,
            )
            claims = _claimed_roles(soft_roles, soft_abilities)
            kept = [
                (bag, weight)
                for bag, weight in base
                if _fits(bag, beliefs, pinned_roles, claims)
            ]
            if not kept:
                kept = self._mixture(
                    soft_roles,
                    soft_abilities,
                    beliefs,
                    pinned_roles,
                    seed + 17,
                    private_abilities,
                )
            return _marginals(self.n_players, kept)
        particles = self._ensure_public(soft_roles, soft_abilities, seed)
        claims = _claimed_roles(soft_roles, soft_abilities)
        kept = [
            (bag, weight)
            for bag, weight in particles
            if _fits(bag, beliefs, pinned_roles, claims)
        ]
        if not kept:
            kept = self._mixture(
                soft_roles,
                soft_abilities,
                beliefs,
                pinned_roles,
                seed + 17,
                (),
            )
        return _marginals(self.n_players, kept)

    def _private_holds(
        self,
        bag: tuple[Role, ...],
        beliefs: Sequence[tuple[int, Role]],
        trusted: Sequence[tuple[int, Role]],
        private_abilities: Sequence[AbilityObservation],
    ) -> bool:
        if not private_abilities:
            return True
        mark = (self.hard_rev, bag, _ability_mark(private_abilities))
        cached = getattr(self, "_private_cache", None)
        if cached is None:
            self._private_cache = {}
            cached = self._private_cache
        if mark in cached:
            return cached[mark]
        feasible, mask, fixed = _resolve_drunk_mask(bag, (*beliefs, *trusted), trusted)
        if not feasible:
            cached[mark] = False
            return False
        self.solver.push()
        try:
            _pin_bag(self.solver, self.world, bag, mask, fixed)
            _assert_private(self.solver, self.world, private_abilities)
            ok = self.solver.check() == sat
        finally:
            self.solver.pop()
        cached[mark] = ok
        return ok

    def _ensure_public(
        self,
        soft_roles: Sequence[tuple[int, Role]],
        soft_abilities: Sequence[AbilityObservation],
        seed: int,
    ) -> list[tuple[tuple[Role, ...], float]]:
        key = (self.hard_rev, tuple(soft_roles), _ability_mark(soft_abilities))
        if key == self._public_key:
            return self._public_particles
        self._public_particles = self._mixture(soft_roles, soft_abilities, (), (), seed, ())
        self._public_key = key
        return self._public_particles

    def _reuse_private(
        self,
        soft_roles: Sequence[tuple[int, Role]],
        soft_abilities: Sequence[AbilityObservation],
        beliefs: Sequence[tuple[int, Role]],
        pinned_roles: Sequence[tuple[int, Role]],
        seed: int,
        private_abilities: Sequence[AbilityObservation],
    ) -> list[tuple[tuple[Role, ...], float]]:
        """用公开样本承接私密读数。被忽略的玩家不生效；整组样本都不成立才重抽该组。"""

        claims = _claimed_roles(soft_roles, soft_abilities)
        groups = _credibility_groups(self.n_players, self.counts, claims, soft_abilities)
        if not groups:
            return []
        self._reuse_context = {
            "soft": soft_abilities,
            "beliefs": tuple(beliefs),
            "pinned": tuple(pinned_roles),
            "seed": seed,
            "private": tuple(private_abilities),
            "groups": groups,
            "raw_total": sum(weight for _trusted, weight in groups),
        }
        indexes = list(range(len(groups)))
        workers = worker_count(len(indexes))
        if workers > 1:
            bind_slot(session=self)
            chunks = map_in_order(_reuse_group_job, indexes, workers)
        else:
            chunks = [(index, self._reuse_one(index)) for index in indexes]
        particles: list[tuple[tuple[Role, ...], float]] = []
        for _index, chunk in sorted(chunks):
            particles.extend(chunk)
        return particles

    def _reuse_one(self, index: int) -> list[tuple[tuple[Role, ...], float]]:
        context = self._reuse_context
        trusted, group_weight = context["groups"][index]
        soft = context["soft"]
        beliefs = context["beliefs"]
        pinned = context["pinned"]
        private = context["private"]
        mark = _ability_mark(soft, {player for player, _role in trusted})
        public = self._cache.get((self.hard_rev, (), (), trusted, mark, ()))
        if public is None or not public.sat or not public.samples or not public.factors:
            return []
        trusted_set = set(trusted)
        extra = [
            observation
            for observation in private
            if (observation.actor, ability_role(observation.ability)) in trusted_set
            and not _observation_covered(observation, soft)
        ]
        if not extra:
            piece = group_weight / len(public.factors)
            return [
                (bag, piece * factor)
                for bag, factor in zip(public.samples, public.factors)
                if factor > 0.0
            ]
        survivors = [
            bag
            for bag, factor in zip(public.samples, public.factors)
            if factor > 0.0
            and self._bag_obeys_private(bag, trusted, beliefs, pinned, soft, extra)
        ]
        if not survivors:
            share = group_weight / context["raw_total"]
            cached = self._group(
                index,
                trusted,
                soft,
                beliefs,
                pinned,
                context["seed"],
                max(1, round(self.target_accepted * share)),
                max(1, round(self.max_trials * share)),
                extra,
            )
            if not cached.sat or not cached.samples:
                return []
            piece = group_weight / len(cached.factors)
            return [
                (bag, piece * factor)
                for bag, factor in zip(cached.samples, cached.factors)
                if factor > 0.0
            ]
        factors = [
            _interference_factor(
                self.solver,
                self.world,
                bag,
                beliefs=(*beliefs, *trusted),
                trusted_claims=trusted,
                soft_abilities=[*soft, *extra],
            )
            for bag in survivors
        ]
        piece = group_weight / len(factors)
        return [
            (bag, piece * factor)
            for bag, factor in zip(survivors, factors)
            if factor > 0.0
        ]

    def _bag_obeys_private(
        self,
        bag: tuple[Role, ...],
        trusted: tuple[tuple[int, Role], ...],
        beliefs: Sequence[tuple[int, Role]],
        pinned_roles: Sequence[tuple[int, Role]],
        soft_abilities: Sequence[AbilityObservation],
        extra: Sequence[AbilityObservation],
    ) -> bool:
        combined = (*beliefs, *trusted)
        feasible, mask, fixed = _resolve_drunk_mask(bag, combined, trusted)
        if not feasible or not _matches_setup(bag, mask, beliefs, pinned_roles, (), ()):
            return False
        self.solver.push()
        try:
            _assert_group(
                self.solver,
                self.world,
                combined,
                trusted,
                soft_abilities,
                pinned_roles,
                (),
                (),
            )
            _assert_private(self.solver, self.world, extra)
            _pin_bag(self.solver, self.world, bag, mask, fixed)
            return self.solver.check() == sat
        finally:
            self.solver.pop()

    def _mixture(
        self,
        soft_roles: Sequence[tuple[int, Role]],
        soft_abilities: Sequence[AbilityObservation],
        beliefs: Sequence[tuple[int, Role]],
        pinned_roles: Sequence[tuple[int, Role]],
        seed: int,
        private_abilities: Sequence[AbilityObservation],
    ) -> list[tuple[tuple[Role, ...], float]]:
        claims = _claimed_roles(soft_roles, soft_abilities)
        groups = _credibility_groups(self.n_players, self.counts, claims, soft_abilities)
        if not groups:
            return []
        raw_total = sum(weight for _trusted, weight in groups)
        specs = []
        for index, (trusted, group_weight) in enumerate(groups):
            share = group_weight / raw_total
            specs.append(
                (
                    index,
                    trusted,
                    soft_abilities,
                    beliefs,
                    pinned_roles,
                    seed,
                    max(1, round(self.target_accepted * share)),
                    max(1, round(self.max_trials * share)),
                    private_abilities,
                )
            )
        if worker_count(len(specs)) > 1:
            bind_slot(session=self, specs=specs)
            filled = map_in_order(_agent_group_job, list(range(len(specs))), worker_count(len(specs)))
            for _index, key, sat, samples, factors in filled:
                self._cache[key] = _GroupCache(sat, list(samples), list(factors))
        particles: list[tuple[tuple[Role, ...], float]] = []
        for spec in specs:
            index, trusted, _abilities, _beliefs, _pinned, _seed, _target, _trials, _private = spec
            del index
            cached = self._group(*spec)
            group_weight = next(weight for claim, weight in groups if claim == trusted)
            if not cached.sat or not cached.samples:
                continue
            piece = group_weight / len(cached.factors)
            for bag, factor in zip(cached.samples, cached.factors):
                if factor <= 0.0:
                    continue
                particles.append((bag, piece * factor))
        return particles

    def _group(
        self,
        index: int,
        trusted: tuple[tuple[int, Role], ...],
        soft_abilities: Sequence[AbilityObservation],
        beliefs: Sequence[tuple[int, Role]],
        pinned_roles: Sequence[tuple[int, Role]],
        seed: int,
        target: int,
        trials: int,
        private_abilities: Sequence[AbilityObservation],
    ) -> _GroupCache:
        mark = _ability_mark(soft_abilities, {player for player, _role in trusted})
        private_mark = _ability_mark(private_abilities)
        key = (self.hard_rev, tuple(beliefs), tuple(pinned_roles), trusted, mark, private_mark)
        self._last_group_key = key
        found = self._cache.get(key)
        if found is not None:
            return found
        if self._known_unsat(trusted, mark, beliefs, pinned_roles, private_mark):
            empty = _GroupCache(False)
            self._cache[key] = empty
            return empty
        revived = self._revalidate(
            key, trusted, soft_abilities, beliefs, pinned_roles, private_abilities, seed, target, trials
        )
        if revived is not None:
            return revived
        return self._compute(
            key, index, trusted, soft_abilities, beliefs, pinned_roles, private_abilities, seed, target, trials
        )

    def _known_unsat(
        self,
        trusted: tuple[tuple[int, Role], ...],
        mark: tuple,
        beliefs: Sequence[tuple[int, Role]],
        pinned_roles: Sequence[tuple[int, Role]],
        private_mark: tuple,
    ) -> bool:
        for drop in range(len(trusted)):
            parent = trusted[:drop] + trusted[drop + 1 :]
            parent_mark = _ability_mark_from(mark, {player for player, _role in parent})
            parent_key = (
                self.hard_rev,
                tuple(beliefs),
                tuple(pinned_roles),
                parent,
                parent_mark,
                private_mark,
            )
            cached = self._cache.get(parent_key)
            if cached is not None and not cached.sat:
                return True
        if beliefs or pinned_roles:
            public = self._cache.get((self.hard_rev, (), (), trusted, mark, ()))
            if public is not None and not public.sat:
                return True
        return False

    def _revalidate(
        self,
        key: tuple,
        trusted: tuple[tuple[int, Role], ...],
        soft_abilities: Sequence[AbilityObservation],
        beliefs: Sequence[tuple[int, Role]],
        pinned_roles: Sequence[tuple[int, Role]],
        private_abilities: Sequence[AbilityObservation],
        seed: int,
        target: int,
        trials: int,
    ) -> _GroupCache | None:
        if self.hard_rev == 0:
            return None
        mark = key[-2]
        previous = self._cache.get((self.hard_rev - 1, *key[1:]))
        if previous is None:
            return None
        if not previous.sat:
            copied = _GroupCache(False)
            self._cache[key] = copied
            return copied
        self.solver.push()
        try:
            _assert_group(
                self.solver,
                self.world,
                (*beliefs, *trusted),
                trusted,
                soft_abilities,
                pinned_roles,
                (),
                (),
            )
            _assert_private(self.solver, self.world, private_abilities)
            if self.solver.check() == unsat:
                copied = _GroupCache(False)
                self._cache[key] = copied
                return copied
            survivors = [
                bag
                for bag in previous.samples
                if _bag_sat(self.solver, self.world, bag, (*beliefs, *trusted), trusted)
            ]
            if len(survivors) < target and trials > 0:
                extra = _sample_worlds(
                    self.n_players,
                    self.counts,
                    beliefs=(*beliefs, *trusted),
                    pinned_roles=pinned_roles,
                    absent_roles=(),
                    drunk_players=(),
                    trusted_claims=trusted,
                    soft_abilities=soft_abilities,
                    solver=self.solver,
                    world=self.world,
                    seed=seed + self.hard_rev * 1009,
                    target_accepted=target - len(survivors),
                    max_trials=trials,
                    use_solver=True,
                    claims_loaded=True,
                )
                survivors.extend(extra)
            active_private = [
                observation
                for observation in private_abilities
                if (observation.actor, ability_role(observation.ability)) in set(trusted)
            ]
            factors = [
                _interference_factor(
                    self.solver,
                    self.world,
                    bag,
                    beliefs=(*beliefs, *trusted),
                    trusted_claims=trusted,
                    soft_abilities=[*soft_abilities, *active_private],
                )
                for bag in survivors
            ]
            copied = _GroupCache(bool(survivors), survivors, factors)
            self._cache[key] = copied
            return copied
        finally:
            self.solver.pop()

    def _compute(
        self,
        key: tuple,
        index: int,
        trusted: tuple[tuple[int, Role], ...],
        soft_abilities: Sequence[AbilityObservation],
        beliefs: Sequence[tuple[int, Role]],
        pinned_roles: Sequence[tuple[int, Role]],
        private_abilities: Sequence[AbilityObservation],
        seed: int,
        target: int,
        trials: int,
    ) -> _GroupCache:
        self.solver.push()
        try:
            _assert_group(
                self.solver,
                self.world,
                (*beliefs, *trusted),
                trusted,
                soft_abilities,
                pinned_roles,
                (),
                (),
            )
            _assert_private(self.solver, self.world, private_abilities)
            if self.solver.check() == unsat:
                cached = _GroupCache(False)
                self._cache[key] = cached
                return cached
            samples = _sample_worlds(
                self.n_players,
                self.counts,
                beliefs=(*beliefs, *trusted),
                pinned_roles=pinned_roles,
                absent_roles=(),
                drunk_players=(),
                trusted_claims=trusted,
                soft_abilities=soft_abilities,
                solver=self.solver,
                world=self.world,
                seed=seed + index,
                target_accepted=target,
                max_trials=trials,
                use_solver=True,
                claims_loaded=True,
            )
            if not samples:
                samples = _conditional_bags(
                    self.solver,
                    self.world,
                    beliefs=(*beliefs, *trusted),
                    trusted_claims=trusted,
                    soft_abilities=soft_abilities,
                    pinned_roles=pinned_roles,
                    absent_roles=(),
                    drunk_players=(),
                    seed=seed + index + 1009,
                    limit=min(16, max(8, target)),
                )
            active_private = [
                observation
                for observation in private_abilities
                if (observation.actor, ability_role(observation.ability)) in set(trusted)
            ]
            factors = [
                _interference_factor(
                    self.solver,
                    self.world,
                    bag,
                    beliefs=(*beliefs, *trusted),
                    trusted_claims=trusted,
                    soft_abilities=[*soft_abilities, *active_private],
                )
                for bag in samples
            ]
            cached = _GroupCache(bool(samples), list(samples), factors)
            self._cache[key] = cached
            return cached
        finally:
            self.solver.pop()


def _reuse_group_job(index: int):
    """在子进程里把一组公开样本接到私密读数上。"""

    session = slot()["session"]
    return index, session._reuse_one(index)


def _observation_covered(
    observation: AbilityObservation,
    others: Sequence[AbilityObservation],
) -> bool:
    signature = _observation_signature(observation)
    return any(_observation_signature(other) == signature for other in others)


def _observation_signature(observation: AbilityObservation):
    return (
        observation.actor,
        observation.ability,
        observation.when,
        observation.target,
        observation.claim.sexpr(),
    )


def _agent_group_job(index: int):
    """计算一组。只在子进程里跑，结果由主进程按编号写回缓存。"""

    session = slot()["session"]
    cached = session._group(*slot()["specs"][index])
    return index, session._last_group_key, cached.sat, cached.samples, cached.factors


def _assert_private(
    solver: Solver,
    world: TroubleBrewingVars,
    abilities: Sequence[AbilityObservation],
) -> None:
    for observation in abilities:
        solver.add(trusted_activation(world, observation))


def _fits(
    bag: tuple[Role, ...],
    beliefs: Sequence[tuple[int, Role]],
    pinned_roles: Sequence[tuple[int, Role]],
    trusted: Sequence[tuple[int, Role]],
) -> bool:
    feasible, mask, _fixed = _resolve_drunk_mask(bag, (*beliefs, *trusted), trusted)
    if not feasible:
        return False
    return _matches_setup(bag, mask, beliefs, pinned_roles, (), ())


def _bag_sat(
    solver: Solver,
    world: TroubleBrewingVars,
    bag: tuple[Role, ...],
    beliefs: Sequence[tuple[int, Role]],
    trusted: Sequence[tuple[int, Role]],
) -> bool:
    feasible, mask, fixed = _resolve_drunk_mask(bag, beliefs, trusted)
    if not feasible:
        return False
    solver.push()
    try:
        _pin_bag(solver, world, bag, mask, fixed)
        return solver.check() == sat
    finally:
        solver.pop()


def _ability_mark(
    abilities: Sequence[AbilityObservation],
    players: set[int] | None = None,
) -> tuple:
    rows = []
    for observation in abilities:
        if players is not None and observation.actor not in players:
            continue
        rows.append(
            (
                observation.actor,
                observation.ability.value,
                observation.when,
                observation.target,
                observation.claim.get_id(),
            )
        )
    return tuple(sorted(rows))


def _ability_mark_from(mark: tuple, players: set[int]) -> tuple:
    return tuple(row for row in mark if row[0] in players)


def _marginals(
    n_players: int,
    particles: Sequence[tuple[tuple[Role, ...], float]],
) -> list[dict[Role, float]] | None:
    total = sum(weight for _bag, weight in particles)
    if total <= 0.0:
        return None
    rows: list[dict[Role, float]] = [{} for _ in range(n_players)]
    for bag, weight in particles:
        for player, role in enumerate(bag):
            rows[player][role] = rows[player].get(role, 0.0) + weight
    return [
        {role: mass / total for role, mass in row.items() if mass > 0.0}
        for row in rows
    ]
