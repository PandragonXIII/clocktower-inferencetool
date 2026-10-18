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

## 双层分析与高级结果

### 前端记录的参与约定

支持四类 BOTC 扩展：技能观察、夜间死亡、白天投票和 `botc:global_assumption`。后者 `data` 为 `{kind:"role_absent",role_id,time,requested_enabled?}`，时间可为 setup/day/night，约束该时点全体玩家的真实身份均不是所选角色；不排除酒鬼的镇民标记。`enabled` 是唯一参与开关，旧 `requested_enabled:true` 不会复活停用记录。reported 全局假设属于 conditional。

新录入技能、死亡和全局假设启用，投票草稿禁用、结算后启用。旧快照不自动迁移启用；可用全局开关、重新录入或在 JSON 中显式启用。首夜仅支持无人死亡；死亡列表是当夜完整公布结果。

投票 `nominations` 按顺序转换为提名人、被提名人、逐人投票变量；settled 且显式带列表时关闭剩余提名槽，voting 不关闭未录入槽且不约束最终处决。省略 nominations 表示未记录提名而非零提名。`execution` 约束处决结果；`alive_count` 若提供也参与约束。threshold/highest_count/default_player_id 是前端计算展示值，不替代实际投票规则；override 不允许绕过规则矛盾。

22 个角色的 UI 技能形状均可提交。结构化信息、目标、死亡／存活结果参与相应约束；送葬者若填写目标也约束前日被处决者，酒鬼结果约束镇民标记而非真实镇民身份。间谍魔典文本、陌客不具体的登记备注、疑似镇长转移不被解析成隐藏真相；圣徒只约束处决，镇长三人无处决只约束人数和处决，均不判断胜负。未观察结果不添加读数约束，但猎手／恶魔已指定的动作仍可保留。

响应 `extensions["reasoner:participation"]` 按每条输入返回 `{id,status,reason}`，status 为 applied（有约束）、partial（只转换结构化部分）、record_only（仅保存）或 disabled（停用）。这不是求解成功保证；矛盾和预算不足仍按正常结果返回。`ui:*` 链接和时间线展示元数据本身不附加跨时段命题。

真实适配器分别求解 **public（规则 + 公共输入）** 和 **conditional（规则 + 公共输入 + 当前采信的其他输入）**。顶层结果对应 conditional。条件背景矛盾不影响公共背景下已证明的结论；背景矛盾时查询返回 `inconsistent`，不据此推出任意身份。

默认只有启用且 `confirmed` 的 `botc:night_deaths` 和已结算 `botc:day_vote` 属于 public，其余为 conditional。事实可用 `extensions["reasoner:scope"]` 显式设为 `public` 或 `conditional`，但只有 `confirmed` 允许 public；假设只能 conditional。`confirmed` role 仍指真实身份，`reported` role 指自认身份。

事实／假设可携带 `reasoner:source`：`received`、`self_claim`、`assumption`、`public_announcement`、`observation`；它只记录来源，不改变可信等级。私密收到的信息与用户假设在条件层同样可撤回，收到数字不代表数字正确，信息正确性仍由健康、注册等规则决定。`reasoner:owner_id` 引用玩家，用于归属和修复分组；默认身份命题归其玩家，技能观察归发动者，不归观察目标。禁用记录不解析技能载荷，但元数据仍校验。

### 分析选项

| 选项 | 默认 | 合法范围与含义 |
| --- | --- | --- |
| `timeout_ms` | 1000 | 正整数，每次求解超时毫秒 |
| `total_timeout_ms` | 8000 | 1..60000，所有分析共享的毫秒预算 |
| `max_worlds` | 0 | 0..100，0 关闭世界枚举 |
| `max_repairs` | 0 | 0..10，0 关闭修复建议 |
| `max_repair_checks` | 128 | 1..1024，每类修复的求解次数上限 |
| `probability_mode` | false | 布尔。为 true 时增加一次初始身份带权抽样估计，写入 `reasoner:probabilities`；不改变逻辑条件 |
| `probability_timeout_ms` | 120000 | 1..300000，**该次概率估计独立**的毫秒预算（与 `total_timeout_ms` 分开），仅在 `probability_mode` 为 true 时生效 |

例如 `"options":{"total_timeout_ms":8000,"max_worlds":10,"max_repairs":3}`。世界枚举用于 sat 背景，修复用于 unsat 背景。总预算从分析阶段开始，不含变量／规则构建或等待适配器锁的时间，也不是整个 HTTP 请求的硬截止时间。预算有限时各项分析可能未完成。

### 概率估计（`reasoner:probabilities`）

`options.probability_mode` 为 true 时，真实适配器在正常分析之外，**另起一次独立预算**（`probability_timeout_ms`，默认 120000）做初始身份的带权抽样估计，结果写入响应 `extensions["reasoner:probabilities"]`。它**不改变本次请求的逻辑条件与逻辑结果**（`consistency`、`results` 仍来自正常分析），也不属于 public/conditional 两轨之一：`scope` 固定 `"conditional"`，`time` 固定 `{"phase":"setup"}`。为把预算留给概率估计，概率模式下正常分析跳过 `reasoner:diagnosis` 与 `reasoner:role_ranges`（连同旧字段 `trouble_brewing:possible_roles`）；显式查询、`max_repairs` 修复和 `max_worlds` 世界枚举仍按原语义执行，逻辑 `unsat` 也不会被概率结果掩盖。

