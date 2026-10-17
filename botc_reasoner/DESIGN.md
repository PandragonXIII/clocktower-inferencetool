# botc_reasoner 目标设计与实现边界

> **状态：部分实现，其余为规划。**
> 已接入真实 API：约束来源记录、public/conditional 双层分析、规则组级冲突诊断、保守身份范围、最少归属组撤回建议、初始角色联合世界枚举及共享分析预算。
> 对应实现为 `provenance.py`、`inputs.py`、`analysis.py`、`pipeline.py`、`repairs.py`、`worlds.py`。
> 角色独立规则模块、事件级因果重构、真实身份替换建议与逐步证明仍未实现。
> 本文描述 `botc_reasoner/` 的**目标架构**与**迁移路径**，用于人工审阅框架与底层规则。
> 文中出现的类名、函数签名、数据结构、API 字段大多是**拟议接口**，当前代码里并不存在。
> 下文保留目标接口与迁移方案，不能据此认定所有字段已落地；实际字段与限制以 README 和协议为准。
>
> 现状的准确描述以 [`README.md`](README.md) 为准；本文**不复制** README 中会过时的清单或限制，
> 只引用其位置（见 §12）。
>
> 目的：让规则可以被**人工逐条复核**。为此需要（a）数据分层清晰、每层语义无歧义，
> （b）规则以角色为单位的独立模块表达、带可追溯的规则编号与人类可读说明，
> （c）诊断（冲突、最小修复、候选世界）每一步都能给出**为什么**，而不是一个黑箱布尔结果。

---

## 0. 指导原则（先读）

1. **一个推理模型。** 继续使用 `z3-solver` 直接建模。**不**引入第二个求解器、**不**引入通用引擎抽象层。
   §4 的「角色规则类」是在**同一个 Z3 求解器**上组织约束的代码结构，不是并行求解体系。
2. **事实与假设分层，可撤销性决定求解语义。** 规则（R）、可信公共启用事件（P）、可撤销项（C）三者
   在语义与求解流程上分开（§1、§2）。R 与 P 构成公共背景，不可自动撤销；C（采信的私密观察 / role
   声明 / 用户假设）可撤销，只参与条件结论。来源（source：`received` / `self_claim` / `assumption`）
   只用于展示与修复追溯，不作为独立语义轴（§1.3）。
3. **命题是「关于何时、谁、什么」的显式三元组，事件级粒度。** 因果步骤分离，未记录即未知
   （open world），不得把「没记录」当作「否定」（§3）。
4. **每条约束可追溯到规则编号与输入 id。** 冲突、修复、候选世界都返回**人类可读的原因**
   （§5–§9）。人工审阅是第一优先级。
5. **不夸大能力。** 未验证的组合不宣称支持；`unknown`/`partial` 必须显式暴露，不能伪装成完整结果
   （§8、§9）。拟议接口一律标注「非已实现」。
6. **逐步迁移，不双加载。** 现有巨型 `rules.py` 保留入口，新旧规则不并存加载（§4.9、§11）。

---

## 1. 数据分层

### 1.1 三层语义（按可撤销性）

结论只有两类来源：**public 必然**（公共背景上必然）与 **conditional 必然**（采信 C 之后才必然）。
数据据此分三层：

| 层 | 名称 | 来源（source） | 求解语义 | 可否撤销 | 示例 |
| --- | --- | --- | --- | --- | --- |
| **R** | 规则 | 剧本规则（钟楼百科） | 公共背景，硬约束 | 否 | 「小恶魔每夜至多杀一人」 |
| **P** | 可信公共启用事件 | 说书人结算、公开公布的 night deaths / settled day vote | 公共背景，硬约束 | 否（不可自动撤销） | 「第 2 夜公布了 p1 死亡」 |
| **C** | 可撤销项 | 采信的私密观察、role 声明、用户假设 | 条件背景（B∧C*），采信后本次求解为硬 | **是** | 「p2 自认是猎手」 |

关键区分，必须在代码与文档里一致：

- **source 只用于展示与修复追溯，不是独立语义轴。** 每条条目记录的来源是
  `received`（收到的观察，如说书人私下/公开给出的信息）、`self_claim`（玩家自述 role 声明）、
  `assumption`（用户假设）。它决定**怎么展示**与**修复时怎么追溯**，但**不决定该条是 public 还是
  conditional**——那是 §1.2 的 `scope` 字段。不应按 source 想象出额外的推理类别。
- **`confirmed` 不自动是 public。** `confirmed` 只表示「来源不是玩家自述」；一条 `confirmed` 的私密观察
  仍然默认是 conditional（§1.2）。
- **claim（声明）不是 believed 真值。** 一条 `reported` role 声明进入系统时只是「某个来源报告了 p 自称某角色」。
  只有被用户（或自动策略）**采信（adopt）**后，才作为可撤销项约束本次求解。未采信的 claim 仍然是有用信息
  （可用于诊断「如果它是真的会怎样」），但**不进入背景 B**。
- **采信后，它是本次请求内的硬约束，但仍是 conditional 而非 public。** 这与现状 `reported` role →
  自认身份（belief）的语义一致（见 README「声明与启用开关」）。`enabled:false` 表示该条不参与本次推理。
- **角色声明与真实身份必须区分。** 采信「p 是猎手」的 `reported` 声明约束的是 p 的**自认身份（belief）**，
  **不等于** p 的真实角色标记：酒鬼的自认 ≠ 真实角色，故 belief=猎手 允许「真是猎手」或「拿着猎手标记的酒鬼」。
  只有**显式断言真实身份**（kind=role 的 `confirmed`/真实身份命题，角色层而非 belief 层）才排除酒鬼（§6.4）。

> **只有 `reported` role 声明才映射为 belief**（现状语义，见 README「声明与启用开关」）。除此之外的
> `confirmed` role 命题**仍旧映射真实命题**，保持现状兼容，**不默默改其 belief**。只有用户**明确**
> 把某条当作「真实 role 假设」时，才显式走真实 role 假设；不能把任意 `confirmed` role 悄悄降级为 belief。

### 1.2 scope：public / conditional，以及 public 的默认来源

求解只有两条轨道，用唯一的 `scope` 字段区分（拟议字段，取值只有 `"public"` / `"conditional"`）：

- **`scope="public"`**：进入公共背景 `public=R∪P`，不可自动撤销，可产生 **public 必然**。
- **`scope="conditional"`**：进入可撤销集合 C，仅当被采信后参与条件背景 `B∧C*`，只能产生 **conditional 必然**。

**public 的默认分类（只有这两类）**：`confirmed` 的 **night deaths**（公开死亡公布）与 **settled day vote**
（已结算的白天处决），默认归类为 public。其余条目**默认 conditional**。

**显式升级为 public 的严格条件**：任何其他条目要作为 public 输入，必须同时满足
1. 显式声明 `extensions["reasoner:scope"] = "public"`，且
2. `status = confirmed`。

`reported` 条目**永远不允许**升级为 public——**公开说了不等于内容为真**，公开只是「大家都听到了这条声明」，
不能使声明内容变成公共必然。

**私密观察默认 conditional**——即便它 `status=confirmed`。当前模型里把 `confirmed` role 命题**仍旧映射真实
命题**以保持兼容（§1.1），`scope` 分类与「映射到真实命题还是 belief」是两件独立的事，**不因 scope=conditional
就默默把已确认 role 改写成 belief**。说书人私下告知的确认信息（洗衣妇 / 占卜师 / 调查员等）是收到者的事实，
但其他玩家视角下它是未知，不能当成公共必然（§2.3）。

> **`confirmed` 不等于 public。** `confirmed` 只表示「来源不是玩家自述」；其 public/conditional 归属仍由上述
> 默认分类与显式 `reasoner:scope` 决定。缺少显式 scope 的条目按「非 public」保守处理，**不得默认视为 public**。
>
> **收到数字是事件事实，不等于数字正确。** 「说书人在第 2 夜告知 p1 厨师数=2」是一条已收到的事件事实；
> 该数字**是否正确**仍可能被中毒/醉酒/误注册影响。不能因为一条 private 观察被收到，就断言其内容必然正确，
> 更不能断言「所有 private 一定错误」——private 观察内容对错由健康/注册规则决定，不是由 private 这一属性决定。
>
> 现状映射：当前模型**没有显式记录 scope**，一律当硬约束且不区公共/条件。
> `botc:night_deaths`（公开死亡公布）、`botc:day_vote`（公开处决）是 public 默认来源，
> 但那是调用约定而非模型内字段；`botc:ability_observation` 的 scope 取决于它是否被显式升级为 public，
> 不能因它是 `confirmed` 就当作公共已知。这是规划要补的字段（§11 阶段 B）。

