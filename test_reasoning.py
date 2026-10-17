"""从文本命题推理《暗流涌动》里每名玩家的可能身份，并估计概率。

在仓库根目录执行::

    .venv/bin/python test_reasoning.py

先输入 ``c/f/h/d``，再逐行输入命题，空行结束。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from typing import Callable

from z3 import And, Not, Solver, is_true, sat, unsat, unknown

from botc_reasoner import (
    MAX_PLAYERS,
    ROLE_ZH,
    Ability,
    AbilityObservation,
    Role,
    add_game_rules,
    declare_variables,
    estimate_role_probabilities,
    minimal_unsatisfiable_subset,
    role_from_name,
    trusted_activation,
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


@dataclass(frozen=True)
class Statement:
    """一条玩家输入。

    ``setup_only`` 为真时，这条确定前提只限制开局身份或自认，抽样可以不调用求解器。
    公开事实和本人技能会把 ``setup_only`` 设为假，从而进入求解。
    他人自称的 ``mode`` 是 ``soft_role`` 或 ``soft_ability``，不进入求解。
    """

    label: str
    nights: int
    mode: str
    build: Callable | None = None
    player: int | None = None
    role: Role | None = None
    ability: Ability | None = None
    when: int | None = None
    target: int | None = None
    setup_only: bool = False
    pin: str | None = None


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
        nights, statements = _parse_facts(lines, sum(counts))
    except ValueError as error:
        print(f"输入错误：{error}", file=sys.stderr)
        return 1

    print("正在推理...")
    report = _reason(counts, nights, statements)
    if report is None:
        return 1
    for line in report:
        print(line)
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

来源要分开写。公开事实可靠性是 100%，直接限制可能身份。
你自己的身份只有酒鬼能推翻。你自己秘密发动的技能同样进入推理。
其他玩家的自称不限制可能身份，只按较低的可靠性改变概率。

我是 <玩家> <角色>
    你自己看到的身份。例：我是 1 占卜师
    「自认」与「我是」相同。
自称 <玩家> <角色>
    另一名玩家声称的身份。例：自称 2 洗衣妇
    每句自称按可信度 0.7 进入采信组合。组权重是三项的乘积：
    置信度 0.7^采信人数 × 0.3^忽略人数；
    忽略人数 i 超过邪恶人数 E 时再乘 1/3^(i-E)；
    被忽略的技能信息先把写法数乘成 M，再乘 1/(1+log2(M))。只自称身份时 M = 1。
    忽略人数不能超过 E + floor(G/5) - O。
    组内只保留被采信的身份和技能读数说得通的世界。
    某一夜的信息是被投毒才失效时，该局再乘 1/当夜入夜时仍存活的善良人数，以及当夜写法数的 1/(1+log2(M))。
    酒鬼使各夜信息一起失效时，把这些写法数合成一个 M，再乘一次 1/(1+log2(M))。
    红鲱鱼整局是同一名善良玩家（可以已死，也可以是占卜师自己）。
    能同时解释全部清醒占卜结果的善良玩家占全部善良玩家的比例，也乘进该局。
    洗衣妇、图书管理员、调查员若清醒属实，把陪衬人数和在场的该类角色人数相乘得到 M，
    再乘 1/(1+log2(M))。调查员通常只有一名爪牙，M 就只剩陪衬人数。
    这个乘数留在合计里，不在组内被归一掉。
    逻辑上无解的组不计入。自称镇民时，酒鬼的面具就是该镇民。
身份 <玩家> <角色>
    已经确定的真实身份，可靠性 100%。例：身份 3 小恶魔
不存在 <角色>
    这局没有这个身份：开局无人是它。镇民也不会是酒鬼的标记。例：不存在 贞洁者

公开事实，可靠性 100%：
夜间死亡 <夜> <玩家>
    黎明公布的夜间死亡，从第 2 夜起。例：夜间死亡 2夜 3
无人死亡 <夜>
    这一夜黎明没有人死于夜间。某一夜若没有人死去，必须输入这一条，
    否则求解器会把「谁在这一夜死去」当成可以自由分配。例：无人死亡 2夜
    也可以写成：夜间死亡 2夜 无
处决 <天> <玩家>
    白天处决，含投票和贞洁者。例：处决 1天 4
无人处决 <天>
    这一天没有人被处决。某一天若没有人被处决，必须输入这一条，
    否则求解器会把「谁被处决」当成可以自由分配。例：无人处决 1天
    也可以写成：处决 1天 无
猎手死亡 <天> <玩家>
    死于猎手射击，不是处决。例：猎手死亡 1天 5

以下也是确定事实：中毒 <夜> <玩家>、醉酒 <玩家>、
恶魔选择 <夜> <目标>、僧侣保护 <夜> <目标>、投毒选择 <夜> <目标>。

技能要写明是你自己发动的，还是别人自称的。猎手射击当众发生，
「我发动」和「自称发动」都按公开事实记入，并且不因此认定射手身份。
我发动 1夜 <玩家> 占卜师 <玩家A> <玩家B> 是
我发动 1夜 <玩家> 占卜师 <玩家A> <玩家B> 否
自称发动 1夜 <玩家> 洗衣妇 <镇民角色> <玩家A> <玩家B>
我发动 1天 <玩家> 猎手 <目标>
我发动 2夜 <玩家> 小恶魔 <目标>
我发动 2夜 <玩家> 僧侣 <目标>
我发动 1夜 <玩家> 投毒者 <目标>
我发动 1夜 <玩家> 管家 <主人>
我发动 2夜 <玩家> 守鸦人 <查看的玩家> <看到的角色>
我发动 1夜 <玩家> 图书管理员 无
我发动 1夜 <玩家> 图书管理员 <外来者角色> <玩家A> <玩家B>
我发动 1夜 <玩家> 调查员 无
我发动 1夜 <玩家> 调查员 <爪牙角色> <玩家A> <玩家B>
我发动 1夜 <玩家> 厨师 <相邻邪恶对数>
我发动 2夜 <玩家> 共情者 <0、1或2>
我发动 2夜 <玩家> 送葬者 <看到的角色>
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


def _parse_facts(lines: list[str], player_count: int) -> tuple[int, list[Statement]]:
    statements = []
    nights = 1
    for line_number, line in enumerate(lines, start=1):
        try:
            statement = _parse_fact(line, player_count)
        except ValueError as error:
            raise ValueError(f"第 {line_number} 行：{error}") from error
        statements.append(replace(statement, label=f"第{line_number}行：{line}"))
        nights = max(nights, statement.nights)
    return nights, statements


def _parse_fact(line: str, player_count: int) -> Statement:
    tokens = line.split()
    if not tokens:
        raise ValueError("空命题")
    kind = tokens[0]
    if kind in {"我是", "自认"}:
        player, role = _player_and_role(tokens[1:], player_count, "我是 <玩家> <角色>")
        return _belief(player, role)
    if kind == "自称":
        player, role = _player_and_role(tokens[1:], player_count, "自称 <玩家> <角色>")
        return Statement(label="", nights=1, mode="soft_role", player=player, role=role)
    if kind == "身份":
        player, role = _player_and_role(tokens[1:], player_count, "身份 <玩家> <角色>")
        return Statement(
            label="",
            nights=1,
            mode="hard",
            build=lambda world, player=player, role=role: world.start_is(player, role),
            player=player,
            role=role,
            setup_only=True,
            pin="role",
        )
    if kind == "不存在":
        if len(tokens) != 2:
            raise ValueError("格式：不存在 <角色>")
        role = _as_role(tokens[1])
        return Statement(
            label="",
            nights=1,
            mode="hard",
            build=lambda world, role=role: _exclude_role(world, role),
            role=role,
            setup_only=True,
            pin="absent",
        )
    if kind == "醉酒":
        if len(tokens) != 2:
            raise ValueError("格式：醉酒 <玩家>")
        player = _player(tokens[1], player_count)
        return Statement(
            label="",
            nights=1,
            mode="hard",
            build=lambda world, player=player: world.is_drunk[player],
            player=player,
            setup_only=True,
            pin="drunk",
        )
    if kind in {"夜间死亡", "无人死亡"}:
        return _night_death_statement(tokens, player_count, kind)
    if kind in {"处决", "无人处决"}:
        return _execution_statement(tokens, player_count, kind)
    if kind == "猎手死亡":
        day, player = _time_and_player(tokens[1:], player_count, "天", "猎手死亡 <天> <玩家>")
        return _public(lambda world, day=day, player=player: world.slayer_kill[day][player], day)
    if kind == "中毒":
        night, player = _time_and_player(tokens[1:], player_count, "夜", "中毒 <夜> <玩家>")
        return _public(lambda world, night=night, player=player: world.poisoned[night][player], night)
    if kind == "恶魔选择":
        night, player = _time_and_player(tokens[1:], player_count, "夜", "恶魔选择 <夜> <目标>")
        if night < 2:
            raise ValueError("首夜恶魔不选择击杀")
        return _public(lambda world, night=night, player=player: world.imp_choice[night][player], night)
    if kind == "僧侣保护":
        night, player = _time_and_player(tokens[1:], player_count, "夜", "僧侣保护 <夜> <目标>")
        if night < 2:
            raise ValueError("僧侣从第 2 夜才行动")
        return _public(lambda world, night=night, player=player: world.monk_choice[night][player], night)
    if kind == "投毒选择":
        night, player = _time_and_player(tokens[1:], player_count, "夜", "投毒选择 <夜> <目标>")
        return _public(
            lambda world, night=night, player=player: world.poison_choice[night][player],
            night,
        )
    if kind == "发动":
        raise ValueError("请写「我发动」或「自称发动」")
    if kind in {"我发动", "自称发动"}:
        return _activation_statement(tokens[1:], player_count, own=kind == "我发动")
    raise ValueError(f"无法识别的命题：{kind}")


def _belief(player: int, role: Role) -> Statement:
    return Statement(
        label="",
        nights=1,
        mode="hard",
        build=lambda world, player=player, role=role: world.believes_at_start(player, role),
        player=player,
        role=role,
        setup_only=True,
        pin="belief",
    )


def _night_death_statement(tokens: list[str], player_count: int, kind: str) -> Statement:
    """夜间死亡。``无人死亡 <夜>`` 或 ``夜间死亡 <夜> 无`` 表示这一夜没有人死去。"""

    if kind == "无人死亡" or (len(tokens) == 3 and tokens[2] == "无"):
        if len(tokens) not in {2, 3}:
            raise ValueError("格式：无人死亡 <夜>")
        night, phase = _time(tokens[1])
        if phase != "夜":
            raise ValueError("格式：无人死亡 <夜>")
        if night < 2:
            raise ValueError("首夜没有夜间死亡")
        return _public(
            lambda world, night=night: And(
                *[Not(world.night_death[night][player]) for player in world.player_ids]
            ),
            night,
        )
    night, player = _time_and_player(tokens[1:], player_count, "夜", "夜间死亡 <夜> <玩家>")
    if night < 2:
        raise ValueError("首夜没有夜间死亡")
    return _public(
        lambda world, night=night, player=player: world.night_death[night][player],
        night,
    )


def _execution_statement(tokens: list[str], player_count: int, kind: str) -> Statement:
    """处决。``无人处决 <天>`` 或 ``处决 <天> 无`` 表示这一天没有人被处决。"""

    if kind == "无人处决" or (len(tokens) == 3 and tokens[2] == "无"):
        if len(tokens) not in {2, 3}:
            raise ValueError("格式：无人处决 <天>")
        day, phase = _time(tokens[1])
        if phase != "天":
            raise ValueError("格式：无人处决 <天>")
        return _public(
            lambda world, day=day: And(
                *[Not(world.executed[day][player]) for player in world.player_ids]
            ),
            day,
        )
    day, player = _time_and_player(tokens[1:], player_count, "天", "处决 <天> <玩家>")
    return _public(lambda world, day=day, player=player: world.executed[day][player], day)


def _public(build: Callable, nights: int) -> Statement:
    return Statement(label="", nights=nights, mode="hard", build=build, setup_only=False)


def _activation_statement(tokens: list[str], player_count: int, *, own: bool) -> Statement:
    build, nights, ability, actor, when, target = _parse_activation(tokens, player_count)
    public_shot = ability is Ability.SLAYER
    if own or public_shot:
        return Statement(
            label="",
            nights=nights,
            mode="hard",
            build=build,
            player=actor,
            ability=ability,
            when=when,
            target=target,
            setup_only=False,
        )
    return Statement(
        label="",
        nights=nights,
        mode="soft_ability",
        build=build,
        player=actor,
        ability=ability,
        when=when,
        target=target,
    )


def _parse_activation(tokens: list[str], player_count: int) -> tuple:
    if len(tokens) < 3:
        raise ValueError("格式：我发动 <时间> <玩家> <技能> <参数>")
    when, phase = _time(tokens[0])
    actor = _player(tokens[1], player_count)
    try:
        skill = _SKILL_ROLE[_as_role(tokens[2])]
    except KeyError as error:
        raise ValueError(f"{tokens[2]} 没有可录入的技能发动") from error
    rest = tokens[3:]
    if skill is Ability.SLAYER:
        if phase != "天" or len(rest) != 1:
            raise ValueError("格式：我发动 <天> <玩家> 猎手 <目标>")
        target = _player(rest[0], player_count)
        return (
            lambda world, when=when, actor=actor, target=target: world.ability_target[Ability.SLAYER][when][
                actor
            ][target]
        ), when, skill, actor, when, target
    if skill in {Ability.IMP, Ability.MONK, Ability.POISONER, Ability.BUTLER}:
        if phase != "夜" or len(rest) != 1:
            raise ValueError("格式：我发动 <夜> <玩家> <技能> <目标>")
        _night_skill_allowed(skill, when)
        target = _player(rest[0], player_count)
        return (
            lambda world, skill=skill, when=when, actor=actor, target=target: world.ability_target[skill][
                when
            ][actor][target]
        ), when, skill, actor, when, target
    if skill is Ability.RAVENKEEPER:
        if phase != "夜" or len(rest) != 2:
            raise ValueError("格式：我发动 <夜> <玩家> 守鸦人 <查看的玩家> <角色>")
        _night_skill_allowed(skill, when)
        target = _player(rest[0], player_count)
        role = _as_role(rest[1])
        return (
            lambda world, when=when, actor=actor, target=target, role=role: And(
                world.ability_target[Ability.RAVENKEEPER][when][actor][target],
                world.ravenkeeper_role[when][actor][role],
            )
        ), when, skill, actor, when, target
    if skill is Ability.FORTUNE_TELLER:
        if phase != "夜" or len(rest) != 3 or rest[2] not in {"是", "否"}:
            raise ValueError("格式：我发动 <夜> <玩家> 占卜师 <玩家A> <玩家B> 是|否")
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
        ), when, skill, actor, when, None
    if skill in {Ability.WASHERWOMAN, Ability.LIBRARIAN, Ability.INVESTIGATOR}:
        if phase != "夜" or when != 1:
            raise ValueError("洗衣妇、图书管理员、调查员只在首夜")
        return _parse_pair_info(skill, actor, rest, player_count), 1, skill, actor, when, None
    if skill is Ability.CHEF:
        if phase != "夜" or when != 1 or len(rest) != 1 or not rest[0].isdecimal():
            raise ValueError("格式：我发动 1夜 <玩家> 厨师 <数字>")
        count = int(rest[0])
        if count > player_count:
            raise ValueError(f"厨师数字不能大于玩家人数 {player_count}")
        return (
            lambda world, actor=actor, count=count: world.chef_number[actor][count]
        ), 1, skill, actor, when, None
    if skill is Ability.EMPATH:
        if phase != "夜" or len(rest) != 1 or rest[0] not in {"0", "1", "2"}:
            raise ValueError("格式：我发动 <夜> <玩家> 共情者 <0、1或2>")
        count = int(rest[0])
        return (
            lambda world, when=when, actor=actor, count=count: world.empath_number[when][actor][count]
        ), when, skill, actor, when, None
    if skill is Ability.UNDERTAKER:
        if phase != "夜" or len(rest) != 1:
            raise ValueError("格式：我发动 <夜> <玩家> 送葬者 <角色>")
        _night_skill_allowed(skill, when)
        role = _as_role(rest[0])
        return (
            lambda world, when=when, actor=actor, role=role: world.undertaker_role[when][actor][role]
        ), when, skill, actor, when, None
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


def _reason(
    counts: tuple[int, int, int, int],
    nights: int,
    statements: list[Statement],
) -> list[str] | None:
    player_count = sum(counts)
    world = declare_variables(player_count, n_nights=nights, tag="reason")
    solver = world.build_solver()
    solver.set("timeout", 30000)
    beliefs: list[tuple[int, Role]] = []
    pinned: list[tuple[int, Role]] = []
    absent: list[Role] = []
    drunks: list[int] = []
    soft_roles: list[tuple[int, Role]] = []
    soft_abilities: list[AbilityObservation] = []
    trusted_abilities: list[AbilityObservation] = []
    propositions: list[tuple] = []
    try:
        add_game_rules(solver, world, *counts)
        for statement in statements:
            _collect_statement(
                world,
                statement,
                beliefs,
                pinned,
                absent,
                drunks,
                soft_roles,
                soft_abilities,
                trusted_abilities,
                propositions,
            )
    except ValueError as error:
        print(f"输入错误：{error}", file=sys.stderr)
        return None

    solver.push()
    for expr, _label in propositions:
        solver.add(expr)
    status = solver.check()
    if status == unknown:
        print("推理超时，未能确定。")
        return None
    if status == unsat:
        solver.pop()
        try:
            subset = minimal_unsatisfiable_subset(solver, propositions)
        except TimeoutError:
            print("推理超时，未能确定矛盾来自哪些命题。")
            return None
        return ["存在矛盾", *subset]

    possible = _possible_roles(solver, world)
    if possible is None:
        print("推理超时，未能确定。")
        return None
    if any(not roles for roles in possible):
        lines = ["存在矛盾"]
        for index, roles in enumerate(possible, start=1):
            if not roles:
                lines.append(f"玩家 {index} 无法为任何身份")
        return lines

    probabilities = estimate_role_probabilities(
        player_count,
        counts,
        beliefs=beliefs,
        pinned_roles=pinned,
        absent_roles=absent,
        drunk_players=drunks,
        soft_roles=soft_roles,
        soft_abilities=soft_abilities,
        trusted_abilities=trusted_abilities,
        solver=solver,
        world=world,
    )
    if probabilities is None:
        lines = ["没有抽到可行世界，因此只列出可能身份。"]
    else:
        lines = ["概率是各组权重乘各局的干扰乘数，再按这些乘积合计归一。逻辑上无解的组不计入。"]
    for index, roles in enumerate(possible, start=1):
        player_probability = None if probabilities is None else probabilities[index - 1]
        lines.append(_format_player(index, roles, player_probability))
    return lines


def _collect_statement(
    world: TroubleBrewingVars,
    statement: Statement,
    beliefs: list[tuple[int, Role]],
    pinned: list[tuple[int, Role]],
    absent: list[Role],
    drunks: list[int],
    soft_roles: list[tuple[int, Role]],
    soft_abilities: list[AbilityObservation],
    trusted_abilities: list[AbilityObservation],
    propositions: list[tuple],
) -> None:
    if statement.mode == "soft_role":
        assert statement.player is not None and statement.role is not None
        soft_roles.append((statement.player, statement.role))
        return
    assert statement.build is not None
    claim = statement.build(world)
    if statement.mode == "soft_ability":
        assert statement.player is not None and statement.ability is not None and statement.when is not None
        soft_abilities.append(
            AbilityObservation(
                statement.player,
                statement.ability,
                statement.when,
                claim,
                statement.target,
            )
        )
        return
    if statement.pin == "belief":
        assert statement.player is not None and statement.role is not None
        beliefs.append((statement.player, statement.role))
        propositions.append((claim, statement.label))
        return
    if statement.pin == "role":
        assert statement.player is not None and statement.role is not None
        pinned.append((statement.player, statement.role))
        propositions.append((claim, statement.label))
        return
    if statement.pin == "absent":
        assert statement.role is not None
        absent.append(statement.role)
        propositions.append((claim, statement.label))
        return
    if statement.pin == "drunk":
        assert statement.player is not None
        drunks.append(statement.player)
        propositions.append((claim, statement.label))
        return
    if statement.ability is None:
        propositions.append((claim, statement.label))
        return
    assert statement.player is not None and statement.when is not None
    observation = AbilityObservation(
        statement.player,
        statement.ability,
        statement.when,
        claim,
        statement.target,
    )
    propositions.append((trusted_activation(world, observation), statement.label))
    if statement.ability is Ability.SLAYER:
        return
    trusted_abilities.append(observation)
    if statement.ability is Ability.IMP:
        if statement.when == 2:
            pinned.append((statement.player, Role.IMP))
        return
    beliefs.append((statement.player, Role(statement.ability.value)))


def _format_player(index: int, roles: list[Role], probs: dict[Role, float] | None) -> str:
    if not probs:
        names = "、".join(ROLE_ZH[role] for role in roles)
        return f"玩家 {index}：{names}"
    total = sum(probs.get(role, 0.0) for role in roles)
    if total <= 0:
        names = "、".join(ROLE_ZH[role] for role in roles)
        return f"玩家 {index}：{names}"
    weighted = sorted(
        ((role, probs.get(role, 0.0) / total) for role in roles),
        key=lambda item: (-item[1], _ROLE_ORDER.index(item[0])),
    )
    shown = [(role, share) for role, share in weighted if share >= 0.005]
    rest = sum(share for _role, share in weighted if share < 0.005)
    omitted = len(weighted) - len(shown)
    if not shown:
        shown = weighted[:3]
        rest = sum(share for _role, share in weighted[3:])
        omitted = max(0, len(weighted) - len(shown))
    parts = [f"{ROLE_ZH[role]} {share * 100:.1f}%" for role, share in shown]
    text = "、".join(parts)
    if omitted and rest >= 0.005:
        text += f"（其余 {omitted} 个可能身份合计 {rest * 100:.1f}%）"
    elif omitted:
        text += f"（另有 {omitted} 个可能身份未进入本次抽样）"
    return f"玩家 {index}：{text}"


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
