const NOTIF = { seen: null };
const notifs = () => data?.notifications || [];
const unreadNotifs = () => notifs().filter(n => !n.read);
const canAlert = () => "Notification" in window && Notification.permission === "granted";

function notifText(n) {
  const o = n.outcome || {}, ref = n.iid ? mrRef(n.iid) : n.name;
  if (n.kind === "thread") return { level: "info", head: `New thread · ${ref}${n.path && n.line ? ` · ${n.path.split("/").pop()}:${n.line}` : ""}`, body: `${n.author}: ${n.body}` };
  if (n.status === "error") return { level: "bad", head: `Fix failed · ${ref}`, body: n.error || "The run ended with an error" };
  if (o.status === "stopped") return { level: "bad", head: `Fix stopped · ${ref}`, body: o.note || "It could not finish" };
  const th = o.threads ? `threads ${o.threads.resolved ?? 0} resolved · ${o.threads.open ?? 0} open` : "";
  const body = [o.commit ? String(o.commit).slice(0, 10) : "", th, o.checks || "", o.note || ""].filter(Boolean).join(" · ");
  return { level: o.status === "committed" ? "warn" : "ok", head: `Fix ${o.status || "finished"} · ${ref}`, body };
}

function renderBell() {
  const n = unreadNotifs().length;
  document.querySelectorAll("[data-bell]").forEach(b => {
    const c = b.querySelector(".bcount");
    c.textContent = n > 9 ? "9+" : String(n);
    c.hidden = !n;
    b.classList.toggle("has", n > 0);
    const label = n ? t(plural(n, "unread notification")) : t("Notifications");
    b.title = label; b.setAttribute("aria-label", label);
  });
  document.title = n ? `(${n}) Opsboard` : "Opsboard";
  if (!$("npanel").hidden) renderNotifPanel();
  announceNew();
}

function announceNew() {
  const items = notifs();
  if (!NOTIF.seen) { NOTIF.seen = new Set(items.map(n => n.id)); return; }
  const fresh = items.filter(n => !NOTIF.seen.has(n.id));
  fresh.forEach(n => NOTIF.seen.add(n.id));
  const unread = fresh.filter(n => !n.read);
  if (!unread.length) return;
  document.querySelectorAll("[data-bell]").forEach(b => { b.classList.remove("ring"); void b.offsetWidth; b.classList.add("ring"); });
  if (!canAlert()) return;
  unread.forEach(n => {
    const x = notifText(n);
    try {
      const alert = new Notification(t(x.head), { body: [n.mr_title, x.body].filter(Boolean).join("\n"), tag: "opsboard-" + n.id });
      alert.onclick = () => { window.focus(); openNotif(n.id); alert.close(); };
    } catch (e) {}
  });
}

function renderNotifPanel() {
  const items = notifs();
  const perm = "Notification" in window ? Notification.permission : "unsupported";
  const alertRow = perm === "default"
    ? `<div class="nalert">${icon("bell", 14)}<span class="grow">Get a desktop alert when a fix finishes</span><button class="fixbtn" data-notif-allow>Turn on</button></div>`
    : perm === "denied" ? `<div class="nalert muted">${icon("info", 14)}<span class="grow">Desktop alerts are blocked for this page in the browser settings</span></div>` : "";
  const list = items.length ? items.map(n => {
    const x = notifText(n), mr = (data.review?.mrs || []).find(m => m.iid === n.iid);
    return `<div class="nitem ${n.read ? "" : "unread"}" data-notif-open="${esc(n.id)}" role="button" tabindex="0">
      <span class="nic ${x.level}">${icon(x.level === "info" ? "comment" : x.level === "bad" ? "fail" : "ok", 16)}</span>
      <div class="grow"><div class="nhead">${esc(x.head)}</div>${n.mr_title ? `<div class="ns" translate="no">${esc(n.mr_title)}</div>` : ""}${x.body ? `<div class="ns">${esc(x.body)}</div>` : ""}<div class="nt">${ago(n.at)}</div></div>
      ${mr ? `<a class="nlink" href="${esc(mr.url)}" target="_blank" title="Open ${esc(mrRef(mr.iid))} in ${hostName()}" aria-label="Open in ${hostName()}">${icon("mrs", 14)}</a>` : ""}
    </div>`;
  }).join("") : `<div class="empty">No notifications yet. You get one when a fix run finishes.</div>`;
  $("npanel").innerHTML = `<div class="nph"><b>Notifications</b>${unreadNotifs().length ? `<button class="linkbtn" data-notif-readall>Mark all read</button>` : ""}${items.length ? `<button class="linkbtn" data-notif-clear>Clear</button>` : ""}</div>${alertRow}<div class="nlist">${list}</div>`;
}

