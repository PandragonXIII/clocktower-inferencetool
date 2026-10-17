"""输入编译（``botc_reasoner.inputs``）测试。

用**小型 Bool 回调**代替真实连接器的 Z3 表达式构造，验证分类与元数据整理：
scope/source/owner 分桶、``reported`` 强制 conditional、禁用条目不调用回调、
owner 在「命题玩家」与「技能 actor」之间的区分、identity_claim 判定，以及
``input_metadata`` 不含表达式且可 JSON 序列化。
"""

import json
import unittest

from z3 import Bool

from botc_reasoner.inputs import (
    EXT_DAY_VOTE,
    EXT_NIGHT_DEATHS,
    EXT_OBSERVATION,
    SOURCE_ASSUMPTION,
    SOURCE_OBSERVATION,
    SOURCE_RECEIVED,
    SOURCE_SELF_CLAIM,
    compile_inputs,
    input_metadata,
)


def _fact_expr(fact, world, seats):
    return Bool(f"fact_{fact.get('id')}")


def _proposition_expr(proposition, world, seats, *, claimed):
    pid = (proposition or {}).get("player_id", "x")
    return Bool(f"prop_{pid}_{'belief' if claimed else 'real'}")


def _night_deaths(fact_id, status="confirmed", enabled=True, **extensions):
    return {
        "id": fact_id,
        "type": EXT_NIGHT_DEATHS,
        "status": status,
        "enabled": enabled,
        "data": {"time": {"phase": "night", "number": 2}, "player_ids": [], "result": "none"},
        "extensions": extensions or None,
    }


def _day_vote(fact_id, stage="settled", status="confirmed", enabled=True, **extensions):
    return {
        "id": fact_id,
        "type": EXT_DAY_VOTE,
        "status": status,
        "enabled": enabled,
        "data": {"time": {"phase": "day", "number": 1}, "stage": stage, "execution": {"player_id": None}},
        "extensions": extensions or None,
    }


def _ability(fact_id, actor_id="p1", status="confirmed", enabled=True, **extensions):
    return {
        "id": fact_id,
        "type": EXT_OBSERVATION,
        "status": status,
        "enabled": enabled,
        "data": {
            "time": {"phase": "night", "number": 1},
            "actor_id": actor_id,
            "role_id": "chef",
            "targets": [],
            "result": {"kind": "number", "value": 2},
        },
        "extensions": extensions or None,
    }


def _role_fact(fact_id, player_id="p0", status="confirmed", enabled=True, **extensions):
    return {
        "id": fact_id,
        "type": "role",
        "status": status,
        "enabled": enabled,
        "proposition": {"kind": "role", "player_id": player_id, "role_id": "chef", "time": {"phase": "setup"}},
        "extensions": extensions or None,
    }


def _assumption(assumption_id, player_id="p0", enabled=True, **extensions):
    return {
        "id": assumption_id,
        "enabled": enabled,
        "proposition": {"kind": "role", "player_id": player_id, "role_id": "chef", "time": {"phase": "setup"}},
        "extensions": extensions or None,
    }


def _by_id(inputs):
    return {item.id: item for item in inputs}


class ScopeBucketingTests(unittest.TestCase):
    def _compile(self, facts, assumptions=None):
        request = {"facts": facts, "assumptions": assumptions or []}
        return compile_inputs(request, world=None, seats={}, fact_expr=_fact_expr, proposition_expr=_proposition_expr)

    def test_confirmed_night_deaths_default_public(self):
        items = self._compile([_night_deaths("f1")])
        self.assertEqual(items[0].scope, "public")

    def test_settled_day_vote_default_public(self):
        items = self._compile([_day_vote("f1", stage="settled")])
        self.assertEqual(items[0].scope, "public")

    def test_unsettled_day_vote_is_not_public(self):
        items = self._compile([_day_vote("f1", stage="voting")])
        self.assertEqual(items[0].scope, "conditional")

    def test_confirmed_private_observation_stays_conditional(self):
        items = self._compile([_ability("f1")])
        self.assertEqual(items[0].scope, "conditional")

    def test_confirmed_role_fact_defaults_conditional(self):
        items = self._compile([_role_fact("f1")])
        self.assertEqual(items[0].scope, "conditional")

    def test_explicit_scope_public_upgrades_confirmed_observation(self):
        items = self._compile([_ability("f1", **{"reasoner:scope": "public"})])
        self.assertEqual(items[0].scope, "public")

    def test_reported_forced_conditional_despite_public_override(self):
        items = self._compile([_role_fact("f1", status="reported", **{"reasoner:scope": "public"})])
        self.assertEqual(items[0].scope, "conditional")

    def test_explicit_scope_conditional_overrides_night_deaths_public(self):
        items = self._compile([_night_deaths("f1", **{"reasoner:scope": "conditional"})])
        self.assertEqual(items[0].scope, "conditional")


