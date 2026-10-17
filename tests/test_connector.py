"""Tests for ``connector`` extension-fact gating.

These tests pin the switch semantics of ``connector._fact_expr``: a fact with
``enabled:false`` must be ignored *before* any type dispatch, so disabled
extension facts are neither parsed nor turned into propositions. Enabled
extension facts must still be dispatched and constrain the model.

The tests do not run the full reasoning pipeline (no ``add_game_rules`` and no
``solver.check()`` over the whole model). They build a 5-player world, collect
propositions directly, and check satisfiability with the variable domain axioms
only, which keeps them fast while still exercising the real Z3 expressions.
"""

import unittest
from unittest import mock

from z3 import sat, unsat

import connector
from botc_reasoner import declare_variables

NIGHT_DEATHS = "botc:night_deaths"
DAY_VOTE = "botc:day_vote"
OBSERVATION = "botc:ability_observation"

PLAYERS = [{"id": f"p{i}", "seat": i} for i in range(1, 6)]
SEATS = {player["id"]: player["seat"] - 1 for player in PLAYERS}


def game_request(facts):
    return {
        "game": {
            "id": "g1",
            "script_id": "trouble_brewing",
            "players": PLAYERS,
        },
        "facts": facts,
    }


def world():
    return declare_variables(5, n_nights=2, tag="connector_test")


_PROBE_WORLD = None


def probe_world():
    """Shared read-only world for proposition extraction (declaration is costly)."""

    global _PROBE_WORLD
    if _PROBE_WORLD is None:
        _PROBE_WORLD = world()
    return _PROBE_WORLD


def propositions(facts):
    return connector._propositions(game_request(facts), probe_world(), SEATS)


def night_deaths_fact(fid, enabled=True, player_ids=("p1",), result="deaths", number=2):
    return {
        "id": fid,
        "type": NIGHT_DEATHS,
        "status": "confirmed",
        "enabled": enabled,
        "data": {
            "time": {"phase": "night", "number": number},
            "player_ids": list(player_ids),
            "result": result,
        },
    }


def day_vote_fact(fid, enabled=True, chosen="p2"):
    return {
        "id": fid,
        "type": DAY_VOTE,
        "status": "confirmed",
        "enabled": enabled,
        "data": {
            "stage": "settled",
            "time": {"phase": "day", "number": 1},
            "execution": {"player_id": chosen},
        },
    }


def observation_fact(fid, enabled=True):
    return {
        "id": fid,
        "type": OBSERVATION,
        "status": "confirmed",
        "enabled": enabled,
        "data": {
            "actor_id": "p1",
            "role_id": "chef",
            "time": {"phase": "night", "number": 1},
            "targets": [],
            "result": {"kind": "number", "value": 1},
        },
    }


EXTENSION_BUILDERS = {
    NIGHT_DEATHS: night_deaths_fact,
    DAY_VOTE: day_vote_fact,
    OBSERVATION: observation_fact,
}


class DisabledExtensionTests(unittest.TestCase):
    """A disabled extension must be ignored without parsing its payload."""

    def test_disabled_extension_does_not_call_extension_expr(self):
        for name, builder in EXTENSION_BUILDERS.items():
            with self.subTest(extension=name):
                request = game_request([builder("f-off", enabled=False)])
                with mock.patch.object(
                    connector,
                    "_extension_expr",
                    side_effect=AssertionError("disabled extension was parsed"),
                ) as spy:
                    result = connector._propositions(request, probe_world(), SEATS)
                spy.assert_not_called()
                self.assertEqual(result, [])

    def test_disabled_extension_matches_absent_fact(self):
        for name, builder in EXTENSION_BUILDERS.items():
            with self.subTest(extension=name):
                with_fact = propositions([builder("f-off", enabled=False)])
                without_fact = propositions([])
                self.assertEqual(with_fact, without_fact)
                self.assertEqual(with_fact, [])

    def test_disabled_malformed_payload_does_not_raise(self):
        malformed = [
            night_deaths_fact("f-bad-death", enabled=False, player_ids=("ghost",)),
            day_vote_fact("f-bad-vote", enabled=False, chosen="ghost"),
            {
                "id": "f-bad-obs",
                "type": OBSERVATION,
                "status": "confirmed",
                "enabled": False,
                "data": {
                    "actor_id": "ghost",
                    "role_id": "not_a_role",
                    "time": {"phase": "night", "number": 1},
                    "targets": ["ghost"],
                    "result": {"kind": "number", "value": 1},
                },
            },
        ]
        for fact in malformed:
            with self.subTest(fact=fact["id"]):
                self.assertEqual(propositions([fact]), [])


