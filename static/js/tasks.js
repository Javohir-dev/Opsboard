const BUCKETS = [
  ["discuss", "Discussion / on hold", "var(--warn)"],
  ["todo", "To do", "var(--muted)"],
  ["doing", "In progress", "var(--busy)"],
  ["review", "In review", "var(--accent)"],
  ["staging", "Staging", "#2bb3a3"],
  ["done", "Done", "var(--ok)"],
  ["cancelled", "Cancelled", "#e07a3a"],
];
const BUCKET = Object.fromEntries(BUCKETS.map(b => [b[0], b]));

const prof = key => key.split(".").reduce((v, k) => v?.[k], data?.profile);
const statusMap = () => ({ ...(prof("tasks.status_map") || {}), ...(conf("jira.status_map") || {}) });
const areaLabels = () => prof("tasks.areas.labels") || {};
const planCfg = () => prof("tasks.areas.plan");
const isPlanArea = area => !!planCfg() && String(area).startsWith(planCfg().area_prefix);
function areaOf(summary) {
  const a = prof("tasks.areas") || {};
  for (const p of a.title_patterns || []) { const m = summary.match(new RegExp(p)); if (m) return m[1]; }
  for (const [text, area] of a.title_areas || []) if (summary.includes(text)) return area;
  for (const [src, flags, area] of a.keywords || []) if (new RegExp(src, flags).test(summary)) return area;
  return "";
}

function cleanTitle(t) {
  let out = t.replace(/^\s*(draft:\s*)?/i, "").replace(/^\(?[A-Z][A-Z0-9]{1,9}-\d+\)?\s*[-:–—]?\s*/, "").replace(/^(draft:\s*)/i, "").replace(/^(feat|fix|chore|refactor|perf)\(([a-z0-9_]+)\):\s*/i, "").replace(/^[a-z][a-z0-9_]+(\(\d+\))?:\s*/, "");
  for (const p of prof("tasks.clean_title") || []) out = out.replace(new RegExp(p), "");
  return out;
}
function buildTasks(ctx) {
  const jira = data.jira || {}, gl = data.review || {};
  const mrsByKey = {};
  const alias = data.key_aliases || {};
  (gl.mrs || []).forEach(m => m.keys.forEach(k => (mrsByKey[alias[k] || k] ||= []).push(m)));
  Object.values(mrsByKey).forEach(list => list.sort((a, b) => (b.state === "opened") - (a.state === "opened") || b.updated - a.updated));
  const issues = jira.issues || [];
  const base = issues.length ? issues : Object.entries(mrsByKey).map(([key, list]) => ({ key, summary: cleanTitle(list[0].title), status: "", updated: list[0].updated, fromMr: true }));
  const byBranch = {};
  ctx.sessions.forEach(s => s.uWorktrees.forEach(w => { const wt = ctx.wts[w.name]; if (wt) (byBranch[wt.branch] ||= new Set()).add(s); }));
  const out = base.map(it => {
    const mrs = mrsByKey[it.key] || [];
    const mr = mrs[0];
    let bucket = statusMap()[it.status];
    if (!bucket) bucket = it.fromMr ? (mr.state === "merged" ? "done" : mr.state === "closed" ? "cancelled" : "review") : it.category === "done" ? "done" : it.category === "indeterminate" ? "doing" : "todo";
    const planRx = planCfg()?.title_regex;
    const plan = mrs.find(m => m.plan != null)?.plan ?? ((planRx && +((it.summary.match(new RegExp(planRx)) || [])[1])) || null);
    const area = mrs.find(m => m.module)?.module || areaOf(it.summary) || "other";
    const sessions = new Set();
    mrs.forEach(m => (byBranch[m.source] || []).forEach(s => sessions.add(s)));
    ctx.sessions.forEach(s => { if ((s.prompts || []).slice(0, 15).some(p => p.text.includes(it.key) || mrs.some(m => m.state === "opened" && new RegExp("\\b" + m.iid + "\\b").test(p.text)))) sessions.add(s); });
    const issuesOf = [];
    if (mr && mr.state === "opened") {
      if (mr.conflicts) issuesOf.push(["bad", "merge conflict"]);
      if (mr.threads) issuesOf.push(["warn", `${mr.threads} open thread${mr.threads > 1 ? "s" : ""}`]);
      if (mr.draft) issuesOf.push(["warn", "draft"]);
    }
    if (issues.length && mr && mr.state === "merged" && !["done", "staging", "cancelled"].includes(bucket)) issuesOf.push(["warn", `MR merged, Jira still «${it.status}»`]);
    if (issues.length && bucket === "doing" && !mrs.some(m => m.state === "opened") && !sessions.size) issuesOf.push(["muted", "in progress, no open MR or session"]);
    return { ...it, mrs, mr, bucket, plan, area, module: area, sessions: [...sessions], problems: issuesOf };
  });
  const sizes = {};
  out.forEach(t => sizes[t.area] = (sizes[t.area] || 0) + 1);
  out.forEach(t => { if (!areaLabels()[t.area] && sizes[t.area] <= 2) t.area = "other"; });
  ui.tasks = out;
  return out;
}

