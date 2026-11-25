const ASSIST = { open: false, items: [], total: 0, at: 0, loading: false, msg: "", sending: false };

function assistKey() { try { return localStorage.getItem("ops.assist") || ""; } catch (e) { return ""; } }
function setAssistKey(v) { try { v ? localStorage.setItem("ops.assist", v) : localStorage.removeItem("ops.assist"); } catch (e) {} }
function assistSession() { const k = assistKey(); return k ? (data?.cockpit || []).find(c => c.key === k || c.sid === k) : null; }

function pageContext() {
  const r = route(), view = $("view");
  const title = view?.querySelector("h1")?.textContent.trim() || r.page;
  const text = (view?.innerText || "").replace(/\n{3,}/g, "\n\n").slice(0, 2500);
  return `<ops-context>\nOpsboard page: ${location.hash || "#/"} — ${title}\nVisible on it:\n${text}\n</ops-context>\n`;
}

function assistBody() {
  const s = assistSession();
  const items = ASSIST.items.map((it, n) => xItem(it, `as:${ASSIST.total - ASSIST.items.length + n}`)).join("");
  const waits = s?.sid ? waitList().filter(w => w.sid === s.sid).map(waitCard).join("") : "";
  const working = s?.busy ? `<div class="asworking"><span class="dot busy"></span>Working…</div>` : "";
  const empty = !items && !working ? `<div class="asempty">Ask about what is on this page, or tell me what to do. I can also pass work to another Claude session.</div>` : "";
  return `${empty}${items}${waits}${working}${s && !s.alive && s.error ? `<div class="fmsg err">${esc(s.error)}</div>` : ""}`;
}

function renderAssist() {
  const box = $("assist");
  if (!box) return;
  const waitN = (data?.claude_wait || []).filter(w => w.sid && w.sid === assistSession()?.sid).length;
  $("assistBtn").classList.toggle("has", !!waitN);
  box.hidden = !ASSIST.open;
  $("assistBtn").setAttribute("aria-expanded", ASSIST.open);
  if (!ASSIST.open) return;
  const s = assistSession();
  if (s?.sid && (Date.now() - ASSIST.at > 1500) && !ASSIST.loading) assistLoad(s.sid);
  const list = $("assistList");
  const near = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
  patch(list, assistBody());
  if (near) list.scrollTop = list.scrollHeight;
  $("assistMsg").textContent = ASSIST.msg;
}

async function assistLoad(sid) {
  ASSIST.loading = true;
  try {
    const r = await (await fetch("/api/session-chat?id=" + encodeURIComponent(sid), { cache: "no-store" })).json();
    if (r.ok) { ASSIST.items = r.items; ASSIST.total = r.total; }
  } catch (x) {}
  ASSIST.loading = false; ASSIST.at = Date.now();
  renderAssist();
}

async function assistSend() {
  const ta = $("assistInput"), text = ta.value.trim();
  if (!text || ASSIST.sending) return;
  ASSIST.sending = true; ASSIST.msg = "Sending…"; renderAssist();
  const s = assistSession();
  const live = s && s.alive;
  try {
    const r = await (await fetch("/api/cockpit/" + (live ? "send" : "new"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(live ? { id: s.sid || s.key, text: pageContext() + text } : { text: pageContext() + text, assistant: true }) })).json();
    if (!r.ok) throw new Error(r.error || "Failed");
    if (!live) { setAssistKey(r.session.key); ASSIST.items = []; }
    ta.value = ""; ASSIST.msg = "";
    ASSIST.items.push({ kind: "user", text });
    data = await (await fetch("/api/state", { cache: "no-store" })).json();
  } catch (x) { ASSIST.msg = x.message; }
  ASSIST.sending = false; ASSIST.at = 0; renderAssist();
  const list = $("assistList"); list.scrollTop = list.scrollHeight;
}

$("assistBtn").addEventListener("click", () => { ASSIST.open = !ASSIST.open; renderAssist(); if (ASSIST.open) setTimeout(() => $("assistInput").focus(), 50); });
$("assistClose").addEventListener("click", () => { ASSIST.open = false; renderAssist(); });
$("assistNew").addEventListener("click", async () => {
  const s = assistSession();
  if (s?.alive) { try { await fetch("/api/cockpit/stop", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: s.sid || s.key, close: true }) }); } catch (x) {} }
  setAssistKey(""); ASSIST.items = []; ASSIST.msg = ""; renderAssist(); $("assistInput").focus();
});
$("assistForm").addEventListener("submit", e => { e.preventDefault(); assistSend(); });
$("assistInput").addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); assistSend(); } });
document.addEventListener("keydown", e => { if (e.key === "Escape" && ASSIST.open && e.target.closest?.("#assist")) { ASSIST.open = false; renderAssist(); $("assistBtn").focus(); } });
setInterval(() => { if (data) renderAssist(); }, 1000);
