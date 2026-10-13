// Spending: where the money went, by day, by service and by model, plus every charge.

import { $, $$, api, esc, icon, money, state, timeAgo, WORKFLOWS } from "./core.js";

const RANGES = [[14, "14 days"], [30, "30 days"], [90, "90 days"]];
const STEP_GROUP = {
  image: "Images", key: "Keyframe", voice: "Voice", clip: "Animated shot", face: "Avatar animation",
  broll: "Cutaway image", draft: "Draft", final: "Final render", review: "Fresh-eyes review", prep: "Genjutsu prep",
};

const modelName = (id) => state.models.find((m) => m.id === id)?.name || (id === "claude:review" ? "Claude reviewer" : id || "–");
function stepLabel(note) {
  const [key, why] = String(note || "").split(":").map((x) => x.trim());
  const m = key.match(/^(.*)-(\d+)$/);
  const base = m ? `${STEP_GROUP[m[1]] || m[1]} ${Number(m[2]) + 1}` : STEP_GROUP[key] || key || "Charge";
  return why ? `${base} · refund` : base;
}
const day = (iso, opts = { month: "short", day: "numeric" }) => new Date(iso + "T00:00:00Z").toLocaleDateString(undefined, { ...opts, timeZone: "UTC" });

// A round axis maximum: 0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10 …
function niceMax(v) {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 2, 2.5, 5, 10]) if (v <= m * p) return m * p;
  return 10 * p;
}

