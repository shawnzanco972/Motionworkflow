// Form engine for the Create pages. A service is declared as data (sections of
// fields); this module renders it with the shared components, keeps a live cost
// estimate in the summary panel, and submits the job.

import { $, $$, api, badge, confirmSpend, draft, esc, icon, money, refreshStatus, state, toast } from "./core.js";
import { addAvatarDialog, addVoiceDialog } from "./modals.js";

const TIERS = [["free", "Free"], ["budget", "Budget"], ["standard", "Standard"], ["premium", "Premium"]];
const TEXT_TYPES = new Set(["textarea", "text", "number", "select", "range"]);

let uid = 0;
const fid = (name) => `f-${name}-${++uid}`;

// -- field renderers ---------------------------------------------------------------

function wrap(f, inner, id) {
  const label = f.label ? `<label class="label" ${id ? `for="${id}"` : ""}>${esc(f.label)}${f.optional ? ' <span class="opt">optional</span>' : ""}</label>` : "";
  return `<div class="field" data-field="${f.name || ""}">${label}${inner}${f.hint ? `<div class="hint">${f.hint}</div>` : ""}</div>`;
}

function modelOptions(kinds) {
  const rows = state.models.filter((m) => m.kinds.some((k) => kinds.includes(k)));
  return `<option value="">Auto: best for the tier</option>` + TIERS.map(([t, label]) => {
    const group = rows.filter((m) => m.tier === t);
    return group.length ? `<optgroup label="${label}">${group.map((m) =>
      `<option value="${m.id}" ${m.available ? "" : "disabled"}>${esc(m.name)} · ${m.price_label}${m.available ? "" : " (needs key)"}</option>`).join("")}</optgroup>` : "";
  }).join("");
}

function stockVoices() {
  const voices = [...new Set(state.models.filter((m) => m.kind === "tts" && m.voices).flatMap((m) => m.voices))];
  return `<option value="">Model default</option>` + voices.map((v) => `<option>${esc(v)}</option>`).join("");
}

