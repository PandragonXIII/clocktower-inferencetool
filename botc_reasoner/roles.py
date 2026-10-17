"""《暗流涌动》角色、配置与后续规则会用到的固定事实。

本文件不依赖 Z3。推理变量见 `variables.py`。

官方剧本只含下面 22 个角色。钟楼百科同页列出的旅行者与实验性角色
不在本模型内。数据依据：
https://clocktower-wiki.gstonegames.com/index.php?title=暗流涌动
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum


class Category(Enum):
    """角色类别。阵营由类别决定：镇民与外来者善良，爪牙与恶魔邪恶。"""

    TOWNSFOLK = "镇民"
    OUTSIDER = "外来者"
    MINION = "爪牙"
    DEMON = "恶魔"


class Alignment(Enum):
    GOOD = "善良"
    EVIL = "邪恶"


class Role(Enum):
    """暗流涌动的全部官方角色。枚举值用作 Z3 变量名的一部分。"""

    WASHERWOMAN = "washerwoman"
    LIBRARIAN = "librarian"
    INVESTIGATOR = "investigator"
    CHEF = "chef"
    EMPATH = "empath"
    FORTUNE_TELLER = "fortune_teller"
    UNDERTAKER = "undertaker"
    MONK = "monk"
    RAVENKEEPER = "ravenkeeper"
    VIRGIN = "virgin"
    SLAYER = "slayer"
    SOLDIER = "soldier"
    MAYOR = "mayor"
    BUTLER = "butler"
    DRUNK = "drunk"
    RECLUSE = "recluse"
    SAINT = "saint"
    POISONER = "poisoner"
    SPY = "spy"
    SCARLET_WOMAN = "scarlet_woman"
    BARON = "baron"
    IMP = "imp"


ROLE_ZH: dict[Role, str] = {
    Role.WASHERWOMAN: "洗衣妇",
    Role.LIBRARIAN: "图书管理员",
    Role.INVESTIGATOR: "调查员",
    Role.CHEF: "厨师",
    Role.EMPATH: "共情者",
    Role.FORTUNE_TELLER: "占卜师",
    Role.UNDERTAKER: "送葬者",
    Role.MONK: "僧侣",
    Role.RAVENKEEPER: "守鸦人",
    Role.VIRGIN: "贞洁者",
    Role.SLAYER: "猎手",
    Role.SOLDIER: "士兵",
    Role.MAYOR: "镇长",
    Role.BUTLER: "管家",
    Role.DRUNK: "酒鬼",
    Role.RECLUSE: "陌客",
    Role.SAINT: "圣徒",
    Role.POISONER: "投毒者",
    Role.SPY: "间谍",
    Role.SCARLET_WOMAN: "红唇女郎",
    Role.BARON: "男爵",
    Role.IMP: "小恶魔",
}

# 带 * 的能力不在首夜行动。
ABILITY_ZH: dict[Role, str] = {
    Role.WASHERWOMAN: "首夜得知一名在场镇民角色，以及两名玩家，其中一名是该角色。",
    Role.LIBRARIAN: "首夜得知一名在场外来者角色及两名玩家之一；若没有外来者，则得知 0。",
    Role.INVESTIGATOR: "首夜得知一名在场爪牙角色，以及两名玩家，其中一名是该角色。",
    Role.CHEF: "首夜得知有多少对相邻的邪恶玩家。",
    Role.EMPATH: "每个夜晚，得知两名存活邻居中有几人是邪恶的。",
    Role.FORTUNE_TELLER: "每个夜晚选择两名玩家，得知其中是否有恶魔。一名善良玩家是干扰项。",
    Role.UNDERTAKER: "每个夜晚*，得知今天白天死于处决的玩家角色。",
    Role.MONK: "每个夜晚*，选择除自己外的一名玩家，当晚恶魔无法杀死该玩家。",
    Role.RAVENKEEPER: "若在夜晚死亡，选择一名玩家并得知其角色。",
    Role.VIRGIN: "第一次被提名时，若提名者是镇民，该提名者立即被处决。",
    Role.SLAYER: "整局一次。白天公开选择一名玩家，若该玩家是恶魔则死亡。",
    Role.SOLDIER: "恶魔无法杀死你。",
    Role.MAYOR: "仅剩三名存活玩家且白天无人被处决时，善良阵营获胜。若将在夜晚死亡，说书人可以改杀另一名玩家。",
    Role.BUTLER: "每个夜晚选择除自己外的一名玩家作为主人；次日仅当主人投票时自己才能投票。",
    Role.DRUNK: "你以为自己是一名镇民，但实际是酒鬼，该镇民能力不会生效。",
    Role.RECLUSE: "可能被当作邪恶阵营、爪牙或恶魔，即使已经死亡。",
    Role.SAINT: "若死于处决，善良阵营落败。",
    Role.POISONER: "每个夜晚选择一名玩家，该玩家在当晚和次日白天中毒。",
    Role.SPY: "每个夜晚查看魔典。可能被当作善良阵营的镇民或外来者，即使已经死亡。",
    Role.SCARLET_WOMAN: "恶魔死亡时若仍有不少于五名玩家存活，你变成恶魔。",
    Role.BARON: "开局镇民少两人、外来者多两人。",
    Role.IMP: "每个夜晚*选择一名玩家，该玩家死亡。若选择自己，一名存活爪牙变成小恶魔。",
}

TOWNSFOLK: tuple[Role, ...] = (
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
)
OUTSIDERS: tuple[Role, ...] = (
    Role.BUTLER,
    Role.DRUNK,
    Role.RECLUSE,
    Role.SAINT,
)
MINIONS: tuple[Role, ...] = (
    Role.POISONER,
    Role.SPY,
    Role.SCARLET_WOMAN,
    Role.BARON,
)
DEMONS: tuple[Role, ...] = (Role.IMP,)

GOOD_ROLES: tuple[Role, ...] = TOWNSFOLK + OUTSIDERS
EVIL_ROLES: tuple[Role, ...] = MINIONS + DEMONS

# 间谍可以注册成这些角色；全为假表示按真实身份（间谍）注册。
SPY_MASK_ROLES: tuple[Role, ...] = GOOD_ROLES
# 陌客可以注册成这些角色；全为假表示按真实身份（陌客）注册。
RECLUSE_MASK_ROLES: tuple[Role, ...] = EVIL_ROLES

MIN_LEGAL_PLAYERS = 5
MAX_LEGAL_PLAYERS = 15

# 官方人数配置：(镇民, 外来者, 爪牙, 恶魔)。不含男爵修正。
BASE_SETUP: dict[int, tuple[int, int, int, int]] = {
    5: (3, 0, 1, 1),
    6: (3, 1, 1, 1),
    7: (5, 0, 1, 1),
    8: (5, 1, 1, 1),
    9: (5, 2, 1, 1),
    10: (7, 0, 2, 1),
    11: (7, 1, 2, 1),
    12: (7, 2, 2, 1),
    13: (9, 0, 3, 1),
    14: (9, 1, 3, 1),
    15: (9, 2, 3, 1),
}

# 百科中的夜晚顺序。黄昏时旅行者会先行动；本模型没有旅行者。
FIRST_NIGHT_ORDER: tuple[str, ...] = (
    "dusk",
    "minion_info",
    "demon_info",
    "poisoner",
    "spy",
    "washerwoman",
    "librarian",
    "investigator",
    "chef",
    "empath",
    "fortune_teller",
    "butler",
    "dawn",
)
OTHER_NIGHT_ORDER: tuple[str, ...] = (
    "dusk",
    "poisoner",
    "monk",
    "spy",
    "scarlet_woman",
    "imp",
    "ravenkeeper",
    "undertaker",
    "empath",
    "fortune_teller",
    "butler",
    "dawn",
)


@dataclass(frozen=True)
class SetupCounts:
    """某一人数下，袋子里各类角色的数量。"""

    townsfolk: int
    outsiders: int
    minions: int
    demons: int

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.townsfolk, self.outsiders, self.minions, self.demons)


def category_of(role: Role) -> Category:
    if role in TOWNSFOLK:
        return Category.TOWNSFOLK
    if role in OUTSIDERS:
        return Category.OUTSIDER
    if role in MINIONS:
        return Category.MINION
    return Category.DEMON


def alignment_of(role: Role) -> Alignment:
    """真实阵营。间谍与陌客的「注册阵营」不是这个函数。"""

    if role in EVIL_ROLES:
        return Alignment.EVIL
    return Alignment.GOOD


def role_from_name(name: str) -> Role:
    """按中文名、英文枚举值或枚举名查找角色。"""

    key = name.strip()
    folded = key.lower().replace(" ", "_")
    for role in Role:
        if key in (ROLE_ZH[role], role.name) or folded == role.value:
            return role
    raise KeyError(f"未知角色：{name}")


def setup_counts(n_players: int, *, baron: bool = False) -> SetupCounts:
    """返回官方配置。男爵在场时镇民 -2、外来者 +2。

    16 人及以上需要旅行者，不在这张表里。
    酒鬼不额外占人数：他占用一个外来者名额，并另持一枚不在座位上的镇民标记。
    """

    if n_players not in BASE_SETUP:
        raise ValueError(
            f"官方《暗流涌动》配置表只覆盖 {MIN_LEGAL_PLAYERS}–{MAX_LEGAL_PLAYERS} 人，"
            f"收到 {n_players}。16–20 人需要旅行者，当前尚未建模。"
        )
    townsfolk, outsiders, minions, demons = BASE_SETUP[n_players]
    if baron:
        townsfolk -= 2
        outsiders += 2
    return SetupCounts(townsfolk, outsiders, minions, demons)


@dataclass(frozen=True)
class SampleSetup:
    """百科给新手说书人的八人示例。`roles` 是座位上的真实角色。"""

    name: str
    roles: tuple[Role, ...]
    drunk_mask: Role | None = None


SAMPLE_SETUPS: tuple[SampleSetup, ...] = (
    SampleSetup(
        "信息量大的新手局",
        (
            Role.CHEF,
            Role.EMPATH,
            Role.FORTUNE_TELLER,
            Role.UNDERTAKER,
            Role.VIRGIN,
            Role.DRUNK,
            Role.SCARLET_WOMAN,
            Role.IMP,
        ),
        drunk_mask=Role.INVESTIGATOR,
    ),
    SampleSetup(
        "安静局",
        (
            Role.SLAYER,
            Role.RAVENKEEPER,
            Role.MAYOR,
            Role.FORTUNE_TELLER,
            Role.EMPATH,
            Role.SAINT,
            Role.POISONER,
            Role.IMP,
        ),
    ),
    SampleSetup(
        "进阶逻辑局",
        (
            Role.WASHERWOMAN,
            Role.SLAYER,
            Role.VIRGIN,
            Role.UNDERTAKER,
            Role.FORTUNE_TELLER,
            Role.RECLUSE,
            Role.SPY,
            Role.IMP,
        ),
    ),
)


# 写规则时要遵守的裁决。它们还不是 Z3 约束。
MODELING_NOTES: tuple[str, ...] = (
    "开局每个座位恰好一个角色，且角色标记不重复。星坠或红唇女郎之后可以同时存在两枚小恶魔标记。",
    "死亡永久。本剧本没有复活。",
    "酒鬼所相信的镇民视为在场：不能当作恶魔看到的不在场角色，洗衣妇也可以指向酒鬼玩家与该镇民。",
    "中毒覆盖投毒者行动当夜的后续结算，以及紧接着的那个白天，次日黄昏失效。投毒者每夜最先行动，因此在本剧本里他行动时自身是清醒的。",
    "间谍每次信息结算都可以独立选择注册为一名镇民或外来者，也可以不伪装。陌客同理，可注册为一名爪牙或小恶魔。",
    "星坠时死者仍保留小恶魔标记，另一枚小恶魔标记交给一名存活爪牙。占卜师对这两名玩家都可能得到「是」。此时善良阵营尚未获胜。",
    "小恶魔自杀走星坠，不再同时触发红唇女郎。红唇女郎在恶魔死于处决或猎手、且死者之外仍有不少于五名存活玩家时变成小恶魔。中毒或醉酒的红唇女郎不会转化。",
    "猎手击杀不是处决。送葬者只看到处决。圣徒只有死于处决才会让善良阵营落败，且圣徒中毒或醉酒时处决他不会落败。贞洁者造成的死亡是处决。",
    "镇长改杀他人是说书人可以做的选择，不是必然。僧侣与健康的士兵会使当晚的恶魔击杀落空。",
    "首夜没有恶魔击杀。僧侣、小恶魔、守鸦人、送葬者、红唇女郎的夜间提醒都不在首夜。",
    "同一天里猎手射击与处决的先后不固定。射击若发生在处决之后，看到的是红唇女郎可能已经转化后的身份。",
    "共情者的邻居按座位环计算，并跳过死者。座位本身是 (i-1) mod n 与 (i+1) mod n。",
    "玩家录入的「我是某角色」钉住自认身份。非酒鬼的自认身份等于当时的真实身份；酒鬼的自认身份等于其镇民标记，真实身份仍是酒鬼。",
    "醉酒只属于酒鬼，并且整局持续。中毒按夜记录，覆盖该夜投毒者行动之后直到次日黄昏；它不等于投毒者选择本身。",
    "技能发动记录玩家声明使用了某能力。声明者若不是该角色，或当时中毒、醉酒，则没有对应效果。多人都可以声明猎手开枪，真正的猎手击杀至多一次。",
    "信息类技能的结果是玩家收到的内容，不必等于真实世界。只有能力生效时，结果才必须和身份、误注册一致。",
)


def validate_catalog() -> None:
    """检查角色表、配置表和示例配置没有漏项。"""

    grouped = TOWNSFOLK + OUTSIDERS + MINIONS + DEMONS
    if len(grouped) != len(set(grouped)) or set(grouped) != set(Role):
        raise RuntimeError("角色分类与 Role 枚举不一致")
    if set(ROLE_ZH) != set(Role) or set(ABILITY_ZH) != set(Role):
        raise RuntimeError("角色中文名或能力说明不完整")
    if len(set(ROLE_ZH.values())) != len(ROLE_ZH):
        raise RuntimeError("角色中文名重复")
    for n_players, counts in BASE_SETUP.items():
        if sum(counts) != n_players:
            raise RuntimeError(f"{n_players} 人配置加总不等于人数：{counts}")
    expected = setup_counts(8)
    for sample in SAMPLE_SETUPS:
        if len(sample.roles) != 8 or len(set(sample.roles)) != 8:
            raise RuntimeError(f"示例配置「{sample.name}」应是 8 个不同角色")
        counts = Counter(category_of(role) for role in sample.roles)
        if (
            counts[Category.TOWNSFOLK] != expected.townsfolk
            or counts[Category.OUTSIDER] != expected.outsiders
            or counts[Category.MINION] != expected.minions
            or counts[Category.DEMON] != expected.demons
        ):
            raise RuntimeError(f"示例配置「{sample.name}」不符合八人官方配置")
        if sample.drunk_mask is None:
            if Role.DRUNK in sample.roles:
                raise RuntimeError(f"示例配置「{sample.name}」有酒鬼但没有伪装镇民")
        else:
            if Role.DRUNK not in sample.roles:
                raise RuntimeError(f"示例配置「{sample.name}」有伪装镇民但不含酒鬼")
            if sample.drunk_mask not in TOWNSFOLK or sample.drunk_mask in sample.roles:
                raise RuntimeError(f"示例配置「{sample.name}」的酒鬼伪装不合法")


validate_catalog()
