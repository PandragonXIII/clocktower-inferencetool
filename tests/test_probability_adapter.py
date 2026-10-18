"""Tests for ``botc_reasoner.probability_adapter`` and the connector switch.

The adapter is exercised directly with fake ``world`` / ``collector`` objects
and real Z3 expressions, while ``estimate_role_probabilities`` is mocked so no
sampling runs. The connector path is tested by mocking ``connector.analyze``
and ``connector._prepare_context`` so only the option gate is exercised.

Covered:

- Public inputs are hard constraints in every group solver; conditional inputs
  are soft and grouped by ``owner_id`` (or by their own id when unowned).
- Conditional groups are enumerated with credibility 0.7 and normalized by
  ``0.7 ** trusted * 0.3 ** ignored``; all-trusted and empty masks are included.
- Contradictory role / alignment / global conditional expressions stay soft:
  the conflicting combination is dropped, the remaining groups still produce
  ``estimated`` rows, and the background is not reported ``inconsistent``.
- A contradictory *public* background is reported as ``inconsistent`` and the
  estimator is never called.
- ``estimate`` returning ``None`` or raising ``ProbabilityIncomplete`` keeps the
  result ``unknown`` (never "impossible").
- ``rows`` echo each player's ``player_id`` / ``seat`` and the role id strings.
- ``probability_mode:false`` never imports/calls the adapter.
- ``probability_mode`` is a validated boolean and ``probability_timeout_ms`` is
  validated as an integer in ``1..300000`` with a connector default of 120000.
"""

import copy
import unittest
from unittest import mock

from z3 import Bool, BoolVal, Not

from backend.validation import validate_request
from backend.errors import ApiError
from botc_reasoner import Role, analysis
from botc_reasoner.analysis import Budget
from botc_reasoner.probability import ProbabilityIncomplete
from botc_reasoner.variables import Ability
from test_extension_validation import base_request


class _FakeWorld:
    def __init__(self, axioms=()):
        self._axioms = list(axioms)

    def encoding_axioms(self):
        return list(self._axioms)


class _FakeCollector:
    def __init__(self):
        self.records = []


def _players(count=5):
    return [{"id": f"p{i}", "seat": i, "name": f"Player {i}"} for i in range(1, count + 1)]


def _request(*, observation=True):
    facts = []
    if observation:
        facts.append(
            {
                "id": "f-chef",
                "type": "botc:ability_observation",
                "status": "confirmed",
                "enabled": True,
                "data": {
                    "actor_id": "p1",
                    "role_id": "chef",
                    "time": {"phase": "night", "number": 1},
                    "targets": [],
                    "result": {"kind": "number", "value": 1},
                },
            }
        )
    return {
        "api_version": "1.0",
        "request_id": "req-1",
        "game": {"id": "g1", "revision": 1, "script_id": "trouble_brewing",
                 "players": _players()},
        "facts": facts,
        "assumptions": [],
        "queries": [],
    }


def _context(*, inputs, axioms=(BoolVal(True),)):
    world = _FakeWorld(axioms)
    collector = _FakeCollector()
    seats = {player["id"]: player["seat"] - 1 for player in _players()}
    return world, collector, inputs, seats


def _input(input_id, expr, *, scope="conditional", owner_id=None):
    return analysis.InputConstraint(
        id=input_id, expr=expr, scope=scope, owner_id=owner_id
    )


_INPUT = _input("f-chef", Bool("f_chef"))


