# 测试说明

`tests/` 下有引擎、后端、连接器、扩展校验、入口五个套件，均由顶层 `main.py test` 统一运行。

## Engine 测试（`test_engine.py`）

覆盖通用推理引擎的可满足性、身份查询结果（可能/必然/不可能/前提矛盾）、冲突标签、临时假设隔离、tracker 变量名冲突、自动标签、超时参数校验。

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
