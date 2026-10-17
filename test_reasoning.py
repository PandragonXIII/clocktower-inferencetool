"""从文本命题推理《暗流涌动》里每名玩家的可能身份。

在仓库根目录执行::

    .venv/bin/python test_reasoning.py

先输入 ``c/f/h/d``，再逐行输入命题，空行结束。
"""

from __future__ import annotations

import sys

from z3 import And, Not, Solver, is_true, sat, unsat, unknown

from botc_reasoner import (
    MAX_PLAYERS,
    ROLE_ZH,
    Ability,
    Role,
    add_game_rules,
    declare_variables,
    minimal_unsatisfiable_subset,
    role_from_name,
)
from botc_reasoner.roles import DEMONS, MINIONS, OUTSIDERS, TOWNSFOLK
from botc_reasoner.variables import TroubleBrewingVars

_ROLE_ORDER = TOWNSFOLK + OUTSIDERS + MINIONS + DEMONS
_SKILL_ROLE = {
    Role.WASHERWOMAN: Ability.WASHERWOMAN,
    Role.LIBRARIAN: Ability.LIBRARIAN,
    Role.INVESTIGATOR: Ability.INVESTIGATOR,
    Role.CHEF: Ability.CHEF,
    Role.EMPATH: Ability.EMPATH,
    Role.FORTUNE_TELLER: Ability.FORTUNE_TELLER,
    Role.UNDERTAKER: Ability.UNDERTAKER,
    Role.RAVENKEEPER: Ability.RAVENKEEPER,
    Role.MONK: Ability.MONK,
    Role.BUTLER: Ability.BUTLER,
    Role.SLAYER: Ability.SLAYER,
    Role.POISONER: Ability.POISONER,
    Role.IMP: Ability.IMP,
}
_ALIASES = {"恶魔": "小恶魔"}


def main() -> int:
    print(_help_text())
    try:
        config_line = input("配置> ").strip()
    except EOFError:
        print("没有读到配置。", file=sys.stderr)
        return 1
    try:
        counts = _parse_config(config_line)
        print("命题> 每行一条，空行结束")
        lines = _read_facts()
        nights, facts = _parse_facts(lines, sum(counts))
    except ValueError as error:
        print(f"输入错误：{error}", file=sys.stderr)
        return 1

    print("正在推理...")
    world = declare_variables(sum(counts), n_nights=nights, tag="reason")
    solver = world.build_solver()
    solver.set("timeout", 30000)
    try:
        add_game_rules(solver, world, *counts)
        propositions = [(fact(world), label) for label, fact in facts]
    except ValueError as error:
        print(f"输入错误：{error}", file=sys.stderr)
        return 1

    solver.push()
    for expr, _label in propositions:
        solver.add(expr)
    status = solver.check()
    if status == unknown:
        print("推理超时，未能确定。")
        return 1
    if status == unsat:
        solver.pop()
        print("存在矛盾")
        try:
            subset = minimal_unsatisfiable_subset(solver, propositions)
        except TimeoutError:
            print("推理超时，未能确定矛盾来自哪些命题。")
            return 1
        for label in subset:
            print(label)
        return 0

    possible = _possible_roles(solver, world)
    if possible is None:
        print("推理超时，未能确定。")
        return 1
    if any(not roles for roles in possible):
        print("存在矛盾")
        for index, roles in enumerate(possible, start=1):
            if not roles:
                print(f"玩家 {index} 无法为任何身份")
        return 0

    for index, roles in enumerate(possible, start=1):
        names = "、".join(ROLE_ZH[role] for role in roles)
        print(f"玩家 {index}：{names}")
    return 0