class EnabledExtensionTests(unittest.TestCase):
    """An enabled extension must be dispatched and turn into a proposition."""

    def test_enabled_extension_calls_extension_expr_and_adds_proposition(self):
        for name, builder in EXTENSION_BUILDERS.items():
            with self.subTest(extension=name):
                fact = builder("f-on", enabled=True)
                with mock.patch.object(
                    connector, "_extension_expr", wraps=connector._extension_expr
                ) as spy:
                    result = connector._propositions(
                        game_request([fact]), probe_world(), SEATS
                    )
                spy.assert_called_once()
                self.assertEqual([label for _expr, label in result], ["f-on"])


class PrepareSwitchTests(unittest.TestCase):
    """Exact switch semantics through the real ``_prepare`` on a 5-player game."""

    def test_disabled_night_death_absent_from_labels(self):
        fact = night_deaths_fact("f-off", enabled=False, player_ids=("p1",))
        _world, _solver, props = connector._prepare(game_request([fact]))
        self.assertEqual([label for _expr, label in props], [])

    def test_enabled_night_death_present_in_labels(self):
        fact = night_deaths_fact("f-on", enabled=True, player_ids=("p1",))
        _world, _solver, props = connector._prepare(game_request([fact]))
        self.assertEqual([label for _expr, label in props], ["f-on"])

    def test_mixed_night_death_keeps_only_enabled(self):
        request = game_request(
            [
                night_deaths_fact("f-off", enabled=False, player_ids=("ghost",)),
                night_deaths_fact("f-on", enabled=True, player_ids=("p2",)),
            ]
        )
        _world, _solver, props = connector._prepare(request)
        self.assertEqual([label for _expr, label in props], ["f-on"])


class SwitchNotMirrorTests(unittest.TestCase):
    """Prove the disabled payload is a real contradiction that is switched off.

    The enabled fact asserts ``p1`` died on night 2; the disabled fact asserts
    nobody died that night. The two together are unsatisfiable under the domain
    axioms. The mixed request stays ``sat`` only because the disabled fact is
    skipped, not because its payload is trivial.
    """

    def test_enabled_death_with_disabled_contradiction_is_sat(self):
        request = game_request(
            [
                night_deaths_fact("f-on", enabled=True, player_ids=("p1",)),
                night_deaths_fact(
                    "f-off", enabled=False, player_ids=("p1",), result="none"
                ),
            ]
        )
        world_instance, _solver, props = connector._prepare(request)
        self.assertEqual([label for _expr, label in props], ["f-on"])
        solver = world_instance.build_solver()
        for expr, _label in props:
            solver.add(expr)
        self.assertEqual(solver.check(), sat)

    def test_disabled_payload_would_contradict_enabled(self):
        world_instance = probe_world()
        enabled = connector._night_deaths(
            world_instance, SEATS, {"time": {"phase": "night", "number": 2}, "player_ids": ["p1"]}
        )
        disabled_payload = connector._night_deaths(
            world_instance,
            SEATS,
            {
                "time": {"phase": "night", "number": 2},
                "player_ids": ["p1"],
                "result": "none",
            },
        )
        solver = world_instance.build_solver()
        solver.add(enabled, disabled_payload)
        self.assertEqual(solver.check(), unsat)


class CoreDisabledTests(unittest.TestCase):
    """The pre-existing ``enabled`` handling for core facts is retained."""

    def role_fact(self, enabled):
        return {
            "id": "f-role",
            "type": "role",
            "status": "confirmed",
            "enabled": enabled,
            "proposition": {
                "kind": "role",
                "player_id": "p1",
                "role_id": "chef",
                "time": {"phase": "setup"},
            },
        }

    def test_disabled_core_role_ignored(self):
        self.assertEqual(propositions([self.role_fact(False)]), [])

    def test_enabled_core_role_produces_proposition(self):
        result = propositions([self.role_fact(True)])
        self.assertEqual([label for _expr, label in result], ["f-role"])


class HorizonTests(unittest.TestCase):
    """Document current horizon behaviour; fixing it is out of scope.

    ``connector._horizon`` scans every fact's time even when the fact is
    disabled, so a disabled night-2 extension still enlarges the declared model
    (more nights = more variables). This test records that behaviour so a
    future change is a deliberate decision, not an accident.
    """

    def test_disabled_extension_time_still_extends_horizon(self):
        request = game_request([night_deaths_fact("f-off", enabled=False, number=2)])
        self.assertEqual(connector._horizon(request), 2)


if __name__ == "__main__":
    unittest.main()