它的条件方式是 **public 硬条件 + conditional 软采信**：

- `scope == "public"` 的全部启用输入始终作为硬约束；public 背景 `unsat` → `status:"inconsistent"`，不抽样。
- 其余启用输入（conditional，包括事实与假设）按 `owner_id` 分组；没有归属的输入各自成组。每个组以可信度 `0.7` 做伯努利采信，枚举「采信 / 忽略」组合：`n` 个组共 `2^n` 种，权重为 `0.7^采信组数 × 0.3^忽略组数`。组数不超过 6 时全部枚举；更多时按固定种子抽样至多 64 种，并在 `groups.complete:false` 标注只覆盖部分组合。
- 每组组合把**被采信输入的已编译表达式原样**加入求解器——包括 `reported` 角色声明编译出的 `belief`（自认身份，不是真实身份）。适配器不改写映射，也不会因为输入是 conditional 就把 `confirmed` role 降级成 belief。
- 逻辑上矛盾的组合权重为 0，被跳过；**用户输入之间互相矛盾不会让概率整体变成 `inconsistent`**，剩余一致组合仍会估计并归一化。只有 public 背景矛盾才是 `inconsistent`。
- 对每个可行组合调用带权抽样估计器，再按组合权重合并各角色概率并归一化到 1。启用的 `botc:ability_observation` 会随其所在组作为 `trusted_abilities` 传入。
- 枚举或抽样因预算耗尽、单次求解超时或未取到样本而中止时，`status:"unknown"`、`rows:[]`；**不把未判定组合当排除，也不归一化只成功的部分组合**。

