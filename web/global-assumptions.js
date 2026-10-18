"use strict";

// 全局业务假设：enabled 是真实开关；启用后作为该时点“全员均非此角色”约束参与推理，requested_enabled 仅留给旧读者。
window.GlobalAssumptions = (() => {
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const name = (id) => window.ClocktowerRoles.names[id] || id;
  const timeName = (t) => t?.phase === "setup" ? "初始配置" : `第 ${t?.number} ${t?.phase === "night" ? "夜" : "天"}`;
  let dialog, snapshot;
  function close() {
    if (!dialog?.open) return;
    dialog.close(); snapshot = undefined;
    document.getElementById("add-global-assumption")?.focus({ preventScroll: true });
  }
  function open(request) {
    if (!request?.game) return;
    if (dialog?.open) return;
    snapshot = structuredClone(request);
    if (!dialog) {
      dialog = el("dialog", undefined, "player-actions global-assumptions-dialog"); dialog.setAttribute("aria-labelledby", "global-assumption-title");
      dialog.addEventListener("cancel", (event) => { event.preventDefault(); close(); }); document.body.append(dialog);
    }
    dialog.replaceChildren();
    const header = el("div", undefined, "section-head"), title = el("h2", "新增全局假设"); title.id = "global-assumption-title";
    const cancel = el("button", "关闭"); cancel.type = "button"; cancel.addEventListener("click", close); header.append(title, cancel); dialog.append(header);
    dialog.append(el("p", "用于添加不属于单个玩家的条件。第一版支持“某角色不在场”。", "hint"));
    const form = el("form");
    const field = (label, control) => { const wrap = el("label", undefined, "action-field"); wrap.append(el("span", label), control); form.append(wrap); return control; };
    const type = el("select"); const option = el("option", "某角色不在场"); option.value = "role_absent"; type.append(option); field("假设类型", type);
    const role = el("select"); role.id = "global-assumption-role"; const empty = el("option", "请选择角色"); empty.value = ""; role.append(empty);
    window.ClocktowerRoles.groups.forEach((g) => { const group = el("optgroup"); group.label = g.name; g.roles.forEach(([id, label]) => { const o = el("option", label); o.value = id; group.append(o); }); role.append(group); });
    role.required = true; field("不在场的角色", role);
    const time = window.Roundtable.getSelectedTime();
    form.append(el("p", `作用时点：${timeName(time)}（当前圆桌展示时点）`, "hint"), el("p", "表示该时点所有玩家都不是所选角色，不代表此角色在整局所有时间都不存在。", "hint"));
    const preview = el("p", "选择角色后预览假设。", "round-status"); preview.setAttribute("aria-live", "polite"); form.append(preview);
    role.addEventListener("change", () => { preview.textContent = role.value ? `假设：${timeName(time)}，${name(role.value)}不在场。` : "选择角色后预览假设。"; });
    form.append(el("p", "此假设作为该时点“全员均非此角色”的结构化约束参与推理。保存后默认启用；停用则本次推理不包含该条件。", "warning"));
    const error = el("p", "", "warning"); error.setAttribute("role", "alert"); form.append(error);
    const buttons = el("div", undefined, "toolbar"), save = el("button", "保存假设", "primary"), back = el("button", "取消"); save.type = "submit"; back.type = "button"; back.addEventListener("click", close); buttons.append(save, back); form.append(buttons);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      try { window.App.addGlobalAssumption(role.value, time, snapshot.request_id); close(); }
      catch (e) { error.textContent = e.message; }
    });
    dialog.append(form); dialog.showModal(); role.focus();
  }
  function cards(facts) {
    const records = facts.filter((f) => f.type === "botc:global_assumption"), section = el("section");
    section.append(el("h4", `全局假设 · ${records.length}`));
    const list = el("div", undefined, "record-list"); section.append(list);
    if (!records.length) list.append(el("p", "暂无全局假设。点击“新增假设”添加角色不在场等条件。", "empty"));
    records.forEach((f) => {
      const d = f.data || {}, active = f.enabled === true, card = el("article", undefined, "evidence record-card"); card.dataset.globalAssumption = f.id;
      card.classList.add("record-assumption"); card.append(el("span", "全局假设", "record-type"));
      const heading = d.kind === "role_absent" ? `${name(d.role_id)}不在场 ?` : "其他全局假设";
      const head = el("div", undefined, "record-head"), copy = el("div", undefined, "record-copy");
      copy.append(el("h5", heading), el("p", timeName(d.time)), el("p", active ? "已启用 · 作为该时点全员非此角色的约束参与推理" : "已停用 · 不参与本次推理", "warning"));
      const label = el("label", undefined, "assumption-switch"), check = el("input"); check.type = "checkbox"; check.checked = active; check.setAttribute("role", "switch"); check.dataset.focus = `global-assumption-${f.id}`; check.setAttribute("aria-label", `${active ? "停用" : "启用"}${timeName(d.time)}的${heading}`);
      const error = el("p", "", "warning"); error.setAttribute("role", "alert");
      const mutate = (action) => { const x = window.scrollX, y = window.scrollY; try { action(); } catch (e) { check.checked = active; error.textContent = `更新失败：${e.message}`; } window.scrollTo(x, y); };
      check.addEventListener("change", () => mutate(() => window.App.setGlobalAssumptionEnabled(f.id, check.checked)));
      const track = el("span", undefined, "switch-track"); track.setAttribute("aria-hidden", "true"); label.append(check, track, el("span", active ? "已启用" : "已停用")); head.append(copy, label); card.append(head, error);
      const remove = el("button", "删除假设"); remove.type = "button"; remove.addEventListener("click", () => mutate(() => window.App.removeGlobalAssumption(f.id)));
      const raw = el("details"); raw.append(el("summary", "完整来源数据"), el("pre", JSON.stringify(f, null, 2))); card.append(remove, raw); list.append(card);
    });
    return section;
  }
  function sync(request) { if (dialog?.open && snapshot?.request_id !== request?.request_id) close(); }
  return { open, close, cards, sync };
})();
