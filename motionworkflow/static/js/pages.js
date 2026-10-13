// Pages other than the Create forms: Home, Projects, Project, Assets, Settings.

import {
  $, $$, api, badge, confirmAction, confirmSpend, draft, esc, icon, money, openDialog, refreshLibrary, refreshModels,
  refreshStatus, state, STATE_LABEL, timeAgo, toast, WORKFLOWS,
} from "./core.js";
import { addAvatarDialog, addVoiceDialog } from "./modals.js";
import { BLURBS, ORDER, SERVICES } from "./services.js";

const wf = (name) => WORKFLOWS[name] || { label: name, icon: "spark", color: "c1" };

const BUSY = (j) => j.active || j.state === "running" || j.state === "queued";

// "$0.28", "$0.10 of ~$1.20", "Free": what a project cost, at a glance.
function costTag(j) {
  const c = j.cost || {};
  const spent = Number(c.spent ?? j.spent) || 0;
  const est = c.estimate;
  if (j.state !== "done" && est > 0 && spent < est - 0.0005) {
    return `<span class="cost-tag" title="Spent so far, of the estimate">${money(spent)}<span class="of"> of ~${money(est)}</span></span>`;
  }
  return `<span class="cost-tag" title="Logged spend">${spent > 0 ? money(spent) : "Free"}</span>`;
}

function projectCard(j) {
  const w = wf(j.workflow);
  const cover = j.thumb ? `style="background-image:url('${j.thumb}')"` : "";
  return `<a class="pcard" href="#/projects/${j.id}">
    <div class="cover" ${cover}>${j.thumb ? "" : icon(w.icon, "xl")}<span class="status">${badge(j.state)}</span></div>
    <div class="body"><div class="t">${esc(j.title)}</div>
    <div class="m">${icon(w.icon)}<span>${w.label}</span><span>·</span><span>${timeAgo(j.created)}</span>${costTag(j)}</div></div></a>`;
}

const emptyState = (iconName, title, text, action = "") => `<div class="empty">${icon(iconName)}<b>${title}</b><div>${text}</div>${action ? `<div style="margin-top:16px">${action}</div>` : ""}</div>`;

// -- Home ------------------------------------------------------------------------------

export async function home(page) {
  const [jobs] = await Promise.all([api("/api/jobs?limit=12"), refreshLibrary()]);
  const st = state.status;
  const waiting = jobs.filter((j) => j.state === "awaiting_approval");
  const checks = [
    { done: st.providers.fal, title: "Add your fal.ai key", text: "One key unlocks the cheap image, video, voice and avatar models.", href: "#/settings/keys", cta: "Add key" },
    { done: st.providers.claude, title: "Add your Claude key", text: "Claude writes your scripts and scores finished videos.", href: "#/settings/keys", cta: "Add key" },
    { done: st.library.avatars > 0, title: "Save your avatar", text: "A photo or 10-20 s of video of you, for Presenter videos.", href: "#/assets", cta: "Add avatar" },
    { done: st.library.voices > 0, title: "Record your voice", text: "20 seconds in a quiet room and every video sounds like you.", href: "#/assets", cta: "Record" },
    { done: st.ffmpeg, title: "ffmpeg installed", text: "Needed to edit videos on this computer.", href: "#/settings/skills", cta: "How" },
  ];
  const doneCount = checks.filter((c) => c.done).length;
  page.innerHTML = `
    <section class="hero">
      <div class="eyebrow">${icon("spark")}Your studio</div>
      <h1>What are we making today?</h1>
      <p>Talking videos as you, narrated shorts, images, clips and character swaps, on the cheapest models that still look good. Every job shows its price first and waits for your approval before the expensive part.</p>
      <div class="actions">
        <a class="btn primary lg" href="#/create/presenter">${icon("presenter")}Make a presenter video</a>
        <a class="btn lg" href="#/create/short">${icon("film")}Make a short</a>
      </div>
    </section>
    ${waiting.length ? `<div class="section-title"><h2 class="h2">Waiting for you</h2><a class="btn ghost sm" href="#/projects?f=awaiting_approval">See all</a></div>
      <div class="grid" style="gap:10px">${waiting.slice(0, 3).map((j) => `<a class="approval" style="margin:0;text-decoration:none" href="#/projects/${j.id}">${icon("alert", "lg")}<div class="txt"><b>${esc(j.title)}</b><span>${esc(j.awaiting?.message || j.status)}</span></div><span class="btn primary sm">Review${icon("arrow")}</span></a>`).join("")}</div>` : ""}
    <div class="section-title"><h2 class="h2">Create</h2></div>
    <div class="services">${ORDER.map((id) => { const s = SERVICES[id]; const [name, text, price] = BLURBS[id];
      return `<a class="service" href="#/create/${id}"><span class="si ${s.color}">${icon(s.icon, "lg")}</span><h3>${name}</h3><p>${text}</p><div class="foot"><span>${price}</span><span class="go">Open${icon("arrow")}</span></div></a>`; }).join("")}</div>
    <div class="grid" style="grid-template-columns:minmax(0,1.6fr) minmax(0,1fr);gap:22px;margin-top:8px" id="homeCols">
      <div><div class="section-title"><h2 class="h2">Recent projects</h2><a class="btn ghost sm" href="#/projects">All projects${icon("arrow")}</a></div>
        ${jobs.length ? `<div class="cards">${jobs.slice(0, 4).map(projectCard).join("")}</div>` : emptyState("grid", "No projects yet", "What you make shows up here.", `<a class="btn primary" href="#/create/short">${icon("plus")}Start with a short</a>`)}</div>
      <div><div class="section-title"><h2 class="h2">Get set up</h2><span class="muted small">${doneCount} of ${checks.length}</span></div>
        <div class="card pad"><div class="meter-bar" style="margin:0 0 6px"><i style="width:${(doneCount / checks.length) * 100}%"></i></div>
        <div class="checklist">${checks.map((c) => `<div class="check-item ${c.done ? "done" : ""}"><span class="state">${icon("check")}</span><div class="txt"><b>${c.title}</b><span>${c.text}</span></div>${c.done ? "" : `<a class="btn sm" href="${c.href}">${c.cta}</a>`}</div>`).join("")}</div></div>
        <div class="grid cols-2" style="margin-top:14px">
          <div class="card stat"><div class="k">Spent today</div><div class="v">${money(st.budget.spent_today)}</div><div class="muted small">of ${money(st.budget.daily_budget)}</div></div>
          <div class="card stat"><div class="k">Finished</div><div class="v">${st.jobs.done || 0}</div><div class="muted small">${st.jobs.awaiting_approval || 0} waiting</div></div>
        </div></div>
    </div>`;
  if (matchMedia("(max-width: 1100px)").matches) $("#homeCols").style.gridTemplateColumns = "1fr";
}

