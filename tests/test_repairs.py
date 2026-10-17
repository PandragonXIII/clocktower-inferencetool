"""Repair search must distinguish optimal cost from complete enumeration."""

import unittest
from unittest.mock import patch

from z3 import Bool, Not, unknown

from botc_reasoner.analysis import Budget, InputConstraint
from botc_reasoner.repairs import minimum_repairs


class RepairTests(unittest.TestCase):
    def test_owner_count_is_prioritized_over_input_count(self):
        x, y = Bool("owner_x"), Bool("owner_y")
        inputs = [InputConstraint("a", x, owner_id="p1"),
                  InputConstraint("b", y, owner_id="p1"),
                  InputConstraint("c", Not(x), owner_id="p2"),
                  InputConstraint("d", Not(y), owner_id="p3")]
        result = minimum_repairs([], [], inputs, Budget(), max_repairs=10)
        self.assertTrue(result["complete"])
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["removed_input_ids"], ["a", "b"])
        self.assertEqual(result["candidates"][0]["cost"], {"owners": 1, "inputs": 2})

    def test_candidate_limit_preserves_proven_optimal_cost(self):
        x = Bool("limited_repair_x")
        inputs = [InputConstraint("a", x), InputConstraint("b", Not(x))]
        result = minimum_repairs([], [], inputs, Budget(), max_repairs=1)
        self.assertFalse(result["complete"])
        self.assertEqual(result["optimality"], "optimal")
        self.assertEqual(len(result["candidates"]), 1)

    def test_unknown_never_claims_no_solution_or_optimality(self):
        with patch.object(Budget, "check", return_value=unknown):
            result = minimum_repairs([], [], [], Budget())
        self.assertFalse(result["complete"])
        self.assertEqual(result["optimality"], "unknown")
        self.assertEqual(result["candidates"], [])

    def test_public_conflict_cannot_be_repaired(self):
        x = Bool("public_repair_x")
        inputs = [InputConstraint("a", x, "public"), InputConstraint("b", Not(x), "public")]
        result = minimum_repairs([], [], inputs, Budget())
        self.assertTrue(result["complete"])
        self.assertEqual(result["candidates"], [])

    def test_sat_problem_needs_no_withdrawal(self):
        result = minimum_repairs([], [], [], Budget(), max_repairs=10)
        self.assertTrue(result["complete"])
        self.assertEqual(result["candidates"][0]["removed_input_ids"], [])

    def test_invalid_return_limit_is_rejected(self):
        for limit in (0, -1, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                minimum_repairs([], [], [], Budget(), max_repairs=limit)