function statusPill(t) {
  const b = BUCKET[t.bucket];
  return `<span class="st" style="background:color-mix(in srgb, ${b[2]} 16%, transparent);color:${b[2]}">${esc(t.status || b[1])}</span>`;
}
function mrCell(t) {
  if (!t.mr) return '<span class="muted">—</span>';
  const m = t.mr, dot = m.state === "merged" ? "ok" : m.state === "closed" ? "bad" : "busy";
  const more = t.mrs.length > 1 ? ` <span class="muted" title="${esc(t.mrs.slice(1).map(x => mrRef(x.iid) + " " + x.state).join("\n"))}">+${t.mrs.length - 1}</span>` : "";
  const flags = t.problems.filter(p => p[0] !== "muted" && !p[1].startsWith("MR merged")).map(p => `<div class="${p[0] === "bad" ? "badline" : "warnline"}">${esc(p[1])}</div>`).join("");
  return `<span class="mr"><span class="dot ${dot}"></span><a href="${esc(m.url)}" target="_blank" title="${esc(m.title)}">${mrRef(m.iid)}</a><span class="muted">${esc(m.state === "opened" ? (m.draft ? "draft" : "open") : m.state)} ${m.state === "merged" ? ago(m.merged) : ""}</span>${more}</span>${flags}`;
}

