const { test } = require("node:test");
const assert = require("node:assert/strict");
global.window = {};
require("../roles.js");
require("../probability-view.js");

test("probability candidates sort by likelihood and preserve alignment and values", () => {
  const items = window.ProbabilityView.entries({ probabilities: { monk: .2, imp: .6, soldier: .2 } });
  assert.equal(items[0].id, "imp");
  assert.equal(items[0].alignment, "evil");
  assert.equal(items[0].value, .6);
  assert.ok(items.slice(1).every((item) => item.alignment === "good" && item.color !== items[0].color));
});

test("missing, zero and malformed probabilities are not shown as candidates", () => {
  assert.deepEqual(window.ProbabilityView.entries(), []);
  assert.deepEqual(window.ProbabilityView.entries({ probabilities: { imp: 0, monk: -1, soldier: "0.8", chef: NaN, spy: 2, missing: .5 } }), []);
});