CLI 的 `test_reasoning.py` 仍按玩家可信度 0.7 对自认/技能声明分软采信组，语义不变；HTTP 适配器现在也做类似的组级软采信，但分组键是通用 `owner_id`，不是只针对角色声明，且 public 输入始终为硬条件。见 [botc_reasoner 文档](../botc_reasoner/README.md#概率估计probabilitypy--probability_adapterpy)。

`status` 取值：`estimated`（已抽样）、`unknown`（预算耗尽、单次求解超时或未取到样本）、`inconsistent`（public 背景本身矛盾）。诚实标注：

- `complete` 恒为 `false`——这是抽样估计，**不是精确概率**，`method` 恒为 `"weighted_sampling"`。组合枚举是否完整另见 `groups.complete`。
- `status != "estimated"` 时 `rows` 返回 `[]`，**不得读作任何角色概率为零**；未采样到的角色也**不代表 `impossible`**。
- `inconsistent` 只说明 public 背景无概率，不是概率结论。逻辑结果为 `unsat` 的请求仍可能得到 `estimated`（conditional 冲突只排除相应采信组合）。

字段：`conditioning` 固定 `"public_with_soft_conditional_inputs"`，`credibility` 为 `0.7`；`input_ids` 是全部参与估计的输入，`hard_input_ids` 是 public 硬条件，`soft_input_ids` 是按组采信的 conditional 输入；`groups` 为 `{total, checked, estimated, complete}`（全部组合数、已检查组合数、可行并完成估计的组合数、是否覆盖全部组合）。**samples 元数据** `target_accepted_per_group` / `max_trials_per_group` 是该适配器实际传给抽样器的「每个采信组合目标接受样本数 / 最大尝试次数」（当前固定为 `2` / `16`），用于解释估计精度与耗时，不改变概率语义。`rows` 每行为 `{ player_id, seat, probabilities }`，其中 `probabilities` 是 `{ role_id: float }`；失败或部分覆盖时附 `reason`。前端在推理结果区展示该估计，并明确提示它不是必然结论。

### 响应扩展

以下均放在响应 `extensions`。其中 `reasoner:participation` 与 `reasoner:probabilities`（后者仅 `probability_mode` 时出现）已在网页推理结果区展示；其余高级结果尚未专门渲染，可直接查看 API JSON。

| 字段 | 当前内容 |
| --- | --- |
| `reasoner:scopes` | 两层各自的 `consistency/results/input_ids` |
| `reasoner:inputs` | 输入的 `id/scope/source/owner_id/identity_claim/description`，不含 Z3 表达式 |
| `reasoner:rule_catalog` | 实际规则组的 `id/title/source`，含变量域 `tb:domain` |
| `reasoner:conclusions` | 已证 necessary 命题、scope、输入及规则依据；`basis_type:full_context` 是整个背景，不是最小证明 |
| `reasoner:diagnosis` | 按 scope 返回冲突核或 unknown，附说明、输入描述、规则组名称 |
| `reasoner:role_ranges` | conditional 初始身份范围：`scope/time/rows/complete`；每行含玩家、seat、可行 `role_ids`、已排除 `impossible_role_ids`、未判定 `unknown_role_ids`、`complete` |
| `reasoner:participation` | 逐条输入的 `id/status/reason`，说明是否被编译成约束（`applied`/`partial`/`record_only`/`disabled`） |
| `reasoner:repairs` | `identity`（仅身份）和 `general`（所有条件输入）两类撤回方案 |
| `reasoner:worlds` | 初始角色联合世界：`worlds:[{roles:{玩家id:角色id}}]`、`returned_count/complete/total/truncated_reason/time` |
| `reasoner:timeout` | `total_ms/per_solve_ms/hit`，反映总预算是否耗尽 |
| `reasoner:timings` | 真实连接器每阶段的实测毫秒：`build_ms/analysis_ms/probability_ms/total_ms`，以及 `excludes`（`adapter_lock_wait`、`http_transport`）。用于本地性能对比，不是预算或硬截止；不修改任何推理结论 |
| `reasoner:probabilities` | `probability_mode` 时的初始身份带权抽样估计：`status/method/scope/conditioning/credibility/time/complete/seed/input_ids/hard_input_ids/soft_input_ids/groups/target_accepted_per_group/max_trials_per_group/rows/description`，行含 `player_id/seat/probabilities`（见上一节） |

冲突按规则组、域公理和单条输入追踪。`minimality:inclusion` 仅表示核内任一组都不可再删除，不表示最少条数；`unverified` 表示收缩未完成。撤回一个核中的一条未必修复其他冲突。解释说明联合不相容，不宣称逐步证明。未取得核时不生成虚假的顶层 `conflicts`。

修复方案含 `removed_input_ids/changed_owner_ids/cost/optimality/verified`，先最少归属组，再最少输入条数；无玩家归属的输入各算独立组。public 固定不撤，每个方案均重验完整剩余问题可满足。撤回不增加原命题的否定，不表示谁撒谎或已替换真实身份。最优代价与方案列举完整性分别用 `optimality` 和 `complete` 表示；次数／时间不足不得当作没有解。

世界按全体玩家的初始角色联合投影去重，不是各人范围的笛卡尔积，也不代表概率。仅 `complete:true` 时 `total` 是精确总数，否则为 null；截断原因为 `max_worlds/solver_unknown/deadline`。旧 `trouble_brewing:possible_roles` 保守保留未判定角色，并附 `unknown_role_ids/complete`，避免把超时误当作排除。

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

- `status: "confirmed"`：已确认来源的输入，启用后必须满足；它仍可能属于可撤回的 conditional 输入，不自动成为公共依据。
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

后台当前已识别四类 BOTC 扩展（见 `types.ts` 中 `AbilityObservationData` / `NightDeathsData` / `DayVoteData` / `GlobalAssumptionData`，它们只是文档性注解，不改变 `ExtensionFact.data: JsonValue` 的开放结构）：

| `type` | `data` 摘要 |
| --- | --- |
| `botc:ability_observation` | `time`（day/night + 正数）、`actor_id`、`role_id`、`targets`，以及 `result.kind`（`unobserved`/`no_outsiders`/`no_direct_result`/`role`/`number`/`text`/`choice`）与对应字段。 |
| `botc:night_deaths` | `time`（night）、`player_ids`、`result`（`deaths`/`none`）。首夜仅支持无人死亡。 |
| `botc:day_vote` | `time`（day）、`stage`（`voting`/`settled`）、`execution.player_id`（可为 `null`），可选 `nominations`（提名人/被提名人/逐人投票）、`alive_count` 等。 |
| `botc:global_assumption` | `kind`（`role_absent`）、`role_id`、`time`（setup/day/night），可选 `requested_enabled`（仅兼容旧字段）。 |

约定：

- **`enabled: false` 不解析 `data`**：可保存任意草稿；`enabled` 是唯一参与开关。
- **结构非法或引用不存在**（未知玩家/角色、时间晚于 `game.time`、字段类型错误、未知全局假设 `kind`）返回 `400`。
- **结构合法但当前模型不支持**返回 `422`，当前主要为首夜出现死者。未结算投票（`stage: "voting"`）与多数角色观察现在通过校验，由转换层做部分或完整转换；实际参与情况见响应 `extensions["reasoner:participation"]`，`422` 不是格式错误，不代表已支持。

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

- 推理模型见 [`../../botc_reasoner/README.md`](../../botc_reasoner/README.md)。
- 当前 HTTP 实现见 [`../../backend/README.md`](../../backend/README.md)：顶层入口 `main.py web` 默认注入真实适配器 `connector.TroubleBrewingAdapter`，对 `examples/request.json` 返回示例描述的 `sat`/`necessary`；框架默认 placeholder 适配器（直接调用 `create_server()` 时）则返回 `consistency: "unknown"`。
- 本协议描述的是网页/后台契约，后台实现需自行完成运行时校验（TypeScript 类型无法在运行时校验）。

## 示例

- 请求：[`examples/request.json`](examples/request.json)
- 成功：[`examples/success.json`](examples/success.json)
- 冲突请求：[`examples/conflict-request.json`](examples/conflict-request.json)
- 冲突：[`examples/conflict.json`](examples/conflict.json)
- 错误：[`examples/error.json`](examples/error.json)