function needsAttention(tasks) {
  return tasks.filter(t => t.problems.some(p => p[0] !== "muted") && t.bucket !== "done");
}
function conf(key) { return data.config?.[key]?.value ?? ""; }
function jiraBase() { return (data.jira?.site || conf("jira.site") || "").replace(/\/$/, ""); }
function jiraLink(k) {
  if (hasJira() && jiraBase()) return `${esc(jiraBase())}/browse/${esc(k)}`;
  const m = (data.review?.mrs || []).find(x => x.keys.includes(k));
  return m ? esc(m.url) : "#/mrs";
}
function runningRun(iid) { return (data.runs || []).find(r => r.iid === iid && r.status === "running"); }
function taskAttentionSection(tasks, heading, extra = "") {
  const attention = needsAttention(tasks);
  const side = t => {
    const run = t.mr && runningRun(t.mr.iid);
    const badge = run ? `<span class="cnt running" title="${esc(run.prompt)}"><span class="dot busy"></span>${esc(conf("claude.fix_skill") || "fix")} ${dur(now() - run.started)}</span>` : "";
    return statusPill(t) + badge + kebab(t, true);
  };
  return `<section><h2>${heading}<span class="count">${attention.length || ""}</span>${extra}</h2><div class="panel list attn">${attention.map(t => isMin(t.key) ? minItem(t, jiraLink) : taskItem(t, jiraLink, { sub: `<div class="s mt-half">${t.problems.filter(p => p[0] !== "muted").map(p => `<span class="fs-sm ${p[0] === "bad" ? "badline" : "warnline"}">${esc(p[1])}</span>`).join(" · ")}</div>`, side: side(t) }, t.problems.some(p => p[0] === "bad") ? "bad" : "warn")).join("") || '<div class="empty">Nothing blocked.</div>'}</div></section>`;
}
const OVERVIEW_TODO = 5;
function notesTodoSection() {
  if (!NOTES.dirty && !NOTES.saving && !editingOverviewNote() && Date.now() - (NOTES.fetched || 0) > 30000) { NOTES.fetched = Date.now(); loadNotes(); }
  if (!NOTES.loaded) return "";
  const all = getPref("overviewNotesAll");
  const keep = new Set([document.activeElement?.dataset?.ntext, ui.notesFocus?.id].filter(Boolean));
  const matching = NOTES.items.filter(i => i.kind === "item" && (i.text.trim() || keep.has(i.id) || i.id === ui.notesFocus?.id) && (all || i.tag === "todo" || keep.has(i.id)));
  const items = all ? matching : matching.filter((i, n) => n < OVERVIEW_TODO || keep.has(i.id));
  const more = matching.length - items.length;
  const todo = NOTES.items.filter(i => i.kind === "item" && i.tag === "todo").length;
  const TAG = { todo: ["t-todo", "ToDo"], warn: ["t-warn", icon("warning", 14)], done: ["t-done", "Done"] };
  return `<section><h2>ToDo<span class="count">${todo || ""}</span><span class="h2-actions"><label class="minisw m-0" title="Show every note, not only the first ${OVERVIEW_TODO} ToDo"><input type="checkbox" data-pref="overviewNotesAll" ${all ? "checked" : ""}><span class="tog"></span>show all</label><a href="#/notes">Open ToDo →</a></span></h2>
    <div class="panel list ovnotes">${items.map(it => {
      const t = TAG[it.tag];
      return `<div class="ovnote nrow ${isDone(it) ? "done" : ""}" style="padding-left:${14 + Math.min(it.indent || 0, 4) * 18}px"><button class="ntag ${t ? t[0] : "t-none"}" data-ntag="${it.id}" title="Choose a tag">${t ? t[1] : "+"}<span class="caret">▾</span></button><div class="ntext ovtext" contenteditable="plaintext-only" spellcheck="false" data-ntext="${it.id}">${esc(it.text)}</div>${noteKeys(it.text).map(noteKeyChip).join("")}<span class="muted ovdate">${noteDate(it.created)}</span></div>`;
    }).join("") || `<div class="empty">${all ? "No notes yet." : "Nothing to do."}</div>`}${more > 0 ? `<a class="ovmore" href="#/notes">+${more} more in ToDo →</a>` : ""}</div></section>`;
}
function outcomeLine(o) {
  if (!o) return "";
  const cls = { pushed: "ok", committed: "warn", stopped: "bad" }[o.status] || "muted";
  const th = o.threads ? `threads ${o.threads.resolved ?? 0} resolved · ${o.threads.open ?? 0} open` : "";
  return `<div class="s outcome"><span class="badge ${cls}">${esc(o.status || "?")}</span>${[o.commit ? `<code>${esc(String(o.commit).slice(0, 10))}</code>` : "", th, o.checks ? esc(o.checks) : "", o.note ? esc(o.note) : ""].filter(Boolean).join(" · ")}</div>`;
}
function runsSection(limit = 8) {
  const recent = (data.runs || []).slice(0, limit);
  if (!recent.length) return "";
  const st = { running: ["busy", "Running"], done: ["ok", "Done"], error: ["bad", "Failed"], stopped: ["cancelled", "Stopped"] };
  const live = recent.filter(r => r.status === "running").length;
  const showAll = getPref("showDoneRuns");
  const runs = showAll ? recent : recent.filter(r => r.status === "running" || r.id === ui.focusRun);
  const hidden = recent.length - runs.length;
  const empty = `<div class="empty">No background runs right now${hidden ? ` · ${hidden} finished hidden` : ""}.</div>`;
  return `<section><h2>Background runs<span class="count">${live} running · ${recent.length} recent</span>${finishedToggle("showDoneRuns")}</h2><div class="panel list">${runs.length ? "" : empty}${runs.map(r => {
    const [dot, label] = st[r.status] || ["", r.status];
    const mr = (data.review?.mrs || []).find(m => m.iid === r.iid);
    const ses = r.status === "running" && (data.sessions || []).find(s => s.run_id === r.id);
    const doing = ses && ses.doing ? `${ses.doing.tool}: ${ses.doing.what}` : ses && ses.running && ses.running.length ? `${plural(ses.running.length, "agent")} running` : "";
    const key = "run:" + r.id;
    const result = r.result ? `<div class="s clickable pre-wrap ${expanded.has(key) ? "" : "clamp"}" data-expand="${esc(key)}" title="click to expand">${esc(r.result)}</div>` : "";
    return `<div class="item titem" data-run="${esc(r.id)}"><span class="dot ${dot}"></span><div class="grow">
      <div class="t">${r.iid ? `<a href="#/mr/${r.iid}/fix" data-open-run="${esc(r.id)}">${esc(r.name)}</a>` : ses ? `<a href="#/s/${esc(ses.id)}">${esc(r.name)}</a> ` : esc(r.name)}${ses && r.iid ? ` <a class="muted fs-sm" href="#/s/${esc(ses.id)}">session</a>` : ""}</div>
      ${mr ? `<div class="mrline"><a href="${esc(mr.url)}" target="_blank"><span class="iid">${mrRef(mr.iid)}</span> ${esc(mr.title)}</a></div>` : ""}
      ${doing ? `<div class="s">${esc(doing)}</div>` : ""}${outcomeLine(r.outcome)}${result}</div>
      <div class="r"><span class="muted">${label} · ${r.status === "running" ? dur(now() - r.started) : dur((r.ended || r.started) - r.started) + " · " + ago(r.ended)}</span>${r.status === "running" ? `<button class="fixbtn" data-stop="${esc(r.id)}">Stop</button>` : ""}</div></div>`;
  }).join("")}</div></section>`;
}
function mrLine(t) {
  if (!t.mr) return '<div class="mrline muted">no merge request</div>';
  const m = t.mr;
  return `<div class="mrline"><span class="dot m-0 flex-none self-center ${m.state === "merged" ? "ok" : m.state === "closed" ? "bad" : "busy"}"></span><a href="${esc(m.url)}" target="_blank" title="${esc(m.title)}"><span class="iid">${mrRef(m.iid)}</span> ${esc(m.title)}</a></div>`;
}
const MARKS = { red: ["#ef4444", "Stopped"], orange: ["#f97316", "High"], yellow: ["#eab308", "Watch"], green: ["#22c55e", "Ready"], blue: ["#3b82f6", "Note"], purple: ["#a855f7", "Waiting on others"], gray: ["#9ca3af", "Paused"] };
function markOf(key) { const c = data.marks?.[key]; return c && MARKS[c] ? c : null; }
function markAttrs(key, cls = "") {
  const c = markOf(key);
  return c ? `class="${cls} marked" style="--mk:${MARKS[c][0]}" data-mark-title="${MARKS[c][1]}"` : `class="${cls}"`;
}
const EXT_ICON = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>`;
const ICON_MIN = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h7"/><path d="M7 8l4 4-4 4"/><path d="M21 12h-7"/><path d="M17 8l-4 4 4 4"/></svg>`;
const ICON_EXP = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 12H3"/><path d="M6 8l-4 4 4 4"/><path d="M14 12h7"/><path d="M18 8l4 4-4 4"/></svg>`;
function minSet() {
  return ui.minSet ||= new Set((() => { try { return JSON.parse(localStorage.getItem("ops.minimized") || "[]"); } catch (e) { return []; } })());
}
function isMin(key) { return minSet().has(key); }
function setMin(key, on) {
  const s = minSet(); on ? s.add(key) : s.delete(key);
  try { localStorage.setItem("ops.minimized", JSON.stringify([...s])); } catch (e) {}
}
function minItem(t, jiraUrl) {
  const dot = t.problems.some(p => p[0] === "bad") ? "bad" : "warn";
  return `<div ${markAttrs(t.key, "item titem minimized")}><span class="dot ${dot}"></span><div class="grow"><div class="t"><a class="key" href="${jiraUrl(t.key)}" target="_blank">${esc(t.key)}</a> · ${esc(cleanTitle(t.summary))}</div></div><button class="kebab" data-min="${esc(t.key)}" data-on="0" title="Expand" aria-label="Expand ${esc(t.key)}">${ICON_EXP}</button></div>`;
}
function kebab(t, minimizable) { return `<button class="kebab" data-menu="${esc(t.key)}" ${minimizable ? 'data-minimizable="1"' : ""} title="Mark, minimize, run fix" aria-label="Task actions for ${esc(t.key)}">${icon("more", 16)}</button>`; }
function openMenu(btn) {
  const key = btn.dataset.menu, cur = markOf(key);
  const minimizable = btn.dataset.minimizable === "1";
  const t = (ui.tasks || []).find(x => x.key === key);
  const canFix = canRunFix();
  const own = key.startsWith("!") ? (data.review?.mrs || []).find(x => "!" + x.iid === key) : t && t.mr;
  const m = canFix && own && own.state === "opened" ? own : null;
  const busy = m && runningRun(m.iid);
  const menu = $("menu");
  menu.innerHTML = `<div class="mh">Mark ${esc(displayKey(key))}</div>
    <div class="sws">${Object.entries(MARKS).map(([c, [hex, name]]) => `<button class="swatch ${cur === c ? "on" : ""}" style="--c:${hex}" data-mark-set="${c}" data-key="${esc(key)}" title="${name}" aria-label="${name}"></button>`).join("")}</div>
    ${cur ? `<button class="mi" data-mark-set="" data-key="${esc(key)}">Clear mark <span class="muted">(${MARKS[cur][1]})</span></button>` : ""}
    ${m || minimizable ? "<hr>" : ""}
    ${minimizable ? `<button class="mi" data-min="${esc(key)}" data-on="1">${ICON_MIN}Minimize</button>` : ""}
    ${m ? `<button class="mi" data-fix="${m.iid}" ${busy ? "disabled" : ""}>${busy ? "fix is running…" : `Run ${esc(conf("claude.fix_skill"))} · ${mrRef(m.iid)}`}</button>` : ""}
    ${own?.url || (t && hasJira()) ? "<hr>" : ""}
    ${own?.url ? `<a class="mi" href="${esc(own.url)}" target="_blank" rel="noopener">${EXT_ICON}Open in ${hostName()}</a>` : ""}
    ${t && hasJira() ? `<a class="mi" href="${esc(jiraLink(t.key))}" target="_blank" rel="noopener">${EXT_ICON}Open in Jira</a>` : ""}`;
  menu.hidden = false;
  const r = btn.getBoundingClientRect(), w = menu.offsetWidth, h = menu.offsetHeight;
  menu.style.left = Math.max(8, Math.min(innerWidth - w - 8, r.right - w)) + "px";
  menu.style.top = (r.bottom + h + 8 > innerHeight ? r.top - h - 4 : r.bottom + 4) + "px";
}
function closeMenu() { $("menu").hidden = true; }
function taskItem(t, jiraUrl, right, dotCls) {
  return `<div ${markAttrs(t.key, "item titem")}>${dotCls ? `<span class="dot ${dotCls}"></span>` : ""}<div class="grow"><div class="t"><a class="key" href="${jiraUrl(t.key)}" target="_blank">${esc(t.key)}</a> · ${esc(cleanTitle(t.summary))}</div>${mrLine(t)}${right.sub || ""}</div>${right.side ? `<div class="r">${right.side}</div>` : ""}</div>`;
}

