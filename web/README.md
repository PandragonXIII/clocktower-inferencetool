# Web：圆桌推理助手

## 主界面布局

“新建对局”位于页眉右侧，示例与来源信息移入“高级数据 / 调试”。圆桌仅保留必要图例、当前展示时点和历史状态；推进卡片只显示操作及不可用原因。身份卡片用开关表达启用状态、简短标签表达来源；动作卡片省略空备注、无直接结果及关联身份说明。完整记录仍可折叠查看，推理范围集中在推理卡片的折叠说明中。

## 当前推理接口兼容性

已同步 Engine 的来源感知双范围推理：启用的 `reported` 声明作为可撤销条件输入参与 conditional 推理，不再被忽略；`confirmed` 也不一概等同 public，来源和 scope 的完整说明见协议与转换层文档。本节取代下文旧的“reported 不参与推理”描述。已有身份声明仍保留问号，不能当作客观事实。原有停用技能、死亡、投票及全局扩展仍不会自动启用，需要后续按后台支持范围逐项接入。

## 固定时点与记录纠错

玩家窗口的假设、动作表单使用打开玩家卡片时的圆桌展示时点，仅显示一行时间说明，不再提供记录时点或阶段编号输入。要在其他阶段添加记录，先关闭窗口并用圆桌历史按钮切换时点。编辑记录使用原记录时点，不能悄悄移动到当前阶段。

“身份 / 阵营假设”统一列出手工假设与 `reported` 身份声明，因此初始身份也能在此编辑、开关和删除；来源标签保留声明与硬假设的语义区别，不自动把初始身份升级为求解约束。动作关联身份通过“编辑关联动作”修改，避免身份与技能互不对应。

每张身份、动作、夜晚死亡卡提供编辑按钮。弹窗预填原数据，保存原位更新，动作保留原 id 并重新整理身份关联，不追加重复动作。死亡修改不会推进时间，支持改为无人死亡；会更新历史死亡标记，并提醒复核后续死者提名、投票人数阈值和重复死亡，不自动重写投票或处决结果。保存清除旧推理响应，取消不更改数据。投票记录和全局假设仍保留现有专用操作，本次未增加全投票历史重编辑。

## 假设延续与角色变化

初始角色声明同样提供展示性的默认阵营：镇民、外来者显示蓝色斜纹“善良？”，爪牙、恶魔显示红色斜纹“邪恶？”，标注“按身份声明 · 默认阵营”，随初始身份一起顺延。若存在显式阵营候选或确定阵营，以显式信息为准；善恶角色候选并存时使用中性斜纹。不新增 alignment 假设、不修改 reported 性质、不向后台提交隐含阵营约束；角色与阵营可能变化，默认颜色不是确定结论。本说明取代下文旧的“声明不派生默认阵营”展示规则。

初始设置的本人身份保存为 `reported`，初始配置的角色声明也作为基础候选跨时点显示，进入首夜或后续阶段不会消失，始终保留问号与声明性质。`reportedCandidates` 与假设时间线共用转化边界：女郎转化后不再叠加旧初始角色；停用声明后不再顺延。非初始时点的声明仍只在原时点显示。此规则同样仅影响展示与候选查询，不会把声明变为硬约束。

### 动作身份去重

保存动作时，按玩家和角色检查启用的身份假设；存在则共用。没有假设但有相同角色的启用声明或确认身份时，复用该记录（`ui:identity_fact_id`），不新建假设、不改变 `reported` 的性质。均不存在时才自动生成身份假设。停用身份不作为有效来源，不会被静默恢复。由于当前身份假设跨时点展示，同一角色不因录入时间不同重复创建；声明的复用仅避免冗余记录，不会把声明扩展为后台全时段约束。

多个动作可使用同一个 `ui:assumption_id`。删除动作时保留手工假设和声明；自动假设仍被其他动作使用时保留并转交关联，最后一个关联动作删除时才删除该自动假设。女郎变化仍由各动作的结果和时间决定，不依赖某个动作独占假设。此规则优先于下文旧的“每个动作创建专用假设”说明。

圆桌上的玩家身份、阵营假设默认跨所有展示时点共享，包括记录之前的时点；它们是用户对整局的基础假设，不是已确认事实。停用或删除后，所有时点同步更新。不同基础假设不会按最后录入覆盖，仍保留多个候选。确认事实、玩家声明和后台查询结果保持单时点语义，不自动顺延。本节的假设展示规则优先于下文旧的严格时点说明。

`assumption-timeline.js` 集中处理展示候选和变化边界。记录红唇女郎“发生转化”或“转化为小恶魔”后，在关联身份假设启用时，从动作所处阶段（含该阶段）起显示小恶魔，之前仍显示基础角色假设；“未发生”“未观察”不触发变化。转化仅覆盖角色，不擅自修改显式阵营假设。停用关联假设或删除动作会取消该变化；重新启用可恢复。动作观察仍不直接成为确定结论。

由于协议时间指阶段结束状态，转化动作自动建立的女郎身份命题放在前一阶段；关联假设的 `extensions["ui:role_transition"]` 保存 `{role_id:"imp",time:动作时点}`，动作仍保留原时间与结果。后台现有 `proposition.time` 仍是单时点命题，**跨时点共享及变化暂为前端展示规则，不代表后台已应用全时段约束**；接入转换层时应把基础假设编译成分段有效的约束，变化覆盖点之后的基础角色，不可直接把女郎约束复制到所有阶段。小恶魔自杀继承等其他变化尚需增加显式变化记录，不能假定身份永远不变。

运行测试：`node --test web/tests/*.test.cjs`。

