"use strict";

// 仅录入元数据，不是规则引擎；所有结果都保留为停用的观察记录。
window.ClocktowerSkills = (() => {
  const names = window.ClocktowerRoles.names;
  const group = (name) => window.ClocktowerRoles.groups.find((g) => g.name === name).roles.map(([id]) => id);
  const all = Object.keys(names);
  const choices = (...items) => items.map(([value, label]) => ({ value, label }));
  const unknown = ["unobserved", "未观察到结果"];
  const death = choices(["died", "死亡"], ["survived", "未死亡"], unknown);
  const roleResult = (ids = all) => ({ kind: "role", roles: ids });
  const selectResult = (options) => ({ kind: "choice", options });
  const skills = [];
  function add(role, title, timing, min, max, result, extra = {}) {
    skills.push({ id: `${role}:record`, role_id: role, name: `${title}（${names[role]}）`, timing, min, max, result, ...extra });
  }
  add("washerwoman", "获知两人中的镇民", "首夜", 2, 2, roleResult(group("镇民")), { indicated: true });
  add("librarian", "获知外来者", "首夜", 2, 2, roleResult(group("外来者")), { indicated: true, noOutsiders: true });
  add("investigator", "获知两人中的爪牙", "首夜", 2, 2, roleResult(group("爪牙")), { indicated: true });
  add("chef", "获知邪恶邻对数量", "首夜", 0, 0, { kind: "number", max: "players" });
  add("empath", "获知存活邻座邪恶数量", "每夜", 0, 0, { kind: "number", max: 2 });
  add("fortune_teller", "查验两人", "每夜", 2, 2, selectResult(choices(["yes", "是"], ["no", "否"], unknown)));
  add("undertaker", "获知被处决者身份", "每夜（首夜除外）", 1, 1, roleResult(), { targetLabel: "被处决玩家（自行核对处决记录）" });
  add("monk", "保护玩家", "每夜（首夜除外）", 1, 1, { kind: "none" }, { notSelf: true });
  add("ravenkeeper", "死亡后获知身份", "夜间死亡触发", 1, 1, roleResult(), { passive: true });
  add("virgin", "首次被提名记录", "白天首次被提名触发", 1, 1, selectResult(choices(["executed", "提名者被处决"], ["not_executed", "提名者未被处决"], unknown)), { passive: true, targetLabel: "提名者" });
  add("slayer", "公开射击", "白天（通常每局一次）", 1, 1, selectResult(death));
  add("soldier", "免疫相关观察", "被动", 0, 0, selectResult(choices(unknown, ["survived", "观察未死亡"], ["died", "观察死亡（不证明是否免疫）"])), { passive: true });
  add("mayor", "胜利或转移击杀记录", "被动 / 三人无处决或夜间触发", 0, 15, selectResult(choices(["three_alive_no_execution_win", "三人无处决胜利"], ["suspected_redirect", "疑似转移击杀"], unknown)), { passive: true });
  add("butler", "选择主人", "每夜", 1, 1, { kind: "none" }, { notSelf: true });
  add("drunk", "记录表象镇民身份", "被动", 0, 0, roleResult(group("镇民")), { passive: true, help: "表象身份不是该玩家的真实身份；仅假设其为酒鬼。" });
  add("recluse", "登记结果记录", "被动 / 被其他技能查验触发", 0, 0, selectResult(choices(["role", "登记为某角色（备注填写）"], ["alignment", "登记为某阵营（备注填写）"], unknown)), { passive: true });
  add("saint", "处决后胜负记录", "被动 / 被处决触发", 0, 0, selectResult(choices(["good_lost", "善良失败"], ["good_won", "善良胜利"], ["ongoing", "对局继续"], unknown)), { passive: true });
  add("poisoner", "投毒", "每夜", 1, 1, { kind: "none" });
  add("spy", "查看魔典记录", "每夜", 0, 15, { kind: "text" }, { help: "请用多行文本保留完整魔典信息；有关玩家可多选但非必选。" });
  add("scarlet_woman", "转化记录", "被动 / 恶魔死亡触发", 0, 0, selectResult(choices(["occurred", "发生转化"], ["not_occurred", "未发生转化"], ["role", "转化为某角色（下方选择）"], unknown)), { passive: true, optionalRole: true });
  add("baron", "外来者配置记录", "初始配置", 0, 0, { kind: "number", max: "players" }, { passive: true });
  add("imp", "夜间击杀", "每夜（首夜除外）", 1, 1, selectResult(death), { help: "可选择自己；观察到死亡不等于确认死因或真实身份。" });

  function validate(skill, data, players) {
    if (!skill) throw new Error("请选择技能。");
    window.SkillAvailability.assert(skill, data);
    const targets = data.targets;
    if (!Array.isArray(targets) || new Set(targets).size !== targets.length || targets.some((id) => !players.some((p) => p.id === id))) throw new Error("目标必须是本局玩家且不能重复。");
    const empty = skill.noOutsiders && data.result?.kind === "no_outsiders";
    const min = empty ? 0 : skill.min, max = empty ? 0 : skill.max;
    if (targets.length < min || targets.length > max) throw new Error(`此技能需要 ${min === max ? min : `${min}–${max}`} 名目标，当前 ${targets.length} 名。`);
    if (skill.notSelf && targets.includes(data.actor_id)) throw new Error("此技能目标不能是自己。");
    const r = data.result || {}, meta = skill.result;
    if (empty) return;
    if (r.kind === "unobserved" && meta.kind !== "none") return;
    if (meta.kind === "role" && (r.kind !== "role" || !meta.roles.includes(r.role_id))) throw new Error("请选择对应类别的结果角色。");
    if (meta.kind === "choice" && (r.kind !== "choice" || !meta.options.some((o) => o.value === r.value))) throw new Error("请选择技能结果。");
    if (skill.optionalRole && r.value === "role" && r.role_id !== "imp") throw new Error("暗流涌动中的红唇女郎转化为小恶魔。");
    if (meta.kind === "number" && (r.kind !== "number" || !Number.isInteger(r.value) || r.value < 0 || r.value > (meta.max === "players" ? players.length : meta.max))) throw new Error("结果数量超出范围。");
    if (meta.kind === "text" && (r.kind !== "text" || !r.text?.trim())) throw new Error("请填写完整观察信息，或选择未观察到结果。");
    if (meta.kind === "none" && r.kind !== "no_direct_result") throw new Error("此技能不提供直接结果。");
  }
  return { all: skills, validate };
})();
