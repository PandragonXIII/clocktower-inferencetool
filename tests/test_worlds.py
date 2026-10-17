"""候选世界枚举（``botc_reasoner.worlds``）测试。

覆盖：one-hot 玩家角色的联合世界枚举、隐藏变量去重、枚举不污染调用方 solver、
数量上限截断、以及预算耗尽与背景状态的诚实标注。
"""

import time
import unittest
from unittest.mock import patch

from z3 import Bool, Solver, sat, unknown

from botc_reasoner.analysis import Budget
from botc_reasoner.worlds import (
    TRUNCATED_DEADLINE,
    TRUNCATED_MAX_WORLDS,
    TRUNCATED_SOLVER_UNKNOWN,
    enumerate_worlds,
)


class JointWorldsTests(unittest.TestCase):
    def test_empty_projection_is_one_joint_world(self):
        result = enumerate_worlds(Solver(), [], Budget())
        self.assertTrue(result["complete"])
        self.assertEqual(result["worlds"], [{"roles": {}}])

    def test_limit_probe_unknown_preserves_timeout_reason(self):
        with patch.object(Budget, "check", return_value=unknown):
            result = enumerate_worlds(Solver(), [], Budget(), max_worlds=0)
        self.assertFalse(result["complete"])
        self.assertEqual(result["truncated_reason"], TRUNCATED_SOLVER_UNKNOWN)

    def test_onehot_two_players_enumerates_joint_worlds(self):
        p0_a, p0_b = Bool("p0_a"), Bool("p0_b")
        p1_a, p1_b = Bool("p1_a"), Bool("p1_b")
        solver = Solver()
        solver.add(p0_a != p0_b)
        solver.add(p1_a != p1_b)

        projection = [
            ("p0", [("a", p0_a), ("b", p0_b)]),
            ("p1", [("a", p1_a), ("b", p1_b)]),
        ]
        result = enumerate_worlds(solver, projection, Budget(), max_worlds=20)

        self.assertTrue(result["complete"])
        self.assertEqual(result["returned_count"], 4)
        self.assertEqual(result["total"], 4)
        self.assertIsNone(result["truncated_reason"])
        seen = {tuple(sorted(w["roles"].items())) for w in result["worlds"]}
        self.assertEqual(
            seen,
            {
                (("p0", "a"), ("p1", "a")),
                (("p0", "a"), ("p1", "b")),
                (("p0", "b"), ("p1", "a")),
                (("p0", "b"), ("p1", "b")),
            },
        )

    def test_unique_roles_constraint_limits_worlds(self):
        p0_a, p0_b = Bool("u0_a"), Bool("u0_b")
        p1_a, p1_b = Bool("u1_a"), Bool("u1_b")
        solver = Solver()
        solver.add(p0_a != p0_b)
        solver.add(p1_a != p1_b)
        solver.add(p0_a != p1_a)

        projection = [
            ("p0", [("a", p0_a), ("b", p0_b)]),
            ("p1", [("a", p1_a), ("b", p1_b)]),
        ]
        result = enumerate_worlds(solver, projection, Budget())

        self.assertTrue(result["complete"])
        self.assertEqual(result["total"], 2)
        worlds = {tuple(sorted(w["roles"].items())) for w in result["worlds"]}
        self.assertEqual(worlds, {(("p0", "a"), ("p1", "b")), (("p0", "b"), ("p1", "a"))})

    def test_result_contains_no_z3_objects(self):
        a, b = Bool("nc_a"), Bool("nc_b")
        solver = Solver()
        solver.add(a != b)
        projection = [("p0", [("a", a), ("b", b)])]
        result = enumerate_worlds(solver, projection, Budget())
        self.assertEqual(result["worlds"], [{"roles": {"p0": "a"}}, {"roles": {"p0": "b"}}])
        self.assertIsInstance(result["worlds"][0]["roles"]["p0"], str)


class HiddenVariableDedupTests(unittest.TestCase):
    def test_hidden_variable_does_not_duplicate_worlds(self):
        a, b = Bool("hd_a"), Bool("hd_b")
        hidden = Bool("hd_hidden")
        solver = Solver()
        solver.add(a != b)

        projection = [("p0", [("a", a), ("b", b)])]
        result = enumerate_worlds(solver, projection, Budget())

        self.assertTrue(result["complete"])
        self.assertEqual(result["returned_count"], 2)
        self.assertEqual(result["total"], 2)
        worlds = [w["roles"]["p0"] for w in result["worlds"]]
        self.assertEqual(sorted(worlds), ["a", "b"])