原生 HTML/CSS/JS 静态网页，无新增依赖。`index.html` 提供初始设置向导、圆桌主界面与折叠调试区；`setup.js` 负责三步设置和完整请求生成，`roles.js` 共享暗流 22 角色的中文名称与分组。`roundtable.js` 负责按时点展示圆桌和整局假设、动作记录，由 `app.js` 的 render hook 接入。`reasoning.js` 提供圆桌与记录之间的独立推理操作区，`app.js` 统一处理补充查询、请求及异步状态，同时保留 JSON 导入和协议明细；`styles.css` 实现响应式布局。所有外部数据使用 `textContent` 展示，不解释为 HTML。

## 运行

统一入口（同时提供 UI 与 `/api/` JSON API，同源）：

```sh
python main.py web --host 127.0.0.1 --port 8000
```

也可在仓库根目录用 Python 原生静态服务器**仅**提供静态页面：

```sh
python -m http.server 8000 --bind 127.0.0.1 --directory web
```

访问 `http://127.0.0.1:8000/`。不要直接以 `file://` 打开，否则浏览器可能阻止读取示例文件。

`main.py web` 由 [`../backend/http_server.py`](../backend/http_server.py) 提供，同时服务静态 UI 与后台 API（含运行时校验），并默认注入真实适配器 `connector.TroubleBrewingAdapter`（运行暗流涌动求解器）。而 `python -m http.server` 只提供静态文件、**不含 API**，此时点击“开始推理”会明确显示 HTTP 失败，不会生成假结果。若后台返回 **placeholder（占位）** 标记 `extensions["adapter:mode"] == "placeholder"`，前端明确提示未接入推理，不采用其一致性或查询结论。

## 查看与导入

### 初始设置与新建对局

- 首次打开仅显示初始设置，不显示圆桌、数据来源或 JSON 调试，不自动读取示例或请求后台。进度标注“第 n/3 步”及 33% / 67% / 100%，进度条按三等分填充，每次只回答一个问题。
- 第一步选择游戏人数：暗流涌动 5–15 人，明确预选 7 人。第二步选择本人座位：原生单选列出 1 至所选人数的座位，默认 1 号。第三步选择本人初始身份：22 个角色按镇民 / 外来者 / 爪牙 / 恶魔分组单选，也可保留“暂不确定”。原生单选支持 Tab、方向键与空格；上一步 / 下一步保留有效的座位和身份选择，摘要始终显示人数、本人座位和身份。
- 返回修改人数时，座位选项同步人数范围；仍合法的座位保留，越界座位自动重置为 1 号，并显示原座位、当前人数与重置说明，身份选择不丢失。
- 只有所选座位姓名为“本人（你）”，其余为对应的“玩家N”。完成后按 seat 1…N 生成玩家，新 game.id / request_id、revision=0、稳定玩家 id（p1…pN，pN 始终对应 N 号位），时间为 setup。选择身份仅生成一个启用的 reported role 事实，player_id 指向本人座位的 pN（setup 时点）；未知不生成事实。不生成阵营、假设、查询或推理结果。
- `App.startGame(request)` 是明确的集成入口：更新快照及请求编辑框、清空旧响应、递增异步 epoch 以拒绝旧响应，再渲染圆桌；来源标记“初始设置，尚未计算”。不会自动调用后台或加载示例覆盖新局。
- 工作区“新建对局”重新打开向导，草稿默认 7 人 / 1 号位 / 暂不确定；只有第三步完成才替换旧对局。任一步点击“返回当前对局”均恢复原工作区，保留当前数据；首次无该按钮。刷新页面重新开始初始设置，不使用 localStorage 保存。
- 向导和工作区以 `hidden` 互斥展示，CSS 明确保证 hidden 不被布局样式覆盖。窄屏选项自动换列，完成后圆桌只在内部横向滚动。

### 圆桌主视图

