"""Budget behaviour of :func:`estimate_role_probabilities`.

预算耗尽或求解返回 ``unknown`` 时必须抛出 :class:`ProbabilityIncomplete`，调用方据此
把结果标为 ``unknown``；绝不允许把未判定的组或世界当成排除掉，也不允许返回部分结果。
不传预算时，原 API 行为保持不变。
"""

import unittest
from unittest.mock import patch

from z3 import Bool, unknown

from botc_reasoner import Role, add_game_rules, declare_variables, estimate_role_probabilities
from botc_reasoner.analysis import REASON_BUDGET_EXHAUSTED, Budget
from botc_reasoner.probability import (
    AbilityObservation,
    ProbabilityIncomplete,
    _current_budget,
)
from botc_reasoner.variables import Ability


def _solver_world(n_players=5, tag="budget"):
    world = declare_variables(n_players, n_nights=1, tag=tag)
    solver = world.build_solver()
    add_game_rules(solver, world, 3, 0, 1, 1)
    return solver, world


class ExpiredBudgetTests(unittest.TestCase):
    def test_expired_budget_never_calls_the_solver(self):
        solver, world = _solver_world(tag="budget_expired")
        budget = Budget()
        budget._deadline = 0
        with patch.object(solver, "check", side_effect=AssertionError("solver must not run")) as mocked:
            with self.assertRaises(ProbabilityIncomplete):
                estimate_role_probabilities(
                    5,
                    (3, 0, 1, 1),
                    solver=solver,
                    world=world,
                    budget=budget,
                )
        mocked.assert_not_called()
        self.assertTrue(budget.hit)

    def test_budget_is_reset_after_the_exception(self):
        solver, world = _solver_world(tag="budget_reset")
        budget = Budget()
        budget._deadline = 0
        with self.assertRaises(ProbabilityIncomplete):
            estimate_role_probabilities(
                5, (3, 0, 1, 1), solver=solver, world=world, budget=budget
            )
        self.assertIsNone(_current_budget.get())


class UnknownIsNotExcludedTests(unittest.TestCase):
    def test_solver_unknown_raises_instead_of_excluding_the_group(self):
        solver, world = _solver_world(tag="budget_unknown")
        budget = Budget(total_ms=100_000, per_solve_ms=100_000)
        with patch.object(solver, "check", return_value=unknown):
            with self.assertRaises(ProbabilityIncomplete):
                estimate_role_probabilities(
                    5,
                    (3, 0, 1, 1),
                    solver=solver,
                    world=world,
                    budget=budget,
                )

    def test_unknown_does_not_fall_back_to_sampling(self):
        solver, world = _solver_world(tag="budget_unknown_sample")
        budget = Budget(total_ms=100_000, per_solve_ms=100_000)
        with patch.object(solver, "check", return_value=unknown):
            with self.assertRaises(ProbabilityIncomplete):
                estimate_role_probabilities(
                    5,
                    (3, 0, 1, 1),
                    soft_roles=[(1, Role.WASHERWOMAN)],
                    solver=solver,
                    world=world,
                    budget=budget,
                )

    def test_incomplete_reason_surfaces_to_the_caller(self):
        solver, world = _solver_world(tag="budget_reason")
        budget = Budget()
        budget._deadline = 0
        with self.assertRaises(ProbabilityIncomplete) as caught:
            estimate_role_probabilities(
                5, (3, 0, 1, 1), solver=solver, world=world, budget=budget
            )
        self.assertEqual(str(caught.exception), REASON_BUDGET_EXHAUSTED)


class TrustedObservationInterferenceTests(unittest.TestCase):
    """`trusted_abilities`（本人/HTTP 确定观察）必须进入干扰乘数计算。

    回归：调用 ``_interference_factor`` 时过去只传 ``soft_abilities``，导致确定观察
    的投毒/酒鬼/陪衬健康信息权重被漏算。修复只把确定观察并入加权阶段的
    ``soft_abilities`` 与 ``trusted_claims``，不改变 `_assert_group` 的硬约束。
    """

    def test_interference_factor_receives_trusted_observation(self):
        solver, world = _solver_world(tag="budget_interference")
        claim = Bool("trusted_night_one")
        observation = AbilityObservation(0, Ability.FORTUNE_TELLER, 1, claim)

        captured = {}

        def fake_interference(*args, **kwargs):
            captured["soft_abilities"] = list(kwargs["soft_abilities"])
            captured["trusted_claims"] = list(kwargs["trusted_claims"])
            return 1.0

        with patch(
            "botc_reasoner.probability._interference_factor",
            side_effect=fake_interference,
        ) as mocked:
            probabilities = estimate_role_probabilities(
                5,
                (3, 0, 1, 1),
                trusted_abilities=[observation],
                solver=solver,
                world=world,
                seed=1,
                target_accepted=8,
                max_trials=8,
                budget=Budget(total_ms=1_000_000, per_solve_ms=1_000_000),
            )

        self.assertIsNotNone(probabilities)
        self.assertTrue(mocked.called)
        self.assertIn(observation, captured["soft_abilities"])
        self.assertIn((0, Role.FORTUNE_TELLER), captured["trusted_claims"])


class NoBudgetRegressionTests(unittest.TestCase):
    def test_original_api_without_budget_still_works(self):
        probabilities = estimate_role_probabilities(
            5,
            (3, 0, 1, 1),
            seed=1,
            target_accepted=3000,
            max_trials=3000,
        )
        self.assertIsNotNone(probabilities)
        assert probabilities is not None
        self.assertAlmostEqual(
            sum(item.get(Role.IMP, 0.0) for item in probabilities), 1.0, delta=0.04
        )

    def test_generous_budget_matches_unbudgeted_result(self):
        solver, world = _solver_world(tag="budget_generous")
        unbudgeted = estimate_role_probabilities(
            5, (3, 0, 1, 1), solver=solver, world=world, seed=7,
            target_accepted=200, max_trials=2000,
        )
        budgeted = estimate_role_probabilities(
            5, (3, 0, 1, 1), solver=solver, world=world, seed=7,
            target_accepted=200, max_trials=2000,
            budget=Budget(total_ms=1_000_000, per_solve_ms=1_000_000),
        )
        self.assertIsNotNone(unbudgeted)
        self.assertEqual(unbudgeted, budgeted)


if __name__ == "__main__":
    unittest.main()
