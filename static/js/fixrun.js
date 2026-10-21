const RUND = { cache: {}, loading: null, at: {} };

function loadRun(id) {
  if (RUND.loading === id) return;
  RUND.loading = id;
  fetch(`/api/run?id=${encodeURIComponent(id)}`, { cache: "no-store" })
    .then(r => r.json())
    .then(r => { if (r.ok) RUND.cache[id] = r; RUND.at[id] = Date.now(); })
    .catch(() => {})
    .finally(() => { RUND.loading = null; if (route().page === "mr") render(); });
}
const runsFor = iid => (data.runs || []).filter(r => r.iid === iid);
const hms = t => t ? new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) : "";
const PHASE_ICON = { done: ["ok", "ok"], running: ["running", "busy"], pending: ["pending", "muted"], skipped: ["skipped", "muted"], failed: ["fail", "bad"], stopped: ["fail", "bad"] };

function fixTab(iid, d) {
  const runs = runsFor(iid);
  if (!runs.length) return `<div class="empty">No fix runs for this request yet.${canRunFix() ? ` <button class="linkbtn" data-fix="${iid}">Run ${esc(conf("claude.fix_skill"))}</button>` : ""}</div>`;
  const run = runs.find(r => r.id === ui.mrRun) || runs[0];
  const tl = RUND.cache[run.id];
  const stale = !RUND.at[run.id] || (run.status === "running" ? Date.now() - RUND.at[run.id] > 1800 : !tl || tl.run.status !== run.status);
  if (stale) loadRun(run.id);
  const st = { running: ["busy", "Running"], done: ["ok", "Done"], error: ["bad", "Failed"], stopped: ["cancelled", "Stopped"] }[run.status] || ["", run.status];
  const took = run.status === "running" ? dur(now() - run.started) : dur((run.ended || run.started) - run.started);
  const picker = runs.length > 1 ? `<div class="runpick">${runs.slice(0, 8).map(r => `<button class="${r.id === run.id ? "on" : ""}" data-pick-run="${esc(r.id)}"><span class="dot ${({ running: "busy", done: "ok", error: "bad", stopped: "cancelled" })[r.status] || ""}"></span>${r.status === "running" ? "now" : ago(r.ended || r.started)}</button>`).join("")}</div>` : "";
  const head = `<div class="panel runhead"><div class="grow"><div class="runname" translate="no">${esc(run.prompt || run.name)}</div>
      <div class="muted fs-sm"><span class="dot ${st[0]}"></span>${st[1]} · ${took}${run.started ? ` · started ${hms(run.started)}` : ""}${run.cost ? ` · $${(+run.cost).toFixed(2)}` : ""}</div>${outcomeLine(run.outcome)}</div>
      ${run.status === "running" ? `<button class="fixbtn" data-stop="${esc(run.id)}">Stop</button>` : ""}</div>`;
  if (!tl) return picker + head + '<div class="skel skel-block mt-3"></div>';
  const steps = `<ol class="steps">${tl.phases.map(p => {
    const [ic, cls] = PHASE_ICON[p.status] || PHASE_ICON.pending;
    const time = p.start ? dur((p.status === "running" ? now() : p.end || p.start) - p.start) : "";
    return `<li class="step s-${p.status}"><span class="sic ${cls}">${icon(ic, 18)}</span><div class="grow"><div class="sname">${esc(p.label)}</div><div class="snote">${p.note ? esc(p.note) : p.status === "skipped" ? "skipped" : p.status === "pending" ? "waiting" : time}</div></div></li>`;
  }).join("")}</ol>`;
  const threads = d ? threadOrder(d) : [];
  const replied = new Set(tl.replied || []);
  const tState = t => t.resolved && t.resolved_at && t.resolved_at >= run.started - 60 ? ["resolved", "ok", "resolved"] : replied.has(t.id) ? ["replied", "ok", "replied"] : t.resolved ? ["earlier", "muted", "resolved earlier"] : ["open", run.status === "running" ? "busy" : "warn", run.status === "running" ? "working" : "open"];
  const tRows = threads.filter(t => tState(t)[0] !== "earlier");
  const earlier = threads.length - tRows.length;
  const tBox = threads.length ? `<section><h2>Threads<span class="count">${tRows.filter(t => ["resolved", "replied"].includes(tState(t)[0])).length} of ${tRows.length} handled${earlier ? ` · ${earlier} resolved before` : ""}</span></h2><div class="panel list">${tRows.map(t => {
    const [, cls, label] = tState(t), first = t.notes[0] || {};
    return `<a class="item trow" href="#" data-run-thread="${esc(t.id)}"><span class="dot ${cls}"></span><div class="grow"><div class="t" translate="no">${esc(t.path ? `${t.path.split("/").pop()}:${t.new_line || t.old_line || ""}` : "General thread")}</div><div class="s">${esc(first.author || "")}: ${esc(String(first.body || "").replace(/\s+/g, " ").slice(0, 120))}</div></div><span class="tstate ${cls}">${label}</span></a>`;
  }).join("") || '<div class="empty">All threads were resolved before this run.</div>'}</div></section>` : "";
  const showReads = getPref("runReads");
  const feedItems = tl.events.filter(e => showReads || !(e.kind === "tool" && ["Read", "Grep", "Glob"].includes(e.tool)));
  const feed = feedItems.map((e, i) => {
    const t = `<span class="ft">${hms(e.at)}</span>`;
    if (e.kind === "say") return `<div class="fe f-say">${t}<span class="fic">${icon("comment", 14)}</span><div class="grow md">${md(e.text)}</div></div>`;
    if (e.kind === "note") return `<div class="fe f-note">${t}<span class="fic">${icon("pending", 14)}</span><div class="grow muted">${esc(e.text)}</div></div>`;
    if (e.kind === "result") return `<div class="fe f-result">${t}<span class="fic ${e.error ? "bad" : "ok"}">${icon(e.error ? "fail" : "ok", 14)}</span><div class="grow"><b>${e.error ? "Turn ended with an error" : "Turn finished"}</b></div></div>`;
    const sym = e.tool === "Bash" ? "$" : ["Edit", "Write", "MultiEdit", "NotebookEdit"].includes(e.tool) ? "✎" : ["Read", "Grep", "Glob"].includes(e.tool) ? "◦" : "•";
    const pill = e.status === "running" ? `<span class="fpill run">${icon("running", 12)}running</span>` : e.status === "background" ? '<span class="fpill">background</span>' : e.status === "failed" ? '<span class="fpill bad">failed</span>' : "";
    const phase = e.phase ? `<span class="fphase">${esc((tl.phases.find(p => p.key === e.phase) || {}).label || e.phase)}</span>` : "";
    const body = e.cmd ? `<details class="fcmd"><summary><span translate="no">${esc(e.text || e.cmd.split("\n")[0])}</span></summary><pre>${esc(e.cmd)}</pre></details>` : `<span class="ftext" translate="no">${esc(e.text)}</span>`;
    return `<div class="fe f-tool t-${esc(e.tool)}">${t}<span class="fic sym">${sym}</span><div class="grow">${body}</div>${phase}${pill}</div>`;
  }).join("");
  return picker + head + `<div class="runlayout"><div class="runmain">${steps}${tBox}</div>
    <section class="runfeed"><h2>Live<span class="count">${feedItems.length} events</span><span class="h2-actions"><label class="minisw m-0"><input type="checkbox" data-pref="runReads" ${showReads ? "checked" : ""}><span class="tog"></span>show reads</label></span></h2>
      <div class="panel feed" id="runFeed">${feed || '<div class="empty">Waiting for the first step…</div>'}</div></section></div>`;
}

let feedPinned = true;
document.addEventListener("scroll", e => { if (e.target.id === "runFeed") feedPinned = e.target.scrollTop + e.target.clientHeight >= e.target.scrollHeight - 24; }, true);
function fixAfterRender() { const f = $("runFeed"); if (f && feedPinned) f.scrollTop = f.scrollHeight; }
document.addEventListener("click", e => {
  const or = e.target.closest("[data-open-run]");
  if (or) { ui.mrRun = or.dataset.openRun; feedPinned = true; }
  const pr = e.target.closest("[data-pick-run]");
  if (pr) { ui.mrRun = pr.dataset.pickRun; feedPinned = true; render(); return; }
  const rt = e.target.closest("[data-run-thread]");
  if (rt) { e.preventDefault(); ui.mrFocus = { iid: parseInt(route().arg, 10), tid: rt.dataset.runThread }; location.hash = `#/mr/${route().arg}/overview`; }
});
document.addEventListener("change", e => { if (e.target.dataset?.pref === "runReads") { setPref("runReads", e.target.checked); render(); } });