- 玩家按 seat 从 12 点方向顺时针排列。灰色 `?` 为未知身份；身份已知时展示暗流涌动的中文角色名，未识别 role_id 原样显示。阵营单独判断：善良蓝、邪恶红，绝不根据角色推测阵营。
- **角色假设可获得展示性的不确定默认阵营**：当某玩家在所选时点没有确定阵营、也没有显式阵营候选时，若存在该时点启用的 role 假设，则按暗流涌动的固有阵营（镇民 / 外来者善良，爪牙 / 恶魔邪恶）把卡片显示为该阵营的低饱和斜纹，并标注“按角色假设 · 默认阵营”。这只是不确定提示，不写入 confirmed、不生成任何隐含 alignment 约束，也不作用于玩家声明或确定身份（声明与 confirmed role 不派生阵营）。一旦存在显式阵营候选或确定阵营，则以显式 / 确定信息为准，不再显示角色派生的默认斜纹。
- 中央分别显示对局实际进度和正在展示的时点。首次载入对局默认初始配置（setup）；▲ 上一阶段、▼ 下一阶段组成上下历史按钮组，位于“推进对局”卡片左侧，圆心不再放置按钮。历史顺序为 setup → night1 → day1 → night2 → day2。首尾按钮禁用。同一对局的新快照保留合法的用户时点；切换对局重置 setup。
- 圆桌右侧的同一控制区域包含历史按钮组和独立“推进对局”卡片，窄屏整体排列在圆桌上方，历史组在左、卡片在右；空间不足时按历史组在先、卡片在后折行，均不进入圆桌横向滚动区域。卡片提供 `next 进入夜晚` / `next 进入下一天`，辅助文字注明目标第 N 夜 / 天。始终从真实 `game.time` 计算 setup → night1 → day1 → night2 → day2，而不是从正在查看的历史时点计算；▲ / ▼ 仅切换展示，不改变 `game.time`。第 99 夜可进入第 99 天；第 99 天达到上限，按钮禁用并提示。无有效对局或时间非法时安全禁用，导入数据仍可查看。
- `App.advancePhase()` 仅在 setup 直接推进；夜晚打开死亡确认，白天打开投票或结算后的技能检查（详见下节），不能直接跳过投票进入夜晚。同局稳定 id 与已有记录保持不变，每次保存 revision +1、刷新 request_id，递增 epoch 拒绝旧响应并清空响应 JSON / 旧推理反馈，同步请求 JSON 和视图。不会复制旧命题、自动继承身份或自动请求 HTTP 推理。原生按钮支持 Enter / Space，重绘保留焦点；忽略双击的第二击与按键自动重复。
- **只读取完全相同时点**的启用 confirmed role/alignment 条件，以及与请求 request_id/game_id/revision 匹配、API 基本结构有效、consistency=sat、非 placeholder 响应中的 necessary 查询结果。setup 身份不沿用到 day1；无数据时提示切换时点，不自动填充。
- 同样严格按所选时点读取 enabled=true 的 reported role/alignment 与临时假设作为**待确认候选**，不是硬结论。确定角色优先；无确定角色时，单一候选显示“中文角色名 ?”，多个候选显示“身份待定 ?”，没有候选仍显示 `?`，不任取一项。候选可通过卡片提示或无障碍名称读取，完整来源见高级数据。
- 确定阵营为纯色蓝 / 红；无确定阵营时，只有 good / evil 候选分别显示低饱和蓝 / 红斜纹及“善良？/邪恶？”文字，双阵营候选显示中性斜纹与“阵营待定”。图例解释纯色、斜纹与身份后的问号；不根据角色推测阵营。
- 卡片区分“玩家声明”“临时假设”，有确定信息时用“另有声明 / 另有假设”压缩标签。声明 / 假设不会使确定信息失效。有启用假设时，推理来源明确标注“假设下推理”；假设本身不作为已确认输入。停用条目不参与候选与上色，但保留在整局记录中。模型 assignment、possible/impossible/unknown 查询结论均不作为候选。
- 同类型存在多个确定值（包括输入与推理相互冲突）时显示“信息冲突”，停止上色，不以后出现的数据覆盖。匹配响应 unsat 时只展示输入并标注“输入有矛盾，未验证”，不采用推理。
- 点击玩家卡片打开操作弹窗，仍可管理该玩家所有时点的假设、动作。条件、玩家声明和查询来源在“高级数据 / 调试”查看；reported 声明不混入身份假设列表，也不会被删除。
- 桌面圆桌居中；5–15 人按人数扩大半径，保持固定可读的玩家卡片，窄屏仅圆桌内部可横向滚动，页面本身不横溢。玩家和时间按钮支持原生键盘操作及可见焦点。

### 夜晚死亡确认

`night-deaths.js` 提供共享 `records(facts)` / `deadAt(facts, time)` 及原生死亡确认 dialog。夜晚点击 next 时只打开草稿，不提前推进；setup → night1 不弹窗，dayN → nightN+1 使用下述投票与技能确认。标题明确“第 N 夜死亡”，每位玩家显示座位与姓名，可多选；初始无选择，必须选至少一人或明确勾选“无人死亡”才能确认，两者互斥。已死亡者禁用并标注“已死亡”。取消、关闭按钮、Escape 不改变请求、revision、request_id、记录、时间或响应，焦点返回 next；不提供复活。

`App.advancePhase()` 在真实 `game.time` 为 night 时始终要求弹窗确认，不能直接跳到白天。`App.confirmNightDeaths(expected, playerIds, result)` 使用打开弹窗时的 epoch token，并要求该弹窗仍有效；检查真实夜晚、版本/时间上限、玩家存在、重复 id、已死亡玩家、一夜不能重复记录，以及 deaths/none 与人数匹配。不接受取消、关闭或过时 context。确认通过统一 mutation 一次增加 fact 并推进 dayN，仅 revision +1 / request_id 更新一次，清空响应、递增 epoch、同步 JSON、切换展示时点；不自动请求推理。推理 busy 时禁用推进，重复打开/提交有防护。新局向导、新快照、示例、导入及其他 mutation 关闭过时弹窗。

扩展使用现有 `ExtensionFact`，不改变核心协议：

```js
{
  id: "f-night-deaths-<unique>",
  type: "botc:night_deaths", status: "confirmed", enabled: false,
  data: {
    time: { phase: "night", number: 1 },
    player_ids: ["p1", "p2"], result: "deaths"
  }
}
// 无人死亡：player_ids: [], result: "none"
```

每夜一个可追溯 fact（包括无人死亡）；confirmed 仅确认用户记录的死亡观察，不生成 role/alignment 或假设。扩展始终 disabled，文案“死亡已记录，尚未参与推理”；未知扩展若启用，当前后台会拒绝。后端接入需实现 schema、时间/玩家引用、重复死亡与规则解释的校验及显式启用机制，不能仅以输入通过核心校验宣称引擎支持。`deadAt` 只读取 confirmed、结构有效的该扩展死亡列表，disabled 不影响本地观察展示；不从技能结果猜测死亡。

圆卡增加“已死亡”文字与中性侧边框，保留阵营顶边、背景色及角色可读性，仍可打开假设/动作。阶段时间表示阶段结束：night1 死亡在 night1、day1 及以后可见，setup/更早阶段不显示。整局“假设与动作”保留原两组，新增独立“死亡记录”轻卡，显示夜次、玩家或无人、不参与推理及完整来源 JSON。不提供死亡记录删除/重开，以免破坏后续死亡一致性；高级 JSON 仍可查看和导入，导入的扩展不替代后端规则校验。

