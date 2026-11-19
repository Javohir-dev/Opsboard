function accColor(p) { return p >= 95 ? "var(--bad)" : p >= 80 ? "var(--warn)" : "var(--usage)"; }
function accMeter(label, w) {
  if (!w) return `<div class="meter accm"><div class="mrow"><span>${label}</span><b class="muted">—</b></div><div class="mbar"><span style="width:0"></span></div><div class="reset">no data yet</div></div>`;
  const past = w.resets_at && w.resets_at < now(), p = past ? 0 : w.percent;
  return `<div class="meter accm"><div class="mrow"><span>${label}</span><b style="color:${p >= 80 ? accColor(p) : "inherit"}">${p}%</b></div><div class="mbar"><span style="width:${Math.min(100, p)}%;background:${accColor(p)}"></span></div><div class="reset" title="${w.resets_at ? esc(fmtDateTime(w.resets_at)) : ""}">${past ? "reset" : w.resets_at ? "resets in " + dur(Math.max(0, w.resets_at - now())) : ""}</div></div>`;
}
function accResets(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000), today = new Date();
  const time = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  if (ts < now()) return "Reset — refreshing";
  return d.toDateString() === today.toDateString() ? `Resets at ${time}` : `Resets ${d.toLocaleDateString("en-US", { weekday: "short" })} ${time}`;
}
function accRow(title, w) {
  const past = w && w.resets_at && w.resets_at < now(), p = !w || past ? 0 : w.percent;
  const tone = p >= 95 ? "bad" : p >= 80 ? "warn" : "";
  return `<div class="ulrow"><div class="ulname"><div class="ult">${esc(title)}</div><div class="ulr" title="${w?.resets_at ? esc(fmtDateTime(w.resets_at)) : ""}">${w ? accResets(w.resets_at) : "No data yet"}</div></div>
    <div class="ulbar ${tone}" role="progressbar" aria-valuenow="${p}" aria-valuemin="0" aria-valuemax="100" aria-label="${esc(title)}"><span style="width:${Math.min(100, p)}%"></span></div><div class="ulp">${w ? p + "% used" : "—"}</div></div>`;
}
function accLimits(a) {
  const w = a.windows || {};
  const scoped = Object.entries(w).filter(([k]) => k.startsWith("seven_day_")).sort(([x], [y]) => x.localeCompare(y));
  return `<div class="ulim">${accRow("Current session", w.five_hour)}<div class="ulhead">Weekly limits</div>${accRow("All models", w.seven_day)}${scoped.map(([, x]) => accRow(x.label || "Model", x)).join("")}</div>`;
}
function accFoot(a) {
  if (a.error) return `<span class="err" title="${esc(a.error)}">${esc(a.error.slice(0, 70))}</span>`;
  return a.at ? `updated ${ago(a.at)}` : "not checked yet";
}
function accBadges(a) {
  return `${a.active ? '<span class="badge ok">in use</span>' : ""}${a.enabled ? "" : '<span class="badge idle" title="Automatic switching never moves to this account">auto-switch off</span>'}`;
}
function accProposal() {
  const p = data.claude_accounts?.proposal;
  if (!p) return "";
  return `<div class="accprop"><div><b>Switch to <span translate="no">${esc(p.dst)}</span>?</b><div class="muted fs-sm"><span translate="no">${esc(p.src)}</span> is at ${esc(p.level)}%${p.to_level != null ? ` · <span translate="no">${esc(p.dst)}</span> ${esc(p.to_level)}%` : ""}</div></div>
    <div class="accpropbtns"><button class="btn-primary" data-acc-decide="1" data-pid="${esc(p.pid)}">Switch</button><button class="linkbtn" data-acc-decide="0" data-pid="${esc(p.pid)}">Not now</button></div></div>`;
}
function accSub(a) {
  return a.id === "main" ? "Claude Code's own /login" : "setup token " + esc(a.masked) + (a.login ? " · also your Claude Code login" : "");
}
function pageAccounts() {
  const ca = data.claude_accounts || {};
  const rows = ca.accounts || [];
  const cards = rows.map(a => `<div role="button" tabindex="0" class="panel acccard ${a.active ? "on" : ""} ${a.enabled ? "" : "off"}" data-acc-open="${esc(a.id)}" aria-label="${esc(a.label)} — open">
      <div class="acctop"><div class="acchead"><b translate="no">${esc(a.label)}</b>${a.plan ? `<span class="accplan">${esc(a.plan)}</span>` : ""}${accBadges(a)}</div><span class="muted fs-sm">${accFoot(a)}</span></div>
      <div class="muted fs-sm">${accSub(a)}</div>
      ${accLimits(a)}</div>`).join("");
  const auto = conf("claude.auto_switch");
  return `<div class="pagehead"><h1>Claude accounts</h1><span class="sub">${auto ? `Above ${esc(conf("claude.switch_at"))}% asks to switch to an account below ${esc(conf("claude.switch_to"))}%` : "Automatic switching is off"}${ca.active === "other" ? ` · <span class="err">${esc(ca.settings)} holds a token Opsboard does not know — automatic switching is paused</span>` : ""}</span>
      <span class="h2-actions"><button class="iconbtn ${ca.refreshing ? "spin" : ""}" data-acc-refresh title="Check every account now" aria-label="Refresh">${icon("refresh", 15)}</button><button class="btn-primary" data-acc-add>${icon("plus", 14)} Add account</button></span></div>
    ${accProposal()}
    <section><div class="acclistv">${cards || '<div class="muted">Loading…</div>'}</div></section>
    <section><h2>Automatic switching</h2><div class="panel form">
      ${field("claude.auto_switch", "Switch automatically", { type: "toggle", help: `When the account in use passes the limit below, Opsboard asks — here, in the sidebar and in Telegram — whether to move to the account with the most room, and switches when you say yes. It writes <code>CLAUDE_CODE_OAUTH_TOKEN</code> into <code>${esc(ca.settings || "~/.claude/settings.json")}</code>, which every new Claude Code session reads — VS Code included.` })}
      ${field("claude.switch_at", "Switch when above", { type: "number", help: "Percent of the 5-hour or the weekly limit, whichever is higher." })}
      ${field("claude.switch_to", "Only to an account below", { type: "number", help: "Percent, with numbers fresher than 30 minutes. Limits are checked every 3 min for the account in use and every 15 min for the rest — one tiny Haiku request each." })}
    </div></section>`;
}
function accDialog() {
  let d = $("accdlg");
  if (!d) {
    d = document.createElement("dialog"); d.id = "accdlg"; d.className = "acct accdlg"; document.body.appendChild(d);
    d.addEventListener("cancel", e => { if (accUi.edit || accUi.del) { e.preventDefault(); accUi.edit = accUi.del = false; openAccDetail(d.dataset.acc, false); } });
    d.addEventListener("click", e => { if (e.target === d) d.close(); });
  }
  return d;
}
function accSay(cls, text) { const m = $("accMsg"); if (m) { m.className = "msg " + cls; m.textContent = text; } }
function openAccAdd() {
  accUi.edit = accUi.del = false;
  accDialog().dataset.acc = "";
  accDialog().innerHTML = `<div class="accdlg-head"><div class="grow"><h3>Add a Claude account</h3><div class="muted fs-sm">Sign in to that account at claude.ai, run <code>claude setup-token</code> in a terminal and paste the token it prints.</div></div>
      <button type="button" class="iconbtn ghost" data-acc-close title="Close (Esc)" aria-label="Close">${icon("x", 16)}</button></div>
    <form class="accdlg-body accadd" data-acc-add-form>
      <label>Name<input id="accName" type="text" placeholder="e.g. Work Max" maxlength="40" spellcheck="false" autocomplete="off" required></label>
      <label>Token<input id="accToken" type="password" placeholder="sk-ant-oat01-…" autocomplete="off" spellcheck="false" required></label>
      <div class="muted fs-sm">Checked with Claude, then kept in ${esc(data.config?._secret_store || "config.json")}.</div>
    </form>
    <div class="msg" id="accMsg" role="status" aria-live="polite"></div>
    <div class="accfootbar"><span class="grow"></span><button type="button" data-acc-close>Cancel</button><button type="button" class="btn-primary" data-acc-save>Save</button></div>`;
  translateTree(accDialog());
  accDialog().showModal();
  $("accName").focus();
}
const accUi = { edit: false, del: false };
function openAccDetail(id, fresh = true) {
  const a = (data.claude_accounts?.accounts || []).find(x => x.id === id);
  if (!a) { if (accDialog().open) accDialog().close(); return; }
  if (fresh) { accUi.edit = false; accUi.del = false; }
  const d = accDialog();
  d.dataset.acc = id;
  const title = accUi.edit
    ? `<form class="accname-edit" data-acc-rename-form><input id="accRename" type="text" value="${esc(a.label)}" maxlength="40" spellcheck="false" autocomplete="off" aria-label="Account name" required>
        <button type="submit" class="iconbtn ok" title="Save (Enter)" aria-label="Save">${icon("check", 15)}</button><button type="button" class="iconbtn" data-acc-edit-cancel title="Cancel (Esc)" aria-label="Cancel">${icon("x", 15)}</button></form>`
    : `<div class="accname-view"><h3 translate="no" title="${esc(a.label)}">${esc(a.label)}</h3>${a.id !== "main" ? `<button type="button" class="iconbtn ghost" data-acc-edit title="Rename" aria-label="Rename">${icon("pencil", 14)}</button>` : ""}</div>`;
  const foot = accUi.del
    ? `<div class="accfootbar danger"><span class="grow">${a.active ? "It is in use — new sessions go back to Claude Code's own login." : "The token is removed from this Mac."} Delete <b translate="no">${esc(a.label)}</b>?</span><button type="button" data-acc-del-cancel>Cancel</button><button type="button" class="btn-danger" data-acc-delete>Delete</button></div>`
    : `<div class="accfootbar">${a.id !== "main" ? `<button type="button" class="linkbtn danger" data-acc-del-ask>${icon("trash", 14)} Delete</button>` : ""}<span class="grow"></span>${a.active ? '<span class="muted fs-sm">New sessions use this account</span>' : `${data.claude_accounts?.busy ? '<span class="muted fs-sm" title="Sessions read the account from their settings">A session is working</span>' : ""}<button type="button" class="btn-primary" data-acc-use>Use now</button>`}</div>`;
  d.innerHTML = `<div class="accdlg-head"><div class="grow">${title}<div class="acchead">${a.plan ? `<span class="accplan">${esc(a.plan)}</span>` : ""}${accBadges(a)}<span class="muted fs-sm">${accSub(a)}</span></div></div>
      <button type="button" class="iconbtn ghost" data-acc-close title="Close (Esc)" aria-label="Close">${icon("x", 16)}</button></div>
    <div class="accdlg-body">${accLimits(a)}<div class="muted fs-sm">${accFoot(a)}</div></div>
    <label class="sw accdlg-sw"><span>Automatic switching<span class="d">${a.enabled ? "Opsboard may offer this account when the one in use runs low." : "Off — Opsboard never offers this account."}</span></span><input type="checkbox" data-acc-enable ${a.enabled ? "checked" : ""}><span class="tog"></span></label>
    <div class="msg" id="accMsg" role="status" aria-live="polite"></div>${foot}`;
  translateTree(d);
  if (!d.open) d.showModal();
  if (accUi.edit) { const i = $("accRename"); i.focus(); i.select(); }
}
async function accPost(body) {
  try { return await (await fetch("/api/claude-accounts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json(); }
  catch (x) { return { ok: false, error: String(x) }; }
}
function accDone(r) { data.claude_accounts = r.claude_accounts; ui.forcePatch = true; render(); }
document.addEventListener("click", async e => {
  if (e.target.closest("[data-acc-add]")) { openAccAdd(); return; }
  const dc = e.target.closest("[data-acc-decide]");
  if (dc) {
    dc.disabled = true;
    const r = await accPost({ action: "decide", id: dc.dataset.pid, yes: dc.dataset.accDecide === "1" });
    if (r.ok) { accDone(r); if (r.note) alert(r.note); } else { dc.disabled = false; alert(r.error); }
    return;
  }
  const op = e.target.closest("[data-acc-open]");
  if (op) { openAccDetail(op.dataset.accOpen); return; }
  if (e.target.closest("[data-acc-close]")) { accDialog().close(); return; }
  const rf = e.target.closest("[data-acc-refresh]");
  if (rf) { rf.classList.add("spin"); const r = await accPost({ action: "refresh" }); if (r.ok) accDone(r); return; }
  const sv = e.target.closest("[data-acc-save]");
  if (sv) {
    sv.disabled = true; accSay("muted", t("Checking the token with Claude…"));
    const r = await accPost({ action: "add", label: $("accName").value.trim(), token: $("accToken").value.trim() });
    sv.disabled = false;
    if (!r.ok) { accSay("err", r.error); return; }
    accDialog().close(); accDone(r);
    return;
  }
  const id = accDialog().dataset.acc;
  const use = e.target.closest("[data-acc-use]");
  if (use) {
    use.disabled = true;
    const r = await accPost({ action: "switch", id });
    if (!r.ok) { use.disabled = false; accSay("err", r.error); return; }
    accDone(r); openAccDetail(id, false);
    return;
  }
  if (e.target.closest("[data-acc-edit]")) { accUi.edit = true; openAccDetail(id, false); return; }
  if (e.target.closest("[data-acc-edit-cancel]")) { accUi.edit = false; openAccDetail(id, false); return; }
  if (e.target.closest("[data-acc-del-ask]")) { accUi.del = true; openAccDetail(id, false); return; }
  if (e.target.closest("[data-acc-del-cancel]")) { accUi.del = false; openAccDetail(id, false); return; }
  const del = e.target.closest("[data-acc-delete]");
  if (del) {
    del.disabled = true;
    const r = await accPost({ action: "remove", id });
    if (!r.ok) { del.disabled = false; accSay("err", r.error); return; }
    accDialog().close(); accDone(r);
  }
});
document.addEventListener("change", async e => {
  const en = e.target.closest("[data-acc-enable]");
  if (!en) return;
  const id = accDialog().dataset.acc;
  const r = await accPost({ action: "enable", id, on: en.checked });
  if (!r.ok) { en.checked = !en.checked; accSay("err", r.error); return; }
  accDone(r); openAccDetail(id, false);
});
document.addEventListener("submit", async e => {
  if (e.target.closest("[data-acc-add-form]")) { e.preventDefault(); $("accdlg").querySelector("[data-acc-save]")?.click(); return; }
  const f = e.target.closest("[data-acc-rename-form]");
  if (!f) return;
  e.preventDefault();
  const id = accDialog().dataset.acc, name = $("accRename").value.trim();
  const r = await accPost({ action: "rename", id, label: name });
  if (!r.ok) { accSay("err", r.error); $("accRename").focus(); return; }
  accUi.edit = false; accDone(r); openAccDetail(id, false);
});
document.addEventListener("keydown", e => {
  const card = e.target.closest?.("[data-acc-open]");
  if (card && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openAccDetail(card.dataset.accOpen); return; }
  if (e.key === "Enter" && e.target.closest?.("#accName, #accToken")) { e.preventDefault(); $("accdlg").querySelector("[data-acc-save]")?.click(); }
  if (e.key === "Escape" && $("accdlg")?.open && (accUi.edit || accUi.del)) { e.preventDefault(); accUi.edit = accUi.del = false; openAccDetail(accDialog().dataset.acc, false); return; }
});
