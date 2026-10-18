"""把《暗流涌动》的规则写成求解器命题。"""

from __future__ import annotations

from z3 import (
    And,
    AtMost,
    BoolRef,
    BoolVal,
    If,
    Implies,
    Not,
    Or,
    PbEq,
    Solver,
    Sum,
    Xor,
)

from botc_reasoner.provenance import ConstraintCollector, rule_context
from botc_reasoner.roles import (
    DEMONS,
    GOOD_ROLES,
    MINIONS,
    OUTSIDERS,
    RECLUSE_MASK_ROLES,
    SPY_MASK_ROLES,
    TOWNSFOLK,
    Role,
)
from botc_reasoner.variables import Ability, Moment, Query, QueryKind, TroubleBrewingVars

WIKI_URL = "https://clocktower-wiki.gstonegames.com/index.php?title=%E6%9A%97%E6%B5%81%E6%B6%8C%E5%8A%A8"
"""规则依据：钟楼百科《暗流涌动》页面。"""


def add_setup_rules(
    solver: Solver,
    world: TroubleBrewingVars,
    c: int,
    f: int,
    h: int,
    d: int,
) -> None:
    """把开局人数规则加入 ``solver``。

    ``c, f, h, d`` 是不计男爵时的镇民、外来者、爪牙、恶魔数量，四者之和必须等于玩家人数。
    求解器里应已经有 ``build_solver()`` 放进的变量域公理。

    镇民总数 = c，或者存在男爵且镇民总数 = c-2。
    外来者和同一次男爵判断绑在一起：没有男爵时外来者 = f，有男爵时外来者 = f+2。
    爪牙总数 = h，恶魔总数 = d。人数按第 1 夜入夜的真实身份计算，酒鬼的镇民标记不算镇民。
    开局每种角色至多一名玩家。
    """

    townsfolk, outsiders, minions, demons = (_nat("c", c), _nat("f", f), _nat("h", h), _nat("d", d))
    if townsfolk + outsiders + minions + demons != world.n_players:
        raise ValueError(
            f"c+f+h+d 必须等于玩家人数 {world.n_players}，"
            f"收到 {townsfolk}+{outsiders}+{minions}+{demons}"
        )

    baron = _or_all([world.start_is(player, Role.BARON) for player in world.player_ids])
    townsfolk_total = _category_flags(world, TOWNSFOLK)
    outsider_total = _category_flags(world, OUTSIDERS)
    without_baron = And(
        Not(baron),
        _count_eq(townsfolk_total, townsfolk),
        _count_eq(outsider_total, outsiders),
    )
    with_baron = And(
        baron,
        _count_eq(townsfolk_total, townsfolk - 2),
        _count_eq(outsider_total, outsiders + 2),
    )
    solver.add(Or(without_baron, with_baron))
    solver.add(_count_eq(_category_flags(world, MINIONS), minions))
    solver.add(_count_eq(_category_flags(world, DEMONS), demons))
    for role in Role:
        bits = [world.start_is(player, role) for player in world.player_ids]
        if len(bits) > 1:
            solver.add(AtMost(*bits, 1))


def add_game_rules(
    solver: Solver,
    world: TroubleBrewingVars,
    c: int,
    f: int,
    h: int,
    d: int,
) -> None:
    """把已实现的《暗流涌动》规则加入求解器。

    包含开局人数、酒鬼标记、干扰项、恶魔伪装、中毒与醉酒、身份和存活的延续、
    夜间恶魔击杀、星坠、红唇女郎、猎手、贞洁者、投票处决，以及健康角色收到的信息。
    镇长三人获胜、圣徒处决落败只结束游戏，不改写这些变量，因此不在这里。

    ``solver`` 可以是普通 Z3 ``Solver``，也可以是 :class:`~botc_reasoner.provenance.ConstraintCollector`：
    后者没有 ``context`` 之外的 ``add`` 差异，规则体只调用 ``add``，因此同一段代码既能真的加进求解器，
    也能只收集带来源的约束。
    """

    with rule_context(solver, "tb:setup", "开局配置", source=WIKI_URL):
        add_setup_rules(solver, world, c, f, h, d)
    with rule_context(solver, "tb:opening", "开局秘密", source=WIKI_URL):
        _add_opening_secrets(solver, world)
    with rule_context(solver, "tb:poison_drunk", "中毒与醉酒", source=WIKI_URL):
        _add_poison_and_drunk(solver, world)
    with rule_context(solver, "tb:continuity", "身份与存活延续", source=WIKI_URL):
        _add_continuity(solver, world)
    with rule_context(solver, "tb:night_kills", "夜间击杀", source=WIKI_URL):
        _add_night_kills(solver, world)
    with rule_context(solver, "tb:day_rules", "白天规则", source=WIKI_URL):
        _add_day_rules(solver, world)
    with rule_context(solver, "tb:ghost_votes", "每名死者整局仅一票", source="https://wiki.bloodontheclocktower.com/Rules_Explanation"):
        for player in world.player_ids:
            dead_ballots = [And(Not(world.alive_dawn[day][player]), world.voted[day][index][player])
                            for day in world.days for index in world.nomination_ids]
            if len(dead_ballots) > 1:
                solver.add(AtMost(*dead_ballots, 1))
    with rule_context(solver, "tb:information", "信息类技能", source=WIKI_URL):
        _add_information(solver, world)


