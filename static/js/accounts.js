const accUi = { menu: null, rules: false, edit: null, toast: null };

function accData() { return data.claude_accounts || {}; }
function accRows() { return accData().accounts || []; }
function accById(id) { return accRows().find(x => x.id === id); }
function accAt() { return +conf("claude.switch_at") || 80; }
function accTo() { return +conf("claude.switch_to") || 60; }
function accShort(name) { return String(name || "").split("@")[0]; }
function accColor(p) { return p >= accAt() ? "bad" : p >= accTo() ? "warn" : "ok"; }
function accWhen(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000), time = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  return d.toDateString() === new Date().toDateString() ? time : `${d.toLocaleDateString("en-US", { weekday: "short" })} ${time}`;
}
function accAdded(a) { return a.added ? "added " + new Date(a.added * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : ""; }
function accFable(w) { return Object.entries(w || {}).find(([k]) => k.startsWith("seven_day_"))?.[1]; }
function accSub(a) {
  if (a.id === "main") return [a.plan, "Claude Code's own /login"].filter(Boolean).join(" · ");
  return [a.plan, "Setup token " + a.masked, a.login ? "Claude Code login" : ""].filter(Boolean).join(" · ");
}
function accMeterCell(w, loading) {
  if (loading) return `<div class="am"><div class="amtop"><span class="amp muted">Checking…</span></div><div class="ambar load"><span></span></div></div>`;
  if (!w) return `<div class="am"><div class="amtop"><span class="amp muted">—</span><span class="muted">n/a</span></div><div class="ambar"><span style="width:0"></span></div></div>`;
  const past = w.resets_at && w.resets_at < now(), p = past ? 0 : w.percent;
  return `<div class="am" title="${w.resets_at ? esc("resets " + fmtDateTime(w.resets_at)) : ""}"><div class="amtop"><span class="amp ${accColor(p)}">${p}%</span><span class="muted">${past ? "reset" : accWhen(w.resets_at)}</span></div>
    <div class="ambar ${accColor(p)}" role="progressbar" aria-valuenow="${p}" aria-valuemin="0" aria-valuemax="100"><span style="width:${Math.max(p, 1)}%"></span><i style="left:${accTo()}%"></i><i class="sw" style="left:${accAt()}%"></i></div></div>`;
}
function accState(a) {
  const err = a.error || "";
  if (err && /401|invalid|expired|authenticate/i.test(err)) return { chip: "Token expired", tone: "bad", meta: "Run claude setup-token and paste the new one", action: "reauth" };
  if (!a.at && !a.error && a.id !== "main" && (!a.added || Date.now() / 1000 - a.added < 300)) return { chip: "Just added", tone: "mute", meta: "Fetching usage…", loading: true, action: "off" };
  if (a.active) return a.level >= accAt() ? { chip: `In use · over ${accAt()}%`, tone: "bad", action: "active" } : { chip: "In use", tone: "ok", action: "active" };
  if (a.level >= 100) {
    const w = a.windows || {}, full = [w.five_hour, w.seven_day].find(x => x && x.percent >= 100);
    return { chip: "Limit reached", tone: "bad", meta: full?.resets_at ? `Available again at ${accWhen(full.resets_at)}` : "", action: "off" };
  }
  if (!a.enabled) return { chip: "Excluded", tone: "mute", meta: "Not in auto-switch · manual only", dim: true, action: "switch" };
  if (a.next) return { chip: "Next up", tone: "info", meta: "Most room left", action: "switch" };
  return { action: "switch" };
}
function accRow(a) {
  const st = accState(a), w = a.windows || {};
  const action = st.action === "active" ? `<span class="muted fs-sm accactive">Active</span>`
    : st.action === "reauth" ? `<button type="button" class="accbtn danger" data-acc-edit="${esc(a.id)}" data-acc-replace="1">Re-authenticate</button>`
    : `<button type="button" class="accbtn" data-acc-switch="${esc(a.id)}" ${st.action === "off" ? "disabled" : ""}>Switch</button>`;
  return `<div class="accrow ${a.active ? "on" : ""} ${st.dim ? "dim" : ""}" data-acc-row="${esc(a.id)}">
    <div class="accwho"><div class="accname"><span class="accdot ${a.active ? "on" : st.tone === "bad" ? "bad" : ""}"></span><b translate="no" title="${esc(a.label)}">${esc(a.label)}</b>${st.chip ? `<span class="accchip ${st.tone}">${esc(st.chip)}</span>` : ""}</div>
      <div class="accmeta muted" title="${esc(a.error || "")}">${esc(st.meta || accSub(a))}</div></div>
    ${accMeterCell(w.five_hour, st.loading)}${accMeterCell(w.seven_day, st.loading)}${accMeterCell(accFable(w), st.loading)}
    <div class="accact">${action}<button type="button" class="iconbtn ghost accmore" data-acc-menu="${esc(a.id)}" aria-label="More actions" aria-haspopup="menu" aria-expanded="${accUi.menu === a.id}">${icon("more", 16)}</button></div></div>`;
}
function accBanner() {
  const p = accData().proposal;
  if (!p) return "";
  const src = accRows().find(x => x.label === p.src) || {}, dst = accRows().find(x => x.label === p.dst) || {};
  const sw = src.windows || {}, dw = dst.windows || {};
  const which = (sw.five_hour?.percent || 0) >= (sw.seven_day?.percent || 0) ? "session" : "weekly limit";
  return `<div class="accbanner" role="alert">${icon("warning", 20)}<div class="grow"><b>${esc(accShort(p.src))} passed ${accAt()}% of its ${which} (${esc(p.level)}%)</b>
      <span>${esc(accShort(p.dst))} has the most room: session ${dw.five_hour?.percent ?? "—"}%, weekly ${dw.seven_day?.percent ?? "—"}%</span></div>
    <div class="accbannerbtns"><button type="button" class="accbtn warnline" data-acc-decide="0" data-pid="${esc(p.pid)}">Snooze 30m</button><button type="button" class="accbtn warnfill" data-acc-decide="1" data-pid="${esc(p.pid)}">Switch to ${esc(accShort(p.dst))}</button></div></div>`;
}
function accProposal() {
  const p = accData().proposal;
  if (!p || !(accData().ask_in || []).includes("sidebar")) return "";
  return `<div class="accprop"><div><b>Switch to <span translate="no">${esc(accShort(p.dst))}</span>?</b><div class="muted fs-sm"><span translate="no">${esc(accShort(p.src))}</span> is at ${esc(p.level)}%${p.to_level != null ? ` · <span translate="no">${esc(accShort(p.dst))}</span> ${esc(p.to_level)}%` : ""}</div></div>
    <div class="accpropbtns"><button class="btn-primary" data-acc-decide="1" data-pid="${esc(p.pid)}">Switch</button><button class="linkbtn" data-acc-decide="0" data-pid="${esc(p.pid)}">Snooze 30m</button></div></div>`;
}
function accRulesBar() {
  const d = accData(), on = !!conf("claude.auto_switch"), ask = d.mode !== "auto";
  const chans = (d.ask_in || []).map(c => `<span class="accpill">${{ sidebar: "Sidebar", telegram: "Telegram", desktop: "Desktop" }[c] || c}</span>`).join("");
  return `<div class="accrules ${on ? "" : "off"}"><label class="accswitch"><input type="checkbox" data-acc-auto ${on ? "checked" : ""}><span class="tog"></span><b>Auto-switch</b></label>
    <div class="accrulestext">${ask ? "Ask when in-use passes" : "Switch when in-use passes"} <span class="accnum warn">${accAt()}%</span> → ${ask ? "switch to" : "move to"} the account with most room under <span class="accnum ok">${accTo()}%</span></div>
    <div class="accrulesask">${ask ? `Ask in ${chans || '<span class="muted">nowhere</span>'}` : "Notifies after switching"}<button type="button" class="linkbtn" data-acc-rules aria-expanded="${accUi.rules}">Edit</button></div></div>`;
}
function pageAccounts() {
  const d = accData(), rows = accRows();
  const newest = Math.max(0, ...rows.map(a => a.at || 0));
  return `<div class="pagehead acchead2"><div><h1>Claude accounts</h1><span class="sub">${plural(rows.length, "account")} · switching from ${accAt()}% to an account below ${accTo()}%${newest ? ` · updated ${ago(newest)}` : ""}</span></div>
      <span class="h2-actions"><button class="iconbtn accbig ${d.refreshing ? "spin" : ""}" data-acc-refresh title="Refresh usage" aria-label="Refresh usage">${icon("refresh", 16)}</button><button class="btn-primary accbig" data-acc-add>${icon("plus", 14)} Add account</button></span></div>
    ${d.active === "other" ? `<div class="accbanner err" role="alert">${icon("warning", 20)}<div class="grow"><b>${esc(d.settings)} holds a token Opsboard does not know</b><span>Automatic switching is paused until you switch to one of these accounts.</span></div></div>` : ""}
    ${accBanner()}${accRulesBar()}
    <div class="acctable" role="table" aria-label="Claude accounts"><div class="acctablein">
      <div class="accrow head" role="row"><span>Account</span><span>Session · 5h</span><span>Weekly · all models</span><span>Weekly · Fable</span><span class="r">Action</span></div>
      ${rows.map(accRow).join("") || '<div class="muted accempty">Loading…</div>'}</div></div>
    <div class="acclegend muted"><span><i class="lg"></i>${accTo()}% target</span><span><i class="lg sw"></i>${accAt()}% switch point</span><span class="grow"></span><span>Switching writes <code>CLAUDE_CODE_OAUTH_TOKEN</code> to <code>${esc(d.settings || "~/.claude/settings.json")}</code></span></div>
    ${accUi.toast ? `<div class="acctoast" role="status">${icon("check", 18)}<span>Switched to <b translate="no">${esc(accShort(accUi.toast.to))}</b> · new sessions use it</span>${accUi.toast.prev ? `<button type="button" class="linkbtn" data-acc-undo>Undo</button>` : ""}</div>` : ""}`;
}

/* popovers: row menu and rules */
function accPop() {
  let p = $("accpop");
  if (!p) { p = document.createElement("div"); p.id = "accpop"; p.className = "accpop"; p.hidden = true; document.body.appendChild(p); }
  return p;
}
function accClosePop() { const p = $("accpop"); if (p) p.hidden = true; accUi.menu = null; accUi.rules = false; }
function accPlace(anchor, el) {
  const r = anchor.getBoundingClientRect();
  el.hidden = false;
  const w = el.offsetWidth, h = el.offsetHeight;
  let top = r.bottom + 6;
  if (top + h > innerHeight - 8) top = Math.max(8, r.top - h - 6);
  el.style.left = Math.max(8, Math.min(r.right - w, innerWidth - w - 8)) + "px";
  el.style.top = top + window.scrollY + "px";
}
function openAccMenu(btn) {
  const a = accById(btn.dataset.accMenu);
  if (!a) return;
  const p = accPop();
  accUi.menu = a.id; accUi.rules = false;
  const item = (attr, ic, label, hint = "", cls = "") => `<button type="button" role="menuitem" class="accmi ${cls}" ${attr}>${icon(ic, 16)}<span class="grow">${label}</span>${hint ? `<kbd>${hint}</kbd>` : ""}</button>`;
  p.setAttribute("role", "menu"); p.setAttribute("aria-label", "Actions for " + a.label);
  p.innerHTML = `<div class="accmihead"><b translate="no">${esc(a.label)}</b><span class="muted fs-sm">${esc([a.id === "main" ? "Claude Code login" : "Setup token " + a.masked, accAdded(a)].filter(Boolean).join(" · "))}</span></div>
    ${a.active ? "" : item(`data-acc-switch="${esc(a.id)}"`, "chevron", "Switch to this account")}
    ${item("data-acc-refresh", "refresh", "Refresh usage", "R")}
    ${item(`data-acc-edit="${esc(a.id)}"`, "pencil", "Edit account…", "E")}
    ${item(`data-acc-copy="${esc(a.label)}"`, "copy", "Copy name")}
    <div class="accmisep"></div>
    <label class="accmi"><span class="ic16">${icon("refresh", 16)}</span><span class="grow">Include in auto-switch</span><input type="checkbox" data-acc-include="${esc(a.id)}" ${a.enabled ? "checked" : ""}><span class="tog sm"></span></label>
    ${a.id === "main" ? "" : `<div class="accmisep"></div>${item(`data-acc-remove="${esc(a.id)}"`, "trash", "Remove account…", "", "danger")}`}`;
  translateTree(p);
  accPlace(btn, p);
  p.querySelector("[role=menuitem]")?.focus();
}
function openAccRules(btn) {
  const d = accData(), p = accPop(), ch = (list, v) => (list || []).some(x => x === v || (v === "fable" && x.startsWith("seven_day_"))) ? "checked" : "";
  accUi.rules = true; accUi.menu = null;
  p.setAttribute("role", "dialog"); p.setAttribute("aria-label", "Auto-switch rules");
  p.innerHTML = `<div class="accpophead"><b>Auto-switch rules</b><button type="button" class="iconbtn ghost" data-acc-popclose aria-label="Close">${icon("x", 14)}</button></div>
    <form class="accpopbody" data-acc-rules-form onsubmit="return false">
      <div class="accmodes" role="radiogroup" aria-label="Mode">
        <label class="accmode"><input type="radio" name="mode" value="ask" ${d.mode !== "auto" ? "checked" : ""}><span><b>Ask first</b><span class="muted fs-sm">Prompt in sidebar / Telegram, switch on yes</span></span></label>
        <label class="accmode"><input type="radio" name="mode" value="auto" ${d.mode === "auto" ? "checked" : ""}><span><b>Switch without asking</b><span class="muted fs-sm">Only send a notification after</span></span></label></div>
      <div class="accpct2"><label>Trigger at<span class="accpct warn"><input type="number" name="switch_at" min="11" max="100" value="${accAt()}"><i>%</i></span></label>
        <label>Target below<span class="accpct ok"><input type="number" name="switch_to" min="10" max="99" value="${accTo()}"><i>%</i></span></label></div>
      <fieldset><legend>Watch these limits</legend><label><input type="checkbox" name="watch" value="five_hour" ${ch(d.watch, "five_hour")}>Session · 5h</label><label><input type="checkbox" name="watch" value="seven_day" ${ch(d.watch, "seven_day")}>Weekly</label><label><input type="checkbox" name="watch" value="fable" ${ch(d.watch, "fable")}>Fable</label></fieldset>
      <fieldset><legend>Ask in</legend><label><input type="checkbox" name="ask_in" value="sidebar" ${ch(d.ask_in, "sidebar")}>Sidebar</label><label><input type="checkbox" name="ask_in" value="telegram" ${ch(d.ask_in, "telegram")}>Telegram</label><label><input type="checkbox" name="ask_in" value="desktop" ${ch(d.ask_in, "desktop")}>Desktop</label></fieldset>
      <label class="accsel">If no account is below target<select name="when_none"><option value="suggest" ${d.when_none === "suggest" ? "selected" : ""}>Suggest the one with most room</option><option value="stay" ${d.when_none !== "suggest" ? "selected" : ""}>Stay and notify me</option></select></label>
      <div class="msg" id="accRulesMsg" role="status"></div>
    </form>
    <div class="accpopfoot"><button type="button" class="linkbtn" data-acc-rules-reset>Reset</button><button type="button" class="btn-primary" data-acc-rules-save>Save</button></div>`;
  translateTree(p);
  accPlace(btn, p);
}

/* dialogs: add, edit, confirm switch */
function accDialog() {
  let d = $("accdlg");
  if (!d) {
    d = document.createElement("dialog"); d.id = "accdlg"; d.className = "acct accdlg"; document.body.appendChild(d);
    d.addEventListener("click", e => { if (e.target === d) d.close(); });
    d.addEventListener("close", () => { accUi.edit = null; });
  }
  return d;
}
function accSay(cls, text, id = "accMsg") { const m = $(id); if (m) { m.className = "msg " + cls; m.textContent = text; } }
function accHead(title, sub) {
  return `<div class="accdlg-head"><div class="grow"><h3>${title}</h3>${sub ? `<div class="muted fs-sm" translate="no">${sub}</div>` : ""}</div><button type="button" class="iconbtn ghost" data-acc-close aria-label="Close">${icon("x", 16)}</button></div>`;
}
function openAccAdd() {
  accClosePop();
  const d = accDialog();
  d.setAttribute("aria-label", "Add Claude account");
  d.innerHTML = `${accHead("Add Claude account")}
    <div class="accdlg-body accform">
      <div class="accstep"><span class="accsteph">1. Get a setup token</span>
        <div class="acccode"><code class="grow">claude setup-token</code><button type="button" class="accbtn sm" data-acc-copy="claude setup-token">Copy</button></div>
        <span class="muted fs-sm">Run it in a terminal, sign in with the account you want to add.</span></div>
      <div class="accstep"><label for="accToken" class="accsteph">2. Paste the token</label>
        <div class="accrowin"><input id="accToken" type="password" autocomplete="off" spellcheck="false" placeholder="sk-ant-oat01-…"><button type="button" class="accbtn" data-acc-paste>Paste</button></div>
        <div id="accCheck" class="acccheck" hidden></div></div>
      <div class="accstep"><label for="accName" class="accsteph">Label <span class="muted">(optional)</span></label><input id="accName" type="text" maxlength="40" placeholder="e.g. Team · backend" autocomplete="off" spellcheck="false"></div>
      <div class="accchecks"><label><input type="checkbox" id="accInclude" checked>Include in auto-switch</label><label><input type="checkbox" id="accNow">Switch to it now</label></div>
      <div class="msg" id="accMsg" role="status" aria-live="polite"></div></div>
    <div class="accfootbar"><span class="muted fs-sm grow">Stored locally · only the last 4 chars are shown</span><button type="button" data-acc-close>Cancel</button><button type="button" class="btn-primary" data-acc-save disabled>Add account</button></div>`;
  translateTree(d);
  if (!d.open) d.showModal();
  $("accToken").focus();
}
let accCheckTimer = null;
function accCheckToken() {
  clearTimeout(accCheckTimer);
  const inp = $("accToken"), tok = inp?.value.trim(), box = $("accCheck"), save = accDialog().querySelector("[data-acc-save]");
  if (!box) return;
  if (save) save.disabled = true;
  inp.classList.remove("bad", "good");
  if (!tok) { box.hidden = true; return; }
  box.hidden = false; box.className = "acccheck wait"; box.textContent = t("Checking the token with Claude…");
  accCheckTimer = setTimeout(async () => {
    const r = await accPost({ action: "check", token: tok });
    if ($("accToken")?.value.trim() !== tok) return;
    if (!r.ok) { box.className = "acccheck bad"; box.innerHTML = `${icon("x", 16)}<span>${esc(r.error)}</span>`; inp.classList.add("bad"); return; }
    const w = JSON.parse(r.note || "{}");
    box.className = "acccheck good"; box.innerHTML = `${icon("check", 16)}<span>Valid · session ${w.five_hour?.percent ?? "—"}%, weekly ${w.seven_day?.percent ?? "—"}%</span>`;
    inp.classList.add("good");
    if (save) save.disabled = false;
  }, 500);
}
function openAccEdit(id, replace = false, del = false) {
  accClosePop();
  const a = accById(id);
  if (!a) return;
  accUi.edit = { id, order: a.order || "normal", enabled: a.enabled, replace, del };
  renderAccEdit();
}
function renderAccEdit() {
  const e = accUi.edit, a = accById(e.id), d = accDialog();
  if (!a) { d.close(); return; }
  const label = $("accLabel")?.value ?? a.label, enabled = $("accEnabled") ? $("accEnabled").checked : e.enabled;
  const seg = (v, l) => `<button type="button" role="radio" aria-checked="${e.order === v}" class="${e.order === v ? "on" : ""}" data-acc-order="${v}">${l}</button>`;
  const tokenRow = a.id === "main" ? "" : `<div class="accstep"><span class="accsteph">Setup token</span>
      ${e.replace ? `<div class="accrowin"><input id="accNewToken" type="password" autocomplete="off" spellcheck="false" placeholder="sk-ant-oat01-…"><button type="button" class="accbtn" data-acc-replace-cancel>Cancel</button></div><span class="muted fs-sm">Run <code>claude setup-token</code> signed in to this same account. It is checked when you save.</span>`
      : `<div class="acccode"><code>${esc(a.masked)}</code><span class="muted fs-sm grow">${esc([accAdded(a), a.error ? "not working" : "valid"].filter(Boolean).join(" · "))}</span><button type="button" class="accbtn sm" data-acc-replace-open>Replace token</button></div>`}</div>`;
  d.setAttribute("aria-label", "Edit account");
  d.innerHTML = `${accHead("Edit account", esc(a.label))}
    <div class="accdlg-body accform">
      ${a.id === "main" ? "" : `<div class="accstep"><label for="accLabel" class="accsteph">Label</label><input id="accLabel" type="text" maxlength="40" value="${esc(label)}" autocomplete="off" spellcheck="false"></div>`}
      ${tokenRow}
      <div class="accbox"><div class="accboxrow"><div><b>Include in auto-switch</b><div class="muted fs-sm">Opsboard can suggest this account when another fills up</div></div><label class="accswitch"><input type="checkbox" id="accEnabled" ${enabled ? "checked" : ""} aria-label="Include in auto-switch"><span class="tog"></span></label></div>
        ${a.id === "main" ? "" : `<div class="accorder"><span class="muted fs-sm">Order when several have room</span><div class="accseg" role="radiogroup" aria-label="Order">${seg("first", "Use first")}${seg("normal", "Normal")}${seg("last", "Last resort")}</div></div>`}</div>
      ${a.login || a.id === "main" ? `<div class="accinfo">${icon("info", 16)}<span>This is also your Claude Code login.${a.id === "main" ? "" : " Removing it here keeps you signed in to Claude Code."}</span></div>` : ""}
      <div class="msg" id="accMsg" role="status" aria-live="polite"></div></div>
    ${e.del ? `<div class="accfootbar danger"><span class="grow">${a.active ? "It is in use — new sessions go back to Claude Code's own login. " : ""}Remove <b translate="no">${esc(a.label)}</b> and its token?</span><button type="button" data-acc-del-cancel>Cancel</button><button type="button" class="btn-danger" data-acc-del-go>Remove</button></div>`
      : `<div class="accfootbar">${a.id === "main" ? "" : `<button type="button" class="accbtn dangerline" data-acc-del-ask>Remove account</button>`}<span class="grow"></span><button type="button" data-acc-close>Cancel</button><button type="button" class="btn-primary" data-acc-edit-save>Save</button></div>`}`;
  translateTree(d);
  if (!d.open) d.showModal();
  if (e.replace) $("accNewToken")?.focus();
}
function openAccConfirm(id) {
  accClosePop();
  const to = accById(id), from = accRows().find(x => x.active);
  if (!to) return;
  if (!accData().confirm_manual) { accDoSwitch(id); return; }
  const card = (cls, tag, a) => `<div class="accfrom ${cls}"><span class="acctag">${tag}</span><b translate="no">${esc(accShort(a?.label || "—"))}</b><span class="fs-sm">Session ${a?.windows?.five_hour?.percent ?? "—"}% · Weekly ${a?.windows?.seven_day?.percent ?? "—"}%</span></div>`;
  const toLogin = to.id === "main" || to.login, d = accDialog();
  d.setAttribute("aria-label", "Switch account");
  d.innerHTML = `<div class="accconfirm"><h3>Switch to ${esc(accShort(to.label))}?</h3>
      <p class="muted">New Claude Code sessions, VS Code included, will use this account. Sessions already running keep the current one until restarted.</p>
      <div class="accfromto">${card("", "From", from)}${icon("chevron", 20)}${card("to", "To", to)}</div>
      <div class="muted fs-sm">${toLogin ? "Removes" : "Writes"} <code>CLAUDE_CODE_OAUTH_TOKEN</code> ${toLogin ? "from" : "to"} <code>${esc(accData().settings || "~/.claude/settings.json")}</code></div>
      <div class="msg" id="accMsg" role="status"></div>
      <div class="accconfirmfoot"><label class="fs-sm muted"><input type="checkbox" id="accNoAsk">Don't ask for manual switches</label><span class="grow"></span><button type="button" data-acc-close>Cancel</button><button type="button" class="btn-primary" data-acc-switch-go="${esc(id)}">Switch</button></div></div>`;
  translateTree(d);
  if (!d.open) d.showModal();
  d.querySelector("[data-acc-switch-go]").focus();
}
function accToast(to, prev) {
  const at = Date.now();
  accUi.toast = { to, prev, at };
  setTimeout(() => { if (accUi.toast?.at === at) { accUi.toast = null; ui.forcePatch = true; render(); } }, 8000);
}
async function accDoSwitch(id) {
  const prev = accRows().find(x => x.active)?.id, to = accById(id)?.label;
  const r = await accPost({ action: "switch", id });
  if (!r.ok) { accSay("err", r.error); return false; }
  accToast(to, prev && prev !== id ? prev : null);
  accDone(r);
  return true;
}
async function accPost(body) {
  try { return await (await fetch("/api/claude-accounts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json(); }
  catch (x) { return { ok: false, error: String(x) }; }
}
function accDone(r) { if (r.claude_accounts) data.claude_accounts = r.claude_accounts; ui.forcePatch = true; render(); }
async function accReloadState() { try { data = await (await fetch("/api/state")).json(); } catch (x) {} ui.forcePatch = true; render(); }
function accRulesNow() {
  const d = accData();
  return { mode: d.mode || "ask", switch_at: accAt(), switch_to: accTo(), watch: [...new Set((d.watch || []).map(w => w.startsWith("seven_day_") ? "fable" : w))], ask_in: d.ask_in || [], when_none: d.when_none || "stay" };
}

document.addEventListener("click", async e => {
  const t0 = e.target, pop = $("accpop");
  if (pop && !pop.hidden && !t0.closest("#accpop, [data-acc-menu], [data-acc-rules]")) accClosePop();
  const mb = t0.closest("[data-acc-menu]");
  if (mb) { if (accUi.menu === mb.dataset.accMenu) accClosePop(); else openAccMenu(mb); return; }
  const rb = t0.closest("[data-acc-rules]");
  if (rb) { if (accUi.rules) accClosePop(); else openAccRules(rb); return; }
  if (t0.closest("[data-acc-popclose]")) { accClosePop(); return; }
  if (t0.closest("[data-acc-add]")) { openAccAdd(); return; }
  if (t0.closest("[data-acc-close]")) { accDialog().close(); return; }
  const cp = t0.closest("[data-acc-copy]");
  if (cp) {
    try { await navigator.clipboard.writeText(cp.dataset.accCopy); if (cp.classList.contains("accbtn")) { const o = cp.textContent; cp.textContent = t("Copied"); setTimeout(() => { cp.textContent = o; }, 1200); } } catch (x) {}
    if (cp.closest("#accpop")) accClosePop();
    return;
  }
  if (t0.closest("[data-acc-paste]")) { try { $("accToken").value = (await navigator.clipboard.readText()).trim(); accCheckToken(); } catch (x) { accSay("err", t("Paste with ⌘V — the browser did not allow reading the clipboard")); } return; }
  if (t0.closest("[data-acc-refresh]")) { accClosePop(); $("view").querySelector("[data-acc-refresh]")?.classList.add("spin"); const r = await accPost({ action: "refresh" }); if (r.ok) accDone(r); return; }
  const ed = t0.closest("[data-acc-edit]");
  if (ed) { openAccEdit(ed.dataset.accEdit, !!ed.dataset.accReplace); return; }
  const rm = t0.closest("[data-acc-remove]");
  if (rm) { openAccEdit(rm.dataset.accRemove, false, true); return; }
  const sw = t0.closest("[data-acc-switch]");
  if (sw) { openAccConfirm(sw.dataset.accSwitch); return; }
  const go = t0.closest("[data-acc-switch-go]");
  if (go) {
    go.disabled = true;
    if ($("accNoAsk")?.checked) await accPost({ action: "confirm_manual", on: false });
    if (await accDoSwitch(go.dataset.accSwitchGo)) accDialog().close(); else go.disabled = false;
    return;
  }
  if (t0.closest("[data-acc-undo]")) { const prev = accUi.toast?.prev; accUi.toast = null; if (prev) await accDoSwitch(prev); accUi.toast = null; ui.forcePatch = true; render(); return; }
  const dc = t0.closest("[data-acc-decide]");
  if (dc) {
    dc.disabled = true;
    const yes = dc.dataset.accDecide === "1", dst = accData().proposal?.dst, prev = accRows().find(x => x.active)?.id;
    const r = await accPost({ action: "decide", id: dc.dataset.pid, yes });
    if (!r.ok) { dc.disabled = false; return; }
    if (yes && /^Switched/.test(r.note || "")) accToast(dst, prev);
    accDone(r);
    return;
  }
  const save = t0.closest("[data-acc-save]");
  if (save) {
    save.disabled = true; accSay("muted", t("Adding…"));
    const r = await accPost({ action: "add", label: $("accName").value.trim(), token: $("accToken").value.trim(), include: $("accInclude").checked, switch_now: $("accNow").checked });
    if (!r.ok) { save.disabled = false; accSay("err", r.error); return; }
    accDialog().close(); accDone(r);
    return;
  }
  if (t0.closest("[data-acc-rules-reset]")) {
    const f = document.querySelector("[data-acc-rules-form]");
    f.querySelector("[name=mode][value=ask]").checked = true; f.switch_at.value = 80; f.switch_to.value = 60; f.when_none.value = "stay";
    f.querySelectorAll("[name=watch]").forEach(c => { c.checked = c.value !== "fable"; });
    f.querySelectorAll("[name=ask_in]").forEach(c => { c.checked = c.value !== "desktop"; });
    return;
  }
  const rs = t0.closest("[data-acc-rules-save]");
  if (rs) {
    const f = document.querySelector("[data-acc-rules-form]"), vals = n => [...f.querySelectorAll(`[name=${n}]:checked`)].map(c => c.value);
    rs.disabled = true;
    const r = await accPost({ action: "rules", mode: f.querySelector("[name=mode]:checked").value, switch_at: f.switch_at.value, switch_to: f.switch_to.value, watch: vals("watch"), ask_in: vals("ask_in"), when_none: f.when_none.value });
    rs.disabled = false;
    if (!r.ok) { accSay("err", r.error, "accRulesMsg"); return; }
    accClosePop(); accReloadState();
    return;
  }
  if (!accUi.edit) return;
  const ord = t0.closest("[data-acc-order]");
  if (ord) { accUi.edit.order = ord.dataset.accOrder; accDialog().querySelectorAll("[data-acc-order]").forEach(b => { const on = b === ord; b.classList.toggle("on", on); b.setAttribute("aria-checked", String(on)); }); return; }
  if (t0.closest("[data-acc-replace-open]")) { accUi.edit.replace = true; renderAccEdit(); return; }
  if (t0.closest("[data-acc-replace-cancel]")) { accUi.edit.replace = false; renderAccEdit(); return; }
  if (t0.closest("[data-acc-del-ask]")) { accUi.edit.del = true; renderAccEdit(); return; }
  if (t0.closest("[data-acc-del-cancel]")) { accUi.edit.del = false; renderAccEdit(); return; }
  const del = t0.closest("[data-acc-del-go]");
  if (del) { del.disabled = true; const r = await accPost({ action: "remove", id: accUi.edit.id }); if (!r.ok) { del.disabled = false; accSay("err", r.error); return; } accDialog().close(); accDone(r); return; }
  const es = t0.closest("[data-acc-edit-save]");
  if (es) {
    const a = accById(accUi.edit.id), body = { action: "update", id: a.id, enabled: $("accEnabled").checked };
    if (a.id !== "main") { body.label = $("accLabel").value.trim(); body.order = accUi.edit.order; body.token = $("accNewToken")?.value.trim() || ""; }
    es.disabled = true; accSay("muted", body.token ? t("Checking the token with Claude…") : t("Saving…"));
    const r = a.id === "main" ? await accPost({ action: "enable", id: "main", on: body.enabled }) : await accPost(body);
    es.disabled = false;
    if (!r.ok) { accSay("err", r.error); return; }
    accDialog().close(); accDone(r);
  }
});
document.addEventListener("change", async e => {
  const au = e.target.closest("[data-acc-auto]");
  if (au) { await accPost({ action: "rules", ...accRulesNow(), auto_switch: au.checked }); accReloadState(); return; }
  const inc = e.target.closest("[data-acc-include]");
  if (inc) { const r = await accPost({ action: "enable", id: inc.dataset.accInclude, on: inc.checked }); if (r.ok) accDone(r); }
});
document.addEventListener("input", e => { if (e.target.id === "accToken") accCheckToken(); });
document.addEventListener("keydown", e => {
  const pop = $("accpop");
  if (e.key === "Escape" && pop && !pop.hidden) { e.preventDefault(); accClosePop(); return; }
  if (e.key === "Enter" && e.target.closest?.("#accToken, #accName")) { e.preventDefault(); const s = accDialog().querySelector("[data-acc-save]"); if (s && !s.disabled) s.click(); return; }
  if (e.key === "Enter" && e.target.closest?.("#accLabel, #accNewToken")) { e.preventDefault(); accDialog().querySelector("[data-acc-edit-save]")?.click(); return; }
  if (accUi.menu && pop && !pop.hidden && !e.target.closest?.("input, textarea")) {
    if (e.key === "r" || e.key === "R") { e.preventDefault(); pop.querySelector("[data-acc-refresh]")?.click(); }
    else if (e.key === "e" || e.key === "E") { e.preventDefault(); pop.querySelector("[data-acc-edit]")?.click(); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      const items = [...pop.querySelectorAll("[role=menuitem], input")], i = items.indexOf(document.activeElement);
      e.preventDefault(); items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length]?.focus();
    }
  }
});
window.addEventListener("hashchange", accClosePop);
