function hue(id) { let h = 0; for (const c of String(id)) h = (h * 31 + c.charCodeAt(0)) % 360; return h; }
function sessTag(s) { return `<a class="sess" href="#/s/${esc(s.id)}" title="${esc(label(s))} (${esc(subLabel(s))})"><i style="background:hsl(${hue(s.id)} 65% 55%)"></i>${esc(label(s))}</a>`; }
function label(s) { return s.name_source === "user" || !s.title ? s.name : s.title; }
function subLabel(s) { return s.name_source === "user" || !s.title ? s.title : s.name; }
function shortModel(m) { return (m || "").replace("claude-", "").replace(/\[.*\]$/, ""); }

function spark(values, max, col) {
  if (!values || values.length < 2) return '<svg class="spark"></svg>';
  max = max || Math.max(...values, 1);
  const w = 200, h = 34, step = w / (values.length - 1);
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(h - 2 - (v / max) * (h - 4)).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polygon points="0,${h} ${pts} ${w},${h}" fill="${col}" opacity=".13"/><polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>`;
}
const bar = parts => `<div class="bar">${parts.map(([p, c]) => `<span style="width:${p}%;background:${c}"></span>`).join("")}</div>`;
const tile = (label, big, sub, extra = "") => `<div class="tile"><div class="label">${label}</div><div class="big">${big}</div>${extra}<div class="sub">${sub}</div></div>`;
const table = (head, rows, empty = "Nothing here.") => `<div class="tbl"><table><thead><tr>${head.map(h => typeof h === "string" ? `<th>${h}</th>` : `<th class="${h[1]}">${h[0]}</th>`).join("")}</tr></thead><tbody>${rows.join("") || `<tr><td colspan="${head.length}" class="muted">${empty}</td></tr>`}</tbody></table></div>`;

function context() {
  const containers = data.containers || [];
  const byName = Object.fromEntries(containers.map(c => [c.name, c]));
  const byIp = {};
  containers.forEach(c => c.ips.forEach(ip => byIp[ip] = c.name));
  const sizes = data.pg_sizes || {};
  const dbConns = {}, ctrConns = {};
  (data.pg?.conns || []).forEach(r => {
    const x = dbConns[r.db] ||= { total: 0, active: 0, idle: 0, tx: 0, txFor: 0, from: new Set() };
    x.total += r.count;
    if (r.state === "active") x.active += r.count;
    else if (r.state.startsWith("idle in")) { x.tx += r.count; x.txFor = Math.max(x.txFor, r.for); }
    else x.idle += r.count;
    const who = byIp[r.addr] || r.addr;
    x.from.add(who);
    const y = ctrConns[who] ||= { total: 0, dbs: new Set() };
    y.total += r.count; y.dbs.add(r.db);
  });
  const wts = Object.fromEntries((data.worktrees || []).map(w => [w.name, w]));
  const wtBySlug = Object.fromEntries((data.worktrees || []).map(w => [w.slug, w]));
  const sessions = data.sessions || [];
  sessions.forEach(s => {
    s.uContainers = s.containers.filter(x => byName[x.name]);
    s.uDbs = s.dbs.filter(x => sizes[x.name] != null);
    s.uWorktrees = s.worktrees.filter(x => wts[x.name]);
    s.running = s.agents.filter(a => a.status === "running");
    s.jobsRunning = s.jobs.filter(j => j.status === "running");
  });
  const users = kind => { const m = {}; sessions.forEach(s => s[kind].forEach(x => (m[x.name] ||= []).push(s))); return m; };
  const slugOf = slugMatcher([data.profile?.containers?.per_worktree]);
  const dbSlug = slugMatcher(data.profile?.databases?.per_worktree || []);
  const orphanCtr = containers.filter(c => (slugOf(c.name) && !wtBySlug[slugOf(c.name)]) || isLeftover(c.name));
  const orphanDb = Object.keys(sizes).filter(d => dbSlug(d) && !wtBySlug[dbSlug(d)]);
  return { byName, byIp, sizes, dbConns, ctrConns, wts, wtBySlug, sessions, slugOf, dbSlug, orphanCtr, orphanDb,
    ctrUsers: users("uContainers"), dbUsers: users("uDbs"), wtUsers: users("uWorktrees") };
}

function macTiles() {
  const m = data.mac || {}, h = data.history || {}, d = data.docker_df || {};
  const memUsedPct = 100 - (m.mem_free_pct ?? 0);
  const diskPct = pct(m.disk_used, m.disk_total), swapPct = pct(m.swap_used, m.swap_total);
  const stats = Object.values(data.docker_stats || {});
  const dockerMem = stats.reduce((a, s) => a + s.mem, 0), dockerCpu = stats.reduce((a, s) => a + s.cpu, 0);
  const rows = Object.fromEntries((d.rows || []).map(r => [r.Type, r]));
  const isMac = (m.os || "macOS") === "macOS";
  const memSub = isMac ? `pressure ${memUsedPct}% · wired ${bytes(m.mem_wired)} · compressed ${bytes(m.mem_compressed)}` : `in use ${memUsedPct}% · cache ${bytes(m.mem_cache)}`;
  const gpuSub = m.gpu == null ? "no supported GPU found" : [m.gpu_renderer != null ? `renderer ${m.gpu_renderer}%` : m.gpu_name || "", m.gpu_mem ? `in use ${bytes(m.gpu_mem)}` : ""].filter(Boolean).join(" · ");
  const powerSub = [m.power, m.battery_state, m.battery_minutes && m.battery_state === "discharging" ? `~${m.battery_minutes >= 60 ? `${Math.floor(m.battery_minutes / 60)}h ${m.battery_minutes % 60}m` : `${m.battery_minutes}m`} left` : "", m.cpu_speed_limit != null ? `CPU speed limit ${m.cpu_speed_limit}%` : "", `${m.processes || "?"} procs`].filter(Boolean).join(" · ");
  return `<section><h2>${esc(m.os || "Machine")}<span class="count">${esc([m.distro, m.chip, m.model, m.pcores && `${m.pcores}P+${m.ecores}E cores`, !m.pcores && m.ncpu && `${m.ncpu} cores`, m.mem_total && bytes(m.mem_total, 0) + " RAM"].filter(Boolean).join(" · "))}</span></h2><div class="tiles">${[
    tile("CPU", `${(m.cpu ?? 0).toFixed(0)}%`, `user ${m.cpu_user ?? 0}% · sys ${m.cpu_sys ?? 0}% · load ${(m.load || []).join(" / ")}`, spark(h.cpu, 100, color(m.cpu))),
    tile("RAM", `${bytes(m.mem_used)} <span class="muted fs-lg fw-500">/ ${bytes(m.mem_total, 0)}</span>`, memSub, bar([[pct(m.mem_used, m.mem_total), color(memUsedPct)]]) + spark(h.mem, 100, color(memUsedPct))),
    tile("Swap", bytes(m.swap_used), m.swap_total ? `of ${bytes(m.swap_total)}` : "no swap configured", bar([[swapPct, color(swapPct)]])),
    tile("GPU", m.gpu == null ? "n/a" : `${m.gpu}%`, gpuSub, spark(h.gpu, 100, "var(--busy)")),
    tile("Disk", `${bytes(m.disk_free, 0)} free`, `${bytes(m.disk_used, 0)} / ${bytes(m.disk_total, 0)}`, bar([[diskPct, color(diskPct)]])),
    tile("Network", `↓ ${bytes(m.net_in)}/s`, `↑ ${bytes(m.net_out)}/s`, spark(h.net_in, 0, "var(--accent)")),
    tile(isMac ? "Docker VM" : "Docker", `${dockerCpu.toFixed(0)}% CPU`, `${bytes(dockerMem)} of ${bytes(d.mem)} · ${d.ncpu || "?"} vCPU · v${d.version || "?"}`, bar([[pct(dockerMem, d.mem), color(pct(dockerMem, d.mem))]])),
    tile("Docker disk", rows.Images ? units(rows.Images.Size) : "—", `${units(rows.Images?.Reclaimable?.replace(/\s*\(.*\)/, "") || "?")} reclaimable · volumes ${units(rows["Local Volumes"]?.Size || "?")}`),
    tile("Power", m.battery != null ? `${m.battery}%` : m.power || "—", powerSub),
  ].join("")}</div></section>`;
}

function statusOf(s) {
  if (s.status === "busy") return `<span class="badge busy">Working · ${dur(now() - s.status_since)}</span>`;
  return `<span class="badge idle">Idle · ${dur(now() - s.status_since)}</span>`;
}
function nowLine(s) {
  if (s.doing) return `<div class="now"><span class="dot busy"></span><span class="lbl">${esc(s.doing.tool)}</span><span class="what" title="${esc(s.doing.what)}">${esc(s.doing.what)}</span><span class="when">${dur(now() - s.doing.ts)}</span></div>`;
  if (s.status === "busy") return `<div class="now"><span class="dot busy"></span><span class="lbl">Thinking…</span><span class="when">${dur(now() - s.status_since)}</span></div>`;
  const job = s.jobsRunning[0];
  if (job) return `<div class="now"><span class="dot busy"></span><span class="lbl">Waiting for background ${job.how === "monitor" ? "monitor" : "job"}</span><span class="what" title="${esc(job.description)}">${esc(job.description)}${s.jobsRunning.length > 1 ? ` <span class="muted">+${s.jobsRunning.length - 1} more</span>` : ""}</span><span class="when">${dur(now() - job.started)}</span></div>`;
  const last = s.activity[0];
  return `<div class="now"><span class="lbl">Waiting for you</span><span class="what muted">${last ? `last: ${esc(last.tool)}${last.what ? " — " + esc(last.what) : ""}` : ""}</span><span class="when">${last ? ago(last.ts) : ""}</span></div>`;
}
const AGENT_GROUPS = [
  ["running", "running", ["running"]],
  ["stalled", "stalled", ["quiet", "unknown"]],
  ["failed", "failed", ["failed"]],
  ["cancelled", "cancelled", ["killed", "stopped", "cancelled"]],
  ["done", "done", ["completed"]],
];
function agentCounts(s, withJobs) {
  const pills = AGENT_GROUPS.map(([cls, label, statuses]) => {
    const n = s.agents.filter(a => statuses.includes(a.status)).length;
    return n ? `<span class="cnt ${cls}" title="${plural(n, "agent")} ${label}"><span class="dot ${cls === "running" ? "busy" : cls === "done" ? "ok" : cls === "failed" ? "bad" : cls === "stalled" ? "warn" : "cancelled"}"></span>${n} ${label}</span>` : "";
  }).join("");
  const jobs = withJobs && s.jobsRunning.length ? `<span class="cnt job" title="background shell commands still running">${s.jobsRunning.length} job${s.jobsRunning.length > 1 ? "s" : ""}</span>` : "";
  return pills || jobs ? `<span class="counts">${pills}${jobs}</span>` : '<span class="cnt none">no agents</span>';
}
function agentStatus(a) {
  const m = { running: ["busy", "Running"], completed: ["ok", "Done"], failed: ["bad", "Failed"], killed: ["cancelled", "Cancelled"], stopped: ["cancelled", "Cancelled"], quiet: ["warn", "Stalled"], unknown: ["warn", "Stalled"] }[a.status] || ["", a.status];
  return `<span class="status"><span class="dot ${m[0]}"></span>${m[1]}</span>`;
}
function agentRow(a) {
  const done = a.status !== "running";
  const side = done ? (a.ended ? `finished ${ago(a.ended)}` : "") : `${dur(now() - a.started)}`;
  const doing = !done && a.doing ? `${a.doing.tool}: ${a.doing.what}` : "";
  return `<div class="agent ${done ? "done" : ""}" title="${esc(a.type)} · ${esc(shortModel(a.model) || "inherit")} · ${plural(a.tools ?? 0, "tool call")}${a.summary ? "\n" + esc(a.summary) : ""}">
    <span class="dot ${a.status === "running" ? "busy" : a.status === "failed" ? "bad" : ["killed", "stopped"].includes(a.status) ? "cancelled" : ["quiet", "unknown"].includes(a.status) ? "warn" : "ok"}"></span>
    <span class="an">${esc(a.description || a.type)}</span>${doing ? `<span class="ad">${esc(doing)}</span>` : ""}<span class="am">${esc(side)}</span></div>`;
}
function usesChips(s, ctx, limit = 4) {
  const out = [];
  const add = (items, fmt) => { items.slice(0, limit).forEach(x => out.push(fmt(x))); if (items.length > limit) out.push(`<span class="chip muted">+${items.length - limit}</span>`); };
  add(s.uContainers, x => { const c = ctx.byName[x.name]; return `<span class="chip" title="container · ${esc(c.state)} · referenced ${ago(x.last)}"><span class="dot ${c.state === "running" ? "ok" : "bad"}"></span>${esc(ctx.slugOf(x.name) || x.name)}</span>`; });
  add(s.uDbs, x => { const c = ctx.dbConns[x.name]; return `<span class="chip" title="database · ${bytes(ctx.sizes[x.name])} · ${c ? c.total + " connections" : "no connections"} · referenced ${ago(x.last)}"><span class="ic">DB</span>${esc(x.name)}</span>`; });
  return out.join("") || '<span class="muted">nothing yet</span>';
}

const LIVE = ["running", "quiet", "unknown"];
const isLive = x => LIVE.includes(x.status);
function finishedToggle(key) {
  return `<label class="minisw" title="Show finished, failed and cancelled ones too"><input type="checkbox" data-pref="${key}" ${getPref(key) ? "checked" : ""}><span class="tog"></span>show done & cancelled</label>`;
}

function sessionCard(s, ctx) {
  const showFinished = getPref("showDoneAgents");
  const live = s.agents.filter(isLive);
  const done = s.agents.filter(a => !isLive(a));
  const open = expanded.has(s.id);
  const shownDone = !showFinished ? [] : open ? done : done.slice(0, Math.max(0, 3 - live.length));
  const tok = s.tokens || {};
  return `<div class="card ${s.status === "busy" ? "busy" : ""}">
    <div class="top"><span class="dot ${s.status === "busy" ? "busy" : "ok"}"></span><a class="name" href="#/s/${esc(s.id)}">${esc(label(s))}</a><span class="ml-auto">${statusOf(s)}</span></div>
    ${subLabel(s) ? `<div class="title">${esc(subLabel(s))}</div>` : ""}
    ${nowLine(s)}
    <div class="block"><div class="bh"><span class="k">Agents</span><span class="v">${agentCounts(s, true)}</span></div>
      ${live.length || shownDone.length ? `<div class="agents">${live.map(agentRow).join("")}${shownDone.map(agentRow).join("")}</div>` : ""}
      ${showFinished && (done.length > shownDone.length || open && done.length > 3) ? `<div class="more" data-expand="${esc(s.id)}">${open ? "Show less" : `Show ${done.length - shownDone.length} more finished`}</div>` : ""}
    </div>
    <div class="block"><div class="bh"><span class="k">Uses</span></div><div class="uses">${usesChips(s, ctx)}</div></div>
    ${s.skills.length ? `<div class="block"><div class="bh"><span class="k">Skills</span></div><div class="uses">${s.skills.slice(0, 5).map(x => `<span class="chip" title="used ${x.count}× · last ${ago(x.last)}">${esc(x.name)}</span>`).join("")}</div></div>` : ""}
    <div class="foot"><span>${esc(shortModel(s.model))}</span><span>up <b>${dur(now() - s.started)}</b></span><span>RAM <b>${bytes(s.rss)}</b></span><span title="input ${num(tok.input_tokens)} · cache read ${num(tok.cache_read_input_tokens)} · cache write ${num(tok.cache_creation_input_tokens)}">output <b>${num(tok.output_tokens)}</b> tokens</span><a class="open" href="#/s/${esc(s.id)}">Details →</a></div>
  </div>`;
}

function pageOverview(ctx) {
  const pg = data.pg || {}, m = data.mac || {};
  const running = (data.containers || []).filter(c => c.state === "running");
  const attn = [];
  if (pct(m.swap_used, m.swap_total) > 80) attn.push(["warn", `Swap is ${bytes(m.swap_used)} of ${bytes(m.swap_total)} — RAM is short`, "#/processes"]);
  if (ctx.orphanCtr.length) attn.push(["warn", `${ctx.orphanCtr.length} container(s) without a worktree: ${ctx.orphanCtr.map(c => c.name).join(", ")}`, "#/docker"]);
  if (ctx.orphanDb.length) attn.push(["warn", `${ctx.orphanDb.length} worktree database(s) whose worktree is gone (${bytes(ctx.orphanDb.reduce((a, d) => a + ctx.sizes[d], 0))})`, "#/postgres"]);
  Object.entries(ctx.dbConns).filter(([, c]) => c.tx && c.txFor > 60).forEach(([db, c]) => attn.push(["bad", `${db}: ${c.tx} connection(s) idle in transaction for ${dur(c.txFor)}`, "#/postgres"]));
  (pg.active || []).filter(a => a.secs > 30 && a.state === "active").forEach(a => attn.push(["bad", `Query on ${a.db} running ${dur(a.secs)}`, "#/postgres"]));
  if (pg.waiting_locks) attn.push(["bad", `${pg.waiting_locks} lock(s) waiting in Postgres`, "#/postgres"]);
  if (pg.ok === false) attn.push(["bad", "Postgres container is not reachable", "#/postgres"]);
  const totalConns = Object.values(ctx.dbConns).reduce((a, c) => a + c.total, 0);
  const fetched = Math.min(data.jira?.fetched || Infinity, data.review?.fetched || Infinity);
  const refreshBtn = `<span class="refreshwrap"><span class="muted">${isFinite(fetched) ? "updated " + ago(fetched) : ""}</span><button class="iconbtn ${ui.refreshing ? "spin" : ""}" id="taskRefresh2" title="${hasJira() ? `Update from Jira and ${hostName()} now` : `Update from ${hostName()} now`}" aria-label="Update from Jira and GitLab" ${ui.refreshing ? "disabled" : ""}><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 4v5h-5"/></svg></button></span>`;
  const openMrs = (data.review?.mrs || []).filter(m => m.state === "opened").sort((x, y) => y.created - x.created);
  const mrBlock = data.review?.mrs ? `<section><h2>${mrWord()} · open<span class="count">${openMrs.length || ""}</span><span class="h2-actions">${refreshBtn}<a href="#/mrs">Open ${mrsPage()} →</a></span></h2><div class="panel list mrlist">${openMrs.map(mrRow).join("") || '<div class="empty">No open merge requests.</div>'}</div></section>` : "";
  const busy = ctx.sessions.filter(x => x.status === "busy").length;
  return `<div class="pagehead"><h1>Overview</h1><span class="sub">${plural(ctx.sessions.length, "live session")} · ${busy} working · ${plural(openMrs.length, "open request")}</span></div>` + (showUsage() ? macTiles() : "") + mrBlock + notesTodoSection() + `<div class="cols">
    <section><h2>Sessions<span class="count">${ctx.sessions.length} live</span></h2><div class="panel list">${ctx.sessions.map(s => `<a class="item" href="#/s/${esc(s.id)}"><span class="dot ${s.status === "busy" ? "busy" : "ok"}"></span><div class="grow"><div class="t">${esc(label(s))}</div><div class="s">${s.doing ? esc(s.doing.tool + " — " + s.doing.what) : s.status === "busy" ? "Thinking…" : s.jobsRunning.length ? "Waiting for background job — " + esc(s.jobsRunning[0].description) : esc(subLabel(s) || "Waiting for you")}</div></div><div class="r stack-end">${agentCounts(s, true)}<span>${s.status === "busy" ? "working" : "idle"} ${dur(now() - s.status_since)}</span></div></a>`).join("") || '<div class="empty">No live sessions.</div>'}</div></section>
    <section><h2>System alerts<span class="count">${attn.length || ""}</span></h2><div class="panel list attn">${attn.map(([lvl, text, href]) => `<a class="item" href="${href}"><span class="dot ${lvl}"></span><div class="grow"><div class="t">${esc(text)}</div></div></a>`).join("") || '<div class="empty">All good.</div>'}</div>
      <h2 class="mt-7">Stack</h2><div class="panel list">
        <a class="item" href="#/docker"><div class="grow"><div class="t">${running.length} containers running</div><div class="s">${running.filter(c => ctx.slugOf(c.name)).length} QA worktree servers</div></div><div class="r">${bytes(Object.values(data.docker_stats || {}).reduce((a, s) => a + s.mem, 0))}</div></a>
        <a class="item" href="#/postgres"><div class="grow"><div class="t">${totalConns} / ${pg.max_connections || "?"} Postgres connections</div><div class="s">${(pg.active || []).length} active queries · ${Object.keys(ctx.sizes).length} databases</div></div><div class="r">${bytes(Object.values(ctx.sizes).reduce((a, b) => a + b, 0))}</div></a>
        <a class="item" href="#/worktrees"><div class="grow"><div class="t">${(data.worktrees || []).length} worktrees</div><div class="s">${(data.worktrees || []).filter(w => w.dirty).length} with uncommitted changes</div></div></a>
      </div></section></div>` + runsSection();
}

