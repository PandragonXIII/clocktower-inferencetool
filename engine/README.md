# Constraint reasoning engine

`ReasoningEngine` is a general-purpose Python interface to Z3 Boolean and SMT constraints. It stores labeled base constraints, checks satisfiability, and tests whether a query is possible, necessary, or impossible. A contradictory base is reported as `inconsistent`. Checks and queries accept temporary assumptions that do not modify stored constraints.

Unsatisfiable results include labels from Z3's unsat core; this is a useful conflict subset and is not guaranteed to be minimal. SAT results include a Z3 model. UNKNOWN results include Z3's reason when available. The engine does not enumerate all satisfying models and does not encode any BOTC-specific rules.

The default solver timeout is 1000 ms per individual Z3 solve. A query may run multiple solves (base consistency, query possible, and query negation), so this is a per-solve timeout rather than a total query budget. Configure it with `ReasoningEngine(timeout_ms=...)`; the value must be a positive integer.

## Install and run

From the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python main.py test
python main.py demo
```

## Python API

```python
from z3 import Bool, PbEq
from engine import ReasoningEngine

players = [Bool(f"demon_{i}") for i in range(5)]
engine = ReasoningEngine()
engine.add_constraint(PbEq([(player, 1) for player in players], 1), "one_demon")

result = engine.query(players[0])
print(result.status.value)  # "possible"
print(result.model)         # one satisfying model
print(engine.query(players[0], assumptions=[players[1]]).status.value)
```

`add_constraint(expr, label=None)` returns its unique label. `check(assumptions=())` returns a `CheckResult` with `sat`, `unsat`, or `unknown` status. `query(expr, assumptions=())` returns a `QueryResult` with `possible`, `necessary`, `impossible`, `inconsistent`, or `unknown` status. The pinned dependency is `z3-solver==4.13.0.0`.
