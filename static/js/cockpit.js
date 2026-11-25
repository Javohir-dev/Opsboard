const COCKPIT = { busy: {}, msg: {} };

function waitList() { return data.claude_wait || []; }

function cockpitNav(ctx, r) {
  const waiting = new Set(waitList().map(w => w.sid));
  const n = waitList().length;
  const inbox = `<a href="#/cockpit" class="navi ${!r.arg ? "on" : ""}" ${!r.arg ? 'aria-current="page"' : ""}>${icon("inbox", 16)}<span class="lbl">Waiting for you</span>${n ? `<span class="n wait">${n}</span>` : ""}</a>`;
  const pins = ckPins();
  const list = ckAllSessions(ctx);
  const newBtn = `<a href="#/cockpit/new" class="cknew ${r.arg === "new" ? "on" : ""}">${icon("plus", 15)}<span>New session</span></a>`;
  const row = s => {
    const tone = waiting.has(s.id) ? "warn" : s.status === "busy" ? "busy" : "idle";
    const pinned = pins.includes(s.id);
    return `<div class="ckrow ${pinned ? "pinned" : ""}"><a href="#/cockpit/${esc(s.id)}" class="navi cksess ${r.arg === s.id ? "on" : ""}" ${r.arg === s.id ? 'aria-current="page"' : ""} title="${esc(label(s))}"><span class="dot ${tone}"></span><span class="lbl">${esc(label(s))}</span></a><button type="button" class="ckpin" data-ck-pin="${esc(s.id)}" aria-pressed="${pinned}" aria-label="${pinned ? "Unpin" : "Pin"} ${esc(label(s))}" title="${pinned ? "Unpin" : "Pin to the top"}">${icon("pin", 14)}</button></div>`;
  };
  const top = pins.map(id => list.find(s => s.id === id)).filter(Boolean);
  const rest = list.filter(s => !pins.includes(s.id));
  const pinnedGroup = top.length ? `<div class="navgroup"><div class="navtitle">Pinned</div>${top.map(row).join("")}</div>` : "";
  return `${newBtn}<div class="navgroup">${inbox}</div>${pinnedGroup}<div class="navgroup"><div class="navtitle">Sessions</div>${rest.map(row).join("") || `<span class="navi muted">${top.length ? "No other live sessions" : "No live sessions"}</span>`}</div>`;
}