def _help_text() -> str:
    roles = "、".join(ROLE_ZH[role] for role in _ROLE_ORDER)
    return f"""\
《暗流涌动》身份推理

第一段，一行，不计男爵时的人数：镇民/外来者/爪牙/恶魔
例如八人局：5/1/1/1
外来者可以是 0。四项之和是玩家人数，玩家编号从 1 开始。

第二段，每行一条命题，空行结束。角色名：{roles}
也接受「恶魔」作为「小恶魔」。时间写成 1夜、2夜 或 1天、2天。

身份 <玩家> <角色>
    开局真实身份。例：身份 1 洗衣妇
自认 <玩家> <角色>
    玩家自己相信的身份。酒鬼会相信一枚镇民标记。例：自认 2 调查员
不存在 <角色>
    这局没有这个身份：开局无人是它。镇民也不会是酒鬼的标记。例：不存在 贞洁者
夜间死亡 <夜> <玩家>
    黎明公布的夜间死亡，从第 2 夜起。例：夜间死亡 2 3
处决 <天> <玩家>
    白天处决，含投票和贞洁者。例：处决 1 4
猎手死亡 <天> <玩家>
    死于猎手射击，不是处决。例：猎手死亡 1 5
中毒 <夜> <玩家>
醉酒 <玩家>
恶魔选择 <夜> <目标>
    小恶魔当晚实际选择的人，从第 2 夜起。例：恶魔选择 2 3
僧侣保护 <夜> <目标>
投毒选择 <夜> <目标>

发动是玩家声明使用技能。信息类技能把结果写在同一行。
发动 1天 <玩家> 猎手 <目标>
发动 2夜 <玩家> 小恶魔 <目标>
发动 2夜 <玩家> 僧侣 <目标>
发动 1夜 <玩家> 投毒者 <目标>
发动 1夜 <玩家> 管家 <主人>
发动 2夜 <玩家> 守鸦人 <查看的玩家> <看到的角色>
发动 1夜 <玩家> 占卜师 <玩家A> <玩家B> 是
发动 1夜 <玩家> 占卜师 <玩家A> <玩家B> 否
发动 1夜 <玩家> 洗衣妇 <镇民角色> <玩家A> <玩家B>
发动 1夜 <玩家> 图书管理员 无
发动 1夜 <玩家> 图书管理员 <外来者角色> <玩家A> <玩家B>
发动 1夜 <玩家> 调查员 无
发动 1夜 <玩家> 调查员 <爪牙角色> <玩家A> <玩家B>
发动 1夜 <玩家> 厨师 <相邻邪恶对数>
发动 2夜 <玩家> 共情者 <0、1或2>
发动 2夜 <玩家> 送葬者 <看到的角色>
"""


def _read_facts() -> list[str]:
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip():
            break
        if line.strip().startswith("#"):
            continue
        lines.append(line.strip())
    return lines


def _parse_config(line: str) -> tuple[int, int, int, int]:
    parts = line.split("/")
    if len(parts) != 4:
        raise ValueError("配置应为 c/f/h/d，例如 5/1/1/1")
    numbers = []
    for part in parts:
        if not part.isdecimal():
            raise ValueError(f"人数必须是非负整数，收到 {part!r}")
        numbers.append(int(part))
    total = sum(numbers)
    if total < 1 or total > MAX_PLAYERS:
        raise ValueError(f"玩家人数须在 1 到 {MAX_PLAYERS} 之间，收到 {total}")
    return numbers[0], numbers[1], numbers[2], numbers[3]


def _parse_facts(lines: list[str], player_count: int) -> tuple[int, list]:
    facts = []
    nights = 1
    for line_number, line in enumerate(lines, start=1):
        try:
            fact, used_nights = _parse_fact(line, player_count)
        except ValueError as error:
            raise ValueError(f"第 {line_number} 行：{error}") from error
        facts.append((f"第{line_number}行：{line}", fact))
        nights = max(nights, used_nights)
    return nights, facts


def _parse_fact(line: str, player_count: int) -> tuple:
    tokens = line.split()
    if not tokens:
        raise ValueError("空命题")
    kind = tokens[0]
    if kind == "身份":
        player, role = _player_and_role(tokens[1:], player_count, "身份 <玩家> <角色>")
        return (lambda world, player=player, role=role: world.start_is(player, role)), 1
    if kind == "自认":
        player, role = _player_and_role(tokens[1:], player_count, "自认 <玩家> <角色>")
        return (
            lambda world, player=player, role=role: world.believes_at_start(player, role)
        ), 1
    if kind == "不存在":
        if len(tokens) != 2:
            raise ValueError("格式：不存在 <角色>")
        role = _as_role(tokens[1])
        return (lambda world, role=role: _exclude_role(world, role)), 1
    if kind == "醉酒":
        if len(tokens) != 2:
            raise ValueError("格式：醉酒 <玩家>")
        player = _player(tokens[1], player_count)
        return (lambda world, player=player: world.is_drunk[player]), 1
    if kind == "夜间死亡":
        night, player = _time_and_player(tokens[1:], player_count, "夜", "夜间死亡 <夜> <玩家>")
        if night < 2:
            raise ValueError("首夜没有夜间死亡")
        return (
            lambda world, night=night, player=player: world.night_death[night][player]
        ), night
    if kind == "处决":
        day, player = _time_and_player(tokens[1:], player_count, "天", "处决 <天> <玩家>")
        return (lambda world, day=day, player=player: world.executed[day][player]), day
    if kind == "猎手死亡":
        day, player = _time_and_player(tokens[1:], player_count, "天", "猎手死亡 <天> <玩家>")
        return (lambda world, day=day, player=player: world.slayer_kill[day][player]), day
    if kind == "中毒":
        night, player = _time_and_player(tokens[1:], player_count, "夜", "中毒 <夜> <玩家>")
        return (lambda world, night=night, player=player: world.poisoned[night][player]), night
    if kind == "恶魔选择":
        night, player = _time_and_player(tokens[1:], player_count, "夜", "恶魔选择 <夜> <目标>")
        if night < 2:
            raise ValueError("首夜恶魔不选择击杀")
        return (lambda world, night=night, player=player: world.imp_choice[night][player]), night
    if kind == "僧侣保护":
        night, player = _time_and_player(tokens[1:], player_count, "夜", "僧侣保护 <夜> <目标>")
        if night < 2:
            raise ValueError("僧侣从第 2 夜才行动")
        return (lambda world, night=night, player=player: world.monk_choice[night][player]), night
    if kind == "投毒选择":
        night, player = _time_and_player(tokens[1:], player_count, "夜", "投毒选择 <夜> <目标>")
        return (lambda world, night=night, player=player: world.poison_choice[night][player]), night
    if kind == "发动":
        return _parse_activation(tokens[1:], player_count)
    raise ValueError(f"无法识别的命题：{kind}")


