"""Two-scope analysis of one compiled Trouble Brewing snapshot."""

from z3 import sat, unsat

from .analysis import Budget, build_solver, check_scope, diagnose, query_status
from .inputs import input_metadata
from .repairs import minimum_repairs
from .worlds import enumerate_worlds


def analyze(request, world, collector, inputs, query_expr, model_assignments, projection):
    options = request.get("options", {})
    budget = Budget(options.get("total_timeout_ms", 8000), options.get("timeout_ms", 1000))
    domain = list(world.encoding_axioms())
    public = [item for item in inputs if item.scope == "public"]
    scopes = {}
    solvers = {}
    model = None
    # Check both backgrounds before optional, potentially expensive analyses.
    for name, selected in (("public", public), ("conditional", inputs)):
        solver = build_solver(domain, collector.records, selected)
        status = check_scope(solver, budget)
        solvers[name] = solver
        scopes[name] = {"consistency": status, "input_ids": [i.id for i in selected], "results": []}
        if name == "conditional" and status == "sat":
            model = {"assignments": model_assignments(solver)}
    conclusions = []
    catalog = [{"id": "tb:domain", "title": "变量域与唯一性公理", "source": "variables.py"}]
    catalog.extend({"id": s.id, "title": s.title, "source": s.source}
                   for s in collector.catalog.values())
    rule_ids = [r["id"] for r in catalog]
    for name, scope in scopes.items():
        for query in request.get("queries", []):
            try:
                result = query_status(solvers[name], query_expr(query["proposition"]), budget, scope["consistency"])
            except (ValueError, KeyError) as exc:
                result = {"status": "unknown", "reason": str(exc)}
            result = {"id": query["id"], **result}
            scope["results"].append(result)
            if result["status"] == "necessary":
                conclusions.append({"scope": name, "query_id": query["id"],
                                    "proposition": query["proposition"], "status": "necessary",
                                    "input_ids": scope["input_ids"], "rule_ids": rule_ids,
                                    "basis_type": "full_context"})
    response = {"api_version": "1.0", "request_id": request.get("request_id"),
                "game_id": request["game"]["id"], "revision": request["game"]["revision"],
                "consistency": scopes["conditional"]["consistency"],
                "results": scopes["conditional"]["results"]}
    extensions = {"adapter:mode": "trouble_brewing", "reasoner:scopes": scopes,
                  "reasoner:inputs": input_metadata(inputs), "reasoner:conclusions": conclusions,
                  "reasoner:rule_catalog": catalog}
    response["extensions"] = extensions
    if model is not None:
        response["model"] = model
    if response["consistency"] == "unknown":
        response["reason"] = budget.reason or "未能完成条件背景的一致性判断"
    diagnoses = {}
    for name, selected in (("public", public), ("conditional", inputs)):
        if scopes[name]["consistency"] != "unsat":
            continue
        diagnostic = diagnose(domain, collector.records, selected, budget)
        diagnostic["explanation"] = (
            "所列输入与规则组不能同时成立；规则组是实际追踪的依据，不代表逐步证明。"
            if diagnostic["status"] == "unsat" else "预算内未能取得已验证的冲突核。")
        diagnostic["inputs"] = [i.description for i in selected if i.id in diagnostic["input_ids"]]
        diagnostic["rules"] = [r["title"] for r in catalog if r["id"] in diagnostic["rule_ids"]]
        diagnoses[name] = diagnostic
        if name == "conditional" and diagnostic["status"] == "unsat":
            response["conflicts"] = [{"input_ids": diagnostic["input_ids"], "rule_ids": diagnostic["rule_ids"]}]
    extensions["reasoner:diagnosis"] = diagnoses
    if response["consistency"] == "unsat" and options.get("max_repairs", 0):
        extensions["reasoner:repairs"] = {
            name: minimum_repairs(domain, collector.records, inputs, budget,
                                  max_repairs=options["max_repairs"], identity_only=identity_only,
                                  max_checks=options.get("max_repair_checks", 128))
            for name, identity_only in (("identity", True), ("general", False))
        }
    if response["consistency"] == "sat":
        rows = []
        for player_id, roles in projection:
            proven, excluded, pending = [], [], []
            for role_id, expr in roles:
                if budget.deadline_exhausted():
                    pending.append(role_id)
                    continue
                solver = solvers["conditional"]
                solver.push()
                try:
                    solver.add(expr)
                    status = budget.check(solver)
                finally:
                    solver.pop()
                (proven if status == sat else excluded if status == unsat else pending).append(role_id)
            seat = next(p["seat"] for p in request["game"]["players"] if p["id"] == player_id)
            rows.append({"player_id": player_id, "seat": seat, "role_ids": proven,
                         "impossible_role_ids": excluded, "unknown_role_ids": pending,
                         "complete": not pending})
            if len(proven) == 1 and not pending:
                conclusions.append({"scope": "conditional", "status": "necessary",
                                    "proposition": {"kind": "role", "player_id": player_id,
                                                    "role_id": proven[0], "time": {"phase": "setup"}},
                                    "input_ids": scopes["conditional"]["input_ids"],
                                    "rule_ids": rule_ids, "basis_type": "full_context"})
        extensions["reasoner:role_ranges"] = {"scope": "conditional", "time": {"phase": "setup"},
                                              "rows": rows, "complete": all(r["complete"] for r in rows)}
        # Old clients treat omissions as excluded: retain unclassified roles.
        extensions["trouble_brewing:possible_roles"] = [
            {**r, "role_ids": r["role_ids"] + r["unknown_role_ids"]} for r in rows]
    if response["consistency"] == "sat" and options.get("max_worlds", 0):
        extensions["reasoner:worlds"] = enumerate_worlds(
            solvers["conditional"], projection, budget, max_worlds=options["max_worlds"])
        extensions["reasoner:worlds"]["time"] = {"phase": "setup"}
    extensions["reasoner:timeout"] = {"total_ms": budget.total_ms, "per_solve_ms": budget.per_solve_ms,
                                     "hit": budget.hit or budget.deadline_exhausted()}
    return response
