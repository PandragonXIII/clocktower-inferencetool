"""Describe which parts of each UI record were actually compiled."""


def describe_participation(request, inputs):
    applied = {item.id for item in inputs}
    rows = []
    notes = {
        "spy": "魔典为自由文本，未解析其中身份；请另录结构化身份条件。",
        "recluse": "登记记录未指定查验事件及具体结果，备注不转换为登记身份。",
        "saint": "只约束白天被处决；当前模型不判断游戏胜负。",
        "mayor": "只约束三人存活及无人处决；当前模型不判断胜利，疑似转移不确认死因。",
    }
    for fact in request.get("facts", []):
        identifier = fact["id"]
        data = fact.get("data") or {}
        if not fact.get("enabled", True):
            status, reason = "disabled", "已停用，不解析载荷、不参与推理。"
        elif identifier in applied:
            role = data.get("role_id") if fact.get("type") == "botc:ability_observation" else None
            status = "partial" if role in notes else "applied"
            reason = notes.get(role, "已编译为本次求解约束。")
        else:
            status = "record_only"
            reason = notes.get(data.get("role_id"), "未观察到结果，不添加结果约束。")
        rows.append({"id": identifier, "status": status, "reason": reason})
    for item in request.get("assumptions", []):
        rows.append({"id": item["id"], "status": "applied" if item["id"] in applied else "disabled",
                     "reason": "已编译身份或阵营条件。" if item["id"] in applied else "已停用，不参与推理。"})
    return rows
