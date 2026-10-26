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
  ext: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
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

function mdLite(text) {
  return String(text || "").split(/```/).map((part, i) => {
    if (i % 2) return `<pre class="mdpre"><code>${esc(part.replace(/^[\w-]*\n/, ""))}</code></pre>`;
    return esc(part).replace(/^#{1,6} +(.+)$/gm, '<b class="mdh">$1</b>').replace(/`([^`\n]+)`/g, "<code>$1</code>").replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>").replace(/\n/g, "<br>");
  }).join("");
}
const MERMAID = { svg: {}, queue: new Set(), loading: false, n: 0 };
let mdBase = "";
if (window.DOMPurify) {
  DOMPurify.addHook("afterSanitizeAttributes", node => {
    for (const attr of ["href", "src"]) {
      const v = node.getAttribute?.(attr);
      if (v && v.startsWith("/") && !v.startsWith("//") && mdBase) node.setAttribute(attr, mdBase + v);
    }
    if (node.tagName === "A") { node.setAttribute("target", "_blank"); node.setAttribute("rel", "noopener"); }
  });
}
if (window.marked) marked.use({ gfm: true, breaks: true });
const darkTheme = () => document.documentElement.dataset.theme === "dark" || (document.documentElement.dataset.theme !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
function md(text, base = "") {
  if (!window.marked || !window.DOMPurify) return mdLite(text);
  mdBase = base;
  let html;
  try { html = DOMPurify.sanitize(marked.parse(String(text || "")), { FORBID_TAGS: ["style", "form", "input", "button", "textarea", "select"], FORBID_ATTR: ["style"] }); } catch (e) { return mdLite(text); }
  return html.replace(/<pre><code class="language-mermaid">([\s\S]*?)<\/code><\/pre>/g, (_, code) => {
    const src = new DOMParser().parseFromString(code, "text/html").documentElement.textContent;
    const key = (darkTheme() ? "d:" : "l:") + src;
    if (MERMAID.svg[key]) return `<div class="mdmermaid">${MERMAID.svg[key]}</div>`;
    if (MERMAID.svg[key] !== false) { MERMAID.queue.add(key); drawMermaid(); }
    return `<pre class="mdpre"><code>${code}</code></pre>`;
  });
}
function drawMermaid() {
  if (MERMAID.loading) return;
  MERMAID.loading = true;
  const ready = window.mermaid ? Promise.resolve() : new Promise((ok, fail) => { const sc = document.createElement("script"); sc.src = "/static/vendor/mermaid.min.js"; sc.onload = ok; sc.onerror = fail; document.head.appendChild(sc); });
  ready.then(async () => {
    while (MERMAID.queue.size) {
      const key = [...MERMAID.queue][0];
      MERMAID.queue.delete(key);
      mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: key.startsWith("d:") ? "dark" : "default" });
      try { MERMAID.svg[key] = (await mermaid.render("mmd" + ++MERMAID.n, key.slice(2))).svg; } catch (e) { MERMAID.svg[key] = false; }
    }
  }).catch(() => {}).finally(() => { MERMAID.loading = false; ui.lastView = null; if (route().page === "mr") render(); });
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
  return `<div class="thnote">${withHead ? avatarOf(n.author) : ""}<div class="grow">${withHead ? `<div class="thby"><b>${esc(n.author)}</b>${n.username ? `<span class="muted">@${esc(n.username)}</span>` : ""}<span class="muted" title="${esc(fmtDateTime(n.created))}">${ago(n.created)}</span></div>` : ""}<div class="thbody md">${md(n.body, ui.mrBase || "")}</div></div></div>`;
}
function diffSnippet(t, before = 10) {
  const iid = parseInt(route().arg, 10), d = MRD.cache[iid];
  const f = d?.files.find(x => x.path === t.path);
  if (!f) return "";
  const rows = fileStats(f).rows, code = highlighted(f);
  const at = rows.findIndex(r => t.new_line ? r.n === t.new_line && r.kind !== "del" : r.o === t.old_line && r.kind !== "add");
  if (at < 0) return "";
  let from = at;
  while (from > 0 && at - from < before && rows[from - 1].kind !== "hunk") from--;
  const body = rows.slice(from, at + 1).map((r, k) => `<tr class="dl d-${r.kind}${from + k === at ? " dat" : ""}"><td class="dn">${r.o ?? ""}</td><td class="dn">${r.n ?? ""}</td><td class="dc hljs"><span class="dsg">${r.kind === "add" ? "+" : r.kind === "del" ? "-" : " "}</span>${code[from + k]}</td></tr>`).join("");
  return `<div class="thsnip"><div class="thsniph"><a href="#" data-goto-line="${esc(threadKey(t) || t.path)}" data-file="${esc(t.path)}" translate="no">${esc(t.path)}</a><button class="dicon" data-copy="${esc(t.path)}" title="Copy file path" aria-label="Copy file path">${svg(SVG.copy, 14)}</button></div><table class="dtable"><colgroup><col class="cn"><col class="cn"><col></colgroup><tbody>${body}</tbody></table></div>`;
}
function replyBox(t) {
  const iid = parseInt(route().arg, 10), m = (data.review?.mrs || []).find(x => x.iid === iid);
  if (!m || m.state !== "opened" || !t.resolvable) return "";
  return `<div class="threply"><textarea data-reply-box="${esc(t.id)}" rows="1" placeholder="Reply…"></textarea><div class="threplybtns"><span class="fmsg" id="rmsg-${esc(t.id)}"></span><button class="fixbtn" data-reply="${esc(t.id)}">Reply</button>${t.resolved ? "" : `<button class="fixbtn" data-resolve="${esc(t.id)}">Resolve thread</button>`}</div></div>`;
}

