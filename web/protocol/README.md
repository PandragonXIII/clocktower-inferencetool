# Web 推理协议（Protocol）

本目录定义血染钟楼网页端与后台推理服务之间的**通用 JSON 接口契约**。

**本目录只定义协议，不含服务实现**；当前 HTTP 实现见 [`../../backend/README.md`](../../backend/README.md)。顶层入口 `main.py web` 默认注入真实适配器 `connector.TroubleBrewingAdapter`（运行暗流涌动求解器）；后台框架本身自带的默认适配器仍是 **placeholder（占位）**：它只回显请求标识、按 id 回显查询并把全局一致性与所有查询都判为 `unknown`，**并未做规则转换、也未运行推理引擎**。placeholder 通过 `extensions["adapter:mode"] == "placeholder"` 显式暴露。

因此：**输入结构支持不等于真实推理支持**。运行时校验会接受结构完整、语义合法的请求，但这不代表后台已经理解了其中的角色或技能。

## 目录

- `types.ts`：协议 TypeScript 类型定义（机器可读约定）。
- `examples/request.json`：请求示例（对应成功响应）。
- `examples/success.json`：成功响应示例（`consistency: "sat"`）。
- `examples/conflict-request.json`：会触发逻辑冲突的请求示例（对应冲突响应）。
- `examples/conflict.json`：逻辑冲突（不可满足）响应示例（`consistency: "unsat"`）。
- `examples/error.json`：HTTP 错误响应示例。

## 接口

### POST /api/v1/reason

无状态请求：每次携带**完整的对局快照**，服务端不保留会话状态。

请求顶层字段：

| 字段 | 说明 |
| --- | --- |
| `api_version` | 固定为 `"1.0"` |
| `request_id` | 客户端生成，响应回显，用于丢弃旧响应 |
| `game` | 对局快照：`{ id, revision, script_id, players, time }` |
| `facts` | 已知事实列表 |
| `assumptions` | 仅本次请求生效的临时假设 |
| `queries` | 查询列表，可为空 |
| `options` | 可选，如 `timeout_ms` |

`players` 每项为 `{ id, seat, name }`，`id` 为稳定输入 id。

### GET /api/v1/capabilities

简要约定，返回 `supported_fact_types`、`query_types`、`scripts`，供前端了解后台当前支持的能力。`scripts` 为**对象数组** `{ id: string; name: string }[]`（例如 `[{ "id": "trouble_brewing", "name": "暗流涌动" }]`），不是字符串数组。

`extensions` 可选，其中 `adapter:mode` 与 `adapter:accepted_fact_types` 由后台占位适配器提供：`adapter:mode == "placeholder"` 表示尚未接入真实推理引擎；`adapter:accepted_fact_types` 列出运行时校验目前接受的**结构类型**（注意这只是输入结构支持，不是真实推理支持）。注入真实适配器后 `adapter:mode` 为 `"trouble_brewing"`。

## 关键语义

### 时间

时间只有三种取值：

- `{ "phase": "setup" }`：**初始**配置阶段（游戏开始前确定的身份/阵营）。
- `{ "phase": "day", "number": n }`、`{ "phase": "night", "number": n }`（`n` 为正整数）：表示**该阶段结束时**的状态。

命题 `role`/`alignment` **必须带明确时间**；带阶段的时间必须为正整数 `number`，否则拒绝。

### 稳定 id 与引用校验

`game.id`、`player.id`、`fact.id`、`assumption.id`、`query.id` 都是稳定 id。

- **跨集合唯一**：所有稳定 id（含 `request_id`、`game.id`、`player.id`、`fact.id`、`assumption.id`、`query.id`）在**同一请求内共享一个命名空间，整体必须唯一**；任何两个集合之间重复也会被拒绝，错误码 `DUPLICATE_ID`。
- **禁止无效引用**：`proposition.player_id` 必须指向已声明的 `player.id`；`conflicts.input_ids` 必须指向本请求内的 `fact.id`/`assumption.id`/`query.id`；`rule_ids` 必须指向后台已知的规则 id。
- `revision` 必须为非负整数（`>= 0`）；`player.seat` 必须为 `1..N` 的整数（`N` 为玩家数）且不重复；所有数值字段必须是整数，布尔值 `true`/`false` 不算整数。
- `time.number` 必须为正整数；命题的时间不得晚于 `game.time`。`time.phase` 只能取 `setup`/`day`/`night`，`setup` 不允许带 `number`。
- 脚本角色 `role_id` 目前**只做非空字符串校验**，不校验其是否属于该脚本；脚本规则校验尚未实现。

