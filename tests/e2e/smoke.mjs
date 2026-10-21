import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { chromium } from "playwright";

const root = resolve(import.meta.dirname, "../..");
const data = mkdtempSync(join(tmpdir(), "opsboard-e2e-"));
const port = await new Promise(ok => { const s = createServer().listen(0, () => { const p = s.address().port; s.close(() => ok(p)); }); });
const base = `http://127.0.0.1:${port}`;
const user = value => ({ user: { value } });
writeFileSync(join(data, "config.json"), JSON.stringify({
  version: 1,
  migrated: true,
  settings: {
    "project.root": user(root),
    "gitlab.url": user("http://127.0.0.1:9"),
    "gitlab.project": user("team/app"),
    "jira.site": user("http://127.0.0.1:9"),
    "jira.email": user("dev@example.com"),
  },
  secrets: { "gitlab.token": "test-gitlab-token", "jira.token": "test-jira-token" },
}));
const started = Date.now() / 1000 - 600;
writeFileSync(join(data, "runs.json"), JSON.stringify([{ id: "r1", iid: 7, name: "fix !7", prompt: "/fix 7", pid: 999999, started, ended: started + 300, status: "done", exited: true, log: join(data, "none.jsonl") }]));
writeFileSync(join(data, "notifications.json"), JSON.stringify([{ id: "n1", kind: "run", run_id: "r1", iid: 7, name: "fix !7", status: "done", outcome: { status: "pushed", commit: "a1b2c3d" }, error: "", mr_title: "", at: started + 300, read: false }]));
const server = spawn(process.env.PYTHON || "python3", [join(root, "server.py"), "--port", String(port)], {
  env: { ...process.env, OPS_DATA_DIR: data, OPS_SECRET_STORE: "file", OPS_HIS_ROOT: root, OPS_CLAUDE_CREDENTIALS: join(data, "none.json"), OPS_ANTHROPIC_URL: "http://127.0.0.1:9", OPS_NO_OS_NOTIFY: "1" },
  stdio: "ignore",
});
const failures = [];
const check = (ok, what) => { console.log(`${ok ? "ok  " : "FAIL"} ${what}`); if (!ok) failures.push(what); };

