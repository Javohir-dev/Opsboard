const COCKPIT = { busy: {}, msg: {} };

function waitList() { return data.claude_wait || []; }

function cockpitNav(ctx, r) {
  const waiting = new Set(waitList().map(w => w.sid));
  const n = waitList().length;
  const inbox = `<a href="#/cockpit" class="navi ${!r.arg ? "on" : ""}" ${!r.arg ? 'aria-current="page"' : ""}>${icon("inbox", 16)}<span class="lbl">Waiting for you</span>${n ? `<span class="n wait">${n}</span>` : ""}</a>`;
  const pins = ckPins();
  const row = s => {
    const tone = waiting.has(s.id) ? "warn" : s.status === "busy" ? "busy" : "idle";
    const pinned = pins.includes(s.id);
    return `<div class="ckrow ${pinned ? "pinned" : ""}"><a href="#/cockpit/${esc(s.id)}" class="navi cksess ${r.arg === s.id ? "on" : ""}" ${r.arg === s.id ? 'aria-current="page"' : ""} title="${esc(label(s))}"><span class="dot ${tone}"></span><span class="lbl">${esc(label(s))}</span></a><button type="button" class="ckpin" data-ck-pin="${esc(s.id)}" aria-pressed="${pinned}" aria-label="${pinned ? "Unpin" : "Pin"} ${esc(label(s))}" title="${pinned ? "Unpin" : "Pin to the top"}">${icon("pin", 14)}</button></div>`;
  };
  const top = pins.map(id => ctx.sessions.find(s => s.id === id)).filter(Boolean);
  const rest = ctx.sessions.filter(s => !pins.includes(s.id));
  const pinnedGroup = top.length ? `<div class="navgroup"><div class="navtitle">Pinned</div>${top.map(row).join("")}</div>` : "";
  return `<div class="navgroup">${inbox}</div>${pinnedGroup}<div class="navgroup"><div class="navtitle">Sessions</div>${rest.map(row).join("") || `<span class="navi muted">${top.length ? "No other live sessions" : "No live sessions"}</span>`}</div>`;
}

function ckPins() {
  try { const v = JSON.parse(localStorage.getItem("ops.ckPins") || "[]"); return Array.isArray(v) ? v.map(String) : []; } catch (e) { return []; }
}
function setCkPins(list) { try { localStorage.setItem("ops.ckPins", JSON.stringify(list)); } catch (e) {} }

document.addEventListener("click", e => {
  const b = e.target.closest("[data-ck-pin]");
  if (!b) return;
  e.preventDefault();
  const id = b.dataset.ckPin, pins = ckPins();
  setCkPins(pins.includes(id) ? pins.filter(x => x !== id) : [...pins, id]);
  render();
});

const WAIT_KIND = { permission_request: "Permission", permission_prompt: "Permission", question_request: "Question", question: "Question", elicitation_dialog: "Question", idle_prompt: "Finished" };

function waitCard(w) {
  const kind = WAIT_KIND[w.kind] || "Waiting";
  const tone = kind === "Permission" ? "warn" : kind === "Question" ? "acc" : "muted";
  const where = [w.name, w.cwd].filter(Boolean).join(" · ");
  const busy = COCKPIT.busy[w.req], msg = COCKPIT.msg[w.req] || "";
  const head = `<div class="wkhead"><span class="wkkind ${tone}">${kind}</span><b class="wkname" translate="no">${esc(w.name || w.sid.slice(0, 8))}</b><span class="muted fs-sm wkago">${ago(w.at)}</span></div>
    <div class="muted fs-sm mono wkwhere" translate="no">${esc(where)}</div>`;
  let body = "";
  if (w.kind === "permission_request") {
    body = `<div class="wkcmd mono" translate="no">${esc(w.message)}</div>
      <div class="wkbtns"><button class="wkb ok" data-wait-allow="${esc(w.req)}" ${busy ? "disabled" : ""}>Allow</button><button class="wkb danger" data-wait-deny="${esc(w.req)}" ${busy ? "disabled" : ""}>Deny</button></div>`;
  } else if (w.kind === "question_request" && w.questions.length) {
    body = w.questions.map((q, qi) => {
      const done = w.answers[q.question];
      return `<div class="wkq"><div class="wkqtext">${esc(q.question)}</div>${done ? `<div class="okmsg fs-sm">Answered: ${esc(done)}</div>` : `<div class="wkopts">${(q.options || []).map(o => `<button class="wkopt" data-wait-pick="${esc(w.req)}" data-q="${qi}" data-text="${esc(o.label)}" ${busy ? "disabled" : ""}><b>${esc(o.label)}</b>${o.description ? `<span class="muted fs-sm">${esc(o.description)}</span>` : ""}</button>`).join("")}</div>
        <form class="wkown" data-wait-own="${esc(w.req)}" data-q="${qi}"><label class="wksr" for="own-${esc(w.req)}-${qi}">Your own answer</label><input id="own-${esc(w.req)}-${qi}" type="text" placeholder="Or type your own answer" autocomplete="off"><button class="wkb" type="submit" ${busy ? "disabled" : ""}>Send</button></form>`}</div>`;
    }).join("");
  } else {
    body = `${w.message ? `<div class="wkmsg">${esc(w.message)}</div>` : ""}<div class="muted fs-sm">Answer it in the session on the Mac — only VS Code sessions can be answered from here.</div>`;
  }
  return `<section class="wkcard">${head}${body}${msg ? `<div class="fmsg err">${esc(msg)}</div>` : ""}</section>`;
}