### 1.3 C 的语义：actor / claim owner / source attribution 与 target 分离

这里的 `source` 是**归因（attribution）**，只用于展示与修复追溯，**不是 §1.1 的语义轴**；不要把它与
「public/conditional」混淆。一条可撤销项（尤其技能声明/观察）至少涉及四个不同角色，不能混为一谈：

| 角色 | 字段（拟议） | 含义 |
| --- | --- | --- |
| **声明所有者 owner** | `attribution.owner_id` | 谁「说出」这条声明/观察（通常是一个玩家） |
| **来源 source** | `attribution.source` | 这条信息来自谁（`received` / `self_claim` / `assumption`） |
| **行为者 actor** | `attribution.actor_id` | 声明「我发动了该技能」的那个人 |
| **目标 target** | `targets[]` | 技能作用的对象（可能不止一个，且通常 ≠ actor） |

**禁止**把 owner 与 actor、actor 与 target 合并。例如「p3 声称 p1 在夜里是恶魔」：
owner=p3，source=玩家自述，actor=p3（若 p3 自称占卜师），target=p1。
采信这条假设会约束「p1 的注册/身份」与「p3 的能力是否生效」，但不会把 p3 与 p1 当作同一人。

---

## 2. 背景求解流程：先 public=R∪P，再条件 B=public∪C

### 2.1 两段式

```
public = R ∪ P        # 公共背景：硬规则 + 可信公共启用事件（不可自动撤销）
B = public ∪ C        # 条件背景：再加上采信的 C（可撤销）
check(public) / check(B)
  ├─ unsat  → 该轨道背景本身矛盾（分类见 §5.3），没有「该轨道结论」可谈
  │            但**公共背景可以独立判断**（见 §2.3）：即使 B(含 C) unsat，
  │            只要 public=R∪P 仍 sat，公共必然照常给；不得因整体 B unsat 就整体 unknown。
  ├─ unknown→ 本次为「不知道」：所有查询置 unknown（不是 unsat，也不是 sat），附 reason；
  │            不得进入查询阶段，也不得做工种性结论。
  └─ sat    → 对每条查询 q：
               public:       check(public ∧ q) 与 check(public ∧ ¬q)  → necessary / impossible / possible
               conditional:  对采信的 C*：check(B ∧ q) 与 check(B ∧ ¬q)
```

- **public 必然**：在公共背景 `public=R∪P` 上就必然成立，不依赖任何可撤销项。
- **conditional 必然**：只在采信了 C* 之后必然成立。两条结论必须**分开标注**，
  不能把 conditional 当成 public 报给用户。
- **unknown 分支必须补齐**：对应轨道的 `check`（`check(public)` 或 `check(B)`）返回 `unknown`
  （超时/求解器放弃）时，等价于「该轨道本次没有结论」，该轨道查询全部返回 `unknown` 并带 `reason`，
  **不**伪装成 sat 或 unsat。

### 2.2 为什么先 public 再 public∪C

1. 可撤销项不应污染「公共背景是否自洽」的判断。公共背景矛盾（R+P 本身有误，如录入冲突）
   与「采信 C 导致矛盾」是两类问题，诊断与修复手段不同（§5.3、§6）。
2. 条件结论需要能**随时撤销**：用户 withdrawal 掉某条 C 后，只需重算 B 上的 C'，公共背景 `public` 不变。

### 2.3 public 必然与 conditional 必然：两条独立求解轨道

**公共背景独立于「采信的 C」**，两条轨道分别求解、各自给结论：

```
public = R ∪ P                    # 公共背景：不可自动撤销
C = 采信的私密观察 / role 声明 / 用户假设   # 可撤销
B = public ∪ C                    # 条件背景
```

- **public 必然**在 `R ∪ P` 上判断：`check(public ∧ q)` 与 `check(public ∧ ¬q)`。
- **conditional 必然**在完整 `B = public ∪ C` 上判断。
- **关键**：`public` 与 `B` 是**两条独立轨道**。即使 `B`（含 C）unsat，只要
  `public = R ∪ P` 仍 sat，就应**照常返回 public 轨道的结论**，
  而不是因为整体 unsat 就把公共结论也一并 `unknown`。反之亦然——conditional 轨道的矛盾不污染公共轨道。
- 前端可选择展示哪一轨；拟议响应用 `scope` 标记结论轨道（取值只有 `"public"` / `"conditional"`，
  §9.1），避免把 conditional 必然冒充 public 必然，也避免 conditional 矛盾抹掉 public 结论。

> 日常判断「谁一定不是恶魔」这类问题时，默认语境是 public 必然；采信了私密观察/role 声明/用户假设后的细化是 conditional。

> **public 轨道矛盾时，只返回该轨道不可推任何命题，而不是空真爆炸。** 若 `public=R∪P` unsat，
> public 轨道查询返回 `inconsistent`（§2.4、§9），**不**输出任何 public 必然命题。
> 此时即使 public 轨道的另一方向（如取反）在 unsat 背景下形式上也「不可满足」，**不得**把它当结论。
> 反过来，`public` sat 而 `B=public∪C` unsat 时，**仍返回 public 结果**（conditional 轨道单独标记为
> `inconsistent`），公共结论不受 conditional 矛盾影响。

### 2.4 不在 unsat 上空真爆炸

**严禁**在背景 unsat 时，把任意命题判成 `necessary`（空集满足一切是空真，是经典陷阱）。
背景 unsat 时：

- 所有查询状态返回 `unknown`（或专门状态 `inconsistent`，与现有协议 `QueryStatus` 对齐），
  并附上背景冲突的诊断（§5、§9）。**public 轨道矛盾时 public 冲突返回 `inconsistent`，不可推任意命题。**
- 绝不因为「矛盾可以推出任何东西」而给出 `necessary`。
- **逐轨道判断**：上述「整体 unknown」指**该轨道**的背景。按 §2.3，public 轨道 `R∪P` 与
  条件轨道 `B=public∪C` 独立判断；只有**该轨道** unsat 才令其查询 `unknown`，不牵连另一条仍 sat 的轨道。
- **public sat 但 conditional unsat 时仍返回 public 结果**：public 轨道照常给 public 必然，
  conditional 轨道单独标 `inconsistent`，两者互不污染。

实现层要求：`check(public)` 与 `check(B)` 必须是**前置门**；只有对应轨道 sat 才进入该轨道的查询阶段。

---

## 3. 统一 time：事件级、因果分离

### 3.1 现状与目标

- 现状（见 README「时间与座位约定」）：`Moment.NIGHT_START` / `DAWN` / `AFTER_LAST_DAY`，
  以「断面」表达身份与存活。
- 目标：在断面之上引入**事件（event）**粒度，使「发生了什么」与「在哪个断面看身份」分离。

### 3.2 事件模型（拟议）

```
Event {
  id:        string          # 请求内稳定唯一
  time:      Time            # setup | {day|night, number}
  sequence:  int             # 同一 time 内的相对顺序（同一天多事件）
  kind:      EventKind
  actor_id?: string
  targets?:  string[]
  payload?:  ...
}
```

**因果分离**（一次夜间击杀会经过多个步骤，必须分别记录）：

| 步骤 | kind（拟议） | 含义 | 是否公开 |
| --- | --- | --- | --- |
| 选择 | `choice` | 小恶魔选了谁（魔典内） | 否（除非声明） |
| 保护 | `protection` | 僧侣保护了谁 | 否 |
| 结算 | `resolve` | 选择 + 保护 + 士兵/镇长等综合后的实际结果 | 说书人 |
| 攻击 | `attack` | 意图造成的击杀 | 否 |
| 公布 | `announcement` | 黎明公布「谁死了/无人死亡」 | 是 |

**必须分离的维度**：`role`（真实角色标记）、`alignment`（真实阵营）、`registration`（被查询时如何注册）、
`state`（存活/中毒/醉酒）、以及各事件本身。现状的 `spy_mask` / `recluse_mask` 就是 registration 维，
`is_drunk` / `poisoned` 是 state 维，不能与 role 混写。

### 3.3 逐步扩，不否定

- 可由现状的 `night_start` / `dawn` 断面**逐步**扩到事件级：先补「结算→公布」的两步分离，
  再补 choice/protection。
