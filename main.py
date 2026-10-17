"""Project entry point for unit tests, a reasoning demo, and web serving.

Commands:
    python main.py test   Run the unit test suite (default when no command given).
    python main.py demo   Run a small botc_reasoner reasoning demo.
    python main.py web    Serve the web UI and the real reasoning API.
"""

import argparse
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
WEB_DIR = REPO_ROOT / "web"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def run_tests() -> int:
    test_dir = Path(__file__).resolve().parent / "tests"
    suite = unittest.defaultTestLoader.discover(str(test_dir))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def run_demo() -> int:
    from z3 import Not, sat, unsat

    from botc_reasoner import Role, add_game_rules, declare_variables
    from botc_reasoner.roles import BASE_SETUP

    def status(solver) -> str:
        result = solver.check()
        if result == sat:
            return "sat"
        if result == unsat:
            return "unsat"
        return "unknown"

    world = declare_variables(5, n_nights=1)
    solver = world.build_solver()
    add_game_rules(solver, world, *BASE_SETUP[5])

    print("5 人局，1 夜，装载暗流涌动规则")
    print(f"基础一致性：{status(solver)}")

    solver.push()
    solver.add(world.start_is(0, Role.IMP))
    print(f"玩家 0 是小恶魔（正命题）：{status(solver)}")
    solver.pop()

    solver.push()
    solver.add(Not(world.start_is(0, Role.IMP)))
    print(f"玩家 0 是小恶魔（反命题）：{status(solver)}")
    solver.pop()
    return 0


def _valid_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid port: {value!r}")
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be in range 1..65535")
    return port


def run_web(host: str, port: int) -> int:
    from backend.http_server import create_server
    from connector import TroubleBrewingAdapter

    try:
        httpd = create_server(host, port, adapter=TroubleBrewingAdapter())
    except OSError as exc:
        print(f"error: cannot start web server on {host}:{port}: {exc}", file=sys.stderr)
        return 1
    print(f"Serving UI and reasoning API at http://{host}:{port}/ (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nweb server stopped", file=sys.stderr)
    finally:
        httpd.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Blood on the Clocktower reasoning assistant entry point.",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("test", help="run the unit test suite (default)")
    subparsers.add_parser("demo", help="run the botc_reasoner reasoning demo")
    web = subparsers.add_parser("web", help="serve the web UI and real reasoning API")
    web.add_argument("--host", default=DEFAULT_HOST, help="bind host (default: 127.0.0.1)")
    web.add_argument(
        "--port",
        type=_valid_port,
        default=DEFAULT_PORT,
        help="bind port, 1..65535 (default: 8000)",
    )
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "test"
    if command == "test":
        return run_tests()
    if command == "demo":
        return run_demo()
    if command == "web":
        return run_web(args.host, args.port)
    parser.print_usage(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
