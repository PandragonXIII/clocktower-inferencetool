"""Tests for extension fact validation via ``validate_request``.

Covers the three enabled extension fact types the connector understands
(``botc:ability_observation``, ``botc:night_deaths``, ``botc:day_vote``),
their common rejection cases, and the runtime HTTP path: a real
``ThreadingHTTPServer`` with a recording adapter verifies that valid extension
facts reach the adapter (HTTP 200) while an unsupported observation is rejected
before the adapter is ever called (HTTP 422).

The tests exercise validation and protocol plumbing only. No Z3 objects are
built and no model is solved; the ``capabilities`` check inspects the shape of
the connector's advertised ``scripts`` list without calling ``reason``.
"""

import copy
import http.client
import json
import threading
import unittest
from pathlib import Path
from unittest import mock

from backend.errors import ApiError
from backend.http_server import create_server
from backend.validation import validate_request

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "web" / "protocol" / "examples"

_JSON = {"Content-Type": "application/json"}


def load_example(name):
    with (EXAMPLES / f"{name}.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def base_request():
    """A deep copy of the example request, with ``game.time`` set to day 2."""
    request = copy.deepcopy(load_example("request"))
    request["game"]["time"] = {"phase": "day", "number": 2}
    return request


def with_facts(*facts):
    request = base_request()
    request["facts"] = list(facts)
    return request


def chef_fact(fact_id="f-chef", value=1, **overrides):
    data = {
        "time": {"phase": "night", "number": 1},
        "actor_id": "p1",
        "role_id": "chef",
        "targets": [],
        "result": {"kind": "number", "value": value},
    }
    data.update(overrides.pop("data", {}))
    fact = {
        "id": fact_id,
        "type": "botc:ability_observation",
        "status": "confirmed",
        "enabled": True,
        "data": data,
    }
    fact.update(overrides)
    return fact


def night_deaths_fact(fact_id="f-deaths", **overrides):
    data = {
        "time": {"phase": "night", "number": 2},
        "player_ids": [],
        "result": "none",
    }
    data.update(overrides.pop("data", {}))
    fact = {
        "id": fact_id,
        "type": "botc:night_deaths",
        "status": "confirmed",
        "enabled": True,
        "data": data,
    }
    fact.update(overrides)
    return fact


def observation_fact(fact_id, role_id, targets, result, *, time, **overrides):
    data = {
        "time": time,
        "actor_id": "p1",
        "role_id": role_id,
        "targets": list(targets),
        "result": result,
    }
    data.update(overrides.pop("data", {}))
    fact = {
        "id": fact_id,
        "type": "botc:ability_observation",
        "status": "confirmed",
        "enabled": True,
        "data": data,
    }
    fact.update(overrides)
    return fact


def day_vote_fact(fact_id="f-vote", **overrides):
    data = {
        "time": {"phase": "day", "number": 1},
        "stage": "settled",
        "execution": {"player_id": "p1"},
        "nominations": [
            {
                "id": "n1",
                "nominator_id": "p2",
                "nominee_id": "p1",
                "voter_ids": ["p2", "p3"],
                "count": 2,
            }
        ],
    }
    data.update(overrides.pop("data", {}))
    fact = {
        "id": fact_id,
        "type": "botc:day_vote",
        "status": "confirmed",
        "enabled": True,
        "data": data,
    }
    fact.update(overrides)
    return fact


class ValidExtensionFactTests(unittest.TestCase):
    def test_chef_number_first_night(self):
        request = with_facts(chef_fact())
        self.assertIs(validate_request(request), request)

    def test_night_deaths_none_second_night(self):
        request = with_facts(night_deaths_fact())
        self.assertIs(validate_request(request), request)

    def test_day_vote_settled_execution_with_nominations(self):
        request = with_facts(day_vote_fact())
        self.assertIs(validate_request(request), request)

    def test_all_three_together(self):
        request = with_facts(chef_fact(), night_deaths_fact(), day_vote_fact())
        self.assertIs(validate_request(request), request)


class RejectedExtensionFactTests(unittest.TestCase):
    def _assert_rejected(self, request, *, status=400, code=None, path=None):
        with self.assertRaises(ApiError) as ctx:
            validate_request(request)
        error = ctx.exception
        self.assertEqual(error.status, status)
        if code is not None:
            self.assertEqual(error.code, code)
        if path is not None:
            self.assertEqual(error.path, path)
        return error

    def test_wrong_player_reference(self):
        request = with_facts(
            night_deaths_fact(data={"player_ids": ["p9"], "result": "deaths"})
        )
        self._assert_rejected(request, code="INVALID_REFERENCE")

    def test_future_time(self):
        request = with_facts(
            night_deaths_fact(data={"time": {"phase": "night", "number": 3}})
        )
        self._assert_rejected(request, path="/facts/0/data/time")

    def test_time_number_is_bool(self):
        request = with_facts(
            night_deaths_fact(data={"time": {"phase": "night", "number": True}})
        )
        self._assert_rejected(request, path="/facts/0/data/time/number")

    def test_chef_value_out_of_range(self):
        request = with_facts(chef_fact(value=99))
        self._assert_rejected(request, path="/facts/0/data/result/value")

    def test_invalid_night_deaths_result(self):
        request = with_facts(night_deaths_fact(data={"result": "maybe"}))
        self._assert_rejected(request, path="/facts/0/data/result")

    def test_unsupported_spy_observation_is_422(self):
        request = with_facts(
            chef_fact(
                data={
                    "actor_id": "p1",
                    "role_id": "spy",
                    "targets": [],
                    "result": {"kind": "no_direct_result"},
                }
            )
        )
        self._assert_rejected(request, status=422, code="UNSUPPORTED_OBSERVATION")

    def test_unknown_result_role_is_rejected(self):
        request = with_facts(
            observation_fact(
                "f-unknown-role",
                "washerwoman",
                ["p2", "p3"],
                {"kind": "role", "role_id": "not_a_role"},
                time=NIGHT_1,
            )
        )
        self._assert_rejected(request, code="INVALID_REFERENCE")

    def test_duplicate_targets_are_rejected(self):
        request = with_facts(
            observation_fact(
                "f-dup-targets",
                "monk",
                ["p2", "p2"],
                {"kind": "no_direct_result"},
                time=NIGHT_2,
            )
        )
        self._assert_rejected(request, code="INVALID_REQUEST", path="/facts/0/data/targets/1")

    def test_night_deaths_none_with_players_is_rejected(self):
        request = with_facts(
            night_deaths_fact(
                data={"result": "none", "player_ids": ["p2"]}
            )
        )
        self._assert_rejected(request, code="INVALID_REQUEST", path="/facts/0/data/player_ids")

    def test_nomination_unknown_voter_is_rejected(self):
        request = with_facts(
            day_vote_fact(
                data={
                    "nominations": [
                        {
                            "id": "n1",
                            "nominator_id": "p2",
                            "nominee_id": "p1",
                            "voter_ids": ["p2", "p9"],
                        }
                    ]
                }
            )
        )
        self._assert_rejected(
            request,
            code="INVALID_REFERENCE",
            path="/facts/0/data/nominations/0/voter_ids/1",
        )

    def test_unsettled_voting_is_unsupported(self):
        request = with_facts(day_vote_fact(data={"stage": "voting"}))
        self._assert_rejected(request, status=422, code="UNSUPPORTED_OBSERVATION")

    def test_disabled_fact_with_null_data_is_accepted(self):
        request = with_facts(
            {
                "id": "f-disabled-null",
                "type": "botc:ability_observation",
                "status": "confirmed",
                "enabled": False,
                "data": None,
            }
        )
        self.assertIs(validate_request(request), request)

    def test_disabled_fact_with_arbitrary_data_is_accepted(self):
        request = with_facts(
            {
                "id": "f-disabled",
                "type": "botc:ability_observation",
                "status": "confirmed",
                "enabled": False,
                "data": {"garbage": [1, 2, 3], "time": {"phase": "night", "number": 9}},
            }
        )
        self.assertIs(validate_request(request), request)

    def test_unknown_enabled_extension_is_rejected(self):
        request = with_facts(
            {
                "id": "f-unknown",
                "type": "botc:not_real",
                "status": "confirmed",
                "enabled": True,
                "data": {},
            }
        )
        self._assert_rejected(request, code="UNKNOWN_TYPE", path="/facts/0/type")


NIGHT_1 = {"phase": "night", "number": 1}
NIGHT_2 = {"phase": "night", "number": 2}
DAY_2 = {"phase": "day", "number": 2}

# One representative payload per record shape advertised by ``web/skills.js``.
# The 13 cases cover every role id the connector can actually solve, using the
# real target counts, result kinds and category restrictions that the UI emits.
SUPPORTED_SKILL_SHAPES = (
    ("undertaker", "undertaker", NIGHT_2, ["p2"], {"kind": "role", "role_id": "chef"}),
    ("librarian-no-outsiders", "librarian", NIGHT_1, [], {"kind": "no_outsiders"}),
    (
        "librarian-role",
        "librarian",
        NIGHT_1,
        ["p2", "p3"],
        {"kind": "role", "role_id": "butler"},
    ),
    (
        "washerwoman",
        "washerwoman",
        NIGHT_1,
        ["p2", "p3"],
        {"kind": "role", "role_id": "soldier"},
    ),
    (
        "investigator",
        "investigator",
        NIGHT_1,
        ["p2", "p3"],
        {"kind": "role", "role_id": "poisoner"},
    ),
    ("empath", "empath", NIGHT_2, [], {"kind": "number", "value": 2}),
    ("fortune-teller", "fortune_teller", NIGHT_2, ["p2", "p3"], {"kind": "choice", "value": "yes"}),
    ("monk", "monk", NIGHT_2, ["p2"], {"kind": "no_direct_result"}),
    ("poisoner", "poisoner", NIGHT_2, ["p2"], {"kind": "no_direct_result"}),
    ("imp", "imp", NIGHT_2, ["p2"], {"kind": "choice", "value": "died"}),
    ("slayer", "slayer", DAY_2, ["p2"], {"kind": "choice", "value": "died"}),
    ("butler", "butler", NIGHT_2, ["p2"], {"kind": "no_direct_result"}),
    (
        "ravenkeeper",
        "ravenkeeper",
        NIGHT_2,
        ["p2"],
        {"kind": "role", "role_id": "soldier"},
    ),
)


class SupportedSkillShapeTests(unittest.TestCase):
    """Every supported role accepts the payload ``web/skills.js`` actually emits."""

    def test_supported_skill_shapes(self):
        for name, role_id, time, targets, result in SUPPORTED_SKILL_SHAPES:
            with self.subTest(role=name):
                request = with_facts(
                    observation_fact(
                        f"f-{name}", role_id, targets, result, time=time
                    )
                )
                self.assertIs(validate_request(request), request)


class RoleCatalogConsistencyTests(unittest.TestCase):
    """The extension whitelist must match ``botc_reasoner.roles`` exactly."""

    def test_role_categories_match_reasoner(self):
        from botc_reasoner import roles as reasoner

        from backend import extension_validation as ev

        def names(items):
            return {role.value for role in items}

        self.assertEqual(ev.TOWNSFOLK, names(reasoner.TOWNSFOLK))
        self.assertEqual(ev.OUTSIDERS, names(reasoner.OUTSIDERS))
        self.assertEqual(ev.MINIONS, names(reasoner.MINIONS))
        self.assertEqual(ev.ROLES, names(reasoner.Role))


class _RecordingUnknownAdapter:
    """Adapter that records every request and always reports ``unknown``."""

    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()

    def capabilities(self):
        return {
            "api_version": "1.0",
            "supported_fact_types": [],
            "query_types": [],
            "scripts": [],
            "extensions": {"adapter:mode": "recording"},
        }

    def reason(self, request):
        with self._lock:
            self.calls.append(copy.deepcopy(request))
        return {
            "api_version": "1.0",
            "request_id": request.get("request_id"),
            "game_id": (request.get("game") or {}).get("id"),
            "revision": (request.get("game") or {}).get("revision"),
            "consistency": "unknown",
            "reason": "recording adapter",
            "results": [
                {"id": q.get("id"), "status": "unknown"}
                for q in request.get("queries") or []
                if isinstance(q, dict)
            ],
        }


def _request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        payload = resp.read()
        return resp.status, payload
    finally:
        conn.close()


class ExtensionHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = _RecordingUnknownAdapter()
        cls.server = create_server("127.0.0.1", 0, adapter=cls.adapter)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=10)

    def _post(self, value):
        body = json.dumps(value).encode("utf-8")
        return _request(self.port, "POST", "/api/v1/reason", body=body, headers=_JSON)

    def test_valid_extension_facts_reach_adapter(self):
        request = with_facts(chef_fact(), night_deaths_fact(), day_vote_fact())
        before = len(self.adapter.calls)
        status, payload = self._post(request)
        self.assertEqual(status, 200)
        self.assertEqual(len(self.adapter.calls), before + 1)
        delivered = self.adapter.calls[-1]
        self.assertEqual(
            [fact["type"] for fact in delivered["facts"]],
            ["botc:ability_observation", "botc:night_deaths", "botc:day_vote"],
        )
        self.assertEqual(delivered, request)
        self.assertEqual(json.loads(payload.decode("utf-8"))["consistency"], "unknown")

    def test_unsupported_observation_is_422_and_skips_adapter(self):
        request = with_facts(
            chef_fact(
                data={
                    "actor_id": "p1",
                    "role_id": "spy",
                    "targets": [],
                    "result": {"kind": "no_direct_result"},
                }
            )
        )
        before = len(self.adapter.calls)
        status, payload = self._post(request)
        self.assertEqual(status, 422)
        self.assertEqual(len(self.adapter.calls), before)
        body = json.loads(payload.decode("utf-8"))
        self.assertEqual(body["error"]["code"], "UNSUPPORTED_OBSERVATION")


