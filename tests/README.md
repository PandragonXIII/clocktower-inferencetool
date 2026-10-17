# 测试说明

`tests/` 下有引擎测试与后端测试两个套件，均由顶层 `main.py test` 统一运行。

## Engine 测试（`test_engine.py`）

覆盖通用推理引擎的可满足性、身份查询结果（可能/必然/不可能/前提矛盾）、冲突标签、临时假设隔离、tracker 变量名冲突、自动标签、超时参数校验。

## Backend 测试（`test_backend.py`）

- `PreparedRequestTests`：`prepare_request` 把事实分为 confirmed/reported/disabled、假设分为 enabled/disabled，结果是对输入的**深拷贝**且不修改输入，非映射输入抛 `TypeError`，缺失集合默认为空。
- `BackendHttpTests`：`setUpClass` 在**真实临时 HTTP 服务器**（`ThreadingHTTPServer`，端口 `0` 自动分配）上启动线程，`tearDownClass` 在 `finally` 语义下 `shutdown()` 并 `server_close()`。请求全部通过真实 socket（`http.client`）发出，覆盖：
  - 静态协议示例文件（不依赖网页界面）；
  - `/api/v1/capabilities` 占位能力；
  - `POST /api/v1/reason` 的 unknown 回显与空 `queries`；
  - 校验拒绝：跨集合重复 id、无效引用、布尔冒充整数、小数时间、未知且活跃扩展拒绝 / disabled 允许；
  - 传输与解析：重复 JSON 键、`NaN`、类型错误、`415`、`413`、路由 `404` 与方法 `405`（含 `Allow`）；
  - 用 `mock.patch.object(PlaceholderAdapter, "reason")` 在线模拟适配器返回 `sat`/`unsat`（均 `200`）以及抛异常（`500`）。因为适配器在调用时经类解析，单个 server 即可覆盖多种适配器行为，无需多个 server。

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
