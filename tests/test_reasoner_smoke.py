"""Minimal smoke tests for the direct ``botc_reasoner`` Z3 model.

These replace the removed generic ``engine`` tests: they check that the static
role catalog/setup table is self-consistent, that the setup rules actually
enforce role uniqueness, and that ``main.py demo`` runs against the real model.
Full rule coverage lives in ``botc_reasoner``'s own ``-m`` self checks.
"""

import contextlib
import io
import unittest

from z3 import sat, unsat

import main as main_module
from botc_reasoner import Role, add_game_rules, declare_variables
from botc_reasoner.roles import BASE_SETUP, validate_catalog


class CatalogAndSetupTests(unittest.TestCase):
    def test_catalog_is_self_consistent(self):
        validate_catalog()

    def test_base_setup_covers_legal_player_counts(self):
        self.assertTrue(all(5 <= n <= 15 for n in BASE_SETUP))
        for n_players, counts in BASE_SETUP.items():
            with self.subTest(n_players=n_players):
                self.assertEqual(sum(counts), n_players)
                self.assertEqual(counts[3], 1)

    def test_setup_rules_forbid_two_players_same_role(self):
        world = declare_variables(5, n_nights=1, tag="smoke_unique")
        solver = world.build_solver()
        add_game_rules(solver, world, *BASE_SETUP[5])
        self.assertEqual(solver.check(), sat)

        solver.add(world.start_is(0, Role.CHEF), world.start_is(1, Role.CHEF))
        self.assertEqual(solver.check(), unsat)


class DemoSmokeTests(unittest.TestCase):
    def test_demo_runs_on_real_model(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = main_module.run_demo()
        self.assertEqual(code, 0)
        self.assertIn("sat", out.getvalue())


if __name__ == "__main__":
    unittest.main()
