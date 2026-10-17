"""Same-origin static UI and JSON API, independent of the reasoning adapter."""

import json
import logging
import math
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .adapter import PlaceholderAdapter
from .errors import ApiError
from .validation import validate_request

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
MAX_BODY_BYTES = 1024 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f"invalid JSON number: {value}")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON number exceeds finite range")
    return number


def create_server(host="127.0.0.1", port=8000, *, adapter=None):
    """Create an unstarted server. Injected adapters must be thread-safe/stateless."""
    adapter = adapter if adapter is not None else PlaceholderAdapter()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(WEB_DIR), **kwargs)

        def _json(self, status, value, *, allow=None, head=False):
            body = json.dumps(value, ensure_ascii=True, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if allow:
                self.send_header("Allow", allow)
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def _api(self, method):
            request_id = None
            path = urlsplit(self.path).path
            try:
                routes = {"/api/v1/reason": "POST", "/api/v1/capabilities": "GET"}
                if path not in routes:
                    raise ApiError(404, "NOT_FOUND", "未知 API 路径")
                if method != routes[path]:
                    self.close_connection = True
                    self._json(405, ApiError(405, "METHOD_NOT_ALLOWED", "不支持此请求方法").to_response(), allow=routes[path], head=method == "HEAD")
                    return
                if method == "GET":
                    self._json(200, adapter.capabilities())
                    return
                if self.headers.get("Transfer-Encoding") is not None:
                    raise ApiError(400, "INVALID_REQUEST", "不支持 Transfer-Encoding")
                lengths = self.headers.get_all("Content-Length", [])
                if not lengths:
                    raise ApiError(411, "LENGTH_REQUIRED", "需要 Content-Length")
                if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
                    raise ApiError(400, "INVALID_LENGTH", "Content-Length 必须是非负整数")
                length = int(lengths[0])
                if length > MAX_BODY_BYTES:
                    raise ApiError(413, "BODY_TOO_LARGE", "请求体不能超过 1 MiB")
                if self.headers.get_content_type() != "application/json":
                    raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "需要 application/json")
                self.connection.settimeout(10)
                try:
                    raw = self.rfile.read(length)
                    if len(raw) != length:
                        raise ValueError("incomplete request body")
                    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_invalid_constant, parse_float=_finite_float)
                except (ValueError, RecursionError) as exc:
                    raise ApiError(400, "INVALID_JSON", "请求体必须是有效 UTF-8 JSON，不能包含重复键或非有限数值") from exc
                except TimeoutError as exc:
                    raise ApiError(408, "REQUEST_TIMEOUT", "读取请求体超时") from exc
                if isinstance(value, dict) and isinstance(value.get("request_id"), str) and value["request_id"]:
                    request_id = value["request_id"]
                self._json(200, adapter.reason(validate_request(value)))
            except ApiError as exc:
                self.close_connection = True
                self._json(exc.status, exc.to_response(request_id=request_id), head=method == "HEAD")
            except Exception:
                logging.exception("API request failed")
                self.close_connection = True
                self._json(500, ApiError(500, "INTERNAL_ERROR", "后台内部错误").to_response(request_id=request_id), head=method == "HEAD")

        def do_GET(self):
            if urlsplit(self.path).path.startswith("/api/"):
                self._api("GET")
            else:
                super().do_GET()

        def do_HEAD(self):
            if urlsplit(self.path).path.startswith("/api/"):
                self._api("HEAD")
            else:
                super().do_HEAD()

        def do_POST(self):
            self._api("POST")

        def do_PUT(self):
            self._api("PUT")

        def do_DELETE(self):
            self._api("DELETE")

        def do_PATCH(self):
            self._api("PATCH")

        def do_OPTIONS(self):
            self._api("OPTIONS")

    return ThreadingHTTPServer((host, port), Handler)