function chart(el, days) {
  const width = Math.max(280, el.clientWidth);
  const height = 220;
  const pad = { l: 46, r: 8, t: 12, b: 28 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;
  const max = niceMax(Math.max(...days.map((d) => d.usd), 0));
  const band = w / days.length;
  const bar = Math.max(3, Math.min(28, band * 0.64));
  const y = (v) => pad.t + h - (Math.max(0, v) / max) * h;
  const ticks = [0, max / 2, max];
  const every = Math.ceil(days.length / Math.max(2, Math.floor(w / 64)));
  const total = days.reduce((a, d) => a + d.usd, 0);
  const peak = days.reduce((a, d) => (d.usd > a.usd ? d : a), days[0]);
  const bars = days.map((d, i) => {
    const x = pad.l + i * band + (band - bar) / 2;
    const top = y(d.usd);
    const bh = pad.t + h - top;
    const r = Math.min(4, bar / 2, bh);
    // Rounded at the data end (top), square on the baseline.
    const path = bh > 0.5
      ? `M${x},${pad.t + h}V${top + r}Q${x},${top} ${x + r},${top}H${x + bar - r}Q${x + bar},${top} ${x + bar},${top + r}V${pad.t + h}Z`
      : "";
    return `<g class="bar" data-i="${i}">${path ? `<path d="${path}"/>` : ""}<rect class="hit" x="${pad.l + i * band}" y="${pad.t}" width="${band}" height="${h + 4}"/></g>`;
  }).join("");
  el.innerHTML = `<svg width="${width}" height="${height}" role="img" aria-label="Spend per day for the last ${days.length} days: ${money(total)} in total, highest ${money(peak.usd)} on ${day(peak.date)}.">
    ${ticks.map((t) => `<line class="grid" x1="${pad.l}" x2="${width - pad.r}" y1="${y(t)}" y2="${y(t)}"/><text class="axis" x="${pad.l - 8}" y="${y(t) + 4}" text-anchor="end">${t === 0 ? "$0" : money(t)}</text>`).join("")}
    ${days.map((d, i) => (i % every === 0 || i === days.length - 1) && !(i !== days.length - 1 && days.length - 1 - i < every / 2)
      ? `<text class="axis" x="${pad.l + i * band + band / 2}" y="${height - 8}" text-anchor="middle">${i === days.length - 1 ? "Today" : day(d.date)}</text>` : "").join("")}
    ${bars}</svg><div class="chart-tip" role="status" hidden></div>`;
  const tip = $(".chart-tip", el);
  $$(".bar", el).forEach((g) => {
    const show = () => {
      const d = days[Number(g.dataset.i)];
      $$(".bar.on", el).forEach((b) => b.classList.remove("on"));
      g.classList.add("on");
      tip.innerHTML = `<b>${money(d.usd)}</b><span>${day(d.date, { weekday: "short", month: "short", day: "numeric" })} · ${d.count || 0} charge${d.count === 1 ? "" : "s"}</span>`;
      tip.hidden = false;
      const x = pad.l + Number(g.dataset.i) * band + band / 2;
      tip.style.left = `${Math.min(width - 90, Math.max(90, x))}px`;
      tip.style.top = `${Math.max(0, y(d.usd) - 52)}px`;
    };
    g.addEventListener("mouseenter", show);
    g.addEventListener("click", show);
  });
  el.onmouseleave = () => { tip.hidden = true; $$(".bar.on", el).forEach((b) => b.classList.remove("on")); };
}

function table(days) {
  return `<div class="table-wrap"><table class="data"><thead><tr><th>Day</th><th class="num">Charges</th><th class="num">Spent</th></tr></thead><tbody>
    ${[...days].reverse().map((d) => `<tr><td>${day(d.date, { weekday: "short", month: "short", day: "numeric" })}</td><td class="num">${d.count || 0}</td><td class="num">${money(d.usd)}</td></tr>`).join("")}</tbody></table></div>`;
}

const TIER_LABEL = { free: "Cheapest", budget: "Budget", standard: "Standard", premium: "Premium" };

function priceGuide(g) {
  const cell = (p) => {
    if (!p) return `<td class="num muted">–</td>`;
    const models = esc(p.models.filter((m) => m !== "Claude").join(" + "));
    if (p.same_as_cheaper) return `<td class="num muted" title="Same models as the cheaper tier: ${models}">same</td>`;
    return `<td class="num ${p.over_cap ? "over-cap" : ""}" title="${models}">${p.usd === 0 ? "Free" : "~" + money(p.usd)}${p.over_cap ? `<span class="sr-only"> (over your per-project limit)</span>${icon("alert")}` : ""}</td>`;
  };
  return `<div class="section-title" id="guide" style="margin-top:30px"><h2 class="h2">Price guide</h2><span class="muted small">what typical projects cost, by quality tier</span></div>
    <div class="table-wrap"><table class="data guide"><thead><tr><th>Project</th>${g.tiers.map((t) => `<th class="num">${TIER_LABEL[t] || t}</th>`).join("")}</tr></thead><tbody>
    ${g.rows.map((r) => `<tr><td><b>${esc(r.title)}</b><div class="muted small">${esc(r.detail)}</div></td>${g.tiers.map((t) => cell(r.prices[t])).join("")}</tr>`).join("")}
    </tbody></table></div>
    <p class="muted small" style="margin:8px 0 0">Priced with every provider key set; without a key a tier falls back to a cheaper or free model. “Cheapest” uses free models where they exist. Hover a price to see the models. ${icon("alert")} marks a project over your per-project limit (${money(g.max_cost_per_job)}): <a href="#/settings/budget">change it</a> or pick a cheaper tier.</p>`;
}

export async function spending(page, query) {
  const days = Math.max(7, Math.min(90, Math.round(Number(query.get("days")) || 14)));  // the server's range
  const view = query.get("view") === "table" ? "table" : "chart";
  const [s, guide] = await Promise.all([api(`/api/spend?days=${days}`), api("/api/pricing").catch(() => null)]);
  const lim = s.limits;
  const pctToday = Math.min(100, (s.today / Math.max(0.01, lim.daily_budget)) * 100);
  const maxWf = Math.max(0.0001, ...s.by_workflow.map((x) => x.usd));
  const link = (v, d) => `#/spending?days=${d ?? days}${(v ?? view) === "table" ? "&view=table" : ""}`;
  const empty = !s.recent.length;
  const topWf = s.by_workflow.find((x) => WORKFLOWS[x.workflow]);

  page.innerHTML = `
    <div class="page-head"><div class="titles"><h1 class="page-title">Spending</h1>
      <p class="page-sub">What every paid request was estimated to cost, logged the moment it was sent. Refunds appear when a provider rejects a request.</p></div>
      <a class="btn" href="#/settings/budget">${icon("settings")}Budget limits</a></div>

    <div class="stats">
      <div class="card stat"><div class="k">Today</div><div class="v">${money(s.today)}</div>
        <div class="meter-bar ${pctToday >= 100 ? "over" : ""}" style="margin:8px 0 4px" role="img" aria-label="${Math.round(pctToday)}% of today's budget"><i style="width:${pctToday}%"></i></div>
        <div class="muted small">of ${money(lim.daily_budget)} daily budget</div></div>
      <div class="card stat"><div class="k">Last 7 days</div><div class="v">${money(s.week)}</div><div class="muted small">${money(s.week / 7)} a day on average</div></div>
      <div class="card stat"><div class="k">Last 30 days</div><div class="v">${money(s.month)}</div><div class="muted small">${topWf ? `Most on ${esc(WORKFLOWS[topWf.workflow].label)}` : "Nothing yet"}</div></div>
      <div class="card stat"><div class="k">All time</div><div class="v">${money(s.all_time)}</div><div class="muted small">${s.charges} charge${s.charges === 1 ? "" : "s"}</div></div>
    </div>

    ${empty ? `<div class="empty" style="margin-top:20px">${icon("wallet")}<b>Nothing spent yet</b><div>Free and offline (mock) models cost $0. Paid requests show up here the moment they're sent, with the project they belong to.</div><div style="margin-top:16px"><a class="btn primary" href="#/create/image">${icon("plus")}Make something</a></div></div>` : `
    <div class="card pad" style="margin-top:20px">
      <div class="toolbar" style="margin-bottom:6px"><h2 class="h2" style="margin:0">Per day</h2><div class="spacer" style="flex:1"></div>
        <div class="chips" aria-label="Range">${RANGES.map(([d, l]) => `<a class="chip ${d === days ? "active" : ""}" href="${link(null, d)}" ${d === days ? 'aria-current="true"' : ""}>${l}</a>`).join("")}</div>
        <div class="chips" aria-label="View">${[["chart", "Chart"], ["table", "Table"]].map(([v, l]) => `<a class="chip ${v === view ? "active" : ""}" href="${link(v)}" ${v === view ? 'aria-current="true"' : ""}>${l}</a>`).join("")}</div></div>
      <div class="muted small" style="margin-bottom:8px">${money(s.by_day.reduce((a, d) => a + d.usd, 0))} in the last ${days} days · days run on UTC, like the daily budget</div>
      <div id="dayChart" class="chart">${view === "table" ? table(s.by_day) : ""}</div>
    </div>

    <div class="grid cols-2" style="margin-top:20px;gap:20px">
      <div class="card pad"><h2 class="h2" style="margin:0 0 12px">By service</h2>
        ${s.by_workflow.length ? `<div class="hbars">${s.by_workflow.map((x) => { const w = WORKFLOWS[x.workflow]; return `<div class="hbar"><span class="lbl">${icon(w?.icon || "trash")}${esc(w?.label || "Deleted projects")}</span><span class="track"><i style="width:${Math.max(1.5, (x.usd / maxWf) * 100)}%"></i></span><b>${money(x.usd)}</b></div>`; }).join("")}</div>` : `<p class="muted">Nothing yet.</p>`}</div>
      <div class="card pad"><h2 class="h2" style="margin:0 0 12px">By model</h2>
        <table class="cost-steps"><thead><tr><th>Model</th><th class="num">Share</th><th class="num">Spent</th></tr></thead><tbody>
        ${s.by_model.slice(0, 8).map((m) => `<tr><td>${esc(modelName(m.model))}<div class="muted small mono">${esc(m.model)}</div></td><td class="num muted">${s.all_time > 0 ? Math.round((m.usd / s.all_time) * 100) + "%" : "–"}</td><td class="num">${money(m.usd)}</td></tr>`).join("")}</tbody></table></div>
    </div>

    <div class="section-title" style="margin-top:26px"><h2 class="h2">Recent charges</h2><span class="muted small">newest first</span></div>
    <div class="table-wrap"><table class="data"><thead><tr><th>When</th><th>Project</th><th>Step</th><th class="hide-sm">Model</th><th class="num">Amount</th></tr></thead><tbody>
      ${s.recent.slice(0, 40).map((r) => `<tr><td class="nowrap" title="${esc(r.at)}">${timeAgo(r.at)}</td>
        <td>${r.workflow ? `<a href="#/projects/${esc(r.job)}">${esc(r.title)}</a>` : `<span class="muted">${esc(r.title)}</span>`}</td>
        <td>${esc(stepLabel(r.note))}</td><td class="muted hide-sm">${esc(modelName(r.model))}</td>
        <td class="num ${r.usd < 0 ? "refund" : ""}">${r.usd < 0 ? "−" + money(-r.usd) : money(r.usd)}</td></tr>`).join("")}</tbody></table></div>
    ${s.recent.length > 40 ? `<p class="muted small">Showing the latest 40. The full ledger is <code>runs/ledger.jsonl</code>, or run <code>mw spend</code>.</p>` : ""}`}

    ${guide ? priceGuide(guide) : ""}

    <div class="notice info" style="margin-top:22px">${icon("info")}<span>These are estimates from catalog prices (Settings → Models &amp; prices). Your provider's dashboard is the source of truth for what you were billed.</span></div>`;

  if (query.get("guide")) $("#guide")?.scrollIntoView({ block: "start" });
  if (!empty && view === "chart") {
    const el = $("#dayChart");
    chart(el, s.by_day);
    const onResize = () => { if (document.body.contains(el)) chart(el, s.by_day); };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }
}