function pageSessions(ctx) {
  return `<div class="pagehead"><h1>Sessions</h1><span class="sub">${ctx.sessions.length} live · ${ctx.sessions.filter(s => s.status === "busy").length} working · ${plural(ctx.sessions.reduce((a, s) => a + s.running.length, 0), "agent")} running</span></div>
    <div class="cards">${ctx.sessions.map(s => sessionCard(s, ctx)).join("") || '<div class="muted">No live Claude sessions.</div>'}</div>`;
}

function pageSession(ctx, id) {
  const s = ctx.sessions.find(x => x.id === id);
  if (!s) return `<div class="pagehead"><h1>Session ended</h1><a href="#/sessions">← all sessions</a></div>`;
  const tok = s.tokens || {};
  const liveAgents = s.agents.filter(isLive), liveJobs = s.jobs.filter(isLive);
  const agentList = getPref("showDoneAgents") ? s.agents : liveAgents, jobList = getPref("showDoneJobs") ? s.jobs : liveJobs;
  const hiddenNote = (n, what) => n ? ` ${n} finished ${what} hidden.` : "";
  const agents = agentList.map(a => `<tr><td class="nowrap">${agentStatus(a)}</td><td><div class="main">${esc(a.description || a.type)}</div><div class="subt">${a.status === "running" && a.doing ? esc(a.doing.tool + ": " + a.doing.what) : esc(a.summary)}</div></td><td class="nowrap">${esc(a.type)}<div class="subt">${esc(shortModel(a.model) || "inherit")}${a.background ? " · background" : ""}</div></td><td class="num">${ago(a.started)}</td><td class="num">${dur((a.status === "running" ? now() : a.ended || a.last_write) - a.started)}</td><td class="num">${a.usage?.toolUses ?? a.tools ?? 0}</td><td class="num">${a.usage?.totalTokens != null ? num(a.usage.totalTokens) : "—"}</td></tr>`);
  const jobs = jobList.map(j => `<tr><td class="nowrap">${agentStatus(j)}</td><td>${esc(j.description)}<div class="subt">${esc(j.summary)}</div></td><td class="nowrap muted">${esc(j.how || "")}</td><td class="num">${ago(j.started)}</td><td class="num">${dur((j.status === "running" ? now() : j.ended) - j.started)}</td></tr>`);
  const ctrs = s.uContainers.map(x => { const c = ctx.byName[x.name], st = (data.docker_stats || {})[x.name] || {}; const port = c.ports.find(p => p.container === "8069"); return `<tr><td><div class="main mono">${esc(x.name)}</div></td><td class="nowrap"><span class="status"><span class="dot ${c.state === "running" ? "ok" : "bad"}"></span>${esc(c.state)}</span></td><td class="num">${st.mem ? bytes(st.mem) : "—"}</td><td>${port ? `<a href="http://127.0.0.1:${port.host}/web/login" target="_blank">:${port.host} ↗</a>` : ""}</td><td class="num muted">${ago(x.last)}</td></tr>`; });
  const dbs = s.uDbs.map(x => { const c = ctx.dbConns[x.name]; return `<tr><td class="mono">${esc(x.name)}</td><td class="num">${bytes(ctx.sizes[x.name])}</td><td class="num">${c ? c.total : 0}</td><td class="num muted">${ago(x.last)}</td></tr>`; });
  const wts = s.uWorktrees.map(x => { const w = ctx.wts[x.name]; return `<tr><td><div class="main">${esc(x.name)}</div><div class="subt mono">${esc(w.branch)}</div></td><td class="num">${w.dirty || ""}</td><td class="num muted">${ago(x.last)}</td></tr>`; });
  const run = s.run_id && (data.runs || []).find(r => r.id === s.run_id && r.status === "running");
  return `<div class="pagehead"><a href="#/sessions">← Sessions</a><h1>${esc(label(s))}</h1>${statusOf(s)}<span class="sub">${esc(subLabel(s))}</span>${run ? `<span class="h2-actions ml-auto">${run.iid ? `<a class="fixbtn" href="#/mr/${run.iid}/fix">Show progress</a>` : ""}<button class="fixbtn btn-stop" data-stop="${esc(run.id)}">${icon("x", 14)}Stop</button></span>` : ""}</div>
    <section class="mb-4">${nowLine(s)}</section>
    <section><div class="tiles">
      ${tile("Uptime", dur(now() - s.started), `pid ${s.pid} · ${esc(s.entrypoint)} · v${esc(s.version)}`)}
      ${tile("Model", esc(shortModel(s.model)) || "—", esc(s.branch || ""))}
      ${tile("CPU / RAM", `${s.cpu}%`, `${bytes(s.rss)} incl. ${s.children.length} child processes`)}
      ${tile("Output tokens", num(tok.output_tokens), `cache read ${num(tok.cache_read_input_tokens)} · cache write ${num(tok.cache_creation_input_tokens)}`)}
      ${tile("Agents", `${s.running.length} running`, `${s.agents.length} launched · ${plural(s.jobsRunning.length, "background job")} running`, `<div class="my-2">${agentCounts(s, false)}</div>`)}
    </div></section>
    ${promptsSection(s)}
    <section><h2>Agents<span class="count">${liveAgents.length} running${s.agents.length ? ` · ${s.agents.length} total` : ""}</span>${s.agents.length ? finishedToggle("showDoneAgents") : ""}</h2>${table(["Status", "Agent", "Type / model", ["Started", "num"], ["Duration", "num"], ["Tool calls", "num"], ["Tokens", "num"]], agents, s.agents.length ? "No agents running." + hiddenNote(s.agents.length - liveAgents.length, "agents") : "This session has not launched agents.")}</section>
    ${s.jobs.length ? `<section><h2>Background jobs<span class="count">${liveJobs.length} running · ${s.jobs.length} total</span>${finishedToggle("showDoneJobs")}</h2>${table(["Status", "Job", "How", ["Started", "num"], ["Duration", "num"]], jobs, "No background jobs running." + hiddenNote(s.jobs.length - liveJobs.length, "jobs"))}</section>` : ""}
    <div class="cols">
      <section><h2>Containers</h2>${table(["Container", "State", ["Memory", "num"], "Open", ["Last used", "num"]], ctrs, "No containers referenced.")}</section>
      <section><h2>Databases</h2>${table(["Database", ["Size", "num"], ["Conns", "num"], ["Last used", "num"]], dbs, "No databases referenced.")}</section>
    </div>
    <div class="cols">
      <section><h2>Worktrees</h2>${table(["Worktree", ["Changed", "num"], ["Last used", "num"]], wts, "No worktrees referenced.")}</section>
      <section><h2>Skills and tools</h2><div class="panel pad stack-3">
        ${[["Skills", s.skills], ["MCP servers", s.mcp], ["invoke", s.invoke]].filter(([, list]) => list.length).map(([k, list]) => `<div class="block"><div class="bh"><span class="k">${k}</span></div><div class="uses">${list.map(x => `<span class="chip" title="${x.count}× · last ${ago(x.last)}">${esc(x.name)}<span class="ic">${x.count}</span></span>`).join("") || '<span class="muted">—</span>'}</div></div>`).join("")}
        <div class="block"><div class="bh"><span class="k">Tools</span></div><div class="uses">${s.tools.map(([n, c]) => `<span class="chip">${esc(n.startsWith("mcp__") ? n.split("__").slice(2).join("__") : n)}<span class="ic">${c}</span></span>`).join("")}</div></div>
      </div></section>
    </div>
    <section><h2>Recent activity</h2><div class="panel timeline">${s.activity.map(a => `<div class="row"><span class="when">${dur(now() - a.ts)}</span><span class="tool">${esc(a.tool)}</span><span class="what" title="${esc(a.what)}">${esc(a.what)}</span></div>`).join("") || '<div class="empty">No activity yet.</div>'}</div></section>
    <details ${expanded.has("cmd:" + s.id) ? "open" : ""} data-key="cmd:${esc(s.id)}"><summary>Shell commands (${s.bash.length})</summary><div class="panel">${s.bash.map(b => `<div class="cmd"><div class="h">${ago(b.ts)} · ${esc(b.desc)}</div>${esc(b.cmd)}</div>`).join("")}</div></details>
    <details ${s.children.length ? "" : "hidden"} ${expanded.has("proc:" + s.id) ? "open" : ""} data-key="proc:${esc(s.id)}" class="mt-4"><summary>Child processes (${s.children.length})</summary>${table(["Process", ["CPU", "num"], ["RAM", "num"], ["Running", "num"]], s.children.map(p => `<tr><td><div class="main">${esc(p.name)} <span class="muted">${p.pid}</span></div><div class="subt mono clamp" title="${esc(p.args)}">${esc(p.args)}</div></td><td class="num">${p.cpu.toFixed(1)}%</td><td class="num">${bytes(p.rss)}</td><td class="num">${esc(p.etime)}</td></tr>`))}</details>`;
}