function pageTasks(ctx) {
  const jira = data.jira || {}, gl = data.review || {};
  const tasks = buildTasks(ctx);
  const q = (ui.taskQuery || "").toLowerCase();
  const off = new Set((getPrefRaw("taskOff") ?? "done,cancelled").split(",").filter(Boolean));
  const counts = Object.fromEntries(BUCKETS.map(b => [b[0], tasks.filter(t => t.bucket === b[0]).length]));
  const visible = tasks.filter(t => !off.has(t.bucket) && (!q || (t.key + " " + t.summary + " " + t.area + " " + t.mrs.map(m => "!" + m.iid).join(" ")).toLowerCase().includes(q)));
  const working = tasks.filter(t => t.sessions.length && t.bucket !== "done");
  const areas = {};
  visible.forEach(t => (areas[t.area] ||= []).push(t));
  const view = getPrefRaw("taskView") || "list";
  const areaOrder = Object.keys(areas).sort((a, b) => (a === "other") - (b === "other") || areas[b].filter(t => t.bucket !== "done").length - areas[a].filter(t => t.bucket !== "done").length || areas[b].length - areas[a].length);
  const jiraUrl = jiraLink;
  const row = t => `<tr ${markAttrs(t.key)}><td class="key"><a href="${jiraUrl(t.key)}" target="_blank">${esc(t.key)}</a></td>
    <td><div>${t.plan != null && isPlanArea(t.area) ? `<span class="plan">${String(t.plan).padStart(2, "0")}</span>` : ""}${esc(cleanTitle(t.summary))}</div>${t.area === "other" && t.module !== "other" ? `<div class="subt mono">${esc(t.module)}</div>` : ""}${t.problems.filter(p => p[0] === "muted" || p[1].startsWith("MR merged")).map(p => `<div class="${p[0] === "muted" ? "subt" : "warnline"}">${esc(p[1])}</div>`).join("")}</td>
    <td class="nowrap">${statusPill(t)}</td><td class="nowrap">${mrCell(t)}</td>
    <td>${t.sessions.map(sessTag).join("<br>")}</td><td class="num muted" title="${esc(fmtDateTime(t.updated))}">${ago(t.updated)} ${kebab(t)}</td></tr>`;
  const head = ["Key", "Task", hasJira() ? "Jira status" : "Status", mrWord(false), "Claude session", ["Updated", "num"]];
  const areaBlock = a => {
    let list = areas[a].slice();
    let rows;
    if (isPlanArea(a) && planCfg().sections?.length) {
      const sections = planCfg().sections;
      list.sort((x, y) => (x.plan ?? 999) - (y.plan ?? 999));
      rows = [];
      const leftover = list.filter(t => t.plan == null || !sections.some(([lo, hi]) => t.plan >= lo && t.plan <= hi));
      sections.forEach(([lo, hi, name]) => { const part = list.filter(t => t.plan != null && t.plan >= lo && t.plan <= hi); if (part.length) rows.push(`<tr class="sub"><td colspan="6">${esc(name)}</td></tr>`, ...part.map(row)); });
      if (leftover.length) rows.push(`<tr class="sub"><td colspan="6">${esc(planCfg().other || "Other")}</td></tr>`, ...leftover.map(row));
    } else {
      list.sort((x, y) => BUCKETS.findIndex(b => b[0] === x.bucket) - BUCKETS.findIndex(b => b[0] === y.bucket) || y.updated - x.updated);
      rows = list.map(row);
    }
    const c = BUCKETS.map(([k, label, col]) => { const n = areas[a].filter(t => t.bucket === k).length; return n ? `<span class="cnt" style="background:color-mix(in srgb, ${col} 16%, transparent);color:${col}">${n} ${label.toLowerCase().split(" /")[0]}</span>` : ""; }).join("");
    const open = isAreaOpen(a, areaOrder);
    return `<div class="panel area ${open ? "open" : ""}" id="area-${esc(a)}"><div class="area-h" data-area="${esc(a)}"><span class="chev">${icon("chevron", 14)}</span><span class="ttl">${esc(areaLabels()[a] || (a === "other" ? "Other" : a))}</span>${areaLabels()[a] ? `<span class="mod">${esc(a)}</span>` : ""}<span class="counts">${c}</span></div><div class="tbl flush-bottom">${open ? table(head, rows).replace("<table>", '<table><colgroup><col class="c-key"><col><col class="c-st"><col class="c-mr"><col class="c-ses"><col class="c-up"></colgroup>') : ""}</div></div>`;
  };
  const src = [hasJira() ? (jira.configured ? (jira.error ? `<span class="err" title="${esc(jira.error)}">Jira error</span>` : `Jira ${ago(jira.fetched)}`) : `<span class="warnline">Jira not connected</span>`) : "", gl.configured ? (gl.error ? `<span class="err" title="${esc(gl.error)}">${hostName()} error</span>` : `${hostName()} ${ago(gl.fetched)}`) : `${hostName()} not connected`].filter(Boolean).join(" · ");
  return `<div class="pagehead"><h1>${tasksPage()}</h1><span class="sub">${tasks.length} tasks · ${tasks.filter(t => !["done", "cancelled"].includes(t.bucket)).length} open · ${src}</span>
      <span class="acctline ml-auto">${!hasJira() ? "" : jira.account?.connected ? `Jira: <b class="text-strong">${esc(jira.account.name || jira.account.email)}</b> <span>${esc(jira.account.email)}</span>` : "Jira: not connected"}${hasJira() ? `<button class="linkbtn" id="acctOpen">${jira.account?.connected ? "Change account" : "Connect"}</button>` : ""}</span>
      <button class="btn-primary" id="taskRefresh" ${ui.refreshing ? "disabled" : ""}>${ui.refreshing ? "Updating…" : "Update"}</button></div>
    ${jira.configured || !hasJira() ? "" : `<section><div class="panel setup"><b>Connect Jira to see every task, not only those with a merge request.</b><span class="muted">Create a token at <a href="https://id.atlassian.com/manage-profile/security/api-tokens" target="_blank">id.atlassian.com → API tokens</a>, then press <button class="linkbtn" id="acctOpen2">Connect</button>.</span></div></section>`}
    <section><div class="stack">${BUCKETS.map(([k, l, c]) => counts[k] ? `<span style="width:${counts[k] / Math.max(1, tasks.length) * 100}%;background:${c}" title="${l}: ${counts[k]}"></span>` : "").join("")}</div>
      <div class="kpis">${BUCKETS.map(([k, l, c]) => `<button class="kpi ${off.has(k) ? "off" : ""}" data-bucket="${k}" title="Show / hide"><b>${counts[k]}</b><small><span class="dot" style="background:${c}"></span>${l}</small></button>`).join("")}</div></section>
    <div class="cols">
      ${taskAttentionSection(tasks, "Needs attention")}
      <section><h2>Claude is working on<span class="count">${working.length || ""}</span></h2><div class="panel list">${working.map(t => taskItem(t, jiraUrl, { sub: `<div class="mt-1">${statusPill(t)}</div>`, side: t.sessions.map(sessTag).join("<br>") })).join("") || '<div class="empty">No session is linked to a task right now.</div>'}</div></section>
    </div>
    ${runsSection()}
    <div class="toolbar"><span class="seg"><button data-view="list" class="${view === "list" ? "on" : ""}">List</button><button data-view="kanban" class="${view === "kanban" ? "on" : ""}">Kanban</button></span><input class="search" id="taskSearch" placeholder="Search key, title, module, !MR" value="${esc(ui.taskQuery || "")}"><span>${visible.length} shown · ${plural(areaOrder.length, "area")}</span>${view === "list" ? `<span class="ml-auto"><button class="linkbtn" data-areas="open">Expand all</button> · <button class="linkbtn" data-areas="close">Collapse all</button></span>` : ""}</div>
    ${view === "kanban" ? kanban(visible) : areaOrder.map(areaBlock).join("") || '<div class="muted">No tasks match.</div>'}`;
}