class SolverHygieneTests(unittest.TestCase):
    def test_solver_is_not_polluted(self):
        a, b = Bool("hy_a"), Bool("hy_b")
        solver = Solver()
        solver.add(a != b)
        before = len(solver.assertions())
        before_status = solver.check()

        projection = [("p0", [("a", a), ("b", b)])]
        enumerate_worlds(solver, projection, Budget())

        self.assertEqual(len(solver.assertions()), before)
        self.assertEqual(solver.check(), before_status)
        self.assertEqual(before_status, sat)


class TruncationTests(unittest.TestCase):
    def _four_world_solver(self):
        p0_a, p0_b = Bool("t0_a"), Bool("t0_b")
        p1_a, p1_b = Bool("t1_a"), Bool("t1_b")
        solver = Solver()
        solver.add(p0_a != p0_b)
        solver.add(p1_a != p1_b)
        projection = [
            ("p0", [("a", p0_a), ("b", p0_b)]),
            ("p1", [("a", p1_a), ("b", p1_b)]),
        ]
        return solver, projection

    def test_max_worlds_truncates_when_more_remain(self):
        solver, projection = self._four_world_solver()
        result = enumerate_worlds(solver, projection, Budget(), max_worlds=2)

        self.assertFalse(result["complete"])
        self.assertEqual(result["returned_count"], 2)
        self.assertIsNone(result["total"])
        self.assertEqual(result["truncated_reason"], TRUNCATED_MAX_WORLDS)

    def test_reaching_max_worlds_with_no_more_is_complete(self):
        solver, projection = self._four_world_solver()
        result = enumerate_worlds(solver, projection, Budget(), max_worlds=4)

        self.assertTrue(result["complete"])
        self.assertEqual(result["total"], 4)
        self.assertIsNone(result["truncated_reason"])

    def test_zero_max_worlds_is_truncated(self):
        solver, projection = self._four_world_solver()
        result = enumerate_worlds(solver, projection, Budget(), max_worlds=0)

        self.assertFalse(result["complete"])
        self.assertEqual(result["returned_count"], 0)
        self.assertEqual(result["truncated_reason"], TRUNCATED_MAX_WORLDS)

    def test_exhausted_budget_returns_partial_deadline(self):
        a, b = Bool("bd_a"), Bool("bd_b")
        solver = Solver()
        solver.add(a != b)
        budget = Budget(total_ms=1, per_solve_ms=1)
        time.sleep(0.02)
        projection = [("p0", [("a", a), ("b", b)])]
        result = enumerate_worlds(solver, projection, budget)

        self.assertFalse(result["complete"])
        self.assertEqual(result["returned_count"], 0)
        self.assertIsNone(result["total"])
        self.assertEqual(result["truncated_reason"], TRUNCATED_DEADLINE)


class BaseStatusTests(unittest.TestCase):
    def test_unsat_background_is_complete_empty(self):
        a = Bool("bs_a")
        solver = Solver()
        solver.add(a, a == False)
        result = enumerate_worlds(solver, [("p0", [("a", a)])], Budget(), base_status="unsat")

        self.assertTrue(result["complete"])
        self.assertEqual(result["returned_count"], 0)
        self.assertEqual(result["total"], 0)
        self.assertIsNone(result["truncated_reason"])

    def test_unknown_background_is_incomplete(self):
        a = Bool("bs2_a")
        solver = Solver()
        result = enumerate_worlds(
            solver, [("p0", [("a", a)])], Budget(), base_status="unknown"
        )

        self.assertFalse(result["complete"])
        self.assertEqual(result["returned_count"], 0)
        self.assertIsNone(result["total"])
        self.assertEqual(result["truncated_reason"], TRUNCATED_SOLVER_UNKNOWN)

    def test_unsat_solver_with_default_base_status_returns_empty_complete(self):
        a = Bool("bs3_a")
        solver = Solver()
        solver.add(a, a == False)
        result = enumerate_worlds(solver, [("p0", [("a", a)])], Budget())

        self.assertTrue(result["complete"])
        self.assertEqual(result["returned_count"], 0)
        self.assertEqual(result["total"], 0)
        self.assertIsNone(result["truncated_reason"])


if __name__ == "__main__":
    unittest.main()