def _parse_activation(tokens: list[str], player_count: int) -> tuple:
    if len(tokens) < 3:
        raise ValueError("格式：发动 <时间> <玩家> <技能> <参数>")
    when, phase = _time(tokens[0])
    actor = _player(tokens[1], player_count)
    try:
        skill = _SKILL_ROLE[_as_role(tokens[2])]
    except KeyError as error:
        raise ValueError(f"{tokens[2]} 没有可录入的技能发动") from error
    rest = tokens[3:]
    if skill is Ability.SLAYER:
        if phase != "天" or len(rest) != 1:
            raise ValueError("格式：发动 <天> <玩家> 猎手 <目标>")
        target = _player(rest[0], player_count)
        return (
            lambda world, when=when, actor=actor, target=target: world.ability_target[Ability.SLAYER][when][
                actor
            ][target]
        ), when
    if skill in {Ability.IMP, Ability.MONK, Ability.POISONER, Ability.BUTLER}:
        if phase != "夜" or len(rest) != 1:
            raise ValueError("格式：发动 <夜> <玩家> <技能> <目标>")
        _night_skill_allowed(skill, when)
        target = _player(rest[0], player_count)
        return (
            lambda world, skill=skill, when=when, actor=actor, target=target: world.ability_target[skill][
                when
            ][actor][target]
        ), when
    if skill is Ability.RAVENKEEPER:
        if phase != "夜" or len(rest) != 2:
            raise ValueError("格式：发动 <夜> <玩家> 守鸦人 <查看的玩家> <角色>")
        _night_skill_allowed(skill, when)
        target = _player(rest[0], player_count)
        role = _as_role(rest[1])
        return (
            lambda world, when=when, actor=actor, target=target, role=role: And(
                world.ability_target[Ability.RAVENKEEPER][when][actor][target],
                world.ravenkeeper_role[when][actor][role],
            )
        ), when
    if skill is Ability.FORTUNE_TELLER:
        if phase != "夜" or len(rest) != 3 or rest[2] not in {"是", "否"}:
            raise ValueError("格式：发动 <夜> <玩家> 占卜师 <玩家A> <玩家B> 是|否")
        first = _player(rest[0], player_count)
        second = _player(rest[1], player_count)
        if first == second:
            raise ValueError("占卜师的两名目标不能相同")
        yes = rest[2] == "是"
        return (
            lambda world, when=when, actor=actor, first=first, second=second, yes=yes: And(
                world.fortune_first[when][actor][first],
                world.fortune_second[when][actor][second],
                world.fortune_yes[when][actor] if yes else Not(world.fortune_yes[when][actor]),
            )
        ), when
    if skill in {Ability.WASHERWOMAN, Ability.LIBRARIAN, Ability.INVESTIGATOR}:
        if phase != "夜" or when != 1:
            raise ValueError("洗衣妇、图书管理员、调查员只在首夜")
        return _parse_pair_info(skill, actor, rest, player_count), 1
    if skill is Ability.CHEF:
        if phase != "夜" or when != 1 or len(rest) != 1 or not rest[0].isdecimal():
            raise ValueError("格式：发动 1夜 <玩家> 厨师 <数字>")
        count = int(rest[0])
        if count > player_count:
            raise ValueError(f"厨师数字不能大于玩家人数 {player_count}")
        return (lambda world, actor=actor, count=count: world.chef_number[actor][count]), 1
    if skill is Ability.EMPATH:
        if phase != "夜" or len(rest) != 1 or rest[0] not in {"0", "1", "2"}:
            raise ValueError("格式：发动 <夜> <玩家> 共情者 <0、1或2>")
        count = int(rest[0])
        return (
            lambda world, when=when, actor=actor, count=count: world.empath_number[when][actor][count]
        ), when
    if skill is Ability.UNDERTAKER:
        if phase != "夜" or len(rest) != 1:
            raise ValueError("格式：发动 <夜> <玩家> 送葬者 <角色>")
        _night_skill_allowed(skill, when)
        role = _as_role(rest[0])
        return (
            lambda world, when=when, actor=actor, role=role: world.undertaker_role[when][actor][role]
        ), when
    raise ValueError(f"尚未支持的技能：{tokens[2]}")


