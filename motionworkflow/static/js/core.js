// Core helpers shared by every page: API calls, app state, icons, toasts, dialogs.

export const $ = (sel, el = document) => el.querySelector(sel);
export const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const icon = (name, cls = "") => `<svg class="icon ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;

export function money(v) {
  const n = Number(v) || 0;
  if (n === 0) return "$0.00";
  return "$" + n.toFixed(n < 0.1 ? 3 : 2);
}

export function timeAgo(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)} d ago`;
  return new Date(iso).toLocaleDateString();
}

export async function api(path, opts = {}) {
  const init = { ...opts };
  if (opts.json !== undefined) {
    init.method = opts.method || "POST";
    init.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    init.body = JSON.stringify(opts.json);
    delete init.json;
  }
  const res = await fetch(path, init);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : res.statusText;
    const err = new Error(detail);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

// Shared state, refreshed on demand.
export const state = { status: null, models: [], library: { avatars: [], voices: [] } };
const listeners = new Set();
export const onState = (fn) => (listeners.add(fn), () => listeners.delete(fn));
const emit = () => listeners.forEach((fn) => fn(state));

export async function refreshStatus() {
  state.status = await api("/api/status");
  emit();
  return state.status;
}
export async function refreshModels() {
  state.models = await api("/api/models");
  emit();
  return state.models;
}
export async function refreshLibrary() {
  state.library = await api("/api/library");
  emit();
  return state.library;
}

export const WORKFLOWS = {
  presenter: { label: "Presenter", icon: "presenter", color: "c1" },
  short: { label: "Short", icon: "film", color: "c2" },
  image: { label: "Image", icon: "image", color: "c3" },
  video: { label: "Video", icon: "video", color: "c4" },
  voice: { label: "Voiceover", icon: "wave", color: "c5" },
  swap: { label: "Swap", icon: "swap", color: "c6" },
};

export const STATE_LABEL = { done: "Done", error: "Failed", awaiting_approval: "Needs approval", running: "Working", queued: "Queued", stopped: "Stopped" };
export const badge = (st) => `<span class="badge ${esc(st)}">${esc(STATE_LABEL[st] || st)}</span>`;

// Toasts ------------------------------------------------------------------------
export function toast(message, kind = "info", ms = 4200, action = null) {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = `${icon(kind === "good" ? "check" : kind === "bad" ? "alert" : kind === "warn" ? "alert" : "info")}<span>${esc(message)}</span>${action ? `<a class="btn sm" href="${esc(action.href)}">${esc(action.label)}</a>` : ""}`;
  $("#toasts").appendChild(el);
  const t = setTimeout(() => el.remove(), ms);
  el.querySelector("a")?.addEventListener("click", () => { clearTimeout(t); el.remove(); });
}

// Dialogs ------------------------------------------------------------------------
export function openDialog({ title, body, actions = [], iconName = null, onOpen = null, wide = false }) {
  const d = $("#dialog");
  d.style.width = wide ? "min(640px, calc(100% - 32px))" : "";
  d.innerHTML = `<form method="dialog">
    <div class="dlg-head">${iconName ? icon(iconName, "lg") : ""}<h2>${esc(title)}</h2>
      <button class="btn ghost icon-btn" value="__close" type="button" data-close aria-label="Close">${icon("x")}</button></div>
    <div class="dlg-body">${body}</div>
    <div class="dlg-foot">${actions.map((a, i) => `<button class="btn ${a.kind || ""}" value="${i}" ${a.type ? `type="${a.type}"` : ""} ${a.id ? `id="${a.id}"` : ""}>${a.label}</button>`).join("")}</div>
  </form>`;
  return new Promise((resolve) => {
    d.onclose = () => resolve(d.returnValue === "__close" || d.returnValue === "" ? null : Number(d.returnValue));
    d.querySelector("[data-close]").onclick = () => d.close("__close");
    d.querySelector("form").addEventListener("submit", (e) => { if (!e.submitter) e.preventDefault(); });
    d.returnValue = "";
    d.showModal();
    onOpen?.(d);
  });
}

export async function confirmSpend(quote, intro = "") {
  const items = (quote.items || []).map((i) => `<li><div class="what"><b>${esc(i.label)}</b><span>${esc(i.model_name)}${i.mock ? " · offline mock" : ""}</span></div><div class="usd">${money(i.usd)}</div></li>`).join("");
  const choice = await openDialog({
    title: "Confirm the spend",
    iconName: "wallet",
    body: `${intro ? `<p class="muted" style="margin:0">${esc(intro)}</p>` : ""}
      <div class="price">${money(quote.total)} <small>estimated</small></div>
      <ul class="lines" style="padding:0">${items}</ul>
      <div class="notice info">${icon("info")}<span>Estimates come from catalog prices; your provider's bill is the source of truth. Paid requests are never retried automatically.</span></div>`,
    actions: [{ label: "Cancel", kind: "ghost" }, { label: "Spend it", kind: "primary" }],
  });
  return choice === 1;
}

export async function confirmAction(title, text, label = "Continue", kind = "primary") {
  const choice = await openDialog({ title, body: `<p style="margin:0" class="muted">${esc(text)}</p>`, actions: [{ label: "Cancel", kind: "ghost" }, { label, kind }] });
  return choice === 1;
}

// Persist small per-page drafts (text the user typed) ------------------------------
export const draft = {
  load(key) { try { return JSON.parse(localStorage.getItem("mw-draft-" + key) || "{}"); } catch (e) { return {}; } },
  save(key, value) { try { localStorage.setItem("mw-draft-" + key, JSON.stringify(value)); } catch (e) {} },
  clear(key) { try { localStorage.removeItem("mw-draft-" + key); } catch (e) {} },
};