const R = {
  textarea: (f) => { const id = fid(f.name); return wrap(f, `<textarea class="textarea ${f.big ? "big" : ""}" id="${id}" name="${f.name}" placeholder="${esc(f.placeholder || "")}" rows="${f.rows || 4}">${esc(f.default || "")}</textarea>`, id); },
  text: (f) => { const id = fid(f.name); return wrap(f, `<input class="input" id="${id}" name="${f.name}" value="${esc(f.default ?? "")}" placeholder="${esc(f.placeholder || "")}">`, id); },
  number: (f) => { const id = fid(f.name); return wrap(f, `<input class="input" type="number" id="${id}" name="${f.name}" value="${esc(f.default ?? "")}" min="${f.min ?? ""}" max="${f.max ?? ""}" step="${f.step ?? 1}" placeholder="${esc(f.placeholder || "")}">`, id); },
  select: (f) => { const id = fid(f.name); const opts = (typeof f.options === "function" ? f.options() : f.options).map(([v, l]) => `<option value="${esc(v)}" ${String(v) === String(f.default ?? "") ? "selected" : ""}>${esc(l)}</option>`).join(""); return wrap(f, `<select class="select" id="${id}" name="${f.name}">${opts}</select>`, id); },
  model: (f) => { const id = fid(f.name); return wrap({ ...f, hint: f.hint || "Leave on Auto to use the best model in your tier that you have a key for." }, `<select class="select" id="${id}" name="${f.name}" data-kinds="${f.kinds.join(",")}">${modelOptions(f.kinds)}</select>`, id); },
  stockvoice: (f) => { const id = fid(f.name); return wrap(f, `<select class="select" id="${id}" name="${f.name}">${stockVoices()}</select>`, id); },
  seg: (f) => wrap(f, `<div class="seg ${f.full ? "full" : ""}" role="radiogroup" aria-label="${esc(f.label || f.name)}">${f.options.map(([v, l, sub]) => { const id = fid(f.name); return `<input type="radio" id="${id}" name="${f.name}" value="${esc(v)}" ${String(v) === String(f.default) ? "checked" : ""}><label for="${id}">${esc(l)}${sub ? ` <small>${esc(sub)}</small>` : ""}</label>`; }).join("")}</div>`),
  choices: (f) => wrap(f, `<div class="choice-cards" role="radiogroup">${f.options.map(([v, title, sub]) => { const id = fid(f.name); return `<div class="choice"><input type="radio" id="${id}" name="${f.name}" value="${esc(v)}" ${v === f.default ? "checked" : ""}><label for="${id}"><b>${esc(title)}</b><span>${esc(sub || "")}</span></label></div>`; }).join("")}</div>`),
  switch: (f) => { const id = fid(f.name); return `<div class="field" data-field="${f.name}"><label class="switch" for="${id}"><input type="checkbox" id="${id}" name="${f.name}" ${f.default ? "checked" : ""}><span class="track"></span><span class="txt"><b>${esc(f.label)}</b>${f.hint ? `<span>${f.hint}</span>` : ""}</span></label></div>`; },
  switches: (f) => `<div class="switches">${f.items.map((x) => R.switch(x)).join("")}</div>`,
  range: (f) => { const id = fid(f.name); return wrap(f, `<div class="range-row"><input class="range" type="range" id="${id}" name="${f.name}" min="${f.min}" max="${f.max}" step="${f.step || 1}" value="${f.default}"><output for="${id}"></output></div>`, id); },
  chips: (f) => `<div class="chips" data-chips="${f.target}" aria-label="Examples">${f.options.map((o) => `<button type="button" class="chip">${esc(o)}</button>`).join("")}</div>`,
  file: (f) => { const id = fid(f.name); return wrap(f, `<div class="drop" data-drop="${f.name}"><input type="file" id="${id}" ${f.multiple ? "multiple" : ""} accept="${f.accept || ""}" aria-label="${esc(f.label || f.name)}"><div class="ico">${icon(f.icon || "upload")}</div><div><b>${esc(f.cta || "Drop a file or click to browse")}</b><span>${esc(f.types || "")}</span></div></div><div class="files" data-files="${f.name}"></div>`, null); },
  row: (f) => `<div class="row">${f.fields.map(render).join("")}</div>`,
  html: (f) => f.html,
  avatar: (f) => wrap(f, `<div class="picker" data-avatar-picker></div>`),
  voicepick: (f) => wrap(f, `<div class="voice-list" data-voice-picker></div>`),
};

function render(f) {
  const out = R[f.type](f);
  return f.show ? `<div data-show="${f.name || f.type}">${out}</div>` : out;
}

// -- pickers (avatars / voices from the library) ------------------------------------

function renderAvatarPicker(form, ctx) {
  const box = $("[data-avatar-picker]", form);
  if (!box) return;
  const current = ctx.values.avatar_id ?? form.dataset.avatar ?? (state.library.avatars[0]?.id || "");
  box.innerHTML = state.library.avatars.map((a) => {
    const id = fid("av");
    return `<div class="pick"><input type="radio" name="avatar_id" id="${id}" value="${a.id}" ${a.id === current ? "checked" : ""}>
      <label for="${id}"><span class="thumb" style="background-image:url('${a.thumb_url}')">${a.kind === "video" ? `<span class="badge plain">Video</span>` : ""}</span><span class="nm">${esc(a.name)}</span></label></div>`;
  }).join("") + `<div class="pick add"><label tabindex="0" role="button" data-add-avatar>${icon("plus", "lg")}<span>Add a photo<br>or video of you</span></label></div>`;
  const add = $("[data-add-avatar]", box);
  const open = async () => { const item = await addAvatarDialog(); if (item) { ctx.values.avatar_id = item.id; renderAvatarPicker(form, ctx); ctx.changed(); } };
  add.onclick = open;
  add.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } };
}

