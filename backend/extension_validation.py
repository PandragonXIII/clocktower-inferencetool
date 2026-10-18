"""Validation for the BOTC records understood by the current connector.

Disabled records are deliberately not passed here: they may be unfinished UI
drafts. No Z3 objects are imported or constructed by this module.
"""

from .errors import ApiError

KNOWN_EXTENSIONS = {
    "botc:ability_observation", "botc:night_deaths", "botc:day_vote", "botc:global_assumption",
}
TOWNSFOLK = {
    "washerwoman", "librarian", "investigator", "chef", "empath",
    "fortune_teller", "undertaker", "monk", "ravenkeeper", "virgin",
    "slayer", "soldier", "mayor",
}
OUTSIDERS = {"butler", "drunk", "recluse", "saint"}
MINIONS = {"poisoner", "spy", "scarlet_woman", "baron"}
ROLES = TOWNSFOLK | OUTSIDERS | MINIONS | {"imp"}


def fail(path, message, code="INVALID_REQUEST", status=400):
    raise ApiError(status, code, message, path)


def obj(value, path):
    if not isinstance(value, dict):
        fail(path, "必须是 JSON 对象")
    return value


def integer(value, path, minimum=0):
    if type(value) is not int or value < minimum:
        fail(path, f"必须是大于等于 {minimum} 的整数")


def string(value, path):
    if not isinstance(value, str) or not value:
        fail(path, "必须是非空字符串")


def reference(value, path, players, nullable=False):
    if nullable and value is None:
        return
    string(value, path)
    if value not in players:
        fail(path, "引用了不存在的玩家", "INVALID_REFERENCE")


def references(value, path, players):
    if not isinstance(value, list):
        fail(path, "必须是玩家 id 数组")
    seen = set()
    for i, entry in enumerate(value):
        reference(entry, f"{path}/{i}", players)
        if entry in seen:
            fail(f"{path}/{i}", "玩家不能重复")
        seen.add(entry)


def time_value(value, path, game_rank):
    value = obj(value, path)
    phase = value.get("phase")
    if phase not in ("night", "day"):
        fail(path + "/phase", "扩展记录必须指定 day 或 night")
    number = value.get("number")
    integer(number, path + "/number", 1)
    if set(value) - {"phase", "number"}:
        fail(path, "时间含未知字段", "INVALID_FIELD")
    if 2 * number - (phase == "night") > game_rank:
        fail(path, "记录时间不能晚于 game.time")
    return phase, number


def unsupported(path, message):
    fail(path, message, "UNSUPPORTED_OBSERVATION", 422)


def known_role(value, path, allowed=ROLES):
    string(value, path)
    if value not in allowed:
        fail(path, "不是此处允许的暗流涌动角色 id", "INVALID_REFERENCE")


def validate_extension_data(kind, data, path, player_ids, game_rank):
    data = obj(data, path)
    if kind == "botc:global_assumption":
        if data.get("kind") != "role_absent":
            fail(path + "/kind", "未知全局假设", "UNKNOWN_TYPE")
        known_role(data.get("role_id"), path + "/role_id")
        time = obj(data.get("time"), path + "/time")
        if time.get("phase") == "setup":
            if set(time) != {"phase"}:
                fail(path + "/time", "setup 不能带 number 或其他字段")
        else:
            time_value(time, path + "/time", game_rank)
        if "requested_enabled" in data and type(data["requested_enabled"]) is not bool:
            fail(path + "/requested_enabled", "必须是布尔值")
        return
    phase, number = time_value(data.get("time"), path + "/time", game_rank)
    if kind == "botc:night_deaths":
        if phase != "night":
            fail(path + "/time/phase", "夜间死亡记录必须使用 night")
        references(data.get("player_ids"), path + "/player_ids", player_ids)
        if data.get("result") not in ("deaths", "none"):
            fail(path + "/result", "必须是 deaths 或 none")
        if data["result"] == "none" and data["player_ids"]:
            fail(path + "/player_ids", "无人死亡时列表必须为空")
        if number == 1 and data["player_ids"]:
            unsupported(path, "当前模型不支持首夜死亡")
    elif kind == "botc:day_vote":
        _day_vote(data, path, player_ids, phase)
    elif kind == "botc:ability_observation":
        _ability(data, path, player_ids, phase, number)