class AdapterEstimateTests(unittest.TestCase):
    def _call(self, request, inputs, estimate):
        world, collector, inputs, seats = _context(inputs=inputs)
        budget = Budget(total_ms=1000, per_solve_ms=1000)
        snapshots = []

        def snapshot(*args, **kwargs):
            # The adapter reuses one solver and pops each group's assumptions
            # after the call, so capture the assertions at call time.
            snapshots.append([str(expr) for expr in kwargs["solver"].assertions()])
            return estimate(*args, **kwargs)

        with mock.patch(
            "botc_reasoner.probability_adapter.estimate_role_probabilities",
            side_effect=snapshot,
        ) as mocked:
            result = self._analyze(request, world, collector, inputs, seats, budget)
        mocked.snapshots = snapshots
        return result, mocked

    @staticmethod
    def _analyze(request, world, collector, inputs, seats, budget):
        from botc_reasoner.probability_adapter import analyze_probabilities

        return analyze_probabilities(request, world, collector, inputs, seats, budget)

    def test_public_is_hard_and_conditional_is_a_soft_owner_group(self):
        request = _request()
        before = copy.deepcopy(request)
        probabilities = [{Role.CHEF: 1.0} for _ in range(5)]
        inputs = [_input("f-public", Bool("f_public"), scope="public"), _INPUT]

        result, mocked = self._call(request, inputs, lambda *a, **k: probabilities)

        self.assertEqual(mocked.call_count, 2)
        calls = mocked.call_args_list
        trust_flags = ["f_chef" in assertions for assertions in mocked.snapshots]
        self.assertEqual(sorted(trust_flags), [False, True])
        for assertions in mocked.snapshots:
            self.assertIn("f_public", assertions)
        trusted = next(call for call, flag in zip(calls, trust_flags) if flag)
        observations = trusted.kwargs["trusted_abilities"]
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].actor, 0)
        self.assertEqual(observations[0].ability, Ability.CHEF)
        self.assertEqual(observations[0].when, 1)
        self.assertEqual(request, before)
        self.assertEqual(result["status"], "estimated")
        self.assertEqual(result["input_ids"], ["f-public", "f-chef"])
        self.assertEqual(result["hard_input_ids"], ["f-public"])
        self.assertEqual(result["soft_input_ids"], ["f-chef"])
        self.assertEqual(result["conditioning"], "public_with_soft_conditional_inputs")
        self.assertEqual(result["credibility"], 0.7)
        self.assertFalse(result["complete"])
        self.assertEqual(
            result["groups"], {"total": 2, "checked": 2, "estimated": 2, "complete": True}
        )

    def test_trusted_and_ignored_groups_are_weighted_then_normalized(self):
        def estimate(*_args, **kwargs):
            if "soft_flag" in [str(expr) for expr in kwargs["solver"].assertions()]:
                return [{Role.EMPATH: 1.0} for _ in range(5)]
            return [{Role.CHEF: 1.0} for _ in range(5)]

        result, mocked = self._call(
            _request(observation=False),
            [_input("soft", Bool("soft_flag"))],
            estimate,
        )

        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(result["status"], "estimated")
        self.assertAlmostEqual(
            result["rows"][0]["probabilities"]["chef"], 0.3, places=6
        )
        self.assertAlmostEqual(
            result["rows"][0]["probabilities"]["empath"], 0.7, places=6
        )
        self.assertAlmostEqual(sum(result["rows"][0]["probabilities"].values()), 1.0)

    def test_conflicting_conditional_inputs_in_one_owner_group_are_soft(self):
        claim = Bool("claim_a")
        inputs = [
            _input("role-claim", claim, owner_id="p1"),
            _input("alignment-claim", Not(claim), owner_id="p1"),
        ]

        result, mocked = self._call(
            _request(observation=False),
            inputs,
            lambda *a, **k: [{Role.CHEF: 1.0} for _ in range(5)],
        )

        self.assertEqual(mocked.call_count, 1)
        self.assertNotIn("claim_a", mocked.snapshots[0])
        self.assertEqual(result["status"], "estimated")
        self.assertEqual(
            result["groups"], {"total": 2, "checked": 2, "estimated": 1, "complete": True}
        )

    def test_conflicting_role_and_alignment_across_owners_still_estimate(self):
        claim = Bool("claim_a")
        inputs = [
            _input("role-p1", claim, owner_id="p1"),
            _input("alignment-p2", Not(claim), owner_id="p2"),
        ]
        results = {
            (): Role.CHEF,
            ("claim_a",): Role.EMPATH,
            ("Not(claim_a)",): Role.SOLDIER,
        }

        def estimate(*_args, **kwargs):
            markers = tuple(
                str(expr) for expr in kwargs["solver"].assertions() if str(expr) != "True"
            )
            role = results[markers]
            return [{role: 1.0} for _ in range(5)]

        result, _mocked = self._call(_request(observation=False), inputs, estimate)

        self.assertEqual(result["status"], "estimated")
        self.assertEqual(
            result["groups"], {"total": 4, "checked": 4, "estimated": 3, "complete": True}
        )
        probabilities = result["rows"][1]["probabilities"]
        self.assertAlmostEqual(probabilities["chef"], 0.09 / 0.51)
        self.assertAlmostEqual(probabilities["empath"], 0.21 / 0.51)
        self.assertAlmostEqual(probabilities["soldier"], 0.21 / 0.51)
        self.assertAlmostEqual(sum(probabilities.values()), 1.0)

    def test_impossible_global_conditional_does_not_make_result_inconsistent(self):
        result, mocked = self._call(
            _request(observation=False),
            [_input("global-false", BoolVal(False))],
            lambda *a, **k: [{Role.CHEF: 1.0} for _ in range(5)],
        )

        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(result["status"], "estimated")
        self.assertEqual(result["soft_input_ids"], ["global-false"])
        self.assertEqual(
            result["groups"], {"total": 2, "checked": 2, "estimated": 1, "complete": True}
        )
        self.assertAlmostEqual(result["rows"][0]["probabilities"]["chef"], 1.0)

    def test_none_estimate_stays_unknown(self):
        result, mocked = self._call(_request(), [_INPUT], lambda *a, **k: None)
        mocked.assert_called_once()
        self.assertEqual(result["status"], "unknown")
        self.assertIn("reason", result)
        self.assertEqual(result["rows"], [])

    def test_incomplete_estimate_stays_unknown(self):
        def raise_incomplete(*a, **k):
            raise ProbabilityIncomplete("预算耗尽")

        result, mocked = self._call(_request(), [_INPUT], raise_incomplete)
        mocked.assert_called_once()
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["reason"], "预算耗尽")
        self.assertEqual(result["rows"], [])

    def test_unsat_public_background_is_inconsistent_without_estimating(self):
        inputs = [_input("public-false", BoolVal(False), scope="public")]
        world, collector, inputs, seats = _context(inputs=inputs)
        budget = Budget(total_ms=1000, per_solve_ms=1000)
        with mock.patch(
            "botc_reasoner.probability_adapter.estimate_role_probabilities"
        ) as mocked:
            result = self._analyze(_request(), world, collector, inputs, seats, budget)
        mocked.assert_not_called()
        self.assertEqual(result["status"], "inconsistent")
        self.assertEqual(result["hard_input_ids"], ["public-false"])
        self.assertEqual(result["rows"], [])

    def test_rows_echo_player_seat_and_role_ids(self):
        probabilities = [{Role.CHEF: 0.25, Role.EMPATH: 0.75} for _ in range(5)]
        result, _mocked = self._call(_request(), [_INPUT], lambda *a, **k: probabilities)
        self.assertEqual(
            [row["player_id"] for row in result["rows"]],
            ["p1", "p2", "p3", "p4", "p5"],
        )
        self.assertEqual([row["seat"] for row in result["rows"]], [1, 2, 3, 4, 5])
        self.assertEqual(set(result["rows"][0]["probabilities"]), {"chef", "empath"})
        self.assertAlmostEqual(result["rows"][0]["probabilities"]["chef"], 0.25)
        self.assertAlmostEqual(result["rows"][0]["probabilities"]["empath"], 0.75)