### 白天提名、投票与处决

`day-voting.js` 提供白天子阶段原生弹窗；协议 Time 仍只有 setup/day/night，不新增投票阶段。白天主按钮依次显示“进入投票”→“继续投票”→“进入夜晚”。首次进入即保存一个 `stage:voting` fact（revision +1），随后每轮独立保存。选择存活提名者、任意被提名者（含死者），勾选任意投票者后保存本轮，可反复增加或删除尚未结算轮次。关闭 / Escape 保留已保存轮次，未保存表单丢弃；重新打开恢复快照，不提前推进夜晚。

默认处决采用结算时存活人数的 `ceil(alive_count / 2)`，即至少一半，不是严格超过半数。每轮票数由去重后的 voter_ids 派生；同一被提名者多轮取最高票而非相加，达到阈值且在不同人中唯一最高才默认选中。无提名、最高票不足、不同人同票或全员死亡（threshold=0）均默认无人。可手动选择任意玩家或无人以记录技能例外；不限制重复提名、不限制死者每局投票次数，不实现特殊角色提名规则。死者票有明确标注，提名者死亡检查同时在 App mutation 执行，避免仅依赖禁用选项。

“结算投票”一次原子保存 settled、实际处决者、结算时人数/阈值、默认结果与 override，仍保持 dayN。已结算处决与夜间死亡由 `deadAt` 合并为 Set，处决从 dayN 结束起显示死亡，更早历史不受影响；处决已死者不重复减少存活人数，不根据技能结果猜测其他死亡。

结算页询问“是否还有其他技能发动？”，默认允许没有新增技能。可反复选择任意发动者（含死者），点击“记录技能”复用 `PlayerActions.openAbility(request, actor, time, {expected,onComplete,onClose})`。投票弹窗先关闭，再打开技能 editor，时间锁定当前白天；保存创建禁用观察及专用启用身份假设，取消不保存，二者均返回结算页。关闭结算窗口后主按钮“进入夜晚”仍只打开此检查页；仅最后“没有了，进入夜晚”调用 `App.finishVotingDay(expected)` 推进到 nightN+1，同步展示时间、清除响应并关闭旧弹窗，不自动推理。day99 维持进度上限。

扩展 schema（每白天一个 fact；未结算 execution 为 null）：

```js
{
  id: "f-day-vote-<unique>", type: "botc:day_vote",
  enabled: false, status: "confirmed",
  data: {
    time: {phase: "day", number: 1}, stage: "settled", // 或 voting
    nominations: [{id: "nomination-<unique>", nominator_id: "p1",
      nominee_id: "p2", voter_ids: ["p1", "p3", "p4"], count: 3}],
    execution: {player_id: "p2"}, // 无人处决为 {player_id: null}
    alive_count: 6, threshold: 3,
    highest_count: 3, default_player_id: "p2", override: false
  }
}
```

投票中人数/阈值为进入时摘要；结算时重新计算并持久化。`default_player_id`、`highest_count` 是本地默认选择解释，不是规则求解结果。`App.saveNomination(expected,data)`、`removeNomination(expected,id)`、`settleVoting(expected,playerId)`、`finishVotingDay(expected)` 要求当前阶段和有效 epoch context。`DayVoting.perform` 仅在自身保存期间接受恰好下一 epoch，其余 mutation、导入、示例、新局使旧窗口失效；技能保存也走同一 context 刷新路径。每次 mutation 都通过既有快照更新机制同步完整 JSON、revision、request_id 并清除响应。记录卡显示提名、投票者、票数、阈值、处决、默认/覆盖与完整 JSON，始终提示尚未参与推理。所有扩展保持 enabled:false，不派生 confirmed role/alignment。

快照中保存不等于刷新自动恢复；当前仍无 localStorage，需导出/复制请求 JSON 后导入。后端只校验通用禁用扩展容器，不代表支持投票规则求解。

### 推理操作区（操作说明）

