# Backend：网页协议 HTTP 服务

`backend/` 提供血染钟楼网页端与后台之间的 HTTP 服务，实现 [`../web/protocol/`](../web/protocol/README.md) 定义的 JSON 契约的**运行时校验**与路由，并通过**适配器（adapter）**把协议请求接到推理引擎。

框架自带的默认适配器是 **placeholder（占位）**：它回显请求标识、按 id 回显查询，并把全局一致性与所有查询都判为 `unknown`。它**没有做规则转换、也没有运行推理引擎**。这是框架占位，不代表真实推理能力。

顶层入口 `main.py web` **不使用**该占位适配器，而是注入根目录 `connector.TroubleBrewingAdapter`（真实运行暗流涌动求解器）。只有直接调用 `create_server()` 且不传 `adapter` 时才会落到 placeholder 默认值。

## 组成

| 文件 | 职责 |
| --- | --- |
| `http_server.py` | 基于标准库 `http.server` 的同源服务：提供 `web/` 静态文件与 `/api/` JSON API。 |
| `validation.py` | `POST /api/v1/reason` 的运行时校验（形状、类型、跨集合 id 唯一、引用、时间、未知类型）；对已知扩展事实委派给 `extension_validation.py`。 |
| `extension_validation.py` | 三类已知 BOTC 扩展事实（`botc:ability_observation`、`botc:night_deaths`、`botc:day_vote`）的 `data` 结构与语义校验。 |
| `errors.py` | `ApiError`：协议级 HTTP 错误（status + code + message + JSON Pointer path）。 |
| `adapter.py` | 适配器契约 `ReasoningAdapter`、请求分类 `prepare_request`、占位实现 `PlaceholderAdapter`。 |

## 运行

```sh
.venv/bin/python main.py web --host 127.0.0.1 --port 8000
```

该命令同时提供 UI 与 API（同源，无需反向代理），并默认注入**真实适配器** `connector.TroubleBrewingAdapter`（运行暗流涌动求解器）。仅静态文件可用：

```sh
python -m http.server 8000 --bind 127.0.0.1 --directory web
```

但此时 **不含 API**，点击“发送到后台”会失败（标准库静态服务通常返回 501）。

## 接口

### GET /api/v1/capabilities

框架默认占位适配器返回占位能力，`extensions["adapter:mode"] == "placeholder"` 明确表示未运行引擎：

```json
{
  "api_version": "1.0",
  "supported_fact_types": [],
  "query_types": [],
  "scripts": [],
  "extensions": {
    "adapter:mode": "placeholder",
    "adapter:accepted_fact_types": ["role", "alignment"]
  }
}
```

`adapter:accepted_fact_types` 只是运行时校验接受的**输入结构类型**，不等于真实推理支持。

### POST /api/v1/reason

无状态：每次携带完整 `game` 快照。校验通过后交给适配器的 `reason()`。

请求示例：

```sh
curl -sS http://127.0.0.1:8000/api/v1/reason \
  -H 'Content-Type: application/json' \
  --data @web/protocol/examples/request.json
```

框架默认占位适配器的响应（对 `examples/request.json`；`main.py web` 注入真实适配器后不会返回此项）：

```json
{
  "api_version": "1.0",
  "request_id": "req-0001",
  "game_id": "game-7f3a",
  "revision": 12,
  "consistency": "unknown",
  "reason": "规则转换未实现、未运行推理引擎：本适配器仅为框架占位，尚未将请求转换为约束，也未做任何一致性判断。",
  "results": [{ "id": "q-p5-alignment", "status": "unknown", "reason": "..." }],
  "extensions": { "adapter:mode": "placeholder" }
}
```

能力查询：

```sh
curl -sS http://127.0.0.1:8000/api/v1/capabilities
```

## 错误处理

- 校验或服务失败返回 `4xx`/`5xx`，响应体含 `error: { code, message, path }`，`path` 为 JSON Pointer。
- **逻辑 `unsat` 不是错误**：它返回 `200` 且 `consistency: "unsat"`。
- 传输层：缺 `Content-Length` → `411`；超过 1 MiB → `413`；非 `application/json` → `415`；读取超时 → `408`；未知 `/api/` 路径 → `404`；方法不符 → `405`（带 `Allow`）。
- 解析拒绝重复 JSON 键与 `NaN`/`Infinity`。

