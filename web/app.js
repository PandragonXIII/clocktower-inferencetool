"use strict";

const $ = (id) => document.getElementById(id);
const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value) ? value : {};
const list = (value) => Array.isArray(value) ? value : [];
const text = (value) => value === undefined ? "—" : typeof value === "string" ? value : JSON.stringify(value, null, 2);
const labels = { sat: "可满足", unsat: "不可满足（存在矛盾）", unknown: "未知", possible: "可能", necessary: "必然", impossible: "不可能", inconsistent: "前提矛盾", confirmed: "已确认 · 硬约束", reported: "玩家声明 · 软信息" };
const labeled = (value) => typeof value === "string" && Object.hasOwn(labels, value) ? `${labels[value]} (${value})` : text(value);
let currentRequest;
let currentResponse;
let epoch = 0;
let requestBusy = false, pendingTicket, reasonError, errorTicket;
let source = "示例数据，非实时计算";

function node(tag, content, className) {
  const element = document.createElement(tag);
  if (content !== undefined) element.textContent = text(content);
  if (className) element.className = className;
  return element;
}
function notify(message, error = false) {
  $("notice").textContent = message;
  $("notice").className = error ? "error" : "";
}
function section(title, id) {
  const element = node("section", undefined, "card");
  const heading = node("h2", title);
  heading.id = id ? `${id}-title` : `section-${title}`;
  element.setAttribute("aria-labelledby", heading.id);
  if (id) element.id = id;
  element.append(heading);
  return element;
}
function table(parent, headers, rows, caption) {
  if (!rows.length) { parent.append(node("p", "暂无数据（未提供或为空）", "empty")); return; }
  const wrap = node("div", undefined, "table-wrap");
  wrap.tabIndex = 0;
  wrap.setAttribute("role", "region");
  wrap.setAttribute("aria-label", `${caption}，可横向滚动`);
  const t = node("table");
  t.append(node("caption", caption));
  const head = node("thead");
  const tr = node("tr");
  headers.forEach((header) => { const th = node("th", header); th.scope = "col"; tr.append(th); });
  head.append(tr);
  t.append(head);
  const body = node("tbody");
  rows.forEach((cells) => {
    const row = node("tr");
    cells.forEach((value) => { const td = node("td"); td.append(node("pre", text(value))); row.append(td); });
    body.append(row);
  });
  t.append(body); wrap.append(t); parent.append(wrap);
}
function fields(parent, entries) {
  const dl = node("dl");
  entries.forEach(([key, value]) => dl.append(node("dt", key), node("dd", text(value))));
  parent.append(dl);
}
function render(selectedTime) {
  window.NightDeaths.sync(epoch);
  window.DayVoting.sync(epoch);
  const request = object(currentRequest), game = object(request.game), response = object(currentResponse);
  const dashboard = $("dashboard"); dashboard.replaceChildren();
  $("source").textContent = source;
  window.Roundtable.render(currentRequest, currentResponse, selectedTime);
  const overview = section("对局概览", "overview");
  fields(overview, [["对局 id", game.id], ["revision", game.revision], ["剧本", game.script_id], ["当前时间", game.time], ["request_id", request.request_id], ["API 版本", request.api_version], ["推理选项", request.options]]);
  dashboard.append(overview);
  const players = section("所有玩家");
  table(players, ["座位", "玩家 id", "姓名"], list(game.players).map((v) => { const p = object(v); return [p.seat, p.id, p.name]; }), "玩家列表（不将声明当作身份）");
  dashboard.append(players);
  const facts = section("所有事实");
  facts.append(node("p", "confirmed 是硬约束；reported 是玩家声明，不构成硬约束。enabled=false 不参与本次推理。", "hint"));
  table(facts, ["事实 id / 类型", "信息性质", "enabled", "命题（含完整 time）", "扩展 data", "extensions"], list(request.facts).map((v) => { const f = object(v); return [`${text(f.id)}\n${text(f.type)}`, labeled(f.status), f.enabled, f.proposition, f.data, f.extensions]; }), "事实与扩展信息");
  dashboard.append(facts);
  const assumptions = section("临时假设");
  table(assumptions, ["假设 id", "enabled", "命题（含完整 time）", "extensions"], list(request.assumptions).map((v) => { const a = object(v); return [a.id, a.enabled, a.proposition, a.extensions]; }), "仅本次请求生效");
  dashboard.append(assumptions);
  const summary = section("全局推理结果");
  summary.append(node("p", currentResponse === undefined ? "尚无响应。请载入示例、应用响应 JSON 或手动发送到后台。" : "响应如下；结构不完整时缺失字段显示为 —。本页面不是协议校验器。", "hint"));
  fields(summary, [["consistency", labeled(response.consistency)], ["unknown / 原因", response.reason], ["request_id", response.request_id], ["game_id", response.game_id], ["revision", response.revision], ["API 版本", response.api_version]]);
  dashboard.append(summary);
  const queries = section("查询命题与结果");
  const results = list(response.results).map(object);
  const queriesList = list(request.queries).map(object);
  const rows = [];
  queriesList.forEach((q) => {
    const matches = results.filter((r) => r.id === q.id);
    if (!matches.length) rows.push([q.id, q.proposition, "尚无结果", undefined]);
    matches.forEach((r) => rows.push([q.id, q.proposition, labeled(r.status), r.reason]));
  });
  results.filter((r) => !queriesList.some((q) => q.id === r.id)).forEach((r) => rows.push([r.id, "响应中额外的查询，未找到请求命题", labeled(r.status), r.reason]));
  table(queries, ["查询 id", "命题（含完整 time）", "结果", "说明 / unknown 原因"], rows, "查询状态不是概率；前提矛盾时不能当作正常结论");
  dashboard.append(queries);
  const conflicts = section("冲突依据");
  table(conflicts, ["冲突", "输入 input_ids", "规则 rule_ids"], list(response.conflicts).map((v, i) => { const c = object(v); return [i + 1, c.input_ids, c.rule_ids]; }), "冲突子集不保证最小；输入 id 可对照上方事实与假设");
  dashboard.append(conflicts);
  const model = section("模型 assignment");
  table(model, ["玩家 id", "角色 role_id", "阵营 alignment", "完整 time"], list(object(response.model).assignments).map((v) => { const a = object(v); return [a.player_id, a.role_id, a.alignment, a.time]; }), "一个满足解，不代表唯一身份，不含概率");
  dashboard.append(model);
  const errors = section("HTTP / 协议错误");
  fields(errors, [["code", object(response.error).code], ["message", object(response.error).message], ["path（JSON Pointer）", object(response.error).path]]);
  errors.append(node("p", "HTTP 错误是校验或服务问题，不等于逻辑上的 unsat。", "hint"));
  dashboard.append(errors);
  $("raw-request").textContent = text(currentRequest);
  $("raw-response").textContent = text(currentResponse);
}
function matchesRequest(response, request) {
  const r = object(request), g = object(r.game);
  return typeof r.request_id === "string" && typeof g.id === "string" && Number.isInteger(g.revision) && response.request_id === r.request_id && response.game_id === g.id && response.revision === g.revision;
}
function parseRequest() {
  try { currentRequest = JSON.parse($("request-json").value); return true; }
  catch (error) { currentRequest = undefined; notify(`请求 JSON 解析失败：${error.message}。请检查引号、逗号和括号。旧响应已清除。`, true); return false; }
}
function invalidateRequest() {
  window.PlayerActions.close();
  epoch += 1; currentResponse = undefined; $("response-json").value = "";
  source = "本地编辑，尚未计算";
  if (parseRequest()) notify("请求已更新，旧响应已清除。尚未执行推理。");
  render();
}
function applyJSON() {
  window.PlayerActions.close();
  epoch += 1; currentResponse = undefined; source = "本地导入，非实时计算";
  if (!parseRequest()) { render(); return; }
  try {
    const raw = $("response-json").value.trim();
    const response = raw ? JSON.parse(raw) : undefined;
    if (object(response).consistency !== undefined && !matchesRequest(object(response), currentRequest)) throw new Error("响应 request_id / game_id / revision 与当前请求不匹配，已拒绝该响应");
    currentResponse = response;
    notify("JSON 已应用。仅展示数据，未执行推理；缺失字段可在原始 JSON 中检查。错误对象仅按导入内容展示，不证明与请求配对。");
  } catch (error) { notify(`响应未应用：${error.message}。请检查 JSON 格式与请求标识。`, true); }
  render();
}
async function loadExample() {
  window.PlayerActions.close();
  const ticket = ++epoch;
  const choice = $("example").value;
  currentRequest = undefined; currentResponse = undefined;
  $("request-json").value = ""; $("response-json").value = "";
  source = "正在加载示例，非实时计算"; render();
  try {
    const names = [choice === "conflict" ? "conflict-request" : "request", choice];
    const values = await Promise.all(names.map(async (name) => {
      const result = await fetch(`protocol/examples/${name}.json`);
      if (!result.ok) throw new Error(`示例加载失败：HTTP ${result.status}`);
      return result.json();
    }));
    if (ticket !== epoch) return;
    [currentRequest, currentResponse] = values;
    $("request-json").value = JSON.stringify(currentRequest, null, 2);
    $("response-json").value = JSON.stringify(currentResponse, null, 2);
    source = choice === "error" ? "模拟 HTTP 错误，未与请求配对" : "示例数据，非实时计算";
    notify(choice === "error" ? "仅模拟 HTTP 错误展示；错误示例与请求不匹配。未连接后台。" : "已载入配套示例；所有结论来自示例文件，未执行实时计算。");
    render();
  } catch (error) { if (ticket === epoch) { source = "示例加载失败"; render(); notify(`${error.message}。请通过 HTTP 服务打开网页，或手动粘贴 JSON。`, true); } }
}
function validReason(value) {
  const r = object(value);
  const strings = (v) => Array.isArray(v) && v.every((id) => typeof id === "string");
  return r.api_version === "1.0" && typeof r.request_id === "string" && typeof r.game_id === "string" && Number.isInteger(r.revision)
    && ["sat", "unsat", "unknown"].includes(r.consistency)
    && (r.reason === undefined || typeof r.reason === "string")
    && (r.extensions === undefined || (r.extensions !== null && typeof r.extensions === "object" && !Array.isArray(r.extensions)))
    && (r.conflicts === undefined || (Array.isArray(r.conflicts) && r.conflicts.every((c) => strings(c?.input_ids) && strings(c?.rule_ids))))
    && Array.isArray(r.results) && new Set(r.results.map((v) => object(v).id)).size === r.results.length
    && r.results.every((v) => typeof object(v).id === "string" && ["possible", "necessary", "impossible", "inconsistent", "unknown"].includes(object(v).status) && (v.reason === undefined || typeof v.reason === "string"));
}
// 仅补充当前时点的阵营和已有命题；不枚举全角色，不更改 game.time。
function prepareQueries() {
  const r = currentRequest;
  if (!r?.game || !Number.isInteger(r.game.revision) || !Array.isArray(r.queries)) return;
  const time = window.Roundtable.getSelectedTime();
  if (window.PlayerActions.timeIndex(time) > window.PlayerActions.timeIndex(r.game.time)) throw new Error("展示时点晚于对局进度，无法查询未来身份。请先更新实际对局记录。");
  const key = (p) => JSON.stringify([p?.kind, p?.player_id, p?.role_id, p?.alignment, p?.time?.phase, p?.time?.phase === "setup" ? undefined : p?.time?.number]);
  const next = structuredClone(r), known = new Set(r.queries.map((q) => key(q.proposition)));
  const used = new Set([r.request_id, r.game.id, ...list(r.game.players).map((p) => p.id), ...[...list(r.facts), ...list(r.assumptions), ...r.queries].map((v) => v.id)]);
  const add = (p) => {
    const k = key(p); if (known.has(k)) return;
    known.add(k);
    const base = `q-ui-${encodeURIComponent(k)}`;
    let id = base, suffix = 0; while (used.has(id)) id = `${base}-${++suffix}`;
    used.add(id); next.queries.push({ id, proposition: structuredClone(p) });
  };
  list(r.game.players).forEach((p) => ["good", "evil"].forEach((alignment) => add({ kind: "alignment", player_id: p.id, alignment, time })));
  [...list(r.facts), ...list(r.assumptions)].forEach((entry) => {
    const p = entry.proposition;
    if (entry.enabled === true && ["role", "alignment"].includes(p?.kind) && window.PlayerActions.timeIndex(p.time) === window.PlayerActions.timeIndex(time)) add(p);
  });
  if (next.queries.length !== r.queries.length) {
    next.game.revision += 1; next.request_id = uniqueId("req");
    epoch += 1; currentRequest = next; currentResponse = undefined;
    $("request-json").value = JSON.stringify(next, null, 2); $("response-json").value = "";
  }
}
async function sendRequest() {
  if (requestBusy) return;
  window.NightDeaths.close();
  const restoreReasonFocus = document.activeElement === $("send");
  const ticket = ++epoch;
  currentResponse = undefined; $("response-json").value = "";
  source = "手动请求后台";
  if (!parseRequest()) { reasonError = "请求 JSON 无法解析，请检查高级数据。"; errorTicket = ticket; render(); return; }
  try { prepareQueries(); } catch (error) { reasonError = error.message; errorTicket = epoch; render(); notify(error.message, true); return; }
  // 补查询可能改变 revision/epoch；传输期间继续使用这一完整快照。
  const requestTicket = epoch;
  const request = object(currentRequest), game = object(request.game);
  if (typeof request.request_id !== "string" || typeof game.id !== "string" || !Number.isInteger(game.revision)) {
    reasonError = "请求至少需要 request_id、game.id 和整数 game.revision。完整协议由后台校验。"; errorTicket = epoch;
    render(); notify(`无法发送：${reasonError}`, true); return;
  }
  requestBusy = true; pendingTicket = requestTicket;
  render(); notify("正在发送完整快照到同源后台…");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);
  try {
    const result = await fetch("/api/v1/reason", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(currentRequest), signal: controller.signal });
    const body = await result.text();
    if (requestTicket !== epoch) return;
    let data;
    try { data = JSON.parse(body); } catch { throw new Error(`HTTP ${result.status} 返回的不是 JSON，未生成推理结果。后台可能尚未接入`); }
    if (!result.ok) {
      if (object(data).error) {
        currentResponse = data; $("response-json").value = JSON.stringify(data, null, 2); render();
      }
      const detail = object(object(data).error);
      throw new Error(`HTTP ${result.status}：${detail.message || "后台请求失败"}${detail.path ? `（${detail.path}）` : ""}；这不是逻辑矛盾`);
    }
    if (!validReason(data)) throw new Error("后台未返回有效的 reason response，已拒绝展示为推理结果");
    if (!matchesRequest(data, currentRequest)) throw new Error("后台响应标识不匹配（request_id / game_id / revision），已拒绝旧响应");
    currentResponse = data; $("response-json").value = JSON.stringify(data, null, 2);
    const placeholder = object(object(data).extensions)["adapter:mode"] === "placeholder";
    source = placeholder ? "后台响应：占位适配器，未运行推理引擎" : "后台响应（已核对请求标识）"; render();
    notify(placeholder ? "后台响应已接收，但当前为占位适配器，未运行推理引擎，consistency/查询状态均为 unknown。" : "后台响应已接收。");
  } catch (error) {
    if (requestTicket === epoch) {
      reasonError = error.name === "AbortError" ? "请求超过 20 秒，请稍后重试。" : error.message; errorTicket = epoch;
      notify(`发送未成功：${reasonError}。网络、服务或协议失败时不会伪造结果。`, true);
    }
  } finally {
    clearTimeout(timeout); requestBusy = false; pendingTicket = undefined;
    const restore = restoreReasonFocus && document.activeElement === document.body;
    render(); if (restore) $("send")?.focus({ preventScroll: true });
  }
}
$("request-json").addEventListener("input", invalidateRequest);
$("response-json").addEventListener("input", () => {
  epoch += 1; currentResponse = undefined; source = "响应编辑中，尚未应用"; render();
  notify("响应已修改，旧结果已清除。请点击应用 JSON。");
});
$("apply").addEventListener("click", applyJSON);
$("example").addEventListener("change", loadExample);
$("reload").addEventListener("click", loadExample);
["request", "response"].forEach((kind) => {
  $(`${kind}-file`).addEventListener("change", async (event) => {
    const file = event.target.files[0]; if (!file) return;
    const ticket = ++epoch;
    currentResponse = undefined; render();
    try {
      const content = await file.text();
      if (ticket !== epoch) return;
      $(`${kind}-json`).value = content;
      $(`${kind}-json`).dispatchEvent(new Event("input"));
      notify(`已导入${kind === "request" ? "请求" : "响应"}文件。请点击应用 JSON；尚未调用后台。`);
    } catch (error) { if (ticket === epoch) notify(`无法读取文件：${error.message}`, true); }
    event.target.value = "";
  });
});
let mutationSequence = 0;
function uniqueId(prefix) {
  let id;
  const used = new Set([currentRequest?.request_id, currentRequest?.game?.id, ...list(currentRequest?.game?.players).map((p) => p.id), ...[...list(currentRequest?.facts), ...list(currentRequest?.assumptions), ...list(currentRequest?.queries)].map((v) => v.id)]);
  do { id = `${prefix}-${crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${++mutationSequence}`}`; } while (used.has(id));
  return id;
}
function validatePlayerTime(request, playerId, time) {
  if (!list(request.game?.players).some((p) => p.id === playerId)) throw new Error("该玩家已不在当前对局。");
  if (!time || !["setup", "night", "day"].includes(time.phase) || (time.phase !== "setup" && (!Number.isInteger(time.number) || time.number < 1 || time.number > 99))) throw new Error("时间必须为初始配置或 1–99 天/夜。");
}
function validateRoleInput(request, playerId, roleId, time) {
  validatePlayerTime(request, playerId, time);
  if (!Object.hasOwn(window.ClocktowerRoles.names, roleId)) throw new Error("请选择暗流涌动角色。");
}
function validateAlignmentInput(request, playerId, alignment, time) {
  validatePlayerTime(request, playerId, time);
  if (!["good", "evil"].includes(alignment)) throw new Error("阵营必须为善良或邪恶。");
}
function phaseState() {
  if (requestBusy) return { disabled: true, hint: "推理请求进行中，请等待完成后推进。" };
  const g = object(currentRequest?.game), t = object(g.time);
  const validTime = t.phase === "setup" ? t.number === undefined : ["night", "day"].includes(t.phase) && Number.isInteger(t.number) && t.number >= 1 && t.number <= 99;
  if (!validTime || typeof g.id !== "string" || !Number.isSafeInteger(g.revision) || g.revision < 0 || g.revision >= Number.MAX_SAFE_INTEGER) return { disabled: true, hint: "请先创建或载入时间及版本有效的对局。" };
  if (t.phase === "day" && t.number === 99) return { disabled: true, hint: "已达到第 99 天上限，无法继续推进。" };
  const time = t.phase === "setup" ? { phase: "night", number: 1 } : t.phase === "night" ? { phase: "day", number: t.number } : { phase: "night", number: t.number + 1 };
  if (t.phase === "day") {
    const vote = window.DayVoting.current(currentRequest);
    return { disabled: false, time, label: !vote ? "进入投票" : vote.data.stage === "settled" ? "进入夜晚" : "继续投票", hint: vote?.data.stage === "settled" ? "先确认是否还有其他技能，再进入下一夜。" : "白天提名与投票；保存轮次不会推进夜晚。" };
  }
  return { disabled: false, time, label: time.phase === "night" ? "next 进入夜晚" : "next 进入下一天", hint: `第 ${time.number} ${time.phase === "night" ? "夜" : "天"}` };
}
function mutateRequest(change, time, viewTime) {
  if (!currentRequest?.game || !Number.isInteger(currentRequest.game.revision)) throw new Error("请先创建或载入有效对局。");
  const next = structuredClone(currentRequest);
  next.facts = list(next.facts); next.assumptions = list(next.assumptions);
  change(next);
  if (time && window.PlayerActions.timeIndex(time) > window.PlayerActions.timeIndex(next.game.time)) next.game.time = structuredClone(time);
  next.game.revision += 1; next.request_id = uniqueId("req");
  epoch += 1; currentRequest = next; currentResponse = undefined;
  $("request-json").value = JSON.stringify(next, null, 2); $("response-json").value = "";
  source = "本地编辑，尚未计算"; notify("记录已更新，旧响应已清除。技能观察仅记录，尚未参与推理。"); render(viewTime);
  return structuredClone(next);
}
window.App = {
  get votingContext() { return epoch; },
  reason: sendRequest,
  get phaseState() { return phaseState(); },
  advancePhase() {
    const state = phaseState();
    if (state.disabled) throw new Error(state.hint);
    if (currentRequest.game.time.phase === "night") {
      window.NightDeaths.open(currentRequest, epoch);
      return;
    }
    if (currentRequest.game.time.phase === "day") {
      window.PlayerActions.close();
      if (!window.DayVoting.current(currentRequest)) mutateRequest((r) => {
        r.facts.push({ id: uniqueId("f-day-vote"), type: "botc:day_vote", status: "confirmed", enabled: false, data: { time: structuredClone(r.game.time), stage: "voting", nominations: [], execution: null, ...window.DayVoting.defaultResult(r) } });
      });
      window.DayVoting.open(currentRequest, epoch); return;
    }
    window.PlayerActions.close();
    const request = mutateRequest((r) => { r.game.time = structuredClone(state.time); }, undefined, state.time);
    notify(`对局已推进至${state.hint}；历史记录保留，不自动继承身份，尚未执行推理。`);
    return request;
  },
  saveNomination(expected, data) {
    assertVoting(expected, "voting");
    return mutateRequest((r) => {
      const d = window.DayVoting.current(r).data;
      validatePlayerTime(r, data.nominator_id, r.game.time); validatePlayerTime(r, data.nominee_id, r.game.time);
      if (window.NightDeaths.deadAt(r.facts, r.game.time).has(data.nominator_id)) throw new Error("提名者必须存活。");
      if (!Array.isArray(data.voter_ids)) throw new Error("请选择投票者。");
      const voters = [...new Set(data.voter_ids)]; voters.forEach((id) => validatePlayerTime(r, id, r.game.time));
      d.nominations.push({ id: uniqueId("nomination"), nominator_id: data.nominator_id, nominee_id: data.nominee_id, voter_ids: voters, count: voters.length });
    });
  },
  removeNomination(expected, id) {
    assertVoting(expected, "voting");
    return mutateRequest((r) => { const d = window.DayVoting.current(r).data; if (!d.nominations.some((n) => n.id === id)) throw new Error("该轮已不存在。"); d.nominations = d.nominations.filter((n) => n.id !== id); });
  },
  settleVoting(expected, playerId) {
    assertVoting(expected, "voting");
    if (playerId !== null) validatePlayerTime(currentRequest, playerId, currentRequest.game.time);
    return mutateRequest((r) => {
      const d = window.DayVoting.current(r).data, result = window.DayVoting.defaultResult(r);
      Object.assign(d, result, { stage: "settled", execution: { player_id: playerId }, override: result.default_player_id !== playerId });
    }, undefined, currentRequest.game.time);
  },
  finishVotingDay(expected) {
    assertVoting(expected, "settled");
    const time = { phase: "night", number: currentRequest.game.time.number + 1 };
    const request = mutateRequest((r) => { r.game.time = time; }, undefined, time);
    window.DayVoting.close(); window.PlayerActions.close();
    notify(`已进入第 ${time.number} 夜；未自动执行推理。`); return request;
  },
  confirmNightDeaths(expected, playerIds, result) {
    const state = phaseState(), r = currentRequest;
    if (expected !== epoch || !window.NightDeaths.accepts(expected) || state.disabled || r?.game?.time?.phase !== "night") throw new Error("对局已改变或当前无法推进，请重新打开死亡确认。");
    if (!Array.isArray(playerIds) || new Set(playerIds).size !== playerIds.length || !["deaths", "none"].includes(result) || (result === "none" ? playerIds.length !== 0 : playerIds.length === 0)) throw new Error("请选择死亡玩家，或明确确认无人死亡。");
    const time = structuredClone(r.game.time), dead = window.NightDeaths.deadAt(r.facts, time);
    if (window.NightDeaths.records(r.facts).some((f) => f.data?.time?.phase === "night" && f.data.time.number === time.number)) throw new Error("本夜已有死亡记录，不能重复记录。");
    playerIds.forEach((id) => {
      validatePlayerTime(r, id, time);
      if (dead.has(id)) throw new Error("已死亡玩家不能重复死亡。");
    });
    const request = mutateRequest((next) => {
      next.facts.push({ id: uniqueId("f-night-deaths"), type: "botc:night_deaths", status: "confirmed", enabled: false, data: { time, player_ids: [...playerIds], result } });
      next.game.time = structuredClone(state.time);
    }, undefined, state.time);
    window.PlayerActions.close();
    notify(`死亡已记录，尚未参与推理。对局已推进至${state.hint}；未自动执行推理。`);
    return request;
  },
  get reasonState() { return { busy: requestBusy, pending: requestBusy && pendingTicket === epoch, error: errorTicket === epoch ? reasonError : undefined }; },
  isReasonResponse(response, request) { return validReason(response) && matchesRequest(response, request); },
  addAssumption(playerId, roleId, time) {
    return mutateRequest((r) => {
      validateRoleInput(r, playerId, roleId, time);
      r.assumptions.push({ id: uniqueId("a"), enabled: true, proposition: { kind: "role", player_id: playerId, role_id: roleId, time: structuredClone(time) } });
    }, time);
  },
  addAlignmentAssumption(playerId, alignment, time) {
    return mutateRequest((r) => {
      validateAlignmentInput(r, playerId, alignment, time);
      r.assumptions.push({ id: uniqueId("a"), enabled: true, proposition: { kind: "alignment", player_id: playerId, alignment, time: structuredClone(time) } });
    }, time);
  },
  recordAbility(data, expected) {
    if (expected !== undefined) {
      assertVoting(expected, "settled");
      if (JSON.stringify(data.time) !== JSON.stringify(currentRequest.game.time)) throw new Error("结算技能必须记录在当前白天。");
    }
    return mutateRequest((r) => {
      const skill = window.ClocktowerSkills.all.find((s) => s.id === data.ability_id && s.role_id === data.role_id);
      validateRoleInput(r, data.actor_id, data.role_id, data.time);
      window.ClocktowerSkills.validate(skill, data, r.game.players);
      const factId = uniqueId("f-ability"), assumptionId = uniqueId("a-ability");
      r.facts.push({ id: factId, type: "botc:ability_observation", status: "confirmed", enabled: false, data: structuredClone(data), extensions: { "ui:assumption_id": assumptionId } });
      r.assumptions.push({ id: assumptionId, enabled: true, proposition: { kind: "role", player_id: data.actor_id, role_id: data.role_id, time: structuredClone(data.time) }, extensions: { "ui:observation_id": factId } });
    }, data.time);
  },
  setAssumptionEnabled(id, enabled) {
    return mutateRequest((r) => { const a = r.assumptions.find((v) => v.id === id); if (!a) throw new Error("假设已不存在。"); a.enabled = Boolean(enabled); });
  },
  removeAssumption(id) {
    return mutateRequest((r) => {
      r.assumptions = r.assumptions.filter((a) => a.id !== id);
      r.facts.forEach((f) => { if (f.extensions?.["ui:assumption_id"] === id) delete f.extensions["ui:assumption_id"]; });
    });
  },
  removeAbility(id) {
    return mutateRequest((r) => {
      const f = r.facts.find((v) => v.id === id && v.type === "botc:ability_observation");
      if (!f) throw new Error("动作已不存在。");
      r.facts = r.facts.filter((v) => v.id !== id);
      r.assumptions = r.assumptions.filter((a) => !(a.id === f.extensions?.["ui:assumption_id"] && a.extensions?.["ui:observation_id"] === id));
    });
  },
  startGame(request) {
    window.PlayerActions.close();
    epoch += 1;
    currentRequest = request; currentResponse = undefined;
    $("request-json").value = JSON.stringify(request, null, 2);
    $("response-json").value = "";
    source = "初始设置，尚未计算";
    notify("圆桌已创建；本人身份仅为玩家声明。尚未发送后台或执行推理。");
    render();
  }
};
function assertVoting(expected, stage) {
  if (expected !== epoch || !window.DayVoting.accepts(expected) || phaseState().disabled || currentRequest?.game?.time?.phase !== "day" || window.DayVoting.current(currentRequest)?.data.stage !== stage) throw new Error("对局或投票上下文已改变，请重新打开投票窗口。");
}
window.Setup.init(window.App);