- 固定在圆桌后、“假设与动作”前的独立 section。左侧为唯一主入口“开始推理”，右侧初始为空，下方结果区初始隐藏；不因完成初始设置而自动发送。顶部不另设发送按钮。
- `App.reason()` 复用 `app.js` 的唯一 `sendRequest` 路径。`App.reasonState` 提供 busy / pending / error，`Roundtable.render` 接入 `Reasoning.render`。请求中按钮禁用并显示“推理中…”，右侧显示“正在推理…”。函数自身也阻止重复调用；输入变化后不会偷偷排队发送新请求，需等待旧请求结束再手动推理。
- 发送前通过 `Roundtable.getSelectedTime()` 获取真正选定的圆桌时点，为每名玩家补充 good / evil 两项阵营查询，并补充该时点已启用事实、声明、假设中的 role / alignment 命题。命题去重，已有用户查询及 id 原样保留，不从模型、技能结果或角色名称推测阵营。不枚举 22 个角色：7 人未知局首次补 14 项，15 人补 30 项，另加已录入候选；界面明确提示“查询当前展示时点的阵营和已记录身份候选”。保留的历史查询也可能出现在结论中，每项均注明时间。
- 自动 id 基于命题内容且避开 request/game/player/fact/assumption/query 所有集合的 id；重复推理不重复添加相同查询。仅查询集合确有增加时 revision +1、更新 request_id、清除旧响应、递增 epoch 并同步 JSON；然后只发一次完整快照。不为展示时点修改 `game.time`，超出真实对局进度时拒绝查询未来身份。后端 `validation.py` 没有查询数量上限，但每项可能触发额外求解，因此本界面避免全角色枚举；保留的用户查询仍可能增大开销，整体传输超时为 20 秒。
- 只有 API 基本结构有效且 request_id / game_id / revision 匹配当前快照、非 placeholder 的响应才可作为推理结论。`sat` 显示“有可行解”，展开“恒为真结论”，仅按请求 query id 对应 `necessary` 结果，展示座位姓名、时间、中文角色或阵营及来源 id。明确“在当前已启用假设下恒为真”；假设本身的必然性不是额外独立证明。不采用 possible 或 model assignment。没有 necessary 时写“后台未返回必然结论”，不声称不存在必然真理，也不声称已查询所有身份。
- `unsat` 显示“有矛盾”并展开后台 conflicts，解析事实 / 玩家声明 / 假设命题或动作名称，input_id / rule_id 原样保留为次要文字。无解释时显示“后台尚未返回矛盾原因，待接入后展示”。不编造证明，也不宣称最小冲突。
- `unknown` 显示“暂时无法判断”及后台 reason；placeholder 显示“后台尚未接入推理”，即使其 consistency 为 sat 也不显示可行解。HTTP / 网络 / 非 JSON / 协议错误显示可读错误，不当作矛盾。示例或手动导入的有效匹配响应也可展示，但数据来源区域始终注明来源，不能当作实时计算。
- 修改事实、假设、动作、请求 JSON、响应 JSON、加载其他数据或完成新局均清除旧结论；进行中的旧响应经 epoch 拒绝。编辑发生后右侧恢复空白，旧传输未结束前按钮仍禁用以避免并发。状态使用 aria-live，按钮有禁用 / busy / expanded 语义；重绘恢复键盘焦点，不抢走用户正在操作的假设开关或弹窗焦点。窄屏允许状态文字换行，不产生页面横向滚动。

### 假设与动作（整局记录）

- 圆桌下方固定汇总**当前快照整局全部时点、全部玩家**的记录，不按所选玩家或圆桌时间筛选。按“身份 / 阵营假设”和“动作观察”分组显示数量，每条一张卡；两组各有零记录提示。圆桌本身仍严格按时点展示，不跨时间沿用候选。
- 启用、停用假设都显示中文身份及 `?`、玩家座位姓名、明确时间、手工 / 动作关联来源与状态。导入的 alignment 假设显示善良 / 邪恶阵营。右侧滑块为原生 checkbox `role=switch`，Tab 可聚焦，Space 切换；可访问名称说明启用 / 停用的玩家、时间与身份。失败恢复原勾选并显示错误，不因 unsat / unknown 禁止编辑。
- 滑块调用 `App.setAssumptionEnabled`，更新 revision、request_id 与 JSON，清空旧响应并重绘圆桌和关联动作状态；通过 `data-focus` 恢复同一开关焦点，保留页面与圆桌滚动位置。停用假设不隐藏记录，只移除相应时点的候选（其他声明 / 假设仍可提供相同候选）。
- 动作卡直显技能名（角色）、发动者、时点、中文座位姓名目标、中文结果和备注，始终提示“已记录，技能结果尚未参与推理”。关联假设显示当前启用 / 停用状态；假设开关不启用技能观察本身，动作不提供总开关。
- 每条假设可删除，动作可“删除动作及专用假设”，分别使用现有 `App.removeAssumption` / `App.removeAbility`，不删除其他手工或动作假设。未知字段保留在可折叠的完整来源 JSON 中；手机卡片自动单列，开关独占固定宽度，不挤压身份文字。

### 高级数据 / 调试

完成设置后默认折叠，包含原 JSON 编辑、文件导入、应用按钮、协议明细及原始数据。工作区工具栏保留示例选择和重载按钮；发送统一使用圆桌下方的“开始推理”，默认不自动发送。

- 手动点击“重新加载示例”或切换示例时才读取文件：成功示例为 `protocol/examples/request.json` 与 `success.json`，明确标记“示例数据，非实时计算”。下拉切换矛盾时加载 `conflict-request.json` 与 `conflict.json`；HTTP 错误示例仅模拟错误，与请求不配对。
- 调试卡片展示对局、玩家、所有事实、临时假设、查询及结果、全局一致性及 unknown 原因、冲突输入和规则、带完整时间的模型赋值，以及错误 code/message/path。声明与真实身份明确区分，满足模型不是唯一解或概率。
- 粘贴 JSON 或导入本地 JSON 文件，点击“应用 JSON”。该操作不执行计算。合法但结构不完整的 JSON 仍可查看，缺失字段显示为 `—`，完整原始 request/response 可折叠查看，未知字段不会丢失。页面不代替服务端完整协议校验。
- 修改请求会立即更新当前可解析请求并清除旧响应；解析失败则清空有效请求并显示提示。修改响应也会移除已展示的旧结果，应用后才展示新内容。导入请求后需重新粘贴或导入对应响应。
- 导入含 consistency 的响应时校验 request_id/game_id/revision，不匹配则拒绝展示结果；错误对象仅展示导入内容，不宣称与请求配对。
- 支持键盘操作、可见焦点、状态朗读和窄屏单列布局；宽表格可聚焦并横向滚动。

## 玩家弹窗与技能数据约定

点击圆桌玩家打开原生 `dialog`，标题包含座位、姓名和展示时点，首页提供“假设 / 动作”。圆桌下方是整局记录；既有条件、声明和查询在高级数据查看。弹窗管理此玩家所有时点的假设、动作，可展开完整数据。关闭或 Escape 返回原玩家卡片焦点；返回、取消不保存草稿。手机弹窗限制在视口内并纵向滚动。新局、示例加载、请求 JSON 替换均关闭旧弹窗。

