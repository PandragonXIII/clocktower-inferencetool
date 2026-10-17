const { test } = require("node:test");
const assert = require("node:assert/strict");
global.window = {};
require("../roles.js");
require("../skills.js");
require("../skill-availability.js");
const skills = window.ClocktowerSkills;
const availability = window.SkillAvailability;
const skill = (role) => skills.all.find((s) => s.role_id === role);
const at = (phase, number = 1) => phase === "setup" ? { phase } : { phase, number };

test("setup and invalid times never permit skills", () => {
  for (const s of skills.all) for (const t of [at("setup"), at("night", 0), at("day", 100), undefined]) assert.equal(availability.check(s, t).available, false);
});
test("first night and later nights have distinct skill sets", () => {
  for (const role of ["washerwoman", "librarian", "investigator", "chef"]) {
    assert.equal(availability.check(skill(role), at("night")).available, true);
    assert.equal(availability.check(skill(role), at("night", 2)).available, false);
  }
  for (const role of ["imp", "monk", "undertaker"]) {
    assert.equal(availability.check(skill(role), at("night")).available, false);
    assert.equal(availability.check(skill(role), at("night", 2)).available, true);
    assert.equal(availability.check(skill(role), at("day", 2)).available, false);
  }
});
test("day actions and passive observations have separate treatment", () => {
  assert.equal(availability.check(skill("slayer"), at("day")).available, true);
  assert.equal(availability.check(skill("slayer"), at("night")).available, false);
  assert.equal(availability.check(skill("recluse"), at("day")).available, true);
  assert.equal(availability.check(skill("recluse"), at("night")).available, true);
  assert.equal(availability.check(skill("baron"), at("day")).available, false);
});
test("mayor results and saving are constrained independently of UI", () => {
  const mayor = skill("mayor");
  assert.deepEqual(availability.resultOptions(mayor, at("day")).map((v) => v.value), ["three_alive_no_execution_win", "unobserved"]);
  assert.throws(() => skills.validate(mayor, { time: at("day"), targets: [], result: { kind: "choice", value: "suspected_redirect" } }, []), /不适用于/);
  assert.throws(() => skills.validate(skill("imp"), { time: at("night"), targets: [], result: { kind: "unobserved" } }, []), /首夜/);
});