// -- Projects ---------------------------------------------------------------------------

export async function projects(page, query) {
  const filter = query.get("f") || "all";
  const kind = query.get("type") || "";
  const jobs = await api("/api/jobs?limit=500");
  const filters = [["all", "All"], ["awaiting_approval", "Needs approval"], ["running", "Working"], ["done", "Done"], ["error", "Failed"], ["stopped", "Stopped"]];
  const inFilter = (j, v) => v === "all" || j.state === v || (v === "running" && j.state === "queued");
  const byFilter = jobs.filter((j) => inFilter(j, filter) && (!kind || j.workflow === kind));
  page.innerHTML = `
    <div class="page-head"><div class="titles"><h1 class="page-title">Projects</h1><p class="page-sub">Everything you've made. Open one to watch it, approve the next step, or fix a part.</p></div>
      <a class="btn primary" href="#/create/presenter">${icon("plus")}New</a></div>
    <div class="toolbar">
      <div class="chips" aria-label="Filter by status">${filters.map(([v, l]) => { const n = jobs.filter((j) => inFilter(j, v)).length;
        if (v === "stopped" && !n && filter !== v) return "";
        return `<a class="chip ${v === filter ? "active" : ""}" href="#/projects?f=${v}${kind ? `&type=${kind}` : ""}" ${v === filter ? 'aria-current="true"' : ""}>${l} <span class="muted">${n}</span></a>`; }).join("")}</div>
      <div class="spacer" style="flex:1"></div>
      <input class="input" type="search" id="projSearch" placeholder="Search titles…" aria-label="Search projects" style="width:min(240px,100%)">
      <select class="select" style="width:auto" aria-label="Type" id="typeFilter"><option value="">All types</option>${Object.entries(WORKFLOWS).map(([k, w]) => `<option value="${k}" ${k === kind ? "selected" : ""}>${w.label}</option>`).join("")}</select>
    </div>
    <div class="muted small" id="projCount" style="margin:-6px 0 12px"></div>
    <div id="projList"></div>`;
  const draw = () => {
    const q = $("#projSearch").value.trim().toLowerCase();
    const shown = q ? byFilter.filter((j) => `${j.title} ${j.params?.prompt || ""} ${j.params?.topic || ""} ${j.params?.idea || ""}`.toLowerCase().includes(q)) : byFilter;
    const spent = shown.reduce((a, j) => a + (j.cost?.spent || 0), 0);
    $("#projCount").innerHTML = `${shown.length} project${shown.length === 1 ? "" : "s"} · <a href="#/spending">${money(spent)} spent</a>`;
    $("#projList").innerHTML = shown.length ? `<div class="cards">${shown.map(projectCard).join("")}</div>`
      : q ? emptyState("grid", "No matches", `Nothing called “${esc(q)}” in this view.`)
      : emptyState("grid", filter === "all" ? "Nothing here yet" : "Nothing in this view", filter === "all" ? "Start something and it lands here." : "Try another filter.", filter === "all" ? `<a class="btn primary" href="#/create/presenter">${icon("plus")}Create</a>` : "");
  };
  $("#projSearch").addEventListener("input", draw);
  $("#typeFilter").onchange = (e) => (location.hash = `#/projects?f=${filter}${e.target.value ? `&type=${e.target.value}` : ""}`);
  draw();
}

// -- Project ------------------------------------------------------------------------------

const STAGE_TEXT = {
  voice: ["Check your script and voice", "Listen to the voice track and read the script. Edit any line and re-voice it, then approve to animate your avatar."],
  storyboard: ["Approve the storyboard", "Look at every keyframe. Redo any shot, then approve to animate them."],
  final: ["Approve the final render", "The draft is ready. Approve to render the final quality."],
  mask: ["Review the prepared clip", "Watch the WHOLE Genjutsu prep: mask coverage (hair, hands, clothes, edges, spill, flicker) or face tracking. Approve only if it's clean."],
};

const STEP_GROUP = {
  image: "Images", key: "Keyframes", voice: "Voice", clip: "Animated shots", face: "Avatar animation",
  broll: "Cutaway images", draft: "Draft", final: "Final render", review: "Fresh-eyes review", prep: "Genjutsu prep",
};
const stepLabel = (note) => {
  const [key, why] = String(note || "").split(":").map((x) => x.trim());
  const m = key.match(/^(.*)-(\d+)$/);
  const base = m ? `${STEP_GROUP[m[1]] || m[1]} ${Number(m[2]) + 1}` : STEP_GROUP[key] || key || "Charge";
  return why ? `${base} (refund: ${why})` : base;
};
const modelName = (id) => (state.models.find((m) => m.id === id)?.name) || (id === "claude:review" ? "Claude reviewer" : id || "");

// Turn a failure into the one thing to do about it.
function errorActions(job) {
  const e = job.error || job.status || "";
  const key = e.match(/\b(FAL_KEY|ANTHROPIC_API_KEY|REPLICATE_API_TOKEN|ENHANCOR_API_KEY)\b/);
  const parts = [];
  if (key) parts.push(`<a class="btn primary" href="#/settings/keys">${icon("key")}Add ${{ FAL_KEY: "fal.ai", ANTHROPIC_API_KEY: "Claude", REPLICATE_API_TOKEN: "Replicate", ENHANCOR_API_KEY: "Enhancor" }[key[1]]} key</a>`);
  if (/MW_DAILY_BUDGET|MW_MAX_COST_PER_JOB|budget/i.test(e)) parts.push(`<a class="btn" href="#/settings/budget">${icon("wallet")}Budget limits</a>`);
  if (/unclear whether the provider accepted/i.test(e)) {
    parts.push(`<button class="btn" data-act="retry-force" title="Check your provider dashboard first: this can pay twice">${icon("refresh")}Send again anyway</button>`);
  } else {
    parts.push(`<button class="btn ${parts.length ? "" : "primary"}" data-act="retry">${icon("refresh")}Retry failed steps</button>`);
  }
  return `<div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end">${parts.join("")}</div>`;
}