def collect_game_rules(
    world: TroubleBrewingVars,
    c: int,
    f: int,
    h: int,
    d: int,
) -> ConstraintCollector:
    """收集 :func:`add_game_rules` 的约束及来源元数据，**不**求解、**不**含变量域公理。

    返回的 :class:`~botc_reasoner.provenance.ConstraintCollector` 含 ``records``（逐条约束 +
    规则编号 + 稳定实例编号）与 ``catalog``（规则编号 → :class:`RuleSpec`），供冲突解释、
    修复追溯使用。变量域公理仍由调用方按需通过 ``world.encoding_axioms()`` 加入。
    """

    collector = ConstraintCollector()
    add_game_rules(collector, world, c, f, h, d)
    return collector


def _add_opening_secrets(solver: Solver, world: TroubleBrewingVars) -> None:
    """酒鬼标记、占卜师干扰项，以及恶魔看到的三个不在场善良角色。"""

    players = world.player_ids
    any_drunk = _or_all([world.is_drunk[player] for player in players])
    for role in TOWNSFOLK:
        seated = _or_all([world.start_is(player, role) for player in players])
        solver.add(Implies(world.drunk_mask[role], And(any_drunk, Not(seated))))
    solver.add(_count_eq(list(world.drunk_mask.values()), 1) == any_drunk)
    for player in players:
        drunk = world.is_drunk[player]
        for role in Role:
            believed = world.believes_at_start(player, role)
            if role in TOWNSFOLK:
                solver.add(Implies(drunk, believed == world.drunk_mask[role]))
            else:
                solver.add(Implies(drunk, Not(believed)))
            solver.add(Implies(Not(drunk), believed == world.start_is(player, role)))

    fortune_in_play = _or_all([world.start_is(player, Role.FORTUNE_TELLER) for player in players])
    good = {
        player: _or_all(
            [world.start_is(player, role) for role in TOWNSFOLK + OUTSIDERS]
        )
        for player in players
    }
    for player in players:
        solver.add(Implies(world.red_herring[player], And(fortune_in_play, good[player])))
    solver.add(_count_eq(list(world.red_herring.values()), 1) == fortune_in_play)

    solver.add(_count_eq(list(world.bluff.values()), 3))
    for role in GOOD_ROLES:
        seated = _or_all([world.start_is(player, role) for player in players])
        masked = world.drunk_mask[role] if role in TOWNSFOLK else BoolVal(False)
        solver.add(Implies(world.bluff[role], And(Not(seated), Not(masked))))


def _add_poison_and_drunk(solver: Solver, world: TroubleBrewingVars) -> None:
    for player in world.player_ids:
        solver.add(world.is_drunk[player] == world.start_is(player, Role.DRUNK))
    for night in world.nights:
        poisoner_alive = _or_all(
            [
                And(
                    world.role_night_start[night][player][Role.POISONER],
                    world.alive_night_start[night][player],
                )
                for player in world.player_ids
            ]
        )
        for player in world.player_ids:
            solver.add(
                world.poisoned[night][player]
                == And(world.poison_choice[night][player], poisoner_alive)
            )


def _add_continuity(solver: Solver, world: TroubleBrewingVars) -> None:
    for player in world.player_ids:
        solver.add(world.alive_night_start[1][player])
    for night in world.nights:
        for player in world.player_ids:
            if night == 1:
                survived = world.alive_night_start[night][player]
            else:
                survived = And(
                    world.alive_night_start[night][player],
                    Not(world.night_death[night][player]),
                )
            solver.add(world.alive_dawn[night][player] == survived)
            heir = (
                world.starpass_heir[night][player] if night in world.demon_nights else BoolVal(False)
            )
            _hold_role_unless(
                solver,
                world.role_night_start[night][player],
                world.role_dawn[night][player],
                heir,
                Role.IMP,
            )
            _hold_role_unless(
                solver,
                world.believed_night_start[night][player],
                world.believed_dawn[night][player],
                heir,
                Role.IMP,
            )


