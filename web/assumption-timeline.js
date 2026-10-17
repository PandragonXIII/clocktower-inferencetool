"use strict";

// 只计算展示候选，不改变协议命题的单时点含义。
window.AssumptionTimeline = (() => {
  const rank = (t) => t?.phase === "setup" ? 0 : ["day", "night"].includes(t?.phase) && Number.isInteger(t.number) ? t.number * 2 - (t.phase === "night" ? 1 : 0) : -1;
  function transitions(request, playerId) {
    const assumptions = Array.isArray(request?.assumptions) ? request.assumptions : [];
    return (Array.isArray(request?.facts) ? request.facts : []).filter((f) => {
      const d = f?.data;
      const sourceActive = assumptions.some((a) => a.enabled === true && a.id === f.extensions?.["ui:assumption_id"]) || (request.facts || []).some((v) => v.enabled === true && v.type === "role" && v.id === f.extensions?.["ui:identity_fact_id"]);
      return f.type === "botc:ability_observation" && d?.actor_id === playerId && d.role_id === "scarlet_woman" && (d.result?.value === "occurred" || (d.result?.value === "role" && d.result.role_id === "imp")) && rank(d.time) >= 0 && sourceActive;
    });
  }
  function candidates(request, playerId, time) {
    const active = (Array.isArray(request?.assumptions) ? request.assumptions : []).filter((a) => a.enabled === true && a.proposition?.player_id === playerId && ["role", "alignment"].includes(a.proposition.kind));
    const changes = transitions(request, playerId).filter((f) => rank(f.data.time) <= rank(time)).sort((a, b) => rank(b.data.time) - rank(a.data.time));
    if (!changes.length) return active;
    const change = changes[0];
    return [...active.filter((a) => a.proposition.kind !== "role"), { id: change.extensions["ui:assumption_id"], enabled: true, proposition: { kind: "role", player_id: playerId, role_id: "imp", time }, extensions: { "ui:timeline_display": true, "ui:observation_id": change.id } }];
  }
  function reportedCandidates(request, playerId, time) {
    const changed = transitions(request, playerId).some((f) => rank(f.data.time) <= rank(time));
    return (Array.isArray(request?.facts) ? request.facts : []).filter((f) => {
      const p = f?.proposition;
      if (f.enabled !== true || f.status !== "reported" || p?.player_id !== playerId || f.type !== p.kind) return false;
      // 初始身份是基础声明，跨时点展示；其他观察/声明仍保留原时点语义。
      const initialRole = p.kind === "role" && p.time?.phase === "setup";
      if (changed && initialRole) return false;
      return initialRole || rank(p.time) === rank(time);
    });
  }
  return { candidates, transitions, reportedCandidates };
})();