### facts：confirmed 与 reported

- `status: "confirmed"`：**硬约束**。例如自己确认的真实身份、自己技能读到的结果。
- `status: "reported"`：**玩家声明**，来源是玩家自述而非客观确认。启用（`enabled: true`）后作为**可撤销的推理假设**参与本次推理，而不是永久硬约束；玩家可以在下一次请求里撤销或改为 `enabled: false`。玩家声称的身份不等于其真实身份（角色声明在当前模型里对应「自认身份」，见下）。
- `enabled: false`：该条事实不参与本次推理。

**角色声明与真实身份必须区分**：声明用 `status: "reported"`，确认的身份用 `status: "confirmed"`；二者的来源不同，`reported` 只表示玩家这样声称，并不表示客观为真。

### confirmed 技能观察 ≠ 真实身份

`status: "confirmed"` 只是“玩家确认该观察结果”，**不等于该观察反映真实身份**。技能读数可能被**醉酒 / 中毒**等效果扭曲，因此 confirmed 的技能观察（如占卜师读到的阵营）只能作为**带前提的约束**，不能直接当作世界真实身份。后台需要按脚本规则把“观察者状态（醉酒/中毒）”纳入约束，才能由观察推出实际配置。

### 命题

命题分为 `role` 和 `alignment`：

- 角色用 `role_id` 表示，**不固定枚举**，具体取值由 `script_id` 决定。
- 阵营用 `alignment`（`good`/`evil`）。

### 扩展与拒绝策略

扩展类型与扩展字段使用**命名空间 + 冒号**前缀（`` `${命名空间}:${类型}` ``），避免与核心字段冲突：

- `type`：核心为 `"role"` / `"alignment"`（必须与 `proposition.kind` 一致）；扩展形如 `"acme:custom"`，用 `data` 承载载荷。
- `extensions`：形如 `{ "acme:note": "..." }`。

**版本与类型拒绝策略**：

- `api_version` 不是 `"1.0"`：返回 HTTP 错误（不受支持的协议版本）。
- 未知且活跃（`enabled = true`）的事实/命题类型：返回 HTTP 错误，**不得静默忽略**；`enabled = false` 的未知类型可忽略。

#### 已知扩展事实的 `data` 形状

后台当前已识别三类 BOTC 扩展（见 `types.ts` 中 `AbilityObservationData` / `NightDeathsData` / `DayVoteData`，它们只是文档性注解，不改变 `ExtensionFact.data: JsonValue` 的开放结构）：

| `type` | `data` 摘要 |
| --- | --- |
| `botc:ability_observation` | `time`（day/night + 正数）、`actor_id`、`role_id`、`targets`，以及 `result.kind`（`unobserved`/`no_outsiders`/`no_direct_result`/`role`/`number`/`text`/`choice`）与对应字段。 |
| `botc:night_deaths` | `time`（night）、`player_ids`、`result`（`deaths`/`none`）。 |
| `botc:day_vote` | `time`（day）、`stage`（`voting`/`settled`）、`execution.player_id`（可为 `null`），可选 `nominations` 等记录字段。 |

约定：

- **`enabled: false` 不解析 `data`**：可保存任意草稿。
- **结构非法或引用不存在**（未知玩家/角色、时间晚于 `game.time`、字段类型错误）返回 `400`。
- **结构合法但当前模型不支持**返回 `422`，例如未结算投票（`stage: "voting"`）、首夜死亡、转换层未支持的角色观察。`422` 不是格式错误，不代表已支持。
- 未结算的投票、前端未完成记录等应以 `enabled: false` 保存。