def _add_night_kills(solver: Solver, world: TroubleBrewingVars) -> None:
    """恶魔击杀在黎明公布，记入当夜的 ``night_death``。

    健康的小恶魔选中一名存活玩家，且僧侣没有保护他、他也不是健康的士兵时：
    若他是健康的镇长，则他死亡，或者死亡转移到另一名存活玩家；
    否则他在这夜死亡。小恶魔选择自己则星坠。恶魔中毒或醉酒时无人因此死亡。
    """

    for night in world.demon_nights:
        alive = world.alive_night_start[night]
        chosen = world.imp_choice[night]
        bounce = world.mayor_bounce[night]
        death = world.night_death[night]

        def role(player: int, which: Role) -> BoolRef:
            return world.role_night_start[night][player][which]

        demon_acts = _or_all(
            [
                And(role(player, Role.IMP), alive[player], Not(world.is_droisoned(player, night)))
                for player in world.player_ids
            ]
        )
        protected = {
            target: _or_all(
                [
                    And(
                        role(monk, Role.MONK),
                        alive[monk],
                        Not(world.is_droisoned(monk, night)),
                        world.monk_choice[night][target],
                    )
                    for monk in world.player_ids
                    if monk != target
                ]
            )
            for target in world.player_ids
        }

        def lands(target: int) -> BoolRef:
            healthy_soldier = And(role(target, Role.SOLDIER), Not(world.is_droisoned(target, night)))
            return And(
                demon_acts,
                chosen[target],
                alive[target],
                Not(protected[target]),
                Not(healthy_soldier),
            )

        def mayor_case(target: int) -> BoolRef:
            return And(
                lands(target),
                role(target, Role.MAYOR),
                Not(world.is_droisoned(target, night)),
                Not(role(target, Role.IMP)),
            )

        any_mayor = _or_all([mayor_case(target) for target in world.player_ids])
        any_bounce = _or_all(list(bounce.values()))
        solver.add(Implies(Not(any_mayor), Not(any_bounce)))
        for target in world.player_ids:
            solver.add(Implies(bounce[target], And(any_mayor, alive[target], Not(mayor_case(target)))))
            normal = And(lands(target), Not(role(target, Role.MAYOR)), Not(role(target, Role.IMP)))
            self_kill = And(lands(target), role(target, Role.IMP))
            mayor_dies = And(mayor_case(target), Not(any_bounce))
            redirected = And(bounce[target], alive[target], Not(mayor_case(target)))
            solver.add(death[target] == _or_all([normal, self_kill, mayor_dies, redirected]))

        self_kill_happens = _or_all(
            [And(lands(target), role(target, Role.IMP)) for target in world.player_ids]
        )
        living_minion = {
            player: And(alive[player], _or_all([role(player, which) for which in MINIONS]))
            for player in world.player_ids
        }
        any_minion = _or_all(list(living_minion.values()))
        # A healthy Scarlet Woman takes precedence over other heirs at 5+ alive.
        scarlet_ready = {
            player: And(alive[player], role(player, Role.SCARLET_WOMAN),
                        Not(world.is_droisoned(player, night))) for player in world.player_ids
        }
        scarlet_priority = And(Sum([If(alive[p], 1, 0) for p in world.player_ids]) >= 5,
                               _or_all(list(scarlet_ready.values())))
        heirs = list(world.starpass_heir[night].values())
        for player in world.player_ids:
            solver.add(
                Implies(
                    world.starpass_heir[night][player],
                    And(self_kill_happens, living_minion[player]),
                )
            )
            solver.add(Implies(And(self_kill_happens, scarlet_priority),
                               world.starpass_heir[night][player] == scarlet_ready[player]))
        solver.add(
            _count_eq(heirs, 1)
            == And(self_kill_happens, any_minion)
        )


def _add_day_rules(solver: Solver, world: TroubleBrewingVars) -> None:
    for day in world.days:
        with rule_context(solver, "tb:votes_virgin", "投票与贞洁者", source=WIKI_URL):
            _add_votes_and_virgin(solver, world, day)
        with rule_context(solver, "tb:slayer", "猎手", source=WIKI_URL):
            _add_slayer(solver, world, day)
        with rule_context(solver, "tb:butler", "管家", source=WIKI_URL):
            _add_butler(solver, world, day)
        proc = _scarlet_woman_proc(world, day)
        for player in world.player_ids:
            alive_after = And(
                world.alive_dawn[day][player],
                Not(world.executed[day][player]),
                Not(world.slayer_kill[day][player]),
            )
            solver.add(world.alive_after_day(day, player) == alive_after)
            solver.add(Implies(world.executed[day][player], world.alive_dawn[day][player]))
            solver.add(
                Implies(world.slayer_kill[day][player], world.alive_dawn[day][player])
            )
            solver.add(
                Not(And(world.executed[day][player], world.slayer_kill[day][player]))
            )
            becomes_imp = And(
                proc,
                world.role_dawn[day][player][Role.SCARLET_WOMAN],
                alive_after,
            )
            _hold_role_unless(
                solver,
                world.role_dawn[day][player],
                {role: world.role_after_day(day, player, role) for role in Role},
                becomes_imp,
                Role.IMP,
            )
            _hold_role_unless(
                solver,
                world.believed_dawn[day][player],
                _belief_after_day(world, day, player),
                becomes_imp,
                Role.IMP,
            )