function costPill(j) {
  const c = j.cost || {};
  const est = c.estimate;
  const text = est > 0 && j.state !== "done" ? `${money(c.spent)} of ~${money(est)}` : money(c.spent);
  return `<span class="cost-pill" title="Spent so far${est > 0 ? ", of the estimated total" : ""}">${icon("wallet")}${text}</span>`;
}

export async function project(page, id, setCrumb) {
  let job;
  let dirty = false;
  let timer = 0;
  const post = (path, json = {}) => api(`/api/jobs/${id}/${path}`, { json });

  async function load() {
    job = await api(`/api/jobs/${id}`);
    setCrumb(job.title);
    return job;
  }

  function steps() {
    const items = Object.entries(job.steps || {});
    if (!items.length) return `<p class="muted small" style="margin:0">${esc(job.status)}</p>`;
    return `<ol class="progress-steps">${items.map(([key, s]) => `<li class="${s.state}"><span class="st"></span><div class="lbl">${esc(s.label || key)}<span>${esc(modelName(s.model))}${s.estimate ? ` · ~${money(s.estimate)}` : ""}${s.error ? ` · ${esc(s.error)}` : ""}</span></div></li>`).join("")}</ol>`;
  }

  function mainMedia() {
    const outs = job.outputs || [];
    const final = outs.find((o) => o.final && o.kind === "video") || outs.find((o) => o.final && o.kind === "image") || outs.find((o) => o.final && o.kind === "audio");
    const preview = final || [...outs].reverse().find((o) => o.kind === "video") || [...outs].reverse().find((o) => o.kind === "image" && o.path !== "thumbnail.jpg");
    const poster = outs.find((o) => o.path === "thumbnail.jpg")?.url;
    if (!preview) {
      const busy = job.active || job.state === "running" || job.state === "queued";
      const avatar = (job.inputs?.avatar || [])[0];
      if (avatar) {
        const url = `/files/${job.id}/${avatar}`;
        const media = /\.(mp4|mov|webm|mkv)$/i.test(avatar) ? `<video src="${url}" muted loop autoplay playsinline style="max-height:46vh"></video>` : `<img src="${url}" alt="Your avatar" style="max-height:46vh">`;
        const note = busy ? "Working…" : job.state === "awaiting_approval" ? "Your avatar starts talking after you approve the script and voice." : "";
        return `<div class="viewer" style="position:relative">${media}${note ? `<div class="badge plain" style="position:absolute;left:14px;bottom:14px;height:auto;padding:6px 10px;white-space:normal">${note}</div>` : ""}</div>`;
      }
      return `<div class="viewer"><div class="placeholder">${busy ? `<div class="skeleton" style="width:56px;height:56px;border-radius:50%;margin:0 auto 12px"></div>` : icon(wf(job.workflow).icon, "xl")}<div>${busy ? esc(job.status) : ""}</div></div></div>`;
    }
    if (preview.kind === "video") return `<div class="viewer"><video src="${preview.url}" controls playsinline preload="metadata" ${poster ? `poster="${poster}"` : ""}></video></div>`;
    if (preview.kind === "audio") return `<div class="card pad"><audio src="${preview.url}" controls style="width:100%"></audio></div>`;
    return `<div class="viewer"><img src="${preview.url}" alt=""></div>`;
  }

  function scriptEditor() {
    const plan = job.plan;
    if (job.workflow !== "presenter" || !plan?.lines) return "";
    const voice = (job.outputs || []).find((o) => o.path === "voice.wav");
    const times = job.line_times || [];
    const editable = !job.active && job.state !== "running";
    return `<div class="card pad" style="margin-top:18px">
      <div class="section-head" style="margin-bottom:12px"><span class="step-num">${icon("script")}</span><div><h2>Script and voice</h2><p>${esc(plan.title || "")}</p></div></div>
      ${voice ? `<audio src="${voice.url}?v=${encodeURIComponent(job.updated)}" controls style="width:100%;margin-bottom:12px"></audio>` : ""}
      <div class="lines-editor">${plan.lines.map((ln, i) => `<div class="line-ed"><span class="n">${i + 1}</span><div>
        <textarea class="textarea" data-line="${i}" rows="2" ${editable ? "" : "disabled"} aria-label="Line ${i + 1}">${esc(ln.text)}</textarea>
        ${ln.broll ? `<div class="t">${icon("image")} Cutaway: ${esc(ln.broll)}</div>` : ""}
        ${times[i] ? `<div class="t">${times[i][0].toFixed(1)}s – ${times[i][1].toFixed(1)}s</div>` : ""}</div>
        ${editable ? `<button class="btn sm" data-revoice="${i}" title="Record this line again">${icon("refresh")}Re-voice</button>` : ""}</div>`).join("")}</div>
    </div>`;
  }

  function storyboard() {
    if (job.workflow !== "short" || !job.plan?.shots) return "";
    const keys = Object.fromEntries((job.outputs || []).filter((o) => /^Shot \d+ keyframe$/.test(o.label)).map((o) => [Number(o.label.split(" ")[1]) - 1, o.url]));
    const editable = !job.active && job.state !== "running";
    return `<div class="card pad" style="margin-top:18px">
      <div class="section-head" style="margin-bottom:12px"><span class="step-num">${icon("film")}</span><div><h2>Storyboard</h2><p>${esc(job.plan.title || "")}${job.plan.takeaway ? ` · ${esc(job.plan.takeaway)}` : ""}</p></div></div>
      <div class="shots">${job.plan.shots.map((s, i) => `<div class="shot">${keys[i] ? `<img src="${keys[i]}?v=${encodeURIComponent(job.updated)}" alt="Shot ${i + 1}" loading="lazy">` : `<div class="skeleton" style="aspect-ratio:9/12;border-radius:0"></div>`}
        <div class="in"><div class="label">Shot ${i + 1}</div>
        <textarea class="textarea" data-f="visual" ${editable ? "" : "disabled"} aria-label="Shot ${i + 1} picture">${esc(s.visual)}</textarea>
        <textarea class="textarea" data-f="narration" ${editable ? "" : "disabled"} aria-label="Shot ${i + 1} narration">${esc(s.narration)}</textarea>
        <textarea class="textarea" data-f="motion" ${editable ? "" : "disabled"} aria-label="Shot ${i + 1} motion">${esc(s.motion)}</textarea>
        ${editable ? `<button class="btn sm" data-redo-shot="${i}">${icon("refresh")}Redo shot</button>` : ""}</div></div>`).join("")}</div></div>`;
  }

  function review() {
    const r = job.review;
    if (!r) return "";
    if (r.skipped) return `<div class="notice info" style="margin-top:18px">${icon("star")}<span>${esc(r.skipped)}</span></div>`;
    const pass = r.verdict === "PASS";
    const shotAt = (t) => { const ts = job.shot_times || []; let k = null; ts.forEach((s, i) => { if (t >= s) k = i; }); return k; };
    return `<div class="card pad" style="margin-top:18px">
      <div class="section-head" style="margin-bottom:8px"><span class="step-num" style="${pass ? "background:color-mix(in srgb,var(--good) 18%,transparent);color:var(--good)" : "background:color-mix(in srgb,var(--warn) 18%,transparent);color:var(--warn)"}">${icon("star")}</span>
        <div><h2>Fresh-eyes review: ${pass ? "PASS" : "RETURN"} · ${r.scores.overall ?? "?"}/10</h2><p>A reviewer that saw only the frames and timed words. Bar: 8 on every axis.</p></div></div>
      <p style="margin:0 0 10px"><i>${esc(r.retell)}</i></p>
      <table class="scores">${Object.entries(r.scores).map(([k, v]) => `<tr><td>${esc(k.replace("_", " "))}</td><td style="color:${v >= 8 ? "var(--good)" : "var(--warn)"}">${v}</td><td class="muted">${esc((r.reasons || {})[k] || "")}</td></tr>`).join("")}</table>
      <h3 class="h2" style="font-size:14px;margin:14px 0 6px">Three worst problems</h3>
      <ul style="margin:0;padding-left:18px">${(r.problems || []).map((p) => { const k = shotAt(p.time); return `<li>${p.time.toFixed(1)}s${k !== null ? ` (${job.workflow === "presenter" ? "line" : "shot"} ${k + 1})` : ""}: ${esc(p.problem)}</li>`; }).join("")}</ul>
      ${r.looks_off ? `<p class="muted small">Looks off: ${esc(r.looks_off)}</p>` : ""}</div>`;
  }

  function gallery() {
    const outs = (job.outputs || []).filter((o) => !o.final && (o.kind === "image" || o.kind === "video" || o.kind === "audio") && o.path !== "thumbnail.jpg" && !(job.workflow === "short" && /keyframe$/.test(o.label)) && o.path !== "voice.wav");
    if (!outs.length) return "";
    return `<div class="section-title" style="margin-top:26px"><h2 class="h2">Parts</h2></div><div class="gallery">${outs.map((o) => `<div class="tile">${o.kind === "video" ? `<video src="${o.url}" controls preload="metadata" playsinline></video>` : o.kind === "audio" ? `<div style="padding:12px"><audio src="${o.url}" controls style="width:100%"></audio></div>` : `<img src="${o.url}" alt="" loading="lazy">`}<div class="cap"><span>${esc(o.label)}</span><a href="${o.url}" download aria-label="Download ${esc(o.label)}">${icon("download")}</a></div></div>`).join("")}</div>`;
  }

  function costCard() {
    const c = job.cost || {};
    const est = c.estimate;
    const spent = c.spent || 0;
    const pct = est > 0 ? Math.min(100, (spent / est) * 100) : spent > 0 ? 100 : 0;
    const over = est > 0 && spent > est * 1.05;
    // Group numbered steps (voice-0, voice-1 …) so a 20-line script is one row, not twenty.
    const groups = [];
    for (const st of c.steps || []) {
      const prefix = st.key.replace(/-\d+$/, "");
      let g = groups.find((x) => x.prefix === prefix);
      if (!g) groups.push((g = { prefix, label: STEP_GROUP[prefix] || st.label, n: 0, est: 0, spent: 0, states: [], models: new Set() }));
      g.n += 1; g.est += st.estimate || 0; g.spent += st.spent || 0; g.states.push(st.state);
      if (st.model) g.models.add(modelName(st.model));
    }
    const rows = groups.map((g) => {
      const st = g.states.includes("failed") ? "failed" : g.states.every((x) => x === "done") ? "done" : g.states.some((x) => x === "running" || x === "submitting") ? "running" : "pending";
      return `<tr><td><span class="sdot ${st}" aria-hidden="true"></span><span class="sr-only">${{ done: "Done", failed: "Failed", running: "Running", pending: "Not started" }[st]}: </span>${esc(g.label)}${g.n > 1 ? ` <span class="muted">×${g.n}</span>` : ""}<div class="muted small">${esc([...g.models].join(", "))}</div></td>
        <td class="num muted">${g.est ? "~" + money(g.est) : "–"}</td><td class="num">${money(g.spent)}</td></tr>`;
    }).join("");
    const planned = !groups.length && (c.planned || []).length
      ? `<ul class="lines" style="padding:0;margin-top:12px">${c.planned.map((i) => `<li><div class="what"><b>${esc(i.label)}</b><span>${esc(i.model_name || "")}</span></div><div class="usd">${money(i.usd)}</div></li>`).join("")}</ul>` : "";
    const ledger = (c.ledger || []).map((r) => `<li><div class="what"><b>${esc(stepLabel(r.note))}</b><span>${esc(modelName(r.model))} · ${timeAgo(r.at)}</span></div><div class="usd ${r.usd < 0 ? "refund" : ""}">${r.usd < 0 ? "−" + money(-r.usd) : money(r.usd)}</div></li>`).join("");
    return `<div class="card pad cost-card"><div class="h2" style="font-size:14px;margin-bottom:10px;display:flex;align-items:center;gap:8px">${icon("wallet")}Cost</div>
      <div class="cost-hero"><div><div class="v">${money(spent)}</div><div class="muted small">spent so far</div></div>
        ${est > 0 ? `<div style="text-align:right"><div class="v2">~${money(est)}</div><div class="muted small">estimated total</div></div>` : ""}</div>
      ${est > 0 ? `<div class="meter-bar ${over ? "over" : ""}" role="img" aria-label="${Math.round(pct)}% of the estimate spent"><i style="width:${pct}%"></i></div>` : `<div style="height:10px"></div>`}
      ${c.next ? `<div class="next-cost">${icon("alert")}<span>Approving the next step costs about <b>${money(c.next)}</b>.</span></div>` : ""}
      ${rows ? `<table class="cost-steps"><thead><tr><th>Step</th><th class="num">Est.</th><th class="num">Spent</th></tr></thead><tbody>${rows}</tbody></table>` : planned}
      ${ledger ? `<details class="more" style="border:0;margin:12px 0 0;padding:0"><summary>${icon("chev")}Charges (${c.ledger.length})</summary><div class="inner"><ul class="lines" style="padding:0">${ledger}</ul></div></details>` : ""}
      ${c.mock ? `<div class="notice warn" style="margin-top:12px">${icon("key")}<span>Parts of this used free placeholder media. Add an API key for real results.</span></div>`
        : `<p class="muted small" style="margin:12px 0 0">Estimates from catalog prices, logged when each request is sent. Your provider's bill is the source of truth.</p>`}
    </div>`;
  }

  function side() {
    const files = (job.outputs || []).filter((o) => o.kind === "file");
    return `<div class="grid" style="gap:16px">
      ${costCard()}
      <div class="card pad"><div class="h2" style="font-size:14px;margin-bottom:8px">Progress</div>${steps()}</div>
      ${files.length ? `<div class="card pad"><div class="h2" style="font-size:14px;margin-bottom:8px">Files</div><div class="grid" style="gap:6px">${files.map((f) => `<a class="btn ghost sm" style="justify-content:flex-start" href="${f.url}" target="_blank" rel="noopener">${icon("script")}${esc(f.label)}</a>`).join("")}</div></div>` : ""}
      <div class="card pad"><details class="more" style="border:0;margin:0;padding:0"><summary>${icon("chev")}Activity log</summary><div class="inner"><div class="log">${esc((job.log || []).join("\n"))}</div></div></details></div>
    </div>`;
  }

  function render() {
    const w = wf(job.workflow);
    const final = (job.outputs || []).find((o) => o.final);
    const busy = job.active || job.state === "running" || job.state === "queued";
    const [stTitle, stText] = STAGE_TEXT[job.awaiting?.stage] || ["Needs your approval", ""];
    page.innerHTML = `
      <div class="page-head"><div class="titles">
        <div class="eyebrow">${icon(w.icon)}${w.label}</div>
        <h1 class="page-title">${esc(job.title)}</h1>
        <div class="flex" style="display:flex;gap:10px;align-items:center;margin-top:10px;flex-wrap:wrap">${badge(job.state)}${costPill(job)}<span class="muted small">${timeAgo(job.created)}${busy ? ` · ${esc(job.status)}` : ""}</span></div></div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-start">
          ${final ? `<a class="btn primary" href="${final.url}" download>${icon("download")}Download</a>` : ""}
          ${job.active ? `<button class="btn" data-act="stop">${icon("stop")}Stop</button>` : ""}
          ${!job.active && ["running", "queued", "stopped"].includes(job.state) ? `<button class="btn" data-act="resume">${icon("play")}Resume</button>` : ""}
          <details class="menu"><summary class="btn ghost icon-btn" aria-label="More actions" title="More actions">${icon("dots")}</summary>
            <div class="menu-pop" role="menu">
              <button role="menuitem" data-act="again">${icon("refresh")}<span>Run again<span class="sub">Same inputs and settings, new takes</span></span></button>
              <button role="menuitem" data-act="edit">${icon("edit")}<span>Edit as new<span class="sub">Open the form with these settings</span></span></button>
              ${(job.outputs || []).length ? `<a role="menuitem" href="/api/jobs/${job.id}/download" download>${icon("download")}<span>Download everything<span class="sub">Final, parts, script and review (.zip)</span></span></a>` : ""}
              ${!busy ? `<hr><button role="menuitem" class="danger" data-act="delete">${icon("trash")}<span>Delete project</span></button>` : ""}
            </div></details>
        </div></div>
      ${job.state === "awaiting_approval" && job.awaiting ? `<div class="approval">${icon("alert", "xl")}<div class="txt"><b>${stTitle}</b><span>${esc(job.awaiting.message || stText)}</span></div>
        <button class="btn primary lg" data-act="approve">${icon("check")}Approve${job.awaiting.estimate ? ` · ${money(job.awaiting.estimate)}` : ""}</button></div>` : ""}
      ${job.state === "error" ? `<div class="approval" style="border-color:color-mix(in srgb,var(--bad) 55%,transparent);background:color-mix(in srgb,var(--bad) 8%,var(--surface))">${icon("alert", "xl")}<div class="txt"><b>Something stopped this job</b><span>${esc(job.error || job.status)}</span></div>${errorActions(job)}</div>` : ""}
      ${job.state === "stopped" && !job.active ? `<div class="approval" style="border-color:var(--line-2);background:var(--surface)">${icon("stop", "xl")}<div class="txt"><b>Stopped</b><span>Nothing new is sent while it's stopped. Requests already sent may still finish at the provider (and be billed); Resume collects them without paying twice.</span></div><button class="btn primary" data-act="resume">${icon("play")}Resume</button></div>` : ""}
      ${job.warning ? `<div class="notice warn" style="margin-bottom:18px">${icon("info")}<span>${esc(job.warning)}</span></div>` : ""}
      <div class="detail"><div>${mainMedia()}${scriptEditor()}${storyboard()}${review()}${gallery()}</div><aside>${side()}</aside></div>`;
    bind();
  }

  async function startCopy() {
    try {
      return await post("duplicate", {});
    } catch (e) {
      if (e.status === 402 && e.data?.needs_confirmation) {
        if (!(await confirmSpend(e.data.quote, "A new project with the same inputs and settings."))) return null;
        return await post("duplicate", { confirm: true });
      }
      throw e;
    }
  }

  function editAsNew() {
    const keep = {};
    for (const [k, v] of Object.entries(job.params || {})) {
      if (k === "overrides" || v === null || typeof v === "object") continue;
      keep[k] = typeof v === "boolean" ? v : String(v);
    }
    if (job.workflow === "presenter" && job.plan?.lines) keep.script = job.plan.lines.map((l) => l.text).join("\n");
    draft.save(job.workflow, keep);
    const q = new URLSearchParams();
    if (job.params?.avatar_id) q.set("avatar", job.params.avatar_id);
    if (job.params?.voice_id !== undefined) q.set("voice", job.params.voice_id || "");
    if (job.params?.tier) q.set("tier", job.params.tier);
    const uploads = Object.keys(job.inputs || {}).filter((f) => !(f === "avatar" && job.params?.avatar_id) && !(f === "voice_sample" && job.params?.voice_id));
    if (uploads.length) toast("Settings copied. Add your files again (uploads aren't carried over).", "info", 6000);
    location.hash = `#/create/${job.workflow}${q.toString() ? "?" + q : ""}`;
  }

  function bind() {
    $$("textarea", page).forEach((t) => t.addEventListener("input", () => (dirty = true)));
    $$("[data-act]", page).forEach((b) => (b.onclick = async () => {
      const act = b.dataset.act;
      try {
        if (act === "approve") {
          if (job.awaiting?.estimate >= (state.status?.budget.confirm_above ?? 0.5)
              && !(await confirmSpend({ total: job.awaiting.estimate, items: [] }, job.awaiting.message))) return;
          await post("approve", { stage: job.awaiting.stage });
          toast("Approved. Working on it.", "good");
        } else if (act === "retry") {
          if (!(await confirmAction("Retry failed steps?", "Failed steps are sent again, which can cost money again.", "Retry"))) return;
          await post("retry");
        } else if (act === "retry-force") {
          if (!(await confirmAction("Send the request again?", "We couldn't tell whether the provider accepted the first request. Check your provider dashboard first: if it did, sending again pays twice.", "Send again", "danger"))) return;
          await post("retry", { force: true });
        } else if (act === "resume") {
          await post("resume");
        } else if (act === "stop") {
          if (!(await confirmAction("Stop this project?", "It stops before sending anything new. Requests already sent keep running at the provider and may still be billed; Resume later collects them without paying twice.", "Stop"))) return;
          await post("stop");
          toast("Stopping after the current step check…", "info");
        } else if (act === "again") {
          b.closest("details")?.removeAttribute("open");
          const copy = await startCopy();
          if (!copy) return;
          toast("Started a new take", "good");
          location.hash = `#/projects/${copy.id}`;
          return;
        } else if (act === "edit") {
          editAsNew();
          return;
        } else if (act === "delete") {
          if (!(await confirmAction("Delete this project?", "Its files are removed from this computer. This can't be undone.", "Delete", "danger"))) return;
          await api(`/api/jobs/${id}`, { method: "DELETE" });
          toast("Deleted", "good");
          location.hash = "#/projects";
          return;
        }
        dirty = false;
        await refresh(true);
        refreshStatus();
      } catch (e) { toast(e.message, "bad"); }
    }));
    $$("[data-revoice]", page).forEach((b) => (b.onclick = async () => {
      const overrides = {};
      $$("[data-line]", page).forEach((t) => { const i = Number(t.dataset.line); if (t.value.trim() !== job.plan.lines[i].text.trim()) overrides[i] = { text: t.value.trim() }; });
      const i = Number(b.dataset.revoice);
      if (!overrides[i]) overrides[i] = { text: $(`[data-line="${i}"]`, page).value.trim() };
      try {
        await post("redo", { steps: Object.keys(overrides).map((k) => `voice-${k}`), overrides });
        toast(`Re-voicing ${Object.keys(overrides).length} line(s)`, "good");
        dirty = false;
        refresh(true);
      } catch (e) { toast(e.message, "bad"); }
    }));
    $$("[data-redo-shot]", page).forEach((b) => (b.onclick = async () => {
      const i = b.dataset.redoShot;
      const card = b.closest(".shot");
      const edits = { visual: $('[data-f="visual"]', card).value, narration: $('[data-f="narration"]', card).value, motion: $('[data-f="motion"]', card).value };
      try {
        await post("redo", { steps: [`key-${i}`], overrides: { [i]: edits } });
        toast(`Regenerating shot ${Number(i) + 1}`, "good");
        dirty = false;
        refresh(true);
      } catch (e) { toast(e.message, "bad"); }
    }));
  }

  let lastUpdated = "";
  async function refresh(force = false) {
    clearTimeout(timer);
    if (!document.body.contains(page) || location.hash.indexOf(id) < 0) return;
    try { await load(); } catch (e) { page.innerHTML = emptyState("alert", "Project not found", "It may have been deleted.", `<a class="btn" href="#/projects">Back to projects</a>`); return; }
    if (force || (job.updated !== lastUpdated && !dirty)) render();
    lastUpdated = job.updated;
    const busy = job.active || job.state === "running" || job.state === "queued";
    if (busy) timer = setTimeout(() => refresh(), 1800);
  }
  await refresh(true);
  return () => clearTimeout(timer);
}

