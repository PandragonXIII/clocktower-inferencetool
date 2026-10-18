"""UI-shaped records must be validated and actually constrain model variables."""

import unittest

from z3 import Not, Solver, sat, unsat

import connector
from backend.validation import validate_request
from botc_reasoner import Role, declare_variables
from botc_reasoner.participation import describe_participation
from botc_reasoner.rules import collect_game_rules
from botc_reasoner.roles import BASE_SETUP
from botc_reasoner.analysis import build_solver
from test_extension_validation import with_facts, observation_fact, day_vote_fact


class FrontendConditionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = declare_variables(5, n_nights=2, tag="frontend_conditions")
        cls.seats = {f"p{i + 1}": i for i in range(5)}

    def assert_entails(self, expr, consequence):
        solver = Solver()
        solver.add(expr, Not(consequence))
        self.assertEqual(solver.check(), unsat)

    def test_global_absence_is_valid_and_excludes_every_player_at_time(self):
        fact = {"id": "global", "type": "botc:global_assumption", "enabled": True,
                "status": "reported", "data": {"kind": "role_absent", "role_id": "imp",
                "time": {"phase": "day", "number": 1}, "requested_enabled": True}}
        request = with_facts(fact)
        validate_request(request)
        expr = connector._fact_expr(fact, self.world, self.seats)
        for player in self.world.player_ids:
            self.assert_entails(expr, Not(self.world.role_after_day(1, player, Role.IMP)))
        fact["enabled"] = False
        self.assertIsNone(connector._fact_expr(fact, self.world, self.seats))

    def test_all_new_skill_shapes_validate_and_have_honest_participation(self):
        cases = [
            ("virgin", ["p2"], {"kind": "choice", "value": "executed"}, "day"),
            ("soldier", [], {"kind": "choice", "value": "survived"}, "night"),
            ("mayor", [], {"kind": "choice", "value": "three_alive_no_execution_win"}, "day"),
            ("drunk", [], {"kind": "role", "role_id": "chef"}, "night"),
            ("recluse", [], {"kind": "choice", "value": "alignment"}, "night"),
            ("saint", [], {"kind": "choice", "value": "good_lost"}, "day"),
            ("spy", [], {"kind": "text", "text": "1号是厨师"}, "night"),
            ("scarlet_woman", [], {"kind": "choice", "value": "occurred"}, "day"),
            ("baron", [], {"kind": "number", "value": 2}, "night"),
        ]
        for role, targets, result, phase in cases:
            with self.subTest(role=role):
                fact = observation_fact("observation", role, targets, result, time={"phase": phase, "number": 1})
                request = with_facts(fact)
                validate_request(request)
                expr = connector._fact_expr(fact, self.world, self.seats)
                if role in {"spy", "recluse"}:
                    self.assertIsNone(expr)
                    self.assertEqual(describe_participation(request, [])[0]["status"], "record_only")
                else:
                    self.assertIsNotNone(expr)

    def test_survived_results_forbid_reported_deaths(self):
        for role, phase in (("imp", "night"), ("slayer", "day")):
            fact = observation_fact("survived", role, ["p2"], {"kind": "choice", "value": "survived"},
                                    time={"phase": phase, "number": 2})
            validate_request(with_facts(fact))
            expr = connector._fact_expr(fact, self.world, self.seats)
            death = self.world.night_death[2][1] if role == "imp" else self.world.slayer_kill[2][1]
            self.assert_entails(expr, Not(death))

    def test_votes_bind_actual_voters_and_finished_slots(self):
        fact = day_vote_fact(data={"nominations": [{"id": "nom", "nominator_id": "p1",
                          "nominee_id": "p2", "voter_ids": ["p3"], "count": 1}],
                          "execution": {"player_id": None}})
        validate_request(with_facts(fact))
        expr = connector._fact_expr(fact, self.world, self.seats)
        self.assert_entails(expr, self.world.nominator[1][1][0])
        self.assert_entails(expr, self.world.nominee[1][1][1])
        self.assert_entails(expr, self.world.voted[1][1][2])
        self.assert_entails(expr, Not(self.world.voted[1][1][0]))
        self.assert_entails(expr, Not(self.world.nomination_happened[1][2]))

    def test_drunk_observation_sets_mask_not_true_townsfolk_identity(self):
        fact = observation_fact("mask", "drunk", [], {"kind": "role", "role_id": "chef"},
                                time={"phase": "night", "number": 1})
        expr = connector._fact_expr(fact, self.world, self.seats)
        self.assert_entails(expr, self.world.drunk_mask[Role.CHEF])
        self.assert_entails(expr, self.world.is_drunk[0])

    def test_global_absence_reaches_the_real_solver(self):
        fact = {"id": "no-demon", "type": "botc:global_assumption", "enabled": True,
                "status": "reported", "data": {"kind": "role_absent", "role_id": "imp",
                "time": {"phase": "setup"}, "requested_enabled": True}}
        request = with_facts(fact)
        request["assumptions"] = []
        request["queries"] = []
        request["game"]["time"] = {"phase": "setup"}
        validate_request(request)
        world, collector, inputs, _ = connector._prepare_context(request)
        solver = build_solver(world.encoding_axioms(), collector.records, inputs)
        self.assertEqual(solver.check(), unsat)
        fact["enabled"] = False
        world, collector, inputs, _ = connector._prepare_context(request)
        self.assertNotIn("no-demon", [i.id for i in inputs])
        self.assertEqual(build_solver(world.encoding_axioms(), collector.records, inputs).check(), sat)

    def test_healthy_actor_target_controls_actual_poison_selection(self):
        fact = observation_fact("poison", "poisoner", ["p2"], {"kind": "no_direct_result"},
                                time={"phase": "night", "number": 1})
        world = self.world
        expr = connector._fact_expr(fact, world, self.seats)
        solver = Solver()
        solver.add(expr, world.role_night_start[1][0][Role.POISONER],
                   world.alive_night_start[1][0], Not(world.is_droisoned(0, 1)),
                   Not(world.poison_choice[1][1]))
        self.assertEqual(solver.check(), unsat)
        solver = Solver()
        solver.add(expr, world.is_droisoned(0, 1), Not(world.poison_choice[1][1]))
        self.assertEqual(solver.check(), sat)

    def test_self_nomination_is_legal_in_real_model(self):
        world = self.world
        collector = collect_game_rules(world, *BASE_SETUP[5])
        solver = build_solver(world.encoding_axioms(), collector.records)
        solver.set(timeout=3000)
        solver.add(world.nomination_happened[1][1], world.nominator[1][1][0], world.nominee[1][1][0])
        self.assertEqual(solver.check(), sat)

    def test_partial_voting_does_not_assert_no_further_nominations(self):
        fact = day_vote_fact(data={"stage": "voting", "execution": None, "nominations": []})
        validate_request(with_facts(fact))
        expr = connector._fact_expr(fact, self.world, self.seats)
        solver = Solver()
        solver.add(expr, self.world.nomination_happened[1][1])
        self.assertEqual(solver.check(), sat)