function isAreaOpen(a, order) {
  const st = ui.areaState ||= (() => { try { return JSON.parse(localStorage.getItem("ops.areaOpen") || "{}"); } catch (e) { return {}; } })();
  return a in st ? st[a] : a === order[0];
}
function setAreaOpen(a, v) {
  ui.areaState[a] = v;
  try { localStorage.setItem("ops.areaOpen", JSON.stringify(ui.areaState)); } catch (e) {}
}
function kanban(tasks) {
  const off = new Set((getPrefRaw("taskOff") ?? "done,cancelled").split(",").filter(Boolean));
  const cols = BUCKETS.filter(([k]) => !off.has(k));
  const card = t => `<div ${markAttrs(t.key, "kcard")}><div class="km khead"><a class="key" href="${jiraLink(t.key)}" target="_blank">${esc(t.key)}</a>${t.plan != null && isPlanArea(t.area) ? `<span class="plan m-0">${String(t.plan).padStart(2, "0")}</span>` : ""}<span class="areachip">${esc(areaLabels()[t.area] || (t.area === "other" ? "Other" : t.area))}</span><span class="ml-auto nowrap" title="updated">${dur(now() - t.updated)}</span>${kebab(t)}</div>
    <div class="kt">${esc(cleanTitle(t.summary))}</div>
    ${t.status ? `<div class="km">${statusPill(t)}</div>` : ""}
    ${t.mr || t.sessions.length ? `<div class="km">${t.mr ? mrCell(t) : ""}${t.sessions.map(sessTag).join(" ")}</div>` : ""}
    ${t.problems.filter(p => p[0] === "muted" || p[1].startsWith("MR merged")).map(p => `<div class="${p[0] === "muted" ? "subt" : "warnline"}">${esc(p[1])}</div>`).join("")}</div>`;
  return `<div class="board">${cols.map(([k, label, col]) => {
    const list = tasks.filter(t => t.bucket === k).sort((a, b) => b.updated - a.updated);
    const all = expanded.has("kb:" + k), shown = all ? list : list.slice(0, 30);
    return `<div class="bcol"><div class="bcol-h"><span class="dot" style="background:${col}"></span>${label}<span class="n">${list.length}</span></div>${shown.map(card).join("") || '<div class="empty">No tasks</div>'}${list.length > shown.length ? `<div class="bmore" data-expand="kb:${k}">Show ${list.length - shown.length} more</div>` : ""}</div>`;
  }).join("")}</div>`;
}