class RealAdapterHttpTests(unittest.TestCase):
    """End-to-end POST through the real connector adapter over HTTP.

    The request is a legal 5-player game whose only extension fact is an
    empty night-1 death record, which adds a constraint the solver already
    satisfies. ``connector._possible_roles`` (the candidate-enumeration loop) is
    mocked to ``[]`` so the test only exercises the real ``_prepare`` + base
    solve and does not depend on solver timing; the adapter's ``reason`` itself
    is never mocked.
    """

    @classmethod
    def setUpClass(cls):
        from connector import TroubleBrewingAdapter

        cls.adapter = TroubleBrewingAdapter()
        cls.server = create_server("127.0.0.1", 0, adapter=cls.adapter)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=10)

    def _post(self, value):
        body = json.dumps(value).encode("utf-8")
        return _request(self.port, "POST", "/api/v1/reason", body=body, headers=_JSON)

    def test_legal_night1_none_reaches_adapter(self):
        import connector

        request = base_request()
        request["facts"] = [
            night_deaths_fact(
                data={
                    "time": {"phase": "night", "number": 1},
                    "player_ids": [],
                    "result": "none",
                }
            )
        ]
        request["assumptions"] = []
        request["queries"] = []
        request["options"] = {"timeout_ms": 50}
        with mock.patch.object(connector, "_possible_roles", return_value=[]):
            status, payload = self._post(request)
        self.assertEqual(status, 200)
        body = json.loads(payload.decode("utf-8"))
        self.assertEqual(body["extensions"]["adapter:mode"], "trouble_brewing")
        self.assertIn(body["consistency"], ("sat", "unknown"))


class ConnectorCapabilitiesShapeTests(unittest.TestCase):
    def test_capabilities_scripts_are_objects(self):
        from connector import TroubleBrewingAdapter

        capabilities = TroubleBrewingAdapter().capabilities()
        scripts = capabilities["scripts"]
        self.assertIsInstance(scripts, list)
        self.assertTrue(scripts)
        for script in scripts:
            self.assertIsInstance(script, dict)
            self.assertIsInstance(script.get("id"), str)
            self.assertIsInstance(script.get("name"), str)


if __name__ == "__main__":
    unittest.main()
