const SRC_LABEL = { user: "set by you", auto: "detected", agent: "set by Claude", env: "env var", default: "default" };
function srcBadge(key) {
  const e = data.config?.[key] || {};
  const low = e.source === "auto" && e.confidence != null && e.confidence < 0.8;
  const title = [e.from ? "from: " + e.from : "", e.confidence != null ? "confidence " + e.confidence : ""].filter(Boolean).join(" · ");
  return `<span class="src src-${esc(e.source || "default")} ${low ? "low" : ""}" title="${esc(title)}">${low ? "please check" : SRC_LABEL[e.source] || e.source}</span>${low ? `<button class="linkbtn" data-confirm="${esc(key)}">Confirm</button>` : ""}${e.source === "user" && e.resettable ? `<button class="linkbtn" data-reset="${esc(key)}" title="Forget your value and use the detected or default one">Reset</button>` : ""}`;
}
function requiredList() {
  const host = conf("review.host") || "gitlab";
  return [
    ["project.root", "Project folder"],
    ...(host === "github"
      ? [["github.token", "GitHub access token"], ["github.repo", "GitHub repository"]]
      : [["gitlab.token", "GitLab access token"], ["gitlab.url", "GitLab server"], ["gitlab.project", "GitLab project"]]),
    ...(hasJira() ? [["jira.site", "Jira site"], ["jira.email", "Jira email"], ["jira.token", "Jira API token"]] : []),
  ];
}