def _add_votes_and_virgin(solver: Solver, world: TroubleBrewingVars, day: int) -> None:
    players = list(world.player_ids)
    alive = world.alive_dawn[day]
    alive_count = Sum([If(alive[player], 1, 0) for player in players])
    threshold = (alive_count + 1) / 2
    happened = world.nomination_happened[day]
    vote_totals = []
    for index in world.nomination_ids:
        total = Sum([If(world.voted[day][index][player], 1, 0) for player in players])
        vote_totals.append(total)
        for player in players:
            solver.add(Implies(world.nominator[day][index][player], alive[player]))
            # Dead players may be nominated; only the nominator must be alive.
    for player in players:
        ballots = [world.voted[day][index][player] for index in world.nomination_ids]
        if len(ballots) > 1:
            solver.add(Implies(Not(alive[player]), AtMost(*ballots, 1)))

    virgin_exec = {player: BoolVal(False) for player in players}
    query = Query(QueryKind.VIRGIN)
    for index in world.nomination_ids:
        for virgin in players:
            first = _first_nomination(world, day, index, virgin)
            healthy = And(
                alive[virgin],
                world.role_dawn[day][virgin][Role.VIRGIN],
                Not(world.is_droisoned(virgin, day)),
            )
            for nominator in players:
                triggers = And(
                    first,
                    healthy,
                    world.nominator[day][index][nominator],
                    _registers_townsfolk(world, nominator, query, day, Moment.DAWN),
                )
                virgin_exec[nominator] = Or(virgin_exec[nominator], triggers)
    virgin_happened = _or_all(list(virgin_exec.values()))
    for player in players:
        vote_exec = _or_all(
            [
                And(
                    happened[index],
                    world.nominee[day][index][player],
                    vote_totals[index - 1] >= threshold,
                    And(
                        [
                            Implies(
                                happened[other],
                                vote_totals[index - 1] > vote_totals[other - 1],
                            )
                            for other in world.nomination_ids
                            if other != index
                        ]
                    ),
                )
                for index in world.nomination_ids
            ]
        )
        solver.add(
            world.executed[day][player] == If(virgin_happened, virgin_exec[player], vote_exec)
        )


def _add_slayer(solver: Solver, world: TroubleBrewingVars, day: int) -> None:
    query = Query(QueryKind.SLAYER)
    kills = {target: [] for target in world.player_ids}
    for actor in world.player_ids:
        spent = _or_all(
            [
                And(
                    world.ability_used[Ability.SLAYER][earlier][actor],
                    world.alive_dawn[earlier][actor],
                    world.role_dawn[earlier][actor][Role.SLAYER],
                )
                for earlier in world.days
                if earlier < day
            ]
        )
        after = world.slayer_after_execution[day][actor]
        for target in world.player_ids:
            actor_alive = If(
                after,
                And(world.alive_dawn[day][actor], Not(world.executed[day][actor])),
                world.alive_dawn[day][actor],
            )
            target_alive = If(
                after,
                And(world.alive_dawn[day][target], Not(world.executed[day][target])),
                world.alive_dawn[day][target],
            )
            actor_slayer = If(
                after,
                world.role_after_day(day, actor, Role.SLAYER),
                world.role_dawn[day][actor][Role.SLAYER],
            )
            claim = And(
                world.ability_used[Ability.SLAYER][day][actor],
                world.ability_target[Ability.SLAYER][day][actor][target],
            )
            kills[target].append(
                And(
                    claim,
                    actor_slayer,
                    actor_alive,
                    target_alive,
                    Not(spent),
                    Not(world.is_droisoned(actor, day)),
                    _demon_to_slayer(world, day, target, after, query),
                )
            )
    for target in world.player_ids:
        solver.add(world.slayer_kill[day][target] == _or_all(kills[target]))


def _add_butler(solver: Solver, world: TroubleBrewingVars, day: int) -> None:
    for butler in world.player_ids:
        healthy = And(
            world.alive_dawn[day][butler],
            world.role_dawn[day][butler][Role.BUTLER],
            Not(world.is_droisoned(butler, day)),
        )
        master_voted = {
            index: _or_all(
                [
                    And(
                        world.butler_master[day][master],
                        world.voted[day][index][master],
                    )
                    for master in world.player_ids
                ]
            )
            for index in world.nomination_ids
        }
        for index in world.nomination_ids:
            solver.add(
                Implies(
                    healthy,
                    Implies(world.voted[day][index][butler], master_voted[index]),
                )
            )


def _add_information(solver: Solver, world: TroubleBrewingVars) -> None:
    _add_washerwoman(solver, world)
    _add_librarian(solver, world)
    _add_investigator(solver, world)
    _add_chef(solver, world)
    for night in world.nights:
        _add_empath(solver, world, night)
        _add_fortune_teller(solver, world, night)
    for night in world.demon_nights:
        _add_undertaker(solver, world, night)
        _add_ravenkeeper(solver, world, night)


def _add_washerwoman(solver: Solver, world: TroubleBrewingVars) -> None:
    query = Query(QueryKind.WASHERWOMAN)
    for actor in world.player_ids:
        healthy = And(world.start_is(actor, Role.WASHERWOMAN), Not(world.is_droisoned(actor, 1)))
        solver.add(Implies(healthy, world.ability_used[Ability.WASHERWOMAN][1][actor]))
        for role in TOWNSFOLK:
            registers = [
                And(
                    world.washerwoman_first[actor][player],
                    _registers_washerwoman(world, player, role, query),
                )
                for player in world.player_ids
            ]
            other = [
                And(
                    world.washerwoman_second[actor][player],
                    _registers_washerwoman(world, player, role, query),
                )
                for player in world.player_ids
            ]
            solver.add(
                Implies(
                    And(healthy, world.washerwoman_role[actor][role]),
                    Xor(_or_all(registers), _or_all(other)),
                )
            )


