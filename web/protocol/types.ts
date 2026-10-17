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
// status：confirmed 是硬约束；reported 是玩家声明，属软信息，完全不构成硬约束。
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
export interface ExtensionFact extends FactBase {
  type: `${string}:${string}`;
  data: JsonValue;
}

export type Fact = RoleFact | AlignmentFact | ExtensionFact;

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
