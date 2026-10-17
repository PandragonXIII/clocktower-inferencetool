# 约束推理引擎

`ReasoningEngine` 是一个面向 Z3 布尔约束与 SMT 约束的通用 Python 接口。它存储带标签的基础约束、检查可满足性，并测试某个查询是可能、必然还是不可能。若基础约束相互矛盾，则报告为 `inconsistent`。检查和查询都接受临时假设，这些假设不会修改已存储的约束。

不可满足（unsatisfiable）的结果会包含来自 Z3 unsat core 的标签；这是一个有用的冲突子集，但不保证是最小的。SAT 结果会包含一个 Z3 model。UNKNOWN 结果在可用时会包含 Z3 给出的原因。该引擎不会枚举所有可满足的 model，也不编码任何 BOTC 专属规则。

每个单独 Z3 求解的默认超时为 1000 ms。一次查询可能运行多次求解（基础一致性、查询可能、查询取反），因此这是每次求解的超时，而不是一次查询的总预算。可通过 `ReasoningEngine(timeout_ms=...)` 配置；该值必须为正整数。

## 安装与运行

在仓库根目录下：

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python main.py test
python main.py demo
```

## Python 接口

```python
from z3 import Bool, PbEq
from engine import ReasoningEngine

players = [Bool(f"demon_{i}") for i in range(5)]
engine = ReasoningEngine()
engine.add_constraint(PbEq([(player, 1) for player in players], 1), "one_demon")

result = engine.query(players[0])
print(result.status.value)  # "possible"
print(result.model)         # 一个可满足的 model
print(engine.query(players[0], assumptions=[players[1]]).status.value)
```

`add_constraint(expr, label=None)` 返回其唯一标签。`check(assumptions=())` 返回一个 `CheckResult`，其状态为 `sat`、`unsat` 或 `unknown`。`query(expr, assumptions=())` 返回一个 `QueryResult`，其状态为 `possible`、`necessary`、`impossible`、`inconsistent` 或 `unknown`。所固定的依赖为 `z3-solver==4.13.0.0`。
