const PIPE = { success: ["ok", "ok", "Pipeline passed"], failed: ["bad", "fail", "Pipeline failed"], running: ["run", "running", "Pipeline running"], pending: ["wait", "pending", "Pipeline pending"], created: ["wait", "pending", "Pipeline created"], canceled: ["skip", "skipped", "Pipeline canceled"], skipped: ["skip", "skipped", "Pipeline skipped"], manual: ["wait", "play", "Manual action"] };
function mrLabel(name) {
  const lb = data.review?.labels?.[name] || { color: "#6b7280", text: "#ffffff" };
  return `<span class="glbl" style="background:${esc(lb.color)};color:${esc(lb.text)}" title="${esc(name)}">${esc(name)}</span>`;
}
function initials(n) { return n.split(/\s+/).map(x => x[0] || "").join("").slice(0, 2).toUpperCase(); }
function mrRow(m) {
  const alias = data.key_aliases || {};
    const pipe = PIPE[m.pipeline];
    const key = m.keys[0], issue = key && (data.jira?.issues || []).find(i => i.key === (alias[key] || key));
    const thr = m.threads_total ? (m.threads ? `<span class="mrpill thr-open" title="${m.threads} open review thread(s)"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>${m.threads_total - m.threads} of ${m.threads_total}</span>` : `<span class="mrpill okp" title="All threads resolved"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>Resolved</span>`) : "";
    const run = runningRun(m.iid);
    const when = m.state === "merged" ? `merged ${ago(m.merged)}` : m.state === "closed" ? `closed ${ago(m.closed || m.updated)}` : `updated ${ago(m.updated)}`;
    if (isMin("!" + m.iid)) return `<div ${markAttrs("!" + m.iid, "mrrow minimized")} data-mr="${m.iid}"><a class="mrtitle" href="#/mr/${m.iid}">${esc(m.title)}</a><span class="muted mrmin-iid">${mrRef(m.iid)}</span><button class="kebab" data-min="!${m.iid}" data-on="0" title="Expand" aria-label="Expand !${m.iid}">${ICON_EXP}</button></div>`;
    return `<div ${markAttrs("!" + m.iid, "mrrow")} data-mr="${m.iid}">
      <div class="mrmain">
        <a class="mrtitle" href="#/mr/${m.iid}">${esc(m.title)}</a>
        <div class="mrsub"><span title="Created ${esc(fmtDateTime(m.created))}">${mrRef(m.iid)} · created ${ago(m.created)} by ${esc(m.author)}</span><span class="mrbr" title="${esc(m.source)} → ${esc(m.target)}"><svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="7" r="2"/><path d="M6 7v10M18 9c0 5-6 4-12 8"/></svg>${esc(m.target)}</span>
<span class="mrlabels">${m.conflicts ? '<span class="glbl glbl-conflict">merge conflict</span>' : ""}${m.labels.map(mrLabel).join("")}</span>
          ${issue ? `<a class="mrjira" href="${jiraLink(issue.key)}" target="_blank" title="${esc(issue.summary)}">${esc(issue.key)} · ${esc(issue.status)}</a>` : ""}</div>
      </div>
      <div class="mrside">
        <div class="mricons">
          <span class="slot sp">${pipe ? `<span class="pipe p-${pipe[0]}" title="${pipe[2]}" role="img" aria-label="${pipe[2]}">${icon(pipe[1], 18)}</span>` : ""}</span>
          <span class="slot sr">${m.reviewers.map(r => `<span class="avatar" title="Reviewer: ${esc(r)}">${esc(initials(r))}</span>`).join("")}</span>
          <span class="slot sa">${m.approved ? `<span class="mrpill okp" title="Approved by ${esc(m.approved_by.join(", "))}">${icon("check", 14)}Approved</span>` : ""}</span>
          <span class="slot st">${thr}</span>
          <span class="slot sk">${run ? `<span class="cnt running"><span class="dot busy"></span>${esc(conf("claude.fix_skill") || "fix")} ${dur(now() - run.started)}</span>` : `<button class="kebab" data-menu="!${m.iid}" data-minimizable="1" title="Mark, minimize, mr-fix" aria-label="Actions for !${m.iid}">${icon("more", 16)}</button>`}</span>
        </div>
        <div class="muted mrwhen" title="${esc(fmtDateTime(m.state === "merged" ? m.merged : m.state === "closed" ? (m.closed || m.updated) : m.updated))}">${when}</div>
      </div>
    </div>`;
}
function pageMrs() {
  const gl = data.review || {}, all = gl.mrs || [];
  const tab = getPrefRaw("mrTab") || "opened", sort = getPrefRaw("mrSort") || "created", q = (ui.mrQuery || "").toLowerCase();
  const counts = { opened: 0, merged: 0, closed: 0, all: all.length };
  all.forEach(m => counts[m.state] = (counts[m.state] || 0) + 1);
  let list = all.filter(m => (tab === "all" || m.state === tab) && (!q || (m.title + " !" + m.iid + " " + m.labels.join(" ") + " " + m.source).toLowerCase().includes(q)));
  list.sort((a, b) => (sort === "updated" ? b.updated - a.updated : b.created - a.created));
  const tabsHtml = [["opened", "Open"], ["merged", "Merged"], ["closed", "Closed"], ["all", "All"]].map(([k, l]) => `<button class="mrtab ${tab === k ? "on" : ""}" data-mrtab="${k}">${l}<span class="n">${counts[k] || 0}</span></button>`).join("");
  return `<div class="pagehead"><h1>${mrWord()}</h1><span class="sub">${esc(gl.user || "")} · ${esc((isGitHub() ? conf("github.repo") : conf("gitlab.project")) || "")}</span></div>
    <div class="mrbar"><div class="mrtabs">${tabsHtml}</div>
      <input class="search" id="mrSearch" placeholder="Search title, !number, label, branch" value="${esc(ui.mrQuery || "")}">
      <select id="mrSort" class="mrsort"><option value="created" ${sort === "created" ? "selected" : ""}>Created date</option><option value="updated" ${sort === "updated" ? "selected" : ""}>Updated date</option></select>
      <span class="muted mrfetched">${gl.fetched ? "updated " + ago(gl.fetched) : ""}</span>
      <button class="iconbtn ${ui.refreshing ? "spin" : ""}" id="taskRefresh2" title="Update from ${hostName()} now" ${ui.refreshing ? "disabled" : ""}><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 4v5h-5"/></svg></button></div>
    ${gl.error ? `<div class="err mb-3">${esc(gl.error)}</div>` : ""}
    <div class="panel list mrlist">${list.slice(0, 100).map(mrRow).join("") || '<div class="empty">No merge requests here.</div>'}</div>
    ${list.length > 100 ? `<div class="muted mt-2 fs-sm">Showing the latest 100 of ${list.length}.</div>` : ""}`;
}
