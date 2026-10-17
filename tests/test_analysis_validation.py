"""Runtime validation for the analysis pipeline additions.

Covers two things the connector's analysis pipeline consumes from a
``POST /api/v1/reason`` request, both checked by ``backend.validation`` without
building any Z3 object:

- ``options``: the new bounded integer keys (``total_timeout_ms``,
  ``max_worlds``, ``max_repairs``, ``max_repair_checks``) alongside the existing
  positive ``timeout_ms``. Booleans are rejected for every integer option and
  unknown option keys are rejected.
- controlled ``reasoner:*`` metadata inside ``extensions``: ``reasoner:scope``
  (``public`` / ``conditional``), ``reasoner:source`` (fixed enum) and
  ``reasoner:owner_id`` (a valid player reference). ``reported`` facts and
  assumptions may never be ``public``. Unknown non-``reasoner:`` extension
  fields stay allowed, and the metadata is checked even for disabled records.
"""

import copy
import json
import unittest
from pathlib import Path

from backend.errors import ApiError
from backend.validation import validate_request

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "web" / "protocol" / "examples"


def load_example(name):
    with (EXAMPLES / f"{name}.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def base_request():
    """The protocol example request, deep-copied and locked to a fixed time."""
    request = copy.deepcopy(load_example("request"))
    request["game"]["time"] = {"phase": "day", "number": 2}
    return request


def with_facts(*facts):
    request = base_request()
    request["facts"] = list(facts)
    return request


def role_fact(fact_id="f-role", player_id="p1", status="confirmed", **extensions):
    fact = {
        "id": fact_id,
        "type": "role",
        "status": status,
        "enabled": True,
        "proposition": {
            "kind": "role",
            "player_id": player_id,
            "role_id": "empath",
            "time": {"phase": "setup"},
        },
    }
    if extensions:
        fact["extensions"] = extensions
    return fact


def assumption(assumption_id="a1", player_id="p1", **extensions):
    entry = {
        "id": assumption_id,
        "enabled": True,
        "proposition": {
            "kind": "role",
            "player_id": player_id,
            "role_id": "empath",
            "time": {"phase": "setup"},
        },
    }
    if extensions:
        entry["extensions"] = extensions
    return entry


def assert_rejected(test, request, *, status=400, code=None, path=None):
    with test.assertRaises(ApiError) as ctx:
        validate_request(request)
    error = ctx.exception
    test.assertEqual(error.status, status)
    if code is not None:
        test.assertEqual(error.code, code)
    if path is not None:
        test.assertEqual(error.path, path)
    return error


class ProtocolExampleTests(unittest.TestCase):
    def test_protocol_example_request_is_valid(self):
        request = base_request()
        self.assertIs(validate_request(request), request)


class OptionBoundTests(unittest.TestCase):
    def _with_options(self, options):
        request = base_request()
        request["options"] = options
        return request

    def test_new_defaults_are_accepted(self):
        request = self._with_options(
            {
                "total_timeout_ms": 8000,
                "max_worlds": 0,
                "max_repairs": 0,
                "max_repair_checks": 128,
            }
        )
        self.assertIs(validate_request(request), request)

    def test_boundary_values_are_accepted(self):
        cases = {
            "total_timeout_ms": (1, 60000),
            "max_worlds": (0, 100),
            "max_repairs": (0, 10),
            "max_repair_checks": (1, 1024),
        }
        for key, (low, high) in cases.items():
            for value in (low, high):
                with self.subTest(key=key, value=value):
                    request = self._with_options({key: value})
                    self.assertIs(validate_request(request), request)

    def test_low_and_high_out_of_range_are_rejected(self):
        cases = {
            "total_timeout_ms": (0, 60001),
            "max_worlds": (-1, 101),
            "max_repairs": (-1, 11),
            "max_repair_checks": (0, 1025),
        }
        for key, (low, high) in cases.items():
            for value in (low, high):
                with self.subTest(key=key, value=value):
                    assert_rejected(
                        self, self._with_options({key: value}), path=f"/options/{key}"
                    )

    def test_timeout_ms_positive_unchanged(self):
        request = self._with_options({"timeout_ms": 1})
        self.assertIs(validate_request(request), request)
        assert_rejected(self, self._with_options({"timeout_ms": 0}), path="/options/timeout_ms")
        assert_rejected(self, self._with_options({"timeout_ms": -5}), path="/options/timeout_ms")

    def test_booleans_are_rejected_for_every_integer_option(self):
        keys = (
            "timeout_ms",
            "total_timeout_ms",
            "max_worlds",
            "max_repairs",
            "max_repair_checks",
        )
        for key in keys:
            with self.subTest(key=key):
                assert_rejected(
                    self, self._with_options({key: True}), path=f"/options/{key}"
                )

    def test_non_integer_values_are_rejected(self):
        assert_rejected(
            self, self._with_options({"max_worlds": 1.5}), path="/options/max_worlds"
        )
        assert_rejected(
            self, self._with_options({"max_repairs": "3"}), path="/options/max_repairs"
        )

    def test_unknown_option_key_is_rejected(self):
        assert_rejected(
            self, self._with_options({"max_bogus": 1}), path="/options/max_bogus"
        )


class FactReasonerScopeTests(unittest.TestCase):
    def test_confirmed_fact_public_scope_is_accepted(self):
        request = with_facts(role_fact(**{"reasoner:scope": "public"}))
        self.assertIs(validate_request(request), request)

    def test_conditional_scope_is_accepted(self):
        request = with_facts(role_fact(**{"reasoner:scope": "conditional"}))
        self.assertIs(validate_request(request), request)

    def test_confirmed_role_defaults_without_scope_are_valid(self):
        request = with_facts(role_fact())
        self.assertIs(validate_request(request), request)

    def test_unknown_scope_value_is_rejected(self):
        request = with_facts(role_fact(**{"reasoner:scope": "private"}))
        assert_rejected(
            self, request, path="/facts/0/extensions/reasoner:scope"
        )

    def test_reported_fact_public_scope_is_rejected(self):
        request = with_facts(
            role_fact(status="reported", **{"reasoner:scope": "public"})
        )
        assert_rejected(
            self, request, path="/facts/0/extensions/reasoner:scope"
        )

    def test_reported_fact_conditional_scope_is_accepted(self):
        request = with_facts(
            role_fact(status="reported", **{"reasoner:scope": "conditional"})
        )
        self.assertIs(validate_request(request), request)


class AssumptionReasonerScopeTests(unittest.TestCase):
    def test_assumption_public_scope_is_rejected(self):
        request = base_request()
        request["assumptions"] = [
            assumption(**{"reasoner:scope": "public"})
        ]
        assert_rejected(
            self, request, path="/assumptions/0/extensions/reasoner:scope"
        )

    def test_assumption_conditional_scope_is_accepted(self):
        request = base_request()
        request["assumptions"] = [
            assumption(**{"reasoner:scope": "conditional"})
        ]
        self.assertIs(validate_request(request), request)


class ReasonerSourceTests(unittest.TestCase):
    def test_all_allowed_sources_are_accepted(self):
        for source in (
            "received",
            "self_claim",
            "assumption",
            "public_announcement",
            "observation",
        ):
            with self.subTest(source=source):
                request = with_facts(role_fact(**{"reasoner:source": source}))
                self.assertIs(validate_request(request), request)

    def test_unknown_source_is_rejected(self):
        request = with_facts(role_fact(**{"reasoner:source": "gossip"}))
        assert_rejected(
            self, request, path="/facts/0/extensions/reasoner:source"
        )

    def test_empty_source_is_rejected(self):
        request = with_facts(role_fact(**{"reasoner:source": ""}))
        assert_rejected(
            self, request, path="/facts/0/extensions/reasoner:source"
        )


class ReasonerOwnerTests(unittest.TestCase):
    def test_valid_player_owner_is_accepted(self):
        request = with_facts(role_fact(**{"reasoner:owner_id": "p3"}))
        self.assertIs(validate_request(request), request)

    def test_unknown_player_owner_is_rejected(self):
        request = with_facts(role_fact(**{"reasoner:owner_id": "p9"}))
        assert_rejected(
            self, request, code="INVALID_REFERENCE",
            path="/facts/0/extensions/reasoner:owner_id",
        )

    def test_empty_owner_is_rejected(self):
        request = with_facts(role_fact(**{"reasoner:owner_id": ""}))
        assert_rejected(
            self, request, path="/facts/0/extensions/reasoner:owner_id"
        )


class DisabledAndUnknownFieldTests(unittest.TestCase):
    def test_disabled_fact_still_validates_metadata(self):
        fact = role_fact(**{"reasoner:owner_id": "p9"})
        fact["enabled"] = False
        assert_rejected(
            self, with_facts(fact), code="INVALID_REFERENCE",
            path="/facts/0/extensions/reasoner:owner_id",
        )

    def test_disabled_assumption_still_validates_metadata(self):
        entry = assumption(**{"reasoner:scope": "public"})
        entry["enabled"] = False
        request = base_request()
        request["assumptions"] = [entry]
        assert_rejected(
            self, request, path="/assumptions/0/extensions/reasoner:scope"
        )

    def test_unknown_non_reasoner_extension_field_stays_allowed(self):
        request = with_facts(
            role_fact(**{"ui:source": "public_claim", "acme:note": "x"})
        )
        self.assertIs(validate_request(request), request)

    def test_unknown_reasoner_key_is_not_constrained(self):
        request = with_facts(role_fact(**{"reasoner:experimental": "anything"}))
        self.assertIs(validate_request(request), request)


if __name__ == "__main__":
    unittest.main()
