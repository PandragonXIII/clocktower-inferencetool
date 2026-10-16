"use strict";

window.Setup = (() => {
  const get = (id) => document.getElementById(id);
  let step = 1, count = 7, seat = 1, role = "", seatNotice = "", hasGame = false;
  let startGame;
  const radio = (name, value, label, checked) => {
    const wrap = document.createElement("label"); wrap.className = "setup-option";
    const input = document.createElement("input"); input.type = "radio"; input.name = name; input.value = value; input.defaultChecked = checked; input.checked = checked;
    const caption = document.createElement("span"); caption.textContent = label;
    wrap.append(input, caption); return wrap;
  };
  function showWorkspace() {
    get("setup").hidden = true; get("workspace").hidden = false;
    const skip = document.querySelector(".skip"); skip.href = "#roundtable"; skip.textContent = "跳到圆桌";
  }
  function update(focus = true) {
    get("setup-count").hidden = step !== 1; get("setup-seat").hidden = step !== 2; get("setup-role").hidden = step !== 3;
    get("setup-back").hidden = step === 1; get("setup-cancel").hidden = !hasGame;
    const progress = get("setup-progress");
    const percent = Math.round(step / 3 * 100);
    progress.setAttribute("aria-valuenow", String(step)); progress.setAttribute("aria-valuetext", `第 ${step}/3 步，${percent}%`);
    progress.firstElementChild.style.width = `${step / 3 * 100}%`;
    get("setup-step").textContent = `第 ${step}/3 步 · ${percent}%`;
    get("setup-title").textContent = ["这局有几位玩家？", "你坐在几号位？", "你的初始身份是什么？"][step - 1];
    get("setup-help").textContent = ["暗流涌动支持 5–15 人，已预选 7 人，可直接更改。", `请选择你的座位，范围为 1–${count} 号。圆桌将把此座位标记为“本人（你）”。`, `你坐在 ${seat} 号位。身份仅记为玩家声明（reported），不是已确认身份，也不会据此推断阵营。`][step - 1];
    get("setup-selection").textContent = `已选：${count} 人局 · 本人 ${seat} 号位 · ${window.ClocktowerRoles.names[role] || "暂不确定"}`;
    get("setup-seat-notice").textContent = seatNotice;
    get("setup-seat-notice").hidden = !seatNotice;
    get("setup-next").textContent = ["下一步：选择本人座位", "下一步：选择本人身份", "完成设置，创建圆桌"][step - 1];
    if (focus) get("setup-title").focus();
  }
  function renderSeats() {
    const options = get("seat-options"); options.replaceChildren();
    for (let n = 1; n <= count; n += 1) options.append(radio("self-seat", String(n), `${n} 号`, n === seat));
  }
  function open() {
    window.DayVoting.close();
    window.NightDeaths.close();
    window.PlayerActions.close();
    step = 1; count = 7; seat = 1; role = ""; seatNotice = "";
    get("setup-form").reset();
    renderSeats();
    get("setup").hidden = false; get("workspace").hidden = true;
    const skip = document.querySelector(".skip"); skip.href = "#setup-title"; skip.textContent = "跳到初始设置";
    update();
  }
  function request() {
    const id = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${++sequence}-${Math.random().toString(36).slice(2)}`;
    return {
      api_version: "1.0", request_id: `req-${id}`,
      game: { id: `game-${id}`, revision: 0, script_id: "trouble_brewing", players: Array.from({ length: count }, (_, i) => ({ id: `p${i + 1}`, seat: i + 1, name: i + 1 === seat ? "本人（你）" : `玩家${i + 1}` })), time: { phase: "setup" } },
      facts: role ? [{ id: "f-self-role", type: "role", status: "reported", enabled: true, proposition: { kind: "role", player_id: `p${seat}`, role_id: role, time: { phase: "setup" } } }] : [],
      assumptions: [], queries: [], options: { timeout_ms: 1000 }
    };
  }
  let sequence = 0;
  function init(app) {
    startGame = app.startGame;
    for (let n = 5; n <= 15; n += 1) get("count-options").append(radio("player-count", String(n), `${n} 人`, n === 7));
    renderSeats();
    const options = get("role-options"); options.append(radio("self-role", "", "暂不确定", true));
    window.ClocktowerRoles.groups.forEach((group) => {
      const heading = document.createElement("h3"); heading.textContent = group.name;
      const grid = document.createElement("div"); grid.className = "role-grid";
      group.roles.forEach(([id, name]) => grid.append(radio("self-role", id, name, false)));
      options.append(heading, grid);
    });
    get("setup-form").addEventListener("change", (event) => {
      if (event.target.name === "player-count") {
        count = Number(event.target.value);
        if (seat > count) {
          seatNotice = `原选 ${seat} 号位超出 ${count} 人局范围，已自动改为 1 号位。你可以在下一步重新选择。`;
          seat = 1;
        }
        renderSeats();
      }
      if (event.target.name === "self-seat") { seat = Number(event.target.value); seatNotice = ""; }
      if (event.target.name === "self-role") role = event.target.value;
      update(false);
    });
    get("setup-form").addEventListener("submit", (event) => {
      event.preventDefault();
      if (step < 3) { step += 1; update(); return; }
      hasGame = true; showWorkspace(); startGame(request());
      get("new-game").focus();
    });
    get("setup-back").addEventListener("click", () => { step -= 1; update(); });
    get("setup-cancel").addEventListener("click", () => { showWorkspace(); get("new-game").focus(); });
    get("new-game").addEventListener("click", open);
    update(false);
  }
  return { init };
})();