def _add_librarian(solver: Solver, world: TroubleBrewingVars) -> None:
    _add_pair_info(
        solver,
        world,
        Ability.LIBRARIAN,
        OUTSIDERS,
        world.librarian_none,
        world.librarian_role,
        world.librarian_first,
        world.librarian_second,
        Query(QueryKind.LIBRARIAN),
        _registers_outsider,
    )


def _add_investigator(solver: Solver, world: TroubleBrewingVars) -> None:
    _add_pair_info(
        solver,
        world,
        Ability.INVESTIGATOR,
        MINIONS,
        world.investigator_none,
        world.investigator_role,
        world.investigator_first,
        world.investigator_second,
        Query(QueryKind.INVESTIGATOR),
        _registers_minion,
    )


def _add_pair_info(
    solver: Solver,
    world: TroubleBrewingVars,
    ability: Ability,
    roles: tuple[Role, ...],
    none: dict[int, BoolRef],
    shown: dict[int, dict[Role, BoolRef]],
    first: dict[int, dict[int, BoolRef]],
    second: dict[int, dict[int, BoolRef]],
    query: Query,
    registers,
) -> None:
    present = _or_all(
        [
            registers(world, player, role, query)
            for player in world.player_ids
            for role in roles
        ]
    )
    for actor in world.player_ids:
        healthy = And(world.start_is(actor, ability_role(ability)), Not(world.is_droisoned(actor, 1)))
        solver.add(Implies(healthy, world.ability_used[ability][1][actor]))
        solver.add(Implies(And(healthy, Not(present)), none[actor]))
        solver.add(Implies(And(healthy, present), Not(none[actor])))
        for role in roles:
            left = _or_all(
                [
                    And(first[actor][player], registers(world, player, role, query))
                    for player in world.player_ids
                ]
            )
            right = _or_all(
                [
                    And(second[actor][player], registers(world, player, role, query))
                    for player in world.player_ids
                ]
            )
            solver.add(Implies(And(healthy, present, shown[actor][role]), Xor(left, right)))


def _add_chef(solver: Solver, world: TroubleBrewingVars) -> None:
    query = Query(QueryKind.CHEF)
    evil = [
        _registers_evil(world, player, query, 1, Moment.NIGHT_START) for player in world.player_ids
    ]
    pairs = [
        And(evil[player], evil[(player + 1) % world.n_players]) for player in world.player_ids
    ]
    total = Sum([If(pair, 1, 0) for pair in pairs])
    for actor in world.player_ids:
        healthy = And(world.start_is(actor, Role.CHEF), Not(world.is_droisoned(actor, 1)))
        solver.add(Implies(healthy, world.ability_used[Ability.CHEF][1][actor]))
        for count, bit in world.chef_number[actor].items():
            solver.add(Implies(healthy, bit == (total == count)))


def _add_empath(solver: Solver, world: TroubleBrewingVars, night: int) -> None:
    query = Query(QueryKind.EMPATH, night)
    alive = world.alive_dawn[night]
    evil = {
        player: _registers_evil(world, player, query, night, Moment.DAWN)
        for player in world.player_ids
    }
    for actor in world.player_ids:
        healthy = And(
            alive[actor],
            world.role_dawn[night][actor][Role.EMPATH],
            Not(world.is_droisoned(actor, night)),
        )
        solver.add(Implies(healthy, world.ability_used[Ability.EMPATH][night][actor]))
        count = _neighbor_evil_count(world, actor, alive, evil)
        for value, bit in world.empath_number[night][actor].items():
            solver.add(Implies(healthy, bit == (count == value)))


def _add_fortune_teller(solver: Solver, world: TroubleBrewingVars, night: int) -> None:
    query = Query(QueryKind.FORTUNE_TELLER, night)
    for actor in world.player_ids:
        healthy = And(
            world.alive_dawn[night][actor],
            world.role_dawn[night][actor][Role.FORTUNE_TELLER],
            Not(world.is_droisoned(actor, night)),
        )
        solver.add(Implies(healthy, world.ability_used[Ability.FORTUNE_TELLER][night][actor]))
        hit = []
        for player in world.player_ids:
            picked = Or(
                world.fortune_first[night][actor][player],
                world.fortune_second[night][actor][player],
            )
            demon = _registers_demon(world, player, query, night, Moment.DAWN)
            hit.append(And(picked, Or(demon, world.red_herring[player])))
        solver.add(Implies(healthy, world.fortune_yes[night][actor] == _or_all(hit)))


def _add_undertaker(solver: Solver, world: TroubleBrewingVars, night: int) -> None:
    query = Query(QueryKind.UNDERTAKER, night)
    day = night - 1
    executed = world.executed[day]
    for actor in world.player_ids:
        healthy = And(
            world.alive_night_start[night][actor],
            world.role_night_start[night][actor][Role.UNDERTAKER],
            Not(world.is_droisoned(actor, night)),
        )
        someone = _or_all(list(executed.values()))
        solver.add(Implies(And(healthy, Not(someone)), Not(world.ability_used[Ability.UNDERTAKER][night][actor])))
        solver.add(Implies(And(healthy, someone), world.ability_used[Ability.UNDERTAKER][night][actor]))
        for role in Role:
            seen = _or_all(
                [
                    And(
                        executed[player],
                        _seen_as(world, player, role, query, day, Moment.DAWN),
                    )
                    for player in world.player_ids
                ]
            )
            solver.add(
                Implies(
                    And(healthy, someone, world.undertaker_role[night][actor][role]),
                    seen,
                )
            )


