const PAGES = [["overview", "Overview", "g o"], ["sessions", "Sessions", "g s"], ["docker", "Docker", "g d"], ["postgres", "Postgres", "g p"], ["tasks", "Tasks", "g t"], ["mrs", "Merge / pull requests", "g m"], ["worktrees", "Worktrees", "g w"], ["processes", "Processes", "g r"], ["notes", "Notes", "g n"], ["settings", "Settings", "g ,"]];
const CODE_KEYS = { Comma: ",", Period: ".", Slash: "/", Semicolon: ";", Quote: "'", BracketLeft: "[", BracketRight: "]", Backslash: "\\", Minus: "-", Equal: "=", Backquote: "`", Space: "space", Enter: "enter", Escape: "esc" };
function normCombo(s) {
  return String(s || "").trim().toLowerCase().split(/\s+/).filter(Boolean).map(tok => {
    const parts = tok.split("+").filter(Boolean).map(x => ({ option: "alt", opt: "alt", "⌥": "alt", meta: "cmd", command: "cmd", "⌘": "cmd", control: "ctrl", "⌃": "ctrl", "⇧": "shift" }[x] || x));
    const key = parts.pop() || "";
    const mods = ["cmd", "ctrl", "alt", "shift"].filter(m => parts.includes(m));
    return [...mods, key].join("+");
  }).join(" ");
}
function eventToken(e) {
  if (["Shift", "Control", "Alt", "Meta"].includes(e.key)) return null;
  let key = e.code.startsWith("Key") ? e.code.slice(3).toLowerCase() : e.code.startsWith("Digit") ? e.code.slice(5) : CODE_KEYS[e.code] || e.key.toLowerCase();
  if (e.key === "?" ) return "?";
  const mods = [e.metaKey && "cmd", e.ctrlKey && "ctrl", e.altKey && "alt", e.shiftKey && "shift"].filter(Boolean);
  return [...mods, key].join("+");
}
function hotkeys() {
  const custom = conf("ui.hotkeys") || {};
  const named = { tasks: tasksPage(), mrs: mrsPage() };
  return PAGES.map(([page, label, def]) => ({ page, label: named[page] || label, def, combo: normCombo(page in custom ? custom[page] : def) }));
}
const HK = { buffer: [], at: 0 };
function editingTarget(t) { return t && (t.closest?.("input, textarea, select, [contenteditable]") != null); }
document.addEventListener("keydown", e => {
  if (e.target.dataset?.hkRecord) return;
  const tok = eventToken(e); if (!tok) return;
  const typing = editingTarget(e.target);
  if (tok === "?" && !typing) { e.preventDefault(); toggleHotkeyHelp(); return; }
  if (tok === "esc") { const h = $("hkhelp"); if (h && !h.hidden) h.hidden = true; return; }
  const hasMod = /\b(cmd|ctrl|alt)\+/.test(tok);
  if (typing && !hasMod) return;
  const now = Date.now();
  HK.buffer = now - HK.at > 1200 ? [tok] : [...HK.buffer, tok].slice(-3); HK.at = now;
  const seq = HK.buffer.join(" ");
  const hit = hotkeys().find(h => h.combo && (seq === h.combo || seq.endsWith(" " + h.combo)));
  if (hit) {
    e.preventDefault(); HK.buffer = [];
    if (setupMissing().length && !["settings", "notes"].includes(hit.page)) return;
    location.hash = hit.page === "overview" ? "#/" : "#/" + hit.page;
  }
});
const HKREC = { buf: [], at: 0 };
document.addEventListener("keydown", e => {
  const el = e.target.closest?.("[data-hk-record]"); if (!el) return;
  if (e.key === "Tab") return;
  e.preventDefault();
  if (e.key === "Backspace" || e.key === "Delete") { el.value = ""; HKREC.buf = []; return; }
  if (e.key === "Enter") { el.blur(); return; }
  const tok = eventToken(e); if (!tok) return;
  const now = Date.now();
  HKREC.buf = now - HKREC.at > 1200 ? [tok] : [...HKREC.buf, tok].slice(-2); HKREC.at = now;
  el.value = HKREC.buf.join(" ");
});
document.addEventListener("focusout", e => {
  const t = e.target.closest?.("[data-ntext]");
  if (!t) return;
  const i = noteIndex(t.dataset.ntext), it = NOTES.items[i];
  if (!it || it.kind !== "item" || it.text.trim()) return;
  setTimeout(() => {
    if (document.activeElement?.dataset?.ntext === it.id) return;
    const j = noteIndex(it.id); if (j < 0 || NOTES.items[j].text.trim()) return;
    NOTES.items.splice(j, 1); NOTES.deleted.add(it.id);
    const next = e.relatedTarget?.closest?.("[data-ntext]");
    scheduleSave(200); rerenderNotes(next ? { id: next.dataset.ntext, at: "end" } : null);
  }, 0);
});
document.addEventListener("focusout", e => {
  if (!e.target.dataset?.hkRecord) return;
  HKREC.buf = [];
  const map = {};
  document.querySelectorAll("[data-hk-record]").forEach(i => map[i.dataset.hkRecord] = normCombo(i.value));
  const defaults = Object.fromEntries(PAGES.map(([p, , d]) => [p, d]));
  const custom = Object.fromEntries(Object.entries(map).filter(([p, v]) => v !== normCombo(defaults[p])));
  const used = Object.values(map).filter(Boolean);
  const dup = used.filter((v, i) => used.indexOf(v) !== i);
  document.querySelectorAll("[data-hk-record]").forEach(i => i.classList.toggle("missing", dup.includes(normCombo(i.value))));
  if (dup.length) { const m = $("msg-hk"); m.className = "fmsg err"; m.textContent = "Two pages use the same shortcut"; return; }
  if (JSON.stringify(custom) === JSON.stringify(conf("ui.hotkeys") || {})) return;
  saveSetting("ui.hotkeys", custom, "msg-hk");
});
function toggleHotkeyHelp() {
  let box = $("hkhelp");
  if (!box) { box = document.createElement("div"); box.id = "hkhelp"; box.className = "hkhelp"; document.body.appendChild(box); box.addEventListener("click", ev => { if (ev.target === box) box.hidden = true; }); }
  if (!box.hidden && box.innerHTML) { box.hidden = true; return; }
  box.innerHTML = `<div class="hkcard"><div class="hkh"><b>Keyboard shortcuts</b><button class="linkbtn" onclick="this.closest('.hkhelp').hidden=true">Close</button></div>
    ${hotkeys().map(h => `<div class="hkrow"><span>${esc(h.label)}</span><span class="keys">${h.combo ? h.combo.split(" ").map(t => `<kbd>${esc(t)}</kbd>`).join('<span class="then">then</span>') : '<span class="muted">not set</span>'}</span></div>`).join("")}
    <div class="hkrow"><span>This help</span><span class="keys"><kbd>?</kbd></span></div>
    <div class="muted fs-sm mt-2">Change them in Settings → Keyboard shortcuts.</div></div>`;
  box.hidden = false;
}
