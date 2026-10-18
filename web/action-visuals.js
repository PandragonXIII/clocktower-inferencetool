"use strict";

window.ActionVisuals = (() => {
  const index = (t) => t?.phase === "setup" ? 0 : ["night", "day"].includes(t?.phase) && Number.isInteger(t.number) && t.number > 0 && t.number <= 99 ? t.number * 2 - (t.phase === "night" ? 1 : 0) : -1;
  const colors = ["#68509a", "#267f83", "#a56625", "#a84670", "#436db0", "#587b35"];
  function describe(data) {
    const skill = window.ClocktowerSkills.all.find((s) => s.id === data.ability_id);
    const role = data.role_id || skill?.role_id;
    if (role === "spy") return "查看了魔典";
    const r = data.result || {}, roleName = window.ClocktowerRoles.names[r.role_id] || r.role_id || "未知身份";
    const action = { monk: "保护", poisoner: "投毒", butler: "选择主人", slayer: "射击", imp: "击杀", spy: "查看魔典" }[role];
    let result = "";
    if (r.kind === "role") result = ["washerwoman", "librarian", "investigator"].includes(role) ? `有${roleName}` : role === "drunk" ? `表象：${roleName}` : `是${roleName}`;
    else if (r.kind === "number") result = role === "chef" ? `${r.value} 对邪恶邻座` : role === "empath" ? `邻座 ${r.value} 名邪恶` : role === "baron" ? `${r.value} 名外来者` : `数量 ${r.value}`;
    else if (r.kind === "no_outsiders") result = "无外来者";
    else if (r.kind === "text") result = r.text || "";
    else if (r.kind === "unobserved") result = "未观察到结果";
    else if (r.kind === "choice") {
      if (role === "fortune_teller" && ["yes", "no"].includes(r.value)) result = r.value === "yes" ? "有恶魔" : "没有恶魔";
      else if (["slayer", "imp"].includes(role) && ["died", "survived"].includes(r.value)) result = r.value === "died" ? "死亡" : "未死亡";
      else if (role === "scarlet_woman" && r.value === "role") result = `转化为${roleName}`;
      else {
        const compact = {
          virgin: { executed: "提名者被处决", not_executed: "提名者未被处决" },
          soldier: { survived: "未死亡", died: "死亡（免疫未确认）" },
          mayor: { three_alive_no_execution_win: "三人无处决获胜", suspected_redirect: "疑似转移击杀" },
          recluse: { role: "登记为角色（见备注）", alignment: "登记为阵营（见备注）" },
          scarlet_woman: { occurred: "已转化", not_occurred: "未转化" }
        };
        result = compact[role]?.[r.value] || skill?.result.options?.find((o) => o.value === r.value)?.label || "未识别结果";
      }
    }
    return result || action || skill?.name || "技能观察";
  }
  function observations(facts, time, players) {
    const ids = new Set(players.map((p) => p.id));
    return (Array.isArray(facts) ? facts : []).filter((f) => f?.type === "botc:ability_observation" && index(f.data?.time) === time && ids.has(f.data?.actor_id));
  }
  function targetsFor(data, players) {
    const role = data.role_id || window.ClocktowerSkills.all.find((s) => s.id === data.ability_id)?.role_id;
    if (role === "spy") return [];
    const ids = new Set(players.map((p) => p.id));
    return [...new Set(Array.isArray(data.targets) ? data.targets : [])].filter((id) => ids.has(id));
  }
  // 卡片矩形边缘裁切，避免箭头落在卡片文字上。
  function edge(point, toward, padding = 5) {
    const dx = toward.x - point.x, dy = toward.y - point.y;
    const scale = Math.min((66 + padding) / (Math.abs(dx) || .001), (61 + padding) / (Math.abs(dy) || .001));
    return { x: point.x + dx * scale, y: point.y + dy * scale };
  }
  // 沿三次贝塞尔曲线构造宽带轮廓：尾部内凹，头部展开为尖箭头。
  function ribbon(start, c1, c2, end, head = true, tail = false) {
    const point = (t) => {
      const u = 1 - t;
      return { x: u ** 3 * start.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t ** 3 * end.x, y: u ** 3 * start.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t ** 3 * end.y };
    };
    const samples = Array.from({ length: 41 }, (_, i) => point(i / 40));
    let length = 0;
    for (let i = 1; i < samples.length; i++) length += Math.hypot(samples[i].x - samples[i - 1].x, samples[i].y - samples[i - 1].y);
    const headT = head ? Math.max(.4, 1 - Math.min(20, length * .25) / Math.max(length, 1)) : 1;
    const left = [], right = [];
    const offset = (t, width) => {
      const p = point(t), a = point(Math.max(0, t - .001)), b = point(Math.min(1, t + .001));
      const norm = Math.hypot(b.x - a.x, b.y - a.y) || 1;
      return [{ x: p.x - (b.y - a.y) / norm * width, y: p.y + (b.x - a.x) / norm * width }, { x: p.x + (b.y - a.y) / norm * width, y: p.y - (b.x - a.x) / norm * width }];
    };
    for (let i = 0; i <= 32; i++) {
      const [l, r] = offset(headT * i / 32, tail ? 5 - i / 32 * 1.5 : 3.5); left.push(l); right.push(r);
    }
    const corners = head ? [...offset(headT, 10).slice(0, 1), end, offset(headT, 10)[1]] : [];
    const outline = [...left, ...corners, ...right.reverse(), ...(tail ? [point(Math.min(.2, 10 / Math.max(length, 1))) ] : [])];
    return `M${outline.map((p) => `${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(" L")} Z`;
  }
  function render(board, facts, time, players, size, radius) {
    const items = observations(facts, time, players);
    if (!items.length) return;
    const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg");
    svg.classList.add("action-arrows"); svg.setAttribute("viewBox", `0 0 ${size} ${size}`); svg.setAttribute("aria-hidden", "true");
    const positions = new Map(players.map((p, i) => { const a = i * Math.PI * 2 / players.length - Math.PI / 2; return [p.id, { x: size / 2 + radius * Math.cos(a), y: size / 2 + radius * Math.sin(a) }]; }));
    items.forEach((f, i) => {
      const d = f.data, source = positions.get(d.actor_id), color = colors[i % colors.length];
      const targets = targetsFor(d, players);
      const group = document.createElementNS(ns, "g"); group.dataset.actor = d.actor_id; svg.append(group);
      const band = (start, c1, c2, end, head, tail) => { const p = document.createElementNS(ns, "path"); p.classList.add("action-ribbon"); if (head) p.classList.add("action-arrow-head"); p.setAttribute("d", ribbon(start, c1, c2, end, head, tail)); p.setAttribute("fill", color); p.setAttribute("stroke", color); group.append(p); };
      const inward = { x: (size / 2 - source.x) / radius, y: (size / 2 - source.y) / radius };
      const lane = items.slice(0, i).filter((v) => v.data.actor_id === d.actor_id && Boolean(targetsFor(v.data, players).length) === Boolean(targets.length)).length;
      const hub = { x: source.x + inward.x * 112, y: source.y + inward.y * 112 };
      if (targets.length) {
        const start = edge(source, hub);
        const tangent = { x: inward.x * 28 - inward.y * 12, y: inward.y * 28 + inward.x * 12 };
        if (targets.length > 1) band(start, { x: start.x + inward.x * 16, y: start.y + inward.y * 16 }, { x: hub.x - tangent.x * .4, y: hub.y - tangent.y * .4 }, hub, false, true);
        targets.forEach((id) => {
          const target = positions.get(id);
          if (id === d.actor_id) {
            const end = edge(source, { x: source.x - inward.y * 120, y: source.y + inward.x * 120 });
            const from = targets.length > 1 ? hub : start;
            band(from, { x: hub.x + inward.x * 75, y: hub.y + inward.y * 75 }, { x: end.x - inward.y * 95 + inward.x * 70, y: end.y + inward.x * 95 + inward.y * 70 }, end, true, targets.length === 1);
          } else {
            const end = edge(target, hub, 9);
            const from = targets.length > 1 ? hub : start;
            const dx = end.x - from.x, dy = end.y - from.y, distance = Math.hypot(dx, dy) || 1;
            const bend = Math.min(65, distance * .2) * (i % 2 ? -1 : 1);
            band(from, { x: hub.x + tangent.x, y: hub.y + tangent.y }, { x: from.x + dx * .7 - dy / distance * bend, y: from.y + dy * .7 + dx / distance * bend }, end, true, targets.length === 1);
          }
        });
      }
      const label = document.createElement("div"); label.className = "action-label"; label.dataset.actor = d.actor_id; label.style.setProperty("--action-color", color);
      const who = players.find((p) => p.id === d.actor_id), targetNames = targets.map((id) => `${players.find((p) => p.id === id).seat}号`).join("、");
      label.textContent = describe(d);
      const skill = window.ClocktowerSkills.all.find((s) => s.id === d.ability_id);
      const roleName = window.ClocktowerRoles.names[d.role_id || skill?.role_id] || "技能观察";
      label.title = `动作观察：${who.seat}号 · ${roleName} · ${label.textContent}${targetNames ? `；目标：${targetNames}` : ""}${d.note ? `；备注：${d.note}` : ""}`;
      label.setAttribute("aria-label", label.title);
      // 固定锚定发动者，不通过全局碰撞搜索把标签推离来源。
      // 圆桌此时尚未挂载，临时在页面测量自适应标签的实际尺寸。
      label.style.visibility = "hidden";
      document.body.append(label);
      const { width, height } = label.getBoundingClientRect();
      label.remove(); label.style.removeProperty("visibility");
      const direction = targets.length ? inward : { x: -inward.x, y: -inward.y };
      const anchor = edge(source, { x: source.x + direction.x * 120, y: source.y + direction.y * 120 }, 12);
      const x = anchor.x + direction.x * (width / 2 + 4) - width / 2;
      const y = anchor.y + direction.y * (height / 2 + 4) - height / 2 + lane * 48 * (direction.y < 0 ? -1 : 1);
      label.style.left = `${x}px`; label.style.top = `${y}px`;
      {
        const leader = document.createElementNS(ns, "path");
        leader.setAttribute("d", `M${anchor.x} ${anchor.y} L${Math.max(x, Math.min(x + width, anchor.x))} ${Math.max(y, Math.min(y + height, anchor.y))}`);
        leader.classList.add("action-leader"); leader.setAttribute("stroke", color); leader.setAttribute("stroke-dasharray", "3 4"); group.append(leader);
      }
      label.tabIndex = 0;
      const highlight = (on) => { group.classList.toggle("is-highlighted", on); label.classList.toggle("is-highlighted", on); };
      label.addEventListener("mouseenter", () => highlight(true)); label.addEventListener("mouseleave", () => highlight(false));
      label.addEventListener("focus", () => highlight(true)); label.addEventListener("blur", () => highlight(false));
      board.append(label);
    });
    board.prepend(svg);
    board.classList.add("has-action-visuals");
  }
  return { describe, observations, targetsFor, ribbon, render };
})();
