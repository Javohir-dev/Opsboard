function getPrefRaw(k) { try { return localStorage.getItem("ops." + k); } catch (e) { return null; } }
function getPref(k) { try { return localStorage.getItem("ops." + k) === "1"; } catch (e) { return false; } }
function setPref(k, v) { try { localStorage.setItem("ops." + k, v ? "1" : "0"); } catch (e) {} }

function route() { const h = location.hash.replace(/^#\/?/, ""); const [page, arg] = h.split("/"); return { page: page || "overview", arg: decodeURIComponent(arg || "") }; }

function render() {
  if (!data) return;
  const ctx = context(), r = route();
  const agentsRunning = ctx.sessions.reduce((a, s) => a + s.running.length, 0);
  const count = {
    sessions: ctx.sessions.length,
    docker: (data.containers || []).filter(c => c.state === "running").length,
    postgres: Object.values(ctx.dbConns).reduce((a, c) => a + c.total, 0),
    tasks: (data.jira?.issues || []).filter(i => !["done", "cancelled"].includes(statusMap()[i.status] || (i.category === "done" ? "done" : ""))).length,
    mrs: (data.review?.mrs || []).filter(x => x.state === "opened").length,
    worktrees: (data.worktrees || []).length,
  };
  const groups = [
    ["", [["overview", "Overview"], ["sessions", "Sessions"], ["tasks", "Tasks"], ["mrs", mrWord()], ["notes", "Notes"]]],
    ["Infrastructure", [["docker", "Docker"], ["postgres", "Postgres"], ["worktrees", "Worktrees"], ["processes", "Processes"]]],
    ["", [["settings", "Settings"]]],
  ];
  const missing = setupMissing();
  const locked = missing.length > 0;
  if (locked && r.page !== "settings" && r.page !== "notes") { location.hash = "#/settings"; return; }
  const active = r.page === "s" ? "sessions" : r.page === "mr" ? "mrs" : r.page;
  const navItem = ([k, label]) => {
    const combo = (hotkeys().find(h => h.page === k) || {}).combo;
    const n = count[k] ? `<span class="n">${count[k]}</span>` : "";
    const busy = k === "sessions" && agentsRunning ? `<span class="n busy" title="${esc(plural(agentsRunning, "agent"))} running">${icon("agent", 12)}${agentsRunning}</span>` : "";
    if (locked && k !== "settings" && k !== "notes") return `<span class="navi lock" title="Finish the required settings first">${icon(k, 16)}<span class="lbl">${label}</span></span>`;
    return `<a href="#/${k === "overview" ? "" : k}" class="navi ${active === k ? "on" : ""}" ${active === k ? 'aria-current="page"' : ""} title="${esc(label + (combo ? " · " + combo : ""))}">${icon(k, 16)}<span class="lbl">${label}</span>${busy}${n}</a>`;
  };
  patch($("nav"), groups.map(([title, items], gi) => `<div class="navgroup ${gi === groups.length - 1 ? "last" : ""}">${title ? `<div class="navtitle">${title}</div>` : ""}${items.map(navItem).join("")}</div>`).join(""));
  const errs = Object.entries(data).filter(([k]) => k.startsWith("error_"));
  const cu = data.claude_usage || {};
  const usageColor = l => l.severity === "critical" || l.percent >= 95 ? "var(--bad)" : l.severity === "warning" || l.percent >= 80 ? "var(--warn)" : "var(--usage)";
  const usage = (cu.limits || []).map(l => {
    const past = l.resets_at && l.resets_at < now();
    const head = `<div class="mrow"><span>${esc(l.label)}</span><b>${past ? "—" : l.percent + "%"}</b></div><div class="mbar"><span style="width:${past ? 0 : Math.min(100, l.percent)}%;background:${usageColor(l)}"></span></div>`;
    const foot = past ? `<div class="reset" title="Claude Code refreshes these numbers when you open Account & Usage or run /usage">Reset — open /usage to refresh</div>` : l.resets_at ? `<div class="reset" title="${esc(fmtDateTime(l.resets_at))}">Resets in ${dur(Math.max(0, l.resets_at - now()))}</div>` : "";
    return `<div class="meter ${past ? "stale" : ""}">${head}${foot}</div>`;
  }).join("");
  const live = cu.source === "live";
  const stale = cu.fetched && now() - cu.fetched > (live ? 180 : 600) ? `<div class="reset" title="Claude Code refreshes these numbers when you open Account & Usage or run /usage">updated ${ago(cu.fetched)}</div>` : "";
  const liveNote = cu.live_error ? `<div class="reset text-warn" title="${esc(cu.live_error)}">Live usage: ${esc(cu.live_error)}</div>` : "";
  const m = data.mac || {};
  const meter = (label, value, p) => `<div class="meter"><div class="mrow"><span>${label}</span><b>${value}</b></div><div class="mbar"><span style="width:${Math.min(100, p || 0)}%;background:${color(p || 0)}"></span></div></div>`;
  const machine = `${meter("CPU", `${(m.cpu ?? 0).toFixed(0)}%`, m.cpu)}${meter("RAM", `${bytes(m.mem_used)} / ${bytes(m.mem_total, 0)}`, pct(m.mem_used, m.mem_total))}${m.swap_total ? meter("Swap", bytes(m.swap_used), pct(m.swap_used, m.swap_total)) : ""}`;
  patch($("hstats"), `${showUsage() ? `${usage ? `<div class="utitle">Claude usage${live ? `<span class="ulive" title="Updated every minute from Anthropic">live</span>` : ""}</div>${cu.account?.email ? `<div class="uacct" title="${esc([cu.account.email, cu.account.org, cu.account.plan].filter(Boolean).join(" · "))}"><span class="uemail" translate="no">${esc(cu.account.email)}</span>${cu.account.org || cu.account.plan ? `<span class="uorg" translate="no">${esc([cu.account.org, cu.account.plan].filter(Boolean).join(" · "))}</span>` : ""}</div>` : ""}${usage}${stale}${liveNote}` : cu.account?.email ? `<div class="utitle">Claude usage</div><div class="reset" title="Claude Code saves your plan limits when it shows them">Run /usage in Claude Code once to show your limits here</div>${liveNote}` : ""}` : machine}${errs.length ? `<div class="err fs-sm" title="${esc(errs.map(e => e.join(": ")).join("\n"))}">${errs.length} collector error(s)</div>` : ""}${data.version?.update ? `<a class="badge warn" href="#/settings" title="Run opsboard update">${esc(data.version.latest)} available</a>` : ""}`);
  $("ver").textContent = data.version?.current ? "v" + data.version.current : "";
  const pages = { overview: pageOverview, sessions: pageSessions, s: c => pageSession(c, r.arg), docker: pageDocker, postgres: pagePostgres, tasks: pageTasks, mrs: pageMrs, mr: c => pageMr(c, r.arg), worktrees: pageWorktrees, processes: pageProcesses, settings: pageSettings, notes: pageNotes };
  const view = (pages[r.page] || pageOverview)(ctx);
  if (ui.forcePatch || view !== ui.lastView) { ui.lastView = view; patch($("view"), view); }
  ui.forcePatch = false;
  if ((r.page === "notes" || r.page === "overview") && ui.notesFocus) { const f = ui.notesFocus; ui.notesFocus = null; focusNote(f.id, f.at); }
  masonry();
  markScrollers();
  hideEmptyColumns();
  labelDots();
  renderBell();
  syncMrSticky();
  if (r.page === "mr") { mrAfterRender(); fixAfterRender(); }
}

function keepsLocalState(el) {
  if (ui.forcePatch) return false;
  if (el === document.activeElement && (el.isContentEditable || /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName))) return true;
  if (el.tagName === "TEXTAREA" && el.value !== el.defaultValue) return true;
  return el.tagName === "INPUT" && /^(text|password|email|number|search|date)$/.test(el.type) && el.value !== el.defaultValue;
}
function patch(el, html) {
  const next = el.cloneNode(false);
  next.innerHTML = html;
  translateTree(next);
  morphdom(el, next, {
    childrenOnly: true,
    onBeforeElUpdated: (from, to) => {
      if (from.tagName === "DETAILS") to.open = from.open;
      return !keepsLocalState(from) && !from.isEqualNode(to);
    },
  });
}

const DOT_LABEL = { ok: "OK", bad: "Problem", warn: "Needs attention", busy: "Running", cancelled: "Cancelled" };
function labelDots() {
  document.querySelectorAll("#view .dot:not([title])").forEach(d => {
    const k = Object.keys(DOT_LABEL).find(c => d.classList.contains(c));
    if (k) { d.title = t(DOT_LABEL[k]); d.setAttribute("role", "img"); d.setAttribute("aria-label", t(DOT_LABEL[k])); }
  });
}
function hideEmptyColumns() {
  document.querySelectorAll("#view .tbl table").forEach(t => {
    if (t.closest(".area")) return;
    const rows = [...t.tBodies[0]?.rows || []];
    if (!rows.length) return;
    const n = t.tHead?.rows[0]?.cells.length || 0;
    if (!n || rows.some(r => r.cells.length !== n)) return;
    for (let i = 0; i < n; i++) {
      const empty = rows.every(r => !r.cells[i] || ["", "—"].includes(r.cells[i].textContent.trim()));
      [t.tHead.rows[0].cells[i], ...rows.map(r => r.cells[i])].forEach(c => c && (c.hidden = empty));
    }
  });
}
function markScrollers() {
  document.querySelectorAll(".board").forEach(b => b.classList.toggle("scrolls", b.scrollWidth > b.clientWidth + 4 && b.scrollLeft + b.clientWidth < b.scrollWidth - 4));
}
document.addEventListener("scroll", e => { if (e.target.classList?.contains("board")) markScrollers(); }, true);
function masonry() {
  document.querySelectorAll(".cards").forEach(grid => {
    const gap = 14, row = 2;
    grid.querySelectorAll(":scope > .card").forEach(card => {
      card.style.gridRowEnd = "span " + Math.ceil((card.getBoundingClientRect().height + gap) / row);
    });
  });
}
addEventListener("resize", masonry);

async function tick() {
  try {
    data = await (await fetch("/api/state" + (canAlert() ? "?alerts=1" : ""), { cache: "no-store" })).json();
    clockSkew = Date.now() / 1000 - data.now;
    if (await loadLanguage()) { if (ui.translatedStatic) return location.reload(); translateTree(document.body); watchTranslations(); ui.translatedStatic = true; }
    if (!ui.booted) {
      ui.booted = true;
      if (data.config?.["ui.theme"]?.source === "user") applyTheme();
      if (!conf("project.root") && !["settings", "notes"].includes(route().page)) location.hash = "#/settings";
      if (route().page === "settings") loadDoctor();
    }
    render();
  } catch (e) { $("hstats").innerHTML = '<div class="err fs-sm">dashboard server is not running</div>'; }
  setTimeout(tick, 2000);
}

function flushNotes() {
  if (!NOTES.dirty) return;
  clearTimeout(NOTES.saveTimer);
  if (!NOTES.saving) saveNotes();
}
addEventListener("pagehide", () => {
  if (!NOTES.dirty) return;
  fetch("/api/notes", { method: "POST", headers: { "Content-Type": "application/json" }, body: notesPayload(), keepalive: true }).catch(() => {});
});
addEventListener("beforeunload", e => { if (NOTES.dirty || NOTES.saving) { flushNotes(); e.preventDefault(); e.returnValue = ""; } });
addEventListener("hashchange", () => { flushNotes(); if (route().page === "notes") loadNotes(); });
addEventListener("hashchange", () => { scrollTo(0, 0); if (route().page === "settings") { ui.doctor = null; loadDoctor(); } render(); });
document.addEventListener("change", e => {
  if (e.target.dataset?.pref === "notesShowDone") { setPref("notesShowDone", e.target.checked); rerenderNotes(); return; }
  const nf = { noteRange: "range", noteField: "field", noteFrom: "from", noteTo: "to" }[e.target.id];
  if (nf) { setNoteDateFilter({ [nf]: e.target.value }); rerenderNotes(); return; }
  const el = e.target.closest("[data-set-key]");
  if (el) {
    const v = el.dataset.kind === "bool" ? el.checked : el.dataset.kind === "int" ? el.value : el.value.trim();
    saveSetting(el.dataset.setKey, v === "" && el.tagName === "INPUT" ? null : v, "msg-" + el.id);
    return;
  }
  const sm = e.target.closest("[data-status]");
  if (sm) {
    const map = { ...(conf("jira.status_map") || {}) };
    document.querySelectorAll("[data-status]").forEach(s => map[s.dataset.status] = s.value);
    saveSetting("jira.status_map", map, "msg-smap");
  }
});
document.addEventListener("keydown", e => { if (e.key === "Enter" && e.target.matches("input[data-set-key]")) e.target.blur(); });
document.addEventListener("input", e => {
  const t = e.target.closest?.("[data-ntext]");
  if (t) { const it = NOTES.items[noteIndex(t.dataset.ntext)]; if (it) { it.text = t.textContent.replace(/\n/g, " "); scheduleSave(); } return; }
  if (e.target.id === "noteSearch") { ui.noteQuery = e.target.value; rerenderNotes(); setTimeout(() => { const s = $("noteSearch"); if (s) { s.focus(); s.setSelectionRange(s.value.length, s.value.length); } }); }
});
document.addEventListener("keydown", e => {
  const t = e.target.closest?.("[data-ntext]"); if (!t) return;
  const id = t.dataset.ntext, i = noteIndex(id), it = NOTES.items[i]; if (!it) return;
  const text = t.textContent, at = caretOffset(t);
  const vis = t.closest(".ovnotes") ? [...document.querySelectorAll(".ovnotes [data-ntext]")].map(el => NOTES.items[noteIndex(el.dataset.ntext)]).filter(Boolean) : visibleNotes().map(([x]) => x).filter(x => x.kind === "item"), vi = vis.findIndex(x => x.id === id);
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); setNoteTag(it, isDone(it) ? (it.prev_tag || "todo") : "done"); scheduleSave(200); rerenderNotes({ id, at }); return; }
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    if (/^\s*-{3,}\s*$/.test(text)) { NOTES.deleted.add(it.id); NOTES.items.splice(i, 1, { ...newNote(), kind: "divider" }, newNote("", 0)); scheduleSave(200); rerenderNotes({ id: NOTES.items[i + 1].id, at: 0 }); return; }
    it.text = text.slice(0, at);
    const next = newNote(text.slice(at), it.indent);
    NOTES.items.splice(i + 1, 0, next); scheduleSave(200); rerenderNotes({ id: next.id, at: 0 }); return;
  }
  if (e.key === "Tab") { e.preventDefault(); it.indent = Math.max(0, Math.min(4, it.indent + (e.shiftKey ? -1 : 1))); scheduleSave(200); rerenderNotes({ id, at }); return; }
  if (e.key === "Backspace" && at === 0 && !getSelection().toString()) {
    if (it.indent > 0) { e.preventDefault(); it.indent--; scheduleSave(200); rerenderNotes({ id, at: 0 }); return; }
    const prev = vis[vi - 1]; if (!prev) return;
    e.preventDefault();
    const join = prev.text.length; prev.text += text; deleteNoteAt(i);
    scheduleSave(200); rerenderNotes({ id: prev.id, at: join }); return;
  }
  if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
    e.preventDefault(); const j = i + (e.key === "ArrowUp" ? -1 : 1);
    if (j < 0 || j >= NOTES.items.length) return;
    [NOTES.items[i], NOTES.items[j]] = [NOTES.items[j], NOTES.items[i]]; scheduleSave(200); rerenderNotes({ id, at }); return;
  }
  if ((e.key === "ArrowUp" && at === 0) || (e.key === "ArrowDown" && at === text.length)) {
    const other = vis[vi + (e.key === "ArrowUp" ? -1 : 1)]; if (other) { e.preventDefault(); focusNote(other.id, e.key === "ArrowUp" ? "end" : 0); }
  }
});
document.addEventListener("paste", e => {
  const t = e.target.closest?.("[data-ntext]"); if (!t) return;
  const raw = e.clipboardData.getData("text/plain"); const parsed = parseChecklist(raw);
  e.preventDefault();
  if (!parsed) { document.execCommand("insertText", false, raw.replace(/\n/g, " ")); return; }
  const i = noteIndex(t.dataset.ntext), it = NOTES.items[i];
  const base = it.indent;
  parsed.forEach(p => p.indent = Math.min(4, p.indent + base));
  if (!it.text.trim()) { NOTES.deleted.add(it.id); NOTES.items.splice(i, 1, ...parsed); } else NOTES.items.splice(i + 1, 0, ...parsed);
  scheduleSave(200); rerenderNotes({ id: parsed[parsed.length - 1].id, at: "end" });
  notesStatus(`Imported ${parsed.length} lines`, "okmsg");
});
document.addEventListener("input", e => { if (e.target.id === "taskSearch") { ui.taskQuery = e.target.value; render(); } });
document.addEventListener("input", e => { if (e.target.id === "mrSearch") { ui.mrQuery = e.target.value; render(); } });
document.addEventListener("change", e => { if (e.target.id === "mrSort") { e.target.blur(); try { localStorage.setItem("ops.mrSort", e.target.value); } catch (x) {} render(); } });
document.addEventListener("click", e => { const t = e.target.closest("[data-mrtab]"); if (t) { try { localStorage.setItem("ops.mrTab", t.dataset.mrtab); } catch (x) {} render(); } });
document.addEventListener("keydown", e => { if (e.key === "Escape") closeMenu(); });
addEventListener("wheel", e => { if (!e.target.closest("#menu")) closeMenu(); }, { passive: true });
addEventListener("touchmove", closeMenu, { passive: true });
document.addEventListener("click", async e => {
  const mb = e.target.closest("[data-menu]");
  if (mb) { e.preventDefault(); $("menu").hidden || $("menu").dataset.key !== mb.dataset.menu ? (openMenu(mb), $("menu").dataset.key = mb.dataset.menu) : closeMenu(); return; }
  const hrefBtn = e.target.closest("[data-href]");
  if (hrefBtn && !e.target.closest("a")) { e.stopPropagation(); location.hash = hrefBtn.dataset.href; return; }
  if (e.target.closest('[data-act="start-docker"]')) {
    const btn = e.target.closest("[data-act]"); btn.disabled = true; btn.textContent = "Starting…";
    try { await fetch("/api/start-docker", { method: "POST" }); } catch (x) {}
    setTimeout(() => { ui.doctor = null; rerenderSettings(); loadDoctor(); }, 15000);
    return;
  }
  const gb = e.target.closest("[data-goto-btn]") || (!e.target.closest("button") && e.target.closest(".check[data-goto]"));
  if (gb) { e.preventDefault(); gotoSection(gb.dataset.gotoBtn || gb.dataset.goto, gb.dataset.focus); return; }
  const tp = e.target.closest("[data-type-path]");
  if (tp) { const inp = $("f-" + tp.dataset.typePath.replace(/\W/g, "-")); inp.readOnly = false; inp.dataset.typing = "1"; inp.focus(); inp.select(); return; }
  const pk = e.target.closest("[data-pick-btn], input[data-pick]");
  if (pk && !(pk.matches("input") && pk.dataset.typing)) {
    const key = pk.dataset.pickBtn || pk.dataset.pick, id = "f-" + key.replace(/\W/g, "-"), msg = $("msg-" + id);
    if (ui.picking) return;
    ui.picking = true;
    const kind = pk.dataset.pickKind || "folder";
    const PROMPTS = { "project.root": "Choose your project folder", "project.worktrees": "Choose the worktrees folder", "claude.bin": "Choose the claude executable" };
    const start = kind === "file" ? (conf(key) ? conf(key).replace(/\/[^/]*$/, "") : "") : conf(key) || conf("project.root");
    msg.className = "fmsg muted"; msg.textContent = `Choose a ${kind} in the window that opened…`;
    try {
      const r = await (await fetch("/api/pick-folder", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ start, kind, prompt: PROMPTS[key] || `Choose a ${kind}` }) })).json();
      if (r.ok) { $(id).value = r.path; saveSetting(key, r.path, "msg-" + id); }
      else if (r.cancelled) { msg.textContent = ""; }
      else { msg.className = "fmsg err"; msg.textContent = r.error; }
    } catch (x) { msg.className = "fmsg err"; msg.textContent = "Dashboard server is not reachable"; }
    ui.picking = false;
    return;
  }
  const act = e.target.closest("[data-act]");
  if (act) {
    if (act.dataset.act === "doctor") { ui.doctor = null; rerenderSettings(); loadDoctor(); }
    if (act.dataset.act === "detect") {
      act.disabled = true; $("msg-detect").className = "fmsg muted"; $("msg-detect").textContent = "Detecting…";
      const r = await (await fetch("/api/detect", { method: "POST" })).json();
      data = await (await fetch("/api/state")).json(); rerenderSettings(); loadDoctor();
      const m = $("msg-detect"); if (m) { m.className = "fmsg okmsg"; m.textContent = `Detection finished — ${r.changed.length ? "updated: " + r.changed.join(", ") : "nothing changed"}${r.notes.length ? " · " + r.notes.join(" · ") : ""}`; }
    }
    return;
  }
  const rs = e.target.closest("[data-reset], [data-confirm]");
  if (rs) {
    const key = rs.dataset.reset || rs.dataset.confirm;
    saveSetting(key, rs.dataset.reset ? null : conf(key), "msg-f-" + key.replace(/\W/g, "-"));
    return;
  }
  const st = e.target.closest("[data-save-token]");
  if (st) {
    const kind = st.dataset.saveToken, msg = $("msg-tok-" + kind), tok = $("tok-" + kind).value.trim();
    const body = kind === "telegram" ? { token: tok } : kind === "gitlab" ? { token: tok, url: $("f-gitlab-url").value.trim() } : kind === "github" ? { token: tok, url: $("f-github-url").value.trim() } : { token: tok, email: $("f-jira-email").value.trim(), site: $("f-jira-site").value.trim() };
    st.disabled = true; msg.className = "fmsg muted"; msg.textContent = "Checking…";
    const r = await (await fetch(`/api/${kind}-account`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json();
    st.disabled = false;
    if (!r.ok) { msg.className = "fmsg err"; msg.textContent = r.error; return; }
    msg.className = "fmsg okmsg"; msg.textContent = `Connected as ${r.name}`;
    if (kind === "telegram") { ui.tgEdit = false; data = await (await fetch("/api/state")).json(); ui.forcePatch = true; rerenderSettings(); return; }
    setTimeout(async () => { data = await (await fetch("/api/state")).json(); rerenderSettings(); loadDoctor(); }, 1200);
    return;
  }
  if (e.target.closest("[data-copy-setup]")) {
    const msg = $("msg-setup");
    try { await navigator.clipboard.writeText(SETUP_PROMPT); msg.className = "fmsg okmsg"; msg.textContent = t("Copied — paste it into Claude Code"); }
    catch (x) { msg.className = "fmsg err"; msg.textContent = t("Could not copy — select the text and copy it"); }
    return;
  }
  const nt = e.target.closest("[data-ntag]");
  if (nt) { openTagMenu(nt); return; }
  if (e.target.closest("[data-hk-reset]")) { saveSetting("ui.hotkeys", null, "msg-hk"); return; }
  const ts = e.target.closest("[data-ntag-set]");
  if (ts) {
    const it = NOTES.items[noteIndex(ts.dataset.id)], v = ts.dataset.ntagSet;
    setNoteTag(it, v);
    closeMenu(); scheduleSave(200); rerenderNotes(); return;
  }
  const nd = e.target.closest("[data-ndel]");
  if (nd) { closeMenu(); const i = noteIndex(nd.dataset.ndel); if (i >= 0) deleteNoteAt(i); scheduleSave(200); rerenderNotes(); return; }
  const nm = e.target.closest("[data-nmenu]");
  if (nm) { openNoteMenu(nm); return; }
  const nh = e.target.closest("[data-nhist]");
  if (nh) { closeMenu(); showHistory(nh.dataset.nhist); return; }
  if (e.target.closest("[data-ntrash]")) { showTrash(); return; }
  const nr = e.target.closest("[data-nrestore]");
  if (nr) { const it = restoreNote(nr.dataset.nrestore); scheduleSave(200); showTrash(); rerenderNotes(it ? { id: it.id, at: "end" } : null); return; }
  if (e.target.closest("[data-nfilter-clear]")) { setNoteDateFilter({ range: "all", from: "", to: "" }); rerenderNotes(); return; }
  if (e.target.closest("[data-nadd]")) { const n = newNote(); NOTES.items.push(n); scheduleSave(200); rerenderNotes({ id: n.id, at: 0 }); return; }
  const mn = e.target.closest("[data-min]");
  if (mn) { setMin(mn.dataset.min, mn.dataset.on === "1"); closeMenu(); render(); return; }
  const ms = e.target.closest("[data-mark-set]");
  if (ms) {
    const key = ms.dataset.key, color = ms.dataset.markSet || null;
    data.marks = { ...(data.marks || {}) };
    if (color) data.marks[key] = color; else delete data.marks[key];
    closeMenu(); render();
    try { await fetch("/api/task-mark", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key, color }) }); } catch (x) {}
    return;
  }
  if (!e.target.closest("#menu")) closeMenu();
  else if (e.target.closest("[data-fix]")) closeMenu();
  const kb = e.target.closest("[data-bucket]");
  if (kb) { const off = new Set((getPrefRaw("taskOff") ?? "done,cancelled").split(",").filter(Boolean)); off.has(kb.dataset.bucket) ? off.delete(kb.dataset.bucket) : off.add(kb.dataset.bucket); try { localStorage.setItem("ops.taskOff", [...off].join(",")); } catch (x) {} render(); return; }
  const ah = e.target.closest("[data-area]");
  if (ah && !e.target.closest("a")) { const el = ah.parentElement; setAreaOpen(ah.dataset.area, !el.classList.contains("open")); render(); return; }
  const vb = e.target.closest("[data-view]");
  if (vb) { try { localStorage.setItem("ops.taskView", vb.dataset.view); } catch (x) {} render(); return; }
  const ab = e.target.closest("[data-areas]");
  if (ab) { document.querySelectorAll(".area-h[data-area]").forEach(h => setAreaOpen(h.dataset.area, ab.dataset.areas === "open")); render(); return; }
  if (e.target.id === "acctOpen" || e.target.id === "acctOpen2") {
    $("acctEmail").value = data.jira?.account?.email || ""; $("acctToken").value = ""; $("acctMsg").textContent = "";
    $("acct").showModal(); ($("acctEmail").value ? $("acctToken") : $("acctEmail")).focus(); return;
  }
  if (e.target.id === "acctCancel") { $("acct").close(); return; }
  const fb = e.target.closest("[data-fix]");
  if (fb) { openFix(+fb.dataset.fix); return; }
  const sb = e.target.closest("[data-stop]");
  if (sb) {
    if (!confirm(t("Stop this background run? Work it has not committed yet is lost."))) return;
    sb.disabled = true;
    try { await fetch("/api/run-stop", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: sb.dataset.stop }) }); } catch (x) {}
    return;
  }
  if (e.target.closest("#taskRefresh, #taskRefresh2")) {
    ui.refreshing = true; render();
    const before = Math.max(data.jira?.fetched || 0, data.review?.fetched || 0);
    try { await fetch("/api/refresh-tasks", { method: "POST" }); } catch (x) {}
    for (let i = 0; i < 40; i++) { await new Promise(r => setTimeout(r, 500)); const d = await (await fetch("/api/state")).json(); if ((d.gitlab?.fetched || 0) > before) { data = d; break; } }
    ui.refreshing = false; render(); return;
  }
  const ex = e.target.closest("[data-expand]");
  if (ex) { const id = ex.dataset.expand; expanded.has(id) ? expanded.delete(id) : expanded.add(id); render(); }
});
document.addEventListener("toggle", e => { const k = e.target.dataset?.key; if (k) e.target.open ? expanded.add(k) : expanded.delete(k); }, true);
document.addEventListener("change", e => { const k = e.target.dataset?.pref; if (k) { setPref(k, e.target.checked); render(); } });
$("theme").onclick = () => {
  const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const next = cur === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("ops.theme", next); } catch (e) {}
  fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: "ui.theme", value: next }) }).then(() => { if (data?.config) data.config["ui.theme"] = { value: next, source: "user" }; if (route().page === "settings") rerenderSettings(); }).catch(() => {});
};
let fixIid = null;
const FX = ["fxThreads", "fxSkip", "fxConflict", "fxPush"];
function fixOpts() { return { iid: fixIid, threads: $("fxThreads").checked, skiptests: $("fxSkip").checked, conflict: $("fxConflict").checked, push: $("fxPush").checked }; }
async function fixPreview() {
  if ($("fxThreads").checked) $("fxConflict").checked = true;
  $("fxConflict").disabled = $("fxThreads").checked;
  $("fxConflictRow").style.opacity = $("fxThreads").checked ? .6 : 1;
  $("fxConflictHint").textContent = $("fxThreads").checked ? "always on with review threads — the target is merged first" : "only merge the target branch and resolve conflicts (conflict-only)";
  setPref("fixPush", $("fxPush").checked);
  const o = fixOpts();
  $("fixRun").disabled = !(o.threads || o.conflict);
  $("fixMsg").className = "msg warnline";
  $("fixMsg").textContent = !(o.threads || o.conflict) ? "Turn on review threads or merge conflict" : o.push ? "Will push and reply on its own" : "";
  if (!(o.threads || o.conflict)) { $("fixPreview").textContent = "—"; return; }
  try { const r = await (await fetch("/api/fix-preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(o) })).json(); $("fixPreview").textContent = r.prompt || r.error; } catch (x) {}
}
function openFix(iid) {
  const m = (data.review?.mrs || []).find(x => x.iid === iid); if (!m) return;
  fixIid = iid;
  $("fixTitle").textContent = `Run ${conf("claude.fix_skill")} · ${mrRef(iid)}`;
  $("fixSub").textContent = m.title + " — " + [m.conflicts ? "merge conflict" : "", m.threads ? m.threads + " open threads" : ""].filter(Boolean).join(" · ");
  $("fxThreads").checked = !!m.threads || !m.conflicts; $("fxConflict").checked = !!m.conflicts; $("fxSkip").checked = false;
  $("fxPush").checked = getPrefRaw("fixPush") !== "0";
  fixPreview(); $("fix").showModal();
}
FX.forEach(id => $(id).addEventListener("change", fixPreview));
$("fixCancel").onclick = () => $("fix").close();
$("fixForm").addEventListener("submit", async e => {
  e.preventDefault();
  $("fixRun").disabled = true; $("fixMsg").className = "msg muted"; $("fixMsg").textContent = "Starting…";
  try {
    const r = await (await fetch("/api/fix", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(fixOpts()) })).json();
    if (r.ok) { $("fixMsg").className = "msg"; $("fixMsg").style.color = "var(--ok)"; $("fixMsg").textContent = "Started in the background"; setTimeout(() => { $("fix").close(); $("fixMsg").style.color = ""; }, 1200); }
    else { $("fixMsg").className = "msg err"; $("fixMsg").textContent = r.error; $("fixRun").disabled = false; }
  } catch (x) { $("fixMsg").className = "msg err"; $("fixMsg").textContent = "Dashboard server is not reachable"; $("fixRun").disabled = false; }
});
$("acctForm").addEventListener("submit", async e => {
  e.preventDefault();
  $("acctSave").disabled = true; $("acctMsg").className = "msg muted"; $("acctMsg").textContent = "Checking with Jira…";
  try {
    const r = await (await fetch("/api/jira-account", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: $("acctEmail").value, token: $("acctToken").value }) })).json();
    if (r.ok) { $("acctMsg").className = "msg"; $("acctMsg").style.color = "var(--ok)"; $("acctMsg").textContent = `Connected as ${r.name}`; $("acctToken").value = ""; setTimeout(() => $("acct").close(), 900); }
    else { $("acctMsg").className = "msg err"; $("acctMsg").textContent = r.error; }
  } catch (x) { $("acctMsg").className = "msg err"; $("acctMsg").textContent = "Dashboard server is not reachable"; }
  $("acctSave").disabled = false;
});
tick();

$("navToggle").addEventListener("click", () => document.body.classList.toggle("nav-open"));
$("nav").addEventListener("click", e => { if (e.target.closest("a")) document.body.classList.remove("nav-open"); });
$("scrim").addEventListener("click", () => document.body.classList.remove("nav-open"));
