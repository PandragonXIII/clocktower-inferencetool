"""Runtime validation for ``POST /api/v1/reason`` requests.

The contract lives in ``web/protocol/types.ts`` (``ReasonRequest``). TypeScript
types only hold at compile time, so the backend must re-check every request at
runtime for shape, duplicate ids, invalid references and unknown types.

``validate_request`` returns the (unmodified) request on success and raises
:class:`ApiError` on the first problem found. It never depends on Z3 or any
third-party library, never mutates its input, and never lets a ``KeyError`` or
similar escape: every failure is reported as a protocol ``ApiError``.
"""

from __future__ import annotations

from typing import Any

from .errors import ApiError
from .extension_validation import KNOWN_EXTENSIONS, validate_extension_data

API_VERSION = "1.0"

_TOP_LEVEL_FIELDS = {
    "api_version",
    "request_id",
    "game",
    "facts",
    "assumptions",
    "queries",
    "options",
}
_GAME_FIELDS = {"id", "revision", "script_id", "players", "time"}
_PLAYER_FIELDS = {"id", "seat", "name"}
_TIME_FIELDS = {"phase", "number"}
_FACT_COMMON_FIELDS = {"id", "type", "status", "enabled", "extensions"}
_ROLE_PROPOSITION_FIELDS = {"kind", "player_id", "role_id", "time"}
_ALIGNMENT_PROPOSITION_FIELDS = {"kind", "player_id", "alignment", "time"}
_ASSUMPTION_FIELDS = {"id", "enabled", "proposition", "extensions"}
_QUERY_FIELDS = {"id", "proposition"}
_OPTIONS_FIELDS = {
    "timeout_ms",
    "total_timeout_ms",
    "max_worlds",
    "max_repairs",
    "max_repair_checks",
    "probability_mode",
    "probability_timeout_ms",
}

# Bounded integer options: key -> (minimum, maximum), inclusive.
_BOUNDED_OPTIONS = {
    "total_timeout_ms": (1, 60000),
    "max_worlds": (0, 100),
    "max_repairs": (0, 10),
    "max_repair_checks": (1, 1024),
    "probability_timeout_ms": (1, 300000),
}

_STATUS_VALUES = ("confirmed", "reported")
_ALIGNMENT_VALUES = ("good", "evil")
_PHASE_VALUES = ("setup", "day", "night")

# Controlled metadata carried under the ``reasoner:`` extension namespace.
_REASONER_SCOPE = "reasoner:scope"
_REASONER_SOURCE = "reasoner:source"
_REASONER_OWNER = "reasoner:owner_id"
_SCOPE_VALUES = ("public", "conditional")
_SOURCE_VALUES = (
    "received",
    "self_claim",
    "assumption",
    "public_announcement",
    "observation",
)


def _escape(token: Any) -> str:
    return str(token).replace("~", "~0").replace("/", "~1")


def _ptr(path: str, token: Any) -> str:
    return f"{path}/{_escape(token)}"


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_str(value: Any) -> bool:
    return isinstance(value, str)


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and value != ""


def _fail(code: str, message: str, path: str) -> None:
    raise ApiError(400, code, message, path)


def _reject_unknown_fields(value: dict[str, Any], allowed: set[str], path: str) -> None:
    for key in value:
        if key not in allowed:
            _fail("INVALID_FIELD", f"unknown field: {key!r}", _ptr(path, key))


