// 血染钟楼网页/后台通用 JSON 接口契约
// api_version = "1.0"
//
// 本文件只定义协议类型（机器可读约定），不包含服务实现。
// 后端必须对请求做运行时校验：TypeScript 类型只在编译期生效，
// 无法阻止格式错误、重复 id、无效引用或未知类型进入服务端。
//
// 约定：
// - 未知的“活跃”（enabled = true）事实类型必须被拒绝，不得静默忽略。
// - 扩展类型与扩展字段一律使用命名空间前缀 `命名空间:类型`，避免与核心字段冲突。
// - 核心事实（fact.type = "role" | "alignment"）必须与命题 kind 一致，
//   该一致性由判别联合（discriminated union）在类型层面强制。

export type ApiVersion = "1.0";

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

// 时间：
// - setup：初始配置阶段。
// - day/night + 正数 number：表示该阶段结束时刻的状态。
export type Time =
  | { phase: "setup" }
  | { phase: "day"; number: number }
  | { phase: "night"; number: number };

export type Alignment = "good" | "evil";

export interface Player {
  // 玩家稳定 id，请求内唯一。
  id: string;
  seat: number;
  name: string;
}

export interface Game {
  id: string;
  // 客户端持有的对局版本号；请求与响应都会回显，用于丢弃旧响应。
  revision: number;
  script_id: string;
  players: Player[];
  // 请求时的当前时间快照。
  time: Time;
}

// 命题：关于某玩家在明确时刻的角色或阵营。
// 角色用 role_id 表示，不固定枚举，具体取值由 script 决定。
export interface RoleProposition {
  kind: "role";
  player_id: string;
  role_id: string;
  time: Time;
}

export interface AlignmentProposition {
  kind: "alignment";
  player_id: string;
  alignment: Alignment;
  time: Time;
}

export type Proposition = RoleProposition | AlignmentProposition;

// 事实的公共字段。
// status：confirmed 区分确认来源（仍可属于 conditional）；reported 是玩家声明，
//   启用后作为可撤销的推理假设参与本次推理（玩家可在下一次请求中撤销），并不表示客观为真。
// enabled：false 时该条事实不参与本次推理。
interface FactBase {
  // 请求内稳定唯一 id，供冲突 input_ids 引用。
  id: string;
  status: "confirmed" | "reported";
  enabled: boolean;
  // 命名空间化的扩展字段，例如 { "acme:note": "..." }。
  extensions?: Record<string, JsonValue>;
}

// 核心事实：type 与 proposition.kind 必须一致。
export interface RoleFact extends FactBase {
  type: "role";
  proposition: RoleProposition;
}

export interface AlignmentFact extends FactBase {
  type: "alignment";
  proposition: AlignmentProposition;
}

// 扩展事实：type 为 `命名空间:类型`，用 data 承载扩展载荷。
// data 保持开放的 JsonValue：本文件不枚举所有扩展类型，由命名空间自行约定。
export interface ExtensionFact extends FactBase {
  type: `${string}:${string}`;
  data: JsonValue;
}

export type Fact = RoleFact | AlignmentFact | ExtensionFact;

// 以下为后台当前已识别的三类 BOTC 扩展 `data` 的形状（仅文档性注解，
// 不改变 ExtensionFact.data 的开放类型）。运行时校验是否接受某条数据、
// 以及是否真正生成约束，由后台校验与转换层决定；结构合法不代表已支持。
//
// 说明：
// - `time` 用于这些扩展，取值 day/night + 正数 number（不含 setup）。
// - `enabled: false` 的事实不解析 data，可保存任意草稿。
// - 结构合法但当前模型不支持的组合会被拒绝为 HTTP 422。

export interface AbilityObservationData {
  time: { phase: "day" | "night"; number: number };
  // 发动技能的玩家 id。
  actor_id: string;
  // 决定技能分支的角色 id（不是 ability_id）。
  role_id: string;
  targets: string[];
  ability_id?: string;
  note?: string;
  result:
    | { kind: "unobserved" }
    | { kind: "no_outsiders" }
    | { kind: "no_direct_result" }
    | { kind: "role"; role_id: string }
    | { kind: "number"; value: number }
    | { kind: "text"; text: string }
    | { kind: "choice"; value: string; role_id?: string };
}

