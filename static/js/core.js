const OPS_TOKEN = document.querySelector('meta[name="ops-token"]')?.content || "";
const nativeFetch = window.fetch.bind(window);
window.fetch = (url, opts = {}) => {
  if (typeof url === "string" && url.startsWith("/api/") && (opts.method || "GET").toUpperCase() !== "GET") opts = { ...opts, headers: { ...(opts.headers || {}), "X-Ops-Token": OPS_TOKEN } };
  return nativeFetch(url, opts);
};
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const bytes = (n, d = 1) => { n = +n || 0; const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; while (n >= 1024 && i < 4) { n /= 1024; i++; } return n.toFixed(i < 2 ? 0 : d) + " " + u[i]; };
const num = n => { n = +n || 0; return n >= 1e9 ? (n / 1e9).toFixed(1) + "B" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? Math.round(n / 1e3) + "k" : String(n); };
const dur = s => { s = Math.max(0, s); return s < 60 ? Math.round(s) + "s" : s < 3600 ? Math.round(s / 60) + "m" : s < 86400 ? (s / 3600).toFixed(1).replace(".0", "") + "h" : Math.round(s / 86400) + "d"; };
const ago = t => t ? dur(now() - t) + " ago" : "—";
const pct = (a, b) => b ? Math.min(100, a / b * 100) : 0;
const color = p => p > 85 ? "var(--bad)" : p > 65 ? "var(--warn)" : "var(--ok)";
let data = null, clockSkew = 0;
const ui = {};
const units = v => String(v ?? "").replace(/(\d)\s*([kKMGT]?B)\b/g, (_, d, u) => `${d} ${u.replace(/^k/, "K")}`);
const plural = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`;
const isGitHub = () => (conf("review.host") || "gitlab") === "github";
const hostName = () => isGitHub() ? "GitHub" : "GitLab";
const mrWord = (plural = true) => isGitHub() ? (plural ? "Pull requests" : "Pull request") : (plural ? "Merge requests" : "Merge request");
const mrRef = n => (isGitHub() ? "#" : "!") + n;
const displayKey = key => String(key).startsWith("!") ? mrRef(String(key).slice(1)) : key;
const showUsage = () => data?.config?.["claude.live_usage"]?.value !== false;
const tasksPage = () => (hasJira() ? "Jira" : "Tasks");
const mrsPage = () => hostName();
const hasJira = () => (data?.tracker || "none") === "jira";
const canRunFix = () => !!conf("claude.fix_skill") && (conf("claude.skills") || []).includes(conf("claude.fix_skill")) && conf("claude.background_runs") !== false;
const fill = (tpl, vars) => tpl ? tpl.replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? "") : "";
const composeProject = () => (data.containers || []).find(c => c.name === conf("db.container"))?.project || "";
const wtContainer = slug => fill(data.profile?.containers?.per_worktree, { project: composeProject(), slug });
const wtDbs = slug => (data.profile?.databases?.per_worktree || []).map(t => fill(t, { slug }));
const isLeftover = name => { const t = data.profile?.containers?.leftover; return !!t && new RegExp(fill(t, { project: composeProject() })).test(name); };
function slugMatcher(templates) {
  const rxEscape = x => x.replace(/[.*+?^$()|[\]\\{}]/g, "\\$&");
  const res = templates.filter(Boolean).map(t => new RegExp("^" + rxEscape(fill(t, { project: composeProject(), slug: "\u0000" })).replace("\u0000", "(.+?)") + "$"));
  return name => { for (const re of res) { const m = name.match(re); if (m) return m[1]; } return undefined; };
}
const now = () => Date.now() / 1000 - clockSkew;
const expanded = new Set();
try { const t = localStorage.getItem("ops.theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
const I18N = { lang: "en", dict: {}, patterns: [] };
const RE_NUM = /\d+(?:[.,]\d+)?/g;
function t(s) {
  if (I18N.lang === "en" || !s) return s;
  const hit = I18N.dict[s];
  if (hit) return hit;
  const nums = s.match(RE_NUM);
  const tpl = nums && I18N.dict[s.replace(RE_NUM, "{n}")];
  if (tpl) { let i = 0; return tpl.replace(/\{n\}/g, () => nums[i++] ?? ""); }
  for (const [re, out] of I18N.patterns) { const m = s.match(re); if (m) { let i = 1; return out.replace(/\{[ns]\}/g, () => m[i++] ?? ""); } }
  if (s.includes(" · ")) { const parts = s.split(" · "), tr = parts.map(t); if (tr.some((x, i) => x !== parts[i])) return tr.join(" · "); }
  return s;
}
function compilePatterns(dict) {
  const rx = x => x.replace(/[.*+?^$()|[\]\\]/g, "\\$&");
  return Object.entries(dict).filter(([k]) => k.includes("{s}")).map(([k, v]) => [new RegExp("^" + k.split(/(\{[ns]\})/).map(p => p === "{s}" ? "(.+?)" : p === "{n}" ? "(\\d+(?:[.,]\\d+)?)" : rx(p)).join("") + "$"), v]);
}
const I18N_ATTRS = ["title", "placeholder", "aria-label"];
function translateTree(root) {
  if (I18N.lang === "en") return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
    acceptNode: n => n.nodeType === 1 && (n.getAttribute("translate") === "no" || n.tagName === "CODE" || n.tagName === "SCRIPT" || n.tagName === "STYLE") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  for (let n = walker.currentNode; n; n = walker.nextNode()) {
    if (n.nodeType === 3) {
      const raw = n.nodeValue, text = raw.trim();
      if (text && /[A-Za-z]/.test(text)) { const tr = t(text); if (tr !== text) n.nodeValue = raw.replace(text, tr); }
    } else {
      for (const a of I18N_ATTRS) { const v = n.getAttribute(a); if (v && /[A-Za-z]/.test(v)) { const tr = t(v); if (tr !== v) n.setAttribute(a, tr); } }
    }
  }
}
async function loadLanguage() {
  const want = (conf("ui.language") || navigator.language || "en").slice(0, 2).toLowerCase();
  if (want === I18N.lang) return false;
  if (!["uz", "ru"].includes(want)) { I18N.lang = "en"; I18N.dict = {}; return true; }
  try { I18N.dict = await (await fetch(`/static/i18n/${want}.json`)).json(); I18N.patterns = compilePatterns(I18N.dict); I18N.lang = want; } catch (e) { I18N.lang = "en"; I18N.dict = {}; I18N.patterns = []; }
  document.documentElement.lang = I18N.lang;
  return true;
}
const i18nObserver = new MutationObserver(list => {
  if (I18N.lang === "en") return;
  for (const m of list) {
    const el = m.target.nodeType === 3 ? m.target.parentElement : m.target;
    if (el && el.id !== "view" && el.id !== "nav" && el.id !== "hstats") translateTree(el);
  }
});
function watchTranslations() { i18nObserver.observe(document.body, { childList: true, characterData: true, subtree: true }); }

