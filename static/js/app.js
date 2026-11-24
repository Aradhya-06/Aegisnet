/* AegisNet shared front-end helpers (no framework). */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function csrfToken() { return document.querySelector('meta[name="csrf-token"]').content; }

/* fetch wrapper: opts.form (object|FormData) or opts.json -> POST; throws Error(message) on failure */
async function api(url, opts = {}) {
  const init = { method: opts.method || "GET", headers: { "X-CSRFToken": csrfToken() } };
  if (opts.form) {
    init.method = "POST";
    init.body = opts.form instanceof FormData ? opts.form : new URLSearchParams(opts.form);
  } else if (opts.json) {
    init.method = "POST";
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.json);
  } else if (opts.post) {
    init.method = "POST";
  }
  let res, data;
  try { res = await fetch(url, init); } catch (e) { throw new Error("network error: " + e.message); }
  try { data = await res.json(); } catch (e) { data = { error: "server error (" + res.status + ")" }; }
  if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
  return data;
}

function fmtBytes(n) {
  if (n === null || n === undefined) return "—";
  const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0, v = Number(n);
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return (i === 0 ? v.toFixed(0) : v.toFixed(2)) + " " + u[i];
}
function fmtRate(bps) {
  if (bps === null || bps === undefined) return "—";
  const u = ["bit/s", "Kbit/s", "Mbit/s", "Gbit/s"]; let i = 0, v = Number(bps);
  while (v >= 1000 && i < u.length - 1) { v /= 1000; i++; }
  return v.toFixed(i === 0 ? 0 : 2) + " " + u[i];
}
function fmtNum(n, d = 2, unit = "") {
  return (n === null || n === undefined || Number.isNaN(n)) ? "—" : Number(n).toFixed(d) + unit;
}
function pill(text, cls) { return `<span class="pill pill-${esc(cls || text)}">${esc(text)}</span>`; }
function statusPill(s) { return pill(s, s === "degraded" ? "degraded-link" : s); }
function pathHtml(p) { return (p && p.length) ? p.map(esc).join('<span class="path-arrow">›</span>') : "—"; }

function stepsHtml(steps) {
  if (!steps || !steps.length) return '<div class="empty">no steps recorded</div>';
  return '<ul class="steps">' + steps.map(s => `<li><span class="t">${esc(s.t_ms)} ms</span>${esc(s.text)}</li>`).join("") + "</ul>";
}

function setBusy(btn, busy, label) {
  if (!btn) return;
  if (busy) { btn.dataset.label = btn.innerHTML; btn.disabled = true; btn.innerHTML = `<span class="spinner-inline"></span> ${label || "Working…"}`; }
  else { btn.disabled = false; if (btn.dataset.label) btn.innerHTML = btn.dataset.label; }
}

function toast(message, kind = "info") {
  let box = $("#toasts");
  if (!box) { box = document.createElement("div"); box.id = "toasts"; box.style.cssText = "position:fixed;right:1rem;bottom:1rem;z-index:2000;display:grid;gap:.5rem;max-width:min(420px,92vw)"; document.body.appendChild(box); }
  const el = document.createElement("div");
  const color = { info: "#0f1b2d", error: "#8f2424", success: "#11643f", warning: "#7a4d03" }[kind] || "#0f1b2d";
  el.style.cssText = `background:${color};color:#fff;padding:.6rem .9rem;border-radius:.5rem;font-size:.86rem;box-shadow:0 4px 14px rgba(0,0,0,.25)`;
  el.textContent = message;
  box.appendChild(el);
  setTimeout(() => el.remove(), kind === "error" ? 8000 : 4500);
}

/* small Chart.js helper: line chart with a rolling window */
function lineChart(canvas, datasets, yTitle) {
  return new Chart(canvas, {
    type: "line",
    data: { labels: [], datasets: datasets.map(d => ({ tension: .25, pointRadius: 0, borderWidth: 2, fill: false, ...d, data: [] })) },
    options: {
      animation: false, responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: { x: { ticks: { maxTicksLimit: 6, color: "#6b7a90" }, grid: { display: false } },
                y: { beginAtZero: true, title: { display: !!yTitle, text: yTitle }, ticks: { color: "#6b7a90" } } },
      plugins: { legend: { display: datasets.length > 1, labels: { boxWidth: 12 } } },
    },
  });
}
function pushPoint(chart, label, values, max = 40) {
  chart.data.labels.push(label);
  values.forEach((v, i) => chart.data.datasets[i].data.push(v));
  if (chart.data.labels.length > max) { chart.data.labels.shift(); chart.data.datasets.forEach(d => d.data.shift()); }
  chart.update("none");
}
const PALETTE = ["#0e7c86", "#c77d0a", "#5b6ee1", "#c43a3a", "#1a8f5a", "#8a4fb8"];