class ConnectorSwitchTests(unittest.TestCase):
    def _reason(self, options, adapter_result="result"):
        import connector

        request = _request(observation=False)
        request["options"] = options
        with mock.patch.object(connector, "_prepare_context", return_value=(None, None, [], {})), \
                mock.patch.object(connector, "_projection", return_value=[]), \
                mock.patch.object(connector, "analyze", return_value={"extensions": {}}), \
                mock.patch(
                    "botc_reasoner.probability_adapter.analyze_probabilities",
                    return_value=adapter_result,
                ) as mocked:
            response = connector._reason(request)
        return response, mocked

    def test_disabled_mode_never_calls_adapter(self):
        response, mocked = self._reason({"probability_mode": False})
        mocked.assert_not_called()
        self.assertNotIn("reasoner:probabilities", response["extensions"])

    def test_missing_mode_never_calls_adapter(self):
        _response, mocked = self._reason({"timeout_ms": 1000})
        mocked.assert_not_called()

    def test_enabled_mode_calls_adapter_with_budget(self):
        response, mocked = self._reason(
            {"probability_mode": True, "probability_timeout_ms": 2500, "timeout_ms": 500}
        )
        mocked.assert_called_once()
        budget = mocked.call_args.args[-1]
        self.assertIsInstance(budget, Budget)
        self.assertEqual(budget.total_ms, 2500)
        self.assertEqual(budget.per_solve_ms, 500)
        self.assertEqual(response["extensions"]["reasoner:probabilities"], "result")

    def test_enabled_mode_default_budget_is_120000(self):
        _response, mocked = self._reason({"probability_mode": True, "timeout_ms": 500})
        mocked.assert_called_once()
        budget = mocked.call_args.args[-1]
        self.assertEqual(budget.total_ms, 120000)
        self.assertEqual(budget.per_solve_ms, 500)


class ProbabilityOptionValidationTests(unittest.TestCase):
    def _with_options(self, options):
        request = base_request()
        request["options"] = options
        return request

    def test_valid_options_accepted(self):
        request = self._with_options(
            {"probability_mode": True, "probability_timeout_ms": 300000}
        )
        self.assertIs(validate_request(request), request)

    def test_probability_mode_must_be_boolean(self):
        request = self._with_options({"probability_mode": 1})
        with self.assertRaises(ApiError) as ctx:
            validate_request(request)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "INVALID_REQUEST")
        self.assertEqual(ctx.exception.path, "/options/probability_mode")

    def test_probability_timeout_minimum(self):
        request = self._with_options({"probability_timeout_ms": 0})
        with self.assertRaises(ApiError) as ctx:
            validate_request(request)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.path, "/options/probability_timeout_ms")

    def test_probability_timeout_maximum(self):
        request = self._with_options({"probability_timeout_ms": 300001})
        with self.assertRaises(ApiError) as ctx:
            validate_request(request)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.path, "/options/probability_timeout_ms")

    def test_probability_timeout_rejects_bool(self):
        request = self._with_options({"probability_timeout_ms": True})
        with self.assertRaises(ApiError) as ctx:
            validate_request(request)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.path, "/options/probability_timeout_ms")


if __name__ == "__main__":
    unittest.main()
