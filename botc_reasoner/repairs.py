"""Bounded, verified withdrawal suggestions; never change public observations."""

from itertools import combinations

from z3 import sat, unknown

from .analysis import build_solver


def minimum_repairs(domain_exprs, rule_records, inputs, budget, max_repairs=3,
                    identity_only=False, max_checks=256):
    """Minimize changed owners first, then withdrawn inputs.

    Every candidate is checked against the whole remaining problem. Unknown or
    a search limit never becomes a claim of optimality or absence of repairs.
    ``identity_only`` freezes observations and only withdraws identity claims.
    Withdrawal is not a negative identity assertion and is not proof of lying.
    """
    if isinstance(max_repairs, bool) or not isinstance(max_repairs, int) or max_repairs < 1:
        raise ValueError("max_repairs 必须为正整数；禁用修复时调用方应跳过搜索")
    if isinstance(max_checks, bool) or not isinstance(max_checks, int) or max_checks < 0:
        raise ValueError("max_checks 必须为非负整数")
    inputs = list(inputs)
    domain_exprs, rule_records = list(domain_exprs), list(rule_records)
    removable = [item for item in inputs if item.scope != "public"
                 and (not identity_only or item.identity_claim)]
    owner = lambda item: ("player", item.owner_id) if item.owner_id else ("input", item.id)
    owner_count = len({owner(item) for item in removable})
    checks = 0
    result = {"candidates": [], "complete": False, "optimality": "unknown",
              "objective": "changed_owners_then_inputs", "identity_only": identity_only}
    best_cost = None
    for k in range(owner_count + 1):
        for count in range(len(removable) + 1):
            if best_cost is not None and (k, count) > best_cost:
                result.update(complete=True, optimality="optimal")
                return result
            for removed in combinations(removable, count):
                if budget.deadline_exhausted():
                    result["reason"] = "总时间预算耗尽"
                    return result
                if len({owner(item) for item in removed}) != k:
                    continue
                if checks >= max_checks:
                    result["reason"] = "修复搜索次数上限"
                    return result
                removed_ids = {item.id for item in removed}
                solver = build_solver(domain_exprs, rule_records,
                                      [item for item in inputs if item.id not in removed_ids])
                status = budget.check(solver)
                checks += 1
                if status == unknown:
                    result["reason"] = budget.reason or "修复检查未完成"
                    return result
                if status != sat:
                    continue
                best_cost = (k, count)
                result["optimality"] = "optimal"
                result["candidates"].append({
                    "removed_input_ids": [item.id for item in removed],
                    "changed_owner_ids": sorted({item.owner_id for item in removed if item.owner_id}),
                    "cost": {"owners": k, "inputs": count},
                    "optimality": "optimal",
                    "verified": True,
                })
                if len(result["candidates"]) >= max_repairs:
                    result["reason"] = "修复方案返回数量上限（最优代价已证明，方案未必列全）"
                    return result
    result.update(complete=True, optimality="optimal")
    if not result["candidates"]:
        result["reason"] = "允许撤销的输入范围内没有修复方案；请核对公共信息或其他固定输入"
    return result
