const COCKPIT = { busy: {}, msg: {} };

function waitList() { return data.claude_wait || []; }

function cockpitNav(ctx, r) {
  const waiting = new Set(waitList().map(w => w.sid));
  const n = waitList().length;
  const inbox = `<a href="#/cockpit" class="navi ${!r.arg ? "on" : ""}" ${!r.arg ? 'aria-current="page"' : ""}>${icon("inbox", 16)}<span class="lbl">Waiting for you</span>${n ? `<span class="n wait">${n}</span>` : ""}</a>`;
  const rows = ctx.sessions.map(s => {
    const tone = waiting.has(s.id) ? "warn" : s.status === "busy" ? "busy" : "idle";
    return `<a href="#/cockpit/${esc(s.id)}" class="navi cksess ${r.arg === s.id ? "on" : ""}" ${r.arg === s.id ? 'aria-current="page"' : ""} title="${esc(label(s))}"><span class="dot ${tone}"></span><span class="lbl">${esc(label(s))}</span></a>`;
  }).join("");
  return `<div class="navgroup">${inbox}</div><div class="navgroup"><div class="navtitle">Sessions</div>${rows || '<span class="navi muted">No live sessions</span>'}</div>`;
}

const WAIT_KIND = { permission_request: "Permission", permission_prompt: "Permission", question_request: "Question", question: "Question", elicitation_dialog: "Question", idle_prompt: "Finished" };

function waitCard(w) {
  const kind = WAIT_KIND[w.kind] || "Waiting";
  const tone = kind === "Permission" ? "warn" : kind === "Question" ? "acc" : "muted";
  const where = [w.name, w.cwd].filter(Boolean).join(" · ");
  const busy = COCKPIT.busy[w.req], msg = COCKPIT.msg[w.req] || "";
  const head = `<div class="wkhead"><span class="wkkind ${tone}">${kind}</span><b class="wkname" translate="no">${esc(w.name || w.sid.slice(0, 8))}</b><span class="muted fs-sm wkago">${ago(w.at)}</span></div>
    <div class="muted fs-sm mono wkwhere" translate="no">${esc(where)}</div>`;
  let body = "";
  if (w.kind === "permission_request") {
    body = `<div class="wkcmd mono" translate="no">${esc(w.message)}</div>
      <div class="wkbtns"><button class="wkb ok" data-wait-allow="${esc(w.req)}" ${busy ? "disabled" : ""}>Allow</button><button class="wkb danger" data-wait-deny="${esc(w.req)}" ${busy ? "disabled" : ""}>Deny</button></div>`;
  } else if (w.kind === "question_request" && w.questions.length) {
    body = w.questions.map((q, qi) => {
      const done = w.answers[q.question];
      return `<div class="wkq"><div class="wkqtext">${esc(q.question)}</div>${done ? `<div class="okmsg fs-sm">Answered: ${esc(done)}</div>` : `<div class="wkopts">${(q.options || []).map(o => `<button class="wkopt" data-wait-pick="${esc(w.req)}" data-q="${qi}" data-text="${esc(o.label)}" ${busy ? "disabled" : ""}><b>${esc(o.label)}</b>${o.description ? `<span class="muted fs-sm">${esc(o.description)}</span>` : ""}</button>`).join("")}</div>
        <form class="wkown" data-wait-own="${esc(w.req)}" data-q="${qi}"><label class="wksr" for="own-${esc(w.req)}-${qi}">Your own answer</label><input id="own-${esc(w.req)}-${qi}" type="text" placeholder="Or type your own answer" autocomplete="off"><button class="wkb" type="submit" ${busy ? "disabled" : ""}>Send</button></form>`}</div>`;
    }).join("");
  } else {
    body = `${w.message ? `<div class="wkmsg">${esc(w.message)}</div>` : ""}<div class="muted fs-sm">Answer it in the session on the Mac — only VS Code sessions can be answered from here.</div>`;
  }
  return `<section class="wkcard">${head}${body}${msg ? `<div class="fmsg err">${esc(msg)}</div>` : ""}</section>`;
}

function pageWaiting() {
  const list = waitList();
  const oldest = list.length ? ` · oldest ${ago(list[0].at)}` : "";
  return `<div class="pagehead"><h1>Waiting for you</h1><span class="sub">${plural(list.length, "session")}${oldest} · the same requests go to Telegram; the first answer wins</span></div>
    ${list.length ? `<div class="wkgrid">${list.map(waitCard).join("")}</div>` : `<div class="wkempty">${icon("ok", 20)}<span>Nothing waits for you. Permission prompts and questions from Claude sessions on this Mac show up here.</span></div>`}`;
}

function pageCockpit(ctx, arg) {
  return arg ? pageSession(ctx, arg) : pageWaiting(ctx);
}

async function waitAnswer(req, body) {
  COCKPIT.busy[req] = true; delete COCKPIT.msg[req]; render();
  try {
    const r = await (await fetch("/api/claude-wait-answer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ req, ...body }) })).json();
    if (!r.ok) COCKPIT.msg[req] = r.error || "Could not send it";
  } catch (x) { COCKPIT.msg[req] = "Dashboard server is not reachable"; }
  delete COCKPIT.busy[req];
  try { data = await (await fetch("/api/state", { cache: "no-store" })).json(); } catch (x) {}
  render();
}

document.addEventListener("click", e => {
  const a = e.target.closest("[data-wait-allow], [data-wait-deny]");
  if (a) { waitAnswer(a.dataset.waitAllow || a.dataset.waitDeny, { allow: !!a.dataset.waitAllow }); return; }
  const p = e.target.closest("[data-wait-pick]");
  if (p) waitAnswer(p.dataset.waitPick, { question: +p.dataset.q, text: p.dataset.text });
});
document.addEventListener("submit", e => {
  const f = e.target.closest("[data-wait-own]");
  if (!f) return;
  e.preventDefault();
  const text = f.querySelector("input").value.trim();
  if (text) waitAnswer(f.dataset.waitOwn, { question: +f.dataset.q, text });
});