function openNotifPanel(btn) {
  const p = $("npanel");
  renderNotifPanel();
  p.hidden = false;
  const r = btn.getBoundingClientRect(), w = p.offsetWidth;
  p.style.left = Math.max(8, Math.min(innerWidth - w - 8, r.left)) + "px";
  p.style.top = r.bottom + 6 + "px";
  btn.setAttribute("aria-expanded", "true");
}
function closeNotifPanel() {
  $("npanel").hidden = true;
  document.querySelectorAll("[data-bell]").forEach(b => b.setAttribute("aria-expanded", "false"));
}

async function notifAction(body) {
  try { await fetch("/api/notifications", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); } catch (e) {}
}
function markNotifsRead(ids) {
  notifs().forEach(n => { if (!ids || ids.includes(n.id)) n.read = true; });
  renderBell();
  notifAction({ action: "read", ids: ids || null });
}

function blink(el) {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#3b6fe0";
  const glow = accent + "33", ring = `inset 0 0 0 2px ${accent}`;
  const box = el.parentElement && getComputedStyle(el.parentElement);
  const inner = box ? Math.max(0, parseFloat(box.borderTopLeftRadius) - parseFloat(box.borderTopWidth)) + "px" : "0px";
  const first = !el.previousElementSibling, last = !el.nextElementSibling;
  const borderRadius = [first ? inner : "0px", first ? inner : "0px", last ? inner : "0px", last ? inner : "0px"].join(" ");
  el.animate([
    { backgroundColor: "transparent", boxShadow: "inset 0 0 0 2px transparent", borderRadius },
    { backgroundColor: glow, boxShadow: ring, borderRadius, offset: 0.35 },
    { backgroundColor: glow, boxShadow: ring, borderRadius, offset: 0.55 },
    { backgroundColor: "transparent", boxShadow: "inset 0 0 0 2px transparent", borderRadius },
  ], { duration: 1800, delay: 450, easing: "ease-in-out" });
}

function openNotif(id) {
  const n = notifs().find(x => x.id === id);
  if (!n) return;
  if (!n.read) markNotifsRead([id]);
  closeNotifPanel();
  if (n.kind === "thread") { focusMrThread(n.iid, n.thread_id); return; }
  ui.focusRun = n.run_id;
  if (route().page !== "overview") location.hash = "#/"; else render();
  setTimeout(() => {
    const el = (n.iid && document.querySelector(`#view [data-mr="${n.iid}"]`)) || document.querySelector(`#view [data-run="${CSS.escape(n.run_id)}"]`);
    if (el) { el.scrollIntoView({ block: "center", behavior: "smooth" }); blink(el); }
  }, 120);
}

document.addEventListener("click", async e => {
  const bell = e.target.closest("[data-bell]");
  if (bell) { e.preventDefault(); $("npanel").hidden ? openNotifPanel(bell) : closeNotifPanel(); return; }
  if (e.target.closest("[data-notif-allow]")) { try { await Notification.requestPermission(); } catch (x) {} renderNotifPanel(); return; }
  if (e.target.closest("[data-notif-sound]")) { e.preventDefault(); notifAction({ action: "sound" }); return; }
  if (e.target.closest("[data-notif-readall]")) { markNotifsRead(null); return; }
  if (e.target.closest("[data-notif-clear]")) { data.notifications = []; renderBell(); notifAction({ action: "clear" }); return; }
  if (e.target.closest(".nlink")) { const it = e.target.closest("[data-notif-open]"); if (it) markNotifsRead([it.dataset.notifOpen]); return; }
  const it = e.target.closest("[data-notif-open]");
  if (it) { openNotif(it.dataset.notifOpen); return; }
  if (!$("npanel").hidden && !e.target.closest("#npanel")) closeNotifPanel();
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && !$("npanel").hidden) { closeNotifPanel(); return; }
  const it = e.target.closest?.("[data-notif-open]");
  if (it && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openNotif(it.dataset.notifOpen); }
});
addEventListener("resize", closeNotifPanel);
addEventListener("hashchange", () => { if (route().page !== "overview") ui.focusRun = null; closeNotifPanel(); });
