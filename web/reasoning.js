"use strict";

// 独立视图，发送仍只经过 App.reason → sendRequest。
window.Reasoning = (() => {
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const arr = (v) => Array.isArray(v) ? v : [];
  const timeName = (t) => t?.phase === "setup" ? "初始配置" : t && ["day", "night"].includes(t.phase) ? `第 ${t.number} ${t.phase === "night" ? "夜" : "天"}` : "未提供时间";
  function describe(p, request) {
    if (!p || !["role", "alignment"].includes(p.kind)) return "其他记录（请查看完整来源）";
    const player = arr(request?.game?.players).find((v) => v.id === p.player_id);
    const name = player ? `${player.seat} 号 · ${player.name || player.id}` : p.player_id;
    const value = p.kind === "role" ? window.ClocktowerRoles.names[p.role_id] || p.role_id : p.alignment === "good" ? "善良阵营" : p.alignment === "evil" ? "邪恶阵营" : p.alignment;
    return `${name} ｜ ${timeName(p.time)} ｜ ${value}`;
  }
  const root = el("section", undefined, "reasoning"); root.id = "reasoning"; root.setAttribute("aria-labelledby", "reasoning-title");
  const title = el("h3", "推理"); title.id = "reasoning-title";
  const bar = el("div", undefined, "reasoning-bar");
  const button = el("button", "开始推理", "primary"); button.id = "send"; button.type = "button"; button.dataset.focus = "reason"; button.setAttribute("aria-describedby", "reasoning-help"); button.setAttribute("aria-controls", "reasoning-details");
  button.addEventListener("click", () => window.App.reason());
  const status = el("p", ""); status.id = "reasoning-status"; status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite"); status.setAttribute("aria-atomic", "true");
   const add = el("button", "新增假设"); add.id = "add-global-assumption"; add.type = "button"; add.dataset.focus = "global-assumption"; add.setAttribute("aria-haspopup", "dialog");
   let currentRequest;
   add.addEventListener("click", () => window.GlobalAssumptions.open(currentRequest));
    const probabilityToggle = document.getElementById("probability-mode");
    probabilityToggle.addEventListener("change", () => window.App.setProbabilityMode(probabilityToggle.checked));
    bar.append(add, button, status);
    const help = el("div", undefined, "reasoning-help");
    const helpIcon = el("button", "?", "reasoning-help-icon"); helpIcon.type = "button"; helpIcon.setAttribute("aria-label", "推理范围说明"); helpIcon.setAttribute("aria-describedby", "reasoning-help");
    const helpText = el("p", "查询当前时点的阵营和身份候选。跨时点延续仅用于卡片显示；停用记录不参与。概率模式单独估计初始身份，不改变逻辑条件。", "reasoning-tooltip"); helpText.id = "reasoning-help"; helpText.setAttribute("role", "tooltip");
    help.append(helpIcon, helpText);
  const details = el("div"); details.id = "reasoning-details"; details.hidden = true; details.setAttribute("aria-live", "polite");
   const participation = el("div"); participation.id = "reasoning-participation"; participation.setAttribute("role", "status"); participation.hidden = true;
    const columns = el("div", undefined, "reasoning-columns"), left = el("div", undefined, "reasoning-main"), right = el("div", undefined, "reasoning-phase");
    left.append(title, bar, help); columns.append(left, right);
    root.append(columns, participation, details);
  let previousResponse, previousRequest, previousError;
   const name = (id) => window.ClocktowerRoles.names[id] || id;
   const participationLabel = (request, p) => {
     const entry = [...arr(request?.assumptions), ...arr(request?.facts), ...arr(request?.queries)].find((v) => v.id === p.id);
     if (!entry) return p.id;
     if (entry.data?.ability_id) return window.ClocktowerSkills.all.find((s) => s.id === entry.data.ability_id)?.name || entry.data.ability_id;
     if (entry.data?.kind === "role_absent") return `${name(entry.data.role_id)}不在场（${timeName(entry.data.time)}）`;
     if (entry.proposition) return describe(entry.proposition, request);
     return entry.type || p.id;
   };
   const statusText = { applied: "已作为结构化约束参与", partial: "只提供了部分结构化约束", record_only: "仅记录，未产生结构化约束", disabled: "已停用，不参与推理" };
   function render(request, response, state, phaseControls) {
       if (phaseControls) right.replaceChildren(phaseControls);
      currentRequest = request;
      probabilityToggle.checked = request?.options?.probability_mode === true;
      probabilityToggle.disabled = !request?.game || state.busy;
     add.disabled = !request?.game;
     const globals = arr(request?.facts).filter((f) => f.type === "botc:global_assumption");
     const enabledGlobals = globals.filter((f) => f.enabled === true).length, disabledGlobals = globals.length - enabledGlobals;
     const answered = response && window.App.isReasonResponse(response, request);
     const rows = answered ? arr(response.extensions?.["reasoner:participation"]) : [];
     const lines = [];
     if (!answered) {
       if (enabledGlobals) lines.push(`${enabledGlobals} 条已启用的全局假设将作为“该时点全员非此角色”的结构化约束参与推理。`);
       if (disabledGlobals) lines.push(`${disabledGlobals} 条已停用的全局假设不参与本次推理。`);
     } else {
       const applied = rows.filter((p) => p.status === "applied").length;
       if (applied) lines.push(`${applied} 条输入已作为结构化约束参与推理。`);
       rows.filter((p) => ["partial", "record_only", "disabled"].includes(p.status)).forEach((p) => {
         lines.push(`${participationLabel(request, p)}：${statusText[p.status] || p.status}${p.reason ? `（${p.reason}）` : ""}`);
       });
       if (disabledGlobals) lines.push(`${disabledGlobals} 条已停用的全局假设不参与本次推理。`);
     }
     participation.hidden = !lines.length;
     participation.replaceChildren(...lines.map((t) => el("p", t, "warning")));
    const { busy, pending, error } = state;
    button.disabled = busy; button.textContent = busy ? "推理中…" : "开始推理";
    button.setAttribute("aria-busy", String(busy));
    const valid = response && window.App.isReasonResponse(response, request);
    const placeholder = valid && response.extensions?.["adapter:mode"] === "placeholder";
    const label = pending ? "正在推理…" : error ? `推理请求失败：${error}` : placeholder ? "后台尚未接入推理" : !valid ? "" : response.consistency === "unsat" ? "有矛盾" : response.consistency === "sat" ? "有可行解" : "暂时无法判断";
    if (status.textContent !== label) status.textContent = label;
    status.className = error || (valid && !placeholder && response.consistency === "unsat") ? "warning" : "";
    // 无响应时确实留白；编辑后的旧请求即使仍在传输也不显示旧反馈。
    details.hidden = pending || (!valid && !error);
    button.setAttribute("aria-expanded", String(!details.hidden));
    if (previousResponse === response && previousRequest === request && previousError === error) return root;
    previousResponse = response; previousRequest = request; previousError = error;
     details.replaceChildren();
     const probabilityDetails = document.getElementById("probability-details");
     probabilityDetails.replaceChildren(); probabilityDetails.hidden = true;
    if (error) { details.append(el("p", "网络、HTTP 或协议错误不代表输入有矛盾。请检查后台连接或请求内容后重试。")); return root; }
     if (!valid) return root;
      const probability = response.extensions?.["reasoner:probabilities"];
      if (probability) {
        probabilityDetails.hidden = false;
        probabilityDetails.append(el("h4", "初始身份概率估计"), el("p", probability.description || "带权抽样估计，不是精确概率，也不是必然结论。", "hint"));
       if (probability.status !== "estimated") details.append(el("p", probability.reason || "概率估计未完成，不能当作零概率。", "warning"));
       else arr(probability.rows).forEach((row) => {
         const player = arr(request.game?.players).find((p) => p.id === row.player_id);
         const values = Object.entries(row.probabilities || {}).sort((a, b) => b[1] - a[1]);
          probabilityDetails.append(el("p", `${player ? `${player.seat} 号` : row.player_id}：${values.map(([role, value]) => `${name(role)} ${(value * 100).toFixed(1)}%`).join("、")}`));
       });
        if (probability.status === "estimated" && probability.reason) details.append(el("p", probability.reason, "warning"));
        if (probability.status === "estimated" && response.consistency === "unsat") details.append(el("p", "全部启用条件一起采信时有矛盾；以上概率通过分别采信不同条件组合估计，不表示这些条件可以同时成立。", "hint"));
      }
     if (placeholder || response.consistency === "unknown") {
      details.append(el("p", response.reason || (placeholder ? "当前为占位适配器，未运行推理引擎。" : "后台未返回无法判断的原因。"))); return root;
    }
    if (response.consistency === "unsat") {
      details.append(el("h4", "矛盾原因"));
      const conflicts = arr(response.conflicts);
       if (!conflicts.length || !conflicts.some((c) => arr(c.input_ids).length || arr(c.rule_ids).length)) details.append(el("p", request.options?.probability_mode ? "全部条件一起采信时已证明矛盾。概率模式跳过详细冲突诊断以减少等待；概率估计会单独考虑不同采信组合。" : "后台本次未取得详细冲突依据。"));
      conflicts.forEach((c, i) => {
        const card = el("article", undefined, "evidence"); card.append(el("h5", `冲突 ${i + 1}`));
        arr(c.input_ids).forEach((id) => {
          const a = arr(request.assumptions).find((v) => v.id === id), f = arr(request.facts).find((v) => v.id === id), entry = a || f;
          const skill = window.ClocktowerSkills.all.find((v) => v.id === f?.data?.ability_id);
          card.append(el("p", entry ? `${a ? "假设" : f.status === "reported" ? "玩家声明" : "事实记录"}：${entry.proposition ? describe(entry.proposition, request) : skill?.name || f.type}` : "后台引用的输入（当前记录中未找到）"), el("p", `input_id: ${id}`, "hint"));
        });
        arr(c.rule_ids).forEach((id) => card.append(el("p", `rule_id: ${id}`, "hint")));
        details.append(card);
      });
      details.append(el("p", "以上是后台返回的冲突依据，不保证是最小冲突，也不是完整证明。", "hint"));
    } else {
      const possible = arr(response.extensions?.["trouble_brewing:possible_roles"]);
      details.append(el("h4", "可能身份"));
      if (!possible.length) details.append(el("p", "后台未返回每位玩家的可能身份。"));
      possible.forEach((row) => {
        const player = arr(request.game?.players).find((p) => p.id === row.player_id);
        const who = player ? `${player.seat} 号 · ${player.name || player.id}` : row.player_id;
        const names = arr(row.role_ids).map((id) => window.ClocktowerRoles.names[id] || id);
        const card = el("article", undefined, "evidence");
        card.append(el("p", names.length ? `${who}：${names.join("、")}` : `${who}：无法为任何身份`));
        details.append(card);
      });
      details.append(el("h4", "恒为真结论"), el("p", "下面只列出在当前已启用假设下必然成立的阵营或身份。", "hint"));
      const conclusions = arr(request.queries).filter((q) => arr(request.queries).filter((v) => v.id === q.id).length === 1 && arr(response.results).filter((v) => v.id === q.id).length === 1 && response.results.find((v) => v.id === q.id).status === "necessary");
       if (!conclusions.length) details.append(el("p", "后台未在本次查询中返回必然结论，不代表不存在其他必然结论。"));
       details.append(el("p", "结论基于当前启用的条件输入，包括 reported 声明；它们不是无条件事实。", "hint"));
      conclusions.forEach((q) => { const card = el("article", undefined, "evidence"); card.append(el("p", describe(q.proposition, request))); details.append(card); });
    }
    return root;
  }
  return { render };
})();