class SourceAndOwnerTests(unittest.TestCase):
    def _compile(self, facts, assumptions=None):
        request = {"facts": facts, "assumptions": assumptions or []}
        return compile_inputs(request, world=None, seats={}, fact_expr=_fact_expr, proposition_expr=_proposition_expr)

    def test_source_by_status_and_type(self):
        items = _by_id(
            self._compile(
                [
                    _role_fact("f_role"),
                    _role_fact("f_reported", status="reported"),
                    _ability("f_obs"),
                ]
            )
        )
        self.assertEqual(items["f_role"].source, SOURCE_OBSERVATION)
        self.assertEqual(items["f_reported"].source, SOURCE_SELF_CLAIM)
        self.assertEqual(items["f_obs"].source, SOURCE_RECEIVED)

    def test_explicit_source_overrides(self):
        items = self._compile([_ability("f1", **{"reasoner:source": "custom"})])
        self.assertEqual(items[0].source, "custom")

    def test_owner_of_role_fact_is_proposition_player(self):
        items = self._compile([_role_fact("f1", player_id="p7")])
        self.assertEqual(items[0].owner_id, "p7")

    def test_owner_of_observation_is_actor_not_target(self):
        fact = _ability("f1", actor_id="p3")
        fact["data"]["targets"] = ["p1", "p2"]
        items = self._compile([fact])
        self.assertEqual(items[0].owner_id, "p3")

    def test_explicit_owner_overrides_actor(self):
        items = self._compile([_ability("f1", actor_id="p3", **{"reasoner:owner_id": "p9"})])
        self.assertEqual(items[0].owner_id, "p9")

    def test_assumption_owner_is_player_id(self):
        items = self._compile([], [_assumption("a1", player_id="p5")])
        self.assertEqual(items[0].owner_id, "p5")


class DisabledAndSkipTests(unittest.TestCase):
    def test_disabled_facts_do_not_call_expr(self):
        calls = []

        def fact_expr(fact, world, seats):
            calls.append(fact.get("id"))
            return Bool(f"fact_{fact.get('id')}")

        request = {
            "facts": [_role_fact("off", enabled=False), _role_fact("on")],
            "assumptions": [],
        }
        items = compile_inputs(request, world=None, seats={}, fact_expr=fact_expr, proposition_expr=_proposition_expr)
        self.assertEqual(calls, ["on"])
        self.assertEqual([item.id for item in items], ["on"])

    def test_disabled_assumptions_are_skipped(self):
        request = {"facts": [], "assumptions": [_assumption("a_off", enabled=False), _assumption("a_on")]}
        items = compile_inputs(request, world=None, seats={}, fact_expr=_fact_expr, proposition_expr=_proposition_expr)
        self.assertEqual([item.id for item in items], ["a_on"])

    def test_none_expression_skips_entry(self):
        def fact_expr(fact, world, seats):
            return None

        items = compile_inputs({"facts": [_role_fact("f1")]}, world=None, seats={}, fact_expr=fact_expr, proposition_expr=_proposition_expr)
        self.assertEqual(items, [])

    def test_empty_request_yields_empty(self):
        items = compile_inputs({}, world=None, seats={}, fact_expr=_fact_expr, proposition_expr=_proposition_expr)
        self.assertEqual(items, [])


class AssumptionAndIdentityTests(unittest.TestCase):
    def test_assumption_claimed_false_and_defaults(self):
        seen = []

        def proposition_expr(proposition, world, seats, *, claimed):
            seen.append(claimed)
            return Bool("prop")

        items = compile_inputs(
            {"assumptions": [_assumption("a1", player_id="p0")]},
            world=None,
            seats={},
            fact_expr=_fact_expr,
            proposition_expr=proposition_expr,
        )
        self.assertEqual(seen, [False])
        self.assertEqual(items[0].scope, "conditional")
        self.assertEqual(items[0].source, SOURCE_ASSUMPTION)
        self.assertTrue(items[0].identity_claim)

    def test_assumption_explicit_overrides_apply(self):
        items = compile_inputs(
            {"assumptions": [_assumption("a1", **{"reasoner:scope": "public", "reasoner:source": "given", "reasoner:owner_id": "p8"})]},
            world=None,
            seats={},
            fact_expr=_fact_expr,
            proposition_expr=_proposition_expr,
        )
        self.assertEqual(items[0].scope, "public")
        self.assertEqual(items[0].source, "given")
        self.assertEqual(items[0].owner_id, "p8")

    def test_identity_claim_only_for_role_kind(self):
        items = _by_id(
            compile_inputs(
                {"facts": [_role_fact("f_role"), _night_deaths("f_night")]},
                world=None,
                seats={},
                fact_expr=_fact_expr,
                proposition_expr=_proposition_expr,
            )
        )
        self.assertTrue(items["f_role"].identity_claim)
        self.assertFalse(items["f_night"].identity_claim)


class MetadataTests(unittest.TestCase):
    def test_metadata_has_no_expr_and_is_json_serializable(self):
        items = compile_inputs(
            {"facts": [_role_fact("f1", player_id="p2")]},
            world=None,
            seats={},
            fact_expr=_fact_expr,
            proposition_expr=_proposition_expr,
        )
        metadata = input_metadata(items)
        self.assertEqual(len(metadata), 1)
        self.assertNotIn("expr", metadata[0])
        self.assertEqual(
            set(metadata[0]),
            {"id", "scope", "source", "owner_id", "identity_claim", "description"},
        )
        encoded = json.dumps(metadata, ensure_ascii=False)
        self.assertIn("f1", encoded)
        self.assertIn("role_id=chef", encoded)


if __name__ == "__main__":
    unittest.main()
