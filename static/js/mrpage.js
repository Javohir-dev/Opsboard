const MRD = { cache: {}, error: {}, loading: null };
const LARGE_DIFF = 600;
const LANG = { py: "python", xml: "xml", html: "xml", svg: "xml", js: "javascript", mjs: "javascript", jsx: "javascript", ts: "typescript", tsx: "typescript", json: "json", css: "css", scss: "scss", less: "less", md: "markdown", yml: "yaml", yaml: "yaml", sql: "sql", sh: "bash", bash: "bash", ini: "ini", cfg: "ini", toml: "ini", go: "go", rs: "rust", rb: "ruby", php: "php", java: "java", kt: "kotlin", c: "c", h: "c", cpp: "cpp", cs: "csharp", swift: "swift", lua: "lua", pl: "perl", r: "r" };
const extOf = path => { const name = path.split("/").pop(); return name.includes(".") ? name.split(".").pop().toLowerCase() : ""; };
const FICONS = {
  added: '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M12 8v8M8 12h8"/>',
  deleted: '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M8 12h8"/>',
  modified: '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="12" cy="12" r="2.2" fill="currentColor" stroke="none"/>',
  renamed: '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M8 12h8M13 9l3 3-3 3"/>',
};
const svg = (paths, size, cls = "") => `<svg class="${cls}" viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
const statusIcon = st => `<span class="fst fst-${st}" title="${st}">${svg(FICONS[st] || FICONS.modified, 14)}</span>`;
const fileIcon = path => svg('<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>', 15, `fico fx-${extOf(path) || "none"}`);
const folderIcon = () => svg('<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>', 15, "fold");
const SVG = {
  sidebar: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>',
  expand: '<path d="m7 15 5 5 5-5"/><path d="m7 9 5-5 5 5"/>',
  collapse: '<path d="m7 20 5-5 5 5"/><path d="m7 4 5 5 5-5"/>',
  copy: '<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  tree: '<path d="M3 3v12a3 3 0 0 0 3 3h4"/><path d="M3 8h7"/><rect x="13" y="4" width="8" height="6" rx="1"/><rect x="13" y="14" width="8" height="6" rx="1"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
  diff: '<path d="M12 3v14M5 10h14M5 21h14"/>',
};

function fileStats(f) {
  if (!f._stats) {
    const rows = parseDiff(f.diff);
    f._stats = { rows, adds: rows.filter(r => r.kind === "add").length, dels: rows.filter(r => r.kind === "del").length };
  }
  return f._stats;
}
function highlighted(f) {
  if (f._hl) return f._hl;
  const lang = LANG[extOf(f.path)], hl = window.hljs && lang && hljs.getLanguage(lang) ? lang : null;
  f._hl = fileStats(f).rows.map(r => {
    if (r.kind === "hunk" || !hl) return esc(r.text);
    try { return hljs.highlight(r.text, { language: hl, ignoreIllegals: true }).value; } catch (e) { return esc(r.text); }
  });
  return f._hl;
}
function viewedSet(iid) { try { return new Set(JSON.parse(localStorage.getItem("ops.viewed." + iid) || "[]")); } catch (e) { return new Set(); } }
function setViewed(iid, path, on) {
  const v = viewedSet(iid);
  on ? v.add(path) : v.delete(path);
  try { localStorage.setItem("ops.viewed." + iid, JSON.stringify([...v])); } catch (e) {}
}
const isClosed = (key, viewed) => !!ui.mrClosed?.has(key) || (viewed && !ui.mrOpened?.has(key));
function openFile(key) { ui.mrClosed?.delete(key); (ui.mrOpened ||= new Set()).add(key); }
function closeFile(key) { (ui.mrClosed ||= new Set()).add(key); ui.mrOpened?.delete(key); }
function blobUrl(m, path) {
  if (!m?.url) return "";
  return isGitHub() ? `${m.url.split("/pull/")[0]}/blob/${encodeURIComponent(m.source)}/${path}` : `${m.url.split("/-/merge_requests")[0]}/-/blob/${encodeURIComponent(m.source)}/${path}`;
}

function buildTree(files) {
  const root = { dirs: new Map(), files: [] };
  for (const f of files) {
    let node = root;
    for (const part of f.path.split("/").slice(0, -1)) {
      if (!node.dirs.has(part)) node.dirs.set(part, { dirs: new Map(), files: [] });
      node = node.dirs.get(part);
    }
    node.files.push(f);
  }
  return root;
}
function compressDir(name, node) {
  while (!node.files.length && node.dirs.size === 1) { const [n, child] = [...node.dirs][0]; name += "/" + n; node = child; }
  return [name, node];
}
function treeFiles(node, out = []) {
  for (const k of [...node.dirs.keys()].sort()) treeFiles(node.dirs.get(k), out);
  node.files.sort((a, b) => a.path.localeCompare(b.path)).forEach(f => out.push(f));
  return out;
}
function treeRows(node, depth, prefix, ctx) {
  let html = "";
  for (const k of [...node.dirs.keys()].sort()) {
    const [name, child] = compressDir(k, node.dirs.get(k));
    const path = prefix + name;
    const inner = treeRows(child, depth + 1, path + "/", ctx);
    if (!inner) continue;
    const shut = !ctx.q && ui.treeClosed?.has(path);
    html += `<div class="ftrow ftdir" data-ftdir="${esc(path)}" style="--d:${depth}" role="button" tabindex="0" aria-expanded="${!shut}"><span class="dchev ${shut ? "" : "open"}">${icon("chevron", 12)}</span>${folderIcon()}<span class="ftname" translate="no">${esc(name)}</span></div>${shut ? "" : inner}`;
  }
  for (const f of node.files) {
    if (ctx.q && !f.path.toLowerCase().includes(ctx.q)) continue;
    html += fileRow(f, depth, f.path.split("/").pop(), ctx);
  }
  return html;
}
function fileRow(f, depth, label, ctx) {
  const st = fileStats(f), seen = ctx.viewed.has(f.path);
  return `<a class="ftrow ftfile ${ui.activeFile === f.path ? "on" : ""} ${seen ? "seen" : ""}" href="#" data-goto-path="${esc(f.path)}" style="--d:${depth}" title="${esc(f.path)}">${fileIcon(f.path)}<span class="ftname" translate="no">${esc(label)}</span><span class="ftnums">${!st.rows.length && f.too_large ? '<span class="muted" title="Too large to show here">large</span>' : `<span class="dadd">+${st.adds}</span> <span class="ddel">-${st.dels}</span>`}</span>${statusIcon(f.status)}</a>`;
}
function fileTree(d, viewed) {
  const q = (ui.ftQuery || "").trim().toLowerCase();
  const flat = getPref("mrTreeFlat");
  const ctx = { q, viewed };
  const rows = flat
    ? treeFiles(buildTree(d.files)).filter(f => !q || f.path.toLowerCase().includes(q)).map(f => fileRow(f, 0, f.path, ctx)).join("")
    : treeRows(buildTree(d.files), 0, "", ctx);
  return `<aside class="ftree"><div class="fthead"><b>Files</b><span class="ftcount">${d.files.length}</span><span class="grow"></span>
      <span class="ftmode"><button class="${flat ? "on" : ""}" data-ftflat="1" title="List view" aria-label="List view">${svg(SVG.list, 15)}</button><button class="${flat ? "" : "on"}" data-ftflat="0" title="Tree view" aria-label="Tree view">${svg(SVG.tree, 15)}</button></span></div>
    <label class="ftsearch">${svg(SVG.search, 14)}<input id="ftSearch" type="search" placeholder="Search files" value="${esc(ui.ftQuery || "")}" spellcheck="false"></label>
    <div class="ftlist">${rows || '<div class="muted fs-sm ftnone">No file matches.</div>'}</div></aside>`;
}

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

function diffFile(iid, f, i, byLine, threadsByFile, viewed, m) {
  const st = fileStats(f), rows = st.rows;
  const key = `${iid}:${f.path}`, seen = viewed.has(f.path), closed = isClosed(key, seen), big = rows.length > LARGE_DIFF && !ui.mrBig?.has(key);
  const nThreads = threadsByFile[f.path] || 0;
  const name = f.status === "renamed" && f.old_path !== f.path ? `${esc(f.old_path)} → ${esc(f.path)}` : esc(f.path);
  const mode = f.a_mode && f.b_mode && f.a_mode !== f.b_mode ? `<span class="dmode">${esc(f.a_mode)} → ${esc(f.b_mode)}</span>` : "";
  const head = `<div class="dfh" data-dtoggle="${esc(key)}" role="button" tabindex="0" aria-expanded="${!closed}">
    <span class="dchev ${closed ? "" : "open"}">${icon("chevron", 14)}</span><span class="dpath" translate="no">${name}</span>
    <button class="dicon" data-copy="${esc(f.path)}" title="Copy file path" aria-label="Copy file path">${svg(SVG.copy, 14)}</button>${mode}
    <span class="grow"></span>
    ${!rows.length && f.too_large ? "" : `<span class="dnums"><span class="dadd">+${st.adds}</span> <span class="ddel">−${st.dels}</span></span>`}
    <label class="dviewed"><input type="checkbox" data-viewed="${esc(f.path)}" ${seen ? "checked" : ""}>Viewed</label>
    ${nThreads ? `<button class="dicon dthrn" data-file-thread="${esc(f.path)}" title="${plural(nThreads, "thread")}">${icon("comment", 14)}${nThreads}</button>` : ""}
    <button class="dicon" data-dmenu="${esc(f.path)}" title="More" aria-label="More">${icon("more", 16, "vert")}</button></div>`;
  let body = "";
  if (!closed) {
    if (!rows.length) body = `<div class="dnote">${f.too_large ? `${hostName()} does not send this diff through its API — it is too large or binary.` : "No changes to show."} ${blobUrl(m, f.path) ? `<a href="${esc(blobUrl(m, f.path))}" target="_blank">View file @ ${esc(m.source)}</a>` : ""}</div>`;
    else if (big) body = `<div class="dnote">Large diff · ${plural(rows.length, "line")} <button class="linkbtn" data-dbig="${esc(key)}">Show it</button></div>`;
    else {
      const code = highlighted(f);
      body = `<table class="dtable"><colgroup><col class="cn"><col class="cn"><col></colgroup><tbody>${rows.map((r, j) => {
        if (r.kind === "hunk") return `<tr class="dh"><td class="dn" colspan="2"></td><td class="dc">${code[j]}</td></tr>`;
        const ln = r.kind === "del" ? `${f.path}:o${r.o}` : `${f.path}:${r.n}`;
        const ts = byLine[ln] || [];
        const mark = ts.length ? `<button class="dmark ${ts.some(t => threadState(t) === "open") ? "open" : "resolved"}" data-goto-thread="${esc(ts[0].id)}" title="${plural(ts.length, "thread")}">${icon("comment", 12)}</button>` : "";
        return `<tr class="dl d-${r.kind}" data-ln="${esc(ln)}"><td class="dn">${r.o ?? ""}</td><td class="dn">${r.n ?? ""}${mark}</td><td class="dc hljs"><span class="dsg">${r.kind === "add" ? "+" : r.kind === "del" ? "-" : " "}</span>${code[j]}</td></tr>`;
      }).join("")}</tbody></table>`;
    }
  }
  return `<div class="dfile ${seen ? "seen" : ""}" id="df-${i}" data-file="${esc(f.path)}">${head}${body}</div>`;
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
  const files = treeFiles(buildTree(d.files));
  const totals = files.reduce((a, f) => [a[0] + fileStats(f).adds, a[1] + fileStats(f).dels], [0, 0]);
  const viewed = viewedSet(iid);
  const threads = threadOrder(d);
  const open = threads.filter(t => threadState(t) === "open").length, resolved = threads.length - open;
  const treeOn = (getPrefRaw("mrTree") ?? (innerWidth > 1100 ? "1" : "0")) === "1";
  const thOn = (getPrefRaw("mrThreads") ?? (innerWidth >= 1500 ? "1" : "0")) === "1";
  const nav = `<div class="thnav" role="group" aria-label="Unresolved threads"><span class="thnc" title="${plural(open, "unresolved thread")}">${icon("comment", 15)}${open}</span><button class="thnb" data-thnav="-1" ${open ? "" : "disabled"} title="Previous unresolved thread" aria-label="Previous unresolved thread">${icon("chevron", 16, "up")}</button><button class="thnb" data-thnav="1" ${open ? "" : "disabled"} title="Next unresolved thread" aria-label="Next unresolved thread">${icon("chevron", 16, "down")}</button><button class="thnb" data-thmenu title="Thread options" aria-label="Thread options">${icon("more", 16, "vert")}</button></div>`;
  const bar = `<div class="mrbar2">
    <button class="iconbtn ${treeOn ? "on" : ""}" data-tree-toggle title="${treeOn ? "Hide" : "Show"} file browser" aria-label="File browser" aria-pressed="${treeOn}">${svg(SVG.sidebar, 16)}</button>
    <span class="mrcmp">Compare <b translate="no">${esc(m?.target || "")}</b> and <b translate="no">${esc(m?.source || "latest version")}</b></span>
    <span class="grow"></span>
    <span class="mrstat">${svg(SVG.diff, 15)}${plural(files.length, "file")} <span class="dadd">+${totals[0]}</span> <span class="ddel">−${totals[1]}</span></span>
    <span class="mrbtns"><button class="iconbtn" data-dall="1" title="Expand all files" aria-label="Expand all files">${svg(SVG.expand, 16)}</button><button class="iconbtn" data-dall="0" title="Collapse all files" aria-label="Collapse all files">${svg(SVG.collapse, 16)}</button></span>
    <button class="iconbtn thtoggle ${thOn ? "on" : ""}" data-threads-toggle title="${thOn ? "Hide" : "Show"} threads" aria-pressed="${thOn}">${icon("comment", 15)}<span>${open}/${threads.length}</span></button>
  </div>`;
  const desc = d.description ? `<details class="dlist mrdescbox"><summary>Description</summary><div class="mrdesc">${md(d.description)}</div></details>` : "";
  return head + bar + `<div class="mrlayout ${treeOn ? "with-tree" : ""} ${thOn ? "with-threads" : ""}">
    ${treeOn ? fileTree({ files }, viewed) : ""}
    <div class="mrdiff">${desc}${files.map((f, i) => diffFile(iid, f, i, byLine, threadsByFile, viewed, m)).join("")}</div>
    ${thOn ? `<aside class="mrthreads"><div class="thbar"><h2>Threads<span class="count">${resolved} of ${threads.length} resolved</span></h2>${nav}</div>${threads.map(threadCard).join("") || '<div class="empty">No threads.</div>'}</aside>` : ""}
  </div>`;
}

function gotoDiffLine(ln, file) {
  let row = document.querySelector(`.dtable tr[data-ln="${CSS.escape(ln)}"]`);
  if (!row && file) {
    const key = `${route().arg}:${file}`;
    openFile(key);
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
  if (e.target.closest(".dviewed")) return;
  const cp = e.target.closest("[data-copy]");
  if (cp) { e.stopPropagation(); navigator.clipboard?.writeText(cp.dataset.copy).then(() => { cp.classList.add("copied"); cp.title = t("Copied"); setTimeout(() => { cp.classList.remove("copied"); cp.title = t("Copy file path"); }, 1200); }).catch(() => {}); closeMenu(); return; }
  const dm = e.target.closest("[data-dmenu]");
  if (dm) { e.stopImmediatePropagation(); openFileMenu(dm); return; }
  const ft = e.target.closest("[data-file-thread]");
  if (ft) { const iid = parseInt(route().arg, 10), d = MRD.cache[iid]; const th = d && threadOrder(d).find(x => x.path === ft.dataset.fileThread); if (th) { if (getPrefRaw("mrThreads") === "0" || !document.querySelector(".mrthreads")) { setPref("mrThreads", true); render(); } gotoThread(th.id); } return; }
  const tg = e.target.closest("[data-dtoggle]");
  if (tg) { const k = tg.dataset.dtoggle, el = tg.closest(".dfile"); el && el.querySelector(".dtable, .dnote") ? closeFile(k) : openFile(k); render(); return; }
  const tt = e.target.closest("[data-tree-toggle]");
  if (tt) { setPref("mrTree", !document.querySelector(".ftree")); render(); return; }
  const th = e.target.closest("[data-threads-toggle]");
  if (th) { setPref("mrThreads", !document.querySelector(".mrthreads")); render(); return; }
  const da = e.target.closest("[data-dall]");
  if (da) { const iid = route().arg, d = MRD.cache[parseInt(iid, 10)]; (d?.files || []).forEach(f => (da.dataset.dall === "1" ? openFile : closeFile)(`${iid}:${f.path}`)); render(); return; }
  const fl = e.target.closest("[data-ftflat]");
  if (fl) { setPref("mrTreeFlat", fl.dataset.ftflat === "1"); render(); return; }
  const fd = e.target.closest("[data-ftdir]");
  if (fd) { ui.treeClosed ||= new Set(); ui.treeClosed.has(fd.dataset.ftdir) ? ui.treeClosed.delete(fd.dataset.ftdir) : ui.treeClosed.add(fd.dataset.ftdir); render(); return; }
  const gp = e.target.closest("[data-goto-path]");
  if (gp) { e.preventDefault(); gotoFile(gp.dataset.gotoPath); return; }
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
function gotoFile(path) {
  const key = `${route().arg}:${path}`;
  const el = document.querySelector(`.dfile[data-file="${CSS.escape(path)}"]`);
  if (el && !el.querySelector(".dtable, .dnote")) { openFile(key); render(); }
  const target = document.querySelector(`.dfile[data-file="${CSS.escape(path)}"]`);
  if (!target) return;
  ui.activeFile = path;
  window.scrollTo({ top: target.getBoundingClientRect().top + scrollY - (document.querySelector(".mrbar2")?.offsetHeight || 0) - 8, behavior: "smooth" });
  blink(target.querySelector(".dfh"));
  markActiveFile();
}
function openFileMenu(btn) {
  const iid = parseInt(route().arg, 10), m = (data.review?.mrs || []).find(x => x.iid === iid), path = btn.dataset.dmenu, url = blobUrl(m, path);
  const menu = $("menu");
  menu.innerHTML = `<button class="mi" data-copy="${esc(path)}">Copy file path</button>${url ? `<a class="mi" href="${esc(url)}" target="_blank">View file @ ${esc(m.source)}</a>` : ""}`;
  menu.dataset.key = "file:" + path;
  menu.hidden = false;
  const r = btn.getBoundingClientRect(), w = menu.offsetWidth;
  menu.style.left = Math.max(8, Math.min(innerWidth - w - 8, r.right - w)) + "px";
  menu.style.top = r.bottom + 4 + "px";
}
function markActiveFile() {
  document.querySelectorAll(".ftfile.on").forEach(x => x.classList.remove("on"));
  const row = ui.activeFile && document.querySelector(`.ftfile[data-goto-path="${CSS.escape(ui.activeFile)}"]`);
  if (row) { row.classList.add("on"); const list = row.closest(".ftlist"), rr = row.getBoundingClientRect(), lr = list.getBoundingClientRect(); if (rr.top < lr.top || rr.bottom > lr.bottom) list.scrollTop += rr.top - lr.top - lr.height / 2; }
}
let spyQueued = false;
addEventListener("scroll", () => {
  if (spyQueued || route().page !== "mr") return;
  spyQueued = true;
  requestAnimationFrame(() => {
    spyQueued = false;
    const edge = (document.querySelector(".mrbar2")?.offsetHeight || 0) + 24;
    let cur = null;
    for (const f of document.querySelectorAll(".mrdiff .dfile")) { if (f.getBoundingClientRect().top <= edge) cur = f; else break; }
    const path = cur?.dataset.file || document.querySelector(".mrdiff .dfile")?.dataset.file;
    if (path && path !== ui.activeFile) { ui.activeFile = path; markActiveFile(); }
  });
}, { passive: true });
document.addEventListener("input", e => { if (e.target.id === "ftSearch") { ui.ftQuery = e.target.value; render(); } });
document.addEventListener("change", e => {
  const v = e.target.closest?.("[data-viewed]");
  if (!v) return;
  const iid = parseInt(route().arg, 10), key = `${iid}:${v.dataset.viewed}`;
  setViewed(iid, v.dataset.viewed, v.checked);
  v.checked ? closeFile(key) : openFile(key);
  render();
});
document.addEventListener("keydown", e => {
  const fd = e.target.closest?.("[data-ftdir]");
  if (fd && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); fd.click(); return; }
  const tg = e.target.closest?.("[data-dtoggle]");
  if (tg && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); tg.click(); }
});
