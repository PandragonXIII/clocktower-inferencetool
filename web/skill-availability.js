"use strict";

// 录入体验层的时间限制，不是 BOTC 求解规则；不据此确认身份或观察真实性。
window.SkillAvailability = (() => {
  const schedules = {
    washerwoman: "first_night", librarian: "first_night", investigator: "first_night", chef: "first_night",
    empath: "night", fortune_teller: "night", undertaker: "later_night", monk: "later_night",
    ravenkeeper: "night", virgin: "day", slayer: "day", soldier: "night",
    mayor: "any", butler: "night", drunk: "any", recluse: "any", saint: "day",
    poisoner: "night", spy: "night", scarlet_woman: "any", baron: "configuration", imp: "later_night"
  };
  const descriptions = {
    first_night: "仅第 1 夜可录入此技能信息。",
    night: "仅夜晚可录入。",
    later_night: "第 2 夜起可录入，首夜不可发动。",
    day: "仅白天可录入。",
    any: "可在白天或夜晚记录被动效果；是否实际触发需另行核对。",
    configuration: "这是配置效果，不是可发动的技能；请使用身份假设或备注记录。"
  };
  function check(skill, time) {
    if (!skill) return { available: false, reason: "请选择技能。" };
    if (time?.phase === "setup") return { available: false, reason: "初始配置阶段不能发动或录入技能，请先选择白天或夜晚。" };
    if (!["night", "day"].includes(time?.phase) || !Number.isInteger(time.number) || time.number < 1 || time.number > 99) return { available: false, reason: "请选择 1–99 的有效白天或夜晚。" };
    const schedule = schedules[skill.role_id];
    const available = schedule === "any" || schedule === time.phase || (schedule === "first_night" && time.phase === "night" && time.number === 1) || (schedule === "later_night" && time.phase === "night" && time.number >= 2);
    return { available, reason: descriptions[schedule] || "尚未配置此技能的可用时间。" };
  }
  function resultOptions(skill, time) {
    const options = skill?.result?.options || [];
    if (skill?.role_id !== "mayor") return options;
    return options.filter((o) => o.value === "unobserved" || (time?.phase === "day" ? o.value === "three_alive_no_execution_win" : time?.phase === "night" && o.value === "suspected_redirect"));
  }
  function assert(skill, data) {
    const state = check(skill, data.time);
    if (!state.available) throw new Error(state.reason);
    if (skill.result.kind === "choice" && data.result?.kind === "choice" && !resultOptions(skill, data.time).some((o) => o.value === data.result.value)) throw new Error("该结果不适用于当前时段，请重新选择。");
  }
  return { check, resultOptions, assert };
})();
