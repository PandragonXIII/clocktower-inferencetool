"""可复现的概率推理小 benchmark（不是 unittest）。

在同一份 5 人网页请求上，经真实 HTTP（``create_server`` + 真实
``TroubleBrewingAdapter``）分别发送 ``probability_mode:false`` 与
``probability_mode:true``，对比实际耗时、一致性、组合枚举和抽样概率。

输入为 5 名玩家、5 条启用的 ``reported`` 角色声明（其中两人自称厨师，形成
conditional 冲突）、无查询。除概率开关外，两次请求的输入完全相同：

- ``timeout_ms``：10000
- ``total_timeout_ms``：8000
- ``probability_timeout_ms``：120000

用法（仓库根目录）：

    .venv/bin/python tests/benchmark_probability.py

脚本不 mock 连接器或求解器；HTTP 读取超时为 120 秒。若某次请求超过 120 秒，
该轮标记为 ``unknown``（超时不是逻辑结论）。
"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from backend.http_server import create_server  # noqa: E402
from connector import TroubleBrewingAdapter  # noqa: E402
from test_extension_validation import base_request  # noqa: E402

HTTP_TIMEOUT_S = 120
PLAYER_COUNT = 5

# 5 条玩家声明；p1 与 p3 都自称厨师，全部采信时与角色唯一性冲突。
CLAIMS = (
    ("p1", "chef"),
    ("p2", "soldier"),
    ("p3", "chef"),
    ("p4", "washerwoman"),
    ("p5", "imp"),
)

BASE_OPTIONS = {
    "timeout_ms": 10000,
    "total_timeout_ms": 8000,
    "probability_timeout_ms": 120000,
}


def benchmark_request(probability_mode: bool) -> dict:
    request = base_request()
    request["request_id"] = "bench-probability"
    request["game"]["revision"] = 1
    request["game"]["time"] = {"phase": "setup"}
    request["facts"] = [
        {
            "id": f"claim-{player_id}",
            "type": "role",
            "status": "reported",
            "enabled": True,
            "proposition": {
                "kind": "role",
                "player_id": player_id,
                "role_id": role_id,
                "time": {"phase": "setup"},
            },
        }
        for player_id, role_id in CLAIMS
    ]
    request["assumptions"] = []
    request["queries"] = []
    request["options"] = {**BASE_OPTIONS, "probability_mode": probability_mode}
    return request


def start_server() -> tuple:
    adapter = TroubleBrewingAdapter()
    server = create_server("127.0.0.1", 0, adapter=adapter)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, port


def post(port: int, request: dict) -> tuple[dict | None, float, str | None]:
    body = json.dumps(request).encode("utf-8")
    http_request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/v1/reason",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(http_request, timeout=HTTP_TIMEOUT_S) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload, time.perf_counter() - started, None
    except (urllib.error.URLError, TimeoutError) as error:
        return None, time.perf_counter() - started, str(error)


def normalized_rows(rows: list[dict]) -> list[dict]:
    normalized = []
    for row in rows:
        values = row.get("probabilities") or {}
        normalized.append(
            {
                "player_id": row.get("player_id"),
                "seat": row.get("seat"),
                "probabilities": {
                    role_id: round(value, 4) for role_id, value in sorted(values.items())
                },
                "sum": round(sum(values.values()), 4),
            }
        )
    return normalized


def summarize(mode: bool, payload: dict | None, elapsed: float, error: str | None) -> dict:
    if payload is None:
        return {
            "probability_mode": mode,
            "status": "unknown",
            "elapsed_s": round(elapsed, 3),
            "error": error,
        }
    extensions = payload.get("extensions") or {}
    probabilities = extensions.get("reasoner:probabilities")
    summary = {
        "probability_mode": mode,
        "consistency": payload.get("consistency"),
        "elapsed_s": round(elapsed, 3),
        "timings": extensions.get("reasoner:timings"),
        "participation": [
            {"id": item.get("id"), "status": item.get("status")}
            for item in extensions.get("reasoner:participation") or []
        ],
    }
    if probabilities is None:
        summary.update(
            status="not_requested",
            has_diagnosis="reasoner:diagnosis" in extensions,
            has_role_ranges="reasoner:role_ranges" in extensions,
        )
        return summary
    summary.update(
        status=probabilities.get("status"),
        reason=probabilities.get("reason"),
        groups=probabilities.get("groups"),
        target_accepted_per_group=probabilities.get("target_accepted_per_group"),
        max_trials_per_group=probabilities.get("max_trials_per_group"),
        hard_input_ids=probabilities.get("hard_input_ids"),
        soft_input_ids=probabilities.get("soft_input_ids"),
        rows=normalized_rows(probabilities.get("rows") or []),
    )
    return summary


def main() -> int:
    server, thread, port = start_server()
    print(f"HTTP benchmark on 127.0.0.1:{port} ({PLAYER_COUNT} players, 5 reported claims, 2 chefs)")
    try:
        results = []
        for mode in (False, True):
            request = benchmark_request(mode)
            payload, elapsed, error = post(port, request)
            summary = summarize(mode, payload, elapsed, error)
            results.append(summary)
            print(f"\n=== probability_mode={mode} ===")
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        print("\n=== comparison ===")
        print(
            json.dumps(
                [
                    {
                        "probability_mode": item["probability_mode"],
                        "status": item["status"],
                        "consistency": item.get("consistency"),
                        "elapsed_s": item["elapsed_s"],
                        "timings": item.get("timings"),
                        "groups": item.get("groups"),
                    }
                    for item in results
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
