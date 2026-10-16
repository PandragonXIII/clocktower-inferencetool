"""Tests for the web backend: HTTP server, request validation and adapter.

The HTTP tests start one real ``ThreadingHTTPServer`` on an ephemeral port in
``setUpClass`` and shut it down in ``tearDownClass``. All requests go through a
real socket (``http.client``) so routing, body handling and error mapping are
exercised end to end. Adapter behaviour (sat / unsat / exception) is simulated
with ``mock.patch.object`` on the placeholder adapter, so a single server is
enough.
"""

import copy
import http.client
import json
import threading
import unittest
from collections import namedtuple
from pathlib import Path
from unittest import mock

from backend.adapter import PlaceholderAdapter, prepare_request
from backend.http_server import MAX_BODY_BYTES, create_server

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "web" / "protocol" / "examples"

Response = namedtuple("Response", "status content_type allow body")

_JSON = {"Content-Type": "application/json"}


def load_example(name):
    with (EXAMPLES / f"{name}.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        payload = resp.read()
        return Response(
            resp.status,
            resp.getheader("Content-Type"),
            resp.getheader("Allow"),
            payload,
        )
    finally:
        conn.close()


def post_json(port, value, headers=None):
    merged = dict(_JSON)
    merged.update(headers or {})
    body = json.dumps(value).encode("utf-8")
    return request(port, "POST", "/api/v1/reason", body=body, headers=merged)


def post_raw(port, raw_bytes, headers=None):
    merged = dict(_JSON)
    merged.update(headers or {})
    return request(port, "POST", "/api/v1/reason", body=raw_bytes, headers=merged)


def raw_request(port, method, path, headers):
    """Send a request without letting http.client add body framing headers.

    ``HTTPConnection.request`` adds ``Content-Length`` automatically, so the
    transport-level cases (missing / malformed length, Transfer-Encoding) build
    the request by hand with ``putrequest`` / ``putheader`` / ``endheaders``.
    """
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.putrequest(method, path)
        for key, value in headers:
            conn.putheader(key, value)
        conn.endheaders()
        resp = conn.getresponse()
        payload = resp.read()
        return Response(
            resp.status,
            resp.getheader("Content-Type"),
            resp.getheader("Allow"),
            payload,
        )
    finally:
        conn.close()


def json_body(response):
    return json.loads(response.body.decode("utf-8"))


class PreparedRequestTests(unittest.TestCase):
    def test_classification_into_buckets(self):
        source = {
            "request_id": "req-1",
            "api_version": "1.0",
            "game": {"id": "g1"},
            "facts": [
                {"id": "f1", "status": "confirmed", "enabled": True},
                {"id": "f2", "status": "reported", "enabled": True},
                {"id": "f3", "status": "confirmed", "enabled": False},
                {"id": "f4", "status": "reported", "enabled": False},
            ],
            "assumptions": [
                {"id": "a1", "enabled": True},
                {"id": "a2", "enabled": False},
            ],
            "queries": [{"id": "q1"}],
        }
        prepared = prepare_request(source)
        self.assertEqual([f["id"] for f in prepared.confirmed_facts], ["f1"])
        self.assertEqual([f["id"] for f in prepared.reported_facts], ["f2"])
        self.assertEqual([f["id"] for f in prepared.disabled_facts], ["f3", "f4"])
        self.assertEqual([a["id"] for a in prepared.enabled_assumptions], ["a1"])
        self.assertEqual([a["id"] for a in prepared.disabled_assumptions], ["a2"])
        self.assertEqual([q["id"] for q in prepared.queries], ["q1"])
        self.assertEqual(prepared.request_id, "req-1")

    def test_result_is_deep_copy_and_input_untouched(self):
        source = {
            "request_id": "req-1",
            "game": {"id": "g1", "players": [{"id": "p1"}]},
            "facts": [{"id": "f1", "status": "confirmed", "enabled": True}],
            "queries": [{"id": "q1"}],
        }
        before = copy.deepcopy(source)
        prepared = prepare_request(source)

        prepared.game["id"] = "changed"
        prepared.game["players"][0]["id"] = "changed"
        prepared.confirmed_facts[0]["id"] = "changed"
        prepared.queries[0]["id"] = "changed"

        self.assertEqual(source, before)
        self.assertEqual(prepared.confirmed_facts[0]["id"], "changed")

        source["game"]["players"][0]["id"] = "later"
        self.assertEqual(prepared.game["players"][0]["id"], "changed")

    def test_non_mapping_raises(self):
        with self.assertRaises(TypeError):
            prepare_request(["not", "a", "mapping"])

    def test_missing_optional_collections_default_to_empty(self):
        prepared = prepare_request({"request_id": "r"})
        self.assertEqual(prepared.confirmed_facts, [])
        self.assertEqual(prepared.queries, [])
        self.assertEqual(prepared.game, {})
        self.assertEqual(prepared.options, {})


class BackendHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server("127.0.0.1", 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=10)

    # --- static files ---------------------------------------------------

    def test_static_protocol_example_served(self):
        response = request(self.port, "GET", "/protocol/examples/request.json")
        self.assertEqual(response.status, 200)
        self.assertIn("application/json", response.content_type)
        self.assertEqual(json_body(response), load_example("request"))

    # --- capabilities ---------------------------------------------------

    def test_capabilities_placeholder(self):
        response = request(self.port, "GET", "/api/v1/capabilities")
        self.assertEqual(response.status, 200)
        self.assertIn("application/json", response.content_type)
        body = json_body(response)
        self.assertEqual(body["api_version"], "1.0")
        self.assertEqual(body["supported_fact_types"], [])
        self.assertEqual(body["extensions"]["adapter:mode"], "placeholder")

    # --- reason happy path ----------------------------------------------

    def test_reason_example_unknown_echo(self):
        example = load_example("request")
        response = post_json(self.port, example)
        self.assertEqual(response.status, 200)
        body = json_body(response)
        self.assertEqual(body["request_id"], example["request_id"])
        self.assertEqual(body["game_id"], example["game"]["id"])
        self.assertEqual(body["revision"], example["game"]["revision"])
        self.assertEqual(body["consistency"], "unknown")
        self.assertEqual(body["extensions"]["adapter:mode"], "placeholder")
        self.assertEqual(
            [result["id"] for result in body["results"]],
            ["q-p5-alignment"],
        )
        self.assertEqual(body["results"][0]["status"], "unknown")

    def test_reason_empty_queries(self):
        example = load_example("request")
        example = copy.deepcopy(example)
        example["queries"] = []
        response = post_json(self.port, example)
        self.assertEqual(response.status, 200)
        self.assertEqual(json_body(response)["results"], [])

    # --- validation rejections ------------------------------------------

    def test_duplicate_id_across_collections(self):
        example = copy.deepcopy(load_example("request"))
        example["assumptions"][0]["id"] = example["facts"][0]["id"]
        response = post_json(self.port, example)
        self.assertEqual(response.status, 400)
        body = json_body(response)
        self.assertEqual(body["error"]["code"], "DUPLICATE_ID")
        self.assertEqual(body["error"]["path"], "/assumptions/0/id")

    def test_invalid_reference(self):
        example = copy.deepcopy(load_example("request"))
        example["facts"][0]["proposition"]["player_id"] = "p99"
        response = post_json(self.port, example)
        self.assertEqual(response.status, 400)
        body = json_body(response)
        self.assertEqual(body["error"]["code"], "INVALID_REFERENCE")
        self.assertEqual(body["error"]["path"], "/facts/0/proposition/player_id")

    def test_boolean_in_integer_field_rejected(self):
        example = copy.deepcopy(load_example("request"))
        example["game"]["revision"] = True
        response = post_json(self.port, example)
        self.assertEqual(response.status, 400)
        self.assertEqual(json_body(response)["error"]["code"], "INVALID_REQUEST")
        self.assertEqual(json_body(response)["error"]["path"], "/game/revision")

    def test_fractional_time_rejected(self):
        example = copy.deepcopy(load_example("request"))
        example["game"]["time"] = {"phase": "day", "number": 1.5}
        response = post_json(self.port, example)
        self.assertEqual(response.status, 400)
        self.assertEqual(json_body(response)["error"]["code"], "INVALID_REQUEST")
        self.assertEqual(json_body(response)["error"]["path"], "/game/time/number")

    def test_setup_time_with_number_rejected(self):
        example = copy.deepcopy(load_example("request"))
        example["game"]["time"] = {"phase": "setup", "number": 1}
        response = post_json(self.port, example)
        self.assertEqual(response.status, 400)
        self.assertEqual(json_body(response)["error"]["code"], "INVALID_FIELD")
        self.assertEqual(json_body(response)["error"]["path"], "/game/time/number")

    def test_fact_type_proposition_kind_mismatch_rejected(self):
        example = copy.deepcopy(load_example("request"))
        example["facts"][0]["proposition"]["kind"] = "alignment"
        example["facts"][0]["proposition"]["alignment"] = "good"
        del example["facts"][0]["proposition"]["role_id"]
        response = post_json(self.port, example)
        self.assertEqual(response.status, 400)
        self.assertEqual(json_body(response)["error"]["code"], "INVALID_REQUEST")
        self.assertEqual(
            json_body(response)["error"]["path"], "/facts/0/proposition/kind"
        )

    def test_unknown_active_extension_rejected(self):
        example = copy.deepcopy(load_example("request"))
        example["facts"].append(
            {
                "id": "f-ext",
                "type": "acme:custom",
                "status": "confirmed",
                "enabled": True,
                "data": {"note": "x"},
            }
        )
        response = post_json(self.port, example)
        self.assertEqual(response.status, 400)
        body = json_body(response)
        self.assertEqual(body["error"]["code"], "UNKNOWN_TYPE")
        self.assertEqual(body["error"]["path"], "/facts/3/type")

    def test_disabled_unknown_extension_allowed(self):
        example = copy.deepcopy(load_example("request"))
        example["facts"].append(
            {
                "id": "f-ext",
                "type": "acme:custom",
                "status": "confirmed",
                "enabled": False,
                "data": {"note": "x"},
            }
        )
        response = post_json(self.port, example)
        self.assertEqual(response.status, 200)
        self.assertEqual(json_body(response)["consistency"], "unknown")

    # --- raw body / transport errors ------------------------------------

    def test_duplicate_json_key_rejected(self):
        raw = b'{"api_version":"1.0","api_version":"1.0"}'
        response = post_raw(self.port, raw)
        self.assertEqual(response.status, 400)
        self.assertEqual(json_body(response)["error"]["code"], "INVALID_JSON")

    def test_nan_rejected(self):
        raw = b'{"api_version":"1.0","request_id":"r","game":{"revision":NaN}}'
        response = post_raw(self.port, raw)
        self.assertEqual(response.status, 400)
        self.assertEqual(json_body(response)["error"]["code"], "INVALID_JSON")

    def test_overflow_float_rejected(self):
        raw = b'{"api_version":"1.0","request_id":"r","game":{"revision":1e999}}'
        response = post_raw(self.port, raw)
        self.assertEqual(response.status, 400)
        self.assertEqual(json_body(response)["error"]["code"], "INVALID_JSON")

    def test_overflow_float_rejected_in_disabled_extension_data(self):
        raw = (
            b'{"api_version":"1.0","request_id":"r","game":{"revision":12},'
            b'"facts":[{"id":"f","type":"acme:custom","status":"confirmed",'
            b'"enabled":false,"data":{"n":1e999}}]}'
        )
        response = post_raw(self.port, raw)
        self.assertEqual(response.status, 400)
        self.assertEqual(json_body(response)["error"]["code"], "INVALID_JSON")

    def test_wrong_top_level_type_rejected(self):
        response = post_json(self.port, [])
        self.assertEqual(response.status, 400)
        self.assertEqual(json_body(response)["error"]["code"], "INVALID_REQUEST")

    def test_unsupported_media_type(self):
        body = json.dumps(load_example("request")).encode("utf-8")
        response = request(
            self.port,
            "POST",
            "/api/v1/reason",
            body=body,
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(response.status, 415)
        self.assertEqual(
            json_body(response)["error"]["code"], "UNSUPPORTED_MEDIA_TYPE"
        )

    def test_body_too_large(self):
        response = request(
            self.port,
            "POST",
            "/api/v1/reason",
            body=b"{}",
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(MAX_BODY_BYTES + 1),
            },
        )
        self.assertEqual(response.status, 413)
        self.assertEqual(json_body(response)["error"]["code"], "BODY_TOO_LARGE")

    def test_missing_content_length_rejected(self):
        response = raw_request(
            self.port,
            "POST",
            "/api/v1/reason",
            [("Content-Type", "application/json"), ("Connection", "close")],
        )
        self.assertEqual(response.status, 411)
        self.assertEqual(json_body(response)["error"]["code"], "LENGTH_REQUIRED")

    def test_negative_content_length_rejected(self):
        response = raw_request(
            self.port,
            "POST",
            "/api/v1/reason",
            [
                ("Content-Type", "application/json"),
                ("Content-Length", "-1"),
                ("Connection", "close"),
            ],
        )
        self.assertEqual(response.status, 400)
        self.assertEqual(json_body(response)["error"]["code"], "INVALID_LENGTH")

    def test_transfer_encoding_rejected(self):
        response = raw_request(
            self.port,
            "POST",
            "/api/v1/reason",
            [
                ("Content-Type", "application/json"),
                ("Transfer-Encoding", "chunked"),
                ("Connection", "close"),
            ],
        )
        self.assertEqual(response.status, 400)
        self.assertEqual(json_body(response)["error"]["code"], "INVALID_REQUEST")

    # --- routing --------------------------------------------------------

    def test_unknown_api_route(self):
        response = request(self.port, "GET", "/api/v1/nope")
        self.assertEqual(response.status, 404)
        self.assertEqual(json_body(response)["error"]["code"], "NOT_FOUND")

    def test_method_not_allowed_reason_get(self):
        response = request(self.port, "GET", "/api/v1/reason")
        self.assertEqual(response.status, 405)
        self.assertEqual(response.allow, "POST")
        self.assertEqual(
            json_body(response)["error"]["code"], "METHOD_NOT_ALLOWED"
        )

    def test_method_not_allowed_capabilities_post(self):
        response = request(
            self.port,
            "POST",
            "/api/v1/capabilities",
            body=b"{}",
            headers=_JSON,
        )
        self.assertEqual(response.status, 405)
        self.assertEqual(response.allow, "GET")

    # --- injected adapter behaviour -------------------------------------

    def test_adapter_sat_returns_200(self):
        example = load_example("request")
        result = {
            "api_version": "1.0",
            "request_id": example["request_id"],
            "game_id": example["game"]["id"],
            "revision": example["game"]["revision"],
            "consistency": "sat",
            "results": [{"id": "q-p5-alignment", "status": "necessary"}],
        }
        with mock.patch.object(
            PlaceholderAdapter, "reason", return_value=result
        ):
            response = post_json(self.port, example)
        self.assertEqual(response.status, 200)
        self.assertEqual(json_body(response)["consistency"], "sat")

    def test_adapter_unsat_returns_200(self):
        example = load_example("request")
        result = {
            "api_version": "1.0",
            "request_id": example["request_id"],
            "game_id": example["game"]["id"],
            "revision": example["game"]["revision"],
            "consistency": "unsat",
            "results": [{"id": "q-p5-alignment", "status": "inconsistent"}],
        }
        with mock.patch.object(
            PlaceholderAdapter, "reason", return_value=result
        ):
            response = post_json(self.port, example)
        self.assertEqual(response.status, 200)
        body = json_body(response)
        self.assertEqual(body["consistency"], "unsat")
        self.assertEqual(body["results"][0]["status"], "inconsistent")

    def test_adapter_exception_returns_500(self):
        example = load_example("request")
        with mock.patch.object(
            PlaceholderAdapter, "reason", side_effect=RuntimeError("boom")
        ), self.assertLogs(level="ERROR"):
            response = post_json(self.port, example)
        self.assertEqual(response.status, 500)
        self.assertEqual(json_body(response)["error"]["code"], "INTERNAL_ERROR")

    def test_requests_are_isolated_within_one_server(self):
        example = copy.deepcopy(load_example("request"))
        example["queries"] = []
        before = copy.deepcopy(example)

        first = json_body(post_json(self.port, example))
        self.assertEqual(first["results"], [])

        example2 = load_example("request")
        second = json_body(post_json(self.port, example2))
        self.assertEqual(
            [result["id"] for result in second["results"]], ["q-p5-alignment"]
        )

        self.assertEqual(example, before)
        self.assertEqual(json_body(post_json(self.port, example))["results"], [])


if __name__ == "__main__":
    unittest.main()
