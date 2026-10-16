"use strict";

// 投票属于白天；禁用扩展只保存观察，不向引擎注入规则结论。
window.DayVoting = (() => {
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const records = (facts) => (Array.isArray(facts) ? facts : []).filter((f) => f?.type === "botc:day_vote");
  const current = (r) => records(r?.facts).find((f) => f.data?.time?.phase === "day" && r.game.time.phase === "day" && f.data.time.number === r.game.time.number);
  function defaultResult(r) {
    const alive_count = r.game.players.filter((p) => !window.NightDeaths.deadAt(r.facts, r.game.time).has(p.id)).length;
    const threshold = Math.ceil(alive_count / 2), scores = new Map();
    (current(r)?.data.nominations || []).forEach((n) => scores.set(n.nominee_id, Math.max(scores.get(n.nominee_id) || 0, new Set(n.voter_ids).size)));
    const highest_count = Math.max(0, ...scores.values());
    const leaders = [...scores].filter(([, count]) => count === highest_count).map(([id]) => id);
    return { alive_count, threshold, highest_count, default_player_id: alive_count > 0 && highest_count >= threshold && leaders.length === 1 ? leaders[0] : null };
  }
  let dialog, context, request, changing = false, skillOpen = false;
  function close() {
    context = undefined; request = undefined;
    if (skillOpen) { skillOpen = false; window.PlayerActions.close(); }
    if (dialog?.open) dialog.close();
    document.querySelector('[data-focus="advance-phase"]')?.focus({ preventScroll: true });
  }
  function sync(epoch) {
    if (context === undefined || context === epoch) return;
    if (changing && epoch === context + 1) context = epoch;
    else close();
  }
  function perform(action) {
    changing = true;
    try { const next = action(); request = next; return next; }
    finally { changing = false; }
  }
  function button(text, action, primary = false) {
    const b = el("button", text, primary ? "primary" : ""); b.type = "button"; b.id = `vote-button-${text}`;
    b.addEventListener("click", () => { try { action(); } catch (e) { const error = dialog.querySelector('[role="alert"]'); if (error) error.textContent = e.message; } }); return b;
  }
  const name = (id) => { const p = request.game.players.find((p) => p.id === id); return p ? `${p.seat} 号 · ${p.name || p.id}` : id || "无人"; };
  function select(label, id, dead, livingOnly = false, none = false) {
    const wrap = el("label", undefined, "action-field"), s = el("select"); s.id = id;
    if (none) { const o = el("option", "无人处决"); o.value = ""; s.append(o); }
    request.game.players.forEach((p) => { const o = el("option", `${name(p.id)}${dead.has(p.id) ? " · 已死亡" : ""}`); o.value = p.id; o.disabled = livingOnly && dead.has(p.id); s.append(o); });
    if (livingOnly) s.value = request.game.players.find((p) => !dead.has(p.id))?.id || "";
    wrap.append(el("span", label), s); dialog.append(wrap); return s;
  }
  function render() {
    const focus = document.activeElement?.id;
    dialog.replaceChildren();
    const d = current(request).data, settled = d.stage === "settled", dead = window.NightDeaths.deadAt(request.facts, request.game.time);
    const header = el("div", undefined, "section-head"), title = el("h2", `第 ${d.time.number} 天 · ${settled ? "其他技能确认" : "提名与投票"}`); title.id = "day-voting-title";
    header.append(title, button("关闭（保留已保存记录）", close)); dialog.append(header);
    const result = settled ? d : defaultResult(request);
    dialog.append(el("p", `存活 ${result.alive_count} 人 · 阈值 ${result.threshold} 票（至少一半，向上取整）。${settled ? "结算时人数与阈值已保存。" : "以结算时存活人数为准。"}`, "round-status"));
    dialog.append(el("p", "每轮独立计票；同一人多轮取最高票，不累加。不同人最高票相同则默认无人。允许手动覆盖及技能例外；这里只记录观察，尚未参与推理。", "hint"));
    const rounds = el("div", undefined, "vote-rounds"); dialog.append(rounds);
    if (!d.nominations.length) rounds.append(el("p", "暂无提名；也可直接结算为无人处决。", "empty"));
    d.nominations.forEach((n, i) => {
      const card = el("article", undefined, "evidence"); card.dataset.nomination = n.id;
      card.append(el("h3", `第 ${i + 1} 轮 · ${n.voter_ids.length} 票`), el("p", `${name(n.nominator_id)} → ${name(n.nominee_id)}`), el("p", `投票者：${n.voter_ids.map((id) => `${name(id)}${dead.has(id) ? "（已死亡）" : ""}`).join("、") || "无"}`));
      if (!settled) { const remove = button("删除本轮", () => { perform(() => window.App.removeNomination(context, n.id)); render(); dialog.querySelector('#vote-nominator')?.focus({ preventScroll: true }); }); remove.id = `vote-delete-${n.id}`; card.append(remove); } rounds.append(card);
    });
    const error = el("p", "", "warning"); error.setAttribute("role", "alert"); dialog.append(error);
    if (settled) {
      dialog.append(el("p", `已确认处决：${name(d.execution?.player_id)}${d.override ? "（手动覆盖默认）" : "（采用默认）"}。仍处于白天。`, "round-status"), el("h3", "是否还有其他技能发动？"), el("p", "可反复记录技能；默认没有新增技能，不要求必须录入。保存或取消后返回此页。", "hint"));
      const actor = select("发动玩家（含死者）", "vote-actor", dead);
      dialog.append(button("记录技能", () => {
        const expected = context, actorId = actor.value;
        dialog.close(); skillOpen = true;
        const resume = () => { skillOpen = false; if (context === undefined) return; render(); dialog.showModal(); dialog.querySelector("#vote-actor")?.focus(); };
        window.PlayerActions.openAbility(request, request.game.players.find((p) => p.id === actorId), request.game.time, { expected, onClose: resume, onComplete: resume });
      }), button("没有了，进入夜晚", () => perform(() => window.App.finishVotingDay(context)), true));
    } else {
      const nominator = select("提名者（必须存活）", "vote-nominator", dead, true), nominee = select("被提名者（可为死者）", "vote-nominee", dead);
      const group = el("fieldset"); group.append(el("legend", "本轮投票者")); const checks = [];
      request.game.players.forEach((p) => { const c = el("input"); c.type = "checkbox"; c.name = "vote-voter"; c.value = p.id; const label = el("label", undefined, "target-option"); label.append(c, el("span", `${name(p.id)}${dead.has(p.id) ? " · 死者票" : ""}`)); group.append(label); checks.push(c); }); dialog.append(group, el("p", "死者也可勾选。暂不限制每局一次死者票，也不限制重复提名；请按实际情况记录。关闭会丢弃尚未保存的本轮表单。", "hint"));
      const save = button("保存本轮提名投票", () => { perform(() => window.App.saveNomination(context, { nominator_id: nominator.value, nominee_id: nominee.value, voter_ids: checks.filter((c) => c.checked).map((c) => c.value) })); render(); }); save.disabled = !nominator.value; dialog.append(save);
      const execution = select("结算处决者（可手动覆盖默认）", "vote-execution", dead, false, true); execution.value = result.default_player_id || "";
      dialog.append(el("p", `默认：${name(result.default_player_id)} · 最高 ${result.highest_count} 票。全员死亡时不默认选择任何人。已死者处决不会重复减少人数。`, "hint"), button("结算投票", () => { perform(() => window.App.settleVoting(context, execution.value || null)); render(); }, true));
    }
    if (focus) (dialog.querySelector(`#${CSS.escape(focus)}`) || dialog.querySelector("button"))?.focus({ preventScroll: true });
  }
  function open(r, expected) {
    if (!dialog) { dialog = el("dialog", undefined, "player-actions day-voting"); dialog.id = "day-voting-dialog"; dialog.setAttribute("aria-labelledby", "day-voting-title"); dialog.addEventListener("cancel", (e) => { e.preventDefault(); close(); }); document.body.append(dialog); }
    request = structuredClone(r); context = expected; render(); if (!dialog.open) dialog.showModal(); dialog.querySelector("button")?.focus();
  }
  return { records, current, defaultResult, open, close, sync, perform, accepts: (expected) => context === expected && (dialog?.open || skillOpen) };
})();