`player-actions.js` 只持有独立草稿，`skills.js` 集中定义 22 角色的录入元数据和校验，角色中文名共享 `roles.js`。每次仅选一个技能，名字括号内标注角色；被动效果明确标注“被动/触发记录”。`skill-availability.js` 统一筛选时间条件（见下节），不判断是否仍存活、是否使用过技能等复杂触发条件。两人信息中的对象是说书人指示/获知对象，不是假装玩家主动选择。

### 技能可用条件的分层与扩展

- **表单描述：`skills.js`**，负责技能名、目标数量、结果结构；不要在各个弹窗里重复写角色规则。
- **前端时间筛选：`skill-availability.js`**，`check(skill, time)` 返回是否可用及原因，`resultOptions(skill, time)` 返回该时点可选结果，`assert(skill, data)` 供保存路径再次校验。动作窗口与投票后的技能补录共用同一表单；`App.recordAbility` 经 `ClocktowerSkills.validate` 调用同一校验，不能靠直接调用绕过时间限制。
- **后台规则与求解：由转换层维护**。前端筛选只简化录入，不确认身份、不证明技能生效、不替代后台校验。扩展记录仍保持 `enabled:false`，尚未参与推理。

当前时间限制：

| 条件 | 技能 |
| --- | --- |
| 初始配置 | 不允许任何技能录入；仍可添加身份、阵营假设 |
| 仅第 1 夜 | 洗衣妇、图书管理员、调查员、厨师 |
| 每夜 | 共情者、占卜师、管家、投毒者、间谍 |
| 第 2 夜起 | 小恶魔、僧侣、送葬者 |
| 夜间触发或观察 | 守鸦人、士兵 |
| 白天 | 贞洁者、猎手、圣徒 |
| 白天或夜晚的被动记录 | 市长、酒鬼、隐士、红唇女郎 |
| 不作为发动技能选项 | 男爵配置效果；通过假设或既有备注描述 |

市长的结果进一步按阶段筛选：白天可记录“三人无处决胜利”，夜晚可记录“疑似转移击杀”，两者均可选择未观察。死亡、提名、是否真正触发等不因资料不足而隐藏对应技能。

动作窗口随时间更新可选项，折叠区列出不可用技能及原因。改动记录时间时重新建立目标与结果，清除不兼容的技能草稿；尚未保存的选择不会写入对局。初始配置时保留记录时间选择器，提示改选昼夜，不允许保存技能。已有历史观察不会删除或重新校验，仍可查看和删除。

这是暗流涌动普通开局的第一版限制；尚未提供“中途获得新角色”“旅行者或其他剧本”等例外入口，后续应通过明确的上下文扩展 `check`，不能在表单中散落例外条件。

运行时间限制测试：`node --test web/tests/skill-availability.test.cjs`。覆盖配置阶段、首夜与后续夜晚、昼夜区别，以及保存路径对不适用技能与结果的拒绝。

### 操作与更新接口

- 手工假设支持“身份 / 阵营”两种命题：选择“身份 role”可从 22 角色选择，“阵营 alignment”从善良 good / 邪恶 evil 单选；编辑区即时预览，只有“保存假设”才写入快照。动作选定技能后即时预览“将假设该玩家为 X”；只有“保存动作及身份假设”一次性创建记录与专用假设。取消或仅选择类型 / 技能不修改快照。
- 时间默认圆桌展示时点，可选 setup / night / day，编号限制 1–99。未来时点明确提示“对局进度同步至 X”，保存推进 `game.time`，历史记录不后退；保存后圆桌展示保存时点。
- `App.addAssumption(playerId, roleId, time)`、`App.addAlignmentAssumption(playerId, alignment, time)`、`recordAbility(data)`、`setAssumptionEnabled(id, enabled)`、`removeAssumption(id)`、`removeAbility(id)` 是显式变更入口。其中 `addAlignmentAssumption` 创建 alignment 命题，`alignment` 仅接受 `good` / `evil`，不从 role 硬编码推阵营。成功变更均在原 revision 基础上 +1、生成新 request_id、epoch +1、清除旧响应并同步编辑框、原始 JSON 和视图；不借助 `startGame` 重置版本。失败不保存部分数据。旧异步响应不能覆盖新记录。
- 假设支持停用、恢复、删除；动作支持删除。每个动作都有独立假设，角色相同也不共享 id。删除动作只删除双向 id 均匹配的专用假设，手工及其他动作假设不受影响。单独删除假设会移除动作上的旧关联；技能观察始终禁用，不能在 UI 中恢复为参与推理。

### 扩展 schema（使用现有 ExtensionFact，不修改通用协议）

```js
{
  id: "f-ability-<unique>", type: "botc:ability_observation",
  status: "confirmed", enabled: false,
  data: {
    actor_id: "p1", role_id: "fortune_teller",
    ability_id: "fortune_teller:record",
    time: { phase: "night", number: 1 }, targets: ["p2", "p3"],
    result: { kind: "choice", value: "yes" }, note: "可选备注"
  },
  extensions: { "ui:assumption_id": "a-ability-<unique>" }
}
```

对应 assumption 为 `{id, enabled:true, proposition:{kind:'role', player_id:actor_id, role_id, time}, extensions:{'ui:observation_id':fact.id}}`。`confirmed` 仅确认记录了观察，并不确认技能读数等于事实。动作**始终 enabled:false**，显示“已记录，技能结果尚未参与推理”；自动角色假设则启用。绝不从动作结果生成真实 role/alignment confirmed。当前后端拒绝未知活跃类型；后续接入必须实现扩展运行时校验、目标引用/结果校验及醉酒、中毒等规则解释后，再设计显式启用流程；目前不改 capability、不宣称技能求解支持。