// -- Assets ---------------------------------------------------------------------------------

export async function assets(page) {
  await refreshLibrary();
  const { avatars, voices } = state.library;
  page.innerHTML = `
    <div class="page-head"><div class="titles"><h1 class="page-title">Avatars &amp; voices</h1>
      <p class="page-sub">Save your face and voice once; every Presenter video and voiceover can use them. They stay in the <code>library/</code> folder on this computer and are only sent to a model provider when you generate.</p></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn" data-add="voice">${icon("mic")}Add voice</button><button class="btn primary" data-add="avatar">${icon("plus")}Add avatar</button></div></div>
    <div class="section-title" style="margin-top:4px"><h2 class="h2">Avatars</h2><span class="muted small">${avatars.length}</span></div>
    ${avatars.length ? `<div class="asset-grid">${avatars.map((a) => `<div class="asset"><div class="media" style="background-image:url('${a.thumb_url}')"><span class="badge plain">${a.kind === "video" ? `Video · ${Math.round(a.duration)} s` : "Photo"}</span></div>
        <div class="meta"><b title="${esc(a.name)}">${esc(a.name)}</b><a class="btn ghost sm icon-btn" href="#/create/presenter?avatar=${a.id}" title="Use in a presenter video" aria-label="Use ${esc(a.name)}">${icon("arrow")}</a><button class="btn ghost sm icon-btn danger" data-del="avatars/${a.id}" aria-label="Delete ${esc(a.name)}">${icon("trash")}</button></div></div>`).join("")}</div>`
      : emptyState("presenter", "No avatar yet", "A front-facing photo works. 10-20 s of video of you looking at the camera works best, and costs less.", `<button class="btn primary" data-add="avatar">${icon("plus")}Add avatar</button>`)}
    <div class="section-title"><h2 class="h2">Voices</h2><span class="muted small">${voices.length}</span></div>
    ${voices.length ? `<div class="grid" style="gap:10px">${voices.map((v) => `<div class="voice-row"><span class="vi">${icon("mic")}</span><div class="meta"><b>${esc(v.name)}</b><span class="muted small">${v.duration.toFixed(0)} s sample${v.transcript ? " · with transcript" : ""} · added ${timeAgo(v.created)}</span></div>
        <audio src="${v.url}" controls preload="none"></audio><button class="btn ghost sm icon-btn danger" data-del="voices/${v.id}" aria-label="Delete ${esc(v.name)}">${icon("trash")}</button></div>`).join("")}</div>`
      : emptyState("mic", "No voice yet", "Record 20 seconds reading a short text, in a quiet room. Your Presenter videos then speak in your voice.", `<button class="btn primary" data-add="voice">${icon("mic")}Record your voice</button>`)}
    <div class="notice info" style="margin-top:24px">${icon("shield")}<span>Use only your own face and voice, or someone's who agreed. Label AI-generated people when you post.</span></div>`;
  $$("[data-add]", page).forEach((b) => (b.onclick = async () => { const item = b.dataset.add === "avatar" ? await addAvatarDialog() : await addVoiceDialog(); if (item) assets(page); }));
  $$("[data-del]", page).forEach((b) => (b.onclick = async () => {
    if (!(await confirmAction("Delete this item?", "Projects that already used it keep their copy.", "Delete", "danger"))) return;
    await api(`/api/library/${b.dataset.del}`, { method: "DELETE" });
    await refreshStatus();
    assets(page);
  }));
}

