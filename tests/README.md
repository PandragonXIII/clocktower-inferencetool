# 测试说明

`test_frontend_conditions.py` 使用前端实际记录形状验证四类扩展，检查全局缺席进入真实求解器、目标选择的健康守卫、存活负结果、酒鬼标记和提名／投票槽；`test_extension_validation.py` 另通过真实 HTTP 验证全局假设进入条件层并产生正常 unsat。

## 概率适配器测试（`test_probability_adapter.py`）

覆盖 `botc_reasoner.probability_adapter.analyze_probabilities` 与连接器的开关语义，mock `estimate_role_probabilities` 以避免实际抽样：

- **public 硬条件 + conditional 软采信**：public 输入在每个组合的 solver 中都存在；conditional 输入按 `owner_id` 分组（无归属各自成组），每组以 0.7 伯努利采信并枚举组合，权重为 `0.7^采信 × 0.3^忽略`，结果按权重归一化。测试验证采信/忽略两个组合都被调用、概率约为 0.7/0.3，且 `hard_input_ids`/`soft_input_ids`/`conditioning`/`credibility`/`groups` 回显正确。
- **矛盾输入仍可估计**：同一归属组内的矛盾 role/alignment 表达式、跨组的 role/alignment/global 矛盾（如 `BoolVal(False)`）只让相应组合权重为 0，剩余组合继续估计，`status` 为 `estimated`，不会因 conditional 冲突报 `inconsistent`。
- 估计返回 `None` 或抛 `ProbabilityIncomplete` 时结果保持 `unknown`（绝不标 `impossible`）并带 `reason`。
- **public 背景 `unsat`** 报 `inconsistent` 且不调用估计器。
- `rows` 回显每位玩家的 `player_id`/`seat` 与角色 id 字符串。
- 关闭或缺少 `probability_mode` 时不导入/调用适配器；开启时按 `probability_timeout_ms`/`timeout_ms` 构造 `Budget` 并回写 `reasoner:probabilities`（mock `connector.analyze` / `_prepare_context` / `_projection`）。
- `backend.validation`：`probability_mode` 必须为布尔，`probability_timeout_ms` 必须是 `1..300000` 的整数（布尔拒绝）；连接器默认 `120000`，可被显式值覆盖。
- `test_extension_validation.py` 的真实 HTTP 概率用例把五条全钉身份标为 `reasoner:scope:"public"`，验证唯一组合、`estimated`、每行归一化且钉定角色为 1.0。

`tests/` 下的测试均由顶层 `main.py test` 统一运行。

## 概率推理小 benchmark（`benchmark_probability.py`）

可复现的性能脚本，**不是 unittest**，也不 mock 连接器或求解器：它用 `create_server(..., adapter=TroubleBrewingAdapter())` 在 `127.0.0.1` 的随机端口启动线程，通过 `urllib` 以 120 秒读取超时向真实 `/api/v1/reason` 发送同一份 5 人请求。输入含 5 条启用的 `reported` 角色声明（p1 与 p3 都自称厨师，全部采信时与角色唯一性冲突），无查询；两次请求只有概率开关不同，选项均为 `timeout_ms=10000`、`total_timeout_ms=8000`、`probability_timeout_ms=120000`。脚本打印每轮的 `timings`、`consistency`、概率 `status`、`groups` 与按角色排序并保留 4 位小数的 `rows`（附每行概率和）；超过 120 秒时该轮记为 `unknown`（超时不是逻辑结论）。

```sh
.venv/bin/python tests/benchmark_probability.py
```

本机实测（一次代表运行，耗时随机器/负载变化）：

| 轮次 | consistency | 概率 status | groups | HTTP 总耗时 | build_ms | analysis_ms | probability_ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `probability_mode:false` | `unsat` | 未请求 | — | 2.324 s | 969.6 | 1303.4 | 0.0 |
| `probability_mode:true` | `unsat` | `estimated` | total 32 / checked 32 / estimated 24 / complete true | 4.808 s | 877.3 | 940.8 | 2981.6 |

两轮逻辑结果都是 `unsat`（两名厨师声明不能同时为真）；概率模式仍按组合排除矛盾并给出 `estimated`，每行概率和为 1，未出现超时或 `unknown`。

双层分析与来源测试见 `test_analysis.py`、`test_inputs.py`、`test_provenance.py`；预算及元数据校验见 `test_analysis_validation.py`；最少撤回和联合投影枚举见 `test_repairs.py`、`test_worlds.py`。覆盖公共结论不受条件冲突污染、unknown 不误排身份、最优代价与方案完整性分开、public 不撤回以及投影去重。`test_analysis.py` 的 `ProbabilityModePipelineTests` 另验证概率模式下 `pipeline.analyze` 跳过 `diagnose` 与 `role_ranges`，但保留显式查询、`max_repairs` 修复、`max_worlds` 世界枚举，以及真实 `unsat` 的 `consistency`/`results` 与修复结论。

## 推理模型 smoke 测试（`test_reasoner_smoke.py`）

对直接 Z3 模型 `botc_reasoner` 的少量有意义检查，替代已删除的通用 `engine` 测试：

- 角色目录自检 `validate_catalog()` 通过、`BASE_SETUP` 覆盖 5–15 人且每档恰好一名恶魔。
- 5 人局装载 `add_game_rules` 后可满足，且两名玩家同为厨师为 `unsat`（角色唯一性）。
- `main.run_demo` 实际运行返回 `0`。

`botc_reasoner` 的完整规则自检见其自身 `-m` 入口（`botc_reasoner/README.md`）。

