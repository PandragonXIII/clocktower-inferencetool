"""Logical guarantees of scoped analysis and bounded repairs."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from z3 import Bool, Not, Solver, sat, unknown

from botc_reasoner.analysis import Budget, InputConstraint, diagnose, query_status
from botc_reasoner.pipeline import analyze
from botc_reasoner.provenance import ConstraintRecord
from botc_reasoner.repairs import minimum_repairs


class AnalysisTests(unittest.TestCase):
    def test_queries_never_explode_on_inconsistent_background(self):
        x = Bool("analysis_x")
        solver = Solver()
        solver.add(x)
        self.assertEqual(query_status(solver, x, Budget())["status"], "necessary")
        self.assertEqual(query_status(solver, Not(x), Budget())["status"], "impossible")
        self.assertEqual(query_status(solver, x, Budget(), "unsat")["status"], "inconsistent")

    def test_real_rule_and_input_ids_are_tracked(self):
        x = Bool("diagnosis_x")
        rules = [ConstraintRecord(x, "tb:test", "test#1")]
        result = diagnose([], rules, [InputConstraint("claim", Not(x))], Budget())
        self.assertEqual(result["status"], "unsat")
        self.assertEqual(set(result["rule_ids"]), {"tb:test"})
        self.assertEqual(set(result["input_ids"]), {"claim"})
        self.assertEqual(result["minimality"], "inclusion")

    def test_expired_budget_is_unknown(self):
        budget = Budget()
        budget._deadline = 0
        self.assertEqual(str(budget.check(Solver())), "unknown")
        self.assertTrue(budget.hit)

    def test_domain_conflict_retains_its_rule_reference(self):
        x = Bool("domain_diagnosis_x")
        result = diagnose([x], [], [InputConstraint("claim", Not(x))], Budget())
        self.assertEqual(result["status"], "unsat")
        self.assertEqual(set(result["rule_ids"]), {"tb:domain"})

    def test_public_conclusion_survives_conditional_conflict(self):
        x = Bool("pipeline_x")
        request = {"request_id": "request", "game": {"id": "game", "revision": 0,
                   "players": [{"id": "p1", "seat": 1}]},
                   "queries": [{"id": "query", "proposition": {"kind": "test"}}]}
        world = SimpleNamespace(encoding_axioms=lambda: [])
        collector = SimpleNamespace(records=[], catalog={})
        inputs = [InputConstraint("death", x, "public"), InputConstraint("claim", Not(x))]
        result = analyze(request, world, collector, inputs, lambda p: x, lambda s: [], [])
        scopes = result["extensions"]["reasoner:scopes"]
        self.assertEqual(scopes["public"]["results"][0]["status"], "necessary")
        self.assertEqual(result["consistency"], "unsat")
        self.assertEqual(result["results"][0]["status"], "inconsistent")

    def test_received_and_assumed_share_conditional_semantics(self):
        x = Bool("received_x")
        for source in ("received", "assumption"):
            with self.subTest(source=source):
                item = InputConstraint("private", x, source=source)
                solver = Solver()
                solver.add(item.expr)
                self.assertEqual(query_status(solver, x, Budget())["status"], "necessary")

    def test_pipeline_enumerates_joint_worlds_and_retains_initial_model(self):
        x = Bool("joint_pipeline_x")
        request = {"request_id": "request", "game": {"id": "game", "revision": 0,
                   "players": [{"id": "p1", "seat": 1}]}, "queries": [],
                   "options": {"max_worlds": 10}}
        result = analyze(request, SimpleNamespace(encoding_axioms=lambda: []),
                         SimpleNamespace(records=[], catalog={}), [], lambda p: x,
                         lambda s: [{"value": str(s.model().eval(x, model_completion=True))}],
                         [("p1", [("a", x), ("b", Not(x))])])
        self.assertEqual(result["consistency"], "sat")
        self.assertEqual(len(result["model"]["assignments"]), 1)
        worlds = result["extensions"]["reasoner:worlds"]
        self.assertTrue(worlds["complete"])
        self.assertEqual(worlds["total"], 2)

    def test_unknown_role_checks_are_not_excluded_in_legacy_output(self):
        x = Bool("unknown_pipeline_x")
        request = {"request_id": "request", "game": {"id": "game", "revision": 0,
                   "players": [{"id": "p1", "seat": 1}]}, "queries": []}
        original = Budget.check
        calls = 0

        def checked(budget, solver, *assumptions):
            nonlocal calls
            calls += 1
            return original(budget, solver, *assumptions) if calls <= 2 else unknown

        with patch.object(Budget, "check", checked):
            result = analyze(request, SimpleNamespace(encoding_axioms=lambda: []),
                             SimpleNamespace(records=[], catalog={}), [], lambda p: x, lambda s: [],
                             [("p1", [("a", x), ("b", Not(x))])])
        ext = result["extensions"]
        row = ext["reasoner:role_ranges"]["rows"][0]
        self.assertEqual(row["role_ids"], [])
        self.assertEqual(row["impossible_role_ids"], [])
        self.assertFalse(row["complete"])
        self.assertEqual(ext["trouble_brewing:possible_roles"][0]["role_ids"], ["a", "b"])

    def test_repairs_preserve_public_and_verify_full_problem(self):
        x, y = Bool("repair_x"), Bool("repair_y")
        inputs = [InputConstraint("public", x, "public"),
                  InputConstraint("wrong", Not(x), owner_id="p1", identity_claim=True),
                  InputConstraint("a", y, owner_id="p2", identity_claim=True),
                  InputConstraint("b", Not(y), owner_id="p3", identity_claim=True)]
        result = minimum_repairs([], [], inputs, Budget(), max_repairs=10, identity_only=True)
        self.assertEqual(result["optimality"], "optimal")
        for candidate in result["candidates"]:
            removed = candidate["removed_input_ids"]
            self.assertNotIn("public", removed)
            self.assertIn("wrong", removed)
            self.assertEqual(candidate["cost"]["owners"], 2)
            solver = Solver()
            solver.add([item.expr for item in inputs if item.id not in removed])
            self.assertEqual(solver.check(), sat)

    def test_identity_repair_does_not_delete_private_observations(self):
        x = Bool("identity_repair_x")
        inputs = [InputConstraint("observation", x, source="received"),
                  InputConstraint("claim", Not(x), identity_claim=True, owner_id="p1")]
        result = minimum_repairs([], [], inputs, Budget(), identity_only=True)
        self.assertEqual(result["candidates"][0]["removed_input_ids"], ["claim"])

    def test_repair_search_limit_does_not_claim_no_solution(self):
        result = minimum_repairs([], [], [], Budget(), max_checks=0)
        self.assertFalse(result["complete"])
        self.assertEqual(result["optimality"], "unknown")


class ProbabilityModePipelineTests(unittest.TestCase):
    """概率模式只跳过 diagnose / role_ranges，显式查询、修复和世界枚举仍运行。"""

    def test_sat_mode_keeps_queries_and_worlds_but_skips_diagnosis_and_ranges(self):
        x = Bool("probability_mode_sat_x")
        request = {"request_id": "request", "game": {"id": "game", "revision": 0,
                   "players": [{"id": "p1", "seat": 1}]},
                   "queries": [{"id": "query", "proposition": {"kind": "test"}}],
                   "options": {"probability_mode": True, "max_worlds": 10}}
        projection = [("p1", [("a", x), ("b", Not(x))])]
        with patch("botc_reasoner.pipeline.diagnose") as diagnose:
            result = analyze(request, SimpleNamespace(encoding_axioms=lambda: []),
                             SimpleNamespace(records=[], catalog={}),
                             [InputConstraint("public", x, "public")], lambda p: x,
                             lambda s: [], projection)
        diagnose.assert_not_called()
        extensions = result["extensions"]
        self.assertEqual(result["consistency"], "sat")
        self.assertEqual(result["results"][0]["status"], "necessary")
        self.assertNotIn("reasoner:role_ranges", extensions)
        self.assertNotIn("trouble_brewing:possible_roles", extensions)
        self.assertEqual(extensions["reasoner:diagnosis"], {})
        worlds = extensions["reasoner:worlds"]
        self.assertTrue(worlds["complete"])
        self.assertEqual(worlds["total"], 1)

    def test_unsat_mode_keeps_unsat_and_repairs_without_diagnosis(self):
        x = Bool("probability_mode_unsat_x")
        request = {"request_id": "request", "game": {"id": "game", "revision": 0,
                   "players": [{"id": "p1", "seat": 1}]},
                   "queries": [{"id": "query", "proposition": {"kind": "test"}}],
                   "options": {"probability_mode": True, "max_repairs": 1}}
        inputs = [InputConstraint("public", x, "public"),
                  InputConstraint("claim", Not(x), owner_id="p1")]
        with patch("botc_reasoner.pipeline.diagnose") as diagnose:
            result = analyze(request, SimpleNamespace(encoding_axioms=lambda: []),
                             SimpleNamespace(records=[], catalog={}), inputs,
                             lambda p: x, lambda s: [], [])
        diagnose.assert_not_called()
        extensions = result["extensions"]
        self.assertEqual(result["consistency"], "unsat")
        self.assertEqual(result["results"][0]["status"], "inconsistent")
        self.assertEqual(extensions["reasoner:diagnosis"], {})
        self.assertNotIn("conflicts", result)
        self.assertNotIn("reasoner:role_ranges", extensions)
        repairs = extensions["reasoner:repairs"]
        self.assertEqual(
            repairs["general"]["candidates"][0]["removed_input_ids"], ["claim"]
        )
