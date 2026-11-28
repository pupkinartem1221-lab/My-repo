/* CRM — мини-приложение Telegram (v2). Без сборки и внешних зависимостей. */
"use strict";
const tg = window.Telegram && window.Telegram.WebApp;
const $app = document.getElementById("app");
const $tabs = document.getElementById("tabs");
const $sheetRoot = document.getElementById("sheet-root");
const $toast = document.getElementById("toast-root");
const SVG = "http://www.w3.org/2000/svg";

/* ---------- иконки (линейные, в стиле Lucide) ---------- */
const ICON = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  users: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75",
  receipt: "M5 2v20l2.5-1.5L10 22l2-1.5 2 1.5 2.5-1.5L19 22V2l-2.5 1.5L14 2l-2 1.5L10 2 7.5 3.5zM9 8h6M9 12h6M9 16h4",
  chart: "M3 3v18h18M7 16l4-5 3 3 5-7",
  grid: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
  card: "M2 7a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2zM2 10h20M6 15h4",
  plus: "M12 5v14M5 12h14",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3",
  phone: "M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.9.6 2.8.7a2 2 0 0 1 1.7 2z",
  copy: "M9 9h11v11H9zM5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1",
  send: "M22 2 11 13M22 2l-7 20-4-9-9-4z",
  check: "M20 6 9 17l-5-5",
  x: "M18 6 6 18M6 6l12 12",
  right: "M9 18l6-6-6-6",
  user: "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
  trash: "M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6",
  share: "M4 12v7a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7M16 6l-4-4-4 4M12 2v13",
  clock: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 6v6l4 2",
  wallet: "M20 12V8H6a2 2 0 0 1 0-4h12v4M4 6v12a2 2 0 0 0 2 2h14v-4M18 12a2 2 0 0 0 0 4h4v-4z",
  bell: "M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0",
  camera: "M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2zM12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
  file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6",
  more: "M12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM19 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM5 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z",
  swap: "M17 1l4 4-4 4M3 11V9a4 4 0 0 1 4-4h14M7 23l-4-4 4-4M21 13v2a4 4 0 0 1-4 4H3",
  alert: "M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  up: "M23 6l-9.5 9.5-5-5L1 18M17 6h6v6",
  down: "M23 18l-9.5-9.5-5 5L1 6M17 18h6v-6",
  msg: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z",
  shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
  refresh: "M23 4v6h-6M1 20v-6h6M3.5 9a9 9 0 0 1 14.9-3.4L23 10M1 14l4.6 4.4A9 9 0 0 0 20.5 15",
  percent: "M19 5 5 19M6.5 9a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM17.5 20a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z",
  image: "M3 5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM8.5 10a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM21 15l-5-5L5 21",
};
function icon(name, cls = "") {
  const s = document.createElementNS(SVG, "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("class", "i " + cls); s.setAttribute("aria-hidden", "true");
  const p = document.createElementNS(SVG, "path"); p.setAttribute("d", ICON[name] || ""); s.append(p);
  return s;
}

/* ---------- утилиты ---------- */
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style") el.style.cssText = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const money = (kop) => {
  kop = Math.round(kop || 0);
  const s = Math.abs(kop), hr = Math.floor(s / 100), k = s % 100;
  return (kop < 0 ? "−" : "") + hr.toLocaleString("ru-RU").replace(/[, ]/g, " ") + (k ? "," + String(k).padStart(2, "0") : "") + " ₴";
};
const TZ = "Asia/Yerevan";
const dt = (ts) => ts ? new Date(ts * 1000).toLocaleString("ru-RU", { timeZone: TZ, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).replace(",", "") : "—";
const tm = (ts) => new Date(ts * 1000).toLocaleTimeString("ru-RU", { timeZone: TZ, hour: "2-digit", minute: "2-digit" });
const dayKey = (ts) => new Date(ts * 1000).toLocaleDateString("ru-RU", { timeZone: TZ });
function dayTitle(ts) {
  const k = dayKey(ts), now = Date.now() / 1000;
  if (k === dayKey(now)) return "Сегодня";
  if (k === dayKey(now - 86400)) return "Вчера";
  return new Date(ts * 1000).toLocaleDateString("ru-RU", { timeZone: TZ, day: "numeric", month: "long" });
}
const initials = (name) => (name || "?").replace(/^@/, "").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
const haptic = (type = "light") => {
  try {
    if (type === "ok") tg.HapticFeedback.notificationOccurred("success");
    else if (type === "error" || type === "warning") tg.HapticFeedback.notificationOccurred(type);
    else if (type === "select") tg.HapticFeedback.selectionChanged();
    else tg.HapticFeedback.impactOccurred(type);
  } catch (_) {}
};
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const plural = (n, a, b, c) => { const m = n % 10, mm = n % 100; return n + " " + (m === 1 && mm !== 11 ? a : m >= 2 && m <= 4 && (mm < 10 || mm >= 20) ? b : c); };

function toast(text, err = false) {
  const el = h("div", { class: "toast" + (err ? " err" : "") }, icon(err ? "alert" : "check", "sm"), text);
  $toast.append(el);
  haptic(err ? "error" : "ok");
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 300); }, 2600);
}
async function copy(text, what = "Скопировано") {
  try { await navigator.clipboard.writeText(text); }
  catch (_) { const t = h("textarea", { style: "position:fixed;opacity:0" }); t.value = text; document.body.append(t); t.select(); document.execCommand("copy"); t.remove(); }
  toast(what);
}
function shareText(text) {
  // Открывает выбор чата в Telegram с готовым текстом — реквизиты уходят клиенту в один шаг
  const url = "https://t.me/share/url?url=" + encodeURIComponent(text);
  if (tg && tg.openTelegramLink) tg.openTelegramLink(url); else window.open(url, "_blank");
}
function countUp(el, to, fmt = money, ms = 750) {
  const start = performance.now();
  const step = (now) => {
    const p = Math.min(1, (now - start) / ms), e = 1 - Math.pow(1 - p, 3);
    el.textContent = fmt(to * e);
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
const reqText = (r) => `IBAN: ${r.iban}\nОтримувач: ${r.holder}\nІПН: ${r.ipn}`;

/* ---------- API ---------- */
const params = new URLSearchParams(location.search);
let API = params.get("api") || "";
try { if (!API) API = localStorage.getItem("crm_api") || ""; } catch (_) {}

async function refreshApiUrl() {
  const owner = location.hostname.split(".")[0];
  const repo = location.pathname.split("/").filter(Boolean)[0];
  if (!location.hostname.endsWith("github.io") || !repo) return false;
  try {
    const r = await fetch(`https://raw.githubusercontent.com/${owner}/${repo}/bot-data/api.json?t=${Date.now()}`, { cache: "no-store" });
    if (!r.ok) return false;
    const j = await r.json();
    if (j.api && j.api !== API) { API = j.api; try { localStorage.setItem("crm_api", API); } catch (_) {} return true; }
  } catch (_) {}
  return false;
}
async function api(path, { method = "GET", body, form } = {}, retried = false) {
  const headers = { "X-Init-Data": tg ? tg.initData : "" };
  let payload;
  if (form) payload = form;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  let res;
  try { res = await fetch(API + path, { method, headers, body: payload }); }
  catch (e) {
    if (!retried && await refreshApiUrl()) return api(path, { method, body, form }, true);
    throw new Error("Нет связи с сервером. Закройте и откройте приложение");
  }
  if (path.endsWith("/file")) { if (!res.ok) throw new Error("Файл недоступен"); return res.blob(); }
  let data = {};
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) { const err = new Error(data.error || "Ошибка " + res.status); err.code = data.code; throw err; }
  try { localStorage.setItem("crm_api", API); } catch (_) {}
  return data;
}

/* ---------- каркас: шапка, вкладки, экраны ---------- */
let ME = null;
const stack = [];
let currentTab = "home";
let renderToken = 0;
let badge = 0;

const TABS_ADMIN = [["home", "home", "Главная"], ["clients", "users", "Клиенты"], ["receipts", "receipt", "Квитанции"], ["reports", "chart", "Отчёты"], ["more", "grid", "Ещё"]];
const TABS_WORKER = [["home", "home", "Главная"], ["clients", "users", "Клиенты"], ["receipts", "receipt", "Квитанции"], ["reports", "chart", "Доход"], ["reqs", "card", "Реквизиты"]];

function renderTabs() {
  const tabs = ME.admin ? TABS_ADMIN : TABS_WORKER;
  const idx = Math.max(0, tabs.findIndex(([id]) => id === currentTab));
  const pill = h("div", { class: "tab-pill" });
  $tabs.replaceChildren(pill, ...tabs.map(([id, ic, tx]) =>
    h("button", { class: "tab" + (id === currentTab ? " on" : ""), onclick: () => go(id) },
      icon(ic), h("span", { class: "tx" }, tx),
      id === "receipts" && badge ? h("span", { class: "count-badge" }, badge) : null)));
  $tabs.classList.remove("hidden");
  requestAnimationFrame(() => {
    const b = $tabs.children[idx + 1];
    if (b) { pill.style.left = b.offsetLeft + "px"; pill.style.width = b.offsetWidth + "px"; }
  });
}
function setBadge(n) { badge = n; renderTabs(); }

function appbar(title, right) {
  const bar = h("div", { class: "appbar" }, h("div", { class: "title" }, title), right || null);
  return bar;
}
function onScrollBar() {
  const bar = $app.querySelector(".appbar");
  if (bar) bar.classList.toggle("scrolled", window.scrollY > 8);
}
window.addEventListener("scroll", onScrollBar, { passive: true });

function mount(node, push = false) {
  node.classList.add("screen");
  if (push) node.classList.add("push");
  $app.replaceChildren(node);
  window.scrollTo(0, 0);
  onScrollBar();
}
function updateBack() { if (tg) { if (stack.length || $sheetRoot.childElementCount) tg.BackButton.show(); else tg.BackButton.hide(); } }

const SCREENS = () => ({ home: Home, clients: Clients, receipts: Receipts, reports: Reports, more: More, reqs: () => RequisitesScreen(false) });
function go(tab) {
  if (tab !== currentTab) haptic("select");
  currentTab = tab; stack.length = 0; closeSheet(true); updateBack();
  renderTabs();
  SCREENS()[tab]();
}
function push(fn) { stack.push(fn); updateBack(); fn(true); }
function back() {
  if ($sheetRoot.childElementCount) return closeSheet();
  stack.pop(); updateBack();
  if (stack.length) stack[stack.length - 1](true); else go(currentTab);
}
function refreshCurrent() { if (stack.length) stack[stack.length - 1](true); else SCREENS()[currentTab](); }

function skeleton(n = 5) {
  return h("div", null, h("div", { class: "skel", style: "height:30px;width:45%;margin:8px 2px 16px" }),
    h("div", { class: "skel", style: "height:150px;margin-bottom:12px" }),
    Array.from({ length: n }, () => h("div", { class: "skel skel-item" })));
}
function emptyState(ic, text, extra) {
  return h("div", { class: "empty" }, h("div", { class: "ic" }, ic), h("div", null, text), extra || null);
}
function stagger(list) { [...list.children].forEach((el, i) => el.style.animationDelay = Math.min(i, 12) * 35 + "ms"); return list; }

async function load(fn, wrap) {
  const token = ++renderToken;
  mount(skeleton(), !!wrap);
  try {
    const node = await fn();
    if (token === renderToken) { mount(node, !!wrap); attachPullToRefresh(); }
  } catch (e) {
    if (token === renderToken) mount(h("div", null, emptyState("😕", e.message,
      h("button", { class: "btn ghost", style: "margin-top:14px", onclick: refreshCurrent }, icon("refresh", "sm"), "Повторить"))));
  }
}

/* ---------- обновление потягиванием вниз ---------- */
let ptrBound = false;
function attachPullToRefresh() {
  if (ptrBound) return; ptrBound = true;
  let startY = null, ptr = null, dist = 0;
  window.addEventListener("touchstart", (e) => {
    if (window.scrollY > 0 || $sheetRoot.childElementCount || e.target.closest(".swipe-wrap,input,textarea")) { startY = null; return; }
    startY = e.touches[0].clientY; dist = 0;
  }, { passive: true });
  window.addEventListener("touchmove", (e) => {
    if (startY == null) return;
    dist = e.touches[0].clientY - startY;
    if (dist <= 0) return;
    if (!ptr) { ptr = h("div", { class: "ptr" }, icon("refresh")); $app.firstChild && $app.firstChild.prepend(ptr); }
    ptr.style.height = Math.min(70, dist * 0.45) + "px";
    ptr.firstChild.style.transform = `rotate(${dist * 2}deg)`;
  }, { passive: true });
  window.addEventListener("touchend", () => {
    if (ptr) {
      if (dist > 120) { ptr.classList.add("spin"); haptic("medium"); setTimeout(refreshCurrent, 250); }
      else { ptr.style.height = "0px"; const p = ptr; setTimeout(() => p.remove(), 260); }
    }
    ptr = null; startY = null; dist = 0;
  });
}

/* ---------- шторка ---------- */
function openSheet(title, content) {
  closeSheet(true);
  const bd = h("div", { class: "backdrop", onclick: () => closeSheet() });
  const sh = h("div", { class: "sheet" }, h("div", { class: "grab" }), title ? h("h3", null, title) : null, content);
  $sheetRoot.append(bd, sh);
  updateBack(); haptic("light");
  return sh;
}
function closeSheet(instant = false) {
  const kids = [...$sheetRoot.children];
  if (!kids.length) return;
  if (instant) { $sheetRoot.replaceChildren(); updateBack(); return; }
  kids.forEach((k) => k.classList.add("out"));
  setTimeout(() => { kids.forEach((k) => k.remove()); updateBack(); }, 230);
}
function confirmAsk(text) { return new Promise((res) => { if (tg && tg.showConfirm) tg.showConfirm(text, res); else res(confirm(text)); }); }
async function withLoading(btn, fn) {
  if (btn.classList.contains("loading")) return;
  btn.classList.add("loading"); btn.disabled = true;
  try { await fn(); } catch (e) { toast(e.message, true); }
  finally { btn.classList.remove("loading"); btn.disabled = false; }
}
function field(label, input, hint) { return h("div", { class: "field" }, h("label", null, label), input, hint ? h("div", { class: "hint" }, hint) : null); }
function shake(el) { el.classList.add("err"); haptic("error"); setTimeout(() => el.classList.remove("err"), 400); }

/* ---------- графики ---------- */
function sparkline(values) {
  const W = 300, H = 54, n = values.length, max = Math.max(1, ...values), min = 0;
  const pts = values.map((v, i) => [i * (W / (n - 1)), H - 6 - ((v - min) / (max - min || 1)) * (H - 12)]);
  const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("class", "spark"); svg.setAttribute("preserveAspectRatio", "none");
  const defs = document.createElementNS(SVG, "defs");
  const g = document.createElementNS(SVG, "linearGradient");
  g.id = "sparkfill"; g.setAttribute("x1", "0"); g.setAttribute("y1", "0"); g.setAttribute("x2", "0"); g.setAttribute("y2", "1");
  [["0%", "rgba(255,255,255,.35)"], ["100%", "rgba(255,255,255,0)"]].forEach(([o, c]) => { const s = document.createElementNS(SVG, "stop"); s.setAttribute("offset", o); s.setAttribute("stop-color", c); g.append(s); });
  defs.append(g); svg.append(defs);
  const area = document.createElementNS(SVG, "path"); area.setAttribute("class", "area"); area.setAttribute("d", d + ` L${W} ${H} L0 ${H} Z`);
  const line = document.createElementNS(SVG, "path"); line.setAttribute("class", "line"); line.setAttribute("d", d);
  const last = pts[pts.length - 1];
  const dot = document.createElementNS(SVG, "circle"); dot.setAttribute("cx", last[0]); dot.setAttribute("cy", last[1]); dot.setAttribute("r", "3.5");
  svg.append(area, line, dot);
  return svg;
}

function barChart(data) {
  const W = 320, H = 150, pad = 18, n = data.length, max = Math.max(1, ...data.map((d) => d.value));
  const bw = (W - pad) / n;
  const wrap = h("div", { class: "chart-wrap" });
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H + 14}`); svg.setAttribute("class", "chart");
  const defs = document.createElementNS(SVG, "defs");
  const g = document.createElementNS(SVG, "linearGradient");
  g.id = "gb"; g.setAttribute("x1", "0"); g.setAttribute("y1", "0"); g.setAttribute("x2", "0"); g.setAttribute("y2", "1");
  [["0%", "#8b7dff"], ["100%", "#4aa8ff"]].forEach(([o, c]) => { const s = document.createElementNS(SVG, "stop"); s.setAttribute("offset", o); s.setAttribute("stop-color", c); g.append(s); });
  defs.append(g); svg.append(defs);
  [0.25, 0.5, 0.75].forEach((f) => {
    const l = document.createElementNS(SVG, "line");
    l.setAttribute("x1", 0); l.setAttribute("x2", W); l.setAttribute("y1", H - f * (H - 10)); l.setAttribute("y2", H - f * (H - 10));
    l.setAttribute("stroke", "#1f2431"); l.setAttribute("stroke-dasharray", "3 4"); svg.append(l);
  });
  let tip = null;
  const step = Math.ceil(n / 7);
  data.forEach((d, i) => {
    const hgt = Math.max(d.value ? 3 : 1.5, (d.value / max) * (H - 10));
    const r = document.createElementNS(SVG, "rect");
    const x = pad / 2 + i * bw + bw * 0.16;
    r.setAttribute("x", x.toFixed(1)); r.setAttribute("width", (bw * 0.68).toFixed(1));
    r.setAttribute("y", (H - hgt).toFixed(1)); r.setAttribute("height", hgt.toFixed(1)); r.setAttribute("rx", Math.min(6, bw * 0.3).toFixed(1));
    r.setAttribute("fill", d.value ? "url(#gb)" : "#232938"); r.setAttribute("class", "bar"); r.style.animationDelay = i * 25 + "ms";
    r.addEventListener("click", () => {
      haptic("select");
      svg.querySelectorAll(".bar").forEach((b) => b.classList.remove("sel"));
      r.classList.add("sel"); svg.classList.add("has-sel");
      if (tip) tip.remove();
      tip = h("div", { class: "tip" }, `${d.label} · ${money(d.value)}`);
      tip.style.left = ((x + bw * 0.34) / W * 100) + "%";
      tip.style.top = ((H - hgt) / (H + 14) * 100) + "%";
      wrap.append(tip);
    });
    svg.append(r);
    if (i % step === 0 || i === n - 1) {
      const tx = document.createElementNS(SVG, "text");
      tx.setAttribute("x", (pad / 2 + i * bw + bw / 2).toFixed(1)); tx.setAttribute("y", H + 12); tx.setAttribute("text-anchor", "middle"); tx.textContent = d.label;
      svg.append(tx);
    }
  });
  wrap.append(svg);
  return wrap;
}

function breakdown(items) {
  const max = Math.max(1, ...items.map((x) => x.value));
  return h("div", { class: "card" }, ...items.map((x, i) => {
    const bar = h("i");
    setTimeout(() => bar.style.width = (x.value / max * 100).toFixed(1) + "%", 80 + i * 60);
    return h("div", { style: "padding:8px 0" }, h("div", { class: "row between" }, h("div", { class: "ellipsis grow" }, x.name), h("b", null, money(x.value))),
      h("div", { class: "meter" }, bar), h("div", { class: "small muted", style: "margin-top:4px" }, x.sub));
  }));
}

/* ================= ГЛАВНАЯ ================= */
function greeting() {
  const hr = Number(new Date().toLocaleString("en-US", { timeZone: TZ, hour: "numeric", hour12: false }));
  return hr < 5 ? "Доброй ночи" : hr < 12 ? "Доброе утро" : hr < 18 ? "Добрый день" : "Добрый вечер";
}
function Home() {
  load(async () => {
    const d = await api("/api/dashboard");
    if (ME.admin) setBadge(d.pending.count);
    const val = (x) => ME.admin ? x.amount : x.share;
    const todayV = val(d.today), yV = val(d.yesterday);
    const delta = yV ? Math.round((todayV - yV) / yV * 100) : null;
    const big = h("div", { class: "big count-up" }, money(0));

    const att = [];
    if (ME.admin && d.waiting_access) att.push(["bell", "var(--yellow-bg)", "var(--yellow)", `Ждут доступа`, d.waiting_access, () => { currentTab = "more"; renderTabs(); push(TeamScreen); }]);
    if (d.pending.count) att.push(["receipt", "var(--blue-bg)", "var(--blue)", ME.admin ? "Квитанции на проверке" : "Ваши квитанции на проверке", d.pending.count, () => go("receipts")]);
    if (d.clients.no_requisite) att.push(["card", "var(--red-bg)", "var(--red)", "Клиенты без реквизита", d.clients.no_requisite, () => { clientFilter.status = "work"; go("clients"); }]);

    const node = h("div", null,
      appbar(`${greeting()}, ${ME.user.nick}`, h("div", { class: "me" }, initials(ME.user.nick))),
      h("div", { class: "card hero" },
        h("div", { class: "label" }, ME.admin ? "Оплачено сегодня" : "Заработано сегодня",
          delta != null ? h("span", { class: "delta" }, icon(delta >= 0 ? "up" : "down", "xs"), (delta >= 0 ? "+" : "") + delta + "%") : null),
        big,
        h("div", { class: "meta" }, `${plural(d.today.count, "оплата", "оплаты", "оплат")} · вчера ${money(yV)}`),
        sparkline(d.week.map(val))),
      h("div", { class: "kpis" },
        h("div", { class: "kpi click", onclick: () => go("receipts") }, h("div", { class: "row between" }, h("div", { class: "label" }, "На проверке"), icon("clock", "sm")),
          h("div", { class: "value" }, d.pending.count), h("div", { class: "small muted" }, money(d.pending.amount))),
        h("div", { class: "kpi click", onclick: () => go("clients") }, h("div", { class: "row between" }, h("div", { class: "label" }, "В работе"), icon("users", "sm")),
          h("div", { class: "value" }, d.clients.work), h("div", { class: "small muted" }, "всего " + d.clients.total))),
      h("div", { class: "quick" },
        h("div", { class: "q", onclick: () => newClientSheet() }, icon("plus", "lg"), h("div", { class: "tx" }, "Клиент")),
        h("div", { class: "q", onclick: () => go("receipts") }, icon("receipt", "lg"), h("div", { class: "tx" }, "Квитанции"),
          d.pending.count ? h("span", { class: "count-badge" }, d.pending.count) : null),
        h("div", { class: "q", onclick: () => go("reports") }, icon("chart", "lg"), h("div", { class: "tx" }, ME.admin ? "Отчёт" : "Доход"))),
      att.length ? h("div", null, h("div", { class: "subtitle" }, "Требует внимания"),
        stagger(h("div", { class: "attention" }, ...att.map(([ic, bg, fg, text, n, fn]) => h("div", { class: "att", onclick: fn },
          h("div", { class: "ico", style: `background:${bg};color:${fg}` }, icon(ic, "sm")),
          h("div", { class: "grow" }, text), h("b", null, n), icon("right", "sm")))))) : null,
      d.recent.length ? h("div", null, h("div", { class: "subtitle" }, "Последние оплаты"),
        stagger(h("div", { class: "list" }, ...d.recent.map((p) => h("div", { class: "item", onclick: () => p.client_id && push((x) => ClientScreen(p.client_id, x)) },
          h("div", { class: "avatar s-paid" }, initials(p.client_name)),
          h("div", { class: "grow" }, h("div", { class: "name ellipsis" }, p.client_name || "—"),
            h("div", { class: "sub" }, `${dayTitle(p.at)}, ${tm(p.at)}${ME.admin && p.worker ? " · " + p.worker : ""}`)),
          h("div", { class: "right", style: "color:var(--green)" }, "+" + money(ME.admin ? p.amount : p.share))))))) : null);
    setTimeout(() => countUp(big, todayV), 120);
    return node;
  });
}

/* ================= КЛИЕНТЫ ================= */
const ST = { work: "В работе", paid: "Оплачено", lost: "Слив" };
const ST_IC = { work: "🔄", paid: "✅", lost: "❌" };
const ST_GLOW = { work: "rgba(74,168,255,.45)", paid: "rgba(47,210,122,.4)", lost: "rgba(255,93,108,.4)" };
let clientFilter = { status: "", q: "" };

function Clients() {
  const listBox = h("div");
  const chipsBox = h("div", { class: "chips" });
  const input = h("input", { placeholder: "Имя или телефон", value: clientFilter.q, type: "search", enterkeyhint: "search" });
  const fetchList = async () => {
    const token = ++renderToken;
    listBox.replaceChildren(...Array.from({ length: 6 }, () => h("div", { class: "skel skel-item" })));
    try {
      const qs = new URLSearchParams({ status: clientFilter.status, q: clientFilter.q });
      const d = await api("/api/clients?" + qs);
      if (token !== renderToken) return;
      const total = Object.values(d.counts).reduce((a, b) => a + b, 0);
      chipsBox.replaceChildren(...[["", "Все", total], ...Object.keys(ST).map((k) => [k, ST_IC[k] + " " + ST[k], d.counts[k] || 0])].map(([k, t, n]) =>
        h("div", { class: "chip" + (clientFilter.status === k ? " on" : ""), onclick: () => { haptic("select"); clientFilter.status = k; fetchList(); } }, t, h("span", { class: "n" }, n))));
      if (!d.items.length) {
        listBox.replaceChildren(emptyState(clientFilter.q ? "🔍" : "👥", clientFilter.q ? "Ничего не найдено" : "Пока пусто",
          clientFilter.q ? null : h("button", { class: "btn primary", style: "margin-top:14px", onclick: () => newClientSheet() }, icon("plus", "sm"), "Добавить клиента")));
        return;
      }
      // группировка по дате добавления
      const groups = [];
      for (const c of d.items) {
        const t = dayTitle(c.created_at);
        if (!groups.length || groups[groups.length - 1][0] !== t) groups.push([t, []]);
        groups[groups.length - 1][1].push(c);
      }
      listBox.replaceChildren(h("div", { class: "list-meta" }, h("span", null, plural(d.items.length, "клиент", "клиента", "клиентов")), h("span", null, "по дате добавления")),
        ...groups.map(([title, items]) => h("div", null, h("div", { class: "group-title" }, title),
          stagger(h("div", { class: "list" }, ...items.map(clientItem))))));
    } catch (e) { listBox.replaceChildren(emptyState("😕", e.message)); }
  };
  input.addEventListener("input", debounce(() => { clientFilter.q = input.value.trim(); fetchList(); }, 300));
  mount(h("div", null,
    appbar(ME.admin ? "Клиенты" : "Мои клиенты"),
    h("div", { class: "search" }, icon("search", "sm"), input,
      h("button", { class: "copy" + (clientFilter.q ? "" : " hidden"), onclick: () => { input.value = ""; clientFilter.q = ""; fetchList(); } }, icon("x", "xs"))),
    chipsBox, listBox,
    h("button", { class: "fab", onclick: () => newClientSheet() }, icon("plus", "lg"))));
  attachPullToRefresh();
  fetchList();
}

function clientItem(c) {
  return h("div", { class: "item", onclick: () => push((p) => ClientScreen(c.id, p)) },
    h("div", { class: "avatar s-" + c.status }, initials(c.name)),
    h("div", { class: "grow" }, h("div", { class: "name ellipsis" }, c.name),
      h("div", { class: "sub ellipsis" }, [c.phone, ME.admin && c.worker ? c.worker : null].filter(Boolean).join(" · "))),
    c.paid ? h("div", { class: "right", style: "color:var(--green)" }, money(c.paid)) : icon("right", "sm chev"));
}

async function newClientSheet() {
  let team = [];
  if (ME.admin) { try { team = (await api("/api/team")).items.filter((u) => u.state === "active"); } catch (_) {} }
  const name = h("input", { class: "input", placeholder: "Иван Петров", autocomplete: "off", enterkeyhint: "next" });
  const phone = h("input", { class: "input", placeholder: "+380 67 123 45 67", type: "tel", inputmode: "tel", enterkeyhint: "next" });
  const comment = h("textarea", { class: "input", placeholder: "Маршрут, дата поездки, детали — необязательно" });
  name.addEventListener("keydown", (e) => { if (e.key === "Enter") phone.focus(); });
  phone.addEventListener("keydown", (e) => { if (e.key === "Enter") comment.focus(); });
  let worker = ME.user.id;
  const workerBox = ME.admin && team.length > 1 ? h("div", { class: "chips", style: "flex-wrap:wrap" }) : null;
  const drawWorkers = () => workerBox && workerBox.replaceChildren(...team.map((u) => h("div", { class: "chip" + (u.id === worker ? " on" : ""), onclick: () => { worker = u.id; haptic("select"); drawWorkers(); } },
    u.id === ME.user.id ? "Себе" : u.nick)));
  drawWorkers();
  const save = h("button", { class: "btn primary block", style: "margin-top:6px" }, icon("check", "sm"), "Добавить клиента");
  save.onclick = () => withLoading(save, async () => {
    if (!name.value.trim()) { shake(name); throw new Error("Укажите имя"); }
    if (phone.value.replace(/\D/g, "").length < 7) { shake(phone); throw new Error("Проверьте телефон"); }
    const r = await api("/api/clients", { method: "POST", body: { name: name.value, phone: phone.value, comment: comment.value, worker_id: worker } });
    closeSheet(true); toast("Клиент добавлен");
    if (currentTab !== "clients") { currentTab = "clients"; renderTabs(); }
    stack.length = 0; push((p) => ClientScreen(r.id, p));
  });
  openSheet("Новый клиент", h("div", null, field("Имя", name), field("Телефон", phone), field("Комментарий", comment),
    workerBox ? field("Кому отдать", workerBox) : null, save));
  setTimeout(() => name.focus(), 350);
}

function ClientScreen(id) {
  load(async () => {
    const c = await api("/api/clients/" + id);
    const profile = h("div", { class: "profile", style: `--glow:${ST_GLOW[c.status]}` });
    const seg = h("div", { class: "seg" });
    const ind = h("div", { class: "ind" });
    const avatar = h("div", { class: "avatar lg s-" + c.status, style: "margin:0 auto" }, initials(c.name));
    const drawSeg = () => {
      const keys = Object.keys(ST);
      seg.replaceChildren(ind, ...keys.map((k) => h("button", { class: (c.status === k ? "on " : "") + k, onclick: async () => {
        if (c.status === k) return;
        // «Оплачено» — только с квитанцией: сразу предлагаем прикрепить
        if (k === "paid" && !c.payments.some((p) => p.status === "pending" || p.status === "confirmed")) {
          haptic("warning"); return receiptSheet(c, true);
        }
        const prev = c.status; c.status = k; drawSeg(); haptic("medium");
        try { await api("/api/clients/" + id, { method: "PATCH", body: { status: k } }); toast(ST[k]); }
        catch (e) { c.status = prev; drawSeg(); if (e.code === "receipt_required") receiptSheet(c, true); else toast(e.message, true); }
      } }, ST_IC[k] + " " + ST[k])));
      const i = keys.indexOf(c.status);
      ind.className = "ind " + c.status;
      ind.style.width = `calc((100% - 8px) / ${keys.length})`;
      ind.style.left = `calc(4px + (100% - 8px) / ${keys.length} * ${i})`;
      avatar.className = "avatar lg s-" + c.status;
      profile.style.setProperty("--glow", ST_GLOW[c.status]);
    };
    drawSeg();

    const req = c.requisite;
    profile.append(avatar, h("div", { class: "name" }, c.name), h("div", { class: "phone" }, c.phone || "—"),
      h("div", { class: "actions" },
        c.phone ? h("a", { class: "act", href: "tel:" + c.phone.replace(/[^\d+]/g, "") }, icon("phone", "sm"), "Позвонить") : null,
        h("div", { class: "act", onclick: () => receiptSheet(c) }, icon("receipt", "sm"), "Квитанция"),
        req && req.active ? h("div", { class: "act", onclick: () => shareText(reqText(req)) }, icon("send", "sm"), "Реквизиты") : null,
        c.can_manage ? h("div", { class: "act", onclick: () => clientMenu(c) }, icon("more", "sm"), "Ещё") : null));

    const reqCard = h("div", { class: "card" },
      h("div", { class: "row between", style: "margin-bottom:4px" }, h("b", { class: "row", style: "gap:8px" }, icon("card", "sm"), "Реквизит для оплаты"),
        h("button", { class: "copy", onclick: () => pickRequisite(c) }, req ? "Сменить" : "Выбрать")),
      req ? h("div", null,
        ...[["IBAN", req.iban], ["Получатель", req.holder], ["ІПН", req.ipn]].map(([k, v]) =>
          h("div", { class: "kv" }, h("div", { class: "grow" }, h("div", { class: "k" }, k), h("div", { class: "mono" }, v)),
            h("button", { class: "copy", onclick: () => copy(v, k + " скопирован") }, icon("copy", "xs")))),
        req.active ? h("div", { class: "btns", style: "margin-top:10px" },
          h("button", { class: "btn sm", onclick: () => copy(reqText(req), "Реквизиты скопированы") }, icon("copy", "xs"), "Копировать"),
          h("button", { class: "btn sm share-btn", onclick: () => shareText(reqText(req)) }, icon("send", "xs"), "Отправить клиенту"))
          : h("div", { class: "hint warn" }, "⚠️ Этот реквизит не рабочий — выберите другой"))
        : h("div", { class: "hint" }, "Выберите, куда клиент будет платить"));

    const paid = c.payments.filter((p) => p.status === "confirmed").reduce((a, p) => a + p.amount, 0);
    const commentsBox = h("div", { class: "timeline" }, ...c.comments.slice().reverse().map(commentNode));
    const cInput = h("input", { class: "input", placeholder: "Написать комментарий…", enterkeyhint: "send" });
    const cSend = h("button", { class: "btn primary" }, icon("send", "sm"));
    const sendComment = () => withLoading(cSend, async () => {
      if (!cInput.value.trim()) return;
      const r = await api(`/api/clients/${id}/comments`, { method: "POST", body: { text: cInput.value } });
      cInput.value = ""; commentsBox.querySelector(".hint")?.remove(); commentsBox.append(commentNode(r)); haptic("light");
    });
    cSend.onclick = sendComment;
    cInput.addEventListener("keydown", (e) => { if (e.key === "Enter") sendComment(); });
    if (!c.comments.length) commentsBox.append(h("div", { class: "hint" }, "Пока нет комментариев"));

    return h("div", null,
      profile, seg,
      h("div", { class: "card" },
        h("div", { class: "kv" }, h("div", { class: "k" }, "Сотрудник"), h("div", { class: "v" }, c.worker ? c.worker.nick : "—")),
        h("div", { class: "kv" }, h("div", { class: "k" }, "Оплачено"), h("div", { class: "v", style: "color:var(--green)" }, money(paid))),
        h("div", { class: "kv" }, h("div", { class: "k" }, "Добавлен"), h("div", { class: "v" }, dt(c.created_at)))),
      reqCard,
      h("div", { class: "row between subtitle" }, h("span", null, "Оплаты"), h("button", { class: "copy", onclick: () => receiptSheet(c) }, "+ Квитанция")),
      c.payments.length ? stagger(h("div", { class: "list" }, ...c.payments.map(paymentRow))) : h("div", { class: "hint", style: "margin:0 4px" }, "Оплат пока нет"),
      h("div", { class: "subtitle" }, "Комментарии"), commentsBox,
      h("div", { class: "comment-box" }, cInput, cSend));
  }, true);
}

function commentNode(x) { return h("div", { class: "comment" }, h("div", { class: "who" }, `${x.author || "—"} · ${dt(x.at)}`), x.text); }

const PST = { pending: ["clock", "На проверке"], confirmed: ["check", "Подтверждена"], rejected: ["x", "Отклонена"] };
function paymentRow(p) {
  return h("div", { class: "item", onclick: () => viewFile(p) },
    h("div", { class: "avatar s-" + p.status }, icon(PST[p.status][0], "sm")),
    h("div", { class: "grow" }, h("div", { class: "name" }, money(p.amount)), h("div", { class: "sub" }, `${PST[p.status][1]} · ${dt(p.submitted_at)}`)),
    p.share != null ? h("div", { class: "right small muted" }, money(p.share)) : icon("image", "sm chev"));
}

async function pickRequisite(c) {
  const d = await api("/api/requisites").catch((e) => toast(e.message, true));
  if (!d) return;
  const active = d.items.filter((r) => r.active);
  const box = h("div", { class: "options" }, ...active.map((r) => h("div", { class: "opt" + (c.requisite && c.requisite.id === r.id ? " on" : ""), onclick: async () => {
    try { await api("/api/clients/" + c.id, { method: "PATCH", body: { requisite_id: r.id } }); closeSheet(); toast("Реквизит выбран"); refreshCurrent(); }
    catch (e) { toast(e.message, true); }
  } }, h("span", { class: "radio" }), h("div", { class: "grow" }, h("div", { style: "font-weight:600" }, r.holder), h("div", { class: "mono muted" }, "…" + r.iban.slice(-8))))));
  openSheet("Реквизит для клиента", active.length ? h("div", null, box,
    c.requisite ? h("button", { class: "btn red block", style: "margin-top:10px", onclick: async () => {
      await api("/api/clients/" + c.id, { method: "PATCH", body: { requisite_id: null } }); closeSheet(); refreshCurrent();
    } }, "Отвязать реквизит") : null) : emptyState("💳", "Нет рабочих реквизитов"));
}

async function clientMenu(c) {
  let team = [];
  try { team = (await api("/api/team")).items.filter((u) => u.state === "active"); } catch (_) {}
  const box = h("div", { class: "options" }, ...team.map((u) => h("div", { class: "opt" + (c.worker && c.worker.id === u.id ? " on" : ""), onclick: async () => {
    try { await api("/api/clients/" + c.id, { method: "PATCH", body: { worker_id: u.id } }); closeSheet(); toast("Передан: " + u.nick); refreshCurrent(); }
    catch (e) { toast(e.message, true); }
  } }, h("span", { class: "radio" }), h("div", { class: "grow" }, u.nick), h("span", { class: "small muted" }, u.percent + "%"))));
  const del = h("button", { class: "btn red block", style: "margin-top:14px" }, icon("trash", "sm"), "Удалить клиента");
  del.onclick = async () => {
    if (!await confirmAsk(`Удалить клиента «${c.name}»? Оплаты останутся в отчётах.`)) return;
    withLoading(del, async () => { await api("/api/clients/" + c.id, { method: "DELETE" }); closeSheet(true); toast("Удалено"); back(); });
  };
  openSheet("Передать сотруднику", h("div", null, box, del));
}

/* ---------- новая квитанция ---------- */
async function receiptSheet(c, setPaid = false) {
  let file = null, reqId = c.requisite ? c.requisite.id : null;
  const preview = h("div");
  const fileInput = h("input", { type: "file", accept: "image/*,application/pdf", class: "hidden" });
  const drop = h("div", { class: "upload", onclick: () => fileInput.click() }, icon("camera", "lg"), h("div", { style: "margin-top:6px" }, "Сфотографируйте или выберите квитанцию"));
  fileInput.onchange = () => {
    file = fileInput.files[0]; if (!file) return;
    if (file.size > 20 * 1024 * 1024) { file = null; return toast("Файл больше 20 МБ", true); }
    haptic("light");
    preview.replaceChildren(file.type.startsWith("image/") ? h("img", { class: "preview", src: URL.createObjectURL(file) }) : h("div", { class: "pdf" }, icon("file", "lg")),
      h("div", { class: "hint", style: "text-align:center" }, file.name, " · ", h("a", { style: "color:var(--accent2)", onclick: () => fileInput.click() }, "заменить")));
    drop.classList.add("hidden");
    setTimeout(() => amount.focus(), 200);
  };
  const amount = h("input", { class: "input amount-input", placeholder: "0 ₴", inputmode: "decimal" });
  let reqBox = null;
  if (!c.requisite) {
    const d = await api("/api/requisites").catch(() => ({ items: [] }));
    const active = d.items.filter((r) => r.active);
    if (active.length) {
      if (active.length === 1) reqId = active[0].id;
      reqBox = h("div", { class: "options" });
      const draw = () => reqBox.replaceChildren(...active.map((r) => h("div", { class: "opt" + (reqId === r.id ? " on" : ""), onclick: () => { reqId = r.id; haptic("select"); draw(); } },
        h("span", { class: "radio" }), h("div", { class: "grow" }, h("div", null, r.holder), h("div", { class: "mono muted" }, "…" + r.iban.slice(-8))))));
      draw();
    }
  }
  const send = h("button", { class: "btn primary block", style: "margin-top:6px" }, icon("send", "sm"), setPaid ? "Прикрепить и отметить «Оплачено»" : "Отправить на проверку");
  send.onclick = () => withLoading(send, async () => {
    if (!file) { shake(drop); throw new Error("Добавьте фото квитанции"); }
    const sum = amount.value.replace(/\s/g, "").replace(",", ".");
    if (!/^\d{1,9}(\.\d{1,2})?$/.test(sum) || Number(sum) <= 0) { shake(amount); throw new Error("Проверьте сумму"); }
    if (reqBox && !reqId) throw new Error("Выберите реквизит");
    const fd = new FormData(); fd.append("file", file); fd.append("amount", sum); if (reqId && !c.requisite) fd.append("requisite_id", reqId);
    if (setPaid) fd.append("set_paid", "1");
    await api(`/api/clients/${c.id}/payments`, { method: "POST", form: fd });
    closeSheet(true); toast(setPaid ? "Квитанция прикреплена · ✅ Оплачено" : ME.admin ? "Квитанция добавлена" : "Отправлено на проверку"); refreshCurrent();
  });
  openSheet(setPaid ? "Прикрепите квитанцию" : "Квитанция · " + c.name, h("div", null,
    setPaid ? h("div", { class: "banner", style: "cursor:default" }, icon("alert", "sm"), h("div", { class: "grow" }, "Статус «Оплачено» ставится только с квитанцией")) : null,
    fileInput, drop, preview, h("div", { style: "height:12px" }),
    field("Сумма, ₴", amount), reqBox ? field("Куда пришли деньги", reqBox) : null, send));
}

async function viewFile(p) {
  try {
    const blob = await api(`/api/payments/${p.id}/file`);
    const url = URL.createObjectURL(blob);
    if (blob.type === "application/pdf") { window.open(url, "_blank"); return; }
    const v = h("div", { class: "viewer", onclick: () => { v.remove(); URL.revokeObjectURL(url); } }, h("img", { src: url, alt: "" }));
    document.body.append(v); haptic("light");
  } catch (e) { toast(e.message, true); }
}

/* ================= КВИТАНЦИИ ================= */
let receiptTab = "pending";
function Receipts() {
  const box = h("div");
  const tabs = h("div", { class: "seg" });
  const ind = h("div", { class: "ind" });
  const keys = [["pending", "На проверке"], ["confirmed", "Приняты"], ["rejected", "Отклонены"]];
  const drawTabs = () => {
    tabs.replaceChildren(ind, ...keys.map(([k, t]) => h("button", { class: receiptTab === k ? "on" : "", onclick: () => { receiptTab = k; haptic("select"); drawTabs(); fetchList(); } }, t)));
    const i = keys.findIndex(([k]) => k === receiptTab);
    ind.style.width = "calc((100% - 8px) / 3)"; ind.style.left = `calc(4px + (100% - 8px) / 3 * ${i})`;
  };
  const fetchList = async () => {
    const token = ++renderToken;
    box.replaceChildren(...Array.from({ length: 2 }, () => h("div", { class: "skel", style: "height:300px;margin-bottom:10px" })));
    try {
      const d = await api("/api/payments?status=" + receiptTab);
      if (token !== renderToken) return;
      if (receiptTab === "pending" && ME.admin) setBadge(d.items.length);
      if (!d.items.length) { box.replaceChildren(emptyState(receiptTab === "pending" ? "✨" : "🗂", receiptTab === "pending" ? "Всё проверено" : "Пока пусто")); return; }
      const total = d.items.reduce((a, p) => a + p.amount, 0);
      box.replaceChildren(
        h("div", { class: "list-meta" }, h("span", null, plural(d.items.length, "квитанция", "квитанции", "квитанций")), h("span", null, money(total))),
        ME.admin && receiptTab === "pending" ? h("div", { class: "swipe-hint" }, "← отклонить", icon("swap", "xs"), "подтвердить →") : null,
        ...d.items.map((p, i) => { const el = receiptCard(p, box); el.style.animationDelay = Math.min(i, 8) * 60 + "ms"; return el; }));
    } catch (e) { box.replaceChildren(emptyState("😕", e.message)); }
  };
  drawTabs();
  mount(h("div", null, appbar("Квитанции"), tabs, box));
  attachPullToRefresh();
  fetchList();
}

function receiptCard(p, box) {
  const img = h("div", { class: "img skel" });
  (async () => {
    try {
      const blob = await api(`/api/payments/${p.id}/file`);
      if (blob.type === "application/pdf") img.replaceWith(h("div", { class: "pdf", onclick: () => viewFile(p) }, icon("file", "lg")));
      else {
        const el = h("img", { class: "img", src: URL.createObjectURL(blob), alt: "", onclick: () => viewFile(p) });
        el.onerror = () => el.replaceWith(h("div", { class: "pdf", onclick: () => viewFile(p) }, icon("image", "lg")));
        img.replaceWith(el);
      }
    } catch (_) { img.replaceWith(h("div", { class: "pdf" }, icon("image", "lg"))); }
  })();
  const canReview = ME.admin && p.status === "pending";
  const wrap = h("div", { class: "swipe-wrap" });
  const remove = () => {
    wrap.style.maxHeight = wrap.offsetHeight + "px";
    requestAnimationFrame(() => wrap.classList.add("gone"));
    setTimeout(() => { wrap.remove(); if (!box.querySelector(".swipe-wrap")) box.replaceChildren(emptyState("✨", "Всё проверено")); }, 460);
  };
  const review = async (action) => {
    await api(`/api/payments/${p.id}/review`, { method: "POST", body: { action } });
    toast(action === "ok" ? "Подтверждено · " + money(p.amount) : "Отклонено");
    if (badge) setBadge(badge - 1);
    remove();
  };
  const card = h("div", { class: "card receipt" }, img,
    h("div", { class: "body" },
      h("div", { class: "row between" }, h("div", { class: "amount" }, money(p.amount)),
        h("span", { class: "badge s-" + p.status }, icon(PST[p.status][0], "xs"), PST[p.status][1])),
      h("div", { class: "row", style: "margin-top:8px;cursor:pointer", onclick: () => p.client_id && push((x) => ClientScreen(p.client_id, x)) },
        h("div", { class: "grow" }, h("div", { class: "name" }, p.client_name || "—"),
          h("div", { class: "small muted" }, [p.phone, p.requisite ? "💳 …" + p.requisite.split(" ")[0].slice(-6) : null].filter(Boolean).join(" · "))),
        p.client_id ? icon("right", "sm chev") : null),
      h("div", { class: "small muted", style: "margin-top:6px" }, `${p.worker || "—"} · ${dt(p.submitted_at)}`, p.reviewer ? ` · проверил ${p.reviewer}` : ""),
      p.share != null ? h("div", { class: "small", style: "margin-top:4px;color:var(--green)" }, `Сотруднику ${money(p.share)} (${p.percent}%)`) : null,
      canReview ? reviewButtons(p, review) : null,
      ME.admin && p.status !== "pending" ? h("button", { class: "btn red sm", style: "margin-top:10px", onclick: async () => {
        if (!await confirmAsk("Удалить квитанцию? Она пропадёт из отчётов.")) return;
        try { await api("/api/payments/" + p.id, { method: "DELETE" }); toast("Удалено"); remove(); } catch (e) { toast(e.message, true); }
      } }, icon("trash", "xs"), "Удалить") : null));
  wrap.append(h("div", { class: "swipe-bg" }, h("span", { class: "ok" }, icon("check"), "Принять"), h("span", { class: "no" }, "Отклонить", icon("x"))), card);
  if (canReview) enableSwipe(wrap, card, review, p);
  return wrap;
}

function enableSwipe(wrap, card, review, p) {
  const bg = wrap.firstChild;
  let x0 = null, y0 = null, dx = 0, locked = null, busy = false;
  card.addEventListener("touchstart", (e) => { if (busy) return; x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; dx = 0; locked = null; card.style.transition = "none"; }, { passive: true });
  card.addEventListener("touchmove", (e) => {
    if (x0 == null) return;
    const mx = e.touches[0].clientX - x0, my = e.touches[0].clientY - y0;
    if (locked == null && (Math.abs(mx) > 8 || Math.abs(my) > 8)) locked = Math.abs(mx) > Math.abs(my) ? "x" : "y";
    if (locked !== "x") return;
    dx = mx;
    card.style.transform = `translateX(${dx}px) rotate(${dx / 40}deg)`;
    bg.style.opacity = Math.min(1, Math.abs(dx) / 90);
    bg.style.background = dx > 0 ? "var(--green-bg)" : "var(--red-bg)";
    bg.querySelector(".ok").style.visibility = dx > 0 ? "visible" : "hidden";
    bg.querySelector(".no").style.visibility = dx < 0 ? "visible" : "hidden";
    if (Math.abs(dx) > 110 && !card.dataset.armed) { card.dataset.armed = "1"; haptic("medium"); }
    if (Math.abs(dx) <= 110) delete card.dataset.armed;
  }, { passive: true });
  const reset = () => { card.style.transition = "transform .35s var(--spring)"; card.style.transform = ""; bg.style.opacity = 0; };
  card.addEventListener("touchend", async () => {
    if (x0 == null) return; x0 = null;
    if (locked !== "x" || Math.abs(dx) < 110) return reset();
    const action = dx > 0 ? "ok" : "no";
    if (action === "no" && !await confirmAsk(`Отклонить квитанцию на ${money(p.amount)}?`)) return reset();
    busy = true;
    card.style.transition = "transform .3s var(--ease)";
    card.style.transform = `translateX(${dx > 0 ? 120 : -120}%)`;
    try { await review(action); } catch (e) { busy = false; reset(); toast(e.message, true); }
  });
}

function reviewButtons(p, review) {
  const ok = h("button", { class: "btn green" }, icon("check", "sm"), "Подтвердить");
  const no = h("button", { class: "btn red" }, "Отклонить");
  ok.onclick = () => withLoading(ok, () => review("ok"));
  no.onclick = async () => { if (await confirmAsk(`Отклонить квитанцию на ${money(p.amount)}?`)) withLoading(no, () => review("no")); };
  return h("div", { class: "btns", style: "margin-top:12px" }, no, ok);
}

/* ================= ОТЧЁТЫ ================= */
let reportPeriod = "today";
function Reports() {
  const chips = h("div", { class: "chips" });
  const body = h("div");
  const fetchReport = async () => {
    const token = ++renderToken;
    body.replaceChildren(h("div", { class: "skel", style: "height:130px;margin-bottom:10px" }), h("div", { class: "skel", style: "height:200px" }));
    try {
      const d = await api("/api/reports?period=" + reportPeriod);
      if (token !== renderToken) return;
      const big = h("div", { class: "big count-up" }, money(0));
      body.replaceChildren(...[
        h("div", { class: "card hero" }, h("div", { class: "label" }, ME.admin ? "Оплачено клиентами" : "Ваш заработок"), big,
          h("div", { class: "meta" }, `${plural(d.count, "оплата", "оплаты", "оплат")} · ${d.title}`)),
        h("div", { class: "kpis" },
          ME.admin ? kpi("Сотрудникам", money(d.share), null, "users") : kpi("Оплатили клиенты", money(d.total), null, "wallet"),
          ME.admin ? kpi("Остаток", money(d.rest), "var(--green)", "wallet") : kpi("Оплат", d.count, null, "receipt"),
          ME.admin ? kpi("Новых клиентов", d.new_clients, null, "plus") : null,
          ME.admin && d.count ? kpi("Средний чек", money(d.total / d.count), null, "chart") : null),
        d.series.length > 1 ? h("div", { class: "card", style: "margin-top:10px" },
          h("div", { class: "row between", style: "margin-bottom:8px" }, h("div", { class: "small muted" }, ME.admin ? "Оплаты по дням" : "Заработок по дням"), h("div", { class: "small muted" }, "нажмите на столбик")),
          barChart(d.series.map((s) => ({ label: s.label, value: ME.admin ? s.amount : s.share })))) : null,
        ME.admin && d.workers && d.workers.length ? h("div", null, h("div", { class: "subtitle" }, "Сотрудники"),
          breakdown(d.workers.map((w) => ({ name: w.name, value: w.amount, sub: `${plural(w.count, "оплата", "оплаты", "оплат")} · заработок ${money(w.share)}` })))) : null,
        ME.admin && d.requisites && d.requisites.length ? h("div", null, h("div", { class: "subtitle" }, "Реквизиты"),
          breakdown(d.requisites.map((r) => ({ name: r.name, value: r.amount, sub: plural(r.count, "оплата", "оплаты", "оплат") })))) : null,
        !d.count ? emptyState("📭", "За этот период оплат нет") : null].filter(Boolean));
      setTimeout(() => countUp(big, ME.admin ? d.total : d.share), 100);
    } catch (e) { body.replaceChildren(emptyState("😕", e.message)); }
  };
  const drawChips = () => chips.replaceChildren(...Object.entries(ME.periods).map(([k, t]) =>
    h("div", { class: "chip" + (reportPeriod === k ? " on" : ""), onclick: () => { reportPeriod = k; haptic("select"); drawChips(); fetchReport(); } }, t)));
  drawChips();
  mount(h("div", null, appbar(ME.admin ? "Отчёты" : "Мой доход"), chips, body));
  attachPullToRefresh();
  fetchReport();
}
function kpi(label, value, color, ic) {
  return h("div", { class: "kpi" }, h("div", { class: "row between" }, h("div", { class: "label" }, label), ic ? icon(ic, "sm") : null),
    h("div", { class: "value", style: color ? "color:" + color : null }, value));
}

/* ================= ЕЩЁ / РЕКВИЗИТЫ / КОМАНДА ================= */
function More() {
  const list = h("div", { class: "list settings" },
    h("div", { class: "item", onclick: () => push(RequisitesScreen) }, h("div", { class: "avatar s-work" }, icon("card", "sm")),
      h("div", { class: "grow" }, h("div", { class: "name" }, "Реквизиты"), h("div", { class: "sub" }, "IBAN, получатели, статусы")), icon("right", "sm chev")),
    h("div", { class: "item", onclick: () => push(TeamScreen) }, h("div", { class: "avatar s-paid" }, icon("users", "sm")),
      h("div", { class: "grow" }, h("div", { class: "name" }, "Команда"), h("div", { class: "sub" }, "Сотрудники, проценты, доступ")), icon("right", "sm chev")));
  mount(h("div", null, appbar("Ещё"), stagger(list),
    h("div", { class: "card", style: "margin-top:16px;text-align:center" },
      h("div", { class: "me", style: "margin:0 auto 8px;width:52px;height:52px;border-radius:17px;background:var(--grad);display:grid;place-items:center;font-weight:800;color:#fff" }, initials(ME.user.nick)),
      h("div", { style: "font-weight:700" }, ME.user.nick), h("div", { class: "small muted" }, ME.owner ? "Главный админ" : "Админ"))));
}

function RequisitesScreen(pushed) {
  load(async () => {
    const d = await api("/api/requisites");
    const list = h("div", { class: "list" }, ...d.items.map((r) => {
      const sw = h("button", { class: "switch" + (r.active ? " on" : ""), "aria-label": "Рабочий", onclick: async (e) => {
        e.stopPropagation();
        const next = !r.active; sw.classList.toggle("on", next); haptic("medium");
        try { await api("/api/requisites/" + r.id, { method: "PATCH", body: { active: next } }); r.active = next; card.style.opacity = next ? 1 : .6; toast(next ? "Рабочий" : "Не рабочий"); }
        catch (err) { sw.classList.toggle("on", r.active); toast(err.message, true); }
      } });
      const card = h("div", { class: "card", style: `animation:item-in .4s var(--ease) both;opacity:${r.active ? 1 : .6};transition:opacity .3s` },
        h("div", { class: "row between" }, h("div", { class: "grow" }, h("div", { style: "font-weight:650" }, r.holder), h("div", { class: "mono muted", style: "margin-top:2px" }, r.iban)), ME.admin ? sw : null),
        h("div", { class: "row", style: "margin-top:10px;gap:6px;flex-wrap:wrap" },
          h("button", { class: "copy", onclick: () => copy(r.iban, "IBAN скопирован") }, "IBAN"),
          h("button", { class: "copy", onclick: () => copy(r.holder, "ФИО скопировано") }, "ФИО"),
          h("button", { class: "copy", onclick: () => copy(r.ipn, "ІПН скопирован") }, "ІПН"),
          h("button", { class: "copy", onclick: () => copy(reqText(r), "Реквизиты скопированы") }, icon("copy", "xs")),
          r.active ? h("button", { class: "copy share-btn", onclick: () => shareText(reqText(r)) }, icon("send", "xs")) : null),
        r.comment ? h("div", { class: "hint" }, r.comment) : null,
        ME.admin ? h("div", { class: "row between small muted", style: "margin-top:10px" },
          h("span", null, `Сегодня ${money(r.today)} · всего ${money(r.total)} · ${plural(r.clients, "клиент", "клиента", "клиентов")}`),
          h("button", { class: "copy", style: "color:var(--red)", onclick: async () => {
            if (!await confirmAsk("Удалить реквизит? Клиенты будут отвязаны.")) return;
            try { await api("/api/requisites/" + r.id, { method: "DELETE" }); toast("Удалено"); refreshCurrent(); } catch (e) { toast(e.message, true); }
          } }, icon("trash", "xs"))) : null);
      return card;
    }));
    stagger(list);
    return h("div", null, appbar("Реквизиты"),
      d.items.length ? list : emptyState("💳", ME.admin ? "Добавьте первый реквизит" : "Рабочих реквизитов нет"),
      ME.admin ? h("button", { class: "fab", onclick: requisiteSheet }, icon("plus", "lg")) : null);
  }, pushed);
}

function requisiteSheet() {
  const iban = h("input", { class: "input mono", placeholder: "UA00 0000 0000 0000 0000 0000 000", autocapitalize: "characters" });
  const holder = h("input", { class: "input", placeholder: "Иванов Иван Иванович" });
  const ipn = h("input", { class: "input mono", placeholder: "0000000000", inputmode: "numeric", maxlength: "10" });
  const comment = h("input", { class: "input", placeholder: "Например, банк — необязательно" });
  const ibanHint = h("div", { class: "hint" }, "29 символов, начинается с UA");
  iban.addEventListener("input", () => {
    const v = iban.value.replace(/\s/g, "").toUpperCase();
    ibanHint.textContent = v.length ? (ibanValid(v) ? "✅ IBAN корректный" : `${v.length}/29 · проверьте цифры`) : "29 символов, начинается с UA";
    ibanHint.className = "hint" + (v.length >= 29 && !ibanValid(v) ? " warn" : "");
  });
  const save = h("button", { class: "btn primary block" }, icon("check", "sm"), "Добавить реквизит");
  save.onclick = () => withLoading(save, async () => {
    if (!ibanValid(iban.value.replace(/\s/g, "").toUpperCase())) { shake(iban); throw new Error("IBAN с ошибкой"); }
    const r = await api("/api/requisites", { method: "POST", body: { iban: iban.value, holder: holder.value, ipn: ipn.value, comment: comment.value } });
    closeSheet(true); toast(r.ipn_warning ? "Добавлен. ⚠️ Проверьте ІПН" : "Реквизит добавлен"); refreshCurrent();
  });
  openSheet("Новый реквизит", h("div", null,
    h("div", { class: "field" }, h("label", null, "IBAN"), iban, ibanHint),
    field("ФИО получателя", holder), field("ІПН", ipn, "10 цифр"), field("Комментарий", comment), save));
  setTimeout(() => iban.focus(), 350);
}
function ibanValid(v) {
  if (!/^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$/.test(v) || (v.startsWith("UA") && v.length !== 29)) return false;
  const s = (v.slice(4) + v.slice(0, 4)).replace(/[A-Z]/g, (c) => c.charCodeAt(0) - 55);
  let m = 0; for (const ch of s) m = (m * 10 + Number(ch)) % 97; return m === 1;
}

const STATE = { active: ["✅", "в работе"], waiting: ["🔔", "ждёт подтверждения"], invited: ["⏳", "не открыл бота"], expired: ["⌛", "приглашение истекло"], no_nick: ["⏳", "не указал ник"] };
const ROLE = { owner: "Главный админ", admin: "Админ", worker: "Сотрудник" };
function TeamScreen(pushed) {
  load(async () => {
    const d = await api("/api/team");
    const waiting = d.items.filter((u) => u.state === "waiting");
    const list = h("div", { class: "list" }, ...d.items.map((u) => h("div", { class: "item", onclick: () => memberSheet(u) },
      h("div", { class: "avatar " + (u.state === "active" ? "s-paid" : u.state === "waiting" ? "s-pending" : "") }, initials(u.nick || u.username)),
      h("div", { class: "grow" }, h("div", { class: "name ellipsis" }, u.nick || "@" + u.username),
        h("div", { class: "sub" }, `${ROLE[u.role]} · ${STATE[u.state][0]} ${STATE[u.state][1]}`)),
      h("div", { class: "ring", style: `--p:${u.percent}` }, h("span", null, Math.round(u.percent) + "%")))));
    stagger(list);
    return h("div", null, appbar("Команда", h("button", { class: "icon-btn", onclick: () => inviteSheet(d.can_invite_admin) }, icon("plus"))),
      waiting.length ? h("div", { class: "banner", onclick: () => memberSheet(waiting[0]) }, icon("bell", "sm"), h("div", { class: "grow" }, `Ждут подтверждения: ${waiting.length}`), icon("right", "sm")) : null,
      list);
  }, pushed);
}

function memberSheet(u) {
  const parts = [h("div", { class: "detail-head" }, h("div", { class: "avatar lg s-paid", style: "margin:0 auto" }, initials(u.nick || u.username)),
    h("div", { class: "name" }, u.nick || "@" + u.username), h("div", { class: "phone" }, `${ROLE[u.role]}${u.username ? " · @" + u.username : ""}`),
    h("div", { class: "small muted", style: "margin-top:4px" }, `${STATE[u.state][0]} ${STATE[u.state][1]} · ${plural(u.clients, "клиент", "клиента", "клиентов")}, в работе ${u.work}`))];
  if (u.username && tg) parts.push(h("button", { class: "btn block ghost", style: "margin-top:12px", onclick: () => tg.openTelegramLink("https://t.me/" + u.username) }, icon("msg", "sm"), "Написать"));
  if (u.state === "waiting" && u.can_approve) {
    const ok = h("button", { class: "btn green" }, icon("check", "sm"), "Открыть доступ"), no = h("button", { class: "btn red" }, "Отклонить");
    ok.onclick = () => withLoading(ok, async () => { await api(`/api/team/${u.id}/approve`, { method: "POST", body: { ok: true } }); closeSheet(); toast("Доступ открыт"); refreshCurrent(); });
    no.onclick = async () => { if (await confirmAsk("Отклонить запрос доступа?")) withLoading(no, async () => { await api(`/api/team/${u.id}/approve`, { method: "POST", body: { ok: false } }); closeSheet(); toast("Отклонено"); refreshCurrent(); }); };
    parts.push(h("div", { class: "hint", style: "text-align:center;margin:12px 0 8px" }, "Убедитесь, что это нужный человек"), h("div", { class: "btns" }, no, ok));
  }
  if (u.can_percent) {
    const val = h("div", { style: "font-size:36px;font-weight:800;text-align:center;letter-spacing:-.02em" }, u.percent + "%");
    const range = h("input", { type: "range", class: "range", min: "0", max: "100", step: "1", value: String(u.percent) });
    let last = u.percent;
    range.addEventListener("input", () => { val.textContent = range.value + "%"; if (range.value % 5 === 0 && range.value != last) { haptic("select"); last = range.value; } });
    const presets = h("div", { class: "chips", style: "justify-content:center" }, ...[30, 40, 50, 60].map((p) => h("div", { class: "chip", onclick: () => { range.value = p; val.textContent = p + "%"; haptic("select"); } }, p + "%")));
    const save = h("button", { class: "btn primary block", style: "margin-top:8px" }, "Сохранить процент");
    save.onclick = () => withLoading(save, async () => { await api(`/api/team/${u.id}`, { method: "PATCH", body: { percent: Number(range.value) } }); closeSheet(); toast(`Процент: ${range.value}%`); refreshCurrent(); });
    parts.push(h("div", { class: "subtitle" }, "Процент от оплат"), val, range, presets, save, h("div", { class: "hint", style: "text-align:center" }, "Действует для новых оплат"));
  }
  if (u.can_manage) {
    const del = h("button", { class: "btn red block", style: "margin-top:16px" }, icon("trash", "sm"), "Удалить из команды");
    del.onclick = async () => { if (await confirmAsk(`Удалить ${u.nick || "@" + u.username}? Доступ к боту закроется.`)) withLoading(del, async () => { await api("/api/team/" + u.id, { method: "DELETE" }); closeSheet(); toast("Удалено"); refreshCurrent(); }); };
    parts.push(del);
  }
  openSheet(null, h("div", null, ...parts));
}

function inviteSheet(canAdmin) {
  let role = "worker";
  const user = h("input", { class: "input", placeholder: "@username", autocapitalize: "none", autocomplete: "off" });
  const roles = h("div", { class: "options" });
  const draw = () => roles.replaceChildren(...[["worker", "Сотрудник", "Свои клиенты и квитанции"], ...(canAdmin ? [["admin", "Админ", "Всё, кроме управления админами"]] : [])].map(([k, t, s]) =>
    h("div", { class: "opt" + (role === k ? " on" : ""), onclick: () => { role = k; haptic("select"); draw(); } }, h("span", { class: "radio" }), h("div", { class: "grow" }, h("div", null, t), h("div", { class: "small muted" }, s)))));
  draw();
  const save = h("button", { class: "btn primary block", style: "margin-top:6px" }, icon("send", "sm"), "Пригласить");
  save.onclick = () => withLoading(save, async () => {
    await api("/api/team", { method: "POST", body: { username: user.value, role } });
    closeSheet(); toast("Приглашение создано"); refreshCurrent();
    if (tg) tg.showAlert(`Попросите ${user.value.startsWith("@") ? user.value : "@" + user.value} открыть бота и нажать /start. Потом подтвердите доступ здесь.`);
  });
  openSheet("Пригласить в команду", h("div", null, field("Username в Telegram", user), canAdmin ? field("Роль", roles) : null, save));
  setTimeout(() => user.focus(), 350);
}

/* ================= СТАРТ ================= */
async function start() {
  if (tg) {
    tg.ready(); tg.expand();
    try { tg.setHeaderColor("#0b0d12"); tg.setBackgroundColor("#0b0d12"); tg.setBottomBarColor && tg.setBottomBarColor("#0b0d12"); } catch (_) {}
    try { tg.disableVerticalSwipes && tg.disableVerticalSwipes(); } catch (_) {}
    tg.BackButton.onClick(back);
  }
  if (!tg || !tg.initData) { mount(h("div", null, emptyState("🔒", "Откройте приложение через бота в Telegram"))); return; }
  if (!API) await refreshApiUrl();
  try { ME = await api("/api/me"); }
  catch (e) {
    mount(h("div", null, emptyState("😕", e.message, h("button", { class: "btn ghost", style: "margin-top:14px", onclick: () => location.reload() }, icon("refresh", "sm"), "Повторить"))));
    return;
  }
  go("home");
}
start();
