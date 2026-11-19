function accColor(p) { return p >= 95 ? "var(--bad)" : p >= 80 ? "var(--warn)" : "var(--usage)"; }
function accMeter(label, w) {
  if (!w) return `<div class="meter accm"><div class="mrow"><span>${label}</span><b class="muted">—</b></div><div class="mbar"><span style="width:0"></span></div><div class="reset">no data yet</div></div>`;
  const past = w.resets_at && w.resets_at < now(), p = past ? 0 : w.percent;
  return `<div class="meter accm"><div class="mrow"><span>${label}</span><b style="color:${p >= 80 ? accColor(p) : "inherit"}">${p}%</b></div><div class="mbar"><span style="width:${Math.min(100, p)}%;background:${accColor(p)}"></span></div><div class="reset" title="${w.resets_at ? esc(fmtDateTime(w.resets_at)) : ""}">${past ? "reset" : w.resets_at ? "resets in " + dur(Math.max(0, w.resets_at - now())) : ""}</div></div>`;
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
function pageAccounts() {
  const ca = data.claude_accounts || {};
  const rows = ca.accounts || [];
  const cards = rows.map(a => `<div role="button" tabindex="0" class="panel acccard ${a.active ? "on" : ""} ${a.enabled ? "" : "off"}" data-acc-open="${esc(a.id)}">
      <div class="acchead"><b translate="no">${esc(a.label)}</b>${accBadges(a)}</div>
      <div class="muted fs-sm">${a.id === "main" ? "Claude Code's own /login" : "setup token " + esc(a.masked)}</div>
      ${accMeter("Session (5hr)", a.windows?.five_hour)}${accMeter("Weekly (7 day)", a.windows?.seven_day)}
      <div class="accfoot muted fs-sm">${accFoot(a)}</div></div>`).join("");
  const auto = conf("claude.auto_switch");
  return `<div class="pagehead"><h1>Claude accounts</h1><span class="sub">${auto ? `Above ${esc(conf("claude.switch_at"))}% asks to switch to an account below ${esc(conf("claude.switch_to"))}%` : "Automatic switching is off"}${ca.active === "other" ? ` · <span class="err">${esc(ca.settings)} holds a token Opsboard does not know — automatic switching is paused</span>` : ""}</span>
      <span class="h2-actions"><button class="iconbtn ${ca.refreshing ? "spin" : ""}" data-acc-refresh title="Check every account now" aria-label="Refresh">${icon("refresh", 15)}</button><button class="btn-primary" data-acc-add>${icon("plus", 14)} Add account</button></span></div>
    ${accProposal()}
    <section><div class="accgrid">${cards || '<div class="muted">Loading…</div>'}</div></section>
    <section><h2>Automatic switching</h2><div class="panel form">
      ${field("claude.auto_switch", "Switch automatically", { type: "toggle", help: `When the account in use passes the limit below, Opsboard asks — here, in the sidebar and in Telegram — whether to move to the account with the most room, and switches when you say yes. It writes <code>CLAUDE_CODE_OAUTH_TOKEN</code> into <code>${esc(ca.settings || "~/.claude/settings.json")}</code>, which every new Claude Code session reads — VS Code included.` })}
      ${field("claude.switch_at", "Switch when above", { type: "number", help: "Percent of the 5-hour or the weekly limit, whichever is higher." })}
      ${field("claude.switch_to", "Only to an account below", { type: "number", help: "Percent, with numbers fresher than 30 minutes. Limits are checked every 3 min for the account in use and every 15 min for the rest — one tiny Haiku request each." })}
    </div></section>`;
}
function accDialog() {
  let d = $("accdlg");
  if (!d) { d = document.createElement("dialog"); d.id = "accdlg"; d.className = "acct accdlg"; document.body.appendChild(d); }
  return d;
}
function accSay(cls, text) { const m = $("accMsg"); if (m) { m.className = "msg " + cls; m.textContent = text; } }
function openAccAdd() {
  accDialog().innerHTML = `<h3>Add a Claude account</h3>
    <div class="muted fs-sm">Sign in to that account at claude.ai, run <code>claude setup-token</code> in a terminal and paste the token it prints. Opsboard checks it with Claude and keeps it in ${esc(data.config?._secret_store || "config.json")}.</div>
    <label>Name<input id="accName" type="text" placeholder="e.g. Work Max" maxlength="40" spellcheck="false" autocomplete="off"></label>
    <label>Token<input id="accToken" type="password" placeholder="sk-ant-oat01-…" autocomplete="off" spellcheck="false"></label>
    <div class="row"><span class="msg" id="accMsg"></span><button type="button" data-acc-close>Cancel</button><button type="button" class="btn-primary" data-acc-save>Save</button></div>`;
  translateTree(accDialog());
  accDialog().showModal();
  $("accName").focus();
}
function openAccDetail(id) {
  const a = (data.claude_accounts?.accounts || []).find(x => x.id === id);
  if (!a) return;
  accDialog().dataset.acc = id;
  accDialog().innerHTML = `<h3 translate="no">${esc(a.label)}</h3><div class="acchead">${accBadges(a)}<span class="muted fs-sm">${a.id === "main" ? "Claude Code's own /login" : "setup token " + esc(a.masked)}</span></div>
    <div class="accdlgm">${accMeter("Session (5hr)", a.windows?.five_hour)}${accMeter("Weekly (7 day)", a.windows?.seven_day)}<div class="muted fs-sm">${accFoot(a)}</div></div>
    <label class="sw"><span>Automatic switching<span class="d">${a.enabled ? "Opsboard may move to this account when the one in use runs out." : "Off — Opsboard never moves to this account by itself."}</span></span><input type="checkbox" data-acc-enable ${a.enabled ? "checked" : ""}><span class="tog"></span></label>
    <div class="row"><span class="msg" id="accMsg"></span>${a.id !== "main" ? `<button type="button" class="btn-danger" data-acc-delete>Delete</button>` : ""}<button type="button" data-acc-close>Close</button>${a.active ? "" : `<button type="button" class="btn-primary" data-acc-use>Use now</button>`}</div>`;
  translateTree(accDialog());
  if (!accDialog().open) accDialog().showModal();
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
    if (data.claude_accounts?.busy && !confirm(t("A Claude session is working right now. Switch anyway?"))) return;
    use.disabled = true;
    const r = await accPost({ action: "switch", id });
    if (!r.ok) { use.disabled = false; accSay("err", r.error); return; }
    accDone(r); openAccDetail(id); accSay("okmsg", t("New sessions use this account"));
    return;
  }
  const del = e.target.closest("[data-acc-delete]");
  if (del) {
    const a = (data.claude_accounts?.accounts || []).find(x => x.id === id) || {};
    if (!confirm(a.active ? t("This account is in use. Delete it and go back to Claude Code's own login?") : t("Delete this account and its token?"))) return;
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
  accDone(r); openAccDetail(id);
});
document.addEventListener("keydown", e => {
  const card = e.target.closest?.("[data-acc-open]");
  if (card && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openAccDetail(card.dataset.accOpen); return; }
  if (e.key === "Enter" && $("accdlg")?.open && e.target.closest("#accName, #accToken")) { e.preventDefault(); $("accdlg").querySelector("[data-acc-save]")?.click(); }
});