def _require_object(value: Any, path: str, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail("INVALID_REQUEST", f"{label} must be a JSON object", path)
    return value


def _require_array(value: Any, path: str, label: str) -> list[Any]:
    if not isinstance(value, list):
        _fail("INVALID_REQUEST", f"{label} must be a JSON array", path)
    return value


def _require_field(obj: dict[str, Any], key: str, path: str) -> Any:
    if key not in obj:
        _fail("INVALID_REQUEST", f"missing required field: {key!r}", _ptr(path, key))
    return obj[key]


def _require_nonempty_id(obj: dict[str, Any], path: str) -> str:
    value = _require_field(obj, "id", path)
    if not _is_nonempty_str(value):
        _fail("INVALID_REQUEST", "id must be a non-empty string", _ptr(path, "id"))
    return value


def _require_bool(obj: dict[str, Any], key: str, path: str) -> bool:
    value = _require_field(obj, key, path)
    if not _is_bool(value):
        _fail("INVALID_REQUEST", f"{key} must be a boolean", _ptr(path, key))
    return value


def _register_id(seen: dict[str, str], identifier: str, path: str) -> None:
    if identifier in seen:
        _fail(
            "DUPLICATE_ID",
            f"duplicate id {identifier!r} (already used at {seen[identifier]})",
            path,
        )
    seen[identifier] = path


def _validate_extensions(
    value: Any,
    path: str,
    player_ids: set[str],
    *,
    is_assumption: bool,
    status: str | None,
) -> None:
    if not isinstance(value, dict):
        _fail("INVALID_REQUEST", "extensions must be a JSON object", path)
    for key in value:
        if not _is_nonempty_str(key) or ":" not in key:
            _fail(
                "INVALID_REQUEST",
                "extension keys must be namespaced as 'namespace:name'",
                _ptr(path, key),
            )
        namespace, _, name = key.partition(":")
        if namespace == "" or name == "":
            _fail(
                "INVALID_REQUEST",
                "extension keys must be namespaced as 'namespace:name'",
                _ptr(path, key),
            )
    _validate_reasoner_metadata(
        value, path, player_ids, is_assumption=is_assumption, status=status
    )


def _validate_reasoner_metadata(
    extensions: dict[str, Any],
    path: str,
    player_ids: set[str],
    *,
    is_assumption: bool,
    status: str | None,
) -> None:
    """Validate the controlled ``reasoner:*`` metadata inside ``extensions``.

    Unknown (non-``reasoner:``) extension fields stay allowed; only the known
    ``reasoner:`` keys are checked. The metadata is validated even when the
    record is disabled so that references stay meaningful.
    """
    scope = None
    if _REASONER_SCOPE in extensions:
        scope = extensions[_REASONER_SCOPE]
        if scope not in _SCOPE_VALUES:
            _fail(
                "INVALID_REQUEST",
                "reasoner:scope must be 'public' or 'conditional'",
                _ptr(path, _REASONER_SCOPE),
            )

    if _REASONER_SOURCE in extensions:
        source = extensions[_REASONER_SOURCE]
        if not _is_nonempty_str(source) or source not in _SOURCE_VALUES:
            _fail(
                "INVALID_REQUEST",
                "reasoner:source must be one of "
                + ", ".join(repr(v) for v in _SOURCE_VALUES),
                _ptr(path, _REASONER_SOURCE),
            )

    if _REASONER_OWNER in extensions:
        owner = extensions[_REASONER_OWNER]
        if not _is_nonempty_str(owner):
            _fail(
                "INVALID_REQUEST",
                "reasoner:owner_id must be a non-empty string",
                _ptr(path, _REASONER_OWNER),
            )
        if owner not in player_ids:
            _fail(
                "INVALID_REFERENCE",
                f"unknown player_id: {owner!r}",
                _ptr(path, _REASONER_OWNER),
            )

    if scope == "public":
        if is_assumption:
            _fail(
                "INVALID_REQUEST",
                "assumptions cannot be reasoner:scope public",
                _ptr(path, _REASONER_SCOPE),
            )
        if status == "reported":
            _fail(
                "INVALID_REQUEST",
                "reported facts cannot be reasoner:scope public",
                _ptr(path, _REASONER_SCOPE),
            )


def _validate_time(value: Any, path: str) -> int:
    """Validate a Time value and return its sortable rank.

    ``setup`` ranks before everything; then the cycle is night1 < day1 <
    night2 < day2 ... so a proposition never precedes or exceeds the game time.
    """
    obj = _require_object(value, path, "time")
    _reject_unknown_fields(obj, _TIME_FIELDS, path)

    phase = _require_field(obj, "phase", path)
    if not _is_str(phase) or phase not in _PHASE_VALUES:
        _fail(
            "INVALID_REQUEST",
            "time.phase must be 'setup', 'day' or 'night'",
            _ptr(path, "phase"),
        )

    if phase == "setup":
        if "number" in obj:
            _fail("INVALID_FIELD", "setup must not include number", _ptr(path, "number"))
        return 0

    number = _require_field(obj, "number", path)
    if not _is_int(number) or number <= 0:
        _fail(
            "INVALID_REQUEST",
            "time.number must be a positive integer",
            _ptr(path, "number"),
        )

    return 2 * number - 1 if phase == "night" else 2 * number


def _validate_player(
    player: Any,
    index: int,
    players_path: str,
    seen: dict[str, str],
    seat_count: int,
    seats: set[int],
) -> str:
    path = _ptr(players_path, index)
    obj = _require_object(player, path, "player")
    _reject_unknown_fields(obj, _PLAYER_FIELDS, path)

    player_id = _require_nonempty_id(obj, path)
    _register_id(seen, player_id, _ptr(path, "id"))

    seat = _require_field(obj, "seat", path)
    if not _is_int(seat) or seat < 1 or seat > seat_count:
        _fail(
            "INVALID_REQUEST",
            f"seat must be an integer in 1..{seat_count}",
            _ptr(path, "seat"),
        )
    if seat in seats:
        _fail("INVALID_REQUEST", f"duplicate seat: {seat}", _ptr(path, "seat"))
    seats.add(seat)

    name = _require_field(obj, "name", path)
    if not _is_str(name):
        _fail("INVALID_REQUEST", "name must be a string", _ptr(path, "name"))

    return player_id


def _validate_game(
    value: Any,
    path: str,
    seen: dict[str, str],
) -> tuple[int, set[str]]:
    obj = _require_object(value, path, "game")
    _reject_unknown_fields(obj, _GAME_FIELDS, path)

    game_id = _require_nonempty_id(obj, path)
    _register_id(seen, game_id, _ptr(path, "id"))

    revision = _require_field(obj, "revision", path)
    if not _is_int(revision) or revision < 0:
        _fail(
            "INVALID_REQUEST",
            "revision must be a non-negative integer",
            _ptr(path, "revision"),
        )

    script_id = _require_field(obj, "script_id", path)
    if not _is_nonempty_str(script_id):
        _fail(
            "INVALID_REQUEST",
            "script_id must be a non-empty string",
            _ptr(path, "script_id"),
        )

    players_value = _require_field(obj, "players", path)
    players = _require_array(players_value, _ptr(path, "players"), "players")

    player_ids: set[str] = set()
    seats: set[int] = set()
    count = len(players)
    for index, player in enumerate(players):
        player_id = _validate_player(
            player, index, _ptr(path, "players"), seen, count, seats
        )
        player_ids.add(player_id)

    game_rank = _validate_time(_require_field(obj, "time", path), _ptr(path, "time"))

    return game_rank, player_ids


def _validate_proposition(
    value: Any,
    path: str,
    player_ids: set[str],
    game_rank: int,
) -> str:
    """Validate a Proposition; return its kind (``role`` or ``alignment``)."""
    obj = _require_object(value, path, "proposition")

    kind = _require_field(obj, "kind", path)
    if kind not in ("role", "alignment"):
        _fail("UNKNOWN_TYPE", f"unknown proposition kind: {kind!r}", _ptr(path, "kind"))

    if kind == "role":
        _reject_unknown_fields(obj, _ROLE_PROPOSITION_FIELDS, path)
    else:
        _reject_unknown_fields(obj, _ALIGNMENT_PROPOSITION_FIELDS, path)

    player_id = _require_field(obj, "player_id", path)
    if not _is_nonempty_str(player_id):
        _fail(
            "INVALID_REQUEST",
            "player_id must be a non-empty string",
            _ptr(path, "player_id"),
        )
    if player_id not in player_ids:
        _fail(
            "INVALID_REFERENCE",
            f"unknown player_id: {player_id!r}",
            _ptr(path, "player_id"),
        )

    if kind == "role":
        role_id = _require_field(obj, "role_id", path)
        if not _is_nonempty_str(role_id):
            _fail(
                "INVALID_REQUEST",
                "role_id must be a non-empty string",
                _ptr(path, "role_id"),
            )
    else:
        alignment = _require_field(obj, "alignment", path)
        if alignment not in _ALIGNMENT_VALUES:
            _fail(
                "INVALID_REQUEST",
                "alignment must be 'good' or 'evil'",
                _ptr(path, "alignment"),
            )

    rank = _validate_time(_require_field(obj, "time", path), _ptr(path, "time"))
    if rank > game_rank:
        _fail(
            "INVALID_REQUEST",
            "proposition time is later than game.time",
            _ptr(path, "time"),
        )

    return kind


def _validate_fact(
    value: Any,
    index: int,
    facts_path: str,
    player_ids: set[str],
    game_rank: int,
    seen: dict[str, str],
) -> None:
    path = _ptr(facts_path, index)
    obj = _require_object(value, path, "fact")

    fact_id = _require_nonempty_id(obj, path)
    _register_id(seen, fact_id, _ptr(path, "id"))

    fact_type = _require_field(obj, "type", path)
    if not _is_nonempty_str(fact_type):
        _fail("UNKNOWN_TYPE", "fact.type must be a non-empty string", _ptr(path, "type"))

    status = _require_field(obj, "status", path)
    if status not in _STATUS_VALUES:
        _fail(
            "INVALID_REQUEST",
            "status must be 'confirmed' or 'reported'",
            _ptr(path, "status"),
        )

    enabled = _require_bool(obj, "enabled", path)

    if "extensions" in obj:
        _validate_extensions(
            obj["extensions"],
            _ptr(path, "extensions"),
            player_ids,
            is_assumption=False,
            status=status,
        )

    if fact_type in ("role", "alignment"):
        _reject_unknown_fields(obj, _FACT_COMMON_FIELDS | {"proposition"}, path)
        proposition_path = _ptr(path, "proposition")
        proposition = _require_field(obj, "proposition", path)
        kind = _validate_proposition(
            proposition, proposition_path, player_ids, game_rank
        )
        if kind != fact_type:
            _fail(
                "INVALID_REQUEST",
                f"fact.type {fact_type!r} does not match proposition.kind {kind!r}",
                _ptr(proposition_path, "kind"),
            )
        return

    # Extension fact: type must be namespaced as 'namespace:name'.
    if ":" not in fact_type:
        _fail("UNKNOWN_TYPE", f"unknown fact type: {fact_type!r}", _ptr(path, "type"))
    namespace, _, name = fact_type.partition(":")
    if namespace == "" or name == "":
        _fail(
            "INVALID_REQUEST",
            "extension fact type must be namespaced as 'namespace:name'",
            _ptr(path, "type"),
        )

    _reject_unknown_fields(obj, _FACT_COMMON_FIELDS | {"data"}, path)
    if "data" not in obj:
        _fail("INVALID_REQUEST", "extension fact requires 'data'", _ptr(path, "data"))

    if enabled and fact_type in KNOWN_EXTENSIONS:
        validate_extension_data(fact_type, obj["data"], _ptr(path, "data"), player_ids, game_rank)
    elif enabled:
        _fail(
            "UNKNOWN_TYPE",
            f"unsupported enabled extension fact type: {fact_type!r}",
            _ptr(path, "type"),
        )


def _validate_assumption(
    value: Any,
    index: int,
    assumptions_path: str,
    player_ids: set[str],
    game_rank: int,
    seen: dict[str, str],
) -> None:
    path = _ptr(assumptions_path, index)
    obj = _require_object(value, path, "assumption")
    _reject_unknown_fields(obj, _ASSUMPTION_FIELDS, path)

    assumption_id = _require_nonempty_id(obj, path)
    _register_id(seen, assumption_id, _ptr(path, "id"))

    _require_bool(obj, "enabled", path)

    if "extensions" in obj:
        _validate_extensions(
            obj["extensions"],
            _ptr(path, "extensions"),
            player_ids,
            is_assumption=True,
            status=None,
        )

    proposition = _require_field(obj, "proposition", path)
    _validate_proposition(
        proposition, _ptr(path, "proposition"), player_ids, game_rank
    )


def _validate_query(
    value: Any,
    index: int,
    queries_path: str,
    player_ids: set[str],
    game_rank: int,
    seen: dict[str, str],
) -> None:
    path = _ptr(queries_path, index)
    obj = _require_object(value, path, "query")
    _reject_unknown_fields(obj, _QUERY_FIELDS, path)

    query_id = _require_nonempty_id(obj, path)
    _register_id(seen, query_id, _ptr(path, "id"))

    proposition = _require_field(obj, "proposition", path)
    _validate_proposition(
        proposition, _ptr(path, "proposition"), player_ids, game_rank
    )


def _validate_options(value: Any, path: str) -> None:
    obj = _require_object(value, path, "options")
    _reject_unknown_fields(obj, _OPTIONS_FIELDS, path)

    if "timeout_ms" in obj:
        timeout = obj["timeout_ms"]
        if not _is_int(timeout) or timeout <= 0:
            _fail(
                "INVALID_REQUEST",
                "timeout_ms must be a positive integer",
                _ptr(path, "timeout_ms"),
            )

    if "probability_mode" in obj and type(obj["probability_mode"]) is not bool:
        _fail("INVALID_REQUEST", "probability_mode must be boolean", _ptr(path, "probability_mode"))
    for key, (minimum, maximum) in _BOUNDED_OPTIONS.items():
        if key not in obj:
            continue
        option = obj[key]
        if not _is_int(option) or option < minimum or option > maximum:
            _fail(
                "INVALID_REQUEST",
                f"{key} must be an integer in {minimum}..{maximum}",
                _ptr(path, key),
            )


def validate_request(value: Any) -> dict[str, Any]:
    """Validate a ``ReasonRequest`` and return it unchanged.

    Raises :class:`ApiError` (HTTP 400) with an appropriate ``code`` and JSON
    Pointer ``path`` on any protocol violation. The input is never modified.

    Error codes:
    - ``INVALID_REQUEST``: wrong shape / type / missing or malformed value.
    - ``UNSUPPORTED_API_VERSION``: ``api_version`` is not ``"1.0"``.
    - ``DUPLICATE_ID``: an id is reused within the request.
    - ``INVALID_REFERENCE``: a ``player_id`` does not refer to a known player.
    - ``INVALID_FIELD``: an unknown non-namespaced field is present.
    - ``UNKNOWN_TYPE``: an unknown fact type or proposition kind is present.
    """
    request = _require_object(value, "", "request")
    _reject_unknown_fields(request, _TOP_LEVEL_FIELDS, "")

    api_version = _require_field(request, "api_version", "")
    if api_version != API_VERSION:
        _fail(
            "UNSUPPORTED_API_VERSION",
            f"unsupported api_version: {api_version!r}; expected {API_VERSION!r}",
            "/api_version",
        )

    request_id = _require_field(request, "request_id", "")
    if not _is_nonempty_str(request_id):
        _fail(
            "INVALID_REQUEST",
            "request_id must be a non-empty string",
            "/request_id",
        )

    seen: dict[str, str] = {}
    _register_id(seen, request_id, "/request_id")

    game_rank, player_ids = _validate_game(
        _require_field(request, "game", ""), "/game", seen
    )

    facts = _require_array(
        _require_field(request, "facts", ""), "/facts", "facts"
    )
    for index, fact in enumerate(facts):
        _validate_fact(fact, index, "/facts", player_ids, game_rank, seen)

    assumptions = _require_array(
        _require_field(request, "assumptions", ""), "/assumptions", "assumptions"
    )
    for index, assumption in enumerate(assumptions):
        _validate_assumption(
            assumption, index, "/assumptions", player_ids, game_rank, seen
        )

    queries = _require_array(
        _require_field(request, "queries", ""), "/queries", "queries"
    )
    for index, query in enumerate(queries):
        _validate_query(query, index, "/queries", player_ids, game_rank, seen)

    if "options" in request:
        _validate_options(request["options"], "/options")

    return request