- **未录入的事件是「未知」，不是「没有发生」。** 只有当一个阶段的记录被标记为**完整**
  （`complete`/closed-world）时，才能对该阶段做「未出现即否定」的推理。
  默认 open world：没记录不等于否命题。
- **`disabled` 不扩 horizon。** 现状 `_horizon` 会把所有 facts/assumptions/queries（含
  `enabled:false`）的 time 都算进夜数（`connector._horizon`）。这是已知问题：禁用的条目不应
  影响求解规模。规划建议修正为「只有参与本次求解的条目才扩 horizon」，但**本次不改动当前代码**。

---

## 4. 规则组织结构：角色模块 + 中央服务

### 4.1 RoleRule 是规则类，不是「玩家实例的真实角色」

**核心约束**：规则安装**不得按声明身份选择**。不能因为「玩家 p 自称是贞洁者」就只安装贞洁者规则，
再据此推断 p 是贞洁者——那是倒置循环。正确做法：**所有角色规则都安装**，用守卫（guard）在
约束内部表达「该效果只有在 actor 真的是该角色且有效时才触发」。

### 4.2 WorldContext 不是第二个求解器

```
@dataclass
class WorldContext:
    vars:      TroubleBrewingVars     # 复用现有变量声明
    registry:  Registry               # 角色/规则注册表（见 §4.4）
    events:    tuple[Event, ...]      # 事件序列（§3），供 first_nomination_in_game 等使用
    # 只承载共享的中间量（如 alive 帧、时间索引），不承载独立求解状态

@dataclass(frozen=True)
class Registry:
    roles:  dict[str, "RoleRule"]     # role_id -> 规则模块
    services: "Services"              # 中央服务（registration / 角色变化 / 因果事件）

class Services(Protocol):
    def registers_as(self, ctx, player, category, when) -> BoolRef: ...   # 注册层通用原语
    def event_occurred(self, ctx, event_id, kind) -> BoolRef: ...
```

`WorldContext` 是**数据上下文**，最终所有约束仍 `solver.add` 到同一个 `Solver`。它不是 solver 包装器。

### 4.3 install / sink 契约（拟议）

```
class RoleRule(Protocol):
    role_id: str
    spec: RuleSpec
    def guard(self, ctx: WorldContext, actor: str, when) -> BoolRef:
        """返回该角色在该时点「能力生效」的守卫。role-specific（§4.4），不套统一 alive/healthy。"""
    def install(self, ctx: WorldContext, sink: "ConstraintSink") -> None:
        """向 sink 注册本角色的所有约束。必须无条件调用，守卫在表达式内。"""

class ConstraintSink(Protocol):
    def add_rule(self, record: "ConstraintRecord") -> None: ...
    # 细粒度便捷方法（都是 add_rule 的语法糖，不是新引擎）：
    def add_exactly_one(self, flags, *, meta) -> None: ...
    def add_implies(self, lhs, rhs, *, meta) -> None: ...
```

- **所有角色都注册**，包括「本局不太可能有」的角色；不存在「按声明身份跳过安装」。
- `install` 只**注册**约束，不直接 `solver.add`。真正落地到 Z3 由 sink 统一完成（§4.4）。
- 细粒度方法只是 `add_rule` 的便利包装，**不允许**演变成另一个通用引擎。
- 这些 `@dataclass` / `Protocol` 是**拟议接口**，直接在**现有 Z3 Solver** 上落地，**不引入新求解引擎**。

### 4.4 守卫模式：role-specific，不做统一 alive/health 守卫

**不能**给所有能力套同一个 `alive ∧ healthy` 守卫。存活与健康只是**多数主动能力**的通用前提，
不是全部角色的必要条件。必须**按角色**决定守卫：

- **死后触发 / 被动 / 设置阶段能力**：守鸦人（`ravenkeeper`）是「死亡时」触发，守卫要求**已死**而非存活；
  男爵是**设置阶段**能力（改变配置），与存活/健康无关；间谍（`spy`）的伪装、陌客（`recluse`）的误注册是
  **注册层规则**，死亡后仍可能生效，不能要求存活。
- **酒鬼/中毒者的能力**：**表面能力**与**真实能力资源**要分开。酒鬼以为自己在发动、说书人可能给假信息，
  但**没有真实能力**；醉酒的同理。守卫若写成「真角色 ∧ healthy 才允许效果」，反而会漏掉「酒鬼发动但无效果」
  这一类**必须建模**的世界。
- **死亡后的注册例外**：注册规则（间谍/陌客）以及某些结算在角色死后仍可能被查询，不能统一加 alive 守卫。

因此守卫模式是：

```
guard(actor, time) ≡
    actor.role(time) == 该角色          # 真实角色，不是声明身份
  ∧ <该角色-specific 前提>              # 可能含 alive、可能含 dead、可能含设置阶段、可能无
  ∧ <该角色-specific 健康要求>          # 主动能力通常要求 ¬disabled；被动/注册能力不要求
  ∧ actor.eligible(time)               # 该能力此时是否可发动（夜晚/白天、一次限制等）
```

**通用 alive+health 默认策略**只可作为「主动能力」的模板，且**必须能被角色覆盖**；
把它当所有角色的统一前提会破坏守鸦人（死后触发）、间谍/陌客（注册）、酒鬼（能力自知与真实资源分离）、
男爵（设置阶段）。正确做法是：角色规则在 `install` 内**显式声明**自己的守卫，中央服务只提供可复用的判断原语。

**only-if 方向的限制不变**：看到效果**不能**反推出「actor 真是该角色且健康」——
除非该效果本身在该语境下只能由该角色的有效能力产生（见 §4.6 的因果闭包）。
这正是现状许多「声明即施加效果」约束的风险所在。

### 4.5 RuleSpec 与 ConstraintRecord：可追溯

```
@dataclass(frozen=True)
class RuleSpec:
    id:           str                 # 稳定规则编号，如 "tb.virgin.trigger"
    title:        str                 # 人类可读标题
    source:       str                 # 依据：钟楼百科页面 + oldid（§12 引用方式）
    version:      str
    preconditions: tuple[str, ...]    # 触发前提的自然语言/结构化描述
    exception:    tuple[str, ...]     # 例外（如贞洁者的间谍、酒鬼）
    explanation:  str                 # 面向人工复核的说明
    testcases:    tuple[str, ...]     # 关联的测试用例 id（§4.8）

@dataclass(frozen=True)
class ConstraintRecord:
    expr:        BoolRef
    rule_id:     str
    instance:    str                  # 具体实例标签（哪一局/哪一时点）
    players:     tuple[str, ...]      # 涉及玩家 id
    time:        Time                 # 涉及时间
    input_ids:   tuple[str, ...]      # 触发/关联的请求输入 id
```

- 每个约束都带 `rule_id` + `instance` + `players` + `time` + `input_ids`。
- 因此冲突、修复、候选世界可以**指名道姓**地说「是 rule_id X 在玩家 p、时间 t 的实例」。

### 4.6 因果闭包：伪码示例（贞洁者）

**目标**：让「观察到的处决」只在存在合法原因时才能推导出结论；既不能错误地写成
`effect → guard`（把单向蕴含当成反向允许），也不能只写单向 forward 而漏掉该有的反向证据。

**术语（纠正）**：这里的「反向」是**因果闭包（causal closure）/ only-if 方向**，**不是逻辑逆否**。
逻辑上 `A → B` 已蕴含 `¬B → ¬A`（这是逆否，自动成立，无需另写）；但要禁止 `B → A`
（从效果反推原因）。因果闭包说的是：**归因给某个能力的特殊效果，只有在存在合法原因时才允许**，
即把「特殊效果」用独立变量表达，并约束 `special_effect → ∃ legal_cause`。**不允许** `effect → guard`
这种把观测当充分条件的反向推断。