function pageWaiting() {
  const list = waitList();
  const oldest = list.length ? ` · oldest ${ago(list[0].at)}` : "";
  return `<div class="pagehead"><h1>Waiting for you</h1><span class="sub">${plural(list.length, "session")}${oldest} · the same requests go to Telegram; the first answer wins</span></div>
    ${list.length ? `<div class="wkgrid">${list.map(waitCard).join("")}</div>` : `<div class="wkempty">${icon("ok", 20)}<span>Nothing waits for you. Permission prompts and questions from Claude sessions on this Mac show up here.</span></div>`}`;
}

function pageCockpit(ctx, arg) {
  if (!arg) return pageWaiting(ctx);
  const s = ctx.sessions.find(x => x.id === arg);
  const view = ckView();
  const tabs = `<div class="cktabs" role="tablist" aria-label="Session view"><button type="button" role="tab" aria-selected="${view === "chat"}" class="${view === "chat" ? "on" : ""}" data-ck-view="chat">${icon("comment", 14)}Chat</button><button type="button" role="tab" aria-selected="${view === "details"}" class="${view === "details" ? "on" : ""}" data-ck-view="details">${icon("overview", 14)}Details</button></div>`;
  if (view === "details") return `<div class="ckhead">${ckTitle(s, arg)}${tabs}</div><div class="ckdetails">${pageSession(ctx, arg)}</div>`;
  return `<div class="ckchat"><div class="ckhead">${ckTitle(s, arg)}${tabs}</div>${ckThread(arg, s)}</div>`;
}

function ckView() { try { return localStorage.getItem("ops.ckView") === "details" ? "details" : "chat"; } catch (e) { return "chat"; } }

function ckTitle(s, id) {
  if (!s) return `<div class="cktitle"><h1>Session ended</h1></div>`;
  const where = [s.cwd ? s.cwd.replace(/^\/Users\/[^/]+/, "~") : "", s.branch].filter(Boolean);
  return `<div class="cktitle"><h1 translate="no">${esc(label(s))}</h1><div class="ckmeta">${statusOf(s)}${where.map(w => `<span class="ckchip mono" translate="no">${esc(w)}</span>`).join("")}</div></div>`;
}