def _add_ravenkeeper(solver: Solver, world: TroubleBrewingVars, night: int) -> None:
    query = Query(QueryKind.RAVENKEEPER)
    for actor in world.player_ids:
        is_ravenkeeper = world.role_night_start[night][actor][Role.RAVENKEEPER]
        died = world.night_death[night][actor]
        healthy = And(is_ravenkeeper, died, Not(world.is_droisoned(actor, night)))
        solver.add(Implies(And(is_ravenkeeper, Not(died)), Not(world.ability_used[Ability.RAVENKEEPER][night][actor])))
        solver.add(Implies(healthy, world.ability_used[Ability.RAVENKEEPER][night][actor]))
        for role in Role:
            seen = _or_all(
                [
                    And(
                        world.ability_target[Ability.RAVENKEEPER][night][actor][player],
                        _seen_as(world, player, role, query, night, Moment.DAWN),
                    )
                    for player in world.player_ids
                ]
            )
            solver.add(
                Implies(
                    And(healthy, world.ravenkeeper_role[night][actor][role]),
                    seen,
                )
            )


def _category_flags(world: TroubleBrewingVars, roles: tuple[Role, ...]) -> list[BoolRef]:
    return [
        world.start_is(player, role) for player in world.player_ids for role in roles
    ]


def _count_eq(flags: list[BoolRef], total: int) -> BoolRef:
    if total < 0 or total > len(flags):
        return BoolVal(False)
    return PbEq([(flag, 1) for flag in flags], total)


def _or_all(flags: list[BoolRef]) -> BoolRef:
    if not flags:
        return BoolVal(False)
    if len(flags) == 1:
        return flags[0]
    return Or(*flags)


def _nat(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} 必须是整数，收到 {value!r}")
    if value < 0:
        raise ValueError(f"{name} 不能为负，收到 {value}")
    return value


def _hold_role_unless(
    solver: Solver,
    source: dict[Role, BoolRef],
    dest: dict[Role, BoolRef],
    change: BoolRef,
    new_role: Role,
) -> None:
    solver.add(Implies(change, dest[new_role]))
    for role in Role:
        solver.add(Implies(Not(change), dest[role] == source[role]))


def _belief_after_day(world: TroubleBrewingVars, day: int, player: int) -> dict[Role, BoolRef]:
    if day < world.n_nights:
        return world.believed_night_start[day + 1][player]
    return world.believed_end[player]


def _scarlet_woman_proc(world: TroubleBrewingVars, day: int) -> BoolRef:
    players = list(world.player_ids)
    alive = world.alive_dawn[day]
    alive_count = Sum([If(alive[player], 1, 0) for player in players])
    deaths = [
        And(alive[player], Or(world.executed[day][player], world.slayer_kill[day][player]))
        for player in players
    ]
    demon_dies = [
        And(deaths[player], world.role_dawn[day][player][Role.IMP]) for player in players
    ]
    ready = _or_all(
        [
            And(
                alive[player],
                world.role_dawn[day][player][Role.SCARLET_WOMAN],
                Not(world.is_droisoned(player, day)),
                Not(world.executed[day][player]),
                Not(world.slayer_kill[day][player]),
            )
            for player in players
        ]
    )
    # Five players immediately BEFORE the Demon dies, not five survivors.
    return And(_or_all(demon_dies), ready, alive_count >= 5)


def _first_nomination(world: TroubleBrewingVars, day: int, index: int, virgin: int) -> BoolRef:
    this = And(world.nomination_happened[day][index], world.nominee[day][index][virgin])
    earlier = []
    for prev_day in world.days:
        for prev_index in world.nomination_ids:
            if prev_day > day or (prev_day == day and prev_index >= index):
                continue
            earlier.append(
                And(
                    world.nomination_happened[prev_day][prev_index],
                    world.nominee[prev_day][prev_index][virgin],
                )
            )
    return And(this, Not(_or_all(earlier)))


def ability_role(ability: Ability) -> Role:
    return Role(ability.value)


def _registers_townsfolk(
    world: TroubleBrewingVars, player: int, query: Query, night: int, moment: Moment
) -> BoolRef:
    townsfolk = _or_all(
        [world.is_role(player, role, moment, night) for role in TOWNSFOLK]
    )
    spy = world.is_role(player, Role.SPY, moment, night)
    masked = _or_all([world.spy_mask[player][query][role] for role in TOWNSFOLK])
    return If(spy, masked, townsfolk)


def _registers_washerwoman(
    world: TroubleBrewingVars, player: int, role: Role, query: Query
) -> BoolRef:
    return Or(
        And(world.is_drunk[player], world.drunk_mask[role]),
        And(world.start_is(player, Role.SPY), world.spy_mask[player][query][role]),
        And(world.start_is(player, role), Not(world.start_is(player, Role.SPY)), Not(world.is_drunk[player])),
    )