function ckOwned() { return data.cockpit || []; }
function ckOwn(id) { return ckOwned().find(c => c.sid === id || c.key === id); }
function ckAllSessions(ctx) {
  const helper = new Set(ckOwned().filter(c => c.assistant).map(c => c.sid));
  const known = new Set(ctx.sessions.map(s => s.id));
  const extra = ckOwned().filter(c => (c.alive || c.resumable) && !c.assistant && !known.has(c.sid)).map(c => ({ id: c.sid || c.key, name: c.title || "New session", name_source: "user", title: "", status: c.busy ? "busy" : "idle", cockpit: true }));
  return [...extra, ...ctx.sessions.filter(x => !helper.has(x.id))];
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

const VQ = { tab: {}, pick: {}, other: {}, fold: {} };

function vqTitle(tool) {
  if (tool === "Bash") return "Allow this bash command?";
  if (["Write", "Edit", "NotebookEdit"].includes(tool)) return "Allow this edit?";
  if (tool === "Read") return "Allow reading this file?";
  if (tool.startsWith("mcp__")) return `Allow ${tool.split("__").pop()}?`;
  return `Allow ${tool}?`;
}

function waitCard(w) {
  const req = w.req || "", busy = COCKPIT.busy[req], msg = COCKPIT.msg[req] || "";
  const meta = `<div class="vqmeta" translate="no"><b>${esc(w.name || w.sid.slice(0, 8))}</b><span>${esc(w.cwd)}</span><span>${ago(w.at)}</span></div>`;
  const fold = VQ.fold[req];
  const foldBtn = `<button type="button" class="vqicon" data-vq-fold="${esc(req)}" aria-label="${fold ? "Expand" : "Collapse"}" aria-expanded="${!fold}">${icon("chevron", 16)}</button>`;
  let inner = "";
  if (w.kind === "permission_request") {
    const cut = w.message.indexOf(": ");
    const tool = cut > 0 ? w.message.slice(0, cut) : w.message;
    let rest = cut > 0 ? w.message.slice(cut + 2) : "", desc = "";
    const dash = rest.lastIndexOf(" — ");
    if (dash > 0) { desc = rest.slice(dash + 3); rest = rest.slice(0, dash); }
    const other = (VQ.other[req] || {})[0] || "";
    inner = `<div class="vqhead"><b>${esc(vqTitle(tool))}</b>${foldBtn}</div>${fold ? "" : `
      ${rest ? `<pre class="vqcmd" translate="no">${esc(rest)}</pre>` : ""}${desc ? `<div class="vqdesc">${esc(desc)}</div>` : ""}
      <div class="vqopts">
        <button type="button" class="vqopt key" data-vq-allow="${esc(req)}" ${busy ? "disabled" : ""}><kbd>1</kbd><b>Yes</b></button>
        <button type="button" class="vqopt key" data-vq-deny="${esc(req)}" ${busy ? "disabled" : ""}><kbd>2</kbd><b>No</b></button>
        <form class="vqother" data-vq-tell="${esc(req)}"><label class="wksr" for="vqt-${esc(req)}">Tell Claude what to do instead</label><input id="vqt-${esc(req)}" type="text" placeholder="Tell Claude what to do instead" autocomplete="off" value="${esc(other)}" ${busy ? "disabled" : ""}></form>
      </div>`}`;
  } else if (w.kind === "question_request" && w.questions.length) {
    const qs = w.questions, tab = Math.min(VQ.tab[req] || 0, qs.length - 1);
    const picks = VQ.pick[req] || {}, others = VQ.other[req] || {};
    const answered = qi => w.answers[qs[qi].question] != null || (picks[qi] && (picks[qi] !== "__other__" || (others[qi] || "").trim()));
    const tabs = `<div class="vqtabs" role="tablist">${qs.map((q, qi) => `<button type="button" role="tab" aria-selected="${qi === tab}" class="${qi === tab ? "on" : ""} ${answered(qi) ? "done" : ""}" data-vq-tab="${esc(req)}" data-q="${qi}">${esc(q.header || `Question ${qi + 1}`)}</button>`).join("")}</div>`;
    const q = qs[tab], sent = w.answers[q.question];
    const opts = [...(q.options || []).map(o => ({ label: o.label, desc: o.description })), { label: "__other__", desc: "" }];
    const rows = sent != null ? `<div class="vqsent">${icon("ok", 14)}Answered: ${esc(sent)}</div>` : `<div class="vqopts">${opts.map(o => {
      const sel = picks[tab] === o.label;
      return `<button type="button" class="vqopt ${sel ? "sel" : ""}" role="radio" aria-checked="${sel}" data-vq-pick="${esc(req)}" data-q="${tab}" data-label="${esc(o.label)}" ${busy ? "disabled" : ""}><span class="vqradio"></span><span class="vqtext"><b>${o.label === "__other__" ? "Other" : esc(o.label)}</b>${o.desc ? `<span>${esc(o.desc)}</span>` : ""}</span></button>`;
    }).join("")}${picks[tab] === "__other__" ? `<input class="vqown" data-vq-own="${esc(req)}" data-q="${tab}" type="text" placeholder="Type your answer" aria-label="Your answer" value="${esc(others[tab] || "")}" autocomplete="off">` : ""}</div>`;
    const ready = qs.every((_, qi) => answered(qi));
    const left = qs.filter((_, qi) => !answered(qi)).length;
    inner = `<div class="vqhead">${qs.length > 1 ? tabs : "<span></span>"}${foldBtn}</div>${fold ? "" : `<div class="vqq">${esc(q.question)}</div>${rows}
      <button type="button" class="vqsubmit" data-vq-submit="${esc(req)}" ${ready && !busy ? "" : "disabled"}>${ready ? "Submit answers" : `${left} left to answer`}</button>`}`;
  } else {
    inner = `<div class="vqhead"><b>${esc(WAIT_KIND[w.kind] === "Finished" ? "Claude finished and waits for you" : "Claude is waiting for you")}</b></div>${w.message ? `<div class="vqdesc">${esc(w.message)}</div>` : ""}<div class="vqdesc">Answer it in the session on the Mac — only VS Code and Cockpit sessions can be answered here.</div>`;
  }
  return `<section class="vqwrap">${meta}<div class="vqbox ${fold ? "folded" : ""}">${inner}${msg ? `<div class="fmsg err">${esc(msg)}</div>` : ""}</div></section>`;
}

function pageWaiting() {
  const list = waitList();
  const oldest = list.length ? ` · oldest ${ago(list[0].at)}` : "";
  return `<div class="pagehead"><h1>Waiting for you</h1><span class="sub">${plural(list.length, "session")}${oldest} · the same requests go to Telegram; the first answer wins</span></div>
    ${list.length ? `<div class="wkgrid">${list.map(waitCard).join("")}</div>` : `<div class="wkempty">${icon("ok", 20)}<span>Nothing waits for you. Permission prompts and questions from Claude sessions on this Mac show up here.</span></div>`}`;
}

function pageCockpit(ctx, arg) {
  if (!arg) return pageWaiting(ctx);
  if (arg === "new") return ckNewPage();
  const own = ckOwn(arg);
  if (own && !own.sid) return `<div class="ckchat"><div class="ckhead"><div class="cktitle"><h1>${esc(own.title || "New session")}</h1><div class="ckmeta"><span class="badge busy">Starting…</span><span class="ckchip mono">${esc(own.cwd)}</span></div></div></div><div class="ckthread"><div class="ckworking"><span class="dot busy"></span>Claude is starting…</div></div></div>`;
  if (own && own.sid && arg !== own.sid) { location.replace("#/cockpit/" + own.sid); return ""; }
  const s = ctx.sessions.find(x => x.id === arg) || (own ? { id: own.sid, name: own.title, name_source: "user", title: "", status: own.busy ? "busy" : "idle", status_since: own.last, cwd: own.cwd, entrypoint: "cockpit", activity: [], jobsRunning: [] } : null);
  const view = ckView();
  const tabs = `<div class="cktabs" role="tablist" aria-label="Session view"><button type="button" role="tab" aria-selected="${view === "chat"}" class="${view === "chat" ? "on" : ""}" data-ck-view="chat">${icon("comment", 14)}Chat</button><button type="button" role="tab" aria-selected="${view === "details"}" class="${view === "details" ? "on" : ""}" data-ck-view="details">${icon("overview", 14)}Details</button></div>`;
  if (view === "details" && ctx.sessions.find(x => x.id === arg)) return `<div class="ckhead">${ckTitle(s, arg)}${tabs}</div><div class="ckdetails">${pageSession(ctx, arg)}</div>`;
  return `<div class="ckchat"><div class="ckhead">${ckTitle(s, arg)}${tabs}</div>${ckThread(arg, s)}</div>`;
}

function ckView() { try { return localStorage.getItem("ops.ckView") === "details" ? "details" : "chat"; } catch (e) { return "chat"; } }

function ckTitle(s, id) {
  if (!s) return `<div class="cktitle"><h1>Session ended</h1></div>`;
  const own = ckOwn(id);
  const where = [s.cwd ? s.cwd.replace(/^\/Users\/[^/]+/, "~") : "", s.branch].filter(Boolean);
  const parent = own?.parent ? (ctxSessions().find(x => x.id === own.parent) || null) : null;
  const branch = own?.parent ? `<a class="ckchip ckbranch" href="#/cockpit/${esc(own.parent)}" title="Opened from this session with its whole history">↳ branch of ${esc(parent ? label(parent) : own.parent.slice(0, 8))}</a>` : "";
  return `<div class="cktitle"><h1 translate="no">${esc(own?.title || label(s))}</h1><div class="ckmeta">${statusOf(s)}${branch}${where.map(w => `<span class="ckchip mono" translate="no">${esc(w)}</span>`).join("")}</div></div>`;
}
function ctxSessions() { return data.sessions || []; }

function ckThread(id, s) {
  const c = COCKPIT.chat?.[id];
  if (!c || (Date.now() - c.at > 2500 && !c.loading)) ckLoad(id);
  if (!c) return `<div class="ckthread"><div class="skel skel-block"></div></div>`;
  if (c.error) return `<div class="ckthread"><div class="wkempty">${esc(c.error)}</div></div>`;
  const own0 = ckOwn(id);
  let list = c.items, earlier = 0;
  if (own0?.parent && own0.first && !COCKPIT.showEarly?.[id]) {
    const head = own0.first.slice(0, 60);
    let at = -1;
    c.items.forEach((it, n) => { if (it.kind === "user" && it.text.startsWith(head)) at = n; });
    if (at > 0) { earlier = at; list = c.items.slice(at); }
  }
  const early = earlier ? `<button type="button" class="ckearly" data-ck-early="${esc(id)}">${icon("history", 14)}Show ${plural(earlier, "earlier entry")} from the original session</button>` : "";
  const items = early + list.map((it, n) => xItem(it, `${id}:${c.total - c.items.length + (c.items.length - list.length) + n}`)).join("");
  const waits = waitList().filter(w => w.sid === id).map(waitCard).join("");
  const working = s && s.status === "busy" ? `<div class="ckworking"><span class="dot busy"></span>${s.doing ? esc(s.doing.tool + " — " + s.doing.what) : "Thinking…"}</div>` : "";
  const older = c.total > c.items.length ? `<div class="muted fs-sm ckolder">Showing the last ${c.items.length} of ${c.total} entries</div>` : "";
  const own = ckOwn(id);
  let foot = "";
  if (own && (own.alive || own.resumable)) foot = ckComposer(own);
  else if (own) foot = `<div class="ckcompose off">${icon("info", 15)}<span>${esc(own.error || "This session has ended.")}</span><button type="button" class="wkb" data-ck-continue="${esc(id)}">Continue in a new one</button></div>`;
  else if (s && s.entrypoint !== "background") foot = COCKPIT.continueOpen === id
    ? ckComposer(null, id)
    : `<div class="ckcompose off">${icon("cockpit", 15)}<span>This session runs in ${s.entrypoint === "claude-vscode" ? "VS Code" : "a terminal"}. Continue it here as a new branch with its whole history; the original stays as it is.</span><button type="button" class="wkb ok" data-ck-continue="${esc(id)}">Continue in Cockpit</button></div>`;
  return `<button type="button" class="ckdown" id="ckdown" data-ck-down aria-label="Scroll to the latest message" hidden>${icon("chevron", 18)}</button><div class="ckthread" id="ckthread">${older}${items || '<div class="muted">No messages yet.</div>'}${working}${waits ? `<div class="ckwaits">${waits}</div>` : ""}</div>${foot}`;
}

const X_OPEN = new Set();
function sidOf(key) { const k = key.slice(0, key.lastIndexOf(":")); return k === "as" ? (assistSession()?.sid || "") : k; }
function xTime(ts) { const d = ts ? new Date(ts) : null; return d && !isNaN(d) ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : ""; }
function xItem(it, key) {
  if (it.kind === "user") return `<div class="xuser"><div class="xubox">${it.text ? esc(it.text).replace(/\n/g, "<br>") : ""}${(it.imgs || []).length ? `<div class="ximgs">${it.imgs.map(r => `<a href="/api/session-image?id=${encodeURIComponent(sidOf(key))}&ref=${encodeURIComponent(r)}" target="_blank" rel="noopener"><img loading="lazy" alt="Pasted image" src="/api/session-image?id=${encodeURIComponent(sidOf(key))}&ref=${encodeURIComponent(r)}"></a>`).join("")}</div>` : it.images ? `<div class="muted fs-sm">${plural(it.images, "image")} attached</div>` : ""}</div>${xTime(it.ts) ? `<span class="xts">${xTime(it.ts)}</span>` : ""}</div>`;
  if (it.kind === "thought") return `<div class="xrow"><span class="xdot"></span><span class="muted">Thought for ${it.secs}s</span></div>`;
  if (it.kind === "assistant") return `<div class="xrow"><span class="xdot"></span><div class="xtext md">${md(it.text)}</div></div>`;
  if (it.kind !== "tool") return "";
  const name = it.name.replace(/^mcp__[^_]+__/, "");
  const tone = it.error ? "bad" : it.done ? "ok" : "run";
  const open = X_OPEN.has(key) ? "open" : "";
  const fileTool = ["Write", "Edit", "Read"].includes(it.name);
  const head = `<div class="xth"><b>${esc(name)}</b>${it.title ? `<span class="${fileTool ? "xfile" : "muted"}">${esc(it.title)}</span>` : ""}</div>`;
  let body = "";
  if (it.name === "Read") body = it.error ? `<div class="xio ${open}" data-x="${esc(key)}"><div class="xline"><span>OUT</span><pre>${esc(it.out)}</pre></div></div>` : "";
  else if (it.name === "Write" || it.name === "Edit") body = it.in ? `<div class="xio code ${open}" data-x="${esc(key)}"><pre>${it.name === "Edit" ? it.in.split("\n").map(l => `<span class="${l.startsWith("+ ") ? "add" : l.startsWith("- ") ? "del" : ""}">${esc(l)}</span>`).join("\n") : esc(it.in)}</pre></div>${it.error && it.out ? `<div class="xerr">${esc(it.out)}</div>` : ""}` : "";
  else body = `<div class="xio ${open}" data-x="${esc(key)}">${it.in ? `<div class="xline"><span>IN</span><pre>${esc(it.in)}</pre></div>` : ""}${it.done ? `<div class="xline ${it.error ? "bad" : ""}"><span>OUT</span><pre>${esc(it.out || "(no output)")}</pre></div>` : ""}</div>`;
  return `<div class="xrow"><span class="xdot ${tone}"></span><div class="xtool">${head}${body}</div></div>`;
}
document.addEventListener("click", e => {
  const x = e.target.closest("[data-x]");
  if (!x || getSelection().toString()) return;
  X_OPEN.has(x.dataset.x) ? X_OPEN.delete(x.dataset.x) : X_OPEN.add(x.dataset.x);
  x.classList.toggle("open");
});

const CK_MODES = [["default", "Manual"], ["acceptEdits", "Accept edits"], ["plan", "Plan"], ["auto", "Auto"]];
function ckModeSelect(own) {
  const cur = own ? own.mode : (COCKPIT.mode || "default");
  return `<label class="ckmode" title="Permission mode"><span class="wksr">Permission mode</span><select ${own ? `data-ck-mode="${esc(own.sid || own.key)}"` : 'id="ckmodesel"'}>${CK_MODES.map(([v, l]) => `<option value="${v}" ${v === cur ? "selected" : ""}>${l}</option>`).join("")}</select></label>`;
}

function ckComposer(own, resume = "") {
  const busy = own && own.busy;
  const draft = COCKPIT.draft || "";
  return `<form class="ckcompose" data-ck-send="${esc(own ? own.sid || own.key : "")}" data-ck-resume="${esc(resume)}">
    <label class="wksr" for="ckinput">Message</label>
    <textarea id="ckinput" rows="2" placeholder="${resume ? "What should it do next? It continues with the whole history" : "Write to Claude"}">${esc(draft)}</textarea>
    <div class="ckcbar">${ckModeSelect(own)}<span class="muted fs-sm">${COCKPIT.sendMsg ? esc(COCKPIT.sendMsg) : resume ? "Starts a new branch of this session in Cockpit" : "Enter to send · Shift+Enter for a new line"}</span>
    ${busy ? `<button type="button" class="wkb danger" data-ck-stop="${esc(own.sid || own.key)}">Stop</button>` : ""}${resume ? `<button type="button" class="wkb" data-ck-continue-cancel>Cancel</button>` : ""}
    <button type="submit" class="wkb ok" aria-label="Send">${icon("chevron", 15)}${resume ? "Start" : "Send"}</button></div></form>`;
}

function ckNewPage() {
  const root = (conf("project.root") || "").replace(/^\/Users\/[^/]+/, "~");
  return `<div class="ckchat"><div class="ckhead"><div class="cktitle"><h1>New session</h1><div class="ckmeta"><span class="muted fs-sm">Claude Code on this Mac, answered here and in Telegram</span></div></div></div>
    <div class="ckthread ckempty"><div class="muted">Ask anything — it works in the folder below with your usual Claude Code setup. Edits and commands ask for your permission on the Waiting page.</div></div>
    <form class="ckcompose" data-ck-new>
      <label class="wksr" for="ckinput">First message</label>
      <textarea id="ckinput" rows="3" placeholder="What should Claude do?">${esc(COCKPIT.draft || "")}</textarea>
      <div class="ckcbar">${ckModeSelect(null)}<label class="ckfolder"><span class="muted fs-sm">Folder</span><input id="ckcwd" type="text" value="${esc(COCKPIT.cwd || root)}" spellcheck="false"></label><span class="muted fs-sm">${esc(COCKPIT.sendMsg || "")}</span><button type="submit" class="wkb ok">${icon("chevron", 15)}Start</button></div>
    </form></div>`;
}

async function ckPost(path, body) {
  const r = await (await fetch("/api/cockpit/" + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json();
  if (!r.ok) throw new Error(r.error || "Failed");
  return r.session;
}

async function ckSubmit(form) {
  const ta = form.querySelector("textarea"), text = ta.value.trim();
  if (!text || COCKPIT.sending) return;
  COCKPIT.sending = true; COCKPIT.sendMsg = "Sending…"; COCKPIT.draft = text;
  try {
    let s;
    const mode = $("ckmodesel")?.value || "default";
    if (form.hasAttribute("data-ck-new")) { COCKPIT.cwd = $("ckcwd").value.trim(); s = await ckPost("new", { text, cwd: COCKPIT.cwd, mode }); }
    else if (form.dataset.ckResume) s = await ckPost("new", { text, resume: form.dataset.ckResume, mode });
    else s = await ckPost("send", { id: form.dataset.ckSend, text });
    COCKPIT.draft = ""; COCKPIT.sendMsg = ""; COCKPIT.continueOpen = null; ta.value = ""; ta.defaultValue = "";
    data = await (await fetch("/api/state", { cache: "no-store" })).json();
    if (!form.dataset.ckSend) location.hash = "#/cockpit/" + (s.sid || s.key);
    if (COCKPIT.chat?.[s.sid]) COCKPIT.chat[s.sid].at = 0;
  } catch (x) { COCKPIT.sendMsg = x.message; }
  COCKPIT.sending = false; ui.forcePatch = true; render();
}

document.addEventListener("submit", e => {
  const f = e.target.closest("form[data-ck-send], form[data-ck-new]");
  if (!f) return;
  e.preventDefault(); ckSubmit(f);
});
document.addEventListener("keydown", e => {
  if (e.target.id !== "ckinput" || e.key !== "Enter" || e.shiftKey || e.isComposing) return;
  e.preventDefault(); ckSubmit(e.target.closest("form"));
});
document.addEventListener("input", e => { if (e.target.id === "ckinput") COCKPIT.draft = e.target.value; });
document.addEventListener("change", async e => {
  if (e.target.id === "ckmodesel") { COCKPIT.mode = e.target.value; return; }
  const m = e.target.closest("[data-ck-mode]");
  if (!m) return;
  try { await ckPost("mode", { id: m.dataset.ckMode, mode: m.value }); COCKPIT.sendMsg = ""; } catch (x) { COCKPIT.sendMsg = x.message; }
  data = await (await fetch("/api/state", { cache: "no-store" })).json(); ui.forcePatch = true; render();
});
document.addEventListener("click", e => {
  const b = e.target.closest("[data-ck-early]");
  if (!b) return;
  (COCKPIT.showEarly ||= {})[b.dataset.ckEarly] = true; ui.forcePatch = true; render();
});
document.addEventListener("click", async e => {
  const c = e.target.closest("[data-ck-continue]");
  if (c) { COCKPIT.continueOpen = c.dataset.ckContinue; ui.forcePatch = true; render(); $("ckinput")?.focus(); return; }
  if (e.target.closest("[data-ck-continue-cancel]")) { COCKPIT.continueOpen = null; ui.forcePatch = true; render(); return; }
  const st = e.target.closest("[data-ck-stop]");
  if (st) { st.disabled = true; try { await ckPost("stop", { id: st.dataset.ckStop }); } catch (x) {} }
});

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
  const al = e.target.closest("[data-vq-allow]");
  if (al) { waitAnswer(al.dataset.vqAllow, { allow: true }); return; }
  const dn = e.target.closest("[data-vq-deny]");
  if (dn) { waitAnswer(dn.dataset.vqDeny, { allow: false }); return; }
  const tb = e.target.closest("[data-vq-tab]");
  if (tb) { VQ.tab[tb.dataset.vqTab] = +tb.dataset.q; ui.forcePatch = true; render(); renderAssist?.(); return; }
  const fd = e.target.closest("[data-vq-fold]");
  if (fd) { VQ.fold[fd.dataset.vqFold] = !VQ.fold[fd.dataset.vqFold]; ui.forcePatch = true; render(); renderAssist?.(); return; }
  const pk = e.target.closest("[data-vq-pick]");
  if (pk) {
    const req = pk.dataset.vqPick, qi = +pk.dataset.q;
    (VQ.pick[req] ||= {})[qi] = pk.dataset.label;
    const w = waitList().find(x => x.req === req);
    if (pk.dataset.label !== "__other__" && w && qi < w.questions.length - 1) VQ.tab[req] = qi + 1;
    ui.forcePatch = true; render(); renderAssist?.();
    if (pk.dataset.label === "__other__") setTimeout(() => document.querySelector(`[data-vq-own="${CSS.escape(req)}"]`)?.focus(), 30);
    return;
  }
  const sb = e.target.closest("[data-vq-submit]");
  if (sb) {
    const req = sb.dataset.vqSubmit, w = waitList().find(x => x.req === req);
    if (!w) return;
    const answers = {};
    w.questions.forEach((q, qi) => {
      if (w.answers[q.question] != null) return;
      const p = (VQ.pick[req] || {})[qi];
      answers[qi] = p === "__other__" ? ((VQ.other[req] || {})[qi] || "").trim() : p;
    });
    waitAnswer(req, { answers });
  }
});
document.addEventListener("input", e => {
  const o = e.target.closest("[data-vq-own]");
  if (o) { (VQ.other[o.dataset.vqOwn] ||= {})[+o.dataset.q] = o.value; render(); renderAssist?.(); return; }
  const t = e.target.closest("[data-vq-tell] input");
  if (t) (VQ.other[t.closest("form").dataset.vqTell] ||= {})[0] = t.value;
});
document.addEventListener("submit", e => {
  const f = e.target.closest("[data-vq-tell]");
  if (!f) return;
  e.preventDefault();
  const text = f.querySelector("input").value.trim();
  if (text) waitAnswer(f.dataset.vqTell, { allow: false, message: text });
});
document.addEventListener("keydown", e => {
  if (e.key !== "Enter" || !e.target.matches("[data-vq-own]")) return;
  e.preventDefault(); document.querySelector(`[data-vq-submit="${CSS.escape(e.target.dataset.vqOwn)}"]`)?.click();
});

function openLightbox(src) {
  let box = $("lightbox");
  if (!box) {
    box = document.createElement("dialog");
    box.id = "lightbox"; box.className = "lightbox"; box.setAttribute("aria-label", "Image");
    box.innerHTML = '<button type="button" class="lbclose" aria-label="Close">×</button><img alt="Pasted image">';
    box.addEventListener("click", e => { if (e.target === box || e.target.closest(".lbclose")) box.close(); });
    document.body.appendChild(box);
  }
  box.querySelector("img").src = src;
  box.showModal();
}
document.addEventListener("click", e => {
  const a = e.target.closest(".ximgs a");
  if (!a || e.metaKey || e.ctrlKey) return;
  e.preventDefault();
  openLightbox(a.href);
});

COCKPIT.stick = {};
function ckNear(t) { return t.scrollHeight - t.scrollTop - t.clientHeight < 80; }
function ckAfterRender() {
  const t = $("ckthread"), id = route().arg;
  if (!t) return;
  if (COCKPIT.stick[id] !== false) t.scrollTop = t.scrollHeight;
  const b = $("ckdown"); if (b) b.hidden = COCKPIT.stick[id] !== false;
}
document.addEventListener("scroll", e => {
  if (e.target.id !== "ckthread") return;
  const id = route().arg, stick = ckNear(e.target);
  COCKPIT.stick[id] = stick;
  const b = $("ckdown"); if (b) b.hidden = stick;
}, true);
document.addEventListener("load", e => {
  if (e.target.tagName === "IMG" && e.target.closest("#ckthread") && COCKPIT.stick[route().arg] !== false) { const t = $("ckthread"); t.scrollTop = t.scrollHeight; }
}, true);
document.addEventListener("click", e => {
  if (!e.target.closest("[data-ck-down]")) return;
  const t = $("ckthread"); if (!t) return;
  COCKPIT.stick[route().arg] = true;
  t.scrollTo({ top: t.scrollHeight, behavior: "smooth" });
});
addEventListener("hashchange", () => { const r = route(); if (r.page === "cockpit" && r.arg) COCKPIT.stick[r.arg] = true; });