// -- Settings -------------------------------------------------------------------------------

const KEYS = [
  ["FAL_KEY", "fal.ai", "Images, video, voices, talking avatars, lip-sync and swaps. Start here.", "https://fal.ai/dashboard/keys"],
  ["ANTHROPIC_API_KEY", "Anthropic (Claude)", "Writes your scripts and scores finished videos.", "https://platform.claude.com/settings/keys"],
  ["REPLICATE_API_TOKEN", "Replicate", "Alternative models, and Genjutsu prep (vocals, depth, SAM 3).", "https://replicate.com/account/api-tokens"],
  ["ENHANCOR_API_KEY", "Enhancor", "Seedance 2.5 character swap (Genjutsu engine). Needs cloudflared.", "https://app.enhancor.ai/api-dashboard"],
];

export async function settings(page, tab) {
  tab = tab || "keys";
  const tabs = [["keys", "API keys"], ["budget", "Budget & defaults"], ["models", "Models & prices"], ["skills", "Skills & tools"], ["appearance", "Appearance"]];
  page.innerHTML = `<div class="page-head"><div class="titles"><h1 class="page-title">Settings</h1><p class="page-sub">Keys stay in this folder's <code>.env</code>, readable only by you.</p></div></div>
    <nav class="tabs" aria-label="Settings sections">${tabs.map(([k, l]) => `<a href="#/settings/${k}" ${k === tab ? 'aria-current="page"' : ""}>${l}</a>`).join("")}</nav><div id="tabBody"></div>`;
  const body = $("#tabBody", page);
  const s = await api("/api/settings");

  if (tab === "keys") {
    body.innerHTML = `<div class="card pad">${KEYS.map(([k, name, text, url]) => `<div class="key-row"><div><b>${name}</b><div class="hint">${text} <a href="${url}" target="_blank" rel="noopener">Get a key${icon("ext")}</a></div></div>
        <div class="field"><div style="display:flex;gap:8px;align-items:center"><input class="input" type="password" autocomplete="off" data-key="${k}" placeholder="${s.keys[k] ? "•••••••••••• saved" : "Paste key"}" aria-label="${name} key">
        ${s.keys[k] ? `<span class="badge done">Saved</span>` : `<span class="badge plain">Not set</span>`}</div></div></div>`).join("")}
      <div style="display:flex;justify-content:flex-end;margin-top:12px"><button class="btn primary" id="saveKeys">${icon("check")}Save keys</button></div></div>
      <div class="notice info" style="margin-top:14px">${icon("info")}<span>A saved key isn't checked against the provider, and having one doesn't mean the account has credit. Nothing here spends money.</span></div>`;
    $("#saveKeys").onclick = async () => {
      const keys = {};
      $$("[data-key]", body).forEach((i) => { if (i.value.trim()) keys[i.dataset.key] = i.value.trim(); });
      if (!Object.keys(keys).length) { toast("Paste a key first.", "info"); return; }
      await api("/api/settings", { json: { keys } });
      await Promise.all([refreshStatus(), refreshModels()]);
      toast("Keys saved", "good");
      settings(page, "keys");
    };
  } else if (tab === "budget") {
    const v = s.settings;
    body.innerHTML = `<div class="card pad"><div class="grid cols-3">
        <div class="field"><label class="label" for="bDaily">Daily budget ($)</label><input class="input" id="bDaily" data-s="MW_DAILY_BUDGET" value="${esc(v.MW_DAILY_BUDGET)}" inputmode="decimal"><div class="hint">Nothing new starts once today's spend would pass this.</div></div>
        <div class="field"><label class="label" for="bJob">Max per project ($)</label><input class="input" id="bJob" data-s="MW_MAX_COST_PER_JOB" value="${esc(v.MW_MAX_COST_PER_JOB)}" inputmode="decimal"><div class="hint">A single project can't go over this.</div></div>
        <div class="field"><label class="label" for="bAsk">Ask me above ($)</label><input class="input" id="bAsk" data-s="MW_CONFIRM_ABOVE" value="${esc(v.MW_CONFIRM_ABOVE)}" inputmode="decimal"><div class="hint">Confirm before starting anything estimated at this or more.</div></div>
      </div>
      <div class="grid cols-2" style="margin-top:18px">
        <div class="field"><span class="label">Default quality tier</span><div class="seg">${["free", "budget", "standard", "premium"].map((t) => `<input type="radio" name="tierDef" id="td-${t}" value="${t}" ${v.MW_DEFAULT_TIER === t ? "checked" : ""}><label for="td-${t}">${t[0].toUpperCase() + t.slice(1)}</label>`).join("")}</div></div>
        <div class="field"><label class="label" for="bPar">Parallel generations</label><input class="input" id="bPar" data-s="MW_MAX_PARALLEL" value="${esc(v.MW_MAX_PARALLEL)}" inputmode="numeric"></div>
      </div>
      <div class="grid cols-2" style="margin-top:18px">
        <div class="field"><label class="label" for="bPl">Script writer (standard/premium)</label><input class="input" id="bPl" data-s="MW_PLANNER_MODEL" value="${esc(v.MW_PLANNER_MODEL)}"></div>
        <div class="field"><label class="label" for="bPlB">Script writer (free/budget)</label><input class="input" id="bPlB" data-s="MW_PLANNER_MODEL_BUDGET" value="${esc(v.MW_PLANNER_MODEL_BUDGET)}"></div>
      </div>
      <div style="display:flex;justify-content:flex-end;margin-top:16px"><button class="btn primary" id="saveBudget">${icon("check")}Save</button></div></div>`;
    $("#saveBudget").onclick = async () => {
      const settingsOut = { MW_DEFAULT_TIER: $('input[name="tierDef"]:checked', body).value };
      $$("[data-s]", body).forEach((i) => (settingsOut[i.dataset.s] = i.value.trim()));
      try { await api("/api/settings", { json: { settings: settingsOut } }); await refreshStatus(); toast("Saved", "good"); } catch (e) { toast(e.message, "bad"); }
    };
  } else if (tab === "models") {
    const kinds = [...new Set(state.models.map((m) => m.kind))];
    const draw = (kind) => `<div class="table-wrap"><table class="data"><thead><tr><th>Model</th><th>Kind</th><th>Tier</th><th>Price (est.)</th><th>Provider</th><th>Notes</th></tr></thead><tbody>${state.models.filter((m) => !kind || m.kinds.includes(kind)).map((m) => `<tr><td><b>${esc(m.name)}</b><div class="muted mono">${esc(m.id)}</div></td><td>${esc(m.kind.replace("_", " "))}</td><td>${esc(m.tier)}</td><td>${esc(m.price_label)}</td><td>${esc(m.provider)} ${m.available ? `<span class="badge done">ready</span>` : `<span class="badge plain">no key</span>`}</td><td class="muted">${esc(m.notes || "")}</td></tr>`).join("")}</tbody></table></div>`;
    body.innerHTML = `<div class="toolbar"><select class="select" style="width:auto" id="kindF" aria-label="Kind"><option value="">All kinds</option>${kinds.map((k) => `<option value="${k}">${k.replace("_", " ")}</option>`).join("")}</select><span class="muted small">Prices are estimates; override them in <code>models.local.json</code>.</span></div><div id="mt">${draw("")}</div>`;
    $("#kindF").onchange = (e) => ($("#mt").innerHTML = draw(e.target.value));
  } else if (tab === "skills") {
    const st = state.status;
    const g = st.skills.genjutsu;
    const row = (ok, title, text, cmd) => `<div class="check-item ${ok ? "done" : ""}"><span class="state">${icon("check")}</span><div class="txt"><b>${title}</b><span>${text}</span>${!ok && cmd ? `<div class="mono" style="margin-top:6px">${esc(cmd)}</div>` : ""}</div></div>`;
    body.innerHTML = `<div class="card pad"><div class="checklist">
      ${row(st.ffmpeg, "ffmpeg", "Edits every video on this computer.", "macOS: brew install ffmpeg · Ubuntu/WSL: sudo apt install ffmpeg")}
      ${row(st.skills.take_one, "Take One skill", "Studio-grade films directed by Claude Code: /take-one …", "bash scripts/install-skills.sh")}
      ${row(g.installed, "Genjutsu", "Depth + SAM 3 / face-mesh prep for character swaps.", "bash scripts/install-skills.sh")}
      ${row(g.environment && g.rubberband, "Genjutsu environment", "Python 3.12+ and Rubber Band for Genjutsu's prep.", "bash scripts/install-skills.sh --with-genjutsu-env")}
      ${row(st.enhancor_webhook || !st.providers.enhancor, "Enhancor callback", "Seedance needs a webhook: install cloudflared, or set ENHANCOR_WEBHOOK_URL.", "brew install cloudflared")}
    </div></div>`;
  } else if (tab === "appearance") {
    let current = "system";
    try { current = localStorage.getItem("mw-theme") || "system"; } catch (e) {}
    body.innerHTML = `<div class="card pad"><div class="field"><span class="label">Theme</span><div class="seg">${[["system", "System"], ["dark", "Dark"], ["light", "Light"]].map(([k, l]) => `<input type="radio" name="theme" id="th-${k}" value="${k}" ${k === current ? "checked" : ""}><label for="th-${k}">${icon(k === "light" ? "sun" : k === "dark" ? "moon" : "settings")}${l}</label>`).join("")}</div></div></div>`;
    $$('input[name="theme"]', body).forEach((r) => (r.onchange = () => {
      try { localStorage.setItem("mw-theme", r.value); } catch (e) {}
      if (r.value === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = r.value;
    }));
  }
}

export { STATE_LABEL };