def _registers_outsider(
    world: TroubleBrewingVars, player: int, role: Role, query: Query
) -> BoolRef:
    recluse_hidden = And(
        world.start_is(player, Role.RECLUSE),
        _or_all(list(world.recluse_mask[player][query].values())),
    )
    return Or(
        And(world.start_is(player, Role.SPY), world.spy_mask[player][query][role]),
        And(world.start_is(player, role), Not(world.start_is(player, Role.SPY)), Not(recluse_hidden)),
    )


def _registers_minion(
    world: TroubleBrewingVars, player: int, role: Role, query: Query
) -> BoolRef:
    spy_hidden = And(
        world.start_is(player, Role.SPY),
        _or_all(list(world.spy_mask[player][query].values())),
    )
    recluse_as = And(
        world.start_is(player, Role.RECLUSE),
        world.recluse_mask[player][query][role],
    )
    return Or(And(world.start_is(player, role), Not(spy_hidden)), recluse_as)


def _registers_evil(
    world: TroubleBrewingVars,
    player: int,
    query: Query,
    night: int,
    moment: Moment,
) -> BoolRef:
    actual_evil = _or_all(
        [world.is_role(player, role, moment, night) for role in MINIONS + DEMONS]
    )
    spy = world.is_role(player, Role.SPY, moment, night)
    spy_good = And(spy, _or_all(list(world.spy_mask[player][query].values())))
    recluse_evil = And(
        world.is_role(player, Role.RECLUSE, moment, night),
        _or_all(list(world.recluse_mask[player][query].values())),
    )
    return Or(And(actual_evil, Not(spy_good)), recluse_evil)


def _registers_demon(
    world: TroubleBrewingVars,
    player: int,
    query: Query,
    night: int,
    moment: Moment,
) -> BoolRef:
    return Or(
        world.is_role(player, Role.IMP, moment, night),
        And(
            world.is_role(player, Role.RECLUSE, moment, night),
            world.recluse_mask[player][query][Role.IMP],
        ),
    )


def _seen_as(
    world: TroubleBrewingVars,
    player: int,
    role: Role,
    query: Query,
    night: int,
    moment: Moment,
) -> BoolRef:
    actual = world.is_role(player, role, moment, night)
    spy = world.is_role(player, Role.SPY, moment, night)
    recluse = world.is_role(player, Role.RECLUSE, moment, night)
    spy_masks = world.spy_mask[player][query]
    recluse_masks = world.recluse_mask[player][query]
    spy_as = And(spy, spy_masks[role]) if role in spy_masks else BoolVal(False)
    recluse_as = And(recluse, recluse_masks[role]) if role in recluse_masks else BoolVal(False)
    plain = And(
        actual,
        Not(And(spy, _or_all(list(spy_masks.values())))),
        Not(And(recluse, _or_all(list(recluse_masks.values())))),
    )
    return Or(spy_as, recluse_as, plain)


def _neighbor_evil_count(
    world: TroubleBrewingVars,
    origin: int,
    alive: dict[int, BoolRef],
    evil: dict[int, BoolRef],
) -> BoolRef:
    def nearest(step: int) -> dict[int, BoolRef]:
        found = {}
        for dist in range(1, world.n_players):
            seat = (origin + step * dist) % world.n_players
            blockers = [(origin + step * between) % world.n_players for between in range(1, dist)]
            clear = And([Not(alive[block]) for block in blockers]) if blockers else BoolVal(True)
            found[seat] = And(alive[seat], clear)
        return found

    left = nearest(1)
    right = nearest(-1)
    left_evil = _or_all([And(flag, evil[seat]) for seat, flag in left.items()])
    right_evil = _or_all([And(flag, evil[seat]) for seat, flag in right.items()])
    same = _or_all([And(left[seat], right[seat]) for seat in left])
    one_side = If(left_evil, 1, 0)
    return If(same, one_side, one_side + If(right_evil, 1, 0))


def _demon_to_slayer(
    world: TroubleBrewingVars,
    day: int,
    target: int,
    after: BoolRef,
    query: Query,
) -> BoolRef:
    imp = If(
        after,
        world.role_after_day(day, target, Role.IMP),
        world.role_dawn[day][target][Role.IMP],
    )
    recluse = If(
        after,
        world.role_after_day(day, target, Role.RECLUSE),
        world.role_dawn[day][target][Role.RECLUSE],
    )
    return Or(imp, And(recluse, world.recluse_mask[target][query][Role.IMP]))


