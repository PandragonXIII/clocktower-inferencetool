"use strict";

// 暗流涌动的显示名称与分组。分组不用于确认阵营；defaultAlignments 仅把
// 角色在其分组内的固有阵营作为展示性的“不确定默认阵营”，供圆桌斜纹提示，
// 不写入 confirmed，也不生成任何隐式 alignment 约束。
window.ClocktowerRoles = (() => {
  const groups = [
    { name: "镇民", roles: [["washerwoman", "洗衣妇"], ["librarian", "图书管理员"], ["investigator", "调查员"], ["chef", "厨师"], ["empath", "共情者"], ["fortune_teller", "占卜师"], ["undertaker", "送葬者"], ["monk", "僧侣"], ["ravenkeeper", "守鸦人"], ["virgin", "贞洁者"], ["slayer", "猎手"], ["soldier", "士兵"], ["mayor", "市长"]] },
    { name: "外来者", roles: [["butler", "管家"], ["drunk", "酒鬼"], ["recluse", "隐士"], ["saint", "圣徒"]] },
    { name: "爪牙", roles: [["poisoner", "投毒者"], ["spy", "间谍"], ["scarlet_woman", "红唇女郎"], ["baron", "男爵"]] },
    { name: "恶魔", roles: [["imp", "小恶魔"]] }
  ];
  const evilGroups = new Set(["爪牙", "恶魔"]);
  const defaultAlignments = Object.fromEntries(groups.flatMap((group) => group.roles.map(([id]) => [id, evilGroups.has(group.name) ? "evil" : "good"])));
  return { groups, names: Object.fromEntries(groups.flatMap((group) => group.roles)), defaultAlignments };
})();
