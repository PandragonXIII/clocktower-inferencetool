# Backend：网页协议 HTTP 服务

`backend/` 提供血染钟楼网页端与后台之间的 HTTP 服务，实现 [`../web/protocol/`](../web/protocol/README.md) 定义的 JSON 契约的**运行时校验**与路由，并通过**适配器（adapter）**把协议请求接到推理引擎。

当前适配器是 **placeholder（占位）**：它回显请求标识、按 id 回显查询，并把全局一致性与所有查询都判为 `unknown`。它**没有做规则转换、也没有运行推理引擎**。这是框架占位，不代表真实推理能力。

## 组成

| 文件 | 职责 |
| --- | --- |
| `http_server.py` | 基于标准库 `http.server` 的同源服务：提供 `web/` 静态文件与 `/api/` JSON API。 |
| `validation.py` | `POST /api/v1/reason` 的运行时校验（形状、类型、跨集合 id 唯一、引用、时间、未知类型）。 |
| `errors.py` | `ApiError`：协议级 HTTP 错误（status + code + message + JSON Pointer path）。 |
| `adapter.py` | 适配器契约 `ReasoningAdapter`、请求分类 `prepare_request`、占位实现 `PlaceholderAdapter`。 |

## 运行

```sh
.venv/bin/python main.py web --host 127.0.0.1 --port 8000
```

该命令同时提供 UI 与 API（同源，无需反向代理）。仅静态文件可用：

```sh
python -m http.server 8000 --bind 127.0.0.1 --directory web
```

但此时 **不含 API**，点击“发送到后台”会失败（标准库静态服务通常返回 501）。

## 接口

### GET /api/v1/capabilities

返回占位能力，`extensions["adapter:mode"] == "placeholder"` 明确表示未运行引擎：

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

占位响应（对 `examples/request.json`）：

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

## 适配器契约

适配器实现两个方法：

```python
class ReasoningAdapter(Protocol):
    def capabilities(self) -> dict: ...
    def reason(self, request: dict) -> dict: ...
```

`http_server.create_server(host, port, adapter=...)` 可注入自定义适配器（须线程安全/无状态）。`reason()` 收到的 `request` 已经过 `validate_request` 校验；可在内部用 `prepare_request(request)` 把请求拆分为引擎就绪的分桶（confirmed/reported/disabled 事实、enabled/disabled 假设、查询等，均为深拷贝）。

### 替换成真实适配器范例

```python
# backend/my_adapter.py
from backend.adapter import API_VERSION, prepare_request
from engine import ReasoningEngine

class EngineAdapter:
    def capabilities(self):
        return {
            "api_version": API_VERSION,
            "supported_fact_types": ["role", "alignment"],
            "query_types": ["role", "alignment"],
            "scripts": [{"id": "trouble_brewing", "name": "暗流涌动"}],
            "extensions": {"adapter:mode": "engine"},
        }

    def reason(self, request):
        prepared = prepare_request(request)
        engine = ReasoningEngine()
        # TODO: 把 prepared.confirmed_facts / enabled_assumptions 转成约束
        consistency = "unknown"  # 由 engine.check() 得出
        return {
            "api_version": API_VERSION,
            "request_id": prepared.request_id,
            "game_id": prepared.game.get("id"),
            "revision": prepared.game.get("revision"),
            "consistency": consistency,
            "results": [
                {"id": q.get("id"), "status": "unknown"} for q in prepared.queries
            ],
            "extensions": {"adapter:mode": "engine"},
        }
```

注入：

```python
from backend.http_server import create_server
from backend.my_adapter import EngineAdapter

httpd = create_server("127.0.0.1", 8000, adapter=EngineAdapter())
httpd.serve_forever()
```

## 测试

后端测试见 [`../tests/test_backend.py`](../tests/test_backend.py)，覆盖真实临时 HTTP 请求、校验拒绝、路由/传输错误，以及注入 fake adapter 模拟 `sat`/`unsat`/异常。运行：

```sh
.venv/bin/python main.py test
```

## 相关文档

- 协议契约：[../web/protocol/README.md](../web/protocol/README.md)
- 推理内核：[../engine/README.md](../engine/README.md)
