const { test } = require("node:test");
const assert = require("node:assert/strict");
global.window = {};
require("../assumption-timeline.js");
const setup = { phase: "setup" }, night = { phase: "night", number: 2 }, day = { phase: "day", number: 2 };
const base = () => ({ assumptions: [{ id: "a", enabled: true, proposition: { kind: "role", player_id: "p1", role_id: "scarlet_woman", time: day }, extensions: { "ui:observation_id": "f" } }, { id: "b", enabled: true, proposition: { kind: "alignment", player_id: "p1", alignment: "evil", time: day } }], facts: [{ id: "f", type: "botc:ability_observation", extensions: { "ui:assumption_id": "a" }, data: { actor_id: "p1", role_id: "scarlet_woman", time: night, result: { kind: "choice", value: "occurred" } } }] });
const roles = (r, t) => window.AssumptionTimeline.candidates(r, "p1", t).filter(a => a.proposition.kind === "role").map(a => a.proposition.role_id);
test("base assumptions show before and after their recording time", () => {
  const r = base(); r.facts = [];
  assert.deepEqual(roles(r, setup), ["scarlet_woman"]);
  assert.deepEqual(roles(r, day), ["scarlet_woman"]);
  assert.equal(window.AssumptionTimeline.candidates(r, "p1", setup).some(a => a.proposition.alignment === "evil"), true);
});
test("confirmed transition changes the boundary and later only", () => {
  const r = base();
  assert.deepEqual(roles(r, setup), ["scarlet_woman"]);
  assert.deepEqual(roles(r, night), ["imp"]);
  assert.deepEqual(roles(r, day), ["imp"]);
  assert.equal(r.assumptions[0].proposition.role_id, "scarlet_woman");
});
test("unobserved, untriggered and disabled transitions do not transform", () => {
  for (const value of ["unobserved", "not_occurred"]) { const r = base(); r.facts[0].data.result.value = value; assert.deepEqual(roles(r, day), ["scarlet_woman"]); }
  const r = base(); r.assumptions[0].enabled = false;
  assert.deepEqual(roles(r, day), []);
  r.assumptions[0].enabled = true; r.facts = [];
  assert.deepEqual(roles(r, day), ["scarlet_woman"]);
});
test("opening reported identity persists without becoming an assumption", () => {
  const r = { assumptions: [], facts: [{ id: "self", type: "role", status: "reported", enabled: true, proposition: { kind: "role", player_id: "p1", role_id: "empath", time: setup } }] };
  for (const time of [setup, { phase: "night", number: 1 }, day]) assert.equal(window.AssumptionTimeline.reportedCandidates(r, "p1", time)[0].proposition.role_id, "empath");
  assert.deepEqual(window.AssumptionTimeline.candidates(r, "p1", day), []);
  assert.equal(r.facts[0].status, "reported");
  r.facts[0].enabled = false;
  assert.deepEqual(window.AssumptionTimeline.reportedCandidates(r, "p1", day), []);
});
test("opening identity reused by transformation is hidden only after boundary", () => {
  const r = base(); r.assumptions = [];
  r.facts.push({ id: "self", type: "role", status: "reported", enabled: true, proposition: { kind: "role", player_id: "p1", role_id: "scarlet_woman", time: setup } });
  r.facts[0].extensions = { "ui:identity_fact_id": "self" };
  assert.equal(window.AssumptionTimeline.reportedCandidates(r, "p1", setup).length, 1);
  assert.equal(window.AssumptionTimeline.reportedCandidates(r, "p1", night).length, 0);
  assert.deepEqual(roles(r, night), ["imp"]);
});
