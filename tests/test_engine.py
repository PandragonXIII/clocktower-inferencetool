import unittest

from z3 import Bool, PbEq, Not, Or

from engine import CheckStatus, QueryStatus, ReasoningEngine


class ReasoningEngineTests(unittest.TestCase):
    def test_tracker_name_does_not_collide_with_user_variable(self):
        variable = Bool("__constraint_example")
        engine = ReasoningEngine()
        engine.add_constraint(Not(variable), label="example")
        self.assertEqual(engine.check().status, CheckStatus.SAT)

    def test_automatic_label_skips_previously_used_label(self):
        engine = ReasoningEngine()
        engine.add_constraint(Bool("first"), label="constraint_1")
        self.assertEqual(engine.add_constraint(Bool("second")), "constraint_2")

    def test_timeout_must_be_positive_integer(self):
        for timeout in (0, -1, 1.5, True):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                ReasoningEngine(timeout_ms=timeout)

    def test_exactly_one_demon_and_identity_queries(self):
        players = [Bool(f"demon_{i}") for i in range(3)]
        engine = ReasoningEngine()
        engine.add_constraint(PbEq([(player, 1) for player in players], 1), "one_demon")

        self.assertEqual(engine.query(Or(*players)).status, QueryStatus.NECESSARY)
        self.assertEqual(engine.query(players[0]).status, QueryStatus.POSSIBLE)
        impossible = ReasoningEngine()
        impossible.add_constraint(~players[0], "not_player_0")
        self.assertEqual(impossible.query(players[0]).status, QueryStatus.IMPOSSIBLE)

    def test_conflicting_labels_and_temporary_assumption_do_not_leak(self):
        demon = Bool("demon")
        engine = ReasoningEngine()
        engine.add_constraint(demon, "claimed_demon")
        engine.add_constraint(~demon, "known_not_demon")
        result = engine.check()
        self.assertEqual(result.status, CheckStatus.UNSAT)
        self.assertEqual(set(result.conflict_labels), {"claimed_demon", "known_not_demon"})

        temporary = ReasoningEngine()
        temporary.add_constraint(Or(demon, ~demon), "tautology")
        self.assertEqual(temporary.check([demon]).status, CheckStatus.SAT)
        self.assertEqual(temporary.query(~demon).status, QueryStatus.POSSIBLE)

    def test_base_contradiction_is_inconsistent(self):
        value = Bool("value")
        engine = ReasoningEngine()
        engine.add_constraint(value, "positive")
        engine.add_constraint(Not(value), "negative")
        result = engine.query(value)
        self.assertEqual(result.status, QueryStatus.INCONSISTENT)
        self.assertEqual(set(result.conflict_labels), {"positive", "negative"})


if __name__ == "__main__":
    unittest.main()
