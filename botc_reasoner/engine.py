"""暗流涌动的前向结算。

白天、夜晚和胜负按钟楼百科的规则概要，以及本仓库 Z3 模型里已经写死的时序：
首夜恶魔不出刀；镇长替死、星坠、红唇女郎只在白天恶魔死亡后接任。
说书人的自由裁量用随机策略：陌客/间谍各有一半机会误注册，中毒或醉酒时给一条合法的假信息。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from botc_reasoner.roles import (
    EVIL_ROLES,
    GOOD_ROLES,
    MINIONS,
    OUTSIDERS,
    TOWNSFOLK,
    Role,
    alignment_of,
    Alignment,
)


@dataclass
class NightChoices:
    """某一夜玩家选出的目标。没有对应角色时留空。"""

    poison: int | None = None
    monk: int | None = None
    imp: int | None = None
    fortune: tuple[int, int] | None = None
    butler: int | None = None
    ravenkeeper: int | None = None
    bounce: int | None = None


@dataclass(frozen=True)
class Report:
    """一名玩家实际收到、或对外宣布的一次技能信息。"""

    actor: int
    ability: str
    when: int
    targets: tuple[int, ...] = ()
    yes: bool | None = None
    number: int | None = None
    role: Role | None = None
    none: bool = False


@dataclass
class Table:
    """一局进行中的机械状态。座位号从 0 起。"""

    roles: list[Role]
    alive: list[bool]
    drunk_mask: Role | None
    red_herring: int | None
    bluffs: tuple[Role, ...]
    rng: random.Random
    night: int = 1
    day: int = 0
    phase: str = "night"
    poisoned: set[int] = field(default_factory=set)
    ghost_vote: list[bool] = field(default_factory=list)
    slayer_used: list[bool] = field(default_factory=list)
    virgin_used: bool = False
    last_monk: int | None = None
    butler_master: list[int | None] = field(default_factory=list)
    last_executed: int | None = None
    executed_today: bool = False
    winner: str | None = None
    fixed_registration: bool = False
    fortune_pairs: dict[int, list[tuple[int, int]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        n = len(self.roles)
        if not self.ghost_vote:
            self.ghost_vote = [True] * n
        if not self.slayer_used:
            self.slayer_used = [False] * n
        if not self.butler_master:
            self.butler_master = [None] * n

    @property
    def n(self) -> int:
        return len(self.roles)

    def alive_ids(self) -> list[int]:
        return [player for player, living in enumerate(self.alive) if living]

    def droisoned(self, player: int) -> bool:
        return self.roles[player] is Role.DRUNK or player in self.poisoned

    def evil(self, player: int) -> bool:
        return alignment_of(self.roles[player]) is Alignment.EVIL

    def teammates_of(self, player: int) -> set[int]:
        if self.n < 7 or not self.evil(player):
            return {player} if self.evil(player) else set()
        return {seat for seat in range(self.n) if self.evil(seat)}

    def check_winner(self) -> str | None:
        if self.winner:
            return self.winner
        living = self.alive_ids()
        demon_alive = any(self.alive[player] and self.roles[player] is Role.IMP for player in range(self.n))
        if not demon_alive:
            self.winner = "good"
        elif len(living) <= 2:
            self.winner = "evil"
        return self.winner

    def resolve_night(self, choices: NightChoices) -> list[Report]:
        """结算当前夜，结束后停在次日黎明。返回本夜各玩家收到的信息。"""

        if self.winner:
            return []
        self.poisoned = set()
        self.executed_today = False
        reports: list[Report] = []
        night = self.night
        poisoner = self._find(Role.POISONER)
        if poisoner is not None and self.alive[poisoner] and choices.poison is not None:
            if not self.droisoned(poisoner):
                self.poisoned.add(choices.poison)
            reports.append(Report(poisoner, "poisoner", night, (choices.poison,)))

        protected: int | None = None
        monk = self._find(Role.MONK)
        if night > 1 and monk is not None and self.alive[monk] and choices.monk is not None:
            if not self.droisoned(monk) and choices.monk != self.last_monk and choices.monk != monk:
                protected = choices.monk
            self.last_monk = choices.monk
            reports.append(Report(monk, "monk", night, (choices.monk,)))
        elif night == 1:
            self.last_monk = None

        if night > 1:
            self._demon_kill(choices.imp, protected, choices.bounce)

        raven = self._find(Role.RAVENKEEPER)
        if (
            night > 1
            and raven is not None
            and not self.alive[raven]
            and choices.ravenkeeper is not None
            and not self.droisoned(raven)
        ):
            target = choices.ravenkeeper
            truth = self._seen_role(target)
            shown = truth if not self.droisoned(raven) else self._other_role(truth)
            reports.append(Report(raven, "ravenkeeper", night, (target,), role=shown))

        if night > 1 and self.last_executed is not None:
            undertaker = self._find(Role.UNDERTAKER)
            if undertaker is not None and self.alive[undertaker] and not self.droisoned(undertaker):
                truth = self._seen_role(self.last_executed)
                shown = truth if not self.droisoned(undertaker) else self._other_role(truth)
                reports.append(Report(undertaker, "undertaker", night, (self.last_executed,), role=shown))

        reports.extend(self._first_night_info(night))
        reports.extend(self._empath(night))
        reports.extend(self._fortune(night, choices.fortune))
        reports.extend(self._butler(night, choices.butler))
        self._become_day()
        self.check_winner()
        return reports

    def slay(self, actor: int, target: int) -> bool:
        """猎手开枪。返回目标是否因此死亡。"""

        if self.winner or not self.alive[actor] or self.slayer_used[actor]:
            return False
        self.slayer_used[actor] = True
        real = self.roles[actor] is Role.SLAYER and not self.droisoned(actor)
        killed = False
        if real and self.alive[target]:
            if self.roles[target] is Role.IMP or (
                self.roles[target] is Role.RECLUSE and self.rng.random() < 0.5
            ):
                self._kill(target)
                killed = True
                self._scarlet_if_demon_died(target)
                self.check_winner()
        return killed

    def resolve_day(
        self,
        nominations: list[tuple[int, int]],
        votes: dict[int, dict[int, bool]],
    ) -> int | None:
        """按提名顺序结算白天。返回被处决的玩家，没有则为 None。

        ``votes[nominee][voter]`` 为真表示想投赞成。死人只有一张遗言票，管家受到主人限制。
        """

        if self.winner:
            return None
        self.executed_today = False
        executed: int | None = None
        best = 0
        tied = False
        used_nominee: set[int] = set()
        used_nominator: set[int] = set()
        for nominator, nominee in nominations:
            if self.winner:
                break
            if (
                not self.alive[nominator]
                or nominator in used_nominator
                or nominee in used_nominee
            ):
                continue
            used_nominator.add(nominator)
            used_nominee.add(nominee)
            if self._virgin_trigger(nominator, nominee):
                self._kill(nominator)
                self.executed_today = True
                executed = nominator
                self._on_executed(nominator)
                break
            yes = self._count_votes(nominee, votes.get(nominee, {}))
            threshold = (len(self.alive_ids()) + 1) // 2
            if yes < threshold:
                continue
            if executed is None or yes > best:
                executed = nominee
                best = yes
                tied = False
            elif yes == best:
                tied = True
                executed = None
        if tied:
            executed = None
        if executed is not None and self.alive[executed] and not self.executed_today:
            self._kill(executed)
            self.executed_today = True
            self._on_executed(executed)
        elif executed is not None:
            self.last_executed = executed
        else:
            self.last_executed = None
        self._mayor_win()
        if not self.winner:
            self.phase = "night"
            self.night += 1
            self.poisoned = set()
        return executed

    def _on_executed(self, player: int) -> None:
        self.last_executed = player
        if self.roles[player] is Role.SAINT and not self.droisoned(player):
            self.winner = "evil"
            return
        self._scarlet_if_demon_died(player)
        self.check_winner()

    def _virgin_trigger(self, nominator: int, nominee: int) -> bool:
        if self.virgin_used or self.roles[nominee] is not Role.VIRGIN or self.droisoned(nominee):
            return False
        self.virgin_used = True
        if self.droisoned(nominee):
            return False
        return self._registers_townsfolk(nominator)

    def _count_votes(self, nominee: int, wanted: dict[int, bool]) -> int:
        yes = 0
        master_yes = {
            player
            for player, vote in wanted.items()
            if vote and self._can_vote(player, nominee, wanted, check_butler=False)
        }
        for player, vote in wanted.items():
            if not vote:
                continue
            if not self._can_vote(player, nominee, wanted, check_butler=True, masters=master_yes):
                continue
            yes += 1
            if not self.alive[player]:
                self.ghost_vote[player] = False
        return yes

    def _can_vote(
        self,
        player: int,
        nominee: int,
        wanted: dict[int, bool],
        *,
        check_butler: bool,
        masters: set[int] | None = None,
    ) -> bool:
        del nominee, wanted
        if self.alive[player]:
            pass
        elif not self.ghost_vote[player]:
            return False
        if not check_butler or self.roles[player] is not Role.BUTLER or self.droisoned(player):
            return True
        master = self.butler_master[player]
        if master is None or not self.alive[master]:
            return False
        return master in (masters or set())

    def _demon_kill(self, target: int | None, protected: int | None, bounce: int | None) -> None:
        demon = self._find(Role.IMP)
        if demon is None or not self.alive[demon] or target is None or self.droisoned(demon):
            return
        if not self.alive[target]:
            return
        if target == demon:
            self._kill(demon)
            heirs = [
                player
                for player in self.alive_ids()
                if self.roles[player] in MINIONS
            ]
            if heirs:
                heir = self.rng.choice(heirs)
                self.roles[heir] = Role.IMP
            return
        if target == protected or (
            self.roles[target] is Role.SOLDIER and not self.droisoned(target)
        ):
            return
        victim = target
        if self.roles[target] is Role.MAYOR and not self.droisoned(target):
            if bounce is not None and bounce != target and self.alive[bounce] and not self.evil(bounce):
                victim = bounce
            elif bounce is None and self.rng.random() < 0.5:
                options = [
                    player
                    for player in self.alive_ids()
                    if player != target and not self.evil(player)
                ]
                if options:
                    victim = self.rng.choice(options)
        self._kill(victim)

    def _kill(self, player: int) -> None:
        if self.alive[player]:
            self.alive[player] = False
            self.ghost_vote[player] = True

    def _scarlet_if_demon_died(self, dead: int) -> None:
        if self.roles[dead] is not Role.IMP:
            return
        if self.alive[dead]:
            return
        living = self.alive_ids()
        if len(living) < 5:
            return
        scarlet = self._find(Role.SCARLET_WOMAN)
        if scarlet is None or not self.alive[scarlet] or self.droisoned(scarlet):
            return
        self.roles[scarlet] = Role.IMP

    def _mayor_win(self) -> None:
        if self.executed_today or self.winner or len(self.alive_ids()) != 3:
            return
        mayors = [
            player
            for player in self.alive_ids()
            if self.roles[player] is Role.MAYOR and not self.droisoned(player)
        ]
        if mayors:
            self.winner = "good"

    def _become_day(self) -> None:
        self.phase = "day"
        self.day = self.night

    def _first_night_info(self, night: int) -> list[Report]:
        if night != 1:
            return []
        reports: list[Report] = []
        reports.extend(self._washerwoman())
        reports.extend(self._librarian())
        reports.extend(self._investigator())
        reports.extend(self._chef())
        return reports

    def _washerwoman(self) -> list[Report]:
        actor = self._find(Role.WASHERWOMAN)
        if actor is None or not self.alive[actor]:
            return []
        in_play = [player for player, role in enumerate(self.roles) if role in TOWNSFOLK]
        if not in_play:
            return []
        shown_player = self.rng.choice(in_play)
        shown_role = self.roles[shown_player]
        if self.roles[shown_player] is Role.SPY and self.rng.random() < 0.5:
            pool = [role for role in TOWNSFOLK if role not in self.roles]
            if pool:
                shown_role = self.rng.choice(pool)
        partner = self._partner(shown_player, actor)
        pair = tuple(sorted((shown_player, partner)))
        if self.droisoned(actor):
            fake_role = self._other_from(TOWNSFOLK, shown_role)
            others = [player for player in range(self.n) if player != actor]
            picked = self.rng.sample(others, min(2, len(others)))
            pair = tuple(sorted(picked)) if len(picked) == 2 else pair
            shown_role = fake_role
        return [Report(actor, "washerwoman", 1, pair, role=shown_role)]

    def _librarian(self) -> list[Report]:
        actor = self._find(Role.LIBRARIAN)
        if actor is None or not self.alive[actor]:
            return []
        outsiders = [player for player, role in enumerate(self.roles) if role in OUTSIDERS]
        if not outsiders:
            if self.droisoned(actor):
                role = self.rng.choice(list(OUTSIDERS))
                others = [player for player in range(self.n) if player != actor]
                pair = tuple(sorted(self.rng.sample(others, 2))) if len(others) >= 2 else ()
                return [Report(actor, "librarian", 1, pair, role=role)]
            return [Report(actor, "librarian", 1, none=True)]
        shown_player = self.rng.choice(outsiders)
        shown_role = self.roles[shown_player]
        partner = self._partner(shown_player, actor)
        pair = tuple(sorted((shown_player, partner)))
        if self.droisoned(actor):
            if self.rng.random() < 0.5:
                return [Report(actor, "librarian", 1, none=True)]
            shown_role = self._other_from(OUTSIDERS, shown_role)
            others = [player for player in range(self.n) if player != actor]
            pair = tuple(sorted(self.rng.sample(others, 2)))
        return [Report(actor, "librarian", 1, pair, role=shown_role)]

    def _investigator(self) -> list[Report]:
        actor = self._find(Role.INVESTIGATOR)
        if actor is None or not self.alive[actor]:
            return []
        minions = [player for player in range(self.n) if self._registers_minion(player)]
        if not minions:
            if self.droisoned(actor):
                role = self.rng.choice(list(MINIONS))
                others = [player for player in range(self.n) if player != actor]
                pair = tuple(sorted(self.rng.sample(others, 2))) if len(others) >= 2 else ()
                return [Report(actor, "investigator", 1, pair, role=role)]
            return [Report(actor, "investigator", 1, none=True)]
        shown_player = self.rng.choice(minions)
        shown_role = self.roles[shown_player] if self.roles[shown_player] in MINIONS else self.rng.choice(list(MINIONS))
        partner = self._partner(shown_player, actor)
        pair = tuple(sorted((shown_player, partner)))
        if self.droisoned(actor):
            shown_role = self._other_from(MINIONS, shown_role)
            others = [player for player in range(self.n) if player != actor]
            pair = tuple(sorted(self.rng.sample(others, 2)))
        return [Report(actor, "investigator", 1, pair, role=shown_role)]

    def _chef(self) -> list[Report]:
        actor = self._find(Role.CHEF)
        if actor is None or not self.alive[actor]:
            return []
        total = 0
        for player in range(self.n):
            if self._registers_evil(player) and self._registers_evil((player + 1) % self.n):
                total += 1
        if self.droisoned(actor):
            options = [value for value in range(self.n + 1) if value != total]
            total = self.rng.choice(options)
        return [Report(actor, "chef", 1, number=total)]

    def _empath(self, night: int) -> list[Report]:
        actor = self._find(Role.EMPATH)
        if actor is None or not self.alive[actor]:
            return []
        neighbors = self._alive_neighbors(actor)
        total = sum(1 for player in neighbors if self._registers_evil(player))
        if self.droisoned(actor):
            options = [value for value in (0, 1, 2) if value != total]
            total = self.rng.choice(options)
        return [Report(actor, "empath", night, tuple(neighbors), number=total)]

    def _fortune(self, night: int, targets: tuple[int, int] | None) -> list[Report]:
        actor = self._find(Role.FORTUNE_TELLER)
        if actor is None or not self.alive[actor] or targets is None:
            return []
        self.fortune_pairs.setdefault(actor, []).append(tuple(sorted(targets)))
        hit = any(self._registers_demon(player) or player == self.red_herring for player in targets)
        if self.droisoned(actor):
            hit = not hit
        return [Report(actor, "fortune_teller", night, tuple(sorted(targets)), yes=hit)]

    def _butler(self, night: int, master: int | None) -> list[Report]:
        actor = self._find(Role.BUTLER)
        if actor is None or not self.alive[actor] or master is None:
            return []
        self.butler_master[actor] = master
        return [Report(actor, "butler", night, (master,))]

    def _partner(self, shown: int, actor: int) -> int:
        pool = [player for player in range(self.n) if player not in (shown, actor)]
        if not pool:
            pool = [player for player in range(self.n) if player != shown]
        return self.rng.choice(pool)

    def _alive_neighbors(self, player: int) -> list[int]:
        found: list[int] = []
        for direction in (1, -1):
            for step in range(1, self.n):
                other = (player + direction * step) % self.n
                if self.alive[other]:
                    if other not in found:
                        found.append(other)
                    break
        return found

    def _registers_evil(self, player: int) -> bool:
        role = self.roles[player]
        if self.fixed_registration:
            if role is Role.SPY:
                return False
            if role is Role.RECLUSE:
                return True
            return role in EVIL_ROLES
        if role is Role.SPY:
            return self.rng.random() < 0.25
        if role is Role.RECLUSE:
            return self.rng.random() < 0.5
        return role in EVIL_ROLES

    def _registers_demon(self, player: int) -> bool:
        role = self.roles[player]
        if role is Role.IMP or player == self.red_herring:
            return True
        if self.fixed_registration:
            return role is Role.RECLUSE
        if role is Role.RECLUSE:
            return self.rng.random() < 0.5
        return False

    def _registers_minion(self, player: int) -> bool:
        role = self.roles[player]
        if role in MINIONS:
            return True
        if self.fixed_registration:
            return False
        if role is Role.RECLUSE:
            return self.rng.random() < 0.5
        return False

    def _registers_townsfolk(self, player: int) -> bool:
        role = self.roles[player]
        if role is Role.SPY:
            return self.rng.random() < 0.5
        if role is Role.RECLUSE:
            return False
        return role in TOWNSFOLK

    def _seen_role(self, player: int) -> Role:
        role = self.roles[player]
        if self.fixed_registration:
            if role is Role.SPY:
                missing = [item for item in TOWNSFOLK if item not in self.roles]
                return missing[0] if missing else Role.CHEF
            if role is Role.RECLUSE:
                return Role.IMP
            return role
        if role is Role.SPY and self.rng.random() < 0.5:
            pool = [item for item in GOOD_ROLES if item not in self.roles]
            return self.rng.choice(pool or list(TOWNSFOLK))
        if role is Role.RECLUSE and self.rng.random() < 0.5:
            return self.rng.choice([*MINIONS, Role.IMP])
        return role

    def _other_role(self, truth: Role) -> Role:
        pool = [role for role in Role if role is not truth]
        return self.rng.choice(pool)

    def _other_from(self, pool: tuple[Role, ...], truth: Role) -> Role:
        choices = [role for role in pool if role is not truth]
        return self.rng.choice(choices or list(pool))

    def _find(self, role: Role) -> int | None:
        for player, current in enumerate(self.roles):
            if current is role:
                return player
        return None