function threadCard(t, opts = {}) {
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
    return `<div class="thread th-resolved" id="th-${esc(t.id)}">${head}<details class="threplies"><summary><span class="dchev">${icon("chevron", 14)}</span><span class="avs">${people.map(avatarOf).join("")}</span>${label}</summary>${opts.snippet ? diffSnippet(t) : ""}<div class="thnotes">${noteHtml(first)}${rest.map(n => noteHtml(n)).join("")}${t.url ? `<a class="thlink" href="${esc(t.url)}" target="_blank">Open in ${hostName()} →</a>` : ""}</div>${replyBox(t)}</details></div>`;
  }
  return `<div class="thread th-open" id="th-${esc(t.id)}">${head}${opts.snippet ? diffSnippet(t) : ""}<div class="thnotes">${noteHtml(first, !!opts.snippet)}${rest.map(n => noteHtml(n)).join("")}${t.url ? `<a class="thlink" href="${esc(t.url)}" target="_blank">Open in ${hostName()} →</a>` : ""}</div>${replyBox(t)}</div>`;
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

const MR_TABS = ["overview", "commits", "pipelines", "changes", "fix"];
function mrTab() { const t = location.hash.split("/")[3]; return MR_TABS.includes(t) ? t : "overview"; }
const projectUrl = url => (url || "").split(isGitHub() ? "/pull/" : "/-/merge_requests")[0];
const REVIEW_STATE = {
  approved: `<span class="rvs ok" title="Approved">${icon("ok", 16)}</span>`,
  requested_changes: `<span class="rvs bad" title="Requested changes">${icon("warning", 16)}</span>`,
  reviewed: `<span class="rvs" title="Reviewed">${icon("comment", 15)}</span>`,
};
const STATE_LABEL = { opened: ["Open", "mrs"], merged: ["Merged", "mrs"], closed: ["Closed", "x"] };

