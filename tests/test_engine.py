import random
import unittest

from botc_reasoner.engine import NightChoices, Table
from botc_reasoner.roles import Role
from botc_reasoner.winrate import GameInput, _good_target


def _table(roles, *, alive=None, herring=None):
    return Table(
        roles=list(roles),
        alive=list(alive or [True] * len(roles)),
        drunk_mask=None,
        red_herring=herring,
        bluffs=(),
        rng=random.Random(0),
        fixed_registration=True,
    )


class EngineTests(unittest.TestCase):
    def test_imp_kills_and_monk_or_soldier_stops_it(self):
        roles = [Role.IMP, Role.MONK, Role.SOLDIER, Role.CHEF, Role.POISONER]
        table = _table(roles)
        table.night = 2
        table.resolve_night(NightChoices(imp=3, monk=3))
        self.assertTrue(table.alive[3])
        self.assertEqual(table.day, 2)

        table = _table(roles)
        table.night = 2
        table.resolve_night(NightChoices(imp=2))
        self.assertTrue(table.alive[2])

        table = _table(roles)
        table.night = 2
        table.resolve_night(NightChoices(imp=3))
        self.assertFalse(table.alive[3])

    def test_starpass_replaces_the_imp(self):
        table = _table([Role.IMP, Role.POISONER, Role.CHEF, Role.EMPATH, Role.MAYOR])
        table.night = 2
        table.resolve_night(NightChoices(imp=0))
        self.assertFalse(table.alive[0])
        self.assertEqual(table.roles[1], Role.IMP)
        self.assertIsNone(table.winner)

    def test_saint_execution_and_mayor_three_alive(self):
        table = _table([Role.IMP, Role.SAINT, Role.CHEF, Role.EMPATH, Role.POISONER])
        table.night = 1
        table.resolve_night(NightChoices())
        table.resolve_day([(0, 1)], {1: {0: True, 2: True, 3: True}})
        self.assertEqual(table.winner, "evil")

        table = _table(
            [Role.IMP, Role.MAYOR, Role.CHEF],
            alive=[True, True, True],
        )
        table.phase = "day"
        table.day = 2
        table.night = 2
        table.resolve_day([], {})
        self.assertEqual(table.winner, "good")

    def test_virgin_executes_the_townsfolk_nominator(self):
        table = _table([Role.CHEF, Role.VIRGIN, Role.IMP, Role.POISONER, Role.EMPATH])
        table.phase = "day"
        table.day = 1
        table.night = 1
        table.resolve_day([(0, 1)], {})
        self.assertFalse(table.alive[0])
        self.assertTrue(table.alive[1])

    def test_nomination_prefers_a_modal_demon(self):
        probs = [
            {Role.IMP: 0.2, Role.CHEF: 0.8},
            {Role.POISONER: 0.7, Role.CHEF: 0.3},
            {Role.IMP: 0.55, Role.EMPATH: 0.45},
        ]
        table = _table([Role.CHEF, Role.POISONER, Role.IMP])
        self.assertEqual(_good_target(probs, table, 0.5), 2)


if __name__ == "__main__":
    unittest.main()