```
class VirginRule:
    spec = RuleSpec(id="tb.virgin.trigger", source="贞洁者 oldid=4018", ...)

    def install(self, ctx, sink):
        for event in ctx.nomination_events:          # 事件级，见 §3
            virgin = event.nominee
            # 触发器：该贞洁者「整局」第一次被提名且该次提名有效。
            # 注意：是整局唯一，不是每天重置；参数是 nomination event 的 id，不是 day。
            first_nom = ctx.first_nomination_in_game(virgin, event)
            # 有效性：真实贞洁者 + 存活 + 健康（未中毒/醉酒）
            valid = AND(
                ctx.role(event, virgin, VIRGIN),
                ctx.alive(event, virgin),
                NOT(ctx.disabled(event, virgin)),
            )
            nominator = event.nominator
            # 提名者被登记为「镇民」（可能因间谍伪装而注册为镇民，不等于是真镇民）
            registers_townsfolk = ctx.registers(event, nominator, TOWNSFOLK)
            # 该事件的合法原因
            cause = AND(first_nom, valid, registers_townsfolk)
            # forward：有合法原因 → 提名者被立即处决（这是同一事件）
            sink.add_rule(ConstraintRecord(
                expr=Implies(cause, ctx.instant_execution(event, nominator)),
                rule_id=self.spec.id, players=(virgin, nominator), time=event.time, ...))
            # 因果闭包 / only-if：贞洁者特殊处决 → 存在某个合法原因
            sink.add_rule(ConstraintRecord(
                expr=Implies(ctx.virgin_event_execution(event, nominator),
                             Or(*all_causes_for(event, nominator))),
                rule_id=self.spec.id + ".cause", ...))
```

要点：

- **不**写 `execution ↔ trigger` 的裸双向等价；而是把「处决」与「贞洁者触发的处决」用
  独立变量（`virgin_event_execution`）分开，只有后者才与 cause 双向绑定。
- **only-if（因果闭包）方向必须有**，否则会出现「凭空处决」的模型。
- 触发判定必须**真实角色 + 有效健康**，不能只看声明。**受提名者在该事件时是真实贞洁者且有效健康**，
  且整件事发生在**纯 TB 合法事件 + 可信的特殊即时处决上下文**里，才归因给贞洁者能力。
- **「整局首次」是全局资源，不按天重置。** 触发判定必须跨天检查：该贞洁者在**本局此前任何白天**
  是否已被提名过；只有「本局从未被有效提名」的这一次才消耗。一旦消耗，之后即使没触发（中毒/酒鬼/非镇民表象）
  也**永久失去**，因为资源已用掉。
- **必须区分「真实 ability 资源」与「表象提名」。** 一个人被提名是事件；贞洁者的能力资源是否被消耗
  取决于**真实有效**的那次提名（真实贞洁者、存活、健康、提名者合法）。被伪装/误注册导致的表象
  不改变真实资源；反之真实贞洁者被有效提名即消耗资源，与当次是否因中毒而不触发无关。
- **参数用 event id，不是 day。** §3 的事件模型里 `event` 有稳定 id 与顺序；`ctx.first_nomination_in_game`
  比较的是提名事件序列，避免「同一天多次提名」或「按天索引」造成的误判。
- **人审与规则卡必须同一口径**（§13.1）：`first_nomination_in_game` 的语义在代码、RuleSpec 与规则卡里
  用同一句话描述「本局第一次被提名，之后永久失去能力」。

### 4.7 中央服务：避免角色模块互相 import

- 角色 → 角色 的交叉效果（登记为特定角色、因果事件、角色变化）通过**中央服务/注册表**表达，
  而不是让 `A.py` import `B.py` 互相调用。
- 例：间谍/陌客的 registration 是通用服务（现状 `_registers_*` 系列），贞洁者的「提名者登记为镇民」
  调用它；猎手的「目标登记为恶魔」也调用它。这些服务集中在一处，规则模块只声明意图。
- **禁止**散落的、无来源的 `solver.add(...)`；一切经 sink 且带 RuleSpec。

### 4.8 人工审核与测试（规则人审表）

每个 `RuleSpec` 配一张**规则人审表**（可放在规则模块 docstring 或单独 `AUDIT.md` 片段）：

| 字段 | 内容 |
| --- | --- |
| 规则编号 | `tb.virgin.trigger` |
| 依据 | 钟楼百科 + oldid |
| 前提 | 首次被提名、提名者是镇民（含间谍伪装） |
| 例外 | 提名者是酒鬼（外来者）、贞洁者中毒/醉酒、已死玩家提名无效 |
| 代码位置 | `rulebook/roles/virgin.py` install |
| 测试 | 正向 / 负向 / 异常 / 时间边界 / 两角色交互 |

测试类型必须覆盖：**正向**（该触发时触发）、**负向**（不该触发时不触发）、**异常**（酒鬼/中毒/间谍）、
**时间**（首夜无、跨天唯一）、**两角色交互**（贞洁者 × 间谍、贞洁者 × 酒鬼、猎手 × 红唇女郎）。
详见 §10。

### 4.9 迁移策略：巨 rules.py 保留入口，不双加载

- 保留现有 `add_game_rules` 作为**唯一入口**，其内部可选择「旧实现」或「新角色模块」，
  但**同一次求解绝不两者都加载**（避免重复约束与语义打架）。
- 迁移顺序：先建立 sink + RuleSpec + 元数据（**只记录不改变约束语义**），验证元数据正确，
  再逐角色把 `rules.py` 中的约束块搬进角色模块（§11 阶段）。
- 旧巨 `rules.py` 中的约束块一旦搬走就从入口移除，不做「新旧并存兼容期」。

---

## 5. 冲突与原因：MUS 与背景矛盾分类

### 5.1 MUS 是 inclusion-minimal，不是最少数条

现状 `conflict.py` 返回的是**极小（不可再删）子集**，不是**最少条数**子集。两者不同：

- inclusion-minimal：去掉其中任意一条都不再矛盾，但**条数可能不是最少**。
- minimum cardinality：所有不可满足子集中条数最少的那个。

本设计**继续使用 inclusion-minimal**（代价低、足以解释），但必须在输出与文档里如实标注
`minimality: "inclusion"`，**不得**暗示或宣称「最少条」。

**inclusion-minimal 的验证范围仅限于「背景 + 该 core 子集」内部。** 也就是说，「去掉 core 中任意一条后
不再矛盾」这一性质，是在 `B ∧ core` 这个子问题上验证的，**不**意味着把它放回**完整的 `C*`** 后仍然成立：

- 一个不可满足问题**可能有多条 MUS**。删掉当前 core 的一条，剩下的可撤销项仍可能命中**另一条** MUS。
- 因此**不能**从「该条在 core 内是必要的」推出「withdraw 这一条以后整体就 sat」。
- 任何修复候选都必须回到**完整原问题（whole problem，即完整的 `B ∧ C*`）**重新验证 sat（§6.6）。

引用旧说法时注意：不存在「删掉 core 一条后全 C 就 sat」这种保证；只有「在 B + core 子集内，删掉它即可 sat」。

### 5.2 冲突要跟踪规则、公共事件、可撤销项

现状只跟踪输入（input_ids），`rule_ids` 恒为空（`connector._reason` 里 `"rule_ids": []`）。
目标：MUS 要能说明冲突涉及哪些**规则**、哪些**公共事件**、哪些**可撤销项**：

```
Conflict {
  input_ids:  tuple[str, ...]     # 输入（公共事件 / 可撤销项）
  rule_ids:   tuple[str, ...]     # 真实跟踪到的 RuleSpec.id
  public_ids: tuple[str, ...]     # 涉及的 P
  assumption_ids: tuple[str, ...] # 涉及的 C
  minimality: "inclusion" | "cardinality"
  core_kind:  "conditional" | "public"   # 冲突发生在哪条轨道
}
```

### 5.3 背景矛盾分类：rule/model vs P 矛盾

公共背景 `public=R∪P`（或条件背景 B）unsat 时，先分类矛盾来源，再决定怎么修：

1. **规则内部/模型错误（rule/model）**：R 自身不一致，或 R 与变量编码冲突。
   这是**代码/建模 bug**，不应试图通过删事实「修复」，应报给开发者。
2. **P 与 P 矛盾**：两条可信公共事件互斥（例如同一夜公布 p1 死亡、又公布 p1 存活）。
   通常是**录入错误**，修复＝让用户核对哪条错。
3. **P 与 R 矛盾**：公共事件违背剧本硬规则（例如公布的死亡名单违反「至多一名夜晚死亡」而没有对应解释）。
   可能是录入错，也可能是**模型缺规则**（如漏了某个允许例外的角色）。

> **public 轨道矛盾不可推任意命题。** public 冲突时 public 轨道返回 `inconsistent`（§2.3、§2.4），
> 不得据此声明任何 public 结论；若 public 仍 sat 而仅 conditional 轨道矛盾，则 public 结果照常返回。

拟议诊断入口在 §9，分类结果驱动 §6 的修复候选。

### 5.4 条件核（conditional core）重验

采信 C* 后若 `B ∧ C*` unsat，要在**条件语境**下重求 MUS，并**再次验证 core 仍包含可撤销项**：

