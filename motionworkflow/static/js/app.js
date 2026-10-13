// Router and app shell.

import { $, $$, api, esc, icon, money, onState, refreshLibrary, refreshModels, refreshStatus, state, toast } from "./core.js";
import { renderCreatePage } from "./forms.js";
import { assets, home, project, projects, settings } from "./pages.js";
import { SERVICES } from "./services.js";
import { spending } from "./spending.js";

const page = $("#page");
let cleanup = null;

function setCrumbs(parts) {
  $("#crumbs").innerHTML = parts.map((p, i) => i === parts.length - 1
    ? `<span class="here">${esc(p.label)}</span>`
    : `<a href="${p.href}">${esc(p.label)}</a>${icon("chev")}`).join("");
  const waiting = state.status?.jobs?.awaiting_approval || 0;
  document.title = `${waiting ? `(${waiting}) ` : ""}${parts[parts.length - 1].label} · MotionWorkflow`;
}

function setActive(route) {
  $$(".nav a").forEach((a) => {
    const r = a.dataset.route;
    const on = route === r || (r !== "home" && route.startsWith(r + "/")) || (r === "projects" && route.startsWith("projects"));
    if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
}

// Tell the person when a project needs them or finishes, wherever they are in the app.
let seen = null;
function notify(st) {
  const items = st.attention || [];
  const key = (x) => `${x.id}:${x.state}:${x.stage || ""}`;
  if (seen === null) { seen = new Set(items.map(key)); return; }  // first load: nothing is "new"
  const here = location.hash.replace(/^#\/?/, "");
  for (const x of items) {
    if (seen.has(key(x))) continue;
    seen.add(key(x));
    if (here === `projects/${x.id}`) continue;  // already looking at it
    const href = `#/projects/${x.id}`;
    if (x.state === "awaiting_approval") toast(`“${x.title}” is ready for your review.`, "warn", 12000, { label: "Review", href });
    else if (x.state === "done") toast(`“${x.title}” is finished.`, "good", 9000, { label: "Open", href });
    else if (x.state === "error") toast(`“${x.title}” stopped with a problem.`, "bad", 12000, { label: "See why", href });
  }
}

function drawShell() {
  const st = state.status;
  if (!st) return;
  notify(st);
  const b = st.budget;
  $("#spentToday").textContent = money(b.spent_today);
  $("#dailyBudget").textContent = money(b.daily_budget);
  $("#spentBar").style.width = `${Math.min(100, (b.spent_today / Math.max(0.01, b.daily_budget)) * 100)}%`;
  const names = { fal: "fal", claude: "Claude", replicate: "Replicate", enhancor: "Enhancor" };
  $("#providerDots").innerHTML = Object.entries(names).map(([k, v]) => `<span class="dot ${st.providers[k] ? "on" : ""}" title="${v}: ${st.providers[k] ? "key saved" : "no key"}">${v}</span>`).join("");
  const waiting = st.jobs.awaiting_approval || 0;
  const working = (st.jobs.running || 0) + (st.jobs.queued || 0);
  const nav = $("#navProjects");
  nav.className = `count ${waiting ? "alert" : ""}`;
  nav.textContent = waiting ? `${waiting} to approve` : working ? `${working} working` : "";
  document.title = document.title.replace(/^\(\d+\) /, "");
  if (waiting) document.title = `(${waiting}) ${document.title}`;
  const lib = st.library.avatars + st.library.voices;
  $("#navAssets").textContent = lib ? String(lib) : "";
  $("#navSpend").textContent = b.spent_today > 0 ? `${money(b.spent_today)} today` : "";
}

async function route() {
  cleanup?.();
  cleanup = null;
  $("#shell").classList.remove("nav-open");
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, qs] = raw.split("?");
  const query = new URLSearchParams(qs || "");
  const parts = path.split("/").filter(Boolean);
  const key = parts[0] || "home";
  setActive(parts.length ? parts.join("/") : "home");
  $("#topActions").innerHTML = "";
  page.innerHTML = `<div class="skeleton" style="height:120px;margin-bottom:16px"></div><div class="skeleton" style="height:320px"></div>`;
  try {
    if (key === "home") {
      setCrumbs([{ label: "Home" }]);
      await home(page);
    } else if (key === "create" && SERVICES[parts[1]]) {
      const svc = SERVICES[parts[1]];
      setCrumbs([{ label: "Create", href: "#/" }, { label: svc.eyebrow.split(" ·")[0] }]);
      await refreshLibrary();
      const view = renderCreatePage(page, svc);
      const pre = {};
      for (const k of ["avatar", "voice"]) if (query.has(k)) pre[`${k}_id`] = query.get(k);
      if (Object.keys(pre).length) { Object.assign(view.ctx.values, pre); view.rerenderPickers(); }
      const tier = query.get("tier") && $(`input[name="tier"][value="${CSS.escape(query.get("tier"))}"]`, page);
      if (tier) tier.checked = true;
      if (Object.keys(pre).length || tier) view.ctx.changed();
    } else if (key === "projects" && parts[1]) {
      setCrumbs([{ label: "Projects", href: "#/projects" }, { label: "…" }]);
      cleanup = await project(page, parts[1], (title) => setCrumbs([{ label: "Projects", href: "#/projects" }, { label: title }]));
    } else if (key === "projects") {
      setCrumbs([{ label: "Projects" }]);
      await projects(page, query);
    } else if (key === "assets") {
      setCrumbs([{ label: "Avatars & voices" }]);
      await assets(page);
    } else if (key === "spending") {
      setCrumbs([{ label: "Spending" }]);
      cleanup = await spending(page, query);
    } else if (key === "settings") {
      setCrumbs([{ label: "Settings", href: "#/settings" }, { label: { keys: "API keys", budget: "Budget & defaults", models: "Models & prices", skills: "Skills & tools", appearance: "Appearance" }[parts[1] || "keys"] || "Settings" }]);
      await settings(page, parts[1]);
    } else {
      setCrumbs([{ label: "Not found" }]);
      page.innerHTML = `<div class="empty">${icon("alert")}<b>Page not found</b><div><a href="#/">Go home</a></div></div>`;
    }
  } catch (e) {
    page.innerHTML = `<div class="empty">${icon("alert")}<b>Couldn't load this page</b><div>${esc(e.message)}</div></div>`;
  }
  page.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

$("#menuBtn").onclick = () => $("#shell").classList.add("nav-open");
$("#scrim").onclick = () => $("#shell").classList.remove("nav-open");
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { $("#shell").classList.remove("nav-open"); $$("details.menu[open]").forEach((d) => d.removeAttribute("open")); }
});
// Close an open "more" menu when clicking anywhere else.
document.addEventListener("click", (e) => { $$("details.menu[open]").forEach((d) => { if (!d.contains(e.target) || e.target.closest(".menu-pop")) d.removeAttribute("open"); }); });

window.addEventListener("hashchange", route);
onState(drawShell);

(async () => {
  try {
    await Promise.all([refreshStatus(), refreshModels()]);
  } catch (e) {
    toast("Can't reach the MotionWorkflow server. Is it running?", "bad", 10000);
  }
  if (!state.status?.ffmpeg) toast("ffmpeg is missing: videos can't be edited until it's installed.", "bad", 8000);
  route();
  setInterval(() => { if (!document.hidden) refreshStatus().catch(() => {}); }, 10000);
})();

export { api };
