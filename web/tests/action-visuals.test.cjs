const { test } = require("node:test");
const assert = require("node:assert/strict");
global.window = {};
require("../roles.js");
require("../skills.js");
require("../action-visuals.js");
const { describe, observations } = window.ActionVisuals;
test("curved swallowtail ribbons form finite closed outlines including short paths", () => {
  for (const end of [{x:200,y:80},{x:1,y:1},{x:0,y:0}]) {
    const path = window.ActionVisuals.ribbon({x:0,y:0},{x:30,y:50},{x:100,y:90},end,true,true);
    assert.match(path, /^M.* Z$/);
    assert.doesNotMatch(path, /NaN|Infinity/);
  }
});
test("spy observations have no visual targets while targeted skills retain theirs", () => {
  const players = [{ id: "p1" }, { id: "p2" }];
  assert.deepEqual(window.ActionVisuals.targetsFor({ ability_id: "spy:record", targets: ["p1", "p2"] }, players), []);
  assert.deepEqual(window.ActionVisuals.targetsFor({ role_id: "monk", targets: ["p2", "p2", "missing"] }, players), ["p2"]);
});
const data = (role_id, result) => ({ role_id, ability_id: `${role_id}:record`, result });

test("identity observations use concise predicates for the connected targets", () => {
  for (const role of ["washerwoman", "librarian", "investigator"]) assert.equal(describe(data(role, { kind: "role", role_id: "soldier" })), "有士兵");
  assert.equal(describe(data("undertaker", { kind: "role", role_id: "imp" })), "是小恶魔");
  assert.equal(describe(data("librarian", { kind: "no_outsiders" })), "无外来者");
});

test("numbers, yes/no, death and non-result actions have contextual wording", () => {
  assert.equal(describe(data("empath", { kind: "number", value: 2 })), "邻座 2 名邪恶");
  assert.match(describe(data("chef", { kind: "number", value: 1 })), /1 对邪恶邻座/);
  assert.equal(describe(data("fortune_teller", { kind: "choice", value: "no" })), "没有恶魔");
  assert.equal(describe(data("fortune_teller", { kind: "choice", value: "yes" })), "有恶魔");
  assert.equal(describe(data("monk", { kind: "no_direct_result" })), "保护");
  assert.equal(describe(data("slayer", { kind: "choice", value: "survived" })), "未死亡");
  assert.equal(describe(data("drunk", { kind: "role", role_id: "soldier" })), "表象：士兵");
  assert.equal(describe(data("soldier", { kind: "choice", value: "died" })), "死亡（免疫未确认）");
  assert.equal(describe(data("scarlet_woman", { kind: "choice", value: "role", role_id: "imp" })), "转化为小恶魔");
});

test("only the viewed phase and existing actors are visualized, including disabled observations", () => {
  const f = { type: "botc:ability_observation", enabled: false, data: { actor_id: "p1", time: { phase: "night", number: 1 } } };
  const facts = [f, { ...f, data: { ...f.data, actor_id: "missing" } }, { ...f, type: "role" }];
  assert.deepEqual(observations(facts, 1, [{ id: "p1" }]), [f]);
  assert.deepEqual(observations(facts, 2, [{ id: "p1" }]), []);
});