- 去掉 core 中任一 C* 项后 `B`（用剩余 C）是否 sat（即该项是**该 core** 的必要成员）。
- 按 **source 模板**生成解释：说明「若撤销 C 项 c，**在这个 core 内**矛盾消失」——表述必须限定在 core 内，
  因为可能还有其他 MUS（§5.1、§6.6），撤销单条不保证整体恢复 sat。
- 解释文案走模板 + 可追溯字段，**不得用 LLM 生成「证明」**（LLM 只可做措辞润色，
  不能作为逻辑依据）。

---

## 6. 最小修复（repairs）

### 6.1 目标：最少变更，不是最少条数

「最小修复」指**最少的变更代价**：撤销/替换哪些可撤销项，使 `B ∧ C*` 重新 sat。

#### 6.1.1 owner group gate：按「提出者」分组，但不无差别撤回

修复的变更单位是**声明所有者 owner**（谁说的，见 §1.3），不是单个约束。定义：

- **owner group**：同一 owner 提出的一组声明（身份 claim + 该 owner 的能力信息 + 指向别人的声明）。
- **group relax gate**：只有当某 group 被 gate 打开（该 owner 被列为本次修复的变更对象）时，
  才**允许**变更其**可撤销的身份 claim（belief/self claim）**。
- **gate 打开 ≠ 撤回该 owner 全部信息**。撤回权限**仅限身份 claim**；**不得**顺带撤回：
  - 该 owner 的**能力信息/观察**（例如他报告的厨师数字、占卜师答案——那是收到的观察内容，不是身份），
  - 该 owner **指向别人**的声明（target 是别人，撤回它会错误地抹掉对第三方的信息）。
- 撤回某人的身份 claim 后，其余保留项构成 **retained claims**：
  `retained(group) = group \ (被显式撤销的身份 claim)`。求解时只在 `B ∧ retained` 上检查。

#### 6.1.2 cost 是字典序，不是条数

```
cost = lexicographic( changed_players, changed_claims )
```

- **第一关键字**：被触及的 **owner（玩家）数量** `changed_players`——影响最少的人优先。
- **第二关键字**：在该人数下，被变更的 **claim 数量** `changed_claims`。
- 用 **Optimize** 求最小值，并区分：
  - **`optimal`**：Optimize 证明已无更小 cost（求解器给出最优性证明）。
  - **`unknown`**：未证明最优时如实标注，不能假装。
- **最小删除（withdraw）与身份替换（replacement）是不同操作**，不可互相等同：
  - withdraw：把 claim 移出本次推理，不施加否定（§6.3）。
  - replacement：把「p 自认 X」换成「p 自认 Y」（走 belief，§6.4）。
  - **withdraw 一条 claim 不等于说该玩家在撒谎**（§6.5），它只是「本次不再采信」。

#### 6.1.3 「最少身份不同」看 belief self claim，不看全部 C

- 当目标是「最少的身份差异」时，只比较**每个玩家的 belief self claim**（各人自认身份的冲突计数），
  **不是**把全部 C（含各方收到的观察、指向别人的声明）一起算进身份差异。
- 能力观察/第三方指向的错误应归到**信息层**（中毒/醉酒/误报），与「身份不同」分开计数。

- candidate relax **只针对 C（可撤销项）**。**绝不删除 R∪P 中的公共事件**（现有公共已确认观察不能为了让模型好过而抹掉）。

### 6.2 求解方式

- 首选 **MaxSAT / Optimize**：把「保留假设」当软约束，最小化 §6.1.2 的**字典序 cost**
  （先最小化 `changed_players`，再最小化 `changed_claims`）。
- 或**分组 cardinality 递增**：从 k=0 起逐步增大「最多可变更的假设数」，第一个 sat 的 k 给出一个
  修复；继续证明更小的 k 不可行以获得 **optimal lower bound**。
- 若无法证明最优，必须标注 `optimality: "unknown"`，不能假装最优。

```
Repair {
  changes:   tuple[Change, ...]   # 撤销/替换了哪些假设（§6.1.1 group relax）
  cost:      tuple[int, int]      # (changed_players, changed_claims)，字典序
  optimality: "optimal" | "unknown"
  lower_bound: tuple[int, int] | None
  witness:   ...                  # 修复后的一个满足解（在**完整原问题**上验证，§6.6）
}
```

### 6.3 删除与替换要区分；撤回 role claim 不自动写 ¬role

- **withdraw（撤回）**：把某假设移出本次推理（回到「未采信」），**不**对世界施加任何否定。
- **replacement（替换）**：把「p 自认 X」替换为「p 自认 Y」。
- **撤回一条 role claim 时，不得自动添加 `¬(p 是 X)`**。世界可能仍然 p 是 X，只是我们不再采信该声明。
  这是常见错误：把「撤回采信」误当「证明为假」。

### 6.4 采信 claim 走 belief；显式「真实身份」排除 drunk

两条命题必须用**不同**变量，不能互相替换：

- **只有 `reported` 角色 claim（玩家自述）映射为 belief。** 采信它约束的是**自认身份（belief）**，即「p 认为自己是调查员」。
  这**允许**两种世界：p 真是调查员，**或** p 是拿着调查员标记的酒鬼（`drunk_mask=调查员`）。
  采信 claim **不能**自动等价于断言 p 的真实角色，**更不能**排除酒鬼分支。
- **`confirmed` role 命题不改变映射：仍然映射真实命题**（保持现状兼容），**不默默改成 belief**。
- **显式「真实 role 假设」**（用户**明确**把某条当真实 role 假设时）：约束 `role(p)=调查员`。
  真实角色是调查员即 `start_is(p, 调查员)`，**排除** p 是酒鬼（`is_drunk[p]` 为假），
  也就排除了 `drunk_mask` 分支。

因此修复/替换时：

- 把「自认角色」替换为另一种自认，仍走 belief，保留酒鬼语义（不破坏 `drunk_mask`）。
- **不得**把「p 自认调查员」的采信悄悄提升为「p 真是调查员」——那会错误地排除酒鬼。
- 反之，一旦命题确实断言了真实身份（`role` 层，而非 belief 层），就要**正确地**推出 `¬is_drunk[p]`，
  不能再保留「拿着调查员标记的酒鬼」这一分支。这是与旧写法相反的方向（见 README「声明与启用开关」）。

### 6.5 「最少玩家」≠「最可能撒谎」

最小修复给出的是**全局最优的候选**，**不承诺唯一**，也**不等于最可能的真相**：

- **善良玩家也会撒谎/打掩护**（善良的骗术、戏精）。
- 可能是**错误录入**（用户填错）。
- 可能是**中毒/醉酒**导致信息错误（见 §1、README 关于 drunk/poison）。
- 因此结果表述为「在这些假设下，代价最小的撤销集合是 ...」，而非「谁在撒谎」。

### 6.6 多 MUS 与 hitting set

- 一个不可满足背景可能有多条 MUS。要枚举多条 MUS，用它们的 **hitting set** 作为修复候选。
- **每个候选修复都要在完整原问题（whole problem）上重新 sat 验证**，不能只在子集上验证。
- 返回的候选要包含 `alternative changes`、受影响的 facts/state guard，以及 `witness`。

---

## 7. 假设的推荐（hypotheses）

### 7.1 两个可推荐的动作

1. **deletion / recovery（撤销后恢复）**：撤销某条已采信的可撤销项可消除矛盾。
2. **新增可撤销项（new assumption）**：**不能**直接修复 unsat。

### 7.2 单调性：新增可撤销项不能修复 unsat

设当前条件背景 `B ∧ C*` unsat。加入新可撤销项 a 得 `B ∧ C* ∧ a`，仍是 unsat 的**子集扩张**，
不可能变 sat。因此：

- 想通过「多相信一件事」来消除矛盾是**错误的**。
- 必须先 **withdraw** 某可撤销项（回到更弱的背景），才可能恢复 sat。
- 推荐引擎只推荐「撤销/替换」，**不推荐「新增来消除矛盾」**。

### 7.3 sat 时可分支：necessary / possible / unknown

背景 sat 时，对一条尚未采信的可撤销项 a：
- `B ∧ a` unsat → a 与背景不相容（可报告为「采信会矛盾」）。
- `B ∧ a` sat 且 `B ∧ ¬a` unsat → a 在当前背景必然。
- 两者都 sat → a 是 possible，可列出其支持证据（§7.5）。

### 7.4 information gain：无概率模型，不装概率