function renderVoicePicker(form, ctx) {
  const box = $("[data-voice-picker]", form);
  if (!box) return;
  const current = ctx.values.voice_id ?? (state.library.voices[0]?.id || "");
  const mine = state.library.voices.map((v) => {
    const id = fid("vo");
    return `<div class="voice-opt"><input type="radio" name="voice_id" id="${id}" value="${v.id}" ${v.id === current ? "checked" : ""}>
      <label for="${id}"><span class="vi">${icon("mic")}</span><span class="meta"><b>${esc(v.name)}</b><span>Your voice · ${v.duration.toFixed(0)} s sample · cloned</span></span>
      <button type="button" class="btn ghost sm" data-play="${v.url}" aria-label="Play ${esc(v.name)}">${icon("play")}</button></label></div>`;
  }).join("");
  const sid = fid("vo");
  box.innerHTML = mine + `<div class="voice-opt"><input type="radio" name="voice_id" id="${sid}" value="" ${current === "" ? "checked" : ""}>
      <label for="${sid}"><span class="vi">${icon("wave")}</span><span class="meta"><b>Stock voice</b><span>A ready-made AI voice</span></span>
      <select class="select" name="voice" style="width:auto" aria-label="Stock voice">${stockVoices()}</select></label></div>
    <button type="button" class="btn sm" data-add-voice style="justify-self:start">${icon("plus")}Record or upload your voice</button>`;
  $("[data-add-voice]", box).onclick = async () => { const item = await addVoiceDialog(); if (item) { ctx.values.voice_id = item.id; renderVoicePicker(form, ctx); ctx.changed(); } };
  let audio;
  $$("[data-play]", box).forEach((b) => (b.onclick = (e) => { e.preventDefault(); audio?.pause(); audio = new Audio(b.dataset.play); audio.play(); }));
}

// -- file drop zones ------------------------------------------------------------------

function bindDrop(form, ctx, name) {
  const zone = $(`[data-drop="${name}"]`, form);
  const input = $("input", zone);
  const list = $(`[data-files="${name}"]`, form);
  const draw = () => {
    const files = ctx.files[name] || [];
    list.innerHTML = files.map((f, i) => {
      const url = URL.createObjectURL(f);
      const media = f.type.startsWith("image/") ? `<img src="${url}" alt="">` : f.type.startsWith("video/") ? `<video src="${url}" muted></video>` : `<span class="ico">${icon(f.type.startsWith("audio/") ? "wave" : "upload")}</span>`;
      return `<span class="file-pill">${media}<span class="name">${esc(f.name)}</span><button type="button" data-rm="${i}" aria-label="Remove ${esc(f.name)}">${icon("x")}</button></span>`;
    }).join("");
    $$("[data-rm]", list).forEach((b) => (b.onclick = () => { ctx.files[name].splice(Number(b.dataset.rm), 1); draw(); ctx.changed(); }));
  };
  const take = (fileList) => {
    const incoming = [...fileList];
    ctx.files[name] = input.multiple ? [...(ctx.files[name] || []), ...incoming] : incoming.slice(0, 1);
    draw();
    ctx.changed();
  };
  input.onchange = () => { take(input.files); input.value = ""; };
  zone.ondragover = (e) => { e.preventDefault(); zone.classList.add("over"); };
  zone.ondragleave = () => zone.classList.remove("over");
  zone.ondrop = (e) => { e.preventDefault(); zone.classList.remove("over"); take(e.dataTransfer.files); };
}

// -- reading the form ---------------------------------------------------------------------

function collect(form, ctx, svc) {
  const values = {};
  for (const el of form.elements) {
    if (!el.name || el.type === "file") continue;
    if (el.closest("[data-hidden]")) continue;
    if (el.type === "radio") { if (el.checked) values[el.name] = el.value; continue; }
    if (el.type === "checkbox") { values[el.name] = el.checked; continue; }
    if (el.value === "") continue;
    values[el.name] = el.type === "number" || el.type === "range" ? Number(el.value) : el.value;
  }
  const params = svc.toParams ? svc.toParams(values, ctx) : values;
  const counts = {};
  for (const [k, list] of Object.entries(ctx.files)) if (list?.length) counts[k] = list.length;
  Object.assign(counts, svc.counts ? svc.counts(values, ctx) : {});
  return { values, params, counts };
}

// -- the page ----------------------------------------------------------------------------------

