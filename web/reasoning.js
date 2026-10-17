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
   bar.append(add, button, status);
   const help = el("p", "查询当前展示时点的阵营和已记录身份候选；保留已有查询，不枚举所有角色。圆桌的跨时点假设延续及转化显示尚未转换为后台全时段约束，不能视为后台已验证。", "hint"); help.id = "reasoning-help";
  const details = el("div"); details.id = "reasoning-details"; details.hidden = true; details.setAttribute("aria-live", "polite");
   const unsupported = el("p", "", "warning"); unsupported.setAttribute("role", "status"); unsupported.hidden = true;
   root.append(title, bar, help, unsupported, details);
  let previousResponse, previousRequest, previousError;
   function render(request, response, state) {
     currentRequest = request;
     add.disabled = !request?.game;
     const globalCount = arr(request?.facts).filter((f) => f.type === "botc:global_assumption" && f.data?.requested_enabled === true).length;
     unsupported.hidden = !globalCount;
     unsupported.textContent = globalCount ? `${globalCount} 条全局假设待后台接入，尚未参与推理；以下结论不包含这些条件。` : "";
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
    if (error) { details.append(el("p", "网络、HTTP 或协议错误不代表输入有矛盾。请检查后台连接或请求内容后重试。")); return root; }
    if (!valid) return root;
    if (placeholder || response.consistency === "unknown") {
      details.append(el("p", response.reason || (placeholder ? "当前为占位适配器，未运行推理引擎。" : "后台未返回无法判断的原因。"))); return root;
    }
    if (response.consistency === "unsat") {
      details.append(el("h4", "矛盾原因"));
      const conflicts = arr(response.conflicts);
      if (!conflicts.length || !conflicts.some((c) => arr(c.input_ids).length || arr(c.rule_ids).length)) details.append(el("p", "后台尚未返回矛盾原因，待接入后展示"));
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