def _self_check() -> None:
    from z3 import Not, sat, unsat

    from botc_reasoner.variables import declare_variables

    world = declare_variables(8, n_nights=1, tag="setup8")
    solver = world.build_solver()
    add_setup_rules(solver, world, 5, 1, 1, 1)
    if solver.check() != sat:
        raise SystemExit("八人标准配置应当可满足")

    no_baron = world.build_solver()
    add_setup_rules(no_baron, world, 5, 1, 1, 1)
    no_baron.add(Not(_or_all([world.start_is(player, Role.BARON) for player in world.player_ids])))
    for player, role in enumerate(
        (
            Role.CHEF,
            Role.EMPATH,
            Role.FORTUNE_TELLER,
            Role.UNDERTAKER,
            Role.VIRGIN,
            Role.SAINT,
            Role.POISONER,
            Role.IMP,
        )
    ):
        no_baron.add(world.start_is(player, role))
    if no_baron.check() != sat:
        raise SystemExit("没有男爵时 5 镇民 1 外来者应当可满足")

    baron_ok = world.build_solver()
    add_setup_rules(baron_ok, world, 5, 1, 1, 1)
    for player, role in enumerate(
        (
            Role.BARON,
            Role.CHEF,
            Role.EMPATH,
            Role.FORTUNE_TELLER,
            Role.BUTLER,
            Role.DRUNK,
            Role.SAINT,
            Role.IMP,
        )
    ):
        baron_ok.add(world.start_is(player, role))
    if baron_ok.check() != sat:
        raise SystemExit("有男爵时 3 镇民 3 外来者应当可满足")

    baron_keeps_base_townsfolk = world.build_solver()
    add_setup_rules(baron_keeps_base_townsfolk, world, 5, 1, 1, 1)
    for player, role in enumerate(
        (
            Role.BARON,
            Role.CHEF,
            Role.EMPATH,
            Role.FORTUNE_TELLER,
            Role.UNDERTAKER,
            Role.VIRGIN,
            Role.SAINT,
            Role.IMP,
        )
    ):
        baron_keeps_base_townsfolk.add(world.start_is(player, role))
    if baron_keeps_base_townsfolk.check() != unsat:
        raise SystemExit("有男爵时不能仍是 5 名镇民")

    try:
        add_setup_rules(world.build_solver(), world, 3, 1, 1, 1)
    except ValueError:
        pass
    else:
        raise SystemExit("人数之和不等于玩家人数时应当拒绝")

    _check_demon_kill()
    print("规则自检通过")


def _check_demon_kill() -> None:
    from z3 import Not, sat, unsat

    from botc_reasoner.variables import declare_variables

    roster = (
        Role.WASHERWOMAN,
        Role.EMPATH,
        Role.FORTUNE_TELLER,
        Role.UNDERTAKER,
        Role.VIRGIN,
        Role.SAINT,
        Role.POISONER,
        Role.IMP,
    )
    world = declare_variables(8, n_nights=2, tag="kill8")
    solver = _ruled_game(world, roster)
    solver.add(world.poison_choice[2][0])
    solver.add(world.imp_choice[2][1])
    for player in world.player_ids:
        solver.add(Not(world.executed[1][player]))
    if solver.check() != sat:
        raise SystemExit("健康恶魔击杀共情者的局面应当可满足")
    refused = _ruled_game(world, roster)
    refused.add(world.poison_choice[2][0])
    refused.add(world.imp_choice[2][1])
    for player in world.player_ids:
        refused.add(Not(world.executed[1][player]))
    refused.add(Not(world.night_death[2][1]))
    if refused.check() != unsat:
        raise SystemExit("未被保护的共情者应当在恶魔当夜死亡")

    poisoned = _ruled_game(world, roster)
    poisoned.add(world.poison_choice[2][7])
    poisoned.add(world.imp_choice[2][1])
    for player in world.player_ids:
        poisoned.add(Not(world.executed[1][player]))
    poisoned.add(world.night_death[2][1])
    if poisoned.check() != unsat:
        raise SystemExit("中毒的恶魔不应当造成夜间死亡")

    soldier = (
        Role.WASHERWOMAN,
        Role.SOLDIER,
        Role.FORTUNE_TELLER,
        Role.UNDERTAKER,
        Role.VIRGIN,
        Role.SAINT,
        Role.POISONER,
        Role.IMP,
    )
    guarded = _ruled_game(world, soldier)
    guarded.add(world.poison_choice[2][0])
    guarded.add(world.imp_choice[2][1])
    for player in world.player_ids:
        guarded.add(Not(world.executed[1][player]))
    guarded.add(world.night_death[2][1])
    if guarded.check() != unsat:
        raise SystemExit("健康士兵不应当死于恶魔")

    monk = (
        Role.WASHERWOMAN,
        Role.EMPATH,
        Role.FORTUNE_TELLER,
        Role.UNDERTAKER,
        Role.MONK,
        Role.SAINT,
        Role.POISONER,
        Role.IMP,
    )
    protected = _ruled_game(world, monk)
    protected.add(world.poison_choice[2][0])
    protected.add(world.imp_choice[2][1])
    protected.add(world.monk_choice[2][1])
    for player in world.player_ids:
        protected.add(Not(world.executed[1][player]))
    protected.add(world.night_death[2][1])
    if protected.check() != unsat:
        raise SystemExit("被健康僧侣保护的玩家不应当死于恶魔")


def _ruled_game(world, roster):
    solver = world.build_solver()
    add_game_rules(solver, world, 5, 1, 1, 1)
    for player, role in enumerate(roster):
        solver.add(world.start_is(player, role))
    return solver


if __name__ == "__main__":
    _self_check()