所有 ability_id 固定为 `<role_id>:record`。targets 是去重的玩家 id 数组，备注 note 是字符串。结果为判别对象：`{kind:'role',role_id}`、`{kind:'choice',value,role_id?}`、`{kind:'number',value}`、`{kind:'text',text}`、`{kind:'no_direct_result'}`、`{kind:'no_outsiders'}` 或 `{kind:'unobserved'}`。数字、角色、文本结果支持勾选未观察；choice 结果内有 `unobserved` 选项；无直接结果技能不虚构读数。

| role_id / 中文 | 目标 | 结果 |
| --- | --- | --- |
| washerwoman / 洗衣妇 | 指示两人 | 镇民 role_id |
| librarian / 图书管理员 | 指示两人；无外来者分支为零人 | 外来者 role_id 或 no_outsiders |
| investigator / 调查员 | 指示两人 | 爪牙 role_id |
| chef / 厨师 | 无 | 0…玩家人数邻对数量 |
| empath / 共情者 | 无 | 0 / 1 / 2 |
| fortune_teller / 占卜师 | 两人 | yes / no / unobserved |
| undertaker / 送葬者 | 一名被处决玩家 | 任意角色 |
| monk / 僧侣 | 一人，不可自己 | no_direct_result |
| ravenkeeper / 守鸦人 | 一人 | 任意角色（死亡触发） |
| virgin / 贞洁者 | 一名提名者 | executed / not_executed / unobserved |
| slayer / 猎手 | 一人 | died / survived / unobserved |
| soldier / 士兵 | 无 | survived / died / unobserved；不证明免疫 |
| mayor / 市长 | 可选有关玩家 | three_alive_no_execution_win / suspected_redirect / unobserved |
| butler / 管家 | 一人主人，不可自己 | no_direct_result |
| drunk / 酒鬼 | 无 | 表象镇民 role_id，自动假设仍为酒鬼 |
| recluse / 隐士 | 无 | role / alignment / unobserved，具体登记写备注 |
| saint / 圣徒 | 无 | good_lost / good_won / ongoing / unobserved |
| poisoner / 投毒者 | 一人 | no_direct_result |
| spy / 间谍 | 可选多个有关玩家 | 多行完整魔典文本 |
| scarlet_woman / 红唇女郎 | 无 | occurred / not_occurred / role（附 role_id）/ unobserved |
| baron / 男爵 | 无 | setup 外来者数量 0…玩家人数，或未观察 |
| imp / 小恶魔 | 一人，可自己 | died / survived / unobserved，不确认为死因 |

目标少于/多于要求、重复、非本局玩家、禁止自己、非法角色结果、越界数量会明确报错且不变更快照。具体实现与 value 枚举以 `skills.js` 为准。弹窗不是技能规则求解器，也不校验观察真实性，不将间谍文本结构化为全局身份。

## 后台接入

仅点击“开始推理”（或显式调用 `App.reason()`）时，以 `Content-Type: application/json` 向同源 `POST /api/v1/reason` 发送补充查询后的当前完整请求。后端按 [协议文档](protocol/README.md) 进行运行时校验，并返回 JSON；其实现见 [`../backend/README.md`](../backend/README.md)。

若后台使用 placeholder 适配器（框架默认值，`main.py web` 不会使用），响应的 `extensions["adapter:mode"] == "placeholder"` 会使来源标记与推理区域明确说明**占位未运行引擎**，不会把响应当作真实推理结论。输入通过校验不代表引擎支持相应规则。

网页对成功响应检查 API 版本、基本 reason response 结构和查询状态，然后严格比较当前请求的 request_id/game_id/revision；不匹配或发送过程中输入发生变化的响应不会应用。网络失败、20 秒超时、非 JSON、HTTP 错误均明确提示，不伪造结果。HTTP 错误体含 error 时展示并保留原始内容；逻辑 unsat 是正常推理响应，不能当作 HTTP 失败。部署时静态页面和 API 应使用同源地址（`main.py web` 已同源），或由反向代理转发 `/api/`。

## 验证

死亡功能的 Chromium CDP 验收：setup → night1 不弹窗；night1 next 弹窗、时间不提前、初始确认禁用；Escape / 取消保留完整快照并返回 next 焦点；两人死亡确认后 day1 两张卡标死，仅一次 revision / request_id 更新、disabled fact 数据正确、清响应且不请求 API；day1 完成投票与技能检查后进入 night2；night2 已死者禁用、无人分支清空选人并记录空数组；setup 历史不显示死亡、night1 结束显示死亡；其他 mutation / 新局关闭弹窗且旧 context 拒绝；推理 busy 不推进、进行中旧响应拒绝；night99 确认后 day99 达上限禁用；原生 Space / Tab / Escape 与 320px 弹窗无横溢。捕获完整请求，仅调用 `backend.validation.validate_request` 检查协议有效性，不改后端、不运行引擎。

投票功能的真实 Chromium CDP 验收脚本位于临时测试目录 `/tmp/opencode/day-voting-check.mjs`，运行 `node --experimental-websocket /tmp/opencode/day-voting-check.mjs`（复用端口 9223 Chromium 与 8765 网页服务）。覆盖完整设置→夜晚死亡→白天多轮投票，死者提名校验/被提名/投票，保存关闭恢复与删除，7 活 4 票、6 活 3 票、不同人同票、同人多轮最高不叠加，无提名和全死无人默认，手动覆盖处决、结算留白天、历史不提前标死，死者处决不重复扣人数，技能保存/取消返回结算，最终推进及下一夜死亡禁用，无自动 API、旧 context 拒绝、Escape 焦点与 320px 无横溢。最终含投票/处决/技能的请求保存在 `/tmp/opencode/day-voting-request.json`，仅调用后台 validation 校验。

