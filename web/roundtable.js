"use strict";

// 展示层只读取快照；不改写协议数据，也不将模型赋值当作结论。
window.Roundtable = (() => {
  const obj = (v) => v && typeof v === "object" && !Array.isArray(v) ? v : {};
  const arr = (v) => Array.isArray(v) ? v : [];
  const roles = window.ClocktowerRoles.names;
  const states = { possible: "可能", necessary: "必然", impossible: "不可能", inconsistent: "前提矛盾", unknown: "未知" };
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = String(text); if (cls) n.className = cls; return n; };
  const index = (time) => { const t = obj(time); return t.phase === "setup" ? 0 : ["day", "night"].includes(t.phase) && Number.isSafeInteger(t.number) && t.number > 0 ? t.number * 2 - (t.phase === "night" ? 1 : 0) : -1; };
  const timeName = (i) => i === 0 ? "初始配置 · setup" : i < 0 ? "未提供时间" : `第 ${Math.ceil(i / 2)} ${i % 2 ? "夜" : "天"}`;
  const value = (p) => p.kind === "role" && typeof p.role_id === "string" && p.role_id ? p.role_id : p.kind === "alignment" && ["good", "evil"].includes(p.alignment) ? p.alignment : undefined;
  const valueName = (kind, v) => kind === "role" ? roles[v] || v : v === "good" ? "善良" : "邪恶";
  let selectedTime = 0, selectedPlayer, gameId, lastRequest, lastResponse, showInference = true;

  function records(players, assumptions, facts) {
    const identityEntries = [...assumptions, ...facts.filter((f) => f.status === "reported" && ["role", "alignment"].includes(f.type))];
    const section = el("section", undefined, "game-records"); section.setAttribute("aria-labelledby", "records-title");
    const title = el("h3", "假设与动作"); title.id = "records-title"; section.append(title);
    const error = el("p", "", "warning"); error.setAttribute("role", "alert"); section.append(error);
    const playerName = (id) => { const p = players.find((v) => v.id === id); return p ? `${p.seat} 号 · ${p.name || p.id}` : id || "未知玩家"; };
    const raw = (card, entry) => { const d = el("details"); d.append(el("summary", "完整来源数据"), el("pre", JSON.stringify(entry, null, 2))); card.append(d); };
    const mutate = (action, rollback = () => {}) => {
      const x = window.scrollX, y = window.scrollY;
      try { action(); } catch (e) { rollback(); error.textContent = `更新失败：${e.message}。记录未更改，请重试。`; }
      window.scrollTo(x, y);
    };
    const remove = (card, label, action, id) => {
      const b = el("button", label); b.type = "button"; b.dataset.focus = `delete-${id}`;
      b.addEventListener("click", () => mutate(action)); card.append(b);
    };
    section.append(window.GlobalAssumptions.cards(facts));
    section.append(el("h4", `身份 / 阵营假设 · ${identityEntries.length}`));
    const list = el("div", undefined, "record-list"); section.append(list);
    if (!identityEntries.length) list.append(el("p", "暂无身份假设。点击圆桌玩家，选择“假设”添加。", "empty"));
    identityEntries.forEach((a) => {
      const p = obj(a.proposition), enabled = a.enabled === true, time = timeName(index(p.time));
      const name = value(p) === undefined ? "其他命题假设" : `${valueName(p.kind, value(p))} ?`;
      const card = el("article", undefined, "evidence record-card"); card.dataset.assumption = a.id;
      card.classList.add("record-assumption"); card.append(el("span", "假设", "record-type"));
      const head = el("div", undefined, "record-head"), copy = el("div", undefined, "record-copy");
      copy.append(el("h5", `${name}${p.kind === "alignment" ? " · 阵营假设" : ""}`), el("p", `${playerName(p.player_id)} ｜ ${time}`));
      const observationId = obj(a.extensions)["ui:observation_id"];
      copy.append(el("p", a.status === "reported" ? "身份声明" : observationId ? "动作关联" : "手工", "hint"));
      const label = el("label", undefined, "assumption-switch"), check = el("input"); check.type = "checkbox"; check.setAttribute("role", "switch"); check.checked = enabled; check.dataset.focus = `assumption-${a.id}`;
      check.setAttribute("aria-label", `${enabled ? "停用" : "启用"} ${playerName(p.player_id)} 在${time}的${value(p) === undefined ? name : valueName(p.kind, value(p))}${p.kind === "alignment" ? "阵营" : "身份"}假设`);
      check.addEventListener("change", () => mutate(() => window.App.setIdentityEnabled(a.id, check.checked), () => { check.checked = enabled; }));
      const track = el("span", undefined, "switch-track"); track.setAttribute("aria-hidden", "true"); label.append(check, track, el("span", enabled ? "已启用" : "已停用")); head.append(copy, label); card.append(head);
      if (!observationId) remove(card, "编辑", () => window.PlayerActions.edit(lastRequest, a), `edit-${a.id}`);
      else { const observation = facts.find((f) => f.id === observationId); if (observation) remove(card, "编辑关联动作", () => window.PlayerActions.edit(lastRequest, observation), `edit-${a.id}`); }
      remove(card, "删除假设", () => window.App.removeIdentity(a.id), a.id); raw(card, a); list.append(card);
    });
    const actions = facts.filter((f) => f.type === "botc:ability_observation");
    section.append(el("h4", `动作观察 · ${actions.length}`));
    const actionList = el("div", undefined, "record-list"); section.append(actionList);
    if (!actions.length) actionList.append(el("p", "暂无动作记录。点击圆桌玩家，选择“动作”记录观察。", "empty"));
    actions.forEach((f) => {
      const data = obj(f.data), result = obj(data.result), skill = window.ClocktowerSkills.all.find((s) => s.id === data.ability_id);
      const card = el("article", undefined, "evidence record-card"); card.dataset.observation = f.id;
      card.classList.add("record-action"); card.append(el("span", "技能动作", "record-type"));
      card.append(el("h5", skill?.name || `${data.ability_id || "未知技能"}（${roles[data.role_id] || data.role_id || "未知角色"}）`), el("p", `${playerName(data.actor_id)} ｜ ${timeName(index(data.time))}`));
      if (arr(data.targets).length) card.append(el("p", `目标：${arr(data.targets).map(playerName).join("、")}`));
      let resultText;
      switch (result.kind) {
        case "role": resultText = `角色：${roles[result.role_id] || result.role_id}`; break;
        case "number": resultText = `数量：${result.value}`; break;
        case "text": resultText = result.text; break;
        case "unobserved": resultText = "未观察到结果"; break;
        case "no_direct_result": resultText = "无直接结果"; break;
        case "no_outsiders": resultText = "无外来者"; break;
        case "choice": resultText = `${skill?.result.options?.find((o) => o.value === result.value)?.label || result.value}${result.role_id ? ` · ${roles[result.role_id] || result.role_id}` : ""}`; break;
        default: resultText = "未识别的结果类型，请展开完整来源数据";
      }
      if (result.kind !== "no_direct_result") card.append(el("p", `结果：${resultText || "未提供"}`, "observation-result"));
      if (typeof data.note === "string" && data.note.trim()) card.append(el("p", `备注：${data.note}`));
      remove(card, "编辑动作", () => window.PlayerActions.edit(lastRequest, f), `edit-${f.id}`);
      remove(card, "删除", () => window.App.removeAbility(f.id), f.id); raw(card, f); actionList.append(card);
    });
    const deaths = window.NightDeaths.records(facts);
    section.append(el("h4", `死亡记录 · ${deaths.length}`));
    const deathList = el("div", undefined, "record-list"); section.append(deathList);
    if (!deaths.length) deathList.append(el("p", "暂无死亡记录。夜晚进入下一天时确认。", "empty"));
    deaths.forEach((f) => {
      const d = obj(f.data), card = el("article", undefined, "evidence record-card"); card.dataset.death = f.id;
      card.classList.add("record-death"); card.append(el("span", "死亡记录", "record-type"));
      card.append(el("h5", `${timeName(index(d.time))}死亡`), el("p", d.result === "none" ? "无人死亡" : arr(d.player_ids).map(playerName).join("、") || "未提供"));
      remove(card, "编辑死亡记录", () => window.NightDeaths.open(lastRequest, window.App.votingContext, f), `edit-${f.id}`);
      raw(card, f); deathList.append(card);
    });
    const votes = window.DayVoting.records(facts);
    section.append(el("h4", `白天投票 · ${votes.length}`));
    const voteList = el("div", undefined, "record-list"); section.append(voteList);
    votes.forEach((f) => {
      const d = obj(f.data), card = el("article", undefined, "evidence record-card"); card.dataset.vote = f.id;
      card.classList.add("record-vote"); card.append(el("span", "提名投票", "record-type"));
      card.append(el("h5", `${timeName(index(d.time))} · ${d.stage === "settled" ? "已结算" : "投票中"}`));
      arr(d.nominations).forEach((n, i) => card.append(el("p", `第 ${i + 1} 轮：${playerName(n.nominator_id)} → ${playerName(n.nominee_id)} · ${arr(n.voter_ids).length} 票`), el("p", `投票者：${arr(n.voter_ids).map(playerName).join("、") || "无"}`)));
      card.append(el("p", `${d.stage === "settled" ? "结算" : "进入投票时"}存活 ${d.alive_count} 人 · 阈值 ${d.threshold} 票`), el("p", d.stage === "settled" ? `处决：${d.execution?.player_id ? playerName(d.execution.player_id) : "无人"} · 默认：${d.default_player_id ? playerName(d.default_player_id) : "无人"}${d.override ? " · 已手动覆盖" : ""}` : "尚未结算，人数与阈值将在结算时重新计算"), el("p", "投票与处决仅记录，尚未参与推理", "warning"));
      raw(card, f); voteList.append(card);
    });
    return section;
  }

  function render(request, response, viewTime) {
    lastRequest = request; lastResponse = response;
    const r = obj(request), g = obj(r.game), s = obj(response);
    const liveRoot = document.getElementById("roundtable");
    const focusKey = liveRoot.contains(document.activeElement) ? document.activeElement.dataset.focus : undefined;
    // 离线构建后一次替换，避免标签测量强制布局时旧内容已清空，导致页面高度骤减并夹紧滚动位置。
    const root = document.createDocumentFragment();
    const facts = arr(r.facts).map(obj), assumptions = arr(r.assumptions).map(obj), queries = arr(r.queries).map(obj);
    const players = arr(g.players).map(obj).sort((a, b) => Number(a.seat) - Number(b.seat));
    // 只在新对局重置；短暂加载/解析失败不丢失用户选定时点。
    if (g.id !== undefined && g.id !== gameId) { gameId = g.id; selectedTime = 0; selectedPlayer = undefined; }
    if (viewTime !== undefined && index(viewTime) >= 0) selectedTime = index(viewTime);
    const times = [0, index(g.time), ...[...facts, ...assumptions, ...queries].map((f) => index(obj(f.proposition).time))];
     const maxTime = Math.min(198, Math.max(...times));
    if (g.id !== undefined) selectedTime = Math.min(selectedTime, maxTime);
    const dead = window.NightDeaths.deadAt(facts, selectedTime === 0 ? { phase: "setup" } : { phase: selectedTime % 2 ? "night" : "day", number: Math.ceil(selectedTime / 2) });
    const deathsNow = window.NightDeaths.deathsAt(facts, selectedTime === 0 ? { phase: "setup" } : { phase: selectedTime % 2 ? "night" : "day", number: Math.ceil(selectedTime / 2) });
    const matched = typeof r.request_id === "string" && typeof g.id === "string" && Number.isInteger(g.revision) && s.request_id === r.request_id && s.game_id === g.id && s.revision === g.revision;
    const placeholder = obj(s.extensions)["adapter:mode"] === "placeholder";
    const validResponse = matched && s.api_version === "1.0" && Array.isArray(s.results) && s.results.every((v) => typeof obj(v).id === "string" && Object.hasOwn(states, obj(v).status));
    const canInfer = showInference && validResponse && s.consistency === "sat" && !placeholder;
    const unsat = showInference && validResponse && s.consistency === "unsat" && !placeholder;
    const conditional = assumptions.some((a) => a.enabled === true);
    const probability = showInference && validResponse && !placeholder && r.options?.probability_mode === true ? obj(s.extensions)["reasoner:probabilities"] : undefined;
    const probabilityRows = probability?.status === "estimated" ? arr(probability.rows) : [];
    const atTime = (entry, id) => { const p = obj(entry.proposition); return p.player_id === id && index(p.time) === selectedTime; };
    const heading = el("div", undefined, "section-head");
    heading.append(el("h2", "圆桌")); root.append(heading);
    if (unsat) root.append(el("p", "当前条件有矛盾", "round-status warning"));
    const legend = el("div", undefined, "legend");
    [["unknown", "? 无身份候选"], ["good", "纯色蓝：确定善良"], ["evil", "纯色红：确定邪恶"], ["pending", "斜纹：阵营待确认"]].forEach(([cls, label]) => legend.append(el("span", label, `legend-${cls}`)));
    root.append(legend);
    const viewport = el("div", undefined, "table-viewport"); viewport.tabIndex = 0; viewport.setAttribute("aria-label", "玩家圆桌，可缩放和平移");
    const board = el("div", undefined, "round-board");
    // 固定可读卡片尺寸，人数越多增加圆半径；窄屏仅圆桌内部滚动。
    const radius = Math.max(210, players.length * 30);
    const size = radius * 2 + 480;
    board.style.width = `${size}px`; board.style.height = `${size}px`; board.style.setProperty("--orbit", `${radius * 2}px`);
    const center = el("div", undefined, "table-center");
    const phaseClass = selectedTime === 0 ? "setup" : selectedTime % 2 ? "night" : "day";
    const phaseTitleText = el("h3", undefined, `phase-badge phase-${phaseClass}`);
    const phaseIcon = el("span", phaseClass === "night" ? "☾" : phaseClass === "day" ? "☀" : "◇"); phaseIcon.setAttribute("aria-hidden", "true");
    phaseTitleText.append(phaseIcon, document.createTextNode(` ${timeName(selectedTime)}`));
    center.append(el("span", g.script_id === "trouble_brewing" ? "暗流涌动" : g.script_id || "等待对局", "eyebrow"), phaseTitleText);
    if (index(g.time) !== selectedTime) center.append(el("span", `历史 · 当前${timeName(index(g.time))}`, "badge phase-history"));
    const timeControls = el("div", undefined, "time-controls");
    [["▲", -1, "上一阶段"], ["▼", 1, "下一阶段"]].forEach(([symbol, delta, label]) => {
      const button = el("button", symbol); button.type = "button"; button.dataset.focus = label; button.setAttribute("aria-label", label); button.title = label;
      button.disabled = delta < 0 ? selectedTime === 0 : selectedTime >= maxTime;
      button.addEventListener("click", () => { selectedTime += delta; render(lastRequest, lastResponse); });
      const row = el("div"); row.append(button, el("span", label)); timeControls.append(row);
    }); board.append(center);
    players.forEach((p, i) => {
      const fs = facts.filter((f) => atTime(f, p.id)), as = assumptions.filter((a) => atTime(a, p.id)), qs = queries.filter((q) => atTime(q, p.id));
      const conclusions = [];
      if (canInfer) qs.forEach((q) => {
        const results = s.results.filter((result) => obj(result).id === q.id);
        if (results.length === 1 && results[0].status === "necessary" && queries.filter((other) => other.id === q.id).length === 1) conclusions.push({ ...q, origin: conditional ? "假设下推理" : "必然推理" });
      });
      const confirmed = fs.filter((f) => f.enabled === true && f.status === "confirmed" && f.type === obj(f.proposition).kind);
      const determinations = [...confirmed.map((f) => ({ ...f, origin: "已确认输入" })), ...conclusions];
      const reported = window.AssumptionTimeline.reportedCandidates(r, p.id, selectedTime === 0 ? { phase: "setup" } : { phase: selectedTime % 2 ? "night" : "day", number: Math.ceil(selectedTime / 2) });
      const activeAssumptions = window.AssumptionTimeline.candidates(r, p.id, selectedTime === 0 ? { phase: "setup" } : { phase: selectedTime % 2 ? "night" : "day", number: Math.ceil(selectedTime / 2) });
      const candidates = [...reported, ...activeAssumptions];
      const values = (entries, kind) => [...new Set(entries.filter((f) => obj(f.proposition).kind === kind).map((f) => value(obj(f.proposition))).filter((v) => v !== undefined))];
      const rs = values(determinations, "role"), als = values(determinations, "alignment"), crs = values(candidates, "role"), cas = values(candidates, "alignment");
      const conflict = rs.length > 1 || als.length > 1;
      const alignment = !conflict && als.length === 1 ? als[0] : "unknown";
      // 仅当没有确定阵营、也没有显式阵营候选时，才把启用中“角色假设”的暗流固有
      // 阵营作为展示性的“不确定默认阵营”（斜纹）。它不写入 confirmed、不生成任何
       // 隐含 alignment 约束；初始身份声明也提供同样的默认色，显式 alignment 候选优先。
       // 候选由时间线处理器负责共享与角色变化边界。
       const assumptionRoles = values(activeAssumptions, "role");
       const initialReportedRoles = values(reported.filter((f) => obj(obj(f.proposition).time).phase === "setup"), "role");
       const roleDefaults = [...new Set([...assumptionRoles, ...initialReportedRoles].map((r) => window.ClocktowerRoles.defaultAlignments[r]).filter(Boolean))];
       const defaultOrigin = assumptionRoles.length && initialReportedRoles.length ? "按角色候选" : assumptionRoles.length ? "按角色假设" : "按身份声明";
      const roleDerived = !cas.length && roleDefaults.length > 0;
      const pendingValues = cas.length ? cas : roleDefaults;
      const pending = !conflict && !als.length && pendingValues.length > 0;
      const pendingClass = pending ? ` pending-${pendingValues.length === 1 ? pendingValues[0] : "mixed"}` : "";
      const button = el("button", undefined, `player-card ${alignment}${pendingClass}${conflict ? " conflict" : ""}`); button.type = "button"; button.dataset.player = p.id; button.dataset.focus = `player-${p.id}`;
      const angle = i * Math.PI * 2 / players.length - Math.PI / 2;
      button.style.left = `${size / 2 + radius * Math.cos(angle)}px`; button.style.top = `${size / 2 + radius * Math.sin(angle)}px`;
      button.setAttribute("aria-pressed", String(selectedPlayer === p.id)); button.setAttribute("aria-haspopup", "dialog");
      const roleText = conflict ? "信息冲突" : rs.length === 1 ? valueName("role", rs[0]) : crs.length === 1 ? `${valueName("role", crs[0])} ?` : crs.length > 1 ? "身份待定 ?" : "?";
      const alignmentText = conflict ? "请核对信息来源" : alignment !== "unknown" ? valueName("alignment", alignment) : pending ? pendingValues.length === 1 ? `${valueName("alignment", pendingValues[0])}？` : "阵营待定" : "阵营未知";
       const candidateText = [crs.length ? `身份候选：${crs.map((v) => valueName("role", v)).join("、")}` : "", cas.length ? `阵营候选：${cas.map((v) => valueName("alignment", v)).join("、")}` : roleDerived ? `${defaultOrigin}推定默认阵营（不确定）：${roleDefaults.map((v) => valueName("alignment", v)).join("、")}` : ""].filter(Boolean).join("；");
      button.title = [`${p.seat ?? "—"} 号 · ${p.name || p.id}`, roleText, alignmentText, candidateText, "点击管理假设与动作；条件、声明和查询来源见高级数据"].filter(Boolean).join("；");
      button.setAttribute("aria-label", button.title);
      if (dead.has(p.id)) {
        button.classList.add("is-dead"); button.title += "；已死亡"; button.setAttribute("aria-label", button.title);
        button.append(el("span", "已死亡", "death-badge"));
      }
      button.append(el("span", `${p.seat ?? "—"} 号 · ${p.name || p.id}`, "player-name"), el("strong", roleText, "player-role"), el("span", alignmentText, "player-alignment"));
      const inferred = conclusions.some((q) => { const prop = obj(q.proposition); return !confirmed.some((f) => obj(f.proposition).kind === prop.kind && value(obj(f.proposition)) === value(prop)); });
      const probabilityMatches = probabilityRows.filter((row) => row.player_id === p.id);
      const probabilities = probabilityMatches.length === 1 ? window.ProbabilityView.entries(probabilityMatches[0]) : [];
      if (probabilities.length) {
        button.classList.remove("good", "evil", "pending-good", "pending-evil", "pending-mixed", "conflict");
        button.classList.add("probability-card");
        button.querySelector(".player-role").textContent = probabilities[0].name;
        button.querySelector(".player-role").classList.add(`probability-${probabilities[0].alignment}`);
        const subtitle = button.querySelector(".player-alignment"); subtitle.textContent = "";
        probabilities.slice(1, 3).filter((item) => item.value >= .1).forEach((item, i) => { if (i) subtitle.append(document.createTextNode(" · ")); subtitle.append(el("span", item.name, `probability-${item.alignment}`)); });
        button.append(el("span", "初始身份估计 ⓘ", "probability-caption"));
        button.title = `${p.seat} 号 · ${p.name || p.id}；初始身份估计：${probabilities.slice(0, 3).map((item) => item.name).join("、")}；点击查看概率环状图。估计不是确定身份。`;
        button.setAttribute("aria-label", button.title);
      }
      const tags = [];
      if (inferred && !probabilities.length) tags.push(conditional ? "假设下推理" : "必然推理");
      const hasConfirmed = determinations.length > 0;
      if (reported.length) tags.push(hasConfirmed ? "另有声明" : "玩家声明");
      if (activeAssumptions.length) tags.push(hasConfirmed ? "另有假设" : "临时假设");
       const observations = facts.filter((f) => f.type === "botc:ability_observation" && obj(f.data).actor_id === p.id && index(obj(f.data).time) === selectedTime);
       if (observations.length) tags.push(`动作 ${observations.length}`);
        if (tags.length) button.append(el("span", tags.join(" · "), "player-tag"));
        if (deathsNow.has(p.id)) {
          const kind = deathsNow.get(p.id), label = kind === "night" ? "本阶段夜间死亡" : kind === "execution" ? "本阶段被投票处决" : "本阶段特殊死亡";
          const stamp = el("span", undefined, `death-stamp death-stamp-${kind}`); stamp.title = label; stamp.setAttribute("aria-hidden", "true");
          const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg"); svg.setAttribute("viewBox", "0 0 32 32"); svg.setAttribute("fill", "none"); svg.setAttribute("stroke", "currentColor"); svg.setAttribute("stroke-width", "2"); svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("stroke-linejoin", "round");
          const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
          path.setAttribute("d", kind === "night" ? "M7 24 22 9 27 4C28 11 24 16 17 19L11 25M6 21l5 5M4 28l5-5" : kind === "execution" ? "M17 2v9M13 6h8M13 9h8M16 12C12 16 8 20 9 24c1 7 14 7 15 0 1-4-3-8-7-12ZM13 3h8" : "M9 22C1 14 7 4 16 4s15 10 7 18v6H9ZM11 14h1m8 0h1M14 20l2-3 2 3M13 25v3m6-3v3");
          svg.append(path); stamp.append(svg); button.append(stamp);
          button.title += `；${label}`; button.setAttribute("aria-label", button.title);
        }
       button.addEventListener("click", () => { selectedPlayer = p.id; render(lastRequest, lastResponse); window.PlayerActions.open(lastRequest, p, selectedTime, probabilities); });
      board.append(button);
    });
    window.ActionVisuals.render(board, facts, selectedTime, players, size, radius);
    viewport.append(board);
    const layout = el("div", undefined, "round-layout"), rail = el("section", undefined, "phase-controls");
    rail.setAttribute("aria-labelledby", "phase-title");
    const phaseTitle = el("h3", "推进对局"); phaseTitle.id = "phase-title";
    const phase = window.App.phaseState;
    const advance = el("button", phase.label || "next 推进对局", "primary"); advance.type = "button"; advance.dataset.focus = "advance-phase";
    advance.disabled = phase.disabled;
    advance.addEventListener("keydown", (event) => { if (event.repeat && ["Enter", " "].includes(event.key)) event.preventDefault(); });
    advance.addEventListener("click", (event) => {
      if (event.detail > 1) return; // 双击不意外跳过一个阶段；键盘 click 的 detail 为 0。
      try { window.App.advancePhase(); } catch (error) { document.getElementById("notice").textContent = error.message; }
    });
    rail.append(phaseTitle, advance);
    if (phase.disabled) { const target = el("p", phase.hint, "hint"); target.id = "phase-target"; advance.setAttribute("aria-describedby", target.id); rail.append(target); }
    const controlArea = el("div", undefined, "round-controls");
    controlArea.append(timeControls);
    layout.append(viewport, controlArea); root.append(layout);
    if (!players.length || (!assumptions.some((a) => a.enabled === true) && !players.some((p) => window.AssumptionTimeline.reportedCandidates(r, p.id, window.Roundtable.getSelectedTime()).length) && ![...facts, ...queries].some((f) => index(obj(f.proposition).time) === selectedTime))) root.append(el("p", "当前展示时点暂无条件或查询。可切换其他阶段查看。", "empty time-empty"));
    root.append(window.Reasoning.render(request, response, window.App.reasonState, rail), records(players, assumptions, facts));
    liveRoot.replaceChildren(root);
    window.TableCamera.mount(viewport, board, controlArea, g.id, size);
    const viewSwitch = el("label", undefined, "table-view-switch");
    const toggle = el("input"); toggle.type = "checkbox"; toggle.checked = showInference; toggle.setAttribute("role", "switch"); toggle.dataset.focus = "inference-view";
    toggle.setAttribute("aria-label", "显示推理结果");
    viewSwitch.title = "开启显示推理结果；关闭显示未推理时的假设与声明。没有有效结果时显示假设。";
    toggle.addEventListener("change", () => { showInference = toggle.checked; render(lastRequest, lastResponse); });
    viewSwitch.append(toggle, el("span", "推理结果")); viewport.querySelector(".table-zoom").prepend(viewSwitch);
    if (focusKey) [...liveRoot.querySelectorAll("[data-focus]")].find((n) => n.dataset.focus === focusKey)?.focus({ preventScroll: true });
  }
   return { render, getSelectedTime() { return selectedTime === 0 ? { phase: "setup" } : { phase: selectedTime % 2 ? "night" : "day", number: Math.ceil(selectedTime / 2) }; }, selectTime(time) { selectedTime = time; render(lastRequest, lastResponse); } };
})();