def _day_vote(data, path, players, phase):
    if phase != "day":
        fail(path + "/time/phase", "处决记录必须使用 day")
    if data.get("stage") not in ("voting", "settled"):
        fail(path + "/stage", "必须是 voting 或 settled")
    if data["stage"] == "settled" or data.get("execution") is not None:
        execution = obj(data.get("execution"), path + "/execution")
        if "player_id" not in execution:
            fail(path + "/execution/player_id", "必须指定被处决者；无人处决用 null")
        reference(execution["player_id"], path + "/execution/player_id", players, True)
    for key in ("alive_count", "threshold", "highest_count"):
        if key in data:
            integer(data[key], path + "/" + key)
    if "override" in data and type(data["override"]) is not bool:
        fail(path + "/override", "必须是布尔值")
    if "default_player_id" in data:
        reference(data["default_player_id"], path + "/default_player_id", players, True)
    nominations = data.get("nominations", [])
    if not isinstance(nominations, list):
        fail(path + "/nominations", "必须是数组")
    if len(nominations) > len(players):
        unsupported(path + "/nominations", "当前模型每天提名槽不超过玩家数")
    seen = set()
    for i, nomination in enumerate(nominations):
        p = f"{path}/nominations/{i}"
        nomination = obj(nomination, p)
        string(nomination.get("id"), p + "/id")
        if nomination["id"] in seen:
            fail(p + "/id", "提名 id 不能重复", "DUPLICATE_ID")
        seen.add(nomination["id"])
        for key in ("nominator_id", "nominee_id"):
            reference(nomination.get(key), p + "/" + key, players)
        references(nomination.get("voter_ids"), p + "/voter_ids", players)
        if "count" in nomination:
            integer(nomination["count"], p + "/count")
            if nomination["count"] != len(nomination["voter_ids"]):
                fail(p + "/count", "票数必须等于 voter_ids 长度")


