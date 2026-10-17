"use strict";

window.PlayerActions = (() => {
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const names = window.ClocktowerRoles.names;
  const timeIndex = (t) => t?.phase === "setup" ? 0 : t?.number * 2 - (t?.phase === "night" ? 1 : 0);
  const timeFrom = (i) => i === 0 ? { phase: "setup" } : { phase: i % 2 ? "night" : "day", number: Math.ceil(i / 2) };
  const timeName = (t) => t.phase === "setup" ? "初始配置" : `第 ${t.number} ${t.phase === "night" ? "夜" : "天"}`;
  let dialog, body, heading, context, opener;
  function button(label, action, primary = false) {
    const b = el("button", label, primary ? "primary" : ""); b.type = "button"; b.addEventListener("click", action); return b;
  }
  function select(items, id) {
    const s = el("select"); if (id) s.id = id;
    items.forEach(([value, label]) => { const o = el("option", label); o.value = value; s.append(o); }); return s;
  }
  function field(parent, label, control) { const wrap = el("label", undefined, "action-field"); wrap.append(el("span", label), control); parent.append(wrap); return control; }
  function roleSelect(ids = Object.keys(names)) { return select([["", "请选择角色"], ...ids.map((id) => [id, names[id]])]); }
  function close() {
    if (!dialog?.open) return;
    const callback = context?.onClose;
    dialog.close(); context = undefined;
    document.querySelector(`[data-player="${CSS.escape(opener || "")}"]`)?.focus({ preventScroll: true });
    callback?.();
  }
  function init() {
    if (dialog) return;
    dialog = el("dialog", undefined, "player-actions"); dialog.setAttribute("aria-labelledby", "action-title");
    const header = el("div", undefined, "section-head"); heading = el("h2"); heading.id = "action-title";
    header.append(heading, button("关闭", close)); body = el("div"); dialog.append(header, body); document.body.append(dialog);
    dialog.addEventListener("cancel", (event) => { event.preventDefault(); close(); });
  }
  function title() { const p = context.actor; heading.textContent = `${p.seat} 号 · ${p.name || p.id} ｜ ${timeName(context.time)}`; }
  function home(focus = true) {
    body.replaceChildren(); title();
    const actions = el("div", undefined, "action-choices"); actions.append(button("假设 · 假设身份", () => editor(false), true), button("动作 · 记录观察", () => editor(true), true)); body.append(actions);
    body.append(el("p", "圆桌下方“假设与动作”汇总整局全部时点记录。此处管理该玩家的假设和动作；既有条件、声明与查询可在“高级数据 / 调试”查看。", "hint"));
    const { request, actor } = context;
    const assumptions = (request.assumptions || []).filter((a) => a.proposition?.player_id === actor.id);
    const describeAssumption = (p) => p.kind === "alignment" ? (p.alignment === "good" ? "善良阵营" : p.alignment === "evil" ? "邪恶阵营" : p.alignment) : names[p.role_id] || JSON.stringify(p);
    body.append(el("h3", "身份 / 阵营假设"));
    if (!assumptions.length) body.append(el("p", "暂无身份或阵营假设", "empty"));
    assumptions.forEach((a) => {
      const block = el("div", undefined, "evidence");
      block.append(el("p", `${describeAssumption(a.proposition)}${a.proposition.kind === "alignment" ? " · 阵营假设" : ""} · ${timeName(a.proposition.time)} · ${a.enabled ? "启用" : "停用"}${a.extensions?.["ui:observation_id"] ? " · 动作关联" : ""}`));
      block.append(button(a.enabled ? "停用假设" : "恢复假设", () => mutate(() => window.App.setAssumptionEnabled(a.id, !a.enabled))), button("删除假设", () => mutate(() => window.App.removeAssumption(a.id)))); body.append(block);
    });
    body.append(el("h3", "动作观察"));
    const observations = (request.facts || []).filter((f) => f.type === "botc:ability_observation" && f.data?.actor_id === actor.id);
    if (!observations.length) body.append(el("p", "暂无动作记录", "empty"));
    observations.forEach((f) => {
      const block = el("div", undefined, "evidence");
      block.append(el("p", `${window.ClocktowerSkills.all.find((s) => s.id === f.data.ability_id)?.name || f.data.ability_id} · ${timeName(f.data.time)}`), el("p", "已记录，技能结果尚未参与推理", "warning"));
      const raw = el("details"); raw.append(el("summary", "目标、结果、备注及完整数据"), el("pre", JSON.stringify(f, null, 2))); block.append(raw);
      block.append(button("删除动作（保留共用身份）", () => mutate(() => window.App.removeAbility(f.id)))); body.append(block);
    });
    if (focus) body.querySelector("button")?.focus();
  }
  function mutate(action) {
    try { const request = action(); context.request = request; home(); }
    catch (error) { body.append(el("p", error.message, "warning")); }
  }
  function editor(ability) {
    body.replaceChildren(); body.append(button("返回（不保存）", () => context.onClose ? close() : home()));
    const form = el("form"); form.noValidate = true; body.append(form);
    const phase = select([["setup", "初始配置 setup"], ["night", "夜 night"], ["day", "天 day"]]); phase.value = context.time.phase;
    const number = el("input"); number.type = "number"; number.min = "1"; number.max = "99"; number.step = "1"; number.value = String(context.time.number || 1);
    const numberWrap = el("div");
    form.append(el("p", `记录时点：${timeName(context.time)}（固定）`, "hint"));
    if (context.onClose) { phase.disabled = true; number.disabled = true; }
    const sync = el("p", "", "hint");
    const readTime = () => {
      if (phase.value === "setup") return { phase: "setup" };
      const n = Number(number.value); if (!Number.isInteger(n) || n < 1 || n > 99) throw new Error("阶段编号须为 1–99 的正整数。");
      return { phase: phase.value, number: n };
    };
    const updateTime = () => {
      numberWrap.hidden = phase.value === "setup";
      try { const t = readTime(); sync.textContent = timeIndex(t) > timeIndex(context.request.game.time) ? `对局进度同步至${timeName(t)}` : "历史记录不会使对局进度后退。"; } catch (e) { sync.textContent = e.message; }
    };
    phase.addEventListener("change", updateTime); number.addEventListener("input", updateTime); updateTime();
    const choice = ability ? select([["", "请选择一个技能"]], "ability-choice") : roleSelect();
    if (!ability) choice.id = "assumption-role";
    const kindSelect = ability ? undefined : select([["role", "身份 role"], ["alignment", "阵营 alignment"]], "assumption-kind");
    if (kindSelect) field(form, "假设类型", kindSelect);
    field(form, ability ? "技能选项（每次记录一项）" : "假设身份（22 角色）", choice);
    const alignmentSelect = ability ? undefined : select([["good", "善良 good"], ["evil", "邪恶 evil"]], "assumption-alignment");
    const alignmentWrap = alignmentSelect ? field(form, "假设阵营", alignmentSelect).parentElement : undefined;
    if (alignmentWrap) alignmentWrap.hidden = true;
    const preview = el("p", ability ? "请选择后预览身份假设。" : "请选择假设类型与内容后预览。", "round-status"); preview.setAttribute("aria-live", "polite"); form.append(preview);
    const controls = el("div"); form.append(controls);
    const availabilityHint = el("p", "", "hint"); availabilityHint.setAttribute("role", "status"); if (ability) form.insertBefore(availabilityHint, preview);
    const unavailable = el("details"); unavailable.append(el("summary", "查看当前不可用技能及原因"));
    const unavailableList = el("ul"); unavailable.append(unavailableList); if (ability) form.insertBefore(unavailable, preview);
    const note = el("textarea"); note.rows = 3; note.className = "ability-note"; if (ability) field(form, "技能备注（可选）", note);
    const error = el("p", "", "warning"); error.setAttribute("role", "alert"); form.append(error);
    const save = el("button", ability ? "保存动作及身份假设" : "保存假设", "primary"); save.type = "submit"; form.append(save, button("取消（不保存）", () => context.onClose ? close() : home()));
    let skill, targets = [], resultRead;
    const updatePreview = () => {
      if (ability) {
        const role = skill?.role_id;
        preview.textContent = role ? `对应身份：${names[role]}。保存时优先复用同一玩家已有的有效身份假设或声明，不重复创建；没有时才添加假设。取消不保存，技能结果不参与推理。` : "请选择后预览身份假设。";
        return;
      }
      if (kindSelect.value === "alignment") preview.textContent = `将假设该玩家为${alignmentSelect.value === "good" ? "善良" : "邪恶"}阵营。仅为临时假设，不是已确认阵营，也不会据此推断身份。`;
      else preview.textContent = names[choice.value] ? `将假设该玩家为${names[choice.value]}。仅为假设，不是已确认身份。` : "请选择后预览身份假设。";
    };
    const updateKind = () => {
      if (!kindSelect) return;
      const isAlignment = kindSelect.value === "alignment";
      choice.parentElement.hidden = isAlignment;
      alignmentWrap.hidden = !isAlignment;
      updatePreview();
    };
    kindSelect?.addEventListener("change", updateKind);
    alignmentSelect?.addEventListener("change", updatePreview);
    updateKind();
    choice.addEventListener("change", () => {
      controls.replaceChildren(); targets = []; resultRead = undefined;
      skill = ability ? window.ClocktowerSkills.all.find((s) => s.id === choice.value) : undefined;
      updatePreview();
      if (!skill) return;
      controls.append(el("p", `${skill.passive ? "被动/触发记录 · " : ""}${window.SkillAvailability.check(skill, readTime()).reason} 触发条件、死亡状态和技能真实性仍需核对。`, "hint"));
      if (skill.help) controls.append(el("p", skill.help, "hint"));
      let branch;
      if (skill.noOutsiders) branch = field(controls, "获知分支", select([["pair", "两人之一为外来者"], ["none", "无外来者"]]));
      const targetBox = el("fieldset"); targetBox.append(el("legend", `${skill.targetLabel || (skill.indicated ? "说书人指示 / 获知对象（不是主动选择）" : "目标 / 有关玩家")}：${skill.min}–${skill.max} 人${skill.notSelf ? "，不能自己" : ""}`));
      if (skill.max > 0) {
        context.request.game.players.forEach((p) => {
          const check = el("input"); check.type = "checkbox"; check.value = p.id; check.name = "ability-target"; check.disabled = skill.notSelf && p.id === context.actor.id;
          const label = el("label", undefined, "target-option"); label.append(check, el("span", `${p.seat} 号 · ${p.name}`)); targetBox.append(label); targets.push(check);
        }); controls.append(targetBox);
      }
      const resultBox = el("div"); controls.append(resultBox);
      const m = skill.result; let valueControl, unobserved, extraRole;
      if (m.kind === "role") valueControl = field(resultBox, "获知 / 表象角色", roleSelect(m.roles));
      if (m.kind === "choice") valueControl = field(resultBox, "观察结果", select([["", "请选择结果"], ...window.SkillAvailability.resultOptions(skill, readTime()).map((o) => [o.value, o.label])]));
      if (m.kind === "number") { valueControl = el("input"); valueControl.type = "number"; valueControl.min = "0"; valueControl.max = String(m.max === "players" ? context.request.game.players.length : m.max); valueControl.step = "1"; field(resultBox, "观察数量", valueControl); }
      if (m.kind === "text") { valueControl = el("textarea"); valueControl.rows = 6; field(resultBox, "完整魔典信息（多行文本）", valueControl); }
      if (["role", "number", "text"].includes(m.kind)) { unobserved = el("input"); unobserved.type = "checkbox"; field(resultBox, "未观察到结果", unobserved); unobserved.addEventListener("change", () => { valueControl.disabled = unobserved.checked; }); }
      if (skill.optionalRole) { extraRole = field(resultBox, "转化后的角色（暗流涌动：小恶魔）", roleSelect(["imp"])); }
      if (m.kind === "none") resultBox.append(el("p", "无直接结果；可在备注中记录相关观察。", "hint"));
      const updateBranch = () => { const empty = branch?.value === "none"; targetBox.hidden = empty; resultBox.hidden = empty; if (empty) targets.forEach((t) => { t.checked = false; }); };
      branch?.addEventListener("change", updateBranch);
      resultRead = () => {
        if (branch?.value === "none") return { kind: "no_outsiders" };
        if (unobserved?.checked) return { kind: "unobserved" };
        if (m.kind === "none") return { kind: "no_direct_result" };
        if (m.kind === "role") return { kind: "role", role_id: valueControl.value };
        if (m.kind === "number") return { kind: "number", value: valueControl.value === "" ? null : Number(valueControl.value) };
        if (m.kind === "text") return { kind: "text", text: valueControl.value };
        return { kind: "choice", value: valueControl.value, ...(extraRole && valueControl.value === "role" ? { role_id: extraRole.value } : {}) };
      };
    });
    if (ability) {
      const refreshSkills = () => {
        const previous = choice.value;
        let time; try { time = readTime(); } catch { time = undefined; }
        const available = window.ClocktowerSkills.all.filter((s) => window.SkillAvailability.check(s, time).available);
        choice.replaceChildren();
        const placeholder = el("option", available.length ? "请选择一个技能" : "此时点没有可录入技能"); placeholder.value = ""; choice.append(placeholder);
        available.forEach((s) => { const o = el("option", `${s.name}${s.passive ? " · 被动/触发记录" : ""}`); o.value = s.id; choice.append(o); });
        choice.disabled = !available.length; save.disabled = !available.length;
        availabilityHint.textContent = time?.phase === "setup" ? "初始配置阶段不能录入技能。请将记录时点切换到夜晚或白天；身份假设仍可正常添加。" : `当前可选 ${available.length} 项；只筛选明确时间限制，不根据猜测身份、死亡或未记录的触发条件隐藏技能。`;
        unavailableList.replaceChildren();
        window.ClocktowerSkills.all.filter((s) => !available.includes(s)).forEach((s) => unavailableList.append(el("li", `${s.name}：${window.SkillAvailability.check(s, time).reason}`)));
        unavailable.hidden = unavailableList.children.length === 0;
        const retained = available.some((s) => s.id === previous);
        choice.value = retained ? previous : "";
        choice.dispatchEvent(new Event("change"));
        if (previous) availabilityHint.textContent += retained ? " 时间已变更，请重新选择目标与结果。" : " 原技能不适用于新时点，已清除未保存的选择。";
        error.textContent = "";
      };
      phase.addEventListener("change", refreshSkills); number.addEventListener("input", refreshSkills); refreshSkills();
    }
    form.addEventListener("submit", (event) => {
      event.preventDefault(); error.textContent = "";
      try {
        const time = readTime(); let request;
        if (ability) {
          if (!skill) throw new Error("请选择技能。");
          const data = { actor_id: context.actor.id, role_id: skill.role_id, ability_id: skill.id, time, targets: targets.filter((c) => c.checked).map((c) => c.value), result: resultRead(), note: note.value };
          window.ClocktowerSkills.validate(skill, data, context.request.game.players);
          request = context.editId ? window.App.editAbility(context.editId, data, context.request.request_id) : context.onClose ? window.DayVoting.perform(() => window.App.recordAbility(data, context.expected)) : window.App.recordAbility(data);
        } else if (kindSelect.value === "alignment") {
          request = context.editId ? window.App.editIdentity(context.editId, { kind: "alignment", player_id: context.actor.id, alignment: alignmentSelect.value, time }, context.request.request_id) : window.App.addAlignmentAssumption(context.actor.id, alignmentSelect.value, time);
        } else {
          if (!names[choice.value]) throw new Error("请选择身份。");
          request = context.editId ? window.App.editIdentity(context.editId, { kind: "role", player_id: context.actor.id, role_id: choice.value, time }, context.request.request_id) : window.App.addAssumption(context.actor.id, choice.value, time);
        }
        if (context.onComplete) { const complete = context.onComplete; context.onClose = undefined; close(); complete(request); return; }
        context.request = request; context.time = time; delete context.editId; delete context.editEntry; window.Roundtable.selectTime(timeIndex(time)); home();
      } catch (e) { error.textContent = e.message; error.tabIndex = -1; error.focus(); }
    });
    if (context.editEntry) {
      const entry = context.editEntry;
      if (!ability) {
        const p = entry.proposition; kindSelect.value = p.kind; choice.value = p.role_id || ""; alignmentSelect.value = p.alignment || "good"; updateKind();
      } else {
        const d = entry.data; choice.value = d.ability_id; choice.dispatchEvent(new Event("change")); note.value = d.note || "";
        controls.querySelectorAll('input[name="ability-target"]').forEach((c) => { c.checked = d.targets.includes(c.value); });
        const result = d.result || {};
        const labels = [...controls.querySelectorAll("label.action-field")];
        const find = (text) => labels.find((l) => l.querySelector("span")?.textContent === text)?.querySelector("select,input,textarea");
        if (result.kind === "no_outsiders") { const branch = find("获知分支"); if (branch) { branch.value = "none"; branch.dispatchEvent(new Event("change")); } }
        if (result.kind === "role") { const c = find("获知 / 表象角色"); if (c) c.value = result.role_id; }
        if (result.kind === "choice") { const c = find("观察结果"); if (c) c.value = result.value; const role = find("转化后的角色（暗流涌动：小恶魔）"); if (role) role.value = result.role_id || ""; }
        if (result.kind === "number") { const c = find("观察数量"); if (c) c.value = result.value; }
        if (result.kind === "text") { const c = find("完整魔典信息（多行文本）"); if (c) c.value = result.text; }
        if (result.kind === "unobserved") { const c = find("未观察到结果"); if (c) { c.checked = true; c.dispatchEvent(new Event("change")); } }
      }
      save.textContent = "保存修改";
    }
    (kindSelect || choice).focus();
  }
  function open(request, actor, selectedTime) {
    init(); context = { request: structuredClone(request), actor, time: timeFrom(selectedTime) }; opener = actor.id; home(false); dialog.showModal(); body.querySelector("button")?.focus();
  }
  function openAbility(request, actor, time, { expected, onComplete, onClose } = {}) {
    init(); close(); context = { request: structuredClone(request), actor, time: structuredClone(time), expected, onComplete, onClose }; opener = actor.id;
    title(); dialog.showModal(); editor(true);
  }
   function edit(request, entry) {
     init(); close();
     const ability = entry.type === "botc:ability_observation", p = ability ? entry.data : entry.proposition;
     const actor = request.game.players.find((v) => v.id === (ability ? p.actor_id : p.player_id));
     if (!actor) return;
     context = { request: structuredClone(request), actor, time: structuredClone(p.time), editId: entry.id, editEntry: structuredClone(entry) }; opener = actor.id;
     title(); dialog.showModal(); editor(ability);
   }
   return { open, openAbility, edit, close, timeIndex };
})();