详见 [协议文档的“当前 HTTP 实现与框架行为”](../web/protocol/README.md#当前-http-实现与框架行为)。

## 扩展事实校验（extension_validation.py）

`validation.py` 在分发扩展事实时按 `enabled` 与是否已知分别处理：

- **已知且 `enabled: true`**：交由 `extension_validation.validate_extension_data` 校验 `data`。当前已知三类（`KNOWN_EXTENSIONS`）：
  - `botc:ability_observation`：技能观察。需 `time`（`phase`/正数 `number`）、`actor_id`、`role_id`（须为暗流涌动角色 id）、`targets`（玩家 id 数组）、`result.kind`（`unobserved` / `no_outsiders` / `no_direct_result` / `role` / `number` / `text` / `choice`）及对应字段。仅支持部分角色与结果组合，其余角色返回 `422`（见下）。
  - `botc:night_deaths`：夜间死亡。需 `time.phase == "night"`、`player_ids`（玩家 id 数组）、`result`（`"deaths"` / `"none"`，`"none"` 时列表必须为空）。首夜死亡当前返回 `422`。
  - `botc:day_vote`：白天处决。需 `time.phase == "day"`、`stage`（`"voting"` / `"settled"`）、`execution.player_id`（无人处决为 `null`），可选 `alive_count`/`threshold`/`highest_count`/`override`/`default_player_id`/`nominations`。`nominations` 仅做记录用途，不代表完整投票推理。
- **`enabled: false`**：**不解析 `data`**，任意内容均可保存（可为前端未完成草稿）。
- **未知且 `enabled: true`**：仍然拒绝，`UNKNOWN_TYPE` `400`（不静默忽略）。

### 400 非法格式 / 引用 vs 422 当前不支持

- **`400 INVALID_REQUEST` / `INVALID_REFERENCE` 等**：`data` 结构非法或引用不存在（如未知玩家、未知角色、时间晚于 `game.time`、字段类型错误、`time.number` 为布尔）。`path` 为 JSON Pointer。
- **`422 UNSUPPORTED_OBSERVATION`**：结构合法但**当前模型尚不支持**，例如：
  - `botc:ability_observation` 中 `role_id` 不在转换层已支持集合内；
  - `botc:day_vote` 的 `stage != "settled"`（投票尚未结算）——此类草稿应保存在 `enabled: false` 下；
  - `botc:night_deaths` 的首夜死亡。

`422` 表示**语义合法但本模型无法处理**，不是格式错误。校验层只判断结构与引用；是否真正产生约束仍取决于转换层，**不支持不等于已支持**。

## 适配器契约

适配器实现两个方法：

```python
class ReasoningAdapter(Protocol):
    def capabilities(self) -> dict: ...
    def reason(self, request: dict) -> dict: ...
```

`http_server.create_server(host, port, adapter=...)` 可注入自定义适配器（须线程安全/无状态）。`reason()` 收到的 `request` 已经过 `validate_request` 校验；可在内部用 `prepare_request(request)` 把请求拆分为引擎就绪的分桶（confirmed/reported/disabled 事实、enabled/disabled 假设、查询等，均为深拷贝）。

## 真实适配器入口

后台框架只提供 placeholder 默认值。**真正运行暗流涌动求解器**的适配器在仓库根目录 `connector.py`：`TroubleBrewingAdapter` 实现本页定义的 `ReasoningAdapter` 契约，通过 `create_server(..., adapter=TroubleBrewingAdapter())` 注入，因此 `HTTP 校验 → 适配器` 这条链路与持有引擎时完全一致。

推荐使用顶层入口 `main.py web`，它已自动注入该适配器：

```sh
# 启动网页 + 真实推理 API（HTTP 先经 validate_request，再交给 TroubleBrewingAdapter）
.venv/bin/python main.py web --host 127.0.0.1 --port 8000
```

`connector.py serve` 是保留的兼容入口，行为相同：

```sh
.venv/bin/python connector.py serve --port 8000
```

`connector.py` 也能直接求解一份请求 JSON（该 CLI 路径**不经过** `backend.validation`，与 HTTP 路径不同）：

```sh
.venv/bin/python connector.py web/protocol/examples/request.json
```

适配器的模型、CLI/HTTP 差异与当前限制见 [`../botc_reasoner/README.md`](../botc_reasoner/README.md)。

### 替换成真实适配器范例

```python
# backend/my_adapter.py
from connector import TroubleBrewingAdapter
from backend.http_server import create_server

httpd = create_server("127.0.0.1", 8000, adapter=TroubleBrewingAdapter())
httpd.serve_forever()
```

`connector.TroubleBrewingAdapter` 实现本页定义的 `ReasoningAdapter` 契约，通过 `create_server(..., adapter=...)` 注入。推荐直接用顶层入口 `main.py web`，它已完成同样的注入。

## 测试

双层分析使用的 `reasoner:scope/source/owner_id` 元数据由 `validation.py` 校验；只有 confirmed 事实允许显式 public，假设只能 conditional，owner 必须引用玩家。禁用事实不解析技能载荷，但仍校验元数据。

分析选项还包括 `total_timeout_ms`（1..60000）、`max_worlds`（0..100）、`max_repairs`（0..10）、`max_repair_checks`（1..1024）。默认值、预算边界与结果扩展见[协议说明](../web/protocol/README.md#双层分析与高级结果)。编译和分析由 `connector.py` 与 `botc_reasoner/pipeline.py` 执行。

后端测试见 [`../tests/test_backend.py`](../tests/test_backend.py)，覆盖真实临时 HTTP 请求、校验拒绝、路由/传输错误，以及注入 fake adapter 模拟 `sat`/`unsat`/异常。运行：

```sh
.venv/bin/python main.py test
```

## 相关文档

- 协议契约：[../web/protocol/README.md](../web/protocol/README.md)
- 真实适配器与暗流涌动模型：[../botc_reasoner/README.md](../botc_reasoner/README.md)