### assumptions

临时假设**仅在本次请求内生效**，不影响持久化的对局信息；用于“如果 X 成立会怎样”的推演。

### queries 与查询状态

- `queries` 每项有**显式 `id`**，响应按 `id` 回显。
- 单条查询状态语义：

| 状态 | 含义 |
| --- | --- |
| `possible` | 在 base（含规则、confirmed facts、assumptions、启用的 `reported` 角色声明假设）下，命题**可满足**且**非必然**（存在满足解使其为真，也存在满足解使其为假）。 |
| `necessary` | 命题在 base 的**所有**满足解中为真。 |
| `impossible` | 命题在 base 的**所有**满足解中为假（其否定必然）。 |
| `inconsistent` | **base 本身不可满足**（全局 `unsat`），因此命题无从谈起。 |
| `unknown` | solver 超时或返回未知；**保守判定**，不臆断真/假。 |

- **`queries` 为空时**：仅做整体一致性检查，`results` 为空数组。
- **`unknown` 是保守结论**：超时/未知时不可向上取整为 `possible`/`necessary`/`impossible`。
- **逻辑 `unsat` 与单查询 `inconsistent`**：当 base 全局不可满足时，全局 `consistency = "unsat"`，各查询状态为 `inconsistent`。

### 响应

响应回显 `request_id`、`game_id`、`revision`，客户端据此**丢弃旧响应**。`revision` 为整数且 `>= 0`，与请求一致。

- `consistency`：全局一致性，取值 `sat` / `unsat` / `unknown`。全局判定包含**规则约束、confirmed facts、assumptions，以及启用的 `reported` 角色声明假设**（`reported` 启用后即作为本次推理必须满足的假设计入）。
- `reason`：可选。全局 `consistency = "unknown"` 时给出原因说明。
- `conflicts`：`unsat` 时给出，含 `input_ids`（指向请求内 id）和 `rule_ids`（指向规则 id）。这是一组有用的冲突集，**不保证是最小冲突集**。
- `model`：业务 JSON，**仅当 `consistency = "sat"`** 时给出，表示一个满足解。`model` **不代表唯一解、不含概率，也不是各查询各自的见证（witness）**；它只是满足 base 的某一个赋值，与某条查询为真/假无逐一对应关系。每个 assignment 带 `time`。

- **assumption 冲突归因**：由 assumptions 引起的冲突，`input_ids` 应包含对应的 assumption id。判断某次求解失败是否源于 assumption，需要后台**在 adapter 层跟踪每次 solve 实际加入了哪些 assumption**，不能仅凭全局结果。

### HTTP 错误 vs 逻辑 unsat

**HTTP 错误不等于逻辑不可满足（unsat）**。逻辑 `unsat` 是正常的推理结论，返回 **2xx**（如 `200 OK`）响应体（`consistency: "unsat"`）。

HTTP 错误使用标准的 `4xx` **状态码**：

| 状态码 | 场景 |
| --- | --- |
| `400 Bad Request` | JSON 格式错误、重复 JSON 键、`NaN`/`Infinity`、类型错误、重复 id、无效引用、未知且活跃类型、不支持的 `api_version`。 |
| `404 Not Found` | 未知 API 路径（其他路径回退到静态文件服务）。 |
| `405 Method Not Allowed` | 路径存在但方法不支持；响应带 `Allow` 头指明允许的方法（如 `/api/v1/reason` 仅 `POST`，`/api/v1/capabilities` 仅 `GET`）。 |
| `408 Request Timeout` | 读取请求体超时。 |
| `411 Length Required` | 缺少 `Content-Length`（不接受 `Transfer-Encoding`）。 |
| `413 Payload Too Large` | 请求体超过 1 MiB。 |
| `415 Unsupported Media Type` | `Content-Type` 不是 `application/json`。 |
| `422 Unprocessable Entity` | 结构合法但语义无法处理（如后台无法处理该脚本）。 |
| `500 Internal Server Error` | 服务内部错误（适配器抛异常）。 |

HTTP 错误响应体：

