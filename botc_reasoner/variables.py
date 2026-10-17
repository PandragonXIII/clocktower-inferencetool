"""《暗流涌动》的 Z3 推理变量。

这里只声明未知量，并加上「这些布尔量是什么形状」的域公理
（每位玩家在每个断面恰好一个角色、每次行动恰好一个目标等）。
人数配置、中毒是否生效、死亡结算、胜负还不在这里。那些是剧本规则，下一步再写成约束。

玩家座位 0 .. n-1，最多 20 人，圆桌相邻：上家 ``(i - 1) % n``，下家 ``(i + 1) % n``。
夜数按本局实际长度传入。默认夜数等于玩家人数，只是为了在还没裁剪时间轴时也能建出来。

时间轴（第 k 夜之后是第 k 天）::

    第 k 夜入夜   role_night_start[k] / alive_night_start[k]
        投毒者 → 僧侣 → 间谍（看见入夜身份）
        → 小恶魔（可能星坠）→ 守鸦人、送葬者、共情者、占卜师（看见黎明身份）
    第 k 夜黎明   role_dawn[k] / alive_dawn[k]
    第 k 天       提名、投票、处决、猎手
    第 k 天结束   等于第 k+1 夜入夜；最后一天则是 role_end / alive_end

首夜没有恶魔击杀，因此没有 monk / imp / starpass / mayor_bounce / night_death 的第 1 夜变量。

信息类技能的结果是玩家收到的那条信息，单独记在技能发动里。
它还没有被要求等于真实世界算出来的值。能力生效时才会加上这条等式；
中毒或醉酒时不加，虚假信息就不限制世界。

自认身份、中毒、醉酒、技能发动是单独的未知量，还没有和真实身份绑在一起。
因此「玩家输入自己是调查员」钉住的是自认身份：他可以真的是调查员，也可以是拿着调查员标记的酒鬼。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from z3 import And, AtLeast, AtMost, Bool, BoolRef, Implies, Not, Or, Solver

from botc_reasoner.roles import (
    GOOD_ROLES,
    MINIONS,
    OUTSIDERS,
    RECLUSE_MASK_ROLES,
    SPY_MASK_ROLES,
    TOWNSFOLK,
    Role,
)

MAX_PLAYERS = 20

G_ROLE = "身份"
G_BELIEF = "自认身份"
G_ALIVE = "存活"
G_STATUS = "状态"
G_SECRET = "开局秘密"
G_NIGHT = "夜间行动"
G_ACT = "技能发动"
G_DEATH = "死亡与处决"
G_VOTE = "提名与投票"
G_MASK = "误注册"


class Moment(Enum):
    """身份与存活的时间断面。"""

    NIGHT_START = "night_start"
    DAWN = "dawn"
    AFTER_LAST_DAY = "after_last_day"


class Ability(Enum):
    """玩家可以报告「我发动了这个技能」的能力。

    声明本身是信息：声明者可以不是这个角色，那时不会产生技能效果。
    信息类技能另外带有玩家收到的结果。士兵、镇长、贞洁者、圣徒、男爵、
    红唇女郎没有可单独记录的结果。间谍看到的是整本魔典，不另做一条结果。
    """

    WASHERWOMAN = "washerwoman"
    LIBRARIAN = "librarian"
    INVESTIGATOR = "investigator"
    CHEF = "chef"
    EMPATH = "empath"
    FORTUNE_TELLER = "fortune_teller"
    UNDERTAKER = "undertaker"
    RAVENKEEPER = "ravenkeeper"
    MONK = "monk"
    BUTLER = "butler"
    SLAYER = "slayer"
    POISONER = "poisoner"
    IMP = "imp"


# 只在首夜醒来。猎手在白天。僧侣、守鸦人、送葬者、小恶魔从第 2 夜开始。
_FIRST_NIGHT_ABILITIES = frozenset(
    {Ability.WASHERWOMAN, Ability.LIBRARIAN, Ability.INVESTIGATOR, Ability.CHEF}
)
_DEMON_NIGHT_ABILITIES = frozenset(
    {Ability.MONK, Ability.RAVENKEEPER, Ability.UNDERTAKER, Ability.IMP}
)
# 玩家自己选择一名目标。信息结果里由说书人指出的玩家不在这里。
_SINGLE_TARGET_ABILITIES = frozenset(
    {
        Ability.SLAYER,
        Ability.MONK,
        Ability.RAVENKEEPER,
        Ability.BUTLER,
        Ability.POISONER,
        Ability.IMP,
    }
)


class QueryKind(Enum):
    """会让间谍或陌客被当成别的角色的一次信息结算。

    伪装变量是「这次结算里，说书人让他显示成哪一个角色」。
    同一名玩家在洗衣妇查询和共情者查询上可以不同。
    酒鬼的虚假能力不会产生查询：那些信息不约束真实世界。

    读法（规则模块按这个解释，域公理本身不做这层过滤）：

    - 洗衣妇：间谍的镇民伪装可被指认；陌客的邪恶伪装不会使他变成镇民。
    - 图书管理员：间谍的外来者伪装可被指认；陌客若伪装成邪恶，则这次不算外来者。
    - 调查员：间谍不伪装时可以就是那名爪牙；陌客只有伪装成爪牙（不是小恶魔）才算。
    - 厨师、共情者：间谍有善良伪装则这次算善良；陌客有邪恶伪装则这次算邪恶。
    - 占卜师、猎手：只有陌客伪装成小恶魔时才算恶魔。间谍的善良伪装不是恶魔。
    - 送葬者、守鸦人：有伪装就展示伪装，否则展示该时间断面上的真实角色。
    - 贞洁者：间谍伪装成镇民才算镇民。陌客的邪恶伪装不是镇民。
    """

    WASHERWOMAN = "washerwoman"
    LIBRARIAN = "librarian"
    INVESTIGATOR = "investigator"
    CHEF = "chef"
    EMPATH = "empath"
    FORTUNE_TELLER = "fortune_teller"
    UNDERTAKER = "undertaker"
    RAVENKEEPER = "ravenkeeper"
    SLAYER = "slayer"
    VIRGIN = "virgin"


QUERY_ZH: dict[QueryKind, str] = {
    QueryKind.WASHERWOMAN: "洗衣妇",
    QueryKind.LIBRARIAN: "图书管理员",
    QueryKind.INVESTIGATOR: "调查员",
    QueryKind.CHEF: "厨师",
    QueryKind.EMPATH: "共情者",
    QueryKind.FORTUNE_TELLER: "占卜师",
    QueryKind.UNDERTAKER: "送葬者",
    QueryKind.RAVENKEEPER: "守鸦人",
    QueryKind.SLAYER: "猎手",
    QueryKind.VIRGIN: "贞洁者",
}

_ONCE = frozenset(
    {
        QueryKind.WASHERWOMAN,
        QueryKind.LIBRARIAN,
        QueryKind.INVESTIGATOR,
        QueryKind.CHEF,
        QueryKind.RAVENKEEPER,
        QueryKind.SLAYER,
        QueryKind.VIRGIN,
    }
)
_EACH_NIGHT = frozenset({QueryKind.EMPATH, QueryKind.FORTUNE_TELLER})


@dataclass(frozen=True)
class Query:
    """一次具体的信息结算。`night is None` 表示整局只有一次。"""

    kind: QueryKind
    night: int | None = None

    def __post_init__(self) -> None:
        if self.kind in _ONCE:
            if self.night is not None:
                raise ValueError(f"{self.kind.value} 整局只有一次，不能带夜数")
            return
        if self.night is None or self.night < 1:
            raise ValueError(f"{self.kind.value} 需要正的夜数")
        if self.kind is QueryKind.UNDERTAKER and self.night < 2:
            raise ValueError("送葬者不在首夜行动")

    @property
    def slug(self) -> str:
        if self.night is None:
            return self.kind.value
        return f"{self.kind.value}_n{self.night}"

    def label(self) -> str:
        zh = QUERY_ZH[self.kind]
        if self.night is None:
            return zh
        return f"{zh}·第{self.night}夜"


def build_queries(n_nights: int) -> tuple[Query, ...]:
    queries: list[Query] = [Query(kind) for kind in QueryKind if kind in _ONCE]
    for night in range(1, n_nights + 1):
        for kind in QueryKind:
            if kind in _EACH_NIGHT:
                queries.append(Query(kind, night))
        if night >= 2:
            queries.append(Query(QueryKind.UNDERTAKER, night))
    return tuple(queries)


def _exactly_one(xs: list[BoolRef]) -> BoolRef:
    if not xs:
        raise ValueError("恰好为一的列表是空的")
    if len(xs) == 1:
        return xs[0]
    return And(AtLeast(*xs, 1), AtMost(*xs, 1))


def _at_most_one(xs: list[BoolRef]) -> BoolRef | None:
    if len(xs) <= 1:
        return None
    return AtMost(*xs, 1)


class TroubleBrewingVars:
    """一局游戏的全部布尔未知量。

    同一个 Z3 上下文里，相同 ``tag`` 会复用同名布尔量。
    同时建两局时请使用不同的 tag。
    """

    def __init__(
        self,
        n_players: int,
        n_nights: int | None = None,
        *,
        max_nominations: int | None = None,
        tag: str = "tb",
    ) -> None:
        if not tag.isidentifier():
            raise ValueError(f"tag 必须是合法标识符，收到 {tag!r}")
        self.tag = tag
        self.n_players = _positive_int("玩家人数", n_players)
        if not 1 <= self.n_players <= MAX_PLAYERS:
            raise ValueError(f"玩家人数须在 1 到 {MAX_PLAYERS} 之间，收到 {n_players}")
        if n_nights is None:
            n_nights = self.n_players
        self.n_nights = _positive_int("夜数", n_nights)
        if max_nominations is None:
            max_nominations = self.n_players
        self.max_nominations = _positive_int("每天提名上限", max_nominations)
        if self.max_nominations > self.n_players:
            raise ValueError(
                f"每天提名上限不能超过玩家人数 {self.n_players}，收到 {max_nominations}"
            )

        self.player_ids = range(self.n_players)
        self.nights = range(1, self.n_nights + 1)
        self.days = range(1, self.n_nights + 1)
        # 小恶魔、僧侣从第 2 夜才行动。
        self.demon_nights = range(2, self.n_nights + 1)
        self.nomination_ids = range(1, self.max_nominations + 1)
        self.queries = build_queries(self.n_nights)

        self._groups: dict[str, list[BoolRef]] = {}
        self._names: set[str] = set()
        self._role_frames: list[dict[int, dict[Role, BoolRef]]] = []
        self._axiom_cache: list[BoolRef] | None = None

        self._declare_roles()
        self._declare_beliefs()
        self._declare_alive()
        self._declare_status()
        self._declare_secrets()
        self._declare_night_actions()
        self._declare_abilities()
        self._declare_deaths()
        self._declare_nominations()
        self._declare_registration()

    def _bool(self, group: str, name: str) -> BoolRef:
        full = f"{self.tag}_{name}"
        if full in self._names:
            raise RuntimeError(f"重复的变量名：{full}")
        self._names.add(full)
        var = Bool(full)
        self._groups.setdefault(group, []).append(var)
        return var

    def _role_frame(self, slug: str, group: str = G_ROLE) -> dict[int, dict[Role, BoolRef]]:
        frame = {
            player: {
                role: self._bool(group, f"role_{slug}_p{player}_{role.value}")
                for role in Role
            }
            for player in self.player_ids
        }
        self._role_frames.append(frame)
        return frame

    def _alive_frame(self, slug: str) -> dict[int, BoolRef]:
        return {
            player: self._bool(G_ALIVE, f"alive_{slug}_p{player}")
            for player in self.player_ids
        }

    def _by_player(self, group: str, slug: str) -> dict[int, BoolRef]:
        return {
            player: self._bool(group, f"{slug}_p{player}") for player in self.player_ids
        }

    def _declare_roles(self) -> None:
        """每个断面一帧身份。开局帧是第 1 夜入夜。"""

        self.role_night_start: dict[int, dict[int, dict[Role, BoolRef]]] = {}
        self.role_dawn: dict[int, dict[int, dict[Role, BoolRef]]] = {}
        for night in self.nights:
            self.role_night_start[night] = self._role_frame(f"n{night}_start")
            self.role_dawn[night] = self._role_frame(f"n{night}_dawn")
        # 最后一天的处决 / 猎手 / 红唇女郎转化之后。更早的白天结束等于下一夜入夜。
        self.role_end: dict[int, dict[Role, BoolRef]] = self._role_frame("end")

    def _declare_beliefs(self) -> None:
        """每个玩家被说书人告知、因而自己相信的角色。

        这不是白天的公开发言。发言可以撒谎；自认身份只在两种情况下偏离真实标记：
        开局的酒鬼看到的是镇民标记，以及后来被通知「你变成了小恶魔」的玩家。
        和真实身份用同一套时间断面，但现在还没有写成等式。
        """

        self.believed_night_start: dict[int, dict[int, dict[Role, BoolRef]]] = {}
        self.believed_dawn: dict[int, dict[int, dict[Role, BoolRef]]] = {}
        for night in self.nights:
            self.believed_night_start[night] = self._role_frame(
                f"belief_n{night}_start", G_BELIEF
            )
            self.believed_dawn[night] = self._role_frame(f"belief_n{night}_dawn", G_BELIEF)
        self.believed_end: dict[int, dict[Role, BoolRef]] = self._role_frame("belief_end", G_BELIEF)

    def _declare_alive(self) -> None:
        self.alive_night_start: dict[int, dict[int, BoolRef]] = {}
        self.alive_dawn: dict[int, dict[int, BoolRef]] = {}
        for night in self.nights:
            self.alive_night_start[night] = self._alive_frame(f"n{night}_start")
            self.alive_dawn[night] = self._alive_frame(f"n{night}_dawn")
        self.alive_end: dict[int, BoolRef] = self._alive_frame("end")

    def _declare_status(self) -> None:
        """中毒和醉酒。

        ``is_drunk`` 整局不变。暗流涌动里只有酒鬼醉酒，而且从开局持续到结束，
        所以不按夜复制。``poisoned[night]`` 表示第 night 夜投毒者行动之后，
        直到次日黄昏；第 night 天白天用的是同一枚。它和 ``poison_choice`` 分开：
        选择是投毒者的行动，中毒是那次行动是否生效之后的状态。
        """

        self.is_drunk: dict[int, BoolRef] = self._by_player(G_STATUS, "drunk")
        self.poisoned: dict[int, dict[int, BoolRef]] = {
            night: self._by_player(G_STATUS, f"poisoned_n{night}") for night in self.nights
        }

    def _declare_secrets(self) -> None:
        """开局时说书人写下、座位角色不能单独推出的三项。"""

        # 酒鬼相信的那枚镇民。没有酒鬼时应全假；有酒鬼时恰好一个。后者是剧本规则。
        self.drunk_mask: dict[Role, BoolRef] = {
            role: self._bool(G_SECRET, f"drunk_mask_{role.value}") for role in TOWNSFOLK
        }
        # 占卜师的干扰项。至多一名；「有占卜师时恰好一名善良玩家」是剧本规则。
        self.red_herring: dict[int, BoolRef] = self._by_player(G_SECRET, "red_herring")
        # 首夜展示给恶魔的不在场善良角色。恰好三个、且确实不在场，是剧本规则。
        self.bluff: dict[Role, BoolRef] = {
            role: self._bool(G_SECRET, f"bluff_{role.value}") for role in GOOD_ROLES
        }

    def _declare_night_actions(self) -> None:
        """夜间选择。

        每个存在的夜晚，选择变量都恰好指向一名玩家。
        若对应角色不在场或已死亡，规则模块会把这次选择当成无效，
        因此「有目标」不等于「场上有这个角色」。
        僧侣不能选自己、管家不能选自己，也留给规则模块：那取决于谁是僧侣 / 管家。
        """

        self.poison_choice: dict[int, dict[int, BoolRef]] = {
            night: self._by_player(G_NIGHT, f"poison_n{night}") for night in self.nights
        }
        self.monk_choice: dict[int, dict[int, BoolRef]] = {
            night: self._by_player(G_NIGHT, f"monk_n{night}") for night in self.demon_nights
        }
        self.imp_choice: dict[int, dict[int, BoolRef]] = {
            night: self._by_player(G_NIGHT, f"imp_n{night}") for night in self.demon_nights
        }
        # 星坠时哪名玩家拿到新的小恶魔标记。未星坠的夜晚应全假，那是剧本规则。
        self.starpass_heir: dict[int, dict[int, BoolRef]] = {
            night: self._by_player(G_NIGHT, f"starpass_n{night}")
            for night in self.demon_nights
        }
        self.butler_master: dict[int, dict[int, BoolRef]] = {
            night: self._by_player(G_NIGHT, f"butler_n{night}") for night in self.nights
        }
        # 镇长能力把死亡转移到的玩家。全假表示没有转移。
        self.mayor_bounce: dict[int, dict[int, BoolRef]] = {
            night: self._by_player(G_NIGHT, f"mayor_bounce_n{night}")
            for night in self.demon_nights
        }

    def ability_times(self, ability: Ability) -> range:
        """该能力可以被动声明的夜或天。猎手用天数，其余用夜数。"""

        if ability is Ability.SLAYER:
            return self.days
        if ability in _FIRST_NIGHT_ABILITIES:
            return range(1, 2)
        if ability in _DEMON_NIGHT_ABILITIES:
            return self.demon_nights
        return self.nights

    def _declare_abilities(self) -> None:
        """玩家声明发动技能，以及信息类技能收到的结果。

        ``ability_used`` 为真表示这名玩家在该夜或该天说自己使用了该能力。
        玩家自己选择的一名目标用 ``ability_target``。占卜师选两名玩家，用
        ``fortune_first`` 和 ``fortune_second``，收到的是非用 ``fortune_yes``。
        洗衣妇、图书管理员、调查员由说书人指出角色和两名玩家，那是结果，不是玩家选择的目标。
        这些声明和结果可以来自假身份或酒鬼。魔典中的实际选择仍是
        ``poison_choice``、``monk_choice``、``imp_choice``、``butler_master``。
        猎手没有隐藏选择：开枪是公开声明，死亡结果在 ``slayer_kill``。
        """

        self.ability_used: dict[Ability, dict[int, dict[int, BoolRef]]] = {}
        self.ability_target: dict[Ability, dict[int, dict[int, dict[int, BoolRef]]]] = {}
        for ability in Ability:
            self.ability_used[ability] = {}
            for time in self.ability_times(ability):
                self.ability_used[ability][time] = self._by_player(
                    G_ACT, f"claim_{ability.value}_{_when(ability, time)}"
                )
            if ability not in _SINGLE_TARGET_ABILITIES:
                continue
            self.ability_target[ability] = {}
            for time in self.ability_times(ability):
                self.ability_target[ability][time] = {
                    actor: self._by_player(
                        G_ACT, f"claim_{ability.value}_{_when(ability, time)}_p{actor}_t"
                    )
                    for actor in self.player_ids
                }
        self._declare_info_results()
        # 这名玩家的猎手声明发生在当天处决之后。没声明时规则会忽略它。
        self.slayer_after_execution: dict[int, dict[int, BoolRef]] = {
            day: self._by_player(G_ACT, f"slayer_after_execution_d{day}") for day in self.days
        }

    def _declare_info_results(self) -> None:
        """玩家声称自己收到的信息。未发动时这些布尔量全为假。"""

        self.washerwoman_role = self._roles_by_actor("info_washerwoman_n1_role", TOWNSFOLK)
        self.washerwoman_first = self._players_by_actor("info_washerwoman_n1_a")
        self.washerwoman_second = self._players_by_actor("info_washerwoman_n1_b")

        self.librarian_none = self._by_player(G_ACT, "info_librarian_n1_none")
        self.librarian_role = self._roles_by_actor("info_librarian_n1_role", OUTSIDERS)
        self.librarian_first = self._players_by_actor("info_librarian_n1_a")
        self.librarian_second = self._players_by_actor("info_librarian_n1_b")

        self.investigator_none = self._by_player(G_ACT, "info_investigator_n1_none")
        self.investigator_role = self._roles_by_actor("info_investigator_n1_role", MINIONS)
        self.investigator_first = self._players_by_actor("info_investigator_n1_a")
        self.investigator_second = self._players_by_actor("info_investigator_n1_b")

        self.chef_number: dict[int, dict[int, BoolRef]] = {
            actor: {
                count: self._bool(G_ACT, f"info_chef_n1_p{actor}_{count}")
                for count in range(self.n_players + 1)
            }
            for actor in self.player_ids
        }
        self.empath_number: dict[int, dict[int, dict[int, BoolRef]]] = {
            night: {
                actor: {
                    count: self._bool(G_ACT, f"info_empath_n{night}_p{actor}_{count}")
                    for count in (0, 1, 2)
                }
                for actor in self.player_ids
            }
            for night in self.nights
        }
        self.fortune_first: dict[int, dict[int, dict[int, BoolRef]]] = {}
        self.fortune_second: dict[int, dict[int, dict[int, BoolRef]]] = {}
        self.fortune_yes: dict[int, dict[int, BoolRef]] = {}
        for night in self.nights:
            self.fortune_first[night] = self._players_by_actor(f"claim_fortune_teller_n{night}_a")
            self.fortune_second[night] = self._players_by_actor(f"claim_fortune_teller_n{night}_b")
            self.fortune_yes[night] = self._by_player(G_ACT, f"info_fortune_teller_n{night}_yes")
        self.undertaker_role = {
            night: self._roles_by_actor(f"info_undertaker_n{night}_role", Role)
            for night in self.demon_nights
        }
        self.ravenkeeper_role = {
            night: self._roles_by_actor(f"info_ravenkeeper_n{night}_role", Role)
            for night in self.demon_nights
        }

    def _players_by_actor(self, slug: str) -> dict[int, dict[int, BoolRef]]:
        return {
            actor: self._by_player(G_ACT, f"{slug}_p{actor}") for actor in self.player_ids
        }

    def _roles_by_actor(
        self, slug: str, roles: tuple[Role, ...] | type[Role]
    ) -> dict[int, dict[Role, BoolRef]]:
        role_list = tuple(roles)
        return {
            actor: {
                role: self._bool(G_ACT, f"{slug}_p{actor}_{role.value}") for role in role_list
            }
            for actor in self.player_ids
        }

    def _declare_deaths(self) -> None:
        """公开死亡。

        ``executed[天][玩家]`` 是该玩家在这天白天被处决，含投票处决和贞洁者，不含猎手。
        ``night_death[夜][玩家]`` 是该玩家在这夜夜间死亡，从第 2 夜才可能发生。
        二者不是同一个变量。
        ``slayer_kill`` 是猎手能力造成的公开死亡，全局至多一名。
        它必须对应某名玩家当天的猎手声明；声明者是不是真猎手留给规则。
        """

        self.night_death: dict[int, dict[int, BoolRef]] = {
            night: self._by_player(G_DEATH, f"night_death_n{night}")
            for night in self.demon_nights
        }
        self.executed: dict[int, dict[int, BoolRef]] = {
            day: self._by_player(G_DEATH, f"executed_d{day}") for day in self.days
        }
        self.slayer_kill: dict[int, dict[int, BoolRef]] = {
            day: self._by_player(G_DEATH, f"slayer_kill_d{day}") for day in self.days
        }

    def _declare_nominations(self) -> None:
        """白天提名。编号从 1 开始，第 1 次是当天最早的提名。

        投票布尔量只记录谁举手。活人可以每次都投；
        死人整日最多投一次（幽灵票）是剧本规则，要等存活变量接上后再写。
        """

        self.nomination_happened: dict[int, dict[int, BoolRef]] = {}
        self.nominator: dict[int, dict[int, dict[int, BoolRef]]] = {}
        self.nominee: dict[int, dict[int, dict[int, BoolRef]]] = {}
        self.voted: dict[int, dict[int, dict[int, BoolRef]]] = {}
        for day in self.days:
            self.nomination_happened[day] = {}
            self.nominator[day] = {}
            self.nominee[day] = {}
            self.voted[day] = {}
            for index in self.nomination_ids:
                self.nomination_happened[day][index] = self._bool(
                    G_VOTE, f"nom_d{day}_k{index}"
                )
                self.nominator[day][index] = self._by_player(
                    G_VOTE, f"nominator_d{day}_k{index}"
                )
                self.nominee[day][index] = self._by_player(
                    G_VOTE, f"nominee_d{day}_k{index}"
                )
                self.voted[day][index] = self._by_player(G_VOTE, f"vote_d{day}_k{index}")

    def _declare_registration(self) -> None:
        """间谍 / 陌客在每一次查询中的伪装角色。全假表示这次不伪装。"""

        self.spy_mask: dict[int, dict[Query, dict[Role, BoolRef]]] = {}
        self.recluse_mask: dict[int, dict[Query, dict[Role, BoolRef]]] = {}
        for player in self.player_ids:
            self.spy_mask[player] = {}
            self.recluse_mask[player] = {}
            for query in self.queries:
                self.spy_mask[player][query] = {
                    role: self._bool(G_MASK, f"spy_mask_p{player}_{query.slug}_{role.value}")
                    for role in SPY_MASK_ROLES
                }
                self.recluse_mask[player][query] = {
                    role: self._bool(
                        G_MASK, f"recluse_mask_p{player}_{query.slug}_{role.value}"
                    )
                    for role in RECLUSE_MASK_ROLES
                }

    @property
    def bool_count(self) -> int:
        return sum(len(variables) for variables in self._groups.values())

    def groups(self) -> dict[str, list[BoolRef]]:
        """按声明顺序返回各组布尔量。不要修改返回的列表。"""

        return self._groups

    def left(self, player: int) -> int:
        """上家的座位号。共情者还要再跳过死者，那一步在规则里做。"""

        self._require_player(player)
        return (player - 1) % self.n_players

    def right(self, player: int) -> int:
        self._require_player(player)
        return (player + 1) % self.n_players

    def is_role(
        self,
        player: int,
        role: Role,
        moment: Moment,
        night: int | None = None,
    ) -> BoolRef:
        """该玩家在指定断面是否持有该角色标记。"""

        self._require_player(player)
        if moment is Moment.AFTER_LAST_DAY:
            if night is not None:
                raise ValueError("最后一天结束的断面不使用 night")
            return self.role_end[player][role]
        if night is None:
            raise ValueError(f"{moment.value} 需要 night")
        self._require_night(night)
        frame = self.role_night_start if moment is Moment.NIGHT_START else self.role_dawn
        return frame[night][player][role]

    def is_alive(self, player: int, moment: Moment, night: int | None = None) -> BoolRef:
        self._require_player(player)
        if moment is Moment.AFTER_LAST_DAY:
            if night is not None:
                raise ValueError("最后一天结束的断面不使用 night")
            return self.alive_end[player]
        if night is None:
            raise ValueError(f"{moment.value} 需要 night")
        self._require_night(night)
        frame = self.alive_night_start if moment is Moment.NIGHT_START else self.alive_dawn
        return frame[night][player]

    def start_is(self, player: int, role: Role) -> BoolRef:
        """开局真实身份：第 1 夜入夜时该玩家是否为该角色。"""

        return self.is_role(player, role, Moment.NIGHT_START, night=1)

    def believed_role(
        self,
        player: int,
        role: Role,
        moment: Moment,
        night: int | None = None,
    ) -> BoolRef:
        """该玩家在指定断面是否自认这个角色。"""

        self._require_player(player)
        if moment is Moment.AFTER_LAST_DAY:
            if night is not None:
                raise ValueError("最后一天结束的断面不使用 night")
            return self.believed_end[player][role]
        if night is None:
            raise ValueError(f"{moment.value} 需要 night")
        self._require_night(night)
        frame = (
            self.believed_night_start if moment is Moment.NIGHT_START else self.believed_dawn
        )
        return frame[night][player][role]

    def believes_at_start(self, player: int, role: Role) -> BoolRef:
        """开局自认身份。玩家输入「我是这个角色」时钉住这一枚。"""

        return self.believed_role(player, role, Moment.NIGHT_START, night=1)

    def is_droisoned(self, player: int, night: int) -> BoolRef:
        """该玩家在第 night 夜的后续结算和第 night 天是否中毒或醉酒。

        这是表达式，不是新的未知量。醉酒整局有效，中毒只取这一夜。
        """

        self._require_player(player)
        self._require_night(night)
        return Or(self.is_drunk[player], self.poisoned[night][player])

    def role_after_day(self, day: int, player: int, role: Role) -> BoolRef:
        """第 ``day`` 天全部白天结算之后的身份。

        不是最后一天时，这个布尔量和下一夜入夜是同一个变量。
        """

        self._require_day(day)
        self._require_player(player)
        if day < self.n_nights:
            return self.role_night_start[day + 1][player][role]
        return self.role_end[player][role]

    def alive_after_day(self, day: int, player: int) -> BoolRef:
        self._require_day(day)
        self._require_player(player)
        if day < self.n_nights:
            return self.alive_night_start[day + 1][player]
        return self.alive_end[player]

    def encoding_axioms(self) -> list[BoolRef]:
        """变量域公理。不含《暗流涌动》剧本规则。"""

        if self._axiom_cache is None:
            self._axiom_cache = self._make_encoding_axioms()
        return self._axiom_cache

    def build_solver(self) -> Solver:
        """新建求解器并放入域公理。"""

        solver = Solver()
        solver.add(self.encoding_axioms())
        return solver

    def summary(self) -> str:
        lines = [
            f"《暗流涌动》推理变量  tag={self.tag}",
            f"玩家 {self.n_players} 人，座位 0..{self.n_players - 1}，首尾相邻",
            f"夜数 {self.n_nights}，每天提名槽 {self.max_nominations} 个，误注册查询 {len(self.queries)} 次",
            f"布尔变量 {self.bool_count} 个，变量域公理 {len(self.encoding_axioms())} 条",
            "剧本规则尚未加入：自认身份还没等于真实身份或酒鬼标记，中毒还没等于有效的投毒，"
            "猎手声明也不限一次。两名玩家仍可以同为厨师，死亡也还没写进存活。",
            "",
        ]
        for name, variables in self._groups.items():
            lines.append(f"- {name}：{len(variables)}")
        return "\n".join(lines)

    def _make_encoding_axioms(self) -> list[BoolRef]:
        axioms: list[BoolRef] = []
        for frame in self._role_frames:
            for player in self.player_ids:
                axioms.append(_exactly_one(list(frame[player].values())))

        _add_optional(axioms, _at_most_one(list(self.is_drunk.values())))
        _add_optional(axioms, _at_most_one(list(self.drunk_mask.values())))
        _add_optional(axioms, _at_most_one(list(self.red_herring.values())))

        for choices in (
            self.poison_choice,
            self.monk_choice,
            self.imp_choice,
            self.butler_master,
        ):
            for targets in choices.values():
                axioms.append(_exactly_one(list(targets.values())))
        for choices in (self.starpass_heir, self.mayor_bounce, self.night_death):
            for targets in choices.values():
                _add_optional(axioms, _at_most_one(list(targets.values())))
        for targets in self.executed.values():
            _add_optional(axioms, _at_most_one(list(targets.values())))

        kills = [
            self.slayer_kill[day][player]
            for day in self.days
            for player in self.player_ids
        ]
        _add_optional(axioms, _at_most_one(kills))
        for day in self.days:
            for target in self.player_ids:
                claims = [
                    self.ability_target[Ability.SLAYER][day][actor][target]
                    for actor in self.player_ids
                ]
                axioms.append(Implies(self.slayer_kill[day][target], _or_all(claims)))
        self._ability_axioms(axioms)

        for player in self.player_ids:
            for query in self.queries:
                _add_optional(axioms, _at_most_one(list(self.spy_mask[player][query].values())))
                _add_optional(
                    axioms, _at_most_one(list(self.recluse_mask[player][query].values()))
                )

        self._nomination_axioms(axioms)
        return axioms

    def _ability_axioms(self, axioms: list[BoolRef]) -> None:
        for ability in _SINGLE_TARGET_ABILITIES:
            for time in self.ability_times(ability):
                for actor in self.player_ids:
                    used = self.ability_used[ability][time][actor]
                    targets = list(self.ability_target[ability][time][actor].values())
                    axioms.extend(_count_matches_flag(used, targets))
        self._info_result_axioms(axioms)

    def _info_result_axioms(self, axioms: list[BoolRef]) -> None:
        for actor in self.player_ids:
            washerwoman = self.ability_used[Ability.WASHERWOMAN][1][actor]
            axioms.extend(
                _count_matches_flag(washerwoman, list(self.washerwoman_role[actor].values()))
            )
            axioms.extend(
                _count_matches_flag(washerwoman, list(self.washerwoman_first[actor].values()))
            )
            axioms.extend(
                _count_matches_flag(washerwoman, list(self.washerwoman_second[actor].values()))
            )
            self._distinct_players(
                axioms, self.washerwoman_first[actor], self.washerwoman_second[actor]
            )
            self._none_or_ping(
                axioms,
                self.ability_used[Ability.LIBRARIAN][1][actor],
                self.librarian_none[actor],
                list(self.librarian_role[actor].values()),
                self.librarian_first[actor],
                self.librarian_second[actor],
            )
            self._none_or_ping(
                axioms,
                self.ability_used[Ability.INVESTIGATOR][1][actor],
                self.investigator_none[actor],
                list(self.investigator_role[actor].values()),
                self.investigator_first[actor],
                self.investigator_second[actor],
            )
            axioms.extend(
                _count_matches_flag(
                    self.ability_used[Ability.CHEF][1][actor],
                    list(self.chef_number[actor].values()),
                )
            )
        for night in self.nights:
            for actor in self.player_ids:
                empath = self.ability_used[Ability.EMPATH][night][actor]
                axioms.extend(
                    _count_matches_flag(empath, list(self.empath_number[night][actor].values()))
                )
                fortune = self.ability_used[Ability.FORTUNE_TELLER][night][actor]
                axioms.extend(_count_matches_flag(fortune, list(self.fortune_first[night][actor].values())))
                axioms.extend(
                    _count_matches_flag(fortune, list(self.fortune_second[night][actor].values()))
                )
                self._distinct_players(
                    axioms, self.fortune_first[night][actor], self.fortune_second[night][actor]
                )
                axioms.append(Implies(Not(fortune), Not(self.fortune_yes[night][actor])))
        for night in self.demon_nights:
            for actor in self.player_ids:
                axioms.extend(
                    _count_matches_flag(
                        self.ability_used[Ability.UNDERTAKER][night][actor],
                        list(self.undertaker_role[night][actor].values()),
                    )
                )
                axioms.extend(
                    _count_matches_flag(
                        self.ability_used[Ability.RAVENKEEPER][night][actor],
                        list(self.ravenkeeper_role[night][actor].values()),
                    )
                )

    def _none_or_ping(
        self,
        axioms: list[BoolRef],
        used: BoolRef,
        none: BoolRef,
        roles: list[BoolRef],
        first: dict[int, BoolRef],
        second: dict[int, BoolRef],
    ) -> None:
        """发动后要么得知 0，要么得知一个角色和两名不同玩家。"""

        axioms.append(Implies(none, used))
        axioms.append(Implies(Not(used), Not(none)))
        ping = And(used, Not(none))
        axioms.extend(_count_matches_flag(ping, roles))
        axioms.extend(_count_matches_flag(ping, list(first.values())))
        axioms.extend(_count_matches_flag(ping, list(second.values())))
        self._distinct_players(axioms, first, second)

    def _distinct_players(
        self,
        axioms: list[BoolRef],
        first: dict[int, BoolRef],
        second: dict[int, BoolRef],
    ) -> None:
        for player in self.player_ids:
            axioms.append(Implies(first[player], Not(second[player])))

    def _nomination_axioms(self, axioms: list[BoolRef]) -> None:
        for day in self.days:
            happened = self.nomination_happened[day]
            for index in self.nomination_ids:
                if index > 1:
                    axioms.append(Implies(happened[index], happened[index - 1]))
                nominators = list(self.nominator[day][index].values())
                nominees = list(self.nominee[day][index].values())
                axioms.extend(_count_matches_flag(happened[index], nominators))
                axioms.extend(_count_matches_flag(happened[index], nominees))
                for player in self.player_ids:
                    axioms.append(
                        Implies(
                            self.nominator[day][index][player],
                            Not(self.nominee[day][index][player]),
                        )
                    )
                    axioms.append(Implies(self.voted[day][index][player], happened[index]))
            for player in self.player_ids:
                _add_optional(
                    axioms,
                    _at_most_one(
                        [self.nominator[day][index][player] for index in self.nomination_ids]
                    ),
                )
                _add_optional(
                    axioms,
                    _at_most_one(
                        [self.nominee[day][index][player] for index in self.nomination_ids]
                    ),
                )

    def _require_player(self, player: int) -> None:
        if player not in self.player_ids:
            raise IndexError(f"玩家编号 {player} 超出 0..{self.n_players - 1}")

    def _require_night(self, night: int) -> None:
        if night not in self.nights:
            raise IndexError(f"夜数 {night} 超出 1..{self.n_nights}")

    def _require_day(self, day: int) -> None:
        if day not in self.days:
            raise IndexError(f"天数 {day} 超出 1..{self.n_nights}")

    def __repr__(self) -> str:
        return (
            f"TroubleBrewingVars(n_players={self.n_players}, n_nights={self.n_nights}, "
            f"bools={self.bool_count}, tag={self.tag!r})"
        )


def declare_variables(
    n_players: int,
    n_nights: int | None = None,
    *,
    max_nominations: int | None = None,
    tag: str = "tb",
) -> TroubleBrewingVars:
    """声明一局《暗流涌动》的全部推理变量。"""

    return TroubleBrewingVars(
        n_players,
        n_nights,
        max_nominations=max_nominations,
        tag=tag,
    )


def _positive_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name}必须是整数，收到 {value!r}")
    if value < 1:
        raise ValueError(f"{name}必须为正，收到 {value}")
    return value


def _when(ability: Ability, time: int) -> str:
    if ability is Ability.SLAYER:
        return f"d{time}"
    return f"n{time}"


def _or_all(xs: list[BoolRef]) -> BoolRef:
    if len(xs) == 1:
        return xs[0]
    return Or(*xs)


def _add_optional(axioms: list[BoolRef], axiom: BoolRef | None) -> None:
    if axiom is not None:
        axioms.append(axiom)


def _count_matches_flag(flag: BoolRef, xs: list[BoolRef]) -> list[BoolRef]:
    """``flag`` 为真时 ``xs`` 恰好一个为真，否则全假。"""

    if len(xs) == 1:
        only = xs[0]
        return [Implies(flag, only), Implies(Not(flag), Not(only))]
    return [
        Implies(flag, And(AtLeast(*xs, 1), AtMost(*xs, 1))),
        Implies(Not(flag), And([Not(item) for item in xs])),
    ]


def _self_check() -> None:
    from z3 import sat, unsat

    from botc_reasoner.roles import validate_catalog
    from botc_reasoner.roles import setup_counts

    validate_catalog()
    baron = setup_counts(8, baron=True)
    if baron.as_tuple() != (3, 3, 1, 1):
        raise SystemExit(f"男爵配置错误：{baron}")
    try:
        setup_counts(16)
    except ValueError:
        pass
    else:
        raise SystemExit("16 人配置应当拒绝")

    world = declare_variables(8, n_nights=3, tag="tb8")
    if world.left(0) != 7 or world.right(0) != 1:
        raise SystemExit("座位相邻关系错误")
    # 第 1 天结束与第 2 夜入夜是同一个布尔量。
    if world.role_after_day(1, 0, Role.CHEF) is not world.role_night_start[2][0][Role.CHEF]:
        raise SystemExit("白天结束与下一夜入夜应当是同一变量")

    solver = world.build_solver()
    if solver.check() != sat:
        raise SystemExit("只有域公理时应当可满足")

    solver = world.build_solver()
    solver.add(world.start_is(0, Role.CHEF), world.start_is(0, Role.IMP))
    if solver.check() != unsat:
        raise SystemExit("同一玩家不能同时是两个角色")

    solver = world.build_solver()
    solver.add(world.start_is(0, Role.CHEF), world.start_is(1, Role.CHEF))
    if solver.check() != sat:
        raise SystemExit("角色全局唯一还没编码，两名厨师目前应当可满足")

    solver = world.build_solver()
    solver.add(world.night_death[2][0], world.night_death[2][1])
    if solver.check() != unsat:
        raise SystemExit("同一夜不能有两名夜间死亡")

    chef_query = next(query for query in world.queries if query.kind is QueryKind.CHEF)
    solver = world.build_solver()
    solver.add(
        world.spy_mask[0][chef_query][Role.CHEF],
        world.spy_mask[0][chef_query][Role.EMPATH],
    )
    if solver.check() != unsat:
        raise SystemExit("同一次查询不能有两个间谍伪装")

    solver = world.build_solver()
    solver.add(world.slayer_kill[1][0])
    for actor in world.player_ids:
        solver.add(Not(world.ability_target[Ability.SLAYER][1][actor][0]))
    if solver.check() != unsat:
        raise SystemExit("没有人声明猎手射击就不能有猎手击杀")
    solver = world.build_solver()
    solver.add(
        world.ability_used[Ability.SLAYER][1][0],
        world.ability_used[Ability.SLAYER][2][1],
    )
    if solver.check() != sat:
        raise SystemExit("不同玩家应当可以先后声明发动猎手")
    solver = world.build_solver()
    solver.add(world.believes_at_start(0, Role.INVESTIGATOR), world.start_is(0, Role.DRUNK))
    if solver.check() != sat:
        raise SystemExit("自认调查员与真实身份酒鬼目前应当可以同时成立")
    solver = world.build_solver()
    solver.add(
        world.believes_at_start(0, Role.INVESTIGATOR),
        world.believes_at_start(0, Role.CHEF),
    )
    if solver.check() != unsat:
        raise SystemExit("自认身份应当恰好一个")
    solver = world.build_solver()
    solver.add(world.is_drunk[0], world.is_drunk[1])
    if solver.check() != unsat:
        raise SystemExit("醉酒玩家应当至多一名")
    solver = world.build_solver()
    solver.add(
        world.fortune_first[1][0][1],
        world.fortune_second[1][0][1],
    )
    if solver.check() != unsat:
        raise SystemExit("占卜师声明的两名目标不能是同一人")
    solver = world.build_solver()
    solver.add(world.empath_number[1][0][0], world.empath_number[1][0][1])
    if solver.check() != unsat:
        raise SystemExit("同一次共情者信息不能有两个数字")
    solver = world.build_solver()
    solver.add(
        world.fortune_yes[1][0],
        Not(world.ability_used[Ability.FORTUNE_TELLER][1][0]),
    )
    if solver.check() != unsat:
        raise SystemExit("没发动占卜师就不能有是/否结果")
    solver = world.build_solver()
    solver.add(world.washerwoman_first[0][1], world.washerwoman_second[0][1])
    if solver.check() != unsat:
        raise SystemExit("洗衣妇结果里的两名玩家不能相同")
    solver = world.build_solver()
    solver.add(world.librarian_none[0], world.librarian_role[0][Role.DRUNK])
    if solver.check() != unsat:
        raise SystemExit("图书管理员得知 0 时不能再有外来者角色")
    if world.executed[1][0] is world.night_death[2][0]:
        raise SystemExit("处决和夜间死亡必须是不同变量")
    if 2 in world.ability_used[Ability.WASHERWOMAN]:
        raise SystemExit("洗衣妇只应在首夜")

    solver = world.build_solver()
    solver.add(world.nomination_happened[1][2], Not(world.nomination_happened[1][1]))
    if solver.check() != unsat:
        raise SystemExit("提名槽应当从 1 开始连续使用")

    if 1 in world.imp_choice or 1 in world.night_death or 1 in world.ability_used[Ability.MONK]:
        raise SystemExit("首夜不应当有恶魔击杀或僧侣发动变量")

    full = declare_variables(MAX_PLAYERS, n_nights=MAX_PLAYERS, tag="tb20")
    if full.build_solver().check() != sat:
        raise SystemExit("20 人、20 夜的域公理应当可满足")
    try:
        declare_variables(MAX_PLAYERS + 1, n_nights=1, tag="tb21")
    except ValueError:
        pass
    else:
        raise SystemExit("超过 20 人应当拒绝")

    print(world.summary())
    print(f"20 人 20 夜布尔变量：{full.bool_count}")
    print("自检通过")


if __name__ == "__main__":
    _self_check()