try {
  for (let i = 0; i < 100; i++) { try { await fetch(`${base}/api/notes`); break; } catch { await new Promise(r => setTimeout(r, 200)); } }
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on("pageerror", e => errors.push(e.message));
  for (const route of ["", "sessions", "docker", "postgres", "tasks", "mrs", "worktrees", "processes", "notes", "settings"]) {
    await page.goto(`${base}/#/${route}`);
    await page.waitForTimeout(800);
    const stayed = new URL(page.url()).hash === `#/${route}`;
    check(stayed && (await page.locator("#view h1, #view section").count()) > 0, `page ${route || "overview"} renders`);
  }
  await page.goto(`${base}/#/`);
  await page.waitForTimeout(1200);
  const bell = page.locator(".sidebar [data-bell]");
  check((await bell.locator(".bcount").textContent()) === "1", "the bell counts the unread notification");
  check((await page.title()) === "(1) Opsboard", "the tab title shows the unread count");
  await bell.click();
  check(await page.locator("#npanel").isVisible(), "the bell opens the notification panel");
  check((await page.locator("#npanel .nhead").first().textContent()) === "Fix pushed · !7", "a finished fix is listed");
  await page.locator("#npanel [data-notif-open]").first().click();
  await page.waitForTimeout(600);
  check(await page.evaluate(() => document.querySelector('#view [data-run="r1"]')?.getAnimations().length === 1), "the opened run blinks once");
  check(await page.locator("#npanel").isHidden(), "opening a notification closes the panel");
  check(await bell.locator(".bcount").isHidden(), "opening a notification marks it read");
  check((await page.locator('#view [data-run="r1"]').count()) === 1, "the finished run is shown on Overview");
  check(JSON.parse(readFileSync(join(data, "notifications.json"), "utf8"))[0].read === true, "read state is saved on the server");
  await page.goto(`${base}/#/mr/7`);
  await page.waitForTimeout(1500);
  check((await page.locator("#view .err").textContent()).includes("not one of your merge requests"), "the request page refuses requests that are not yours");
  check((await page.locator("#nav .navi.on").textContent()).includes("Merge requests"), "the request page keeps Merge requests active in the menu");
  await page.goto(`${base}/#/notes`);
  await page.waitForTimeout(800);
  await page.click("[data-nadd]");
  await page.keyboard.type("smoke note");
  await page.waitForTimeout(1500);
  const saved = await (await fetch(`${base}/api/notes`)).json();
  check(saved.items.some(i => i.text === "smoke note" && i.tag === "todo"), "a new note is saved as ToDo");
  await page.selectOption("#noteRange", "today");
  await page.waitForTimeout(300);
  check((await page.locator("[data-ntext]").count()) === 1, "date filter applies at once");
  const note = page.locator("[data-ntext]").first();
  await note.click();
  await page.keyboard.press("End");
  await page.waitForTimeout(2500);
  await page.keyboard.type(" kept");
  check((await note.textContent()) === "smoke note kept", "typing survives the 2 s refresh");
  for (let i = 0; i < 5; i++) await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(300);
  const lines = await page.locator("[data-ntext]").allTextContents();
  check(lines[0] === "smoke note" && lines[1] === " kept", `Enter splits the line (${JSON.stringify(lines)})`);
  check(await page.evaluate(() => document.activeElement?.textContent === " kept"), "focus moves to the new line");
  await page.selectOption("#noteRange", "all");
  await page.goto(`${base}/#/settings`);
  await page.waitForTimeout(800);
  const portField = page.locator('[data-set-key="server.port"]');
  await portField.fill("9999");
  await page.locator("#view h1").click();
  await page.waitForTimeout(2500);
  check((await portField.inputValue()) === "9999", "an edited setting is not reset by the refresh");
  await page.locator(".setupclaude summary").click();
  await page.waitForTimeout(3000);
  check(await page.locator(".setupclaude").evaluate(d => d.open), "an opened section stays open after the refresh");
  check(readFileSync(join(data, ".page-token"), "utf8").length > 20, "page token written to the test data dir");
  check(errors.length === 0, `no page errors ${errors.join(" | ")}`);

  const hubData = mkdtempSync(join(tmpdir(), "opsboard-e2e-gh-"));
  writeFileSync(join(hubData, "config.json"), JSON.stringify({
    version: 1,
    settings: { "project.root": user(root), "review.host": user("github"), "github.url": user("https://127.0.0.1:9"), "github.repo": user("acme/shop"), "tasks.tracker": user("none"), "ui.language": user("ru"), "claude.live_usage": user(false) },
    secrets: { "github.token": "test-github-token" },
  }));
  const hubPort = port + 1;
  const hub = spawn(process.env.PYTHON || "python3", [join(root, "server.py"), "--port", String(hubPort)], {
    env: { ...process.env, OPS_DATA_DIR: hubData, OPS_SECRET_STORE: "file", OPS_HIS_ROOT: root, OPS_CLAUDE_CREDENTIALS: join(data, "none.json"), OPS_ANTHROPIC_URL: "http://127.0.0.1:9" },
    stdio: "ignore",
  });
  try {
    const hubBase = `http://127.0.0.1:${hubPort}`;
    for (let i = 0; i < 100; i++) { try { await fetch(`${hubBase}/api/notes`); break; } catch { await new Promise(r => setTimeout(r, 200)); } }
    await page.goto(`${hubBase}/#/mrs`);
    await page.waitForTimeout(1200);
    check(new URL(page.url()).hash === "#/mrs", "GitHub without Jira is not locked behind Settings");
    check((await page.locator("#view h1").textContent()) === "Pull requests", "GitHub wording on the requests page");
    check((await page.locator("#nav").textContent()).includes("Pull requests"), "GitHub wording in the navigation");
    check((await page.locator("#nav").textContent()).includes("Обзор"), "the page is translated (ru)");
    check((await page.locator("#fix h3").textContent()) !== "Run fix", "static dialogs are translated too");
    await page.goto(`${hubBase}/#/`);
    await page.waitForTimeout(1200);
    check((await page.locator("#hstats").textContent()).includes("CPU"), "with live usage off the sidebar shows the machine");
    check((await page.locator("#view .tile").count()) === 0, "with live usage off Overview leaves out the machine tiles");
    await page.goto(`${hubBase}/#/tasks`);
    await page.waitForTimeout(800);
    check(!(await page.locator("#view .pagehead").textContent()).includes("Jira"), "no Jira on Tasks when the tracker is off");
    await page.goto(`${hubBase}/#/settings`);
    await page.waitForTimeout(800);
    check((await page.locator("#tok-github").count()) === 1 && (await page.locator("#tok-gitlab").count()) === 0, "Settings shows the GitHub token, not GitLab");
    check(errors.length === 0, `no page errors with GitHub ${errors.join(" | ")}`);
  } finally {
    hub.kill();
  }
  await browser.close();
} finally {
  server.kill();
}
process.exit(failures.length ? 1 : 0);
