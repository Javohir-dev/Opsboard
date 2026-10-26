const NOTES = { version: 0, items: [], trash: [], loaded: false, saveTimer: null, saving: false, dirty: false, deleted: new Set() };
const nid = () => Math.random().toString(36).slice(2, 12);
const isDone = it => it.tag === "done";
const nowS = () => Date.now() / 1000;
function normalizeNotes(items) {
  return (items || []).map(i => {
    const n = i.kind === "item" && i.done && i.tag !== "done" ? { ...i, tag: "done" } : { ...i };
    if (n.kind === "item") {
      if (!Array.isArray(n.history) || !n.history.length) n.history = [{ t: n.created || nowS(), type: "created", from: "", to: n.text || "" }];
      if (n.last_text == null) n.last_text = n.text || "";
      if (!n.updated) n.updated = n.created;
    }
    return n;
  });
}
function noteEvent(it, type, from = "", to = "") {
  if (!it.history) it.history = [];
  it.history.push({ t: nowS(), type, from, to });
  if (it.history.length > 200) it.history.splice(0, it.history.length - 200);
  it.updated = nowS();
}
function recordTextChanges() {
  const t = nowS();
  NOTES.items.forEach(it => {
    if (it.kind !== "item" || it.text === it.last_text) return;
    const h = it.history || (it.history = []), last = h[h.length - 1];
    if (h.length === 1 && ["created", "imported"].includes(h[0].type) && t - h[0].t < 120) h[0].to = it.text;
    else if (last && last.type === "text" && t - last.t < 120) { last.to = it.text; last.t = t; }
    else h.push({ t, type: "text", from: it.last_text || "", to: it.text });
    it.last_text = it.text; it.updated = t;
  });
}
async function loadNotes() {
  if (NOTES.dirty || NOTES.saving) return;
  try {
    const d = await (await fetch("/api/notes", { cache: "no-store" })).json();
    if (NOTES.dirty || NOTES.saving) return;
    NOTES.version = d.version || 0; NOTES.items = normalizeNotes(d.items); NOTES.trash = normalizeNotes(d.trash); NOTES.loaded = true;
    const before = NOTES.items.length;
    NOTES.items = NOTES.items.filter(i => i.kind !== "item" || i.text.trim());
    if (NOTES.items.length !== before) scheduleSave(300);
  } catch (e) {}
  NOTES.fetched = Date.now();
  render();
}
function editingOverviewNote() { return route().page === "overview" && !!document.activeElement?.closest?.(".ovnotes [data-ntext]"); }
function setNoteTag(it, tag) {
  if ((it.tag || "") === tag) return;
  if (tag === "done") { it.prev_tag = it.tag; it.done_at = nowS(); } else it.done_at = 0;
  noteEvent(it, "tag", it.tag || "", tag);
  it.tag = tag; it.done = tag === "done";
}
function deleteNoteAt(i) {
  const [gone] = NOTES.items.splice(i, 1); if (!gone) return;
  NOTES.deleted.add(gone.id);
  if (gone.kind !== "item" || (!gone.text.trim() && (gone.history || []).length <= 1)) return;
  noteEvent(gone, "deleted", "", gone.text); gone.deleted_at = nowS();
  NOTES.trash.unshift(gone); NOTES.trash.length = Math.min(NOTES.trash.length, 300);
}
function restoreNote(id) {
  const j = NOTES.trash.findIndex(i => i.id === id); if (j < 0) return null;
  const [it] = NOTES.trash.splice(j, 1);
  it.deleted_at = 0; noteEvent(it, "restored", "", it.text); NOTES.deleted.delete(it.id);
  NOTES.items.push(it); return it;
}
function notesPayload() {
  recordTextChanges();
  return JSON.stringify({ version: NOTES.version, items: NOTES.items.map(i => ({ ...i, done: isDone(i) })), trash: NOTES.trash });
}
function rerenderNotes(focus) { ui.notesFocus = focus || null; ui.forcePatch = !!focus; render(); }
function notesStatus(text, cls = "muted") { const el = $("notes-status"); if (el) { el.className = cls; el.textContent = text; } }
function scheduleSave(delay = 600) {
  NOTES.dirty = true; notesStatus("Saving…");
  clearTimeout(NOTES.saveTimer); NOTES.saveTimer = setTimeout(saveNotes, delay);
}
async function saveNotes() {
  if (NOTES.saving) { scheduleSave(300); return; }
  NOTES.saving = true; NOTES.dirty = false;
  try {
    const r = await (await fetch("/api/notes", { method: "POST", headers: { "Content-Type": "application/json" }, body: notesPayload() })).json();
    if (r.ok) { NOTES.version = r.version; notesStatus("Saved", "okmsg"); }
    else if (r.conflict) {
      const ids = new Set(NOTES.items.map(i => i.id));
      const extra = normalizeNotes(r.notes.items).filter(i => !ids.has(i.id) && !NOTES.deleted.has(i.id));
      NOTES.items = [...NOTES.items, ...extra]; NOTES.version = r.notes.version;
      const tids = new Set(NOTES.trash.map(i => i.id));
      NOTES.trash = [...NOTES.trash, ...normalizeNotes(r.notes.trash).filter(i => !tids.has(i.id) && !ids.has(i.id))];
      notesStatus(extra.length ? `Merged ${extra.length} line(s) from another tab` : "Saved", "warnline");
      if (extra.length) rerenderNotes();
      NOTES.saving = false; scheduleSave(50); return;
    }
    else notesStatus(r.error || "Could not save", "err");
  } catch (e) { notesStatus("Dashboard server is not reachable — not saved", "err"); NOTES.dirty = true; }
  NOTES.saving = false;
}
function noteKeys(text) {
  const projects = (conf("jira.projects") || []).filter(p => /^[A-Z][A-Z0-9]{1,9}$/.test(p));
  if (!projects.length) return [];
  const rx = new RegExp("\\b((?:" + projects.join("|") + ")-\\d+)\\b", "g");
  return [...new Set(text.match(rx) || [])];
}
function noteKeyChip(key) {
  const alias = data.key_aliases || {}, k = alias[key] || key;
  const issue = (data.jira?.issues || []).find(i => i.key === k);
  const bucket = issue ? (statusMap()[issue.status] || (issue.category === "done" ? "done" : "todo")) : null;
  const col = bucket ? BUCKET[bucket][2] : "var(--muted)";
  return `<a class="nkey" href="${jiraLink(k)}" target="_blank" title="${esc(issue ? issue.summary + " — " + issue.status : k)}"><span class="dot" style="background:${col}"></span>${esc(k)}${issue ? `<span class="muted">${esc(issue.status)}</span>` : ""}</a>`;
}
function noteDate(t) { const d = new Date(t * 1000); return d.toLocaleDateString([], { day: "2-digit", month: "short", year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric" }); }
function noteDateFilter() {
  const f = ui.noteDate || (ui.noteDate = (() => { try { return JSON.parse(localStorage.getItem("ops.noteDate") || "null"); } catch (e) { return null; } })() || { range: "all", field: "created", from: "", to: "" });
  return f;
}
function setNoteDateFilter(patch) {
  Object.assign(noteDateFilter(), patch);
  try { localStorage.setItem("ops.noteDate", JSON.stringify(ui.noteDate)); } catch (e) {}
}
function dateBounds(f) {
  const day = d => { const x = new Date(d); x.setHours(0, 0, 0, 0); return x.getTime() / 1000; };
  const today = day(Date.now());
  switch (f.range) {
    case "today": return [today, today + 86400];
    case "yesterday": return [today - 86400, today];
    case "7d": return [today - 6 * 86400, today + 86400];
    case "30d": return [today - 29 * 86400, today + 86400];
    case "custom": return [f.from ? day(f.from + "T00:00") : -Infinity, f.to ? day(f.to + "T00:00") + 86400 : Infinity];
    default: return null;
  }
}
function visibleNotes() {
  const q = (ui.noteQuery || "").toLowerCase(), showDone = getPref("notesShowDone");
  const f = noteDateFilter(), b = dateBounds(f), field = f.field === "updated" ? "updated" : "created";
  const out = [];
  NOTES.items.forEach((it, i) => {
    if (it.kind === "divider") { if (!q && !b) out.push([it, i]); return; }
    if (!showDone && isDone(it)) return;
    if (q && !it.text.toLowerCase().includes(q)) return;
    if (b) { const v = it[field] || it.created; if (v < b[0] || v >= b[1]) return; }
    out.push([it, i]);
  });
  return out.filter(([it], j, arr) => it.kind !== "divider" || (j > 0 && arr[j - 1][0].kind !== "divider"));
}
function pageNotes() {
  if (!NOTES.loaded) { loadNotes(); return '<div class="pagehead"><h1>ToDo</h1></div><div class="muted">Loading…</div>'; }
  const rows = visibleNotes();
  const open = NOTES.items.filter(i => i.kind === "item" && !isDone(i)).length, done = NOTES.items.filter(i => i.kind === "item" && isDone(i)).length;
  const hiddenDone = !getPref("notesShowDone") && done;
  return `<div class="pagehead"><h1>ToDo</h1><span class="sub">${open} open · ${done} done</span><span id="notes-status" class="muted ml-auto fs-sm"></span></div>
    <div class="toolbar"><input class="search" id="noteSearch" placeholder="Search notes" value="${esc(ui.noteQuery || "")}">
      ${(() => {
        const f = noteDateFilter();
        const opts = [["all", "All time"], ["today", "Today"], ["yesterday", "Yesterday"], ["7d", "Last 7 days"], ["30d", "Last 30 days"], ["custom", "Custom range…"]];
        return `<span class="datef"><select id="noteRange">${opts.map(([v, l]) => `<option value="${v}" ${f.range === v ? "selected" : ""}>${l}</option>`).join("")}</select>
          ${f.range !== "all" ? `<select id="noteField"><option value="created" ${f.field !== "updated" ? "selected" : ""}>created</option><option value="updated" ${f.field === "updated" ? "selected" : ""}>changed</option></select>` : ""}
          ${f.range === "custom" ? `<input type="date" id="noteFrom" value="${esc(f.from)}"><span class="muted">–</span><input type="date" id="noteTo" value="${esc(f.to)}">` : ""}
          ${f.range !== "all" ? `<button class="linkbtn" data-nfilter-clear="1">Clear</button>` : ""}</span>`;
      })()}
      ${finishedToggle("notesShowDone").replace("show done &amp; cancelled", "show done").replace("show done & cancelled", "show done").replace('margin-left: auto', '')}
      <button class="linkbtn ml-auto" data-ntrash="1">Deleted${NOTES.trash.length ? ` (${NOTES.trash.length})` : ""}</button>
      <span class="muted fs-sm" title="Enter new line · Tab indent · ⌘Enter done · --- divider · paste a Notion checklist to import">Shortcuts ${icon("info", 14)}</span></div>
    <div class="panel notes" id="notes">
      ${rows.map(([it]) => it.kind === "divider"
        ? `<div class="nrow ndiv" data-id="${it.id}"><hr><button class="nx" data-ndel="${it.id}" title="Remove divider" aria-label="Remove divider">${icon("x", 14)}</button></div>`
        : `<div class="nrow ${isDone(it) ? "done" : ""}" data-id="${it.id}" style="--ind:${it.indent}">
            <button class="ntag ${it.tag ? "t-" + it.tag : "t-none"}" data-ntag="${it.id}" title="Choose a tag">${{ todo: "ToDo", warn: icon("warning", 14), done: "Done" }[it.tag] || "+"}<span class="caret">▾</span></button>
            <div class="ntext" contenteditable="plaintext-only" spellcheck="false" data-ntext="${it.id}">${esc(it.text)}</div>
            <span class="nmeta">${noteKeys(it.text).map(noteKeyChip).join("")}<span class="ndate" title="Created ${esc(fmtDateTime(it.created))}${it.updated && it.updated - it.created > 60 ? " · changed " + esc(fmtDateTime(it.updated)) : ""}">${noteDate(it.created)}</span><button class="kebab nkebab" data-nmenu="${it.id}" title="More" aria-label="More actions">${icon("more", 16)}</button></span>
          </div>`).join("")}
      <button class="nadd" data-nadd="1">+ New note</button>
    </div>
    ${hiddenDone ? `<div class="muted mt-2 fs-sm">${done} done hidden — turn on “show done” to see them.</div>` : ""}`;
}
function fmtDateTime(t) { return new Date(t * 1000).toLocaleString([], { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }); }
const TAG_LABEL = { "": "None", todo: "ToDo", warn: "Warning", done: "Done" };
const tagChip = v => `<span class="ntag ntag-inline t-${v || "none"}">${TAG_LABEL[v] || v}</span>`;
function openNoteMenu(btn) {
  const id = btn.dataset.nmenu, menu = $("menu");
  menu.innerHTML = `<button class="mi" data-nhist="${id}">${icon("history", 15)}Show history</button><hr><button class="mi text-bad" data-ndel="${id}">${icon("trash", 15)}Delete</button>`;
  menu.dataset.key = "nmenu:" + id; menu.hidden = false;
  const r = btn.getBoundingClientRect(), h = menu.offsetHeight;
  menu.style.left = Math.max(8, Math.min(innerWidth - menu.offsetWidth - 8, r.right - menu.offsetWidth)) + "px";
  menu.style.top = (r.bottom + h + 8 > innerHeight ? r.top - h - 4 : r.bottom + 4) + "px";
}
function historyHtml(it) {
  const rows = (it.history || []).slice().reverse().map(h => {
    let what;
    if (h.type === "created" || h.type === "imported") what = `<b>${h.type === "imported" ? "Imported" : "Created"}</b>${h.to ? `<div class="hval">${esc(h.to)}</div>` : ""}`;
    else if (h.type === "tag") what = `<b>Tag</b> ${tagChip(h.from)} → ${tagChip(h.to)}`;
    else if (h.type === "text") what = `<b>Text changed</b><div class="hval old">${esc(h.from) || "<i>empty</i>"}</div><div class="hval new">${esc(h.to) || "<i>empty</i>"}</div>`;
    else if (h.type === "deleted") what = `<b class="text-bad">Deleted</b>`;
    else if (h.type === "restored") what = `<b class="text-ok">Restored</b>`;
    else what = esc(h.type);
    return `<div class="hrow"><span class="htime">${esc(fmtDateTime(h.t))}</span><div class="hwhat">${what}</div></div>`;
  }).join("");
  return `<div class="hhead"><div class="hcur">${esc(it.text) || "<i>empty</i>"}</div><div class="muted fs-sm">Created ${esc(fmtDateTime(it.created))} · ${(it.history || []).length} change(s)${it.deleted_at ? ` · deleted ${esc(fmtDateTime(it.deleted_at))}` : ""}</div></div><div class="hlist">${rows || '<div class="muted">No history.</div>'}</div>`;
}
function showNoteDialog(title, body) {
  $("nhistTitle").textContent = title; $("nhistBody").innerHTML = body;
  if (!$("nhist").open) $("nhist").showModal();
}
function showHistory(id) {
  recordTextChanges();
  const it = NOTES.items.find(i => i.id === id) || NOTES.trash.find(i => i.id === id); if (!it) return;
  showNoteDialog("History", historyHtml(it));
}
function showTrash() {
  const rows = NOTES.trash.map(it => `<div class="trow"><div class="ttext">${esc(it.text) || "<i>empty</i>"}<div class="muted fs-sm">deleted ${esc(fmtDateTime(it.deleted_at))} · created ${esc(fmtDateTime(it.created))}</div></div><button class="linkbtn" data-nhist="${it.id}">History</button><button class="fixbtn" data-nrestore="${it.id}">Restore</button></div>`).join("");
  showNoteDialog(`Deleted notes (${NOTES.trash.length})`, rows || '<div class="muted">Nothing deleted.</div>');
}
function openTagMenu(btn) {
  const it = NOTES.items[noteIndex(btn.dataset.ntag)]; if (!it) return;
  const cur = it.tag || "";
  const opt = (v, label, cls) => `<button class="mi" data-ntag-set="${v}" data-id="${it.id}"><span class="ntag ${cls} ntag-static">${label}</span>${cur === v ? '<span class="check-on">✓</span>' : ""}</button>`;
  const menu = $("menu");
  menu.innerHTML = `<div class="mh">Tag</div>${opt("todo", "ToDo", "t-todo")}${opt("warn", `${icon("warning", 13)} Warning`, "t-warn")}${opt("done", "Done", "t-done")}<hr>${opt("", "None", "t-none")}`;
  menu.dataset.key = "tag:" + it.id;
  menu.hidden = false;
  const r = btn.getBoundingClientRect(), h = menu.offsetHeight;
  menu.style.left = Math.max(8, Math.min(innerWidth - menu.offsetWidth - 8, r.left)) + "px";
  menu.style.top = (r.bottom + h + 8 > innerHeight ? r.top - h - 4 : r.bottom + 4) + "px";
}
function noteIndex(id) { return NOTES.items.findIndex(i => i.id === id); }
function focusNote(id, at) {
  const el = document.querySelector(`[data-ntext="${id}"]`); if (!el) return;
  el.focus();
  const sel = getSelection(), r = document.createRange(), node = el.firstChild || el;
  const len = (el.textContent || "").length, pos = at === "end" || at == null ? len : Math.min(at, len);
  try { r.setStart(node, node.nodeType === 3 ? pos : 0); r.collapse(true); sel.removeAllRanges(); sel.addRange(r); } catch (e) {}
}
function caretOffset(el) {
  const sel = getSelection(); if (!sel.rangeCount) return 0;
  const r = sel.getRangeAt(0).cloneRange(); r.selectNodeContents(el); r.setEnd(sel.getRangeAt(0).endContainer, sel.getRangeAt(0).endOffset);
  return r.toString().length;
}
function newNote(text = "", indent = 0, extra = {}) {
  const t = nowS();
  return { id: nid(), kind: "item", text, done: false, tag: "todo", indent, created: t, updated: t, done_at: 0, last_text: text, history: [{ t, type: extra.imported ? "imported" : "created", from: "", to: text }], ...extra };
}
function parseChecklist(text) {
  const lines = text.replace(/\r/g, "").split("\n").filter(l => l.trim());
  if (lines.length < 2 && !/^\s*[-*]\s*\[[ xX]\]/.test(lines[0] || "")) return null;
  const leads = lines.map(l => l.match(/^\s*/)[0].replace(/\t/g, "    ").length);
  const base = Math.min(...leads);
  const unit = Math.min(...leads.map(x => x - base).filter(x => x > 0), 99) === 99 ? 2 : Math.min(...leads.map(x => x - base).filter(x => x > 0));
  return lines.map((l, idx) => {
    const lead = Math.round((leads[idx] - base) / unit) * 2;
    let s = l.trim();
    if (/^(-{3,}|\*{3,})$/.test(s)) return { id: nid(), kind: "divider", text: "", done: false, tag: "", indent: 0, created: Date.now() / 1000, done_at: 0 };
    const m = s.match(/^[-*+]\s*\[([ xX])\]\s*(.*)$/) || s.match(/^[-*+]\s+(.*)$/);
    let done = false;
    if (m && m.length === 3) { done = m[1].toLowerCase() === "x"; s = m[2]; } else if (m) s = m[1];
    let tag = "";
    const t = s.match(/^\[\s*(todo|done|⚠️?)\s*\]\s*-?\s*/i);
    if (t) { tag = /⚠/.test(t[1]) ? "warn" : "todo"; if (/done/i.test(t[1])) done = true; s = s.slice(t[0].length); }
    return newNote(s, Math.min(4, Math.round(lead / 2)), { done, tag: done ? "done" : tag, done_at: done ? Date.now() / 1000 : 0, imported: true });
  });
}