export interface NightDeathsData {
  // 必须为 night。
  time: { phase: "night"; number: number };
  // 公布的死亡玩家 id；result 为 "none" 时须为空数组。
  player_ids: string[];
  result: "deaths" | "none";
}

// 当前唯一的全局假设：所选时点全体玩家真实身份均非该角色。
// 不排除酒鬼拿到该镇民标记；enabled 是唯一参与开关。
export interface GlobalAssumptionData {
  kind: "role_absent";
  role_id: string;
  time: Time;
  requested_enabled?: boolean; // 兼容旧 UI 的记录字段，不覆盖 enabled。
}

export interface ReasonerParticipation {
  id: string;
  status: "applied" | "partial" | "record_only" | "disabled";
  reason: string;
}

export interface DayVoteData {
  // 必须为 day。
  time: { phase: "day"; number: number };
  // voting 仅约束已有提名，不封闭后续槽；UI 草稿默认禁用。
  stage: "voting" | "settled";
  // 被处决者；无人处决为 null。
  execution: { player_id: string | null } | null;
  alive_count?: number;
  threshold?: number;
  highest_count?: number;
  override?: boolean;
  default_player_id?: string | null;
  // 按数组顺序映射提名槽及逐人投票，参与贞洁者、管家、处决规则。
  nominations?: {
    id: string;
    nominator_id: string;
    nominee_id: string;
    voter_ids: string[];
    count?: number;
  }[];
}

// 临时假设：仅在本次请求内生效，不修改持久化的对局信息。
export interface Assumption {
  id: string;
  enabled: boolean;
  proposition: Proposition;
  extensions?: Record<string, JsonValue>;
}

// 查询：显式 id，稳定唯一，响应按 id 回显。
export interface Query {
  id: string;
  proposition: Proposition;
}

export interface Options {
  // 每次 solve 的超时（毫秒），不是整体请求预算。一次请求可能执行多次 solve。
  timeout_ms?: number;
  // 分析总预算，默认 8000，1..60000；不含构建与排队。
  total_timeout_ms?: number;
  // 初始角色联合世界数量上限，默认 0（关闭），0..100。
  max_worlds?: number;
  // 每类最优撤回方案返回上限，默认 0（关闭），0..10。
  max_repairs?: number;
  // 每类修复搜索的求解次数上限，默认 128，1..1024。
  max_repair_checks?: number;
  // 概率模式不改变逻辑条件，仅增加初始身份的带权抽样估计。
  probability_mode?: boolean;
  // 独立概率分析预算，默认 120000，1..300000 毫秒。
  probability_timeout_ms?: number;
}

export interface ReasonerProbabilities {
  status: "estimated" | "unknown" | "inconsistent";
  method: "weighted_sampling";
  scope: "conditional";
  // public 输入为硬条件，其他启用输入按 owner 组以 0.7 伯努利采信后枚举组合。
  conditioning: "public_with_soft_conditional_inputs";
  credibility: number;
  time: { phase: "setup" };
  complete: false;
  seed: number;
  input_ids: string[];
  hard_input_ids: string[];
  soft_input_ids: string[];
  // total：全部组合数；checked：已检查；estimated：可行且完成估计；
  // complete：是否枚举了全部组合（不是概率的完整性保证）。
  groups: { total: number; checked: number; estimated: number; complete: boolean };
  // 抽样元数据：每个采信组合的目标接受样本数与最大尝试次数。
  target_accepted_per_group: number;
  max_trials_per_group: number;
  rows: { player_id: string; seat: number; probabilities: Record<string, number> }[];
  description: string;
  reason?: string;
}

