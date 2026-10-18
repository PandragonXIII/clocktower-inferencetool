"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

function app() {
  const elements = new Map();
  const element = () => ({ value: "", dataset: {}, append() {}, replaceChildren() {}, setAttribute() {}, addEventListener() {} });
  const document = { createElement: element, getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); } };
  const window = { Setup: { init() {} }, ClocktowerRoles: { names: { chef: "厨师" } },
    PlayerActions: { timeIndex(t) { return t.phase === "setup" ? 0 : t.number * 2 - (t.phase === "night" ? 1 : 0); } },
    DayVoting: { accepts: () => true, current: (r) => r.facts.find((f) => f.type === "botc:day_vote"), defaultResult: () => ({ default_player_id: null }) } };
  const context = vm.createContext({ window, document, structuredClone, console, AbortController, setTimeout, clearTimeout, crypto: require("node:crypto").webcrypto });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../app.js"), "utf8"), context);
  vm.runInContext(`render = () => {}; currentRequest = {request_id:'original',game:{id:'game',revision:0,time:{phase:'day',number:1},players:[]},facts:[],assumptions:[],queries:[]};`, context);
  return { context, window, state: () => JSON.parse(vm.runInContext("JSON.stringify(currentRequest)", context)) };
}

test("probability toggle changes the actual outgoing snapshot and revision", () => {
  const a = app();
  a.window.App.setProbabilityMode(true);
  assert.equal(a.state().options.probability_mode, true);
  assert.equal(a.state().game.revision, 1);
  assert.notEqual(a.state().request_id, "original");
  a.window.App.setProbabilityMode(false);
  assert.equal(a.state().options.probability_mode, false);
});

test("transport timeout includes independent budgets and construction/network grace", () => {
  const { context } = app();
  const timeout = (options) => vm.runInContext(`requestTimeoutMs(${JSON.stringify({ options })})`, context);
  assert.equal(timeout({ total_timeout_ms: 60000, timeout_ms: 10000, probability_mode: true, probability_timeout_ms: 30000 }), 120000);
  assert.equal(timeout({ total_timeout_ms: 60000, probability_mode: false, probability_timeout_ms: 30000 }), 90000);
  assert.equal(timeout({}), 38000);
  assert.equal(timeout({ probability_mode: true }), 158000);
  assert.equal(timeout({ total_timeout_ms: 60000, probability_mode: true, probability_timeout_ms: 300000 }), 390000);
  assert.equal(timeout({ total_timeout_ms: 60000, probability_mode: true, probability_timeout_ms: 300001 }), 210000);
  assert.equal(timeout({ total_timeout_ms: -1, probability_mode: true, probability_timeout_ms: "30000" }), 158000);
});

test("global assumption uses enabled rather than legacy requested_enabled", () => {
  const a = app();
  a.window.App.addGlobalAssumption("chef", { phase: "setup" }, "original");
  const id = a.state().facts[0].id;
  assert.equal(a.state().facts[0].enabled, true);
  a.window.App.setGlobalAssumptionEnabled(id, false);
  assert.equal(a.state().facts[0].enabled, false);
  assert.equal(a.state().facts[0].data.requested_enabled, false);
});

test("settling a voting draft enables the actual record", () => {
  const a = app();
  vm.runInContext(`currentRequest.facts.push({id:'vote',type:'botc:day_vote',enabled:false,data:{stage:'voting',time:{phase:'day',number:1}}});`, a.context);
  a.window.App.settleVoting(0, null);
  assert.equal(a.state().facts[0].enabled, true);
  assert.equal(a.state().facts[0].data.stage, "settled");
});