- 本模型**没有概率**。不得输出「某项成立概率 60%」之类数字。
- `information_gain` 只表示**信息量/区分度**（例如：采信某可撤销项后能排除多少候选世界），
  必须标注为**非概率**。
- **在 partial 枚举（未完整列出世界）下，信息增益只能定性，不能精确排名。** 如果候选世界被
  `max_worlds`/`deadline` 截断（§8.4），就**不能**据此宣称「假设 A 比假设 B 信息量更大」，
  更不能折算成百分比。此时只能给方向性描述（如「A 至少排除了 N 个已枚举世界」），
  并标注 `complete=false`，**不得**输出精确名次或概率。

### 7.5 新增项不能伪成 public

- 新增的可撤销项只进入 C，**永远不能**变成 public（`R∪P`）。除非用户把它按 §1.2 显式升级为 public
  （必须 `status=confirmed` 且显式 `reasoner:scope="public"`；`reported` 不允许升级）。
- 推荐时要返回**条件支持证据**：采信 a 之后，哪些结论变为必然、依据哪些 rule_ids/input_ids。

---

## 8. 候选世界（worlds）与枚举

> **默认不做全量世界枚举。** 联合世界数随玩家数组合爆炸，**`complete=true` 的全枚举不是默认行为**。
> 默认返回的是**每玩家 range**（§8.1，逐组合存在性测试，代价可控）；全量/限量联合世界枚举是**可选能力**，
> 由调用方显式开启 `max_worlds`/`deadline`。**range 优先、枚举按需**。

### 8.1 roles range 独立存在、独立测试

- 每个玩家的角色候选是一个**独立的 range**（可能角色的集合）。
- 对每个 (player, role) 组合用 **存在性测试**（`check(B ∧ role(p) == r)`）判定，而不是从一个解里读。
  原因：一个解只给出**每个玩家各一个**角色（是该玩家众多可能之一），**读不出**「该玩家还能是什么」的完整集合。
  故 range 必须靠 `exists` 测试（`B ∧ role(p)==r` 是否 sat）得到，而非从单解抄。
- **unknown 必须独立分类，不能混入已证的 possible。** 某次求解返回 `unknown` 时，该角色**不**能作为
  已证明的 `possible`；要单列到 `unknown_roles`（或置该候选的 `status="unknown"`），与 proven
  `possible_roles` **分开**。只有 sat 才算「已证可能」；unsat 算「已证不可能」；unknown 是第三类。
- **partial flags**：若枚举过程中出现 any `unknown` 或提前停止，必须置
  `partial=true` + `truncated_reason`。

### 8.2 逐玩家候选的笛卡尔积不是联合世界

- **一个模型可以一次性读出所有玩家**：`model.eval(...)` 给出的是**同时选定**的一整套赋值，
  这是一个**合法世界**。**不存在**「一个解不能读组合」这种说法——从一个模型读取全体玩家是正确的一组合法赋值。
- 但反过来：把「每个玩家各自某次 SAT 里出现的角色」按玩家**拼接**成的笛卡尔积，**不**保证构成一个合法世界
  （各玩家的局部选择可能互相冲突）。**逐玩家候选（8.1 的 range）不能当作联合世界的枚举。**
- 因此枚举**联合世界**必须靠逐模型 + blocking：
  - 每求出一个模型，读取其**完整投影**（一次读出所有玩家），加入 blocking clause 阻断该投影，再求下一个；
  - 对每个 (player, role) 组合独立 `push/check/pop` **只用于 range**（8.1），**不用于**联合世界。
- 联合世界与 per-player range 是两类不同产物，不能混为一谈。

### 8.3 worlds 的投影（projection）

- 枚举出的是**世界**，需要投影到**指定时间**的角色赋值：
  `setup` / `current` / `history` 各自的投影不同。
- **block projection 去重**：对同一次投影，用 blocking clause 阻断已枚举的**完整投影**，
  避免「隐藏目标不同但投影相同」造成的重复计数。

```
WorldProjection {
  time:  Time
  roles: { player_id -> role_id }   # 该时间断面
  alignment?: ...
}
```

### 8.4 max_worlds、deadline、complete / truncated_reason

```
WorldsResult {
  worlds:    tuple[WorldProjection, ...]
  complete:  bool
  returned_count: int               # 已经返回的世界数
  truncated_reason: str | None      # "deadline" | "solver_unknown" | "max_worlds"
  total:     int | None             # 仅 complete=true 时才有精确值
  lower_bound: int | None           # partial 时的下界（= returned_count）
}
```

- 设 `max_worlds`（数量上限）与 `deadline`（时间上限）。**`max_worlds` 不是 `min_limit`**：
  它是「最多枚举这么多个」的**上限**，不是「至少枚举这么多个」的下限。达到上限即停，是 `truncated`。
- **枚举在一个「工作 solver」上进行**：它在原背景上不断 `add` blocking clause 阻断已枚举投影。
  所以**结束时的 unsat 是这个工作 solver（背景 + 累积 blocking）再无剩余投影**的 unsat，
  **不是**「原背景 unsat」。两者含义不同：
  - 原背景 unsat → 一个世界都没有（空枚举，且是矛盾）；
  - 工作 solver 在原背景 sat 的前提下被 blocking 到无解 → 枚举**完整**。
- **只有枚举正常结束**（工作 solver 在全部 blocking 后 unsat，即「无更多投影」）才算 `complete=true`。
  达到 `max_worlds` 上限、`deadline` 超时、或中途 `unknown` 均为 `truncated`，`complete=false`。
- **`total` 只在 `complete=true` 时精确**。`partial` 时不给精确总数，只给
  `returned_count`（已返回数）与 `lower_bound`（至少这么多）；不得把 `returned_count` 当 `total`。
- **`total` 无概率**：它是**计数**，不是概率，也不代表每种世界等可能。

---

## 9. 结果与解释（results / explanations）

### 9.1 public 与 conditional 分开

结果层必须同时给出两类，并**各自带依据**：

```
Conclusion {
  query_id:   str
  status:     "necessary" | "possible" | "impossible" | "inconsistent" | "unknown"
  modality:   "public" | "conditional"     # public: 基于 R∪P；conditional: 基于 B=public∪C
  supports:   ConditionSupport | None       # conditional 时的可撤销项支撑
  confidence: "proven"                       # 本模型只有证明，没有概率
}

ConditionSupport {
  assumption_ids: tuple[str, ...]   # 被采信的 C*
  rule_ids:       tuple[str, ...]   # 用到的规则
  input_ids:      tuple[str, ...]   # 用到的输入
  time:           Time
  scope:          "public" | "conditional"  # 结论轨道（只有这两个取值）
}
```

### 9.2 witness / counterexample

- `necessary` 应给出（或可请求）**witness**：至少一个满足 `R∪P`（public）或 `B=public∪C`（conditional）且 q 为真的解。
- `impossible` / `possible` 应能给出 **counterexample**：q 为假（或真）的一个解。
- 模型只有一个满足解不等于唯一；witness 只是**一个**例子。

### 9.3 confidence 是状态，不是概率

`confidence` 只取 `proven` / `unknown` 之类**离散状态**，**没有**百分比。
不得输出「73% 确定」。

### 9.4 core / proof 解释的适用范围

- **`core`（MUS）只能解释背景/条件矛盾本身**，即说明「这些输入（及其规则）互相冲突」。
  它**不能**用来解释任意命题 q 的结论。
- `proof` 与 `¬q` 的证据**只在特定方向成立**：当对应轨道 sat 且 q 为 `necessary` 时，该轨道背景 ∧ ¬q
  unsat 可以作为「q 必然」的证据（说明不存在 ¬q 的解）。此时这个 unsat 的证据**不能**反过来用于
  「背景 unsat 下的任意结论」——背景 unsat 时任意命题都可被空真推出，证据无意义（§2.4）。
- 对 `inconsistent`（**该轨道**背景 unsat）：
  - 给 `core`（MUS，§5）与只描述**该矛盾**的 `proof` 结构：依据 = 支撑该矛盾的
    `R + P + C 子集`，且说明**是它们之间**互相矛盾。
  - **不得**用这个 core 去声明任何**与该矛盾无关**的查询结论（例如「因为背景矛盾所以 p 是恶魔」）。
    public 轨道 unsat 时 public 冲突返回 `inconsistent`，**不可推任意命题**；该轨道查询一律
    `unknown`/`inconsistent`（§2.4），不给出结论性 witness。若 public sat 而仅 conditional 轨道 unsat，
    仍返回 public 结果（§2.3）。
