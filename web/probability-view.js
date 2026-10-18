"use strict";

window.ProbabilityView = (() => {
  const names = window.ClocktowerRoles.names;
  const good = ["#28639e", "#427bb5", "#578dc3", "#1e527f", "#709dca", "#346d98"];
  const evil = ["#aa3547", "#c14e60", "#912b40", "#d3707d"];
  function entries(row) {
    let blue = 0, red = 0;
    return Object.entries(row?.probabilities || {})
      .filter(([id, value]) => Object.hasOwn(names, id) && Number.isFinite(value) && value > 0 && value <= 1)
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([id, value]) => {
        const alignment = window.ClocktowerRoles.defaultAlignments[id];
        return { id, value, name: names[id], alignment, color: alignment === "evil" ? evil[red++ % evil.length] : good[blue++ % good.length] };
      });
  }
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  function panel(items) {
    const section = el("section", undefined, "probability-panel");
    section.append(el("h3", "初始身份概率估计"), el("p", "带权抽样估计，不是确定身份；蓝色代表善良，红色代表邪恶。", "hint"));
    const layout = el("div", undefined, "probability-layout");
    const ns = "http://www.w3.org/2000/svg", chart = document.createElementNS(ns, "svg");
    chart.setAttribute("viewBox", "0 0 160 160"); chart.classList.add("probability-donut"); chart.setAttribute("role", "img"); chart.setAttribute("aria-label", "初始身份概率环状图，具体比例见旁边列表");
    const total = items.reduce((sum, item) => sum + item.value, 0);
    let offset = 0;
    for (const item of items) {
      const circle = document.createElementNS(ns, "circle"), length = item.value / total * 100;
      for (const [key, value] of Object.entries({ cx: 80, cy: 80, r: 58, fill: "none", stroke: item.color, "stroke-width": 24, pathLength: 100, "stroke-dasharray": `${length} ${100 - length}`, "stroke-dashoffset": -offset, transform: "rotate(-90 80 80)" })) circle.setAttribute(key, String(value));
      const title = document.createElementNS(ns, "title"); title.textContent = `${item.name} ${(item.value * 100).toFixed(1)}%`; circle.append(title); chart.append(circle); offset += length;
    }
    const caption = document.createElementNS(ns, "text"); caption.setAttribute("x", "80"); caption.setAttribute("y", "85"); caption.setAttribute("text-anchor", "middle"); caption.textContent = "初始身份"; chart.append(caption);
    const list = el("ul", undefined, "probability-list");
    for (const item of items) {
      const row = el("li"), swatch = el("span", undefined, "probability-swatch"); swatch.style.background = item.color; swatch.setAttribute("aria-hidden", "true");
      row.append(swatch, el("span", `${item.name} · ${item.alignment === "evil" ? "邪恶" : "善良"}`), el("strong", `${(item.value * 100).toFixed(1)}%`)); list.append(row);
    }
    layout.append(chart, list); section.append(layout); return section;
  }
  return { entries, panel };
})();
