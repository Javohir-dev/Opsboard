const JIRA = { cache: {}, error: {}, loading: null };
const CAT_ORDER = { new: 0, indeterminate: 1, done: 2 };
const TYPE_ICON = {
  story: ["#63ba3c", '<path d="M6 3h12a1 1 0 0 1 1 1v17l-7-4-7 4V4a1 1 0 0 1 1-1z" fill="currentColor" stroke="none"/>'],
  bug: ["#e5493a", '<circle cx="12" cy="12" r="6" fill="currentColor" stroke="none"/>'],
  task: ["#4bade8", '<path d="m7 12.5 3.2 3.2L17 9" stroke="#fff" stroke-width="2.6"/>'],
  epic: ["#904ee2", '<path d="M13.5 3 6 13.5h5L10 21l8-11h-5.5z" fill="#fff" stroke="none"/>'],
  subtask: ["#4bade8", '<rect x="7" y="7" width="10" height="10" rx="1.5" fill="none" stroke="#fff" stroke-width="2.2"/>'],
};
const PRIORITY = {
  highest: ["#d04437", '<path d="m6 15 6-5 6 5"/><path d="m6 10 6-5 6 5"/>'],
  high: ["#f15c75", '<path d="m6 14 6-6 6 6"/>'],
  medium: ["#f79232", '<path d="M6 9h12"/><path d="M6 15h12"/>'],
  low: ["#2a8735", '<path d="m6 10 6 6 6-6"/>'],
  lowest: ["#55a557", '<path d="m6 9 6 5 6-5"/><path d="m6 14 6 5 6-5"/>'],
};
function typeIcon(type) {
  const k = (type || "").toLowerCase().replace(/[^a-z]/g, "");
  const [color, inner] = TYPE_ICON[k.startsWith("sub") ? "subtask" : k in TYPE_ICON ? k : "task"];
  const bg = k === "story" || k === "bug" ? "none" : color;
  return `<span class="jtype" title="${esc(type || "Task")}" style="--c:${color}"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke-linecap="round" stroke-linejoin="round" style="color:${color}"><rect x="2" y="2" width="20" height="20" rx="4" fill="${bg}"/>${inner}</svg></span>`;
}
function priorityIcon(p) {
  const hit = PRIORITY[(p || "").toLowerCase()];
  if (!hit) return "";
  return `<span class="jprio" title="${esc(p)}"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="${hit[0]}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">${hit[1]}</svg></span>`;
}
function lozenge(status, category) {
  return `<span class="jloz jloz-${esc(category || "new")}" translate="no">${esc(status || "—")}</span>`;
}
function issueMrChip(t) {
  if (!t.mr) return "";
  const m = t.mr, st = m.state === "merged" ? "merged" : m.state === "closed" ? "closed" : m.draft ? "draft" : "open";
  const threads = m.state === "opened" && m.threads_total ? `<span class="jmrth ${m.threads ? "open" : ""}">${icon("comment", 11)}${m.threads_total - (m.threads || 0)}/${m.threads_total}</span>` : "";
  return `<a class="jmr jmr-${st}" href="#/mr/${m.iid}" title="${esc(m.title)}" data-stop-card>${icon("mrs", 12)}${mrRef(m.iid)}${threads}${m.conflicts ? `<span class="jmrbad" title="merge conflict">${icon("warning", 11)}</span>` : ""}</a>`;
}
const issueDone = t => t.category === "done" || ["done", "cancelled"].includes(t.bucket);
function openSprint(t) { return t.sprint && t.sprint.state !== "closed" ? t.sprint : null; }
function sprintsOf(tasks) {
  const seen = {};
  tasks.forEach(t => { const sp = openSprint(t); if (sp) seen[sp.id] = sp; });
  return Object.values(seen).sort((a, b) => (a.state === "active" ? 0 : 1) - (b.state === "active" ? 0 : 1) || (a.start || 9e12) - (b.start || 9e12));
}
const fmtDay = ts => ts ? new Date(ts * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "";
function inScope(t, scope, sprints) {
  if (scope === "all") return true;
  if (scope === "backlog") return !openSprint(t) && !issueDone(t);
  if (scope) return String(openSprint(t)?.id) === scope;
  const active = sprints.filter(sp => sp.state === "active");
  return active.length ? active.some(sp => sp.id === openSprint(t)?.id) : true;
}
function sprintCounts(items) {
  const n = { new: 0, indeterminate: 0, done: 0 };
  items.forEach(t => n[t.category in n ? t.category : "new"]++);
  return `<span class="jcounts"><span class="c-new" title="To do">${n.new}</span><span class="c-ind" title="In progress">${n.indeterminate}</span><span class="c-done" title="Done">${n.done}</span></span>`;
}

function jiraFilters() {
  const pick = k => getPrefRaw("jira." + k) || "";
  return { sprint: pick("sprint"), hideDone: getPrefRaw("jira.hideDone") !== "0", attention: getPref("jira.attention"), claude: getPref("jira.claude"), withMr: getPref("jira.withMr"), type: pick("type"), prio: pick("prio") };
}
function columnsOf(tasks) {
  const cols = {};
  tasks.forEach(t => { const k = t.status || "—"; (cols[k] ||= { status: k, category: t.category || "new", bucket: t.bucket, items: [] }).items.push(t); });
  const bucketIdx = b => BUCKETS.findIndex(x => x[0] === b);
  return Object.values(cols).sort((a, b) => (CAT_ORDER[a.category] ?? 1) - (CAT_ORDER[b.category] ?? 1) || bucketIdx(a.bucket) - bucketIdx(b.bucket) || b.items.length - a.items.length);
}
function jiraCard(t) {
  const done = t.category === "done" || t.bucket === "done";
  const warn = t.problems.find(p => p[0] === "bad") || t.problems.find(p => p[0] === "warn");
  return `<div ${markAttrs(t.key, "jcard" + (ui.jiraOpen === t.key ? " on" : ""))} data-issue="${esc(t.key)}" role="button" tabindex="0">
    ${t.parent ? `<div class="jepic" title="${esc(t.parent.summary)}" translate="no">${esc(t.parent.summary || t.parent.key)}</div>` : ""}
    <div class="jsum">${esc(cleanTitle(t.summary))}</div>
    ${t.labels?.length ? `<div class="jlabels">${t.labels.slice(0, 3).map(l => `<span translate="no">${esc(l)}</span>`).join("")}</div>` : ""}
    <div class="jfoot">${typeIcon(t.type)}<span class="jkey ${done ? "done" : ""}" translate="no">${esc(t.key)}</span>${issueMrChip(t)}<span class="grow"></span>
      ${warn ? `<span class="jwarn ${warn[0]}" title="${esc(t.problems.map(p => p[1]).join("\n"))}">${icon("warning", 13)}</span>` : ""}
      ${t.sessions.length ? `<span class="jclaude" title="${esc(t.sessions.map(s => s.title || s.name).join("\n"))}">${icon("agent", 13)}</span>` : ""}
      ${priorityIcon(t.priority)}</div></div>`;
}
function jiraBoard(tasks) {
  const cols = columnsOf(tasks);
  if (!cols.length) return '<div class="empty">No issues match.</div>';
  return `<div class="jboard">${cols.map(c => `<div class="jcol"><div class="jcolh"><span translate="no">${esc(c.status)}</span><span class="jcount">${c.items.length}</span></div>
    <div class="jcards">${c.items.sort((a, b) => b.updated - a.updated).map(jiraCard).join("")}</div></div>`).join("")}</div>`;
}
function jiraRow(t) {
  return `<tr class="jrow ${ui.jiraOpen === t.key ? "on" : ""}" data-issue="${esc(t.key)}">
    <td class="jt">${typeIcon(t.type)}</td><td class="nowrap"><span class="jkey ${issueDone(t) ? "done" : ""}" translate="no">${esc(t.key)}</span></td>
    <td><div class="jsum1">${esc(cleanTitle(t.summary))}</div>${t.parent ? `<div class="subt" translate="no">${esc(t.parent.summary || t.parent.key)}</div>` : ""}</td>
    <td class="nowrap">${lozenge(t.status, t.category)}</td>
    <td class="nowrap">${issueMrChip(t) || '<span class="muted">—</span>'}</td>
    <td class="nowrap">${priorityIcon(t.priority)}</td>
    <td class="num muted" title="${esc(fmtDateTime(t.updated))}">${ago(t.updated)}</td></tr>`;
}
function backlogGroup(id, title, meta, items) {
  const shut = getPref("jira.shut." + id);
  const rows = items.slice().sort((x, y) => issueDone(x) - issueDone(y) || y.updated - x.updated).map(jiraRow).join("");
  return `<section class="jgroup"><div class="jgh" data-jgroup="${esc(id)}" role="button" tabindex="0" aria-expanded="${!shut}"><span class="dchev ${shut ? "" : "open"}">${icon("chevron", 14)}</span><b translate="no">${esc(title)}</b><span class="muted">${meta}</span><span class="grow"></span>${sprintCounts(items)}</div>
    ${shut ? "" : items.length ? `<div class="tbl panel jlist"><table><colgroup><col class="c-t"><col class="c-k"><col><col class="c-s"><col class="c-m"><col class="c-p"><col class="c-u"></colgroup><tbody>${rows}</tbody></table></div>` : '<div class="empty">No issues.</div>'}</section>`;
}
function jiraList(tasks, sprints, f) {
  const groups = [];
  const single = f.sprint && f.sprint !== "all" && f.sprint !== "backlog";
  const shown = single ? sprints.filter(sp => String(sp.id) === f.sprint) : f.sprint === "backlog" ? [] : sprints;
  shown.forEach(sp => {
    const items = tasks.filter(t => openSprint(t)?.id === sp.id);
    groups.push(backlogGroup("sp" + sp.id, sp.name, `${fmtDay(sp.start)}${sp.end ? " – " + fmtDay(sp.end) : ""} · ${plural(items.length, "issue")}${sp.state === "active" ? "" : " · planned"}`, items));
  });
  if (!single) {
    const backlog = tasks.filter(t => !openSprint(t) && !issueDone(t));
    groups.push(backlogGroup("backlog", "Backlog", plural(backlog.length, "issue"), backlog));
  }
  return groups.join("") || '<div class="empty">No issues match.</div>';
}

function loadIssue(key, fresh = false) {
  if (JIRA.loading === key) return;
  JIRA.loading = key;
  fetch(`/api/jira-issue?key=${encodeURIComponent(key)}${fresh ? "&fresh=1" : ""}`, { cache: "no-store" })
    .then(r => r.json()).then(r => { if (r.ok) { JIRA.cache[key] = r.issue; delete JIRA.error[key]; } else JIRA.error[key] = r.error; })
    .catch(() => { JIRA.error[key] = "dashboard server is not running"; })
    .finally(() => { JIRA.loading = null; ui.lastView = null; render(); });
}
function personRow(p) {
  if (!p?.name) return '<span class="muted">None</span>';
  return `<span class="jperson">${p.avatar ? `<span class="avatar avimg"><img src="${esc(p.avatar)}" alt="" referrerpolicy="no-referrer" onerror="this.remove()"><span>${esc(initials(p.name))}</span></span>` : avatarOf(p.name)}<span>${esc(p.name)}</span></span>`;
}
function jiraPanel(t) {
  const key = ui.jiraOpen;
  if (!key) return "";
  const it = JIRA.cache[key], err = JIRA.error[key];
  if (!it && !err && JIRA.loading !== key) loadIssue(key);
  const base = t || {};
  const summary = it?.summary || base.summary || "";
  const html = s => (window.DOMPurify ? DOMPurify.sanitize(s || "", { FORBID_TAGS: ["style", "form", "input", "button"], FORBID_ATTR: ["style"] }) : esc(s || ""));
  const details = it ? [
    ["Status", lozenge(it.status, it.category)],
    ["Type", `${typeIcon(it.type)}<span>${esc(it.type)}</span>`],
    ["Priority", `${priorityIcon(it.priority)}<span>${esc(it.priority || "None")}</span>`],
    ["Assignee", personRow(it.assignee)],
    ["Reporter", personRow(it.reporter)],
    ["Labels", it.labels.length ? `<span class="jlabels">${it.labels.map(l => `<span translate="no">${esc(l)}</span>`).join("")}</span>` : '<span class="muted">None</span>'],
    ["Created", `<span title="${esc(fmtDateTime(it.created))}">${ago(it.created)}</span>`],
    ["Updated", `<span title="${esc(fmtDateTime(it.updated))}">${ago(it.updated)}</span>`],
    ...(it.due ? [["Due", esc(it.due)]] : []),
    ...(it.resolved ? [["Resolved", ago(it.resolved)]] : []),
  ].map(([k, v]) => `<div class="jdk">${k}</div><div class="jdv">${v}</div>`).join("") : "";
  const mrs = (base.mrs || []).map(m => `<a class="jpmr" href="#/mr/${m.iid}"><span class="dot ${m.state === "merged" ? "ok" : m.state === "closed" ? "bad" : "busy"}"></span><span class="mono">${mrRef(m.iid)}</span><span class="grow ell">${esc(m.title)}</span><span class="muted fs-sm">${esc(m.state === "opened" ? (m.threads ? `${m.threads} open thread(s)` : "open") : m.state)}</span></a>`).join("");
  const body = it ? `
      ${it.description ? `<section class="jsec"><h3>Description</h3><div class="md jdesc">${html(it.description)}</div></section>` : `<section class="jsec"><h3>Description</h3><div class="muted">No description.</div></section>`}
      ${it.subtasks.length ? `<section class="jsec"><h3>Subtasks</h3>${it.subtasks.map(s => `<div class="jsubt" data-issue="${esc(s.key)}">${esc(s.key)} · ${esc(s.summary)} <span class="muted">${esc(s.status)}</span></div>`).join("")}</section>` : ""}
      <section class="jsec"><h3>Comments <span class="muted">${it.comments.length}</span></h3>${it.comments.slice().reverse().map(c => `<div class="jcomment">${personRow(c.author)}<span class="muted fs-sm" title="${esc(fmtDateTime(c.created))}">${ago(c.created)}</span><div class="md">${html(c.body)}</div></div>`).join("") || '<div class="muted">No comments.</div>'}</section>`
    : err ? `<div class="err">${esc(err)}</div>` : '<div class="skel skel-block"></div>';
  return `<div class="jscrim" data-jira-close></div><aside class="jpanel" role="dialog" aria-label="${esc(key)}">
    <div class="jph"><span class="jcrumb" translate="no">${it?.parent ? `<span class="muted">${esc(it.parent.key)} /</span> ` : ""}${typeIcon(it?.type || base.type)}<a href="${esc(jiraLink(key))}" target="_blank">${esc(key)}</a></span>
      <span class="grow"></span><button class="iconbtn" data-jira-refresh title="Reload from Jira">${icon("refresh", 14)}</button><a class="fixbtn" href="${esc(jiraLink(key))}" target="_blank">Open in Jira</a><button class="iconbtn" data-jira-close title="Close" aria-label="Close">${icon("x", 16)}</button></div>
    <div class="jpbody"><h2 class="jptitle">${esc(summary)}</h2>
      ${mrs ? `<section class="jsec"><h3>${mrsPage()}</h3><div class="jpmrs">${mrs}</div></section>` : ""}
      ${it ? `<section class="jsec"><h3>Details</h3><div class="jdetails">${details}</div></section>` : ""}
      ${body}</div></aside>`;
}

function pageJira(ctx) {
  const jira = data.jira || {};
  const tasks = buildTasks(ctx);
  const f = jiraFilters(), q = (ui.taskQuery || "").toLowerCase();
  const types = [...new Set(tasks.map(t => t.type).filter(Boolean))].sort();
  const prios = Object.keys(PRIORITY).map(p => p[0].toUpperCase() + p.slice(1)).filter(p => tasks.some(t => t.priority === p));
  const attention = new Set(needsAttention(tasks).map(t => t.key));
  const sprints = sprintsOf(tasks);
  const matches = tasks.filter(t => (!f.attention || attention.has(t.key)) && (!f.claude || t.sessions.length) && (!f.withMr || t.mr)
    && (!f.type || t.type === f.type) && (!f.prio || t.priority === f.prio)
    && (!q || (t.key + " " + t.summary + " " + (t.labels || []).join(" ") + " " + t.mrs.map(m => "!" + m.iid).join(" ")).toLowerCase().includes(q)));
  const visible = matches.filter(t => inScope(t, f.sprint, sprints) && (!f.hideDone || !issueDone(t) || (openSprint(t) && f.sprint !== "all")));
  const view = getPrefRaw("jira.view") || "board";
  const active = sprints.filter(sp => sp.state === "active");
  const sprintSelect = `<select class="jselect jsprint" data-jselect="sprint" title="Sprint"><option value="">${active.length ? esc(active.map(sp => sp.name).join(", ")) : "Current sprint"}</option>${sprints.filter(sp => sp.state !== "active").map(sp => `<option value="${esc(sp.id)}" ${f.sprint === String(sp.id) ? "selected" : ""}>${esc(sp.name)}</option>`).join("")}<option value="backlog" ${f.sprint === "backlog" ? "selected" : ""}>Backlog</option><option value="all" ${f.sprint === "all" ? "selected" : ""}>All issues</option></select>`;
  const chip = (k, label, on, n) => `<button class="jchip ${on ? "on" : ""}" data-jchip="${k}">${label}${n != null ? `<span class="n">${n}</span>` : ""}</button>`;
  const src = jira.configured ? (jira.error ? `<span class="err" title="${esc(jira.error)}">Jira error</span>` : `updated ${ago(jira.fetched)}`) : '<span class="warnline">Jira not connected</span>';
  const current = active[0];
  const sub = view === "board" && !f.sprint && current ? `${esc(current.name)} · ${fmtDay(current.start)} – ${fmtDay(current.end)} · ${plural(visible.length, "issue")}` : `${visible.length} of ${tasks.length} issues`;
  const open = ui.jiraOpen && tasks.find(t => t.key === ui.jiraOpen);
  const listTasks = matches.filter(t => !f.hideDone || !issueDone(t) || openSprint(t));
  return `<div class="pagehead"><h1>Jira</h1><span class="sub">${sub} · ${src}</span>
      <span class="acctline ml-auto">${jira.account?.connected ? `<b class="text-strong">${esc(jira.account.name || jira.account.email)}</b>` : ""}</span>
      <button class="btn-primary" id="taskRefresh" ${ui.refreshing ? "disabled" : ""}>${ui.refreshing ? "Updating…" : "Update"}</button></div>
    <div class="jbar">
      ${sprintSelect}
      <label class="ftsearch jsearch">${icon("search", 14)}<input id="taskSearch" type="search" placeholder="Search issues" value="${esc(ui.taskQuery || "")}" spellcheck="false"></label>
      ${chip("attention", "Needs attention", f.attention, [...attention].filter(k => matches.some(t => t.key === k)).length)}${chip("claude", "Claude working", f.claude, tasks.filter(t => t.sessions.length).length)}${chip("withMr", `With ${mrsPage()}`, f.withMr)}${chip("hideDone", "Hide done", f.hideDone)}
      <select class="jselect" data-jselect="type"><option value="">All types</option>${types.map(x => `<option ${f.type === x ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>
      <select class="jselect" data-jselect="prio"><option value="">All priorities</option>${prios.map(x => `<option ${f.prio === x ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>
      <span class="grow"></span>
      <span class="ftmode"><button class="${view === "board" ? "on" : ""}" data-jview="board" title="Board">${icon("overview", 15)}</button><button class="${view === "list" ? "on" : ""}" data-jview="list" title="Backlog">${icon("tasks", 15)}</button></span>
    </div>
    ${view === "list" ? jiraList(listTasks, sprints, f) : jiraBoard(visible)}
    ${jiraPanel(open)}`;
}

document.addEventListener("click", e => {
  if (route().page !== "tasks" || !hasJira()) return;
  if (e.target.closest("[data-stop-card]")) return;
  const ch = e.target.closest("[data-jchip]");
  if (ch) { const k = ch.dataset.jchip; if (k === "hideDone") setPref("jira.hideDone", !jiraFilters().hideDone); else setPref("jira." + k, !getPref("jira." + k)); render(); return; }
  const g = e.target.closest("[data-jgroup]");
  if (g) { setPref("jira.shut." + g.dataset.jgroup, !getPref("jira.shut." + g.dataset.jgroup)); render(); return; }
  const v = e.target.closest("[data-jview]");
  if (v) { try { localStorage.setItem("ops.jira.view", v.dataset.jview); } catch (x) {} render(); return; }
  if (e.target.closest("[data-jira-close]")) { ui.jiraOpen = null; render(); return; }
  if (e.target.closest("[data-jira-refresh]")) { if (ui.jiraOpen) loadIssue(ui.jiraOpen, true); return; }
  const card = e.target.closest("[data-issue]");
  if (card && !e.target.closest("a, button, .kebab")) { ui.jiraOpen = card.dataset.issue; render(); }
});
document.addEventListener("change", e => {
  const s = e.target.closest?.("[data-jselect]");
  if (s && route().page === "tasks") { try { localStorage.setItem("ops.jira." + s.dataset.jselect, s.value); } catch (x) {} render(); }
});
document.addEventListener("keydown", e => {
  if (route().page !== "tasks") return;
  if (e.key === "Escape" && ui.jiraOpen) { ui.jiraOpen = null; render(); return; }
  const card = e.target.closest?.("[data-issue]");
  if (card && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); ui.jiraOpen = card.dataset.issue; render(); }
});