- 解释必须可追溯到 rule_ids / input_ids；**LLM 只做措辞，不作为证明**。

---

## 10. 网页协议扩展（拟议字段，非已实现）

> **重要：本设计不宣称协议已增加这些能力。** 下面是**拟议形状**，需与
> `web/protocol/types.ts` 和 `web/protocol/README.md` 同步评审后才可能落地。
> 现状协议见 §12；扩展一律用命名空间（`reasoner:*`）避免冲突。

拟议在响应 `extensions` 下增加命名空间字段（均以 `reasoner:` 前缀）：

```
extensions: {
  "reasoner:diagnosis": {
    kind: "public" | "conditional",
    classification: "rule_or_model" | "public_conflict" | "public_rule_conflict",
    core: { input_ids, rule_ids, public_ids, assumption_ids },
    minimality: "inclusion" | "cardinality"
  },
  "reasoner:conclusions": [
    { query_id, status, modality, supports, confidence }
  ],
  "reasoner:worlds": {
    worlds: [WorldProjection],
    complete: bool,
    returned_count: int,
    truncated_reason: str | null,
    total: int | null,
    lower_bound: int | null,
    time: Time
  },
  "reasoner:repairs": {
    candidates: [Repair],
    optimality: "optimal" | "unknown",
    lower_bound: int | null
  },
  "reasoner:completeness": "complete" | "partial",
  "reasoner:timeout": { overall_ms, per_solve_ms, hit: bool },
  "reasoner:optimality": "optimal" | "unknown"
}
```

输入侧另用命名空间字段标注某条目的求解轨道（**只有两个取值**）：

```
extensions: {
  "reasoner:scope": "public" | "conditional"   // 默认分类：confirmed night deaths / settled day vote → public，其余 → conditional
}
```

约定：
- **回显 `request_id` / `game_id` / `revision`**（现有响应已有，沿用，用于丢弃旧响应）。
- `query` 状态沿用现有 `QueryStatus`（`possible`/`necessary`/`impossible`/`inconsistent`/`unknown`）。
- **`reasoner:scope` 只有 `public` / `conditional`。** 升为 public 必须同时 `status=confirmed` 且显式
  声明 `reasoner:scope="public"`；`reported` 不允许升级 public（公开说了不等于内容真）。
- 逻辑 `unsat` 与 HTTP 错误严格区分（沿用现状）。
- 所有拟议字段都必须能带**依据 id**（rule_ids/input_ids），否则不落地。

---

## 11. 目标目录与迁移阶段（8h MVP + 后续）

### 11.1 目标目录（拟议）

```
botc_reasoner/
  roles.py            # 现状：静态角色/配置（保留）
  variables.py        # 现状：变量声明与域公理（保留）
  rules.py            # 现状：巨型规则；迁移后仅保留 add_game_rules 入口（模块）
  conflict.py         # 现状：MUS（保留，补 rule_ids 跟踪）
  DESIGN.md           # 本文（拟议架构）
  README.md           # 现状说明（保持事实描述）
  rulebook/           # 拟议：新规则组织（**不叫 rules/**，见下）
    __init__.py       # 注册表 + install 调度（不双加载）
    sink.py           # ConstraintSink / ConstraintRecord
    context.py        # WorldContext / Registry
    spec.py           # RuleSpec / RuleAudit
    services.py       # 中央服务：registration / 角色变化 / 因果事件
    roles/
      virgin.py       # 贞洁者规则模块（示例）
      slayer.py       # 猎手规则模块（示例）
      ...
    world/            # 拟议：世界/时间轴子模块（现 rules.py 的对应内容）
      setup.py        # 开局配置、男爵、酒鬼标记
      timeline.py     # 时间轴推进、身份/存活延续
      death.py        # 夜间击杀、保护、星坠、镇长转移
      vote.py         # 提名、投票、处决、贞洁者触发
  compiler/           # 拟议：约束编译流水线
    __init__.py
    compiler.py       # constraint compilation：把 RuleSpec/角色模块编译打包给 sink
  analysis/           # 拟议：分析服务
    __init__.py
    service.py        # pipeline 编排：背景求解 → 查询 → 诊断
    conflict.py       # MUS 分类 + 条件核
    repairs.py        # MaxSAT / 分组 cardinality
    hypotheses.py     # 推荐（§7）
    worlds.py         # 枚举与投影（§8）
```

> **命名约束（重要）：新规则包不能叫 `rules/`。** 现有 `rules.py` 是模块，若新建同名 `rules/` 包，
> Python 导入 `botc_reasoner.rules` 时**包会遮蔽模块**（package 优先于 module），导致现有入口被替换、
> 迁移期出现「新旧同时可导入」的歧义。因此新包命名为 `rulebook/`（或 `rulesets/`）。
> `roles.py`（角色静态数据）与新的 `rulebook/roles/`（角色规则模块）是不同名，不冲突。
>
> **保留旧入口**：`rules.py` 仍暴露 `add_game_rules` 作为**唯一兼容入口**，内部可委托到 `rulebook`，
> 但**绝不双加载**（§4.9）。`world modules`（`setup/timeline/death/vote`）与角色 composer
> 都通过这个旧入口被调度，避免调用方同时改两处。

> 也可以先不建 `rulebook/` 子包，把 `sink.py`/`spec.py`/`context.py` 放在 `botc_reasoner/` 顶层。
> **以最小改动可审阅为优先**，目录结构服务于「角色一模块、可追溯」，不是目标本身。
> 但无论放哪，**都不得出现与 `rules.py` 同名的包**。

### 11.2 8h MVP 阶段（优先，含验收标准）

| 阶段 | 内容 | 验收标准 |
| --- | --- | --- |
| **A. partial flag 修复** | `_possible_roles` 遇 `unknown` 或超时置 `partial` + `truncated_reason`（README 已列为待修正） | 构造会返回 unknown 的用例，输出 `partial=true`；正常用例 `complete=true` |
| **B. 事件/原因数据** | fact 增加 `reasoner:scope`（public/conditional）；事件因果步骤字段（§3）；至少「结算→公布」两步 | 请求可携带并回显；不破坏现有三类扩展 |
| **C. 规则审计元数据** | 建 RuleSpec/RuleAudit；先**只记录**现有约束的 id/title/source，不改语义 | 规则人审表可导出；约束可与 rule_id 对应 |
| **D. 诊断** | diagnosis（MUS 分类）+ repairs（只动 C）+ worlds（逐组合枚举 + partial） | 背景 unsat 分类正确；repair 候选在原问题重验证；worlds 有 complete 标志 |

### 11.3 后续阶段

- 把 `rules.py` 约束逐角色搬进 `rulebook/roles/*`，入口切换（不双加载）。
- 事件级 time 全面替换断面近似。
- 条件核重验、MUS hitting set、MaxSAT 最优性证明。

### 11.4 目录职责：compiler 与 analysis 的分工

目前设计缺「世界规则」与「编译/分析流水线」的归属，补明确分工：

- **`rulebook/world/`**：只负责**世界规则**（setup / timeline / death / vote），即「世界如何运转」
  的客观规则；不含角色专属能力（那些在 `rulebook/roles/`）。
- **`compiler/compiler.py`（constraint compilation）**：把 `rulebook` 的规则模块
  （角色模块 + world 模块 + 注册表）**编译打包**成一组 `ConstraintRecord`，交给 `ConstraintSink`。
  它是「注册 → 落地」的中间层，**不**做求解、不做诊断、不引入新引擎。
- **`analysis/service.py`（pipeline 编排）**：调用 **同一个 Z3 Solver**，按阶段编排
  「背景求解（含 public/conditional 两轨）→ 查询 → 诊断 → 修复 → 候选世界」，
  输出带依据的结果。它**只编排**，具体算法在 `analysis/conflict.py`、`repairs.py`、
  `hypotheses.py`、`worlds.py`。
- 依赖方向：`analysis` → `compiler` → `rulebook` → `variables.py`，**单向**，不反向 import。

---

## 12. 已知限制的引用方式（不复制）

本文**不重复** README 中会过时的清单。凡涉及「当前实现限制 / 待修正」，一律引用：

- [`botc_reasoner/README.md`](README.md) 的「当前限制 / 待修正（先读）」一节。
- [`../connector.py`](../connector.py) 及其在 README 中的使用说明。
- [`../backend/README.md`](../backend/README.md)、[`../web/protocol/README.md`](../web/protocol/README.md)。

