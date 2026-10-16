"""Project entry point for engine tests and a small reasoning demo."""

import sys
import unittest
from pathlib import Path


def run_tests() -> int:
    test_dir = Path(__file__).resolve().parent / "tests"
    suite = unittest.defaultTestLoader.discover(str(test_dir))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def run_demo() -> int:
    from z3 import Bool, Or

    from engine import ReasoningEngine

    demon = Bool("player_is_demon")
    engine = ReasoningEngine()
    engine.add_constraint(Or(demon, ~demon), label="valid_state")
    print(engine.query(demon))
    return 0


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "test"
    if command == "test":
        return run_tests()
    if command == "demo":
        return run_demo()
    print("Usage: python main.py [test|demo]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