// 连接器一次请求内各阶段的实测耗时（毫秒），用于本地性能对比。
// 不含等待适配器锁的时间与 HTTP 传输时间。
export interface ReasonerTimings {
  build_ms: number;
  analysis_ms: number;
  probability_ms: number;
  total_ms: number;
  excludes: string[];
}

// 以下类型说明 reasoner:* 扩展；运行时仍由后端校验。
export type ReasonerScope = "public" | "conditional";
export type ReasonerSource = "received" | "self_claim" | "assumption"
  | "public_announcement" | "observation";

export interface ReasonerInputExtensions {
  // 仅 confirmed 事实可显式 public；假设始终 conditional。
  "reasoner:scope"?: ReasonerScope;
  "reasoner:source"?: ReasonerSource;
  "reasoner:owner_id"?: string;
}

export interface ReasonerScopeResult {
  consistency: Consistency;
  input_ids: string[];
  results: QueryResult[];
}

export interface ReasonerRoleRange {
  player_id: string;
  seat: number;
  role_ids: string[];
  impossible_role_ids: string[];
  unknown_role_ids: string[];
  complete: boolean;
}

export interface ReasonerRepairCandidate {
  removed_input_ids: string[];
  changed_owner_ids: string[];
  cost: { owners: number; inputs: number };
  optimality: "optimal";
  verified: boolean;
}

export interface ReasonerWorlds {
  worlds: { roles: Record<string, string> }[];
  complete: boolean;
  returned_count: number;
  total: number | null;
  truncated_reason: "max_worlds" | "solver_unknown" | "deadline" | null;
  time: { phase: "setup" };
}

export interface ReasonRequest {
  api_version: ApiVersion;
  request_id: string;
  game: Game;
  facts: Fact[];
  assumptions: Assumption[];
  // queries 允许为空；为空时仅做整体一致性检查。
  queries: Query[];
  options?: Options;
}

export type Consistency = "sat" | "unsat" | "unknown";

export type QueryStatus =
  | "possible"
  | "necessary"
  | "impossible"
  | "inconsistent"
  | "unknown";

export interface QueryResult {
  id: string;
  status: QueryStatus;
  // 说明信息，例如 unknown 的原因。
  reason?: string;
}

// 冲突：input_ids 指向请求内的 id，rule_ids 指向规则 id。
// 这是有用的冲突子集，不保证是最小冲突集。
export interface Conflict {
  input_ids: string[];
  rule_ids: string[];
}

// 模型：业务 JSON，表示一个满足解（仅 consistency = "sat" 时给出），
// 不代表唯一解、不含概率，也不区分各查询各自的见证。
export interface ModelAssignment {
  player_id: string;
  role_id?: string;
  alignment?: Alignment;
  // 该赋值对应的时刻。
  time: Time;
}

export interface Model {
  assignments: ModelAssignment[];
}

export interface ReasonResponse {
  api_version: ApiVersion;
  request_id: string;
  game_id: string;
  revision: number;
  consistency: Consistency;
  // 全局 consistency = "unknown" 时的原因说明。
  reason?: string;
  results: QueryResult[];
  conflicts?: Conflict[];
  model?: Model;
  // 命名空间化的扩展字段，例如 { "adapter:mode": "placeholder" }。
  // 前端可据此判断后台当前是否真正运行了推理引擎。
  extensions?: Record<string, JsonValue>;
}

// HTTP 错误：表示协议/校验/服务问题，与逻辑不可满足（unsat）无关。
export interface ErrorResponse {
  api_version: ApiVersion;
  request_id?: string;
  error: {
    code: string;
    message: string;
    // 出错位置的 JSON Pointer，必选，例如 "/facts/1/proposition/player_id"。
    path: string;
  };
}

// GET /api/v1/capabilities 的简要约定。
export interface CapabilitiesResponse {
  api_version: ApiVersion;
  supported_fact_types: string[];
  query_types: string[];
  scripts: { id: string; name: string }[];
  // 命名空间化的扩展字段，例如 { "adapter:mode": "placeholder" }。
  extensions?: Record<string, JsonValue>;
}