const REJECTED = /\b(401|403)\b/;
function requiredState(key) {
  if (key.endsWith(".token")) {
    if (!data.config?._secrets?.[key]) return "missing";
    const err = key === "jira.token" ? data.jira?.error : key === "telegram.token" ? data.telegram?.error : data.review?.error;
    return err && REJECTED.test(err) ? "rejected" : "ok";
  }
  return conf(key) ? "ok" : "missing";
}
function setupMissing() {
  if (!data?.config) return [];
  return requiredList().filter(([k]) => requiredState(k) !== "ok").map(([k, label]) => ({ key: k, label, why: requiredState(k) }));
}
const req = key => requiredList().some(r => r[0] === key) ? '<span class="req" title="Required">*</span>' : "";
function field(key, label, opts = {}) {
  const v = conf(key);
  const id = "f-" + key.replace(/\W/g, "-");
  label = label + req(key);
  const bad = requiredList().some(r => r[0] === key) && requiredState(key) !== "ok" ? "missing" : "";
  let input;
  if (opts.type === "select") input = `<select id="${id}" data-set-key="${esc(key)}">${opts.options.map(([val, txt]) => `<option value="${esc(val)}" ${String(v) === String(val) ? "selected" : ""}>${esc(txt)}</option>`).join("")}</select>`;
  else if (opts.type === "toggle") input = `<label class="minisw m-0"><input type="checkbox" id="${id}" data-set-key="${esc(key)}" data-kind="bool" ${v ? "checked" : ""}><span class="tog"></span></label>`;
  else if (opts.readonly) input = `<div class="ro">${Array.isArray(v) ? (v.length ? v.map(x => `<span class="chip">${esc(x)}</span>`).join(" ") : "—") : esc(v || "—")}</div>`;
  else if (opts.type === "folder" || opts.type === "file") {
    const what = opts.type === "file" ? "file" : "folder";
    input = `<div class="pathpick"><input id="${id}" class="${bad}" type="text" data-set-key="${esc(key)}" data-pick="${esc(key)}" data-pick-kind="${what}" value="${esc(v)}" placeholder="${esc(opts.placeholder || `Click to choose a ${what}`)}" spellcheck="false" readonly title="Click to choose a ${what}"><button class="fixbtn" data-pick-btn="${esc(key)}" data-pick-kind="${what}" title="Choose a ${what}">Browse…</button><button class="linkbtn" data-type-path="${esc(key)}">type path</button></div>`;
  }
  else input = `<input id="${id}" class="${bad}" type="${opts.type || "text"}" data-set-key="${esc(key)}" ${opts.type === "number" ? 'data-kind="int"' : ""} value="${esc(v)}" placeholder="${esc(opts.placeholder || "")}" spellcheck="false">`;
  return `<div class="frow"><div class="flabel"><div>${label}</div>${opts.help ? `<div class="fhelp">${opts.help}</div>` : ""}</div><div class="fctl">${input}<div class="fmeta">${srcBadge(key)}<span class="fmsg" id="msg-${id}"></span></div></div></div>`;
}
function secretRow(kind, label, help) {
  const masked = data.config?._secrets?.[kind + ".token"];
  const st = requiredState(kind + ".token");
  return `<div class="frow"><div class="flabel"><div>${label}${req(kind + ".token")}</div><div class="fhelp">${help}</div>${st === "rejected" ? '<div class="fhelp err">The saved token was rejected — paste a new one.</div>' : ""}</div><div class="fctl">
    <input id="tok-${kind}" class="${st !== "ok" ? "missing" : ""}" type="password" autocomplete="off" placeholder="${masked ? "saved " + esc(masked) + " — type to replace" : "paste token"}">
    <div class="fmeta"><button class="btn-primary" data-save-token="${kind}">Test &amp; save</button><span class="muted fs-sm">stored in ${esc(data.config?._secret_store || "config.json")}</span><span class="fmsg" id="msg-tok-${kind}"></span></div></div></div>`;
}
function checkAction(c) {
  const bad = c.ok === false, off = c.ok === null;
  const go = (section, focus, label) => ({ section, focus, label, attr: `data-goto-btn="${section}" ${focus ? `data-focus="${focus}"` : ""}` });
  switch (c.id) {
    case "project": return { section: "sec-you", label: bad ? "Choose folder" : "Change", attr: 'data-pick-btn="project.root"' };
    case "gitlab": return go("sec-gitlab", bad ? "tok-gitlab" : "", bad ? "Fix" : "Edit");
    case "github": return go("sec-gitlab", bad ? "tok-github" : "", bad ? "Fix" : "Edit");
    case "jira": return go("sec-jira", bad ? (conf("jira.site") ? "tok-jira" : "f-jira-site") : "", bad ? "Fix" : "Edit");
    case "docker": return bad || off ? { section: "sec-workspace", label: "Start Docker", attr: 'data-act="start-docker"' } : { section: "sec-workspace", label: "Show", attr: 'data-href="#/docker"' };
    case "postgres": return bad || off ? go("sec-workspace", "f-db-container", "Fix") : { section: "sec-workspace", label: "Show", attr: 'data-href="#/postgres"' };
    case "claude": return go("sec-claude", bad || off ? "f-claude-bin" : "", bad || off ? "Fix" : "Edit");
    default: return go("sec-claude", "", "View");
  }
}
function gotoSection(id, focus) {
  const sec = $(id); if (!sec) return;
  sec.scrollIntoView({ behavior: "smooth", block: "start" });
  sec.classList.remove("flash"); void sec.offsetWidth; sec.classList.add("flash");
  if (focus && $(focus)) setTimeout(() => { $(focus).focus({ preventScroll: true }); }, 450);
}
const CHECK_LABEL = { project: "Project", gitlab: "GitLab", github: "GitHub", jira: "Jira", docker: "Docker", postgres: "Postgres", claude: "Claude CLI", "fix-skill": "Fix skill" };
const SETUP_PROMPT = `Set up Opsboard (a local dashboard, CLI: opsboard) for this project. Work only through the opsboard CLI; do not edit its files by hand.

1. Run \`opsboard doctor --json\` and \`opsboard detect --json\` and read both.
2. If project.root is not this folder: \`opsboard config set project.root "$PWD" --source agent\`.
3. \`opsboard detect --apply\`, then check what is still missing in \`opsboard doctor\`.
4. Fill what detection could not, each with \`opsboard config set <key> <value> --source agent --from "<how you found it>"\`:
   review.host (gitlab or github, from the git remote), gitlab.url + gitlab.project or github.repo,
   tasks.tracker (jira if the team uses Jira — look for atlassian.net links in recent commits or merge request descriptions — otherwise none), jira.site, jira.email (ask me),
   project.profile (one of the file names in the profiles folder of \`opsboard home\` — pick the one that matches this repository's layout),
   db.container / db.user if the project runs Postgres in Docker.
5. Tokens: never ask me to paste a token into the chat. Tell me which ones are needed and to run, in my own terminal: \`opsboard secret set gitlab.token\` (or github.token, jira.token). Wait until I say it is done.
6. Fix skill: if \`opsboard config get claude.skills\` shows a skill that fixes review threads, set claude.fix_skill to it. Otherwise offer — do not do it unasked — to write one in .claude/skills/fix-review from examples/fix-skill/SKILL.md in \`opsboard home\`, filling in this project's test and lint commands, and check it with \`opsboard skill check fix-review\`.
7. Claude usage: never read Claude Code's own sign-in (the Keychain item "Claude Code-credentials" or ~/.claude/.credentials.json) and never change claude.live_usage yourself. If I want my plan limits in the sidebar, tell me to switch on Settings → Claude → Live Claude usage myself and choose Always Allow when macOS asks.
8. Finish with \`opsboard doctor\` and tell me in one short list what is set, what is still missing and why.`;
function setupBox(open) {
  return `<details class="panel setupclaude" ${open ? "open" : ""}><summary><b>Set up with Claude</b><span class="muted">Paste this into Claude Code in your project folder — it fills these settings for you.</span></summary>
    <pre class="prompt" translate="no">${esc(SETUP_PROMPT)}</pre>
    <div class="row"><button class="btn-primary" data-copy-setup="1">Copy prompt</button><span class="fmsg" id="msg-setup"></span></div></details>`;
}
function pageSettings() {
  const doc = ui.doctor;
  const first = !conf("project.root");
  const statuses = Object.entries(conf("jira.status_map") || {});
  const skills = conf("claude.skills") || [];
  return `<div class="pagehead"><h1>Settings</h1><span class="sub">Saved in ${esc(data.paths?.config || "config.json")} · tokens in ${esc(data.config?._secret_store || "config.json")}, sent only to your code host and Jira</span></div>
    ${(() => {
      const missing = setupMissing();
      if (!missing.length) return "";
      return `<section><div class="panel setup gate"><b>${first ? "Welcome to Opsboard. " : ""}Finish the required settings to open the dashboard.</b>
        <span class="muted">Fields marked <span class="req">*</span> are required. ${first ? "Start with your project folder — GitLab and the database are detected from it." : ""}</span>
        <ul>${missing.map(m => `<li><span class="req">*</span> ${esc(m.label)} — ${m.why === "rejected" ? "the saved token was rejected" : "not set"}</li>`).join("")}</ul></div>${setupBox(first)}</section>`;
    })()}
    <section><h2>Status<span class="h2-actions"><button class="fixbtn" data-act="doctor">Run checks</button><button class="fixbtn" data-act="detect">Re-detect</button></span></h2>
      <div class="checks">${doc ? doc.map(c => {
        const a = checkAction(c);
        return `<div class="check ${c.ok === true ? "ok" : c.ok === false ? "bad" : "skip"}" title="${esc(c.detail)}" data-goto="${a.section}" ${a.focus ? `data-focus="${a.focus}"` : ""} role="button" tabindex="0"><span class="dot ${c.ok === true ? "ok" : c.ok === false ? "bad" : ""}"></span><b>${CHECK_LABEL[c.id] || c.id}</b><button class="checkact ${c.ok === false ? "bad" : ""}" ${a.attr}>${a.label}</button><span class="muted">${esc(c.detail)}</span></div>`;
      }).join("") : '<div class="muted">Checking…</div>'}</div>
      <div class="fmsg mt-2" id="msg-detect"></div>${setupMissing().length ? "" : setupBox(false)}</section>
    <div class="setgrid"><nav class="setnav" aria-label="Settings sections">${[["sec-you", "You"], ["sec-gitlab", "Code host"], ["sec-jira", "Tasks"], ["sec-workspace", "Workspace"], ["sec-claude", "Claude"], ["sec-telegram", "Telegram"], ["sec-keys", "Keyboard shortcuts"], ["sec-adv", "Advanced"]].map(([id, l]) => `<a href="#/settings" data-goto-btn="${id}">${l}</a>`).join("")}</nav><div class="setbody">
    <section id="sec-you"><h2>You</h2><div class="panel form">
      ${field("project.root", "Project folder", { type: "folder", placeholder: "Click to choose your project folder", help: "The checkout you work in. Everything else is detected from here." })}
      ${field("ui.theme", "Theme", { type: "select", options: [["system", "System"], ["light", "Light"], ["dark", "Dark"]] })}
      ${field("ui.language", "Language", { type: "select", options: [["", "Browser default"], ["en", "English"], ["uz", "O'zbekcha"], ["ru", "Русский"]], help: "The page switches language right away." })}
    </div></section>
    <section id="sec-gitlab"><h2>Code host</h2><div class="panel form">
      ${field("review.host", "Host", { type: "select", options: [["gitlab", "GitLab"], ["github", "GitHub"]], help: "Where your merge / pull requests live. Detected from the project's git remote." })}
      ${conf("review.host") === "github" ? `
      ${secretRow("github", "Access token", 'Fine-grained token with <i>Pull requests</i>, <i>Contents</i> (read) and <i>Checks</i> (read) — GitHub → Settings → Developer settings → Personal access tokens. Add <i>Pull requests: write</i> if your fix skill replies to reviews.')}
      ${field("github.repo", "Repository", { placeholder: "owner/name" })}
      ${field("github.url", "Server", { placeholder: "https://github.com", help: "Change only for GitHub Enterprise Server." })}
      ${field("github.username", "Signed in as", { readonly: true })}` : `
      ${secretRow("gitlab", "Access token", 'Personal access token with the <code>read_api</code> scope (<code>api</code> if your fix skill replies to threads) — GitLab → Preferences → Access tokens.')}
      ${field("gitlab.url", "Server", { placeholder: "https://gitlab.example.com" })}
      ${field("gitlab.project", "Project", { placeholder: "group/project" })}
      ${field("gitlab.username", "Signed in as", { readonly: true })}`}
    </div></section>
    <section id="sec-jira"><h2>Tasks</h2><div class="panel form">
      ${field("tasks.tracker", "Tracker", { type: "select", options: [["", "Automatic"], ["jira", "Jira"], ["none", "None — tasks from merge / pull requests only"]], help: "Task keys such as <code>ABC-123</code> in titles link merge / pull requests to tasks." })}
      ${hasJira() ? `
      ${field("jira.site", "Site", { placeholder: "https://your-team.atlassian.net" })}
      ${field("jira.email", "Email", { placeholder: "you@company.com" })}
      ${secretRow("jira", "API token", 'Create one at <a href="https://id.atlassian.com/manage-profile/security/api-tokens" target="_blank">id.atlassian.com → API tokens</a>.')}
      ${field("jira.name", "Signed in as", { readonly: true })}
      ${field("jira.jql", "Which tasks", { help: "JQL query. Default: tasks assigned to you." })}
      ${field("jira.projects", "Project keys", { readonly: true, help: "Used to link merge requests to tasks." })}
      ${statuses.length ? `<div class="frow"><div class="flabel"><div>Status → column</div><div class="fhelp">Where each Jira status lands on the Tasks board.</div></div><div class="fctl"><div class="smap">${statuses.map(([s, b]) => `<label><span>${esc(s)}</span><select data-status="${esc(s)}">${BUCKETS.map(([k, l]) => `<option value="${k}" ${k === b ? "selected" : ""}>${l}</option>`).join("")}</select></label>`).join("")}</div><div class="fmeta">${srcBadge("jira.status_map")}<span class="fmsg" id="msg-smap"></span></div></div></div>` : ""}` : ""}
    </div></section>
    <section id="sec-workspace"><h2>Workspace</h2><div class="panel form">
      ${field("project.profile", "Project profile", { type: "select", options: (data.profiles || ["generic"]).map(p => [p, p]), help: "Layout conventions: worktrees, QA containers and databases, Jira status names, task areas. Add your own overrides in <code>profile.local.json</code>." })}
      ${field("project.worktrees", "Worktrees folder", { type: "folder", help: "Leave empty to use <code>git worktree list</code>." })}
      ${field("db.container", "Postgres container", { placeholder: "project-db-1" })}
      ${field("db.user", "Postgres user", { placeholder: "odoo" })}
    </div></section>
    <section id="sec-claude"><h2>Claude</h2><div class="panel form">
      ${field("claude.bin", "Claude CLI", { type: "file", help: "The <code>claude</code> executable used for background runs." })}
      ${field("claude.version", "Version", { readonly: true })}
      <div class="frow"><div class="flabel"><div>Skills</div><div class="fhelp">Found in the project's and your own <code>.claude/skills</code>.</div></div><div class="fctl"><div class="ro">${skills.map(s => `<span class="chip ${s === conf("claude.fix_skill") ? "live" : ""}">${esc(s)}</span>`).join(" ") || "—"}</div><div class="fmeta">${srcBadge("claude.skills")}</div></div></div>
      ${field("claude.fix_skill", "Fix skill", { type: "select", options: [["", "None"], ...skills.map(s => [s, s])], help: "Run by ⋯ → Run fix on your merge requests. Any skill that follows <a href=\"https://github.com/Javohir-dev/opsboard/blob/main/docs/fix-skill.md\" target=\"_blank\">the fix-skill contract</a>." })}
      ${field("notify.sound", "Sound when a fix finishes", { type: "toggle", help: "A short system sound with the notification — a different one when the run failed or stopped. <button class=\"linkbtn\" data-notif-sound>Play it</button>" })}
      ${field("claude.background_runs", "Background runs", { type: "toggle", help: "Let the dashboard start the fix skill in the background." })}
      ${field("claude.permission_mode", "Permission mode", { type: "select", options: [["auto", "auto"], ["acceptEdits", "acceptEdits"], ["manual", "manual"]], help: "Used by background runs." })}
      ${field("claude.reply_language", "Reply language", { type: "select", options: [["thread", "Same as the review thread"], ["uz", "Uzbek"], ["ru", "Russian"], ["en", "English"]], help: "Passed to the fix skill as <code>OPS_REPLY_LANGUAGE</code> for its thread replies." })}
      ${field("claude.live_usage", "Live Claude usage", { type: "toggle", help: "Your plan limits in the sidebar, asked from Anthropic every minute with Claude Code's own sign-in. Off: no limits at all — the sidebar shows CPU, RAM and swap instead, and Overview leaves out the machine tiles. The token is read from the Keychain (macOS asks once — choose <i>Always Allow</i>), kept in memory only and never renewed here." })}
    </div></section>
    ${telegramSection()}
    <section id="sec-keys"><h2>Keyboard shortcuts<span class="h2-actions"><span class="fmsg" id="msg-hk"></span><button class="linkbtn" data-hk-reset="1">Reset to defaults</button></span></h2><div class="panel form">
      <div class="frow"><div class="flabel"><div>How it works</div><div class="fhelp">Click a field and press the keys. A sequence like <code>g t</code> means: press <kbd>g</kbd>, then <kbd>t</kbd>. Backspace clears. Plain keys are ignored while you type in a field; shortcuts with <code>alt</code>/<code>ctrl</code>/<code>cmd</code> work everywhere. Press <kbd>?</kbd> to see them all.</div></div><div class="fctl"></div></div>
      ${hotkeys().map(h => `<div class="frow"><div class="flabel"><div>${esc(h.label)}</div></div><div class="fctl"><input type="text" class="hkinput" readonly data-hk-record="${h.page}" value="${esc(h.combo)}" placeholder="not set"><div class="fmeta"><span class="muted">default: ${esc(h.def)}</span></div></div></div>`).join("")}
    </div></section>
    <section id="sec-adv"><h2>Advanced</h2><div class="panel form">
      ${field("refresh.tasks_seconds", "Jira / GitLab refresh", { type: "number", help: "Seconds between automatic updates (30–3600)." })}
      ${field("server.port", "Port", { type: "number", help: "Takes effect after <code>opsboard restart</code>." })}
      <div class="frow"><div class="flabel"><div>Version</div><div class="fhelp">Start at login: <code>opsboard autostart on</code>.</div></div><div class="fctl"><div class="ro">${esc(data.version?.current || "")}${data.version?.update ? ` <span class="badge warn">${esc(data.version.latest)} available</span> — run <code>opsboard update</code>` : ""}</div></div></div>
    </div></section></div></div>`;
}
async function loadDoctor() {
  try { ui.doctor = await (await fetch("/api/doctor")).json(); } catch (e) {}
  if (route().page === "settings") rerenderSettings();
}
function rerenderSettings() { render(); }
async function saveSetting(key, value, msgId) {
  const msg = $(msgId);
  if (msg) { msg.className = "fmsg muted"; msg.textContent = "Saving…"; }
  const r = await (await fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key, value }) })).json();
  if (!r.ok) { if (msg) { msg.className = "fmsg err"; msg.textContent = r.error; } return; }
  data.config[key] = r.entry;
  if (key === "ui.theme") applyTheme();
  if (key === "ui.language") return location.reload();
  if (msg) { msg.className = "fmsg okmsg"; msg.textContent = "Saved"; }
  setTimeout(async () => { data = await (await fetch("/api/state")).json(); rerenderSettings(); loadDoctor(); }, 900);
}
function applyTheme() {
  const t = conf("ui.theme");
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
  else if (t === "system") delete document.documentElement.dataset.theme;
}

