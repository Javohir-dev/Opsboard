const MRD = { cache: {}, error: {}, loading: null };
const LARGE_DIFF = 600;

function loadMr(iid, fresh = false) {
  if (MRD.loading === iid) return;
  MRD.loading = iid;
  fetch(`/api/mr?iid=${iid}${fresh ? "&fresh=1" : ""}`, { cache: "no-store" })
    .then(r => r.json())
    .then(r => { if (r.ok) { MRD.cache[iid] = r.mr; delete MRD.error[iid]; } else MRD.error[iid] = r.error; })
    .catch(() => { MRD.error[iid] = "dashboard server is not running"; })
    .finally(() => { MRD.loading = null; if (route().page === "mr") render(); });
}

function md(text) {
  return String(text || "").split(/```/).map((part, i) => {
    if (i % 2) return `<pre class="mdpre"><code>${esc(part.replace(/^[\w-]*\n/, ""))}</code></pre>`;
    return esc(part)
      .replace(/^#{1,6} +(.+)$/gm, '<b class="mdh">$1</b>')
      .replace(/`([^`\n]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>")
      .replace(/!?\[([^\]\n]*)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/\n/g, "<br>");
  }).join("");
}

function parseDiff(diff) {
  const rows = [];
  let o = 0, n = 0;
  for (const line of String(diff || "").split("\n")) {
    const h = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/);
    if (h) { o = +h[1]; n = +h[2]; rows.push({ kind: "hunk", text: line }); continue; }
    if (line.startsWith("\\")) continue;
    const sign = line[0];
    if (sign === "+") rows.push({ kind: "add", n: n++, text: line.slice(1) });
    else if (sign === "-") rows.push({ kind: "del", o: o++, text: line.slice(1) });
    else if (rows.length) rows.push({ kind: "ctx", o: o++, n: n++, text: line.slice(1) });
  }
  while (rows.length && rows[rows.length - 1].kind === "ctx" && rows[rows.length - 1].text === "") rows.pop();
  return rows;
}

function threadKey(t) { return t.new_line ? `${t.path}:${t.new_line}` : t.old_line ? `${t.path}:o${t.old_line}` : ""; }
function threadState(t) { return !t.resolvable ? "comment" : t.resolved ? "resolved" : "open"; }

function diffFile(iid, f, i, byLine, threadsByFile) {
  const rows = parseDiff(f.diff);
  const adds = rows.filter(r => r.kind === "add").length, dels = rows.filter(r => r.kind === "del").length;
  const key = `${iid}:${f.path}`, closed = ui.mrClosed?.has(key), big = rows.length > LARGE_DIFF && !ui.mrBig?.has(key);
  const nThreads = threadsByFile[f.path] || 0;
  const name = f.status === "renamed" && f.old_path !== f.path ? `${esc(f.old_path)} → ${esc(f.path)}` : esc(f.path);
  const head = `<div class="dfh" data-dtoggle="${esc(key)}" role="button" tabindex="0" aria-expanded="${!closed}">
    <span class="dchev ${closed ? "" : "open"}">${icon("chevron", 14)}</span><span class="dpath" translate="no">${name}</span>
    ${f.status !== "modified" ? `<span class="dstat ds-${f.status}">${f.status}</span>` : ""}
    ${nThreads ? `<span class="dthrn" title="${plural(nThreads, "thread")}">${icon("comment", 13)}${nThreads}</span>` : ""}
    <span class="dnums"><span class="dadd">+${adds}</span> <span class="ddel">−${dels}</span></span></div>`;
  let body = "";
  if (!closed) {
    if (!rows.length) body = `<div class="dnote">${f.too_large ? "This diff is too large or binary to show here." : "No changes to show."} <a href="${esc(MRD.cache[iid]?.url || "#")}" target="_blank">Open in ${hostName()}</a></div>`;
    else if (big) body = `<div class="dnote">Large diff · ${rows.length} lines <button class="linkbtn" data-dbig="${esc(key)}">Show it</button></div>`;
    else body = `<table class="dtable"><tbody>${rows.map(r => {
      if (r.kind === "hunk") return `<tr class="dh"><td class="dn"></td><td class="dn"></td><td class="dc">${esc(r.text)}</td></tr>`;
      const ln = r.kind === "del" ? `${f.path}:o${r.o}` : `${f.path}:${r.n}`;
      const ts = byLine[ln] || [];
      const mark = ts.length ? `<button class="dmark ${ts.some(t => threadState(t) === "open") ? "open" : "resolved"}" data-goto-thread="${esc(ts[0].id)}" title="${plural(ts.length, "thread")}">${icon("comment", 12)}</button>` : "";
      return `<tr class="dl d-${r.kind}" data-ln="${esc(ln)}"><td class="dn">${r.o ?? ""}</td><td class="dn">${r.n ?? ""}${mark}</td><td class="dc"><span class="dsg">${r.kind === "add" ? "+" : r.kind === "del" ? "−" : " "}</span>${esc(r.text)}</td></tr>`;
    }).join("")}</tbody></table>`;
  }
  return `<div class="dfile" id="df-${i}" data-file="${esc(f.path)}">${head}${body}</div>`;
}

const avatarOf = name => `<span class="avatar" title="${esc(name)}">${esc(initials(name || "?"))}</span>`;
function noteHtml(n, withHead = true) {
  return `<div class="thnote">${withHead ? avatarOf(n.author) : ""}<div class="grow">${withHead ? `<div class="thby"><b>${esc(n.author)}</b>${n.username ? `<span class="muted">@${esc(n.username)}</span>` : ""}<span class="muted" title="${esc(fmtDateTime(n.created))}">${ago(n.created)}</span></div>` : ""}<div class="thbody">${md(n.body)}</div></div></div>`;
}
function threadCard(t) {
  const st = threadState(t), first = t.notes[0] || {}, rest = t.notes.slice(1), last = t.notes[t.notes.length - 1] || first;
  const line = t.new_line || t.old_line;
  const where = t.path ? `<a class="thwhere" href="#" data-goto-line="${esc(threadKey(t) || t.path)}" data-file="${esc(t.path)}" translate="no" title="${esc(t.path)}">${esc(t.path.split("/").pop())}${line ? ":" + line : ""}</a>` : `<span class="muted">the ${isGitHub() ? "pull" : "merge"} request</span>`;
  const status = st === "resolved"
    ? `<div class="thres resolved">${icon("ok", 13)}<span>Resolved${t.resolved_at ? ` ${ago(t.resolved_at)}` : ""}${t.resolved_by ? ` by <b>${esc(t.resolved_by)}</b>` : ""}</span></div>`
    : `<div class="thres open">${icon("pending", 13)}<span>Unresolved</span></div>`;
  const head = `<div class="thhead">${avatarOf(first.author)}<div class="grow"><div class="thwho"><b>${esc(first.author)}</b> ${first.username ? `<span class="muted">@${esc(first.username)}</span> ` : ""}<span class="muted">started a thread on</span> ${where} <span class="muted" title="${esc(fmtDateTime(first.created))}">${ago(first.created)}</span></div>${status}</div></div>`;
  if (st === "resolved") {
    const people = [...new Set(t.notes.map(n => n.author))].slice(0, 3);
    const label = rest.length ? `<span class="thrn">${plural(rest.length, "reply", "replies")}</span><span class="muted">Last reply by</span><b>${esc(last.author)}</b><span class="muted" title="${esc(fmtDateTime(last.created))}">${ago(last.created)}</span>` : `<span class="thrn">Show thread</span>`;
    return `<div class="thread th-resolved" id="th-${esc(t.id)}">${head}<details class="threplies"><summary><span class="dchev">${icon("chevron", 14)}</span><span class="avs">${people.map(avatarOf).join("")}</span>${label}</summary><div class="thnotes">${noteHtml(first)}${rest.map(n => noteHtml(n)).join("")}${t.url ? `<a class="thlink" href="${esc(t.url)}" target="_blank">Open in ${hostName()} →</a>` : ""}</div></details></div>`;
  }
  return `<div class="thread th-open" id="th-${esc(t.id)}">${head}<div class="thnotes">${noteHtml(first, false)}${rest.map(n => noteHtml(n)).join("")}${t.url ? `<a class="thlink" href="${esc(t.url)}" target="_blank">Open in ${hostName()} →</a>` : ""}</div></div>`;
}

function threadOrder(d) {
  const fileIdx = Object.fromEntries(d.files.map((f, i) => [f.path, i]));
  const pos = t => [t.path in fileIdx ? fileIdx[t.path] : 1e6, t.new_line || t.old_line || 0];
  return d.threads.filter(t => t.resolvable).sort((a, b) => {
    const sa = threadState(a) === "open" ? 0 : 1, sb = threadState(b) === "open" ? 0 : 1;
    if (sa !== sb) return sa - sb;
    const [fa, la] = pos(a), [fb, lb] = pos(b);
    return fa - fb || la - lb;
  });
}

function pageMr(ctx, arg) {
  const iid = parseInt(arg, 10);
  const m = (data.review?.mrs || []).find(x => x.iid === iid);
  const d = MRD.cache[iid], err = MRD.error[iid];
  if (!d && !err && MRD.loading !== iid) loadMr(iid);
  else if (d && now() - d.fetched > 120 && MRD.loading !== iid) loadMr(iid);
  const title = d?.title || m?.title || mrRef(iid);
  const url = d?.url || m?.url || "";
  const pipe = m && PIPE[m.pipeline];
  const run = m && runningRun(iid);
  const meta = m ? [
    `<span class="badge ${m.state === "opened" ? "ok" : m.state === "merged" ? "busy" : "bad"}">${m.state === "opened" ? "Open" : m.state === "merged" ? "Merged" : "Closed"}</span>`,
    `<span>${mrRef(iid)} · ${esc(m.author)} · created ${ago(m.created)}</span>`,
    `<span class="mrbr" translate="no">${esc(m.source)} → ${esc(m.target)}</span>`,
    m.conflicts ? '<span class="glbl glbl-conflict">merge conflict</span>' : "",
    m.labels.map(mrLabel).join(""),
    pipe ? `<span class="pipe p-${pipe[0]}" title="${pipe[2]}">${icon(pipe[1], 16)}</span>` : "",
    m.approved ? `<span class="mrpill okp">${icon("check", 14)}Approved</span>` : "",
  ].filter(Boolean).join("") : "";
  const actions = `<span class="h2-actions">
    <button class="iconbtn ${MRD.loading === iid ? "spin" : ""}" data-mr-refresh="${iid}" title="Update from ${hostName()} now" ${MRD.loading === iid ? "disabled" : ""}>${icon("refresh", 14)}</button>
    ${m && m.state === "opened" && canRunFix() ? (run ? `<span class="cnt running"><span class="dot busy"></span>${esc(conf("claude.fix_skill") || "fix")} ${dur(now() - run.started)}</span>` : `<button class="fixbtn" data-fix="${iid}">Run ${esc(conf("claude.fix_skill"))}</button>`) : ""}
    ${url ? `<a class="fixbtn" href="${esc(url)}" target="_blank">Open in ${hostName()}</a>` : ""}</span>`;
  const head = `<div class="mrcrumb"><a href="#/mrs">${icon("chevron", 14, "flip")}${mrWord()}</a></div>
    <div class="pagehead mrpagehead"><h1 class="mrh1">${esc(title)}</h1>${actions}</div>
    <div class="mrmeta">${meta}${d ? `<span class="muted fs-sm">updated ${ago(d.fetched)}</span>` : ""}</div>`;
  if (!d) return head + (err ? `<div class="err mt-3">${esc(err)}</div>` : `<div class="skel-page mt-3" aria-busy="true"><div class="skel skel-block"></div><div class="skel skel-block"></div></div>`);
  const byLine = {}, threadsByFile = {};
  d.threads.filter(t => t.resolvable).forEach(t => { const k = threadKey(t); if (k) (byLine[k] ||= []).push(t); if (t.path) threadsByFile[t.path] = (threadsByFile[t.path] || 0) + 1; });
  const totals = d.files.reduce((a, f) => { parseDiff(f.diff).forEach(r => { if (r.kind === "add") a[0]++; else if (r.kind === "del") a[1]++; }); return a; }, [0, 0]);
  const threads = threadOrder(d);
  const open = threads.filter(t => threadState(t) === "open").length, resolved = threads.length - open;
  const nav = `<div class="thnav" role="group" aria-label="Unresolved threads"><span class="thnc" title="${plural(open, "unresolved thread")}">${icon("comment", 15)}${open}</span><button class="thnb" data-thnav="-1" ${open ? "" : "disabled"} title="Previous unresolved thread" aria-label="Previous unresolved thread">${icon("chevron", 16, "up")}</button><button class="thnb" data-thnav="1" ${open ? "" : "disabled"} title="Next unresolved thread" aria-label="Next unresolved thread">${icon("chevron", 16, "down")}</button><button class="thnb" data-thmenu title="Thread options" aria-label="Thread options">${icon("more", 16, "vert")}</button></div>`;
  const fileList = `<details class="dlist" open><summary>${plural(d.files.length, "file")} changed <span class="dadd">+${totals[0]}</span> <span class="ddel">−${totals[1]}</span></summary>
    <div class="dlinks">${d.files.map((f, i) => `<a href="#" data-goto-file="${i}" translate="no"><span class="dstat ds-${f.status}">${f.status[0].toUpperCase()}</span>${esc(f.path)}</a>`).join("")}</div></details>`;
  return head + `<div class="mrgrid">
    <div class="mrdiff">${d.description ? `<details class="dlist mrdescbox"><summary>Description</summary><div class="mrdesc">${md(d.description)}</div></details>` : ""}${fileList}${d.files.map((f, i) => diffFile(iid, f, i, byLine, threadsByFile)).join("")}</div>
    <aside class="mrthreads"><div class="thbar"><h2>Threads<span class="count">${resolved} of ${threads.length} resolved</span></h2>${nav}</div>${threads.map(threadCard).join("") || '<div class="empty">No threads.</div>'}</aside>
  </div>`;
}

function gotoDiffLine(ln, file) {
  let row = document.querySelector(`.dtable tr[data-ln="${CSS.escape(ln)}"]`);
  if (!row && file) {
    const key = `${route().arg}:${file}`;
    ui.mrClosed?.delete(key);
    (ui.mrBig ||= new Set()).add(key);
    render();
    row = document.querySelector(`.dtable tr[data-ln="${CSS.escape(ln)}"]`);
  }
  const el = row || (file && document.querySelector(`.dfile[data-file="${CSS.escape(file)}"]`));
  if (el) { el.scrollIntoView({ block: "center", behavior: "smooth" }); blink(el); }
}

function gotoThread(tid) {
  const iid = parseInt(route().arg, 10), d = MRD.cache[iid];
  const el = $("th-" + tid);
  if (!el) return false;
  const det = el.querySelector("details.threplies");
  if (det) det.open = true;
  el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  blink(el);
  const t = d?.threads.find(x => x.id === tid);
  if (t && t.path) gotoDiffLine(threadKey(t) || t.path, t.path);
  return true;
}
function stepThread(dir) {
  const iid = parseInt(route().arg, 10), d = MRD.cache[iid];
  if (!d) return;
  const open = threadOrder(d).filter(t => threadState(t) === "open");
  if (!open.length) return;
  const cur = ui.thNav?.iid === iid ? ui.thNav.idx : -1;
  const idx = cur < 0 ? (dir > 0 ? 0 : open.length - 1) : (cur + dir + open.length) % open.length;
  ui.thNav = { iid, idx };
  gotoThread(open[idx].id);
}
function focusMrThread(iid, tid) {
  ui.mrFocus = { iid, tid };
  delete MRD.cache[iid];
  if (route().page === "mr" && parseInt(route().arg, 10) === iid) { loadMr(iid, true); render(); } else location.hash = `#/mr/${iid}`;
}
function mrAfterRender() {
  const f = ui.mrFocus;
  if (!f || parseInt(route().arg, 10) !== f.iid || !MRD.cache[f.iid]) return;
  ui.mrFocus = null;
  setTimeout(() => gotoThread(f.tid), 80);
}
function openThreadMenu(btn) {
  const menu = $("menu");
  menu.innerHTML = `<button class="mi" data-thall="1">Expand all threads</button><button class="mi" data-thall="0">Collapse resolved threads</button>`;
  menu.dataset.key = "threads";
  menu.hidden = false;
  const r = btn.getBoundingClientRect(), w = menu.offsetWidth;
  menu.style.left = Math.max(8, Math.min(innerWidth - w - 8, r.right - w)) + "px";
  menu.style.top = r.bottom + 4 + "px";
}

document.addEventListener("click", e => {
  if (route().page !== "mr") return;
  const nv = e.target.closest("[data-thnav]");
  if (nv) { stepThread(parseInt(nv.dataset.thnav, 10)); return; }
  if (e.target.closest("[data-thmenu]")) { e.stopImmediatePropagation(); $("menu").hidden || $("menu").dataset.key !== "threads" ? openThreadMenu(e.target.closest("[data-thmenu]")) : closeMenu(); return; }
  const all = e.target.closest("[data-thall]");
  if (all) { document.querySelectorAll(".thread details.threplies").forEach(x => x.open = all.dataset.thall === "1"); closeMenu(); return; }
  const tg = e.target.closest("[data-dtoggle]");
  if (tg) { const k = tg.dataset.dtoggle; ui.mrClosed ||= new Set(); ui.mrClosed.has(k) ? ui.mrClosed.delete(k) : ui.mrClosed.add(k); render(); return; }
  const big = e.target.closest("[data-dbig]");
  if (big) { (ui.mrBig ||= new Set()).add(big.dataset.dbig); render(); return; }
  const rf = e.target.closest("[data-mr-refresh]");
  if (rf) { loadMr(parseInt(rf.dataset.mrRefresh, 10), true); render(); return; }
  const gl = e.target.closest("[data-goto-line]");
  if (gl) { e.preventDefault(); e.stopPropagation(); gotoDiffLine(gl.dataset.gotoLine, gl.dataset.file); return; }
  const gf = e.target.closest("[data-goto-file]");
  if (gf) { e.preventDefault(); const el = $("df-" + gf.dataset.gotoFile); if (el) { el.scrollIntoView({ block: "start", behavior: "smooth" }); blink(el.querySelector(".dfh")); } return; }
  const gt = e.target.closest("[data-goto-thread]");
  if (gt) { const el = $("th-" + gt.dataset.gotoThread); if (el) { const det = el.querySelector("details.threplies"); if (det) det.open = true; el.scrollIntoView({ block: "nearest", behavior: "smooth" }); blink(el); } }
});
document.addEventListener("keydown", e => {
  const tg = e.target.closest?.("[data-dtoggle]");
  if (tg && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); tg.click(); }
});
