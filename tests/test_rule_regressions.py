"""Regression cases taken from official rules, not inferred from implementation."""

import unittest

from z3 import Not, Solver, sat, unsat

from botc_reasoner import Role, declare_variables
from botc_reasoner.rules import add_game_rules, _scarlet_woman_proc
from botc_reasoner.roles import BASE_SETUP


class RuleRegressions(unittest.TestCase):
    def test_night_starpass_prefers_healthy_scarlet_at_five_alive(self):
        world = declare_variables(5, n_nights=2, tag="scarlet_starpass")
        from botc_reasoner.rules import _add_night_kills
        solver = Solver()
        _add_night_kills(solver, world)
        solver.add(*world.alive_night_start[2].values())
        for player in world.player_ids:
            for role in Role:
                expected = Role.IMP if player == 0 else Role.SCARLET_WOMAN if player == 1 else Role.POISONER if player == 2 else Role.CHEF
                solver.add(world.role_night_start[2][player][role] == (role is expected))
            solver.add(Not(world.is_droisoned(player, 2)))
        solver.add(world.imp_choice[2][0], Not(world.starpass_heir[2][1]))
        self.assertEqual(solver.check(), unsat)

    def test_scarlet_trigger_counts_demon_before_death(self):
        world = declare_variables(5, n_nights=1, tag="scarlet_five")
        solver = Solver()
        solver.add(*world.alive_dawn[1].values())
        solver.add(world.role_dawn[1][0][Role.IMP], world.executed[1][0])
        solver.add(world.role_dawn[1][1][Role.SCARLET_WOMAN], Not(world.is_droisoned(1, 1)),
                   Not(world.executed[1][1]), Not(world.slayer_kill[1][1]))
        solver.add(Not(_scarlet_woman_proc(world, 1)))
        self.assertEqual(solver.check(), unsat)

    def test_dead_player_cannot_vote_on_two_different_days(self):
        world = declare_variables(5, n_nights=2, tag="ghost_two_days")
        solver = world.build_solver()
        add_game_rules(solver, world, *BASE_SETUP[5])
        solver.set(timeout=3000)
        solver.add(Not(world.alive_dawn[1][0]), world.voted[1][1][0], world.voted[2][1][0])
        self.assertEqual(solver.check(), unsat)

    def test_dead_vote_budget_has_explicit_cross_day_constraint(self):
        # Isolate this rule from continuity: both days dead, one ballot each.
        from botc_reasoner.rules import collect_game_rules
        world = declare_variables(5, n_nights=2, tag="ghost_isolated")
        rules = collect_game_rules(world, *BASE_SETUP[5])
        solver = Solver()
        solver.add([r.expr for r in rules.records if r.rule_id == "tb:ghost_votes"])
        solver.add(Not(world.alive_dawn[1][0]), Not(world.alive_dawn[2][0]),
                   world.voted[1][1][0], world.voted[2][1][0])
        self.assertEqual(solver.check(), unsat)

    def test_live_vote_does_not_consume_later_dead_vote(self):
        from botc_reasoner.rules import collect_game_rules
        world = declare_variables(5, n_nights=2, tag="ghost_live_then_dead")
        rules = collect_game_rules(world, *BASE_SETUP[5])
        solver = Solver()
        solver.add([r.expr for r in rules.records if r.rule_id == "tb:ghost_votes"])
        solver.add(world.alive_dawn[1][0], Not(world.alive_dawn[2][0]),
                   world.voted[1][1][0], world.voted[2][1][0])
        self.assertEqual(solver.check(), sat)
