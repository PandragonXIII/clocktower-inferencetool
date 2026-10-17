# botc_reasoner：暗流涌动 Z3 规则模型

`botc_reasoner/` 是《暗流涌动》（Trouble Brewing）的**直接 Z3 模型**：它把角色、配置、时间轴、中毒/醉酒、夜间击杀、白天处决等规则写成 Z3 布尔约束，并提供声明变量、装载规则、查询可满足性的 Python 接口。

> **它不调用 `engine.ReasoningEngine`。** `engine/` 是通用 Z3 约束封装；本目录完全绕过它，直接用 `z3-solver` 建模暗流涌动。两者没有依赖关系。
>
> **`connector.py` 才是 JSON 桥。** 网页协议 JSON → Z3 命题 → 推理结果这条链路在仓库根目录的 `connector.py`，不在本目录。本目录只提供模型与规则。参见[与 connector.py 的关系](#与-connectorpy-的关系)。

## 定位与关系

```text
web/ 前端 ──POST /api/v1/reason──► backend/http_server.py ──校验──► connector.TroubleBrewingAdapter
                                                                          │  使用
                                                                          ▼
                                                        botc_reasoner/  ← 直接 Z3 建模（本目录）
```

| 组件 | 作用 | 是否调用 engine |
| --- | --- | --- |
| `botc_reasoner/`（本目录） | 暗流涌动变量与规则，直接 Z3 | 否 |
| 根 `connector.py` | 网页协议 JSON ↔ 模型 ↔ 响应；也能独立起服务 | 否（直接用 botc_reasoner） |
| `engine/` | 通用 Z3 约束/查询封装，不含 BOTC 规则 | — |
| `backend/` | HTTP 路由与运行时校验，适配器可注入；框架默认 placeholder 时不使用任何求解器，`main.py web` 注入本目录的真实适配器 |

## 文件分工

| 文件 | 职责 | 是否依赖 Z3 |
| --- | --- | --- |
| `roles.py` | 22 个官方角色、四类分组、中文名/能力说明、5–15 人官方配置表 `BASE_SETUP`、男爵修正 `setup_counts`、示例局、建模裁决 `MODELING_NOTES`、自检 `validate_catalog` | 否 |
| `variables.py` | 声明全部布尔未知量（身份、自认、存活、状态、夜间行动、技能发动、死亡、提名投票、误注册）及**域公理**；`TroubleBrewingVars`、`declare_variables`、`Moment`、`Ability`、`Query`、`build_solver` | 是 |
| `rules.py` | 把暗流涌动规则写成约束：`add_setup_rules`（人数/男爵）、`add_game_rules`（装载当前已实现规则）、私有辅助函数 `_add_information` 等 | 是 |
| `conflict.py` | `minimal_unsatisfiable_subset`：从输入命题中抽取**极小（不可再删）**不可满足子集 | 是 |

职责边界：
- `roles.py` 只放静态事实，不建约束。
- `variables.py` 只声明「未知量是什么形状」（每位玩家每断面恰好一个角色、每次行动恰好一个目标等），**不含剧本规则**。
- `rules.py` 才连接真实身份、自认、中毒、死亡与信息结果。
- `connector.py` 负责把外部 JSON 的命题映射到上述变量（`start_is` / `belief_bit` / 扩展事实）。

## 时间与座位约定

**时间断面**（`Moment`）：
- `Moment.NIGHT_START`（`night_start`）：第 k 夜入夜，投毒者/僧侣/间谍看到的身份。
- `Moment.DAWN`（`dawn`）：第 k 夜黎明，共情者/占卜师/守鸦人/送葬者看到身份。
- `Moment.AFTER_LAST_DAY`（`after_last_day`）：最后一天全部结算之后（处决 + 猎手 + 红唇女郎转化）。

第 k 天结束 = 第 k+1 夜入夜（`role_after_day` / `alive_after_day` 复用同一布尔量，最后一天则用 `role_end` / `alive_end`）。首夜没有恶魔击杀，因此没有 monk / imp / starpass / mayor_bounce / night_death 的第 1 夜变量。

**座位**：
- **内部为 0-based**：`player_ids = 0..n-1`，`world.left(0) = n-1`、`world.right(0) = 1`，圆桌相邻按 `(i±1) % n` 计算。
- **外部为 1-based**：网页协议 `player.seat` 是 `1..N`，`test_reasoning.py` 的玩家编号从 1 开始。`connector._seats` 做 `seat - 1` 转换。

**人数**：官方配置表覆盖 **5–15 人**；`setup_counts(16)` 会抛 `ValueError`（16–20 人需要旅行者，未建模）。`variables.MAX_PLAYERS = 20` 只是变量声明的上限，不代表完整规则支持 20 人。男爵在场时镇民 -2、外来者 +2（`add_setup_rules` 自动判断男爵是否在场，不需要调用方额外传参）。

## 公共 Python API

从 `botc_reasoner` 顶层可导入：`declare_variables`、`add_game_rules`、`add_setup_rules`、`minimal_unsatisfiable_subset`、`Role`、`Moment`、`Ability`、`Query`、`QueryKind`、`BASE_SETUP`、`setup_counts`、`role_from_name`、`ROLE_ZH` 等（完整列表见 `__init__.py` 的 `__all__`）。`validate_catalog` 从 `botc_reasoner.roles` 导入。

最小可运行示例（5 人局，1 夜）：

```python
from z3 import Not, sat, unsat
from botc_reasoner import Role, add_game_rules, declare_variables
from botc_reasoner.roles import BASE_SETUP

world = declare_variables(5, n_nights=1)          # 声明变量
solver = world.build_solver()                      # 求解器 + 域公理
add_game_rules(solver, world, *BASE_SETUP[5])      # 装载暗流涌动规则；BASE_SETUP[5] == (3, 0, 1, 1)
assert solver.check() == sat

# 角色条件检查
solver.push(); solver.add(world.start_is(0, Role.IMP))
print(solver.check())                              # sat：玩家 0 可以是小恶魔
solver.pop()

solver.push(); solver.add(world.start_is(0, Role.IMP), world.start_is(1, Role.IMP))
print(solver.check())                              # unsat：不满足「全局至多一名小恶魔」
solver.pop()

# 查询语义：分别尝试命题与其否定
q = world.start_is(0, Role.CHEF)
solver.push(); solver.add(q);        positive = solver.check(); solver.pop()
solver.push(); solver.add(Not(q));   negative = solver.check(); solver.pop()
# positive=sat 且 negative=sat   → possible
# positive=sat 且 negative=unsat → necessary
# positive=unsat 且 negative=sat → impossible
```

- `declare_variables(n_players, n_nights=None, *, max_nominations=None, tag="tb")`：同一 Z3 上下文里相同 `tag` 复用同名变量；同时建两局请用不同 `tag`。`n_nights` 默认等于人数。
- `world.build_solver()` 只放入域公理；剧本规则必须再调用 `add_game_rules`。
- `world.is_role/is_alive/believed_role(player, ..., moment, night)`、`world.start_is`、`world.believes_at_start`、`world.role_after_day`、`world.alive_after_day`、`world.is_droisoned` 是主要读写入口。

自检（会打印变量统计，通过则 exit 0）：

```sh
.venv/bin/python -m botc_reasoner.variables   # 变量域公理自检
.venv/bin/python -m botc_reasoner.rules       # 规则自检
.venv/bin/python -c 'from botc_reasoner.roles import validate_catalog; validate_catalog()'
```

`-m` 方式会因包已导入而出现 `runpy` RuntimeWarning，属正常现象，不影响结果。

## 文本推理工具

`test_reasoning.py`（仓库根）是**交互式命令行工具**，不是单元测试，也不被 `python main.py test` 收集（后者只发现 `tests/` 下的测试套件）。先输入 `c/f/h/d`（如 `5/1/1/1`），再逐行输入中文命题（`身份`、`自认`、`夜间死亡`、`处决`、`发动 …` 等），空行结束。运行：

```sh
.venv/bin/python test_reasoning.py
```

## connector.py 使用（真实 HTTP 接口）

`connector.py` 是**真正运行本模型**的入口，有两条路径：

**1. 命令行求解一份请求 JSON（不走 HTTP 校验）：**

```sh
.venv/bin/python connector.py web/protocol/examples/request.json
```

它直接读取 JSON、构造 `TroubleBrewingAdapter.reason()` 并打印响应。
注意：**该路径不经过 `backend.validation`**，不提供完整的协议校验；部分非法输入会得到 `unknown`，另一些会抛异常退出。

**2. 启动网页 + 真实推理 API（HTTP 会先做运行时校验）：**

```sh
# 推荐：顶层入口，默认注入真实适配器
.venv/bin/python main.py web --port 8000
# 兼容入口，行为相同
.venv/bin/python connector.py serve --port 8000
# 或 .venv/bin/python connector.py --serve --port 8000
```

此时 `POST /api/v1/reason` 先经 `backend.validation.validate_request`，再交给 `TroubleBrewingAdapter`。两条路径的差异：CLI 无校验、HTTP 有校验；求解逻辑相同。

> 只有后台框架自带的默认适配器（直接调用 `create_server()` 且不传 adapter）才是 **placeholder**，未运行本模型。`main.py web` 与 `connector.py serve` 都使用真实适配器。

## 支持范围与输出语义

**已建模**：开局人数与男爵、酒鬼自认与标记、占卜师干扰项、恶魔三个不在场伪装、中毒/醉酒、身份与存活延续、恶魔夜间击杀（含僧侣保护与健康士兵免疫）、星坠（小恶魔自杀传给存活爪牙）、红唇女郎转化、猎手、贞洁者、投票处决、以及健康角色收到的信息（洗衣妇/图书管理员/调查员/厨师/共情者/占卜师/送葬者/守鸦人），含间谍/陌客的逐次误注册。

**未建模**：**圣徒处决落败、镇长三人获胜等游戏结束判定**不在 `add_game_rules` 中。镇长的夜间死亡转移已建模，不能与获胜条件混淆。**只有暗流涌动**，没有旅行者、没有其他剧本。这里列出的是代码覆盖范围，不代表全部规则都经过完整的对局验证。

`connector` 响应语义：
- `consistency`：`sat` / `unsat` / `unknown`。**不是**概率，也不是枚举全部解。
- `model.assignments`：一个**满足解**，不代表唯一解或真实情况。
- `extensions["trouble_brewing:possible_roles"]`：按玩家枚举「初始配置下仍可满足的角色」。这是**初始候选**，不是当前角色，也不是概率。
- 单条查询状态 `possible` / `necessary` / `impossible` / `inconsistent` / `unknown`（逐 query 两次求解：命题与其否定）。

## 声明与启用开关

`reported` role 命题在 `connector._proposition_expr` 中映射为**自认身份**（`_belief_bit`），即「该玩家认为自己是什么角色」，而非真实身份。`rules._add_opening_secrets` 约束非酒鬼的自认等于真实身份，酒鬼的自认由 `drunk_mask` 决定，可能与真实身份不同。因此启用一条 `reported` role 声明，等于**在本次推理中要求该自认成立**：对非酒鬼即该真实角色，对酒鬼则按其自认角色求解。声明开启后必须满足，由此推出的冲突是正常结论而非缺陷（例如恶魔自认士兵时，该自认与真实身份约束不相容会得到 `unsat`）。若要表达「不采信某条声明」，用 `enabled:false` 把它排除在本次推理之外，而不是期待它自动降级为软信息。

`alignment` 命题目前**直接约束真实阵营**（`_proposition_expr` 的 alignment 分支返回真实角色集合的 `Or`，未区分 `reported`）。即声明阵营会被当作真实阵营约束。这与角色声明的「自认」语义不同；二者是否统一、`reported` alignment 是否应改为软信息，**待产品明确**，此处不判定为缺陷。

## 当前限制 / 待修正（先读）

以下问题来自代码审阅及针对性验证，尚无完整对局的集成测试覆盖。它们不是设计意图。行号易变，以函数名为准。

1. **CLI 的能力输入可能静默丢弃或缺少校验**（`connector._ability`）：如占卜师目标不足两人，分支未匹配会返回 `None`；厨师分支本身不检查是否首夜。HTTP 路径通过 `backend.extension_validation` 拦截此类格式错误和不支持的观察，但 CLI 直接调用连接器不经过这些检查。`kind == "unobserved"` 是合法的「无观察结果」，两条路径都刻意不生成约束。

2. **未知引用可能 `KeyError`**：`connector._night_deaths` / `_execution` 用 `seats[player_id]` 直接索引，未知玩家抛 `KeyError`；`_ability` 只捕获 `ValueError`，而 `role_from_name` 对未知 `role_id` 抛 `KeyError`，同样逃逸。`_reason` 只捕获 `ValueError`，最终在 HTTP 层变成 **500**。HTTP 路径会先经 `backend.extension_validation` 拦截未知玩家/角色，但 **CLI 路径不校验**，仍可直接触发。

3. **候选角色枚举提前停止且无完整标志**（`connector._possible_roles` 的 `while solver.check() == sat`）：一旦某次求解返回 `unknown`，循环直接结束，**不标记候选集不完整**，会得到看似完整的错误候选列表。

4. **冲突异常未捕获可致 HTTP 500**（`connector._reason` 的 `unsat` 分支在 `try` 之外调用 `minimal_unsatisfiable_subset`）：该函数背景不可满足时抛 `ValueError`、超时抛 `TimeoutError`，均未捕获，会在 HTTP 层变成 **500**。另注意它返回的是**极小（不可再删）子集，不是最少条数子集**（`conflict.py` 文档已说明）。

HTTP 的三类已知扩展由 `backend.extension_validation` 校验，`enabled:true` 的受支持数据可正常提交：结构非法或引用错误返回 `400`，当前模型不支持的组合返回 `422`。`enabled:false` 仅供记录、不解析载荷、不参与求解。`capabilities.scripts` 使用协议规定的 `{ id, name }` 对象数组；声明某类输入受支持不代表该类所有角色和结果组合都已建模。

性能相关（非缺陷，但需知晓）：每条 query 两次求解；候选枚举对每名玩家反复求解；`TroubleBrewingAdapter` 用实例锁 `self._lock` 串行化所有请求；`options.timeout_ms` 是**每次 solve** 的超时，不是整体请求预算。

## 扩展事实 data 格式（按 connector 实际实现）

三类扩展由 `connector._extension_expr` 分发，只读取下列字段；其余字段被忽略。**`enabled:false` 的事实（核心与扩展一律）不参与本次推理**，其 `data` 不会被解析。经 HTTP 提交的 `enabled:true` 已知扩展会先由 `backend.extension_validation` 做结构与部分语义校验（见 [backend/README.md](../backend/README.md#扩展事实校验extension_validationpy)）：结构非法/引用错误为 `400`，当前模型不支持的组合为 `422`；CLI 路径不校验。

| `type` | 说明 | connector 读取的 `data` 字段 |
| --- | --- | --- |
| `botc:night_deaths` | 某夜公布的死亡 | `time.phase == "night"`、`time.number >= 2`、`player_ids`（死亡玩家 id）、`result`（`"none"` 表示无人死亡） |
| `botc:day_vote` | 白天处决结算 | `stage == "settled"`、`time.phase == "day"`、`time.number >= 1`、`execution.player_id`（无人处决为 `null`） |
| `botc:ability_observation` | 技能观察 | `actor_id`、`role_id`（决定走哪个分支）、`time`（`phase`/`number`）、`targets`、`result.kind`、`result.value`、`result.role_id` |

例：

```json
{
  "id": "f-night-deaths-1",
  "type": "botc:night_deaths",
  "status": "confirmed",
  "enabled": true,
  "data": {
    "time": { "phase": "night", "number": 2 },
    "player_ids": ["p1", "p2"],
    "result": "deaths"
  }
}
```

`botc:ability_observation` 的分支由 `role_id` 决定（不是 `ability_id`），例如 `role_id:"chef"` 配 `result:{kind:"number",value:N}`；`role_id:"fortune_teller"` 配 `targets` 与 `result:{value:"yes"|"no"}`。转换层 `connector._ability` 只对已建模的角色/结果组合生成约束，`result.kind == "unobserved"` 明确表示无观察结果，**刻意不生成约束**；它不会为此报错。

`botc:day_vote` 在转换层（`connector._execution`）只识别 `stage:"settled"`，`voting` 会返回 `None`（不生成约束）。经 HTTP 提交时，活跃（`enabled:true`）的未结算投票会被校验层以 `422 UNSUPPORTED_OBSERVATION` 拒绝，应改为 `enabled:false` 保存。`nominations`、`alive_count`、`threshold` 等字段仅作记录，当前不参与规则推理；处决判定只读取 `execution.player_id`。

## 相关文档

- 项目总览：[../README.md](../README.md)
- JSON 桥与 CLI/HTTP：[../connector.py](../connector.py)（使用说明见本页）
- 通用推理引擎：[../engine/README.md](../engine/README.md)
- 后台/协议：[../backend/README.md](../backend/README.md)、[../web/protocol/README.md](../web/protocol/README.md)
