# 自主检查与概率融合交接

## 范围与代码来源

本轮覆盖前端记录、协议校验、约束转换、直接 Z3 模型及概率估计适配。当前工作分支为 `Engine`。

已合入 `origin/main` 的 UI 更新 `6e57447` 和队友概率更新 `2f4178f`，合并提交为 `1ae834d`。队友概率算法保留在 `botc_reasoner/probability.py`，没有另建推理模型。

合并前工作区的完整 tracked diff 保存在 `/tmp/opencode/overnight-before-main.patch`，命令行局部改动另保存在 `/tmp/opencode/overnight-cli-local.patch`。原工作区曾删除概率模块和旧概率测试；按本轮明确的融合要求采用 main 中最新概率模块、测试及 CLI，原始差异保存在上述补丁。`main.py` 本地默认端口 8001 的设置继续保留。

## 任务与当前实现

| 任务 | 结果与实现位置 | 验证 |
| --- | --- | --- |
| 同步队友工作 | 合并最新 UI、概率模块与 CLI | Git 来源核对，保留工作区补丁 |
| 全局假设 | `botc:global_assumption` 的 role_absent 编译成指定时点全员真实角色排除；不排除酒鬼标记 | `test_frontend_conditions.py`，真实 HTTP 无恶魔条件得到正常 unsat |
| 启用开关 | 新技能、死亡、全局记录启用，投票草稿禁用、结算启用；enabled 唯一生效 | `web/tests/app-conditions.test.cjs` 实际加载 app.js 调用方法 |
| 技能观察 | 接受 UI 的 22 角色记录形状，转换结构化部分；真实动作目标受身份／健康守卫连接到选择变量 | 形状校验、投毒目标守卫、酒鬼标记、死亡／存活负结果回归 |
| 白天投票 | 提名人、被提名人、逐人票映射到实际槽；结算记录封闭剩余槽，未结算不封闭 | 槽绑定测试、未结算开放性、自提名真实求解 |
| 规则修正 | 允许自提名、提名死者；死者票整局一次；女郎五人门槛按恶魔死前；满足条件时夜间女郎优先接星坠 | `test_rule_regressions.py`、规则来源见后文 |
| 参与说明 | `participation.py` 输出 applied/partial/record_only/disabled，前端逐条说明 | HTTP 与结构化观察回归 |
| 概率核心预算 | `ProbabilityIncomplete`、上下文独立预算、求解 unknown 不得当排除、长循环检查截止 | `test_probability_budget.py` |
| 概率权重遗漏 | 确定观察也传入干扰权重计算；不额外向求解器钉身份、不改软分组 | mocked 干扰计算回归，队友原概率套件 |
| HTTP 概率适配 | `probability_adapter.py` 以 public 输入为硬条件、conditional 输入按 owner 组以 0.7 采信枚举组合，估计 setup 身份；独立预算 | `test_probability_adapter.py` 的分组加权、矛盾仍 estimated、public unsat、unknown、开关测试 |
| 网页概率模式 | 推理栏复选框写 options，更新 revision/request_id 并清旧结果；显示估计及未知原因 | 实际 app.js VM 交互测试与 JS 语法检查 |
| 协议和文档 | 同步 types.ts、协议／后台／模型／网页 README、AGENTS | 字段与实现逐项核对 |

## 使用与语义

```sh
.venv/bin/python main.py web --host 127.0.0.1 --port 8000
.venv/bin/python main.py test
node --test web/tests/*.test.cjs
```

网页勾选“概率估计模式”后点击推理。API 可传：

```json
{"options":{"probability_mode":true,"probability_timeout_ms":120000,"total_timeout_ms":8000,"timeout_ms":1000}}
```

`reasoner:probabilities` 的 scope 固定 conditional，时间固定 setup。public 输入是硬条件；其他启用输入按 `owner_id` 分组、以可信度 0.7 伯努利采信并枚举组合，再按组合权重归一化。reported role 仍是 belief，自认并不被擅自改成真实身份。用户输入之间矛盾时，矛盾组合被跳过，概率仍可为 estimated；只有 public 背景矛盾才是 inconsistent。概率模式不改变逻辑 consistency 与 results，但会跳过 `reasoner:diagnosis` 与 `reasoner:role_ranges`，显式查询、修复和世界枚举仍保留。

CLI 仍按玩家可信度 0.7 对自认／技能声明分软采信组；HTTP 适配器以通用 owner 组做软采信，且 public 始终为硬条件。两者输入组织不同，不应直接比较同名输出百分比。

结果状态为 estimated、unknown 或 inconsistent；complete 恒 false，组合覆盖见 groups.complete。estimated 是启发式带权抽样估计，不是精确概率或完整世界计数。unknown 的 rows 为空；未采样到某角色不证明该角色 impossible。概率预算独立于逻辑总分析预算，两者均不覆盖锁等待和变量／规则构建。

## 规则依据与已核对要点

- [Scarlet Woman 官方说明](https://wiki.bloodontheclocktower.com/Scarlet_Woman)：恶魔死亡前五人，死后四人也可触发；五人及以上时健康女郎优先接恶魔自杀。
- [Rules Explanation](https://wiki.bloodontheclocktower.com/Rules_Explanation)：死亡后余下整局只有一票；活着时投票不消耗死者票。
- [Poisoner](https://wiki.bloodontheclocktower.com/Poisoner)：投毒持续当夜与次日；中毒时使用一次性技能仍消耗机会。现猎手 spent 条件不要求健康，此项未误改成“中毒可再用”。

这是重点规则审阅及回归验证，不等于整本规则全部对局组合通过。

## 已知边界与后续任务

1. 现模型阶段粒度不能完整表达同一天多个死亡／角色转化的精确事件顺序。女郎白天五人判断按黎明人数；若当天先有其他死亡再恶魔死亡，仍需事件级重构。
2. 投毒者星坠成为恶魔后立即停止中毒的细时点尚未完整建模；当前中毒用夜间断面变量表示。不能据此宣传完整时间线正确。
3. 圣徒／镇长胜负判定未建模；魔典自由文本、模糊登记备注、疑似转移不解析成隐藏真相，participation 会说明。
4. 前端跨时点身份卡片的延续是展示约定，`ui:*` 元数据不自动增加后台全时段约束。
5. 同日重复提名次数、槽上限和白天死亡先后仍受当前规则模型限制；超出模型能力的实际记录需扩展模型，不能以“已接受结构”等同“完整支持”。
6. 目前概率样本数和试次数较保守，复杂无身份局可能返回 unknown；无置信区间和误差保证。后续宜增加样本诊断、可调预算与性能基准。
7. 浏览器真实点击与视觉布局仍建议人工验收；本轮前端自动验收是 Node VM 交互与模块测试，不替代真实浏览器渲染检查。

## 验收记录

全量 Python 套件 235 项通过，新增真实 HTTP 概率样例另做针对性验证；前端 Node 12 项通过，修改 JS 语法检查、demo、工作区和暂存区的 diff --check 均通过。真实模型样例：五人身份全钉为 imp、poisoner、chef、soldier、washerwoman 并显式标 `reasoner:scope:"public"`，逻辑为 sat，概率为 estimated，唯一组合、每行钉定身份为 1.0 且归一化；若这些身份保持默认 conditional，它们会按 owner 组软采信，可能出现非 1.0 或预算不足的 unknown，符合新的组合枚举语义。

本轮未自动推送；合并提交之外的功能修改保留在工作区，后续提交前应复核暂存区（合并恢复补丁时 `git apply --3way` 曾将部分文件暂存）。