本文只补充**设计层面**的已知约束（这些不是「现状 bug」，而是规划的边界）：

1. 事件级 time 尚未实现，当前以 `night_start`/`dawn`/`after_last_day` 断面近似。
2. `reasoner:scope` 尚未进入协议；当前所有条目一律按硬约束、且不区 public/conditional。
3. `rule_ids` 跟踪尚未落地（现状冲突只给 input_ids）。
4. 概率、最优性证明、完整枚举仍未实现（§7、§8、§9 只给拟议语义）。
5. 本模型**只有暗流涌动（Trouble Brewing）**，无旅行者、无其他剧本。

## 13. 规则示例卡（供人工复核）

> 示例用于说明「规则人审表 + 因果闭包」的写法，**描述的是规则本身**（依据钟楼百科），
> 代码接口为拟议。规则细节核对：§12 的 oldid 引用。

### 13.1 完整贞洁者（Virgin）规则卡

**规则编号**：`tb.virgin.trigger`
**依据**：钟楼百科「贞洁者」oldid=4018
**能力**：当你首次被提名时，如果提名你的玩家是镇民，他立刻被处决。

**触发条件**（全部满足才触发）：
1. 这是该贞洁者**整局第一次**被提名（跨所有白天、按提名事件顺序判断，**不是**每天重置；
   之后即使没触发也永久失去能力）。
2. 发起提名的玩家**不是已死玩家**（死人不能发起提名）。
3. **受提名者（贞洁者）在该事件时是真实贞洁者**，且**有效健康**（未中毒、未醉酒）。
4. 提名者被**登记为镇民**。注意：**间谍**可能登记为镇民（这是唯一能触发贞洁者能力的邪恶角色）；
   **陌客**的邪恶伪装使他**不**算镇民。
5. 事件处于**纯 TB 合法事件**且是**可信的特殊即时处决**上下文（不能把普通投票处决混进来）。

**例外与边界**：
- 提名者是**酒鬼**：他是外来者（即使自认镇民），**不触发**。
- 贞洁者自己中毒/醉酒：**不触发**，但仍会失去能力（隐性规则）。
- 已死玩家提名：提名无效，贞洁者**不**失去能力。
- 即便触发，**立刻处决**并**结束当天白天**（不再进行其他处决）。
- **真实能力资源 vs 表象**：能力是否被消耗取决于**真实有效**的提名（真实贞洁者 + 存活 + 健康 + 提名者合法）；
  中毒/伪装造成的表象不改变真实资源（§4.6）。

**因果闭包要点**（§4.6）：
- 正向：`first_nom ∧ valid ∧ registers_townsfolk → virgin_event_execution(nominator)`。
- **因果闭包（only-if，不是逻辑逆否）**：`virgin_event_execution(nominator) → ∃ 合法原因`
  （不能凭空出现贞洁者处决）。逻辑逆否 `¬effect → ¬cause` 由 `A→B` 自动蕴含，无需另写；
  这里禁止的是 `effect → guard` 这种从效果反推原因。
- **不写** `execution ↔ trigger` 裸等价；处决与「贞洁者触发的处决」是两个变量。

**测试**：
- 正向：普通镇民提名贞洁者 → 提名者被立即处决，当天结束。
- 负向：外来者/爪牙/恶魔提名 → 无事发生，流程继续。
- 异常：酒鬼提名（不触发）；中毒贞洁者被镇民提名（不触发但仍失去能力）。
- 时间：跨天只触发一次；首夜无。
- 交互：贞洁者 × 间谍（间谍伪装镇民可触发）、贞洁者 × 酒鬼（外来者不触发）。

### 13.2 猎手（Slayer）示例卡

**规则编号**：`tb.slayer.shot`
**依据**：钟楼百科「猎手」oldid=6237
**能力**：每局限一次，白天公开选择一名玩家；若他是恶魔，他死亡。

**因果闭包要点**：
- **公开且立即成功**（目标当场死亡）时，才可归因：**actor 是有效真实猎手**，
  且 **target 被登记为恶魔**（可能是**小恶魔 Imp**，也可能**陌客 Recluse**）。
- **声明射击本身、或任意死亡，都不能倒推**「actor 是猎手」或「target 是恶魔」：
  - 猎手打中陌客 → 陌客被当作恶魔而死亡（target 不真是恶魔）。
  - 玩家可冒充猎手。（现状 README「技能发动记录」已述：声明者若不是该角色，或中毒/醉酒，则无效果。）
- 已死玩家不能再次死亡；打已死小恶魔无事发生。
- 猎手击杀**不是处决**；送葬者只看处决。

**测试**：正向（打中恶魔死亡）、负向（打善良无事）、异常（中毒/醉酒猎手宣告后失去能力但不致死）、
时间（白天先后与处决的因果，§3）、交互（猎手 × 红唇女郎转化后的身份判定）。

### 13.3 其他关键规则的设计注记（非完整卡）

- **酒鬼 / 中毒**：**无能力**，但**信息可能巧合正确**。因此**不能**由「信息正确」反推「健康」，
  也不能由「信息错误」反推「不健康」。现状 README 已强调信息是「收到的内容」。
- **镇长 redirect**：说书人**可以**改杀他人，是选择而非必然；与僧侣保护、健康士兵免疫并列。
- **星坠 / 红唇女郎**：角色**变化**要作为事件记录（§3），占卜师对两枚小恶魔标记都可能得「是」。
- **execution != death**：处决是事件，死亡是状态变化；纯 TB 可简化，但**必须限定 scope**。
- **公开公布存活/死亡可信，而死因未确认不可自动赋**：公布「谁死了」是 public 事件（night deaths /
  settled day vote 默认分类），但「死于恶魔击杀/死于猎手/死于处决」若未公布，不得自动认定。

## 14. 术语与不变量（速查）

- 结论只有两类：public 必然（R∪P）与 conditional 必然（B=public∪C）。R 硬、P 公共事件硬不可自动撤销、
  C 可撤销（采信后本次求解为硬）。`confirmed` 不自动 public；public 默认只由 confirmed night deaths /
  settled day vote 分类，其他需显式 `reasoner:scope="public"` 且 `status=confirmed`；`reported` 不允许升 public。
- source（`received`/`self_claim`/`assumption`）只用于展示与修复追溯，不是独立语义轴。
- public 背景 `public=R∪P` 与条件背景 `B=public∪C` 是**两条独立轨道**：一方 unsat 不必然使另一方 unknown。
- 该轨道背景先 sat；再算条件结论；unsat 时不空真爆炸（public 冲突返回 `inconsistent`，不可推任意命题）；
  unknown 分支单独处理；public sat 但 conditional unsat 仍返回 public 结果。
- 只有 `reported` role claim 走 **belief**（允许酒鬼）；`confirmed` role 仍旧映射真实命题保持兼容，
  不默默改 belief；用户明确声明真实 role 假设时才走真实 role。显式真实身份命题才排除酒鬼（§6.4）。
- 所有角色规则无条件安装；守卫**role-specific**（不统一 alive/healthy）：死后触发、设置阶段、
  注册例外、酒鬼能力自知都要被覆盖。
- 贞洁者「首次被提名」是**整局**资源（event 级，不按天重置），区分真实能力资源与表象。
- 每条约束带 rule_id/instance/players/time/input_ids。
- 冲突是 inclusion-minimal，仅在 `B∧core` 内验证，**不保证** withdraw 单条整体即 sat；
  修复只动 C、不删 R∪P 中的公共事件，候选必须在**完整原问题**上重验。
- 修复 cost 字典序 `changed_players → changed_claims`；group relax 只放开身份 claim，
  不无差别撤回能力信息/他人指向；withdraw ≠ 说谎。
- 联合世界不能由 per-player range 笛卡尔积拼出；unknown 独立分类，不混入已证 possible。
- worlds `complete` 指**工作 solver（背景+blocking）无剩余投影**，不是原背景 unsat；
  `max_worlds` 是上限；`total` 仅 complete 时精确，partial 给 returned_count/lower_bound。
- 反向约束是**因果闭包（only-if）**，不是逻辑逆否：禁止 `effect → guard`。
- 新增假设不能修复 unsat；无概率、无最优性时不假装最优；partial 枚举不算信息增益精确名次。
- 未录入事件是未知；只有完整 record 才允许 closed-world。
- 命名：新规则包不得叫 `rules/`（遮蔽 `rules.py`）；用 `rulebook/` 或 `rulesets/`，保留旧入口。

<!-- END -->