def _ability(data, path, players, phase, number):
    reference(data.get("actor_id"), path + "/actor_id", players)
    known_role(data.get("role_id"), path + "/role_id")
    references(data.get("targets"), path + "/targets", players)
    for key in ("ability_id", "note"):
        if key in data and not isinstance(data[key], str):
            fail(path + "/" + key, "必须是字符串")
    result = obj(data.get("result"), path + "/result")
    kind = result.get("kind")
    if kind not in ("unobserved", "no_outsiders", "no_direct_result", "role", "number", "text", "choice"):
        fail(path + "/result/kind", "未知技能结果类型", "UNKNOWN_TYPE")
    if kind == "number":
        integer(result.get("value"), path + "/result/value")
    elif kind == "role":
        known_role(result.get("role_id"), path + "/result/role_id")
    elif kind == "choice":
        string(result.get("value"), path + "/result/value")
        if "role_id" in result:
            known_role(result["role_id"], path + "/result/role_id")
    elif kind == "text" and not isinstance(result.get("text"), str):
        fail(path + "/result/text", "必须是字符串")
    role = data["role_id"]
    supported = {
        "washerwoman", "librarian", "investigator", "chef", "empath",
        "fortune_teller", "undertaker", "monk", "poisoner", "imp",
        "butler", "slayer", "ravenkeeper",
    }
    if role not in supported:
        _passive_ability(data, path, players, phase, kind)
        return
    if phase != ("day" if role == "slayer" else "night"):
        fail(path + "/time/phase", "技能时间阶段不匹配")
    if role in {"washerwoman", "librarian", "investigator", "chef"} and number != 1:
        fail(path + "/time/number", "该信息只在首夜收到")
    if role in {"undertaker", "monk", "imp", "ravenkeeper"} and number < 2:
        unsupported(path + "/time/number", "当前模型该技能从第二夜开始")
    target_counts = {
        "washerwoman": (2,), "librarian": (0,) if kind == "no_outsiders" else (2,),
        "investigator": (2,), "chef": (0,), "empath": (0,), "fortune_teller": (2,),
        "undertaker": (0, 1), "monk": (1,), "poisoner": (1,), "imp": (1,),
        "butler": (1,), "slayer": (1,), "ravenkeeper": (1,),
    }
    if len(data["targets"]) not in target_counts[role]:
        fail(path + "/targets", "此技能的目标数量不正确")
    if kind == "unobserved":
        return  # No readout constraint; known action targets may still be compiled.
    expected = {
        "washerwoman": "role", "librarian": "no_outsiders" if kind == "no_outsiders" else "role",
        "investigator": "role", "chef": "number", "empath": "number",
        "fortune_teller": "choice", "undertaker": "role", "ravenkeeper": "role",
        "monk": "no_direct_result", "poisoner": "no_direct_result", "butler": "no_direct_result",
        "imp": "choice", "slayer": "choice",
    }
    if kind != expected[role]:
        fail(path + "/result/kind", "技能结果格式不匹配")
    categories = {"washerwoman": TOWNSFOLK, "librarian": OUTSIDERS, "investigator": MINIONS}
    if kind == "role" and role in categories:
        known_role(result["role_id"], path + "/result/role_id", categories[role])
    if kind == "number" and result["value"] > (2 if role == "empath" else len(players)):
        fail(path + "/result/value", "技能数字结果超出范围")
    if role in {"fortune_teller", "imp", "slayer"}:
        allowed = {"yes", "no"} if role == "fortune_teller" else {"died", "survived"}
        if result["value"] not in allowed:
            fail(path + "/result/value", "技能结果取值不匹配")


def _passive_ability(data, path, players, phase, kind):
    """Validate UI observations, including explicitly unstructured notes."""
    role, result, targets = data["role_id"], data["result"], data["targets"]
    counts = {"virgin": (1, 1), "soldier": (0, 0), "mayor": (0, len(players)),
              "drunk": (0, 0), "recluse": (0, 0), "saint": (0, 0),
              "spy": (0, len(players)), "scarlet_woman": (0, 0), "baron": (0, 0)}
    minimum, maximum = counts[role]
    if not minimum <= len(targets) <= maximum:
        fail(path + "/targets", "此技能的目标数量不正确")
    if role == "virgin" and phase != "day":
        fail(path + "/time/phase", "贞洁者提名观察必须在白天")
    if kind == "unobserved":
        return
    if role == "drunk":
        if kind != "role":
            fail(path + "/result/kind", "酒鬼观察应为表象镇民身份")
        known_role(result["role_id"], path + "/result/role_id", TOWNSFOLK)
    elif role == "spy":
        if kind != "text" or not result["text"].strip():
            fail(path + "/result", "请填写魔典文本或选择未观察到结果")
    elif role == "baron":
        if kind != "number" or result["value"] > len(players):
            fail(path + "/result", "外来者数量必须为玩家数以内的非负整数")
    else:
        choices = {"virgin": {"executed", "not_executed"}, "soldier": {"died", "survived"},
                   "mayor": {"three_alive_no_execution_win", "suspected_redirect"},
                   "recluse": {"role", "alignment"}, "saint": {"good_lost", "good_won", "ongoing"},
                   "scarlet_woman": {"occurred", "not_occurred", "role"}}
        if kind != "choice" or result.get("value") not in choices[role]:
            fail(path + "/result", "技能结果格式或取值不匹配")
        if role == "scarlet_woman" and result["value"] == "role" and result.get("role_id") != "imp":
            fail(path + "/result/role_id", "暗流涌动红唇女郎转化为小恶魔")