export function renderCreatePage(page, svc) {
  const ctx = { files: {}, values: {}, quote: null, changed: () => {} };
  const saved = draft.load(svc.id);
  const sections = svc.sections.map((s, i) => {
    const body = s.fields.map(render).join("");
    if (s.advanced) {
      return `<div class="section"><details class="more"><summary>${icon("chev")}${esc(s.title)}</summary><div class="inner">${body}</div></details></div>`;
    }
    return `<div class="section"><div class="section-head"><span class="step-num">${i + 1}</span><div><h2>${esc(s.title)}</h2>${s.desc ? `<p>${s.desc}</p>` : ""}</div></div><div class="section-body">${body}</div></div>`;
  }).join("");
  const tierId = (t) => `tier-${svc.id}-${t}`;
  const defTier = state.status?.default_tier || "budget";

  page.innerHTML = `
    <div class="page-head"><div class="titles">
      <div class="eyebrow">${icon(svc.icon)}${esc(svc.eyebrow)}</div>
      <h1 class="page-title">${esc(svc.title)}</h1>
      <p class="page-sub">${svc.intro}</p></div>
      ${svc.headAction || ""}
    </div>
    ${svc.steps ? `<div class="flow" aria-label="How it works">${svc.steps.map(([t, gate], i) => `${i ? icon("chev") : ""}<span class="flow-step ${gate ? "gate" : ""}"><span class="n">${gate ? icon("check") : i + 1}</span>${esc(t)}</span>`).join("")}</div>` : ""}
    <form class="create" novalidate>
      <div class="card">${sections}</div>
      <aside class="summary" aria-label="Cost summary"><div class="card">
        <div class="summary-head">
          <div class="label" style="margin-bottom:8px">Quality and price</div>
          <div class="seg full" role="radiogroup" aria-label="Tier">${TIERS.map(([t, l]) => `<input type="radio" name="tier" id="${tierId(t)}" value="${t}" ${t === defTier ? "checked" : ""}><label for="${tierId(t)}">${l}</label>`).join("")}</div>
        </div>
        <div class="summary-head" style="padding-top:14px">
          <div class="muted small">Estimated cost</div>
          <div class="price" data-price>…</div>
        </div>
        <ul class="lines" data-lines></ul>
        <div class="summary-body">
          <div data-notices style="display:grid;gap:8px"></div>
          ${svc.gate ? `<div class="notice good">${icon("shield")}<span>${svc.gate}</span></div>` : ""}
          <button class="btn primary lg block cta" type="submit">${icon("spark")}${esc(svc.cta)}</button>
          <p class="hint" style="margin:0">${svc.youGet || ""}</p>
        </div>
      </div></aside>
      <div class="mobile-cta"><div class="p"><b data-price-m>…</b><span>estimated</span></div><button class="btn primary" type="submit">${esc(svc.ctaShort || svc.cta)}</button></div>
    </form>`;

  const form = $("form", page);
  // Restore typed drafts.
  for (const [k, v] of Object.entries(saved)) {
    const el = form.elements[k];
    if (el && !(el instanceof RadioNodeList) && TEXT_TYPES.has(el.tagName === "TEXTAREA" ? "textarea" : el.tagName === "SELECT" ? "select" : el.type) && v !== "") el.value = v;
  }
  for (const s of svc.sections) for (const f of flat(s.fields)) if (f.type === "file") bindDrop(form, ctx, f.name);
  $$("[data-chips]", form).forEach((box) => $$(".chip", box).forEach((c) => (c.onclick = () => {
    const t = form.elements[box.dataset.chips]; t.value = c.textContent; t.dispatchEvent(new Event("input", { bubbles: true })); t.focus();
  })));
  $$('input[type="range"]', form).forEach((r) => {
    const f = flat(svc.sections.flatMap((s) => s.fields)).find((x) => x.name === r.name);
    const out = r.parentElement.querySelector("output");
    const show = () => (out.textContent = f?.format ? f.format(Number(r.value)) : r.value);
    r.addEventListener("input", show); show();
  });

  let timer;
  const showHide = (values) => {
    for (const f of flat(svc.sections.flatMap((s) => s.fields))) {
      if (!f.show) continue;
      const el = $(`[data-show="${f.name || f.type}"]`, form);
      if (!el) continue;
      const visible = f.show(values, ctx);
      el.hidden = !visible;
      el.toggleAttribute("data-hidden", !visible);
    }
  };
  ctx.changed = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const { values, params, counts } = collect(form, ctx, svc);
      ctx.values = { ...ctx.values, ...values };
      showHide(values);
      const keep = {};
      for (const [k, v] of Object.entries(values)) if (typeof v === "string" && k !== "tier") keep[k] = v;
      draft.save(svc.id, keep);
      try {
        ctx.quote = await api("/api/estimate", { json: { workflow: svc.workflow, params, counts } });
        drawQuote(form, ctx.quote, svc, values, ctx);
      } catch (e) {
        $("[data-price]", form).textContent = "–";
        $("[data-price-m]", form).textContent = "–";
        $("[data-lines]", form).innerHTML = "";
        $("[data-notices]", form).innerHTML = `<div class="notice bad">${icon("alert")}<span>${esc(e.message)}</span></div>`;
      }
    }, 250);
  };
  form.addEventListener("input", ctx.changed);
  form.addEventListener("change", ctx.changed);
  form.addEventListener("submit", (e) => { e.preventDefault(); submit(form, ctx, svc); });
  renderAvatarPicker(form, ctx);
  renderVoicePicker(form, ctx);
  showHide(collect(form, ctx, svc).values);
  ctx.changed();
  svc.after?.(form, ctx);
  return { form, ctx, rerenderPickers: () => { renderAvatarPicker(form, ctx); renderVoicePicker(form, ctx); } };
}