function clock(t) {
  const d = new Date(t * 1000), today = new Date();
  const hm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  return d.toDateString() === today.toDateString() ? hm : `${d.toLocaleDateString([], { day: "2-digit", month: "short" })} ${hm}`;
}
function took(s, p, i) {
  const live = i === 0 && s.status === "busy";
  const secs = (live ? now() : p.end) - p.ts;
  return `<span class="took ${live ? "live" : secs > 900 ? "long" : ""}">${live ? "running " : "took "}${dur(secs)}</span>`;
}
function promptRow(s, p, i) {
  const key = `pt:${s.id}:${p.ts}`;
  const bits = [p.tools ? `${p.tools} tool call${p.tools > 1 ? "s" : ""}` : "no tools", p.agents ? `${p.agents} agent${p.agents > 1 ? "s" : ""}` : "", p.images ? `${p.images} image${p.images > 1 ? "s" : ""}` : "", p.queued ? "sent while working" : "", p.interrupted ? "interrupted" : ""].filter(Boolean);
  return `<div class="p"><span class="when" title="${esc(new Date(p.ts * 1000).toLocaleString())}">${clock(p.ts)}</span>
    <span class="txt ${expanded.has(key) ? "full" : ""}" data-expand="${esc(key)}" title="click to expand">${esc(p.text || "(image only)")}</span>
    <span class="meta">${esc(bits.join(" · "))}${took(s, p, i)}</span></div>`;
}
function promptsSection(s) {
  const ps = s.prompts || [];
  if (!ps.length) return "";
  const all = expanded.has("prompts:" + s.id);
  const total = ps.reduce((a, p, i) => a + ((i === 0 && s.status === "busy" ? now() : p.end) - p.ts), 0);
  return `<section><h2>Your messages<span class="count">${ps.length}</span><span class="count muted fw-500">Claude worked ${dur(total)} in total</span></h2>
    <div class="panel prompts">${(all ? ps : ps.slice(0, 1)).map((p, i) => promptRow(s, p, i)).join("")}</div>
    ${ps.length > 1 ? `<div class="more" data-expand="prompts:${esc(s.id)}">${all ? "Show only the last message" : `Show all ${ps.length} messages`}</div>` : ""}</section>`;
}
