const { test } = require("node:test");
const assert = require("node:assert/strict");
global.window = {};
require("../night-deaths.js");
const { deadAt, deathsAt } = window.NightDeaths;
const at = (phase, number = 1) => ({ phase, number });
const night = { type: "botc:night_deaths", status: "confirmed", enabled: false, data: { time: at("night"), result: "deaths", player_ids: ["p1"] } };
const execution = (id, number = 1) => ({ type: "botc:day_vote", status: "confirmed", enabled: false, data: { time: at("day", number), stage: "settled", execution: { player_id: id } } });

test("death stamps occur only at the recorded boundary while death persists", () => {
  const facts = [execution("p2"), night];
  assert.equal(deathsAt(facts, { phase: "setup" }).size, 0);
  assert.deepEqual([...deathsAt(facts, at("night"))], [["p1", "night"]]);
  assert.deepEqual([...deathsAt(facts, at("day"))], [["p2", "execution"]]);
  assert.equal(deathsAt(facts, at("night", 2)).size, 0);
  assert.deepEqual([...deadAt(facts, at("night", 2))].sort(), ["p1", "p2"]);
});

test("executing a previously dead player does not create another death stamp", () => {
  assert.equal(deathsAt([execution("p1"), night], at("day")).size, 0);
  assert.equal(deathsAt([execution("p2", 2), execution("p2")], at("day", 2)).size, 0);
});

test("draft votes, unconfirmed observations and skill results are not deaths", () => {
  const draft = execution("p2"); draft.data.stage = "voting";
  const facts = [draft, { ...night, status: "reported" }, { type: "botc:ability_observation", status: "confirmed", data: { time: at("day"), targets: ["p3"], result: { value: "died" } } }];
  assert.equal(deathsAt(facts, at("night")).size, 0);
  assert.equal(deathsAt(facts, at("day")).size, 0);
  assert.equal(deadAt(facts, at("day")).size, 0);
});