function telegramSection() {
  const tg = data.telegram || {};
  const state = !tg.configured ? "" : tg.error ? `<span class="badge bad" title="${esc(tg.error)}">${esc(tg.error.slice(0, 60))}</span>` : tg.running ? '<span class="badge ok">connected</span>' : '<span class="badge muted">connecting…</span>';
  const link = !tg.configured ? "" : tg.linked
    ? `<div class="frow"><div class="flabel"><div>Linked chat</div><div class="fhelp">Only this Telegram account can use the bot; everyone else is ignored.</div></div><div class="fctl"><div class="ro">${tg.user ? "@" + esc(tg.user) : "linked"}</div><div class="fmeta"><button class="fixbtn" data-tg="test">Send a test message</button><button class="linkbtn" data-tg="unlink">Unlink</button><span class="fmsg" id="msg-tg"></span></div></div></div>`
    : tg.link
      ? `<div class="frow"><div class="flabel"><div>Link your chat</div><div class="fhelp">Open the bot and press <b>Start</b> — that sends a one-time code (valid 15 minutes) and links this Telegram account to your Opsboard.</div></div><div class="fctl"><div class="fmeta"><a class="btn-primary tglink" href="${esc(tg.link)}" target="_blank">Open @${esc(tg.bot)} in Telegram</a><span class="muted fs-sm">or send <code>/start ${esc(tg.code)}</code></span></div></div></div>`
      : `<div class="frow"><div class="flabel"><div>Link your chat</div></div><div class="fctl"><div class="ro muted">waiting for the bot to connect…</div></div></div>`;
  return `<section id="sec-telegram"><h2>Telegram${tg.bot ? `<span class="count">@${esc(tg.bot)}</span>` : ""}<span class="h2-actions">${state}</span></h2><div class="panel form">
      ${secretRow("telegram", "Bot token", 'Create a bot with <a href="https://t.me/BotFather" target="_blank">@BotFather</a> (<code>/newbot</code>) and paste its token. The bot runs inside Opsboard: it starts and stops with it, and needs no public address.')}
      ${link}
      ${tg.configured ? field("telegram.notify", "Notifications in Telegram", { type: "toggle", help: "Finished fix runs (with live progress while they run) and new review threads." }) : ""}
      ${tg.configured ? field("telegram.allow_runs", "Allow fix runs from Telegram", { type: "toggle", help: "Lets the linked chat start and stop your fix skill with /fix and the ▶ buttons. Every start asks for confirmation." }) : ""}
      ${tg.configured ? `<div class="frow"><div class="flabel"><div>Remove the bot</div><div class="fhelp">Forgets the token and the linked chat.</div></div><div class="fctl"><button class="linkbtn danger" data-tg="forget">Forget the bot</button></div></div>` : ""}
    </div></section>`;
}
document.addEventListener("click", async e => {
  const b = e.target.closest("[data-tg]");
  if (!b) return;
  const action = b.dataset.tg, msg = $("msg-tg");
  if (action === "forget" && !confirm(t("Forget the Telegram bot and the linked chat?"))) return;
  b.disabled = true;
  try {
    const r = await (await fetch("/api/telegram", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }) })).json();
    if (msg) { msg.className = r.ok ? "fmsg okmsg" : "fmsg err"; msg.textContent = r.ok ? (action === "test" ? t("Sent — check Telegram") : t("Done")) : r.error; }
    data = await (await fetch("/api/state")).json(); rerenderSettings();
  } finally { b.disabled = false; }
});