function commitsTab(d) {
  if (!d.commits?.length) return '<div class="empty">No commits.</div>';
  const day = t => new Date(t * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  let last = "", html = "";
  for (const c of d.commits) {
    const dd = day(c.at);
    if (dd !== last) { html += `${last ? "</div>" : ""}<div class="cday">${esc(dd)}</div><div class="panel list">`; last = dd; }
    html += `<div class="crow">${avatarOf(c.author)}<div class="grow"><div class="ctitle">${esc(c.title)}</div><div class="muted fs-sm"><b class="ctext">${esc(c.author)}</b> authored <span title="${esc(fmtDateTime(c.at))}">${ago(c.at)}</span></div></div>
      <code class="cha">${esc(c.short)}</code><button class="dicon" data-copy="${esc(c.sha)}" title="Copy commit SHA" aria-label="Copy commit SHA">${svg(SVG.copy, 14)}</button>${c.url ? `<a class="dicon" href="${esc(c.url)}" target="_blank" title="Open in ${hostName()}" aria-label="Open in ${hostName()}">${svg(SVG.ext, 14)}</a>` : ""}</div>`;
  }
  return html + "</div>";
}
function pipelinesTab(d) {
  if (!d.pipelines?.length) return `<div class="empty">No ${isGitHub() ? "workflow runs" : "pipelines"}.</div>`;
  return `<div class="tbl panel"><table><thead><tr><th>Status</th><th>${isGitHub() ? "Workflow" : "Pipeline"}</th><th>Ref</th><th>Trigger</th><th class="num">Created</th></tr></thead><tbody>${d.pipelines.map(p => {
    const st = PIPE[p.status] || ["skip", "skipped", p.status];
    return `<tr><td><span class="pstat p-${st[0]}">${icon(st[1], 16)}${esc(p.status)}</span></td><td>${p.url ? `<a href="${esc(p.url)}" target="_blank">#${esc(p.id)}</a>` : "#" + esc(p.id)}</td><td><span class="mono">${esc(p.ref)}</span> <code class="cha">${esc(p.sha)}</code></td><td class="muted">${esc(p.source)}</td><td class="num" title="${esc(fmtDateTime(p.at))}">${ago(p.at)}</td></tr>`;
  }).join("")}</tbody></table></div>`;
}
function overviewTab(d, m) {
  const threads = threadOrder(d), open = threads.filter(t => threadState(t) === "open").length;
  const pipe = d.pipelines?.[0], pst = pipe && (PIPE[pipe.status] || ["skip", "skipped", pipe.status]);
  const widget = [
    pipe ? `<div class="wrow"><span class="pstat p-${pst[0]}">${icon(pst[1], 18)}</span><span>${isGitHub() ? "Workflow" : "Pipeline"} ${pipe.url ? `<a href="${esc(pipe.url)}" target="_blank">#${esc(pipe.id)}</a>` : "#" + esc(pipe.id)} <b>${esc(pipe.status)}</b> <span class="muted">for <code class="cha">${esc(pipe.sha)}</code> ${ago(pipe.at)}</span></span></div>` : "",
    m ? `<div class="wrow">${m.approved ? `<span class="wic ok">${icon("ok", 18)}</span><span>Approved by <b>${esc(m.approved_by.join(", "))}</b></span>` : `<span class="wic">${icon("pending", 18)}</span><span class="muted">Not approved yet</span>`}</div>` : "",
    threads.length ? `<div class="wrow"><span class="wic ${open ? "warn" : "ok"}">${icon(open ? "comment" : "ok", 18)}</span><span>${open ? `<b>${plural(open, "unresolved thread")}</b>` : "All threads resolved"} <span class="muted">· ${threads.length - open} of ${threads.length} resolved</span></span></div>` : "",
    m?.conflicts ? `<div class="wrow"><span class="wic bad">${icon("warning", 18)}</span><span><b>Merge conflicts</b> <span class="muted">with ${esc(m.target)}</span></span></div>` : "",
  ].filter(Boolean).join("");
  const sb = d.sidebar || {};
  const face = u => u.avatar ? `<span class="avatar avimg" title="${esc(u.name)}"><img src="${esc(u.avatar)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()"><span>${esc(initials(u.name || "?"))}</span></span>` : avatarOf(u.name);
  const people = list => list?.length ? list.map(u => `<div class="sperson">${face(u)}<span class="grow">${esc(u.name)}</span>${REVIEW_STATE[u.state] || ""}</div>`).join("") : '<span class="muted">None</span>';
  const reviewers = sb.reviewers || (m?.reviewers || []).map(r => ({ name: r, state: m.approved_by.includes(r) ? "approved" : "" }));
  const time = sb.estimate || sb.spent ? [sb.spent ? `Spent <b>${esc(sb.spent)}</b>` : "", sb.estimate ? `Estimate <b>${esc(sb.estimate)}</b>` : ""].filter(Boolean).join(" · ") : '<span class="muted">No estimate or time spent</span>';
  const side = `<aside class="mrside2">
      <div class="sblock"><div class="sh">${(sb.assignees || []).length > 1 ? "Assignees" : "Assignee"}</div>${people(sb.assignees || (m ? [{ name: m.author }] : []))}</div>
      <div class="sblock"><div class="sh">${reviewers.length > 1 ? "Reviewers" : "Reviewer"}</div>${people(reviewers)}</div>
      <div class="sblock"><div class="sh">Labels</div>${m?.labels.length ? `<div class="slabels">${m.labels.map(mrLabel).join("")}</div>` : '<span class="muted">None</span>'}</div>
      <div class="sblock"><div class="sh">Milestone</div>${sb.milestone ? esc(sb.milestone) : '<span class="muted">None</span>'}</div>
      ${m?.keys?.length ? `<div class="sblock"><div class="sh">Tasks</div><div>${m.keys.map(k => `<span class="mono">${esc(k)}</span>`).join(" ")}</div></div>` : ""}
      ${isGitHub() ? "" : `<div class="sblock"><div class="sh">Time tracking</div><div>${time}</div></div>`}
      ${sb.participants?.length ? `<div class="sblock"><div class="sh">${plural(sb.participants.length, "Participant")}</div><div class="sparts">${sb.participants.map(face).join("")}</div></div>` : ""}
    </aside>`;
  return `<div class="mrov"><div class="mrovmain">
      ${d.description ? `<div class="panel md mrdesc">${md(d.description, projectUrl(d.url))}</div>` : '<div class="empty">No description.</div>'}
      ${widget ? `<div class="panel mrwidget">${widget}</div>` : ""}
      ${threads.length ? `<h2 class="mt-3">Threads<span class="count">${threads.length - open} of ${threads.length} resolved</span></h2><div class="ovthreads">${threads.map(t => threadCard(t, { snippet: true })).join("")}</div>` : ""}
    </div>${side}</div>`;
}

function pageMr(ctx, arg) {
  const iid = parseInt(arg, 10);
  const m = (data.review?.mrs || []).find(x => x.iid === iid);
  const d = MRD.cache[iid], err = MRD.error[iid];
  if (!d && !err && MRD.loading !== iid) loadMr(iid);
  else if (d && now() - d.fetched > 120 && MRD.loading !== iid) loadMr(iid);
  const title = d?.title || m?.title || mrRef(iid);
  const url = d?.url || m?.url || "";
  const run = m && runningRun(iid);
  const actions = `<span class="h2-actions">
    <button class="iconbtn ${MRD.loading === iid ? "spin" : ""}" data-mr-refresh="${iid}" title="Update from ${hostName()} now" ${MRD.loading === iid ? "disabled" : ""}>${icon("refresh", 14)}</button>
    ${m && m.state === "opened" && canRunFix() ? (run ? `<span class="cnt running"><span class="dot busy"></span>${esc(conf("claude.fix_skill") || "fix")} ${dur(now() - run.started)}</span>` : `<button class="fixbtn" data-fix="${iid}">Run ${esc(conf("claude.fix_skill"))}</button>`) : ""}
    ${url ? `<a class="fixbtn" href="${esc(url)}" target="_blank">Open in ${hostName()}</a>` : ""}</span>`;
  const tab = mrTab();
  ui.mrBase = projectUrl(d?.url || m?.url);
  const st = STATE_LABEL[m?.state] || STATE_LABEL.opened;
  const chip = b => b ? `<code class="brchip" title="${esc(b)}" translate="no">${esc(b)}</code><button class="dicon" data-copy="${esc(b)}" title="Copy branch name" aria-label="Copy branch name">${svg(SVG.copy, 14)}</button>` : "";
  const created = d?.created || m?.created;
  const sub = `<div class="mrhdr"><span class="mrstate s-${esc(m?.state || "opened")}">${icon(st[1], 14)}${m?.draft ? "Draft" : st[0]}</span><b>${esc(d?.author || m?.author || "")}</b><span class="muted">requested to merge</span>${chip(m?.source)}<span class="muted">into</span>${chip(m?.target)}${created ? `<span class="muted" title="${esc(fmtDateTime(created))}">${ago(created)}</span>` : ""}</div>`;
  const tabs = [["overview", "Overview", d?.notes], ["commits", "Commits", d?.commits?.length], ["pipelines", isGitHub() ? "Checks" : "Pipelines", d?.pipelines?.length], ["changes", "Changes", d?.files?.length]];
  const fixRuns = runsFor(iid);
  if (fixRuns.length) tabs.push(["fix", fixRuns.some(r => r.status === "running") ? `<span class="dot busy"></span>${esc(conf("claude.fix_skill") || "Fix")}` : esc(conf("claude.fix_skill") || "Fix"), fixRuns.length]);
  const allThreads = d ? threadOrder(d) : [], open = allThreads.filter(t => threadState(t) === "open").length;
  const nav = d && allThreads.length ? `<div class="thnav" role="group" aria-label="Unresolved threads"><span class="thnc" title="${plural(open, "unresolved thread")}">${icon("comment", 15)}${open}</span><button class="thnb" data-thnav="-1" ${open ? "" : "disabled"} title="Previous unresolved thread" aria-label="Previous unresolved thread">${icon("chevron", 16, "up")}</button><button class="thnb" data-thnav="1" ${open ? "" : "disabled"} title="Next unresolved thread" aria-label="Next unresolved thread">${icon("chevron", 16, "down")}</button><button class="thnb" data-thmenu title="Thread options" aria-label="Thread options">${icon("more", 16, "vert")}</button></div>` : "";
  const tabBar = `<nav class="mrtabs2" aria-label="Request sections">${tabs.map(([k, l, n]) => `<a href="#/mr/${iid}/${k}" class="${tab === k ? "on" : ""}" ${tab === k ? 'aria-current="page"' : ""}>${l}${n != null ? `<span class="n">${n}</span>` : ""}</a>`).join("")}<span class="grow"></span>${d ? `<span class="muted fs-sm">updated ${ago(d.fetched)}</span>` : ""}${nav}</nav>`;
  const head = `<div class="mrcrumb"><a href="#/mrs">${icon("chevron", 14, "flip")}${mrsPage()}</a></div>
    <div class="pagehead mrpagehead"><h1 class="mrh1">${esc(title)}</h1>${actions}</div>${sub}
    <div class="mrsticky ${ui.mrStuck ? "stuck" : ""}"><div class="mrmini"><span class="mrstate s-${esc(m?.state || "opened")}">${icon(st[1], 13)}${m?.draft ? "Draft" : st[0]}</span><b class="mrminititle">${esc(title)}</b>${chip(m?.source)}<span class="muted">into</span>${chip(m?.target)}</div>${tabBar}</div>`;
  if (!d && tab === "fix") return head + fixTab(iid, null);
  if (err && !d && !MRD.retry?.[iid]) { (MRD.retry ||= {})[iid] = setTimeout(() => { delete MRD.retry[iid]; delete MRD.error[iid]; if (route().page === "mr") render(); }, 15000); }
  const offline = err && /URLError|nodename|servname|timed out|Connection|Network is unreachable/i.test(err);
  const errBox = err ? `<div class="err mt-3 mrerr"><div class="grow">${offline ? `Could not reach ${hostName()} — check the internet connection. Trying again in a few seconds.` : esc(err)}${offline ? `<div class="muted fs-sm mt-1">${esc(err)}</div>` : ""}</div><button class="fixbtn" data-mr-retry="${iid}">Retry</button></div>` : "";
  if (!d) return head + (err ? errBox : `<div class="skel-page mt-3" aria-busy="true"><div class="skel skel-block"></div><div class="skel skel-block"></div></div>`);
  if (tab === "overview") return head + overviewTab(d, m);
  if (tab === "commits") return head + `<div class="mrcommits">${commitsTab(d)}</div>`;
  if (tab === "pipelines") return head + pipelinesTab(d);
  if (tab === "fix") return head + fixTab(iid, d);
  const byLine = {}, threadsByFile = {};
  d.threads.filter(t => t.resolvable).forEach(t => { const k = threadKey(t); if (k) (byLine[k] ||= []).push(t); if (t.path) threadsByFile[t.path] = (threadsByFile[t.path] || 0) + 1; });
  const files = treeFiles(buildTree(d.files));
  const totals = files.reduce((a, f) => [a[0] + fileStats(f).adds, a[1] + fileStats(f).dels], [0, 0]);
  const viewed = viewedSet(iid);
  const threads = allThreads, resolved = threads.length - open;
  const treeOn = (getPrefRaw("mrTree") ?? (innerWidth > 1100 ? "1" : "0")) === "1";
  const thOn = (getPrefRaw("mrThreads") ?? (innerWidth >= 1500 ? "1" : "0")) === "1";
  const bar = `<div class="mrbar2">
    <button class="iconbtn ${treeOn ? "on" : ""}" data-tree-toggle title="${treeOn ? "Hide" : "Show"} file browser" aria-label="File browser" aria-pressed="${treeOn}">${svg(SVG.sidebar, 16)}</button>
    <span class="mrcmp">Compare <b translate="no">${esc(m?.target || "")}</b> and <b translate="no">${esc(m?.source || "latest version")}</b></span>
    <span class="grow"></span>
    <span class="mrstat">${svg(SVG.diff, 15)}${plural(files.length, "file")} <span class="dadd">+${totals[0]}</span> <span class="ddel">−${totals[1]}</span></span>
    <span class="mrbtns"><button class="iconbtn" data-dall="1" title="Expand all files" aria-label="Expand all files">${svg(SVG.expand, 16)}</button><button class="iconbtn" data-dall="0" title="Collapse all files" aria-label="Collapse all files">${svg(SVG.collapse, 16)}</button></span>
    <button class="iconbtn thtoggle ${thOn ? "on" : ""}" data-threads-toggle title="${thOn ? "Hide" : "Show"} threads" aria-pressed="${thOn}">${icon("comment", 15)}<span>${open}/${threads.length}</span></button>
  </div>`;
  return head + bar + `<div class="mrlayout ${treeOn ? "with-tree" : ""} ${thOn ? "with-threads" : ""}">
    ${treeOn ? fileTree({ files }, viewed) : ""}
    <div class="mrdiff">${files.map((f, i) => diffFile(iid, f, i, byLine, threadsByFile, viewed, m)).join("")}</div>
    ${thOn ? `<aside class="mrthreads"><div class="thbar"><h2>Threads<span class="count">${resolved} of ${threads.length} resolved</span></h2></div>${threads.map(t => threadCard(t)).join("") || '<div class="empty">No threads.</div>'}</aside>` : ""}
  </div>`;
}

function gotoDiffLine(ln, file) {
  if (mrTab() !== "changes") { ui.mrPending = { ln, file }; location.hash = `#/mr/${route().arg}/changes`; return; }
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
  const el = $("th-" + tid), onChanges = mrTab() === "changes";
  if (el) {
    const det = el.querySelector("details.threplies");
    if (det) det.open = true;
    el.scrollIntoView({ block: onChanges ? "nearest" : "center", behavior: "smooth" });
    blink(el);
  }
  const t = d?.threads.find(x => x.id === tid);
  if (onChanges && t && t.path) gotoDiffLine(threadKey(t) || t.path, t.path);
  return !!el || onChanges;
}
function stepThread(dir) {
  const iid = parseInt(route().arg, 10), d = MRD.cache[iid];
  if (!d) return;
  const open = threadOrder(d).filter(t => threadState(t) === "open");
  if (!open.length) return;
  const cur = ui.thNav?.iid === iid ? ui.thNav.idx : -1;
  const idx = cur < 0 ? (dir > 0 ? 0 : open.length - 1) : (cur + dir + open.length) % open.length;
  ui.thNav = { iid, idx };
  if (!["overview", "changes"].includes(mrTab())) { ui.mrFocus = { iid, tid: open[idx].id }; location.hash = `#/mr/${iid}/overview`; return; }
  gotoThread(open[idx].id);
}
function focusMrThread(iid, tid) {
  ui.mrFocus = { iid, tid };
  delete MRD.cache[iid];
  if (route().page === "mr" && parseInt(route().arg, 10) === iid && mrTab() === "overview") { loadMr(iid, true); render(); } else location.hash = `#/mr/${iid}/overview`;
}
function mrAfterRender() {
  const pend = ui.mrPending;
  if (pend && mrTab() === "changes" && document.querySelector(".mrdiff")) { ui.mrPending = null; setTimeout(() => gotoDiffLine(pend.ln, pend.file), 80); }
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
  if (cp) { e.stopPropagation(); navigator.clipboard?.writeText(cp.dataset.copy).then(() => { const was = cp.title; cp.classList.add("copied"); cp.title = t("Copied"); setTimeout(() => { cp.classList.remove("copied"); cp.title = was; }, 1200); }).catch(() => {}); closeMenu(); return; }
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
  const rt = e.target.closest("[data-mr-retry]");
  if (rt) { const i = parseInt(rt.dataset.mrRetry, 10); delete MRD.error[i]; loadMr(i, true); render(); return; }
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

function syncMrSticky() {
  const el = document.querySelector(".mrsticky");
  if (!el) { document.documentElement.style.removeProperty("--mrstick"); return; }
  const top = parseFloat(getComputedStyle(el).top) || 0;
  const stuck = el.getBoundingClientRect().top <= top + 0.5 && scrollY > 0;
  if (stuck !== !!ui.mrStuck) { ui.mrStuck = stuck; el.classList.toggle("stuck", stuck); }
  document.documentElement.style.setProperty("--mrstick", el.offsetHeight + "px");
}
addEventListener("scroll", () => { if (route().page === "mr") syncMrSticky(); }, { passive: true });
addEventListener("resize", () => { if (route().page === "mr") syncMrSticky(); });
addEventListener("hashchange", () => { ui.mrStuck = false; });

document.addEventListener("click", async e => {
  const b = e.target.closest("[data-reply], [data-resolve]");
  if (!b || route().page !== "mr") return;
  const tid = b.dataset.reply || b.dataset.resolve, iid = parseInt(route().arg, 10);
  const box = document.querySelector(`[data-reply-box="${CSS.escape(tid)}"]`), msg = $("rmsg-" + tid);
  const text = (box?.value || "").trim(), resolve = !!b.dataset.resolve;
  if (!text && !resolve) { box?.focus(); return; }
  b.disabled = true;
  if (msg) { msg.className = "fmsg muted"; msg.textContent = t(resolve ? "Resolving…" : "Sending…"); }
  try {
    const r = await (await fetch("/api/mr-reply", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ iid, thread: tid, body: text, resolve }) })).json();
    if (!r.ok) { if (msg) { msg.className = "fmsg err"; msg.textContent = r.error; } return; }
    if (box) { box.value = ""; box.defaultValue = ""; }
    if (msg) { msg.className = "fmsg okmsg"; msg.textContent = t(resolve ? "Resolved" : "Sent"); }
    loadMr(iid, true);
  } finally { b.disabled = false; }
});
document.addEventListener("keydown", e => {
  const box = e.target.closest?.("[data-reply-box]");
  if (box && e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); document.querySelector(`[data-reply="${CSS.escape(box.dataset.replyBox)}"]`)?.click(); }
});