function ckThread(id, s) {
  const c = COCKPIT.chat?.[id];
  if (!c || (Date.now() - c.at > 2500 && !c.loading)) ckLoad(id);
  if (!c) return `<div class="ckthread"><div class="skel skel-block"></div></div>`;
  if (c.error) return `<div class="ckthread"><div class="wkempty">${esc(c.error)}</div></div>`;
  const items = c.items.map(it => {
    if (it.kind === "user") return `<div class="ckmsg me"><div class="ckbub">${it.text ? `<div class="mdtext">${esc(it.text).replace(/\n/g, "<br>")}</div>` : ""}${it.images ? `<div class="muted fs-sm">${plural(it.images, "image")} attached</div>` : ""}</div></div>`;
    if (it.kind === "assistant") return `<div class="ckmsg ai"><div class="ckai md">${md(it.text)}</div></div>`;
    const bad = it.tools.filter(t => t.error).length;
    const names = [...new Set(it.tools.map(t => t.name.replace(/^mcp__[^_]+__/, "")))].slice(0, 4).join(", ");
    return `<details class="cktools"><summary>${icon(bad ? "fail" : "ok", 14)}<span>${plural(it.tools.length, "step")}</span><span class="muted">${esc(names)}</span></summary><ul>${it.tools.map(t => `<li class="${t.error ? "err" : ""}"><b>${esc(t.name.replace(/^mcp__[^_]+__/, ""))}</b> <span class="muted mono">${esc(t.what)}</span></li>`).join("")}</ul></details>`;
  }).join("");
  const waits = waitList().filter(w => w.sid === id).map(waitCard).join("");
  const working = s && s.status === "busy" ? `<div class="ckworking"><span class="dot busy"></span>${s.doing ? esc(s.doing.tool + " — " + s.doing.what) : "Thinking…"}</div>` : "";
  const older = c.total > c.items.length ? `<div class="muted fs-sm ckolder">Showing the last ${c.items.length} of ${c.total} entries</div>` : "";
  const foot = s && s.entrypoint && s.entrypoint !== "background"
    ? `<div class="ckcompose off">${icon("cockpit", 15)}<span>This session runs in ${s.entrypoint === "claude-vscode" ? "VS Code" : "a terminal"} — write to it there. Permission prompts and questions can be answered here.</span></div>`
    : "";
  return `<div class="ckthread" id="ckthread">${older}${items || '<div class="muted">No messages yet.</div>'}${working}${waits ? `<div class="ckwaits">${waits}</div>` : ""}</div>${foot}`;
}

async function ckLoad(id) {
  const c = (COCKPIT.chat ||= {})[id] ||= { items: [], total: 0, at: 0 };
  c.loading = true;
  try {
    const r = await (await fetch("/api/session-chat?id=" + encodeURIComponent(id), { cache: "no-store" })).json();
    const grew = r.ok && (r.total !== c.total || !c.at);
    if (r.ok) Object.assign(c, { items: r.items, total: r.total, error: "" }); else c.error = r.error;
    c.at = Date.now(); c.loading = false;
    if (grew || !r.ok) {
      const el = $("ckthread"), near = !el || el.scrollHeight - el.scrollTop - el.clientHeight < 120;
      render();
      const now = $("ckthread"); if (now && near) now.scrollTop = now.scrollHeight;
    }
  } catch (x) { c.loading = false; c.at = Date.now(); }
}

document.addEventListener("click", e => {
  const v = e.target.closest("[data-ck-view]");
  if (!v) return;
  try { localStorage.setItem("ops.ckView", v.dataset.ckView); } catch (x) {}
  ui.forcePatch = true; render();
  const t = $("ckthread"); if (t) t.scrollTop = t.scrollHeight;
});

async function waitAnswer(req, body) {
  COCKPIT.busy[req] = true; delete COCKPIT.msg[req]; render();
  try {
    const r = await (await fetch("/api/claude-wait-answer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ req, ...body }) })).json();
    if (!r.ok) COCKPIT.msg[req] = r.error || "Could not send it";
  } catch (x) { COCKPIT.msg[req] = "Dashboard server is not reachable"; }
  delete COCKPIT.busy[req];
  try { data = await (await fetch("/api/state", { cache: "no-store" })).json(); } catch (x) {}
  render();
}

document.addEventListener("click", e => {
  const a = e.target.closest("[data-wait-allow], [data-wait-deny]");
  if (a) { waitAnswer(a.dataset.waitAllow || a.dataset.waitDeny, { allow: !!a.dataset.waitAllow }); return; }
  const p = e.target.closest("[data-wait-pick]");
  if (p) waitAnswer(p.dataset.waitPick, { question: +p.dataset.q, text: p.dataset.text });
});
document.addEventListener("submit", e => {
  const f = e.target.closest("[data-wait-own]");
  if (!f) return;
  e.preventDefault();
  const text = f.querySelector("input").value.trim();
  if (text) waitAnswer(f.dataset.waitOwn, { question: +f.dataset.q, text });
});
