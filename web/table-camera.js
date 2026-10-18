"use strict";

window.TableCamera = (() => {
  let state, observer, viewportSize;
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  function mount(viewport, board, controls, gameId, size) {
    observer?.disconnect();
    if (!state || state.gameId !== gameId || state.size !== size) state = { gameId, size, zoom: 1, x: 0, y: 0, auto: true };
    const applySize = () => {
      viewport.classList.toggle("is-user-sized", Boolean(viewportSize));
      viewport.style.width = viewportSize ? `${viewportSize.width}px` : "";
      viewport.style.height = viewportSize ? `${viewportSize.height}px` : "";
    };
    applySize();
    const toolbar = document.createElement("div"); toolbar.className = "table-zoom"; toolbar.setAttribute("aria-label", "圆桌视角");
    const percent = document.createElement("output"); percent.setAttribute("aria-live", "polite");
    const apply = () => {
      board.style.transform = `translate(${state.x}px, ${state.y}px) scale(${state.zoom})`;
      percent.textContent = `${Math.round(state.zoom * 100)}%`;
    };
    const fit = () => {
      // 外围留白用于容纳标签，不计入初始适配；仅适配玩家卡片围成的圆桌。
      const tableSize = size - 480 + 144;
      state.zoom = Math.min(1, (viewport.clientWidth - 24) / tableSize, (viewport.clientHeight - 24) / tableSize);
      state.x = (viewport.clientWidth - size * state.zoom) / 2;
      state.y = (viewport.clientHeight - size * state.zoom) / 2;
      state.auto = true; apply();
    };
    const zoomAt = (zoom, x = viewport.clientWidth / 2, y = viewport.clientHeight / 2) => {
      const next = clamp(zoom, Math.min(.15, (viewport.clientWidth - 24) / size), 2.5);
      const ratio = next / state.zoom;
      state.x = x - (x - state.x) * ratio; state.y = y - (y - state.y) * ratio;
      state.zoom = next; state.auto = false; apply();
    };
    const button = (text, title, action) => {
      const b = document.createElement("button"); b.type = "button"; b.textContent = text; b.title = title; b.setAttribute("aria-label", title); b.addEventListener("click", action); return b;
    };
    const fitButton = button("", "适应窗口", fit);
    const resetButton = button("", "重置大小", () => { viewportSize = undefined; applySize(); fit(); });
    const icon = (b, path) => {
      const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg"), p = document.createElementNS(ns, "path");
      svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true");
      p.setAttribute("d", path); svg.append(p); b.append(svg);
    };
    icon(fitButton, "M14 4h6v6M20 4l-7 7M10 20H4v-6M4 20l7-7");
    icon(resetButton, "M4 10a8 8 0 1 1 1 8M4 4v6h6");
    toolbar.append(button("−", "缩小圆桌", () => zoomAt(state.zoom / 1.2)), percent, button("+", "放大圆桌", () => zoomAt(state.zoom * 1.2)), fitButton, resetButton);
    viewport.append(toolbar);
    {
      const handle = document.createElement("div"); handle.className = "table-resize table-resize-bottom";
      handle.tabIndex = 0; handle.setAttribute("role", "separator"); handle.setAttribute("aria-label", "调整圆桌视窗高度"); handle.setAttribute("aria-orientation", "horizontal");
      handle.title = "拖动调整高度；上下方向键微调";
      let drag;
      const resize = (width, height) => {
        const maxWidth = viewport.parentElement.clientWidth - (matchMedia("(max-width: 700px)").matches ? 0 : 72);
        viewportSize = { width: clamp(width, Math.min(220, maxWidth), maxWidth), height: clamp(height, 240, 1600) };
        applySize();
      };
      handle.addEventListener("pointerdown", (e) => {
        if (e.button !== 0) return;
        e.preventDefault(); e.stopPropagation();
        drag = { x: e.clientX, y: e.clientY, width: viewport.clientWidth, height: viewport.clientHeight };
        handle.setPointerCapture(e.pointerId);
      });
      handle.addEventListener("pointermove", (e) => {
        if (!drag) return;
        e.preventDefault(); e.stopPropagation();
        resize(drag.width, drag.height + e.clientY - drag.y);
      });
      const finish = () => { drag = undefined; };
      handle.addEventListener("pointerup", finish); handle.addEventListener("pointercancel", finish);
      handle.addEventListener("click", (e) => e.stopPropagation());
      handle.addEventListener("keydown", (e) => {
        if (!["ArrowUp", "ArrowDown"].includes(e.key)) return;
        e.preventDefault(); e.stopPropagation();
        resize(viewport.clientWidth, viewport.clientHeight + (e.key === "ArrowDown" ? 20 : -20));
      });
      viewport.append(handle);
    }
    viewport.title = "拖动空白处平移；Ctrl / ⌘ + 滚轮缩放；触屏双指缩放";
    viewport.addEventListener("wheel", (e) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault(); const rect = viewport.getBoundingClientRect();
      zoomAt(state.zoom * Math.exp(-e.deltaY * (e.deltaMode === 1 ? 16 : 1) * .002), e.clientX - rect.left, e.clientY - rect.top);
    }, { passive: false });
    const pointers = new Map(); let previous, dragged = false;
    const snapshot = () => {
      const points = [...pointers.values()];
      if (points.length >= 2) return { x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2, distance: Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y) };
      return points[0];
    };
    viewport.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || e.target.closest(".table-resize, .table-zoom") || (e.pointerType !== "touch" && e.target.closest("button, .action-label"))) return;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY }); previous = snapshot(); dragged = false;
      if (e.pointerType !== "touch") viewport.setPointerCapture(e.pointerId);
    });
    viewport.addEventListener("pointermove", (e) => {
      if (!pointers.has(e.pointerId)) return;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY }); const next = snapshot();
      const dx = next.x - previous.x, dy = next.y - previous.y;
      if (Math.abs(dx) + Math.abs(dy) > 2 || next.distance) dragged = true;
      if (dragged && !viewport.hasPointerCapture(e.pointerId)) viewport.setPointerCapture(e.pointerId);
      if (next.distance && previous.distance) {
        const rect = viewport.getBoundingClientRect(); zoomAt(state.zoom * next.distance / Math.max(1, previous.distance), previous.x - rect.left, previous.y - rect.top);
      }
      state.x += dx; state.y += dy; state.auto = false; apply(); previous = next;
      viewport.classList.toggle("is-panning", dragged);
    });
    const release = (e) => { pointers.delete(e.pointerId); previous = snapshot(); if (!pointers.size) viewport.classList.remove("is-panning"); };
    viewport.addEventListener("pointerup", release); viewport.addEventListener("pointercancel", release);
    viewport.addEventListener("click", (e) => { if (dragged) { e.preventDefault(); e.stopPropagation(); dragged = false; } }, true);
    viewport.addEventListener("keydown", (e) => {
      if (e.target !== viewport) return;
      const delta = { ArrowLeft: [30, 0], ArrowRight: [-30, 0], ArrowUp: [0, 30], ArrowDown: [0, -30] }[e.key];
      if (delta) { e.preventDefault(); state.x += delta[0]; state.y += delta[1]; state.auto = false; apply(); }
      else if (["+", "=", "-", "0"].includes(e.key)) { e.preventDefault(); if (e.key === "0") fit(); else zoomAt(state.zoom * (e.key === "-" ? 1 / 1.2 : 1.2)); }
    });
    observer = new ResizeObserver(() => { if (state.auto) fit(); }); observer.observe(viewport);
    if (state.auto) fit(); else apply();
  }
  return { mount };
})();