function flat(fields) {
  return fields.flatMap((f) => (f.type === "row" ? flat(f.fields) : f.type === "switches" ? f.items : [f]));
}

function drawQuote(form, q, svc, values, ctx) {
  $("[data-price]", form).innerHTML = `${money(q.total)} <small>est.</small>`;
  $("[data-price-m]", form).textContent = money(q.total);
  $("[data-lines]", form).innerHTML = q.items.map((i) => `<li><div class="what"><b>${esc(i.label)}</b><span>${esc(i.model_name)}${i.mock ? " · offline mock" : ""}</span></div><div class="usd">${money(i.usd)}</div></li>`).join("");
  const notes = [];
  if (q.mock) notes.push(`<div class="notice warn">${icon("key")}<span>Some steps will make placeholder media because no API key covers them yet. <a href="#/settings">Add a key</a>.</span></div>`);
  if (q.total > q.budget.max_cost_per_job) notes.push(`<div class="notice bad">${icon("alert")}<span>Over your per-job limit of ${money(q.budget.max_cost_per_job)}. Shorten it, pick a cheaper tier, or raise the limit in <a href="#/settings/budget">Settings</a>.</span></div>`);
  else if (q.budget.spent_today + q.total > q.budget.daily_budget) notes.push(`<div class="notice bad">${icon("alert")}<span>This would pass today's budget (${money(q.budget.spent_today)} of ${money(q.budget.daily_budget)} used).</span></div>`);
  const extra = svc.notices?.(values, ctx) || [];
  $("[data-notices]", form).innerHTML = notes.concat(extra).join("");
}

async function submit(form, ctx, svc, confirmed = false) {
  const { params } = collect(form, ctx, svc);
  if (svc.validate) {
    const problem = svc.validate(params, ctx);
    if (problem) { toast(problem, "bad"); return; }
  }
  const fd = new FormData();
  fd.append("workflow", svc.workflow);
  fd.append("params", JSON.stringify(params));
  fd.append("confirm", confirmed ? "true" : "false");
  for (const [k, list] of Object.entries(ctx.files)) (list || []).forEach((f) => fd.append(k, f));
  const buttons = $$('button[type="submit"]', form);
  buttons.forEach((b) => (b.disabled = true));
  try {
    const job = await api("/api/jobs", { method: "POST", body: fd });
    toast("Started. You can follow it here.", "good");
    location.hash = `#/projects/${job.id}`;
    refreshStatus();
  } catch (e) {
    if (e.status === 402 && e.data?.needs_confirmation) {
      if (await confirmSpend(e.data.quote)) return submit(form, ctx, svc, true);
    } else toast(e.message, "bad", 7000);
  } finally {
    buttons.forEach((b) => (b.disabled = false));
  }
}

export { badge };