## Connector 测试（`test_connector.py`）

覆盖 `connector._fact_expr` 对 `enabled` 的开关语义：**先看 `enabled:false` 再分派 type**。用 5 人局声明变量与域公理验证（不装载 `add_game_rules`、不做全模型求解，保持快速）：

- 三种扩展（`botc:night_deaths` / `botc:day_vote` / `botc:ability_observation`）禁用时**不调用** `_extension_expr`、不产生 proposition，且与「事实缺省」结果相同；非法 payload（未知玩家/角色）禁用时不抛异常。
- 同样三种扩展启用时确实调用 `_extension_expr` 并产生带 label 的约束。
- 经真实 `_prepare` 的 5 人局：禁用夜间死亡不进 labels、启用进；混合时只保留启用项。
- **开关而非镜像**：启用夜间死亡与禁用「无人死亡」的 payload 直接组合为 `unsat`，混合请求仍 `sat`，证明禁用项是被真正跳过而非 payload 平凡。
- 既有 core fact（`role`）的 `enabled` 处理保留。
- `_horizon` 现状记录：禁用事实的时间仍会扩大声明的模型（本次不修）。

## Backend 测试（`test_backend.py`）

- `PreparedRequestTests`：`prepare_request` 把事实分为 confirmed/reported/disabled、假设分为 enabled/disabled，结果是对输入的**深拷贝**且不修改输入，非映射输入抛 `TypeError`，缺失集合默认为空。
- `BackendHttpTests`：`setUpClass` 在**真实临时 HTTP 服务器**（`ThreadingHTTPServer`，端口 `0` 自动分配）上启动线程，`tearDownClass` 在 `finally` 语义下 `shutdown()` 并 `server_close()`。请求全部通过真实 socket（`http.client`）发出，覆盖：
  - 静态协议示例文件（不依赖网页界面）；
  - `/api/v1/capabilities` 占位能力；
  - `POST /api/v1/reason` 的 unknown 回显与空 `queries`；
  - 校验拒绝：跨集合重复 id、无效引用、布尔冒充整数、小数时间、未知且活跃扩展拒绝 / disabled 允许；
  - 传输与解析：重复 JSON 键、`NaN`、类型错误、`415`、`413`、路由 `404` 与方法 `405`（含 `Allow`）；
  - 用 `mock.patch.object(PlaceholderAdapter, "reason")` 在线模拟适配器返回 `sat`/`unsat`（均 `200`）以及抛异常（`500`）。因为适配器在调用时经类解析，单个 server 即可覆盖多种适配器行为，无需多个 server。

## 扩展校验测试（`test_extension_validation.py`）

覆盖 `backend.extension_validation` 经 `validate_request` 的三类已知 BOTC 扩展事实校验，不构建 Z3 对象、不求解模型：

- **合法**：`botc:ability_observation`（首夜厨师数字）、`botc:night_deaths`（第二夜无人死亡）、`botc:day_vote`（已结算处决含提名），以及三者同时存在。
- **拒绝（400）**：未知玩家引用、时间晚于 `game.time`、`time.number` 为布尔、结果取值越界、非法 `result` 值。
- **不支持（422 `UNSUPPORTED_OBSERVATION`）**：当前转换层不支持的角色观察（如间谍）。
- **禁用不解析**：`enabled:false` 携带任意垃圾 `data` 仍通过校验；未知 `enabled:true` 扩展仍拒绝（`UNKNOWN_TYPE`）。
- **HTTP 路径**：真实 `ThreadingHTTPServer` + 记录型适配器，验证合法扩展事实到达适配器（`200`）、不支持的观察在调用适配器前即被拒绝（`422`），故适配器不被调用。
- **能力形状**：`connector.TroubleBrewingAdapter.capabilities()["scripts"]` 为对象数组（每项含 `id`/`name`），只查形状不调用 `reason`。

## 入口测试（`test_main.py`）

覆盖顶层 `main.py` 的命令分发与 `run_web`，用 `mock.patch` 把 `backend.http_server.create_server` 替换成假服务器，避免真实监听端口：

- `run_web` 确实调用 `create_server(host, port, adapter=...)`，且注入的 `adapter` 是 `connector.TroubleBrewingAdapter` 实例（真实适配器，不是 placeholder）。
- `KeyboardInterrupt` 后走 `finally` 调用 `server_close()`；`create_server` 抛 `OSError` 时返回 `1`。
- `main([])` 默认跑测试，`test` / `demo` 分别派发到 `run_tests` / `run_demo`，`web --host --port` 正确转发参数。

## 运行

从仓库根目录运行：

```sh
.venv/bin/python main.py test
```

`main.py` 相对自身位置解析 `tests/`，因此在其他工作目录下也可运行：

```sh
cd /tmp
/home/jing/repo/hackathon/.venv/bin/python /home/jing/repo/hackathon/main.py test
```

## 模拟对局记录（`simulate-games/`）

[`simulate-games/`](simulate-games/README.md) 存放主代理主持 + 隔离代理决策的文字模拟对局，**不由** `main.py test` 运行，也**不是**推理引擎的输出或能力验证；直接阅读各局 `overview.md` 即可。当前有 [`game1-5p/`](simulate-games/game1-5p/README.md)（暗流涌动 5 人局）和 [`game2-7p/`](simulate-games/game2-7p/README.md)（暗流涌动 7 人局，两夜两昼，含恶魔继承、保护与鬼票）。五人局的 `d2.json` 是空占位，不是可用的 JSON 示例请求；七人局附 12 份逐时刻完整网页请求 JSON，校验方式见其 README。
