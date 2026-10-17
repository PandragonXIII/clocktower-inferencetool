"use strict";

// 死亡是用户观察，不是角色/阵营命题；禁用扩展仍可用于本地展示。
window.NightDeaths = (() => {
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const index = (t) => t?.phase === "setup" ? 0 : ["night", "day"].includes(t?.phase) && Number.isInteger(t.number) && t.number >= 1 && t.number <= 99 ? t.number * 2 - (t.phase === "night" ? 1 : 0) : -1;
  const records = (facts) => (Array.isArray(facts) ? facts : []).filter((f) => f?.type === "botc:night_deaths");
  function deadAt(facts, time) {
    const dead = new Set(), at = index(time);
    records(facts).forEach((f) => {
      const d = f.data;
      if (f.status === "confirmed" && d?.time?.phase === "night" && index(d.time) > 0 && index(d.time) <= at && d.result === "deaths" && Array.isArray(d.player_ids)) d.player_ids.forEach((id) => { if (typeof id === "string") dead.add(id); });
    });
    (Array.isArray(facts) ? facts : []).forEach((f) => {
      const d = f?.data;
      if (f.type === "botc:day_vote" && f.status === "confirmed" && d?.stage === "settled" && d.time?.phase === "day" && index(d.time) > 0 && index(d.time) <= at && typeof d.execution?.player_id === "string") dead.add(d.execution.player_id);
    });
    return dead;
  }
  let dialog, context, saving = false;
  function close() {
    context = undefined;
    if (!dialog?.open) return;
    dialog.close();
    document.querySelector('[data-focus="advance-phase"]')?.focus({ preventScroll: true });
  }
  function sync(expected) { if (context !== undefined && context !== expected) close(); }
  function open(request, expected) {
    if (dialog?.open || saving) return;
    window.PlayerActions.close();
    if (!dialog) {
      dialog = el("dialog", undefined, "player-actions night-deaths"); dialog.id = "night-deaths-dialog";
      dialog.setAttribute("aria-labelledby", "night-deaths-title"); dialog.setAttribute("aria-describedby", "night-deaths-help");
      dialog.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
      document.body.append(dialog);
    }
    context = expected; dialog.replaceChildren();
    const heading = el("h2", `第 ${request.game.time.number} 夜死亡`); heading.id = "night-deaths-title";
    const cancel = el("button", "取消（不推进）"); cancel.type = "button"; cancel.addEventListener("click", close);
    const header = el("div", undefined, "section-head"); header.append(heading, cancel);
    const help = el("p", "请选择昨晚死亡的玩家（可多选），或明确勾选“无人死亡”。确认后才进入白天；死亡已记录，尚未参与推理。", "hint"); help.id = "night-deaths-help";
    const form = el("form"), group = el("fieldset"); group.append(el("legend", "昨晚死亡的玩家"));
    const dead = deadAt(request.facts, request.game.time), checks = [];
    [...request.game.players].sort((a, b) => a.seat - b.seat).forEach((p) => {
      const check = el("input"); check.type = "checkbox"; check.name = "night-death-player"; check.value = p.id; check.disabled = dead.has(p.id);
      const label = el("label", undefined, "target-option"); label.append(check, el("span", `${p.seat} 号 · ${p.name || p.id}${check.disabled ? " · 已死亡" : ""}`)); group.append(label); checks.push(check);
    });
    const none = el("input"); none.type = "checkbox"; none.id = "night-deaths-none";
    const noneLabel = el("label", undefined, "target-option"); noneLabel.append(none, el("span", "无人死亡（明确确认）"));
    const error = el("p", "", "warning"); error.setAttribute("role", "alert");
    const save = el("button", "确认记录并进入白天", "primary"); save.type = "submit"; save.disabled = true;
    const update = () => { save.disabled = saving || (!none.checked && !checks.some((c) => c.checked)); };
    checks.forEach((c) => c.addEventListener("change", () => { if (c.checked) none.checked = false; update(); }));
    none.addEventListener("change", () => { if (none.checked) checks.forEach((c) => { c.checked = false; }); update(); });
    form.append(group, noneLabel, error, save); dialog.append(header, help, form);
    form.addEventListener("submit", (e) => {
      e.preventDefault(); if (saving || context !== expected || save.disabled) return;
      saving = true; update();
      try { window.App.confirmNightDeaths(expected, checks.filter((c) => c.checked).map((c) => c.value), none.checked ? "none" : "deaths"); close(); }
      catch (err) { error.textContent = err.message; }
      finally { saving = false; update(); }
    });
    dialog.showModal(); cancel.focus();
  }
  return { records, deadAt, open, close, sync, accepts(expected) { return dialog?.open === true && context === expected; } };
})();