def _parse_pair_info(skill: Ability, actor: int, rest: list[str], player_count: int) -> object:
    if skill is not Ability.WASHERWOMAN and len(rest) == 1 and rest[0] == "无":
        none = {Ability.LIBRARIAN: "librarian_none", Ability.INVESTIGATOR: "investigator_none"}[skill]
        return lambda world, actor=actor, none=none: getattr(world, none)[actor]
    if len(rest) != 3:
        name = {Ability.WASHERWOMAN: "洗衣妇", Ability.LIBRARIAN: "图书管理员", Ability.INVESTIGATOR: "调查员"}[
            skill
        ]
        raise ValueError(f"格式：发动 1夜 <玩家> {name} <角色> <玩家A> <玩家B>")
    role = _as_role(rest[0])
    first = _player(rest[1], player_count)
    second = _player(rest[2], player_count)
    if first == second:
        raise ValueError("两名玩家不能相同")
    expected = {
        Ability.WASHERWOMAN: TOWNSFOLK,
        Ability.LIBRARIAN: OUTSIDERS,
        Ability.INVESTIGATOR: MINIONS,
    }[skill]
    if role not in expected:
        raise ValueError(f"{ROLE_ZH[role]} 不是这次技能会看到的角色类别")
    prefix = {
        Ability.WASHERWOMAN: "washerwoman",
        Ability.LIBRARIAN: "librarian",
        Ability.INVESTIGATOR: "investigator",
    }[skill]
    return lambda world, actor=actor, role=role, first=first, second=second, prefix=prefix: And(
        getattr(world, f"{prefix}_role")[actor][role],
        getattr(world, f"{prefix}_first")[actor][first],
        getattr(world, f"{prefix}_second")[actor][second],
    )


def _night_skill_allowed(skill: Ability, night: int) -> None:
    if skill in {Ability.IMP, Ability.MONK, Ability.RAVENKEEPER, Ability.UNDERTAKER} and night < 2:
        raise ValueError("该技能从第 2 夜才行动")


def _exclude_role(world: TroubleBrewingVars, role: Role):
    terms = [Not(world.start_is(player, role)) for player in world.player_ids]
    if role in TOWNSFOLK:
        terms.append(Not(world.drunk_mask[role]))
    return And(*terms)


def _player_and_role(tokens: list[str], player_count: int, sample: str) -> tuple[int, Role]:
    if len(tokens) != 2:
        raise ValueError(f"格式：{sample}")
    return _player(tokens[0], player_count), _as_role(tokens[1])


def _time_and_player(tokens: list[str], player_count: int, phase: str, sample: str) -> tuple[int, int]:
    if len(tokens) != 2:
        raise ValueError(f"格式：{sample}")
    number, got = _time(tokens[0])
    if got != phase:
        raise ValueError(f"格式：{sample}")
    return number, _player(tokens[1], player_count)


def _time(token: str) -> tuple[int, str]:
    text = token[1:] if token.startswith("第") else token
    if len(text) < 2 or text[-1] not in {"夜", "天"} or not text[:-1].isdecimal() or int(text[:-1]) < 1:
        raise ValueError(f"时间应为 1夜 或 1天，收到 {token}")
    return int(text[:-1]), text[-1]


def _player(token: str, player_count: int) -> int:
    if not token.isdecimal() or int(token) < 1 or int(token) > player_count:
        raise ValueError(f"玩家编号须在 1 到 {player_count} 之间，收到 {token}")
    return int(token) - 1


def _as_role(token: str) -> Role:
    try:
        return role_from_name(_ALIASES.get(token, token))
    except KeyError as error:
        raise ValueError(str(error)) from error


def _possible_roles(solver: Solver, world: TroubleBrewingVars) -> list[list[Role]] | None:
    found = []
    for player in world.player_ids:
        roles: list[Role] = []
        solver.push()
        while True:
            status = solver.check()
            if status == unknown:
                solver.pop()
                return None
            if status != sat:
                break
            model = solver.model()
            role = next(
                candidate
                for candidate in _ROLE_ORDER
                if is_true(model.eval(world.start_is(player, candidate), model_completion=True))
            )
            roles.append(role)
            solver.add(Not(world.start_is(player, role)))
        solver.pop()
        roles.sort(key=_ROLE_ORDER.index)
        found.append(roles)
    return found


if __name__ == "__main__":
    raise SystemExit(main())