推理区的浏览器验收应覆盖：初始右侧空白、唯一发送入口、首次空 queries 补齐阵营查询、已录入角色去重和用户查询保留；匹配 SAT 的 necessary / possible / unknown 混合响应只展示 necessary；UNSAT 有 / 无 conflicts；unknown 原因、placeholder（即使其 consistency=sat）、HTTP / 网络 / 非 JSON / 协议失败及标识不匹配；请求中重复点击只发一次，编辑开关后清除反馈且旧异步响应拒绝，完成后按钮恢复；新局清空、键盘焦点和 320px 页面不溢出。可通过 Chromium CDP 在浏览器内替换 fetch 返回以上响应，不依赖真实引擎。捕获实际发送的完整快照后，使用 `backend.validation.validate_request(json.load(...))` 校验（仅调用，不改后端）；该校验不代表查询经过真实求解。

```sh
node --check web/app.js
node --check web/reasoning.js
node --check web/roundtable.js
node --check web/setup.js
node --check web/roles.js
node --check web/skills.js
node --check web/player-actions.js
node --check web/night-deaths.js
node --check web/day-voting.js
git diff --check
```

浏览器先检查首次只有问题 1、三步进度与人数 5/15 边界、前后返回保留座位及身份、7 人局选择 6 号士兵后只有 p6 标记本人且显示灰色“士兵 ?”、声明指向 p6、未知无事实；15 号返回将人数降为 5 时自动重置合法座位且明确提示。检查新建重置 7 人 / 1 号 / 未知、各步取消保留旧局、连续座位及新 game.id、三步窄屏无页面横溢且无自动网络请求。生成请求可调用 `backend.validation.validate_request` 校验。随后检查三种示例切换、错误 JSON 提示、请求编辑清空结果、不匹配响应拒绝、窄屏滚动和静态服务器下的发送失败。输入含 `<script>` 等内容应只作为文本展示。

圆桌检查：setup 时 p1 为共情者但仍灰色、p2 为“士兵 ?”并标玩家声明、p3 邪恶纯色红、p4 为邪恶低饱和斜纹并标临时假设、p5 的 necessary good 为纯色蓝并标“假设下推理”；切到第 1 夜不沿用 setup 信息。检查确定信息优先于相异声明 / 假设、多身份 / 双阵营候选不任取、禁用无候选但记录仍保留、全部来源可读、时间边界、矛盾输入警告、confirmed 与推理冲突、模型不影响身份，以及 5–15 人窄屏圆桌局部滚动、卡片无重叠和键盘操作。

阵营假设检查：在弹窗中以“假设类型 = 阵营”添加善良 / 邪恶假设后，卡片立即出现对应低饱和斜纹（邪恶 → `pending-evil`，善良 → `pending-good`）而非纯色；停用移除斜纹、恢复重新出现；同一玩家 good + evil 双候选显示中性混合斜纹且不任取；存在 confirmed 阵营或必要阵营结论时保持纯色优先。仅 role 假设且无确定 / 显式阵营时显示按暗流固有阵营的默认斜纹并标注“按角色假设 · 默认阵营”，该默认不为 confirmed role 或玩家声明派生；显式 alignment 候选优先于角色默认。切换展示时点后，其他时点的假设不会错误上色。

整局记录检查：从设置创建，两名玩家分别在不同时间添加手工假设和动作；切换玩家、时间后记录均保留。关开同一假设检查对应时点圆桌候选消失 / 恢复、revision / JSON 更新、旧响应清除、Space 操作后开关焦点及页面滚动保留；检查关联状态同步、删除动作保留其他假设、失败回滚提示、alignment 导入、双组空态及 320px 无页面横溢。生成请求只需调用 `backend.validation.validate_request` 校验，不必运行推理或发送 API。

## 相关文档

- 协议：[protocol/README.md](protocol/README.md)
- 后台/API：[../backend/README.md](../backend/README.md)
- 推理模型：[../botc_reasoner/README.md](../botc_reasoner/README.md)

## 全局假设

“推理”卡片中，“开始推理”左侧的 **新增假设** 用于添加不属于单个玩家的条件。当前支持“某角色不在场”：选择角色后，作用时间取打开窗口时圆桌展示的时点。例如“初始配置时小恶魔不在场”，表示该时点没有任何玩家具有此角色，不代表整局所有时间均不存在。

保存后的记录位于“假设与动作 → 全局假设”，可以切换希望采用的状态或删除。保存、切换、删除都会更新请求版本、清除旧推理响应；取消不产生记录，同一角色同一时点不能重复添加。新局、导入或其他快照变化会关闭过期窗口。

**后台接入状态：** 当前核心命题不支持角色缺席，因此此功能先保存为停用扩展，尚未参与推理；开关仅表达接入后是否希望采用，不能把推理结果当作已考虑此条件。

供转换层接入的数据约定（位于 `facts`，不修改现有 `assumptions` 命题格式）：

```json
{
  "id": "a-global-唯一标识",
  "type": "botc:global_assumption",
  "status": "reported",
  "enabled": false,
  "data": {
    "kind": "role_absent",
    "role_id": "imp",
    "time": { "phase": "setup" },
    "requested_enabled": true
  }
}
```

`enabled` 保持 `false`，确保未支持此类型的后台可接收完整快照；`requested_enabled` 是用户选择。后端接入时需明确协商支持并将其编译为该时点全部玩家均非此角色的临时约束，不能按普通 `reported` 声明忽略后仍声称此假设已参与求解。