```json
{
  "api_version": "1.0",
  "request_id": "req-0003",
  "error": {
    "code": "INVALID_REFERENCE",
    "message": "fact 'f-claim-p2' references unknown player_id 'p99'",
    "path": "/facts/1/proposition/player_id"
  }
}
```

`path` 为 **JSON Pointer**（RFC 6901），**必选**，指向出错位置，例如 `/facts/1/proposition/player_id`。

### 当前 HTTP 实现与框架行为

当前实现位于 [`../../backend/`](../../backend/README.md)，基于 Python 标准库 `http.server`，同一进程内提供静态 UI 与 `/api/`：

- 路由：`GET /api/v1/capabilities`、`POST /api/v1/reason`；其余 `/api/` 路径 `404`，方法不符 `405` 并带 `Allow` 头。
- 请求体：要求 `Content-Type: application/json` 与单个十进制 `Content-Length`；拒绝 `Transfer-Encoding`；超过 1 MiB 返回 `413`；读取超时 `408`。
- 解析：拒绝重复 JSON 键与 `NaN`/`Infinity`（`INVALID_JSON`）。
- 错误与逻辑结论分离：校验/服务失败返回 `4xx`/`5xx` 且带 `error` 对象；逻辑 `unsat` 是 `200` 正常响应。`ApiError`（协议错误）与 HTTP 传输错误是两回事。
- 未知 API 路径之外的路径交给静态文件服务（`web/`），因此直接用 `python -m http.server` 只提供静态文件、**不含 API**；`python main.py web` 才同时提供 UI 与 API（默认注入真实适配器）。

### 拒绝的情况

- 重复 id（跨集合共享命名空间，玩家、事实、假设、查询、对局、request_id 之间重复均拒绝）。
- 无效引用（如 `player_id` 指向不存在的玩家）。
- 非法数值（非整数、布尔冒充整数、小数、负的 revision 或阶段号）。
- 未知且活跃（`enabled = true`）的事实/命题类型；`enabled = false` 的未知类型可忽略。
- 不支持的 `api_version`。

以上均返回 HTTP 错误，而非逻辑 unsat。

### timeout_ms

`options.timeout_ms` 为**每次 solve** 的超时（正整数），不是整体请求预算。一次请求可能执行多次 solve（base 一致性、查询可能、查询否定等）。

## 示例配对

- `examples/request.json` ↔ `examples/success.json`：请求中 `f-p3-evil` 确认 p3 阵营为 evil，查询“p5 是否 good”在 base 下必然为真，故响应 `q-p5-alignment.status = "necessary"`。model 中 p3 = poisoner/evil、p4 = imp/evil、p5 = washerwoman/good，满足“一名恶魔”等规则，且 **p5 并非恶魔**，与查询一致。
- `examples/conflict-request.json` ↔ `examples/conflict.json`：在 `request.json` 基础上，加入与 `f-self-role` **同一时间、同一玩家 p1、不同角色**的 confirmed 事实 `f-p1-other-role`（soldier）。p1 在 setup 既 empath 又 soldier 违反 `tb:one_role_per_player`，全局 `unsat`，查询状态为 `inconsistent`，冲突指向两条输入与该规则。

## 与其他目录的关系

- 推理内核接口见 [`../../engine/README.md`](../../engine/README.md)。
- 当前 HTTP 实现见 [`../../backend/README.md`](../../backend/README.md)：顶层入口 `main.py web` 默认注入真实适配器 `connector.TroubleBrewingAdapter`，对 `examples/request.json` 返回示例描述的 `sat`/`necessary`；框架默认 placeholder 适配器（直接调用 `create_server()` 时）则返回 `consistency: "unknown"`。
- 本协议描述的是网页/后台契约，后台实现需自行完成运行时校验（TypeScript 类型无法在运行时校验）。

## 示例

- 请求：[`examples/request.json`](examples/request.json)
- 成功：[`examples/success.json`](examples/success.json)
- 冲突请求：[`examples/conflict-request.json`](examples/conflict-request.json)
- 冲突：[`examples/conflict.json`](examples/conflict.json)
- 错误：[`examples/error.json`](examples/error.json)
