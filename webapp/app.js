/* CRM — мини-приложение Telegram. Без сборки и зависимостей. */
"use strict";
const tg = window.Telegram && window.Telegram.WebApp;
const $app = document.getElementById("app");
const $tabs = document.getElementById("tabs");
const $sheetRoot = document.getElementById("sheet-root");
const $toast = document.getElementById("toast-root");

/* ---------- утилиты ---------- */
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style") el.style.cssText = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "html") throw new Error("no html");
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
  return (kop < 0 ? "−" : "") + hr.toLocaleString("ru-RU").replace(/,/g, " ") + (k ? "," + String(k).padStart(2, "0") : "") + " ₴";
};
const TZ = "Asia/Yerevan";
const dt = (ts) => ts ? new Date(ts * 1000).toLocaleString("ru-RU", { timeZone: TZ, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).replace(",", "") : "—";
const initials = (name) => (name || "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
const haptic = (type = "light") => { try { if (type === "ok" || type === "error" || type === "warning") tg.HapticFeedback.notificationOccurred(type === "ok" ? "success" : type); else if (type === "select") tg.HapticFeedback.selectionChanged(); else tg.HapticFeedback.impactOccurred(type); } catch (_) {} };
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

function toast(text, err = false) {
  const el = h("div", { class: "toast" + (err ? " err" : "") }, text);
  $toast.append(el);
  haptic(err ? "error" : "ok");
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 300); }, 2600);
}

async function copy(text, what = "Скопировано") {
  try { await navigator.clipboard.writeText(text); }
  catch (_) { const t = h("textarea", { style: "position:fixed;opacity:0" }); t.value = text; document.body.append(t); t.select(); document.execCommand("copy"); t.remove(); }
  toast("📋 " + what);
}

function countUp(el, to, fmt = money, ms = 700) {
  const start = performance.now();
  const step = (now) => {
    const p = Math.min(1, (now - start) / ms), e = 1 - Math.pow(1 - p, 3);
    el.textContent = fmt(to * e);
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

/* ---------- API ---------- */
const params = new URLSearchParams(location.search);
let API = params.get("api") || "";
try { if (!API) API = localStorage.getItem("crm_api") || ""; } catch (_) {}

async function refreshApiUrl() {
  // Резерв: бот публикует актуальный адрес в api.json (ветка bot-data этого репозитория)
  const owner = location.hostname.split(".")[0];
  const repo = location.pathname.split("/").filter(Boolean)[0];
  if (!owner || !repo) return false;
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
  try {
    res = await fetch(API + path, { method, headers, body: payload });
  } catch (e) {
    if (!retried && await refreshApiUrl()) return api(path, { method, body, form }, true);
    throw new Error("Нет связи с сервером. Попробуйте позже");
  }
  if (path.endsWith("/file")) { if (!res.ok) throw new Error("Файл недоступен"); return res.blob(); }
  let data = {};
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) throw new Error(data.error || "Ошибка " + res.status);
  try { localStorage.setItem("crm_api", API); } catch (_) {}
  return data;
}

/* ---------- навигация ---------- */
let ME = null;
const stack = [];          // открытые вложенные экраны
let currentTab = "home";
let renderToken = 0;

const TABS_ADMIN = [["home", "🏠", "Главная"], ["clients", "👥", "Клиенты"], ["receipts", "🧾", "Квитанции"], ["reports", "📊", "Отчёты"], ["more", "⚙️", "Ещё"]];
const TABS_WORKER = [["home", "🏠", "Главная"], ["clients", "👥", "Клиенты"], ["receipts", "🧾", "Квитанции"], ["reports", "📊", "Доход"], ["reqs", "💳", "Реквизиты"]];

function renderTabs(badge = 0) {
  $tabs.replaceChildren(...(ME.admin ? TABS_ADMIN : TABS_WORKER).map(([id, ic, tx]) =>
    h("button", { class: "tab" + (id === currentTab ? " on" : ""), onclick: () => go(id) },
      h("span", { class: "ic" }, ic), h("span", { class: "tx" }, tx),
      id === "receipts" && badge ? h("span", { class: "count-badge" }, badge) : null)));
  $tabs.classList.remove("hidden");
}

function mount(node, push = false) {
  node.classList.add("screen");
  if (push) node.classList.add("push");
  $app.replaceChildren(node);
  window.scrollTo(0, 0);
}

function updateBack() {
  if (!tg) return;
  if (stack.length) tg.BackButton.show(); else tg.BackButton.hide();
}

function go(tab) {
  if (tab !== currentTab) haptic("select");
  currentTab = tab; stack.length = 0; updateBack(); closeSheet();
  renderTabs(window.__badge || 0);
  ({ home: Home, clients: Clients, receipts: Receipts, reports: Reports, more: More, reqs: Requisites, team: Team })[tab]();
}

function push(fn) { stack.push(fn); updateBack(); fn(true); }
function back() {
  if ($sheetRoot.childElementCount) return closeSheet();
  stack.pop(); updateBack();
  if (stack.length) stack[stack.length - 1](true); else go(currentTab);
}
function refreshCurrent() { if (stack.length) stack[stack.length - 1](true); else go(currentTab); }

function skeleton(n = 5) {
  return h("div", null, h("div", { class: "skel", style: "height:30px;width:45%;margin:8px 2px 16px" }),
    Array.from({ length: n }, () => h("div", { class: "skel skel-item" })));
}
function emptyState(ic, text, extra) { return h("div", { class: "empty" }, h("div", { class: "ic" }, ic), h("div", null, text), extra || null); }
function stagger(list) { [...list.children].forEach((el, i) => el.style.animationDelay = Math.min(i, 12) * 35 + "ms"); return list; }

async function load(fn, wrap) {
  const token = ++renderToken;
  mount(skeleton(), !!wrap);
  try {
    const node = await fn();
    if (token === renderToken) mount(node, !!wrap);
  } catch (e) {
    if (token === renderToken) mount(h("div", null, emptyState("😕", e.message, h("button", { class: "btn ghost", style: "margin-top:14px", onclick: refreshCurrent }, "Повторить"))));
  }
}

/* ---------- шторка ---------- */
function openSheet(title, content) {
  closeSheet(true);
  const bd = h("div", { class: "backdrop", onclick: () => closeSheet() });
  const sh = h("div", { class: "sheet" }, h("div", { class: "grab" }), title ? h("h3", null, title) : null, content);
  $sheetRoot.append(bd, sh);
  if (tg) tg.BackButton.show();
  haptic("light");
  return sh;
}
function closeSheet(instant = false) {
  const kids = [...$sheetRoot.children];
  if (!kids.length) return;
  if (instant) { $sheetRoot.replaceChildren(); return; }
  kids.forEach((k) => k.classList.add("out"));
  setTimeout(() => { kids.forEach((k) => k.remove()); updateBack(); }, 230);
}
function confirmAsk(text) {
  return new Promise((res) => { if (tg && tg.showConfirm) tg.showConfirm(text, res); else res(confirm(text)); });
}
async function withLoading(btn, fn) {
  if (btn.classList.contains("loading")) return;
  btn.classList.add("loading"); btn.disabled = true;
  try { await fn(); } catch (e) { toast(e.message, true); }
  finally { btn.classList.remove("loading"); btn.disabled = false; }
}
function field(label, input, hint) { return h("div", { class: "field" }, h("label", null, label), input, hint ? h("div", { class: "hint" }, hint) : null); }

/* ================= ГЛАВНАЯ ================= */
function greeting() {
  const hr = Number(new Date().toLocaleString("en-US", { timeZone: TZ, hour: "numeric", hour12: false }));
  return hr < 5 ? "Доброй ночи" : hr < 12 ? "Доброе утро" : hr < 18 ? "Добрый день" : "Добрый вечер";
}

function Home() {
  load(async () => {
    const d = await api("/api/dashboard");
    window.__badge = ME.admin ? d.pending.count : 0; renderTabs(window.__badge);
    const big = h("div", { class: "big count-up" }, money(0));
    const node = h("div", null,
      h("div", { class: "title" }, `${greeting()}, ${ME.user.nick} 👋`),
      ME.admin && d.waiting_access ? h("div", { class: "banner", onclick: () => { currentTab = "more"; renderTabs(window.__badge); push(TeamScreen); } },
        "🔔", h("div", { class: "grow" }, `Ждут подтверждения доступа: ${d.waiting_access}`), "›") : null,
      h("div", { class: "card hero" },
        h("div", { class: "label" }, ME.admin ? "Оплачено сегодня" : "Заработано сегодня"), big,
        h("div", { class: "meta" }, ME.admin ? `${d.today.count} опл. · остаток ${money(d.today.rest)}` : `${d.today.count} опл. · клиенты оплатили ${money(d.today.amount)}`)),
      h("div", { class: "kpis" },
        h("div", { class: "kpi click", onclick: () => go("receipts") }, h("div", { class: "label" }, h("span", { class: "dot", style: "background:var(--yellow)" }), "На проверке"),
          h("div", { class: "value" }, d.pending.count), h("div", { class: "small muted" }, money(d.pending.amount))),
        h("div", { class: "kpi click", onclick: () => go("clients") }, h("div", { class: "label" }, h("span", { class: "dot", style: "background:var(--blue)" }), "В работе"),
          h("div", { class: "value" }, d.clients.work), h("div", { class: "small muted" }, `всего ${d.clients.total}`))),
      h("div", { class: "quick" },
        h("div", { class: "q", onclick: () => newClientSheet() }, h("div", { class: "ic" }, "➕"), h("div", { class: "tx" }, "Клиент")),
        h("div", { class: "q", onclick: () => go("receipts") }, h("div", { class: "ic" }, "🧾"), h("div", { class: "tx" }, "Квитанции"),
          d.pending.count && ME.admin ? h("span", { class: "count-badge" }, d.pending.count) : null),
        h("div", { class: "q", onclick: () => go(ME.admin ? "reports" : "reports") }, h("div", { class: "ic" }, "📊"), h("div", { class: "tx" }, ME.admin ? "Отчёт" : "Доход"))));
    setTimeout(() => countUp(big, ME.admin ? d.today.amount : d.today.share), 120);
    return node;
  });
}

/* ================= КЛИЕНТЫ ================= */
const ST = { work: "В работе", paid: "Оплачено", lost: "Слив" };
const ST_IC = { work: "🔄", paid: "✅", lost: "❌" };
let clientFilter = { status: "", q: "" };

function Clients() {
  const listBox = h("div", { class: "list" });
  const chipsBox = h("div", { class: "chips" });
  const input = h("input", { placeholder: "Имя или телефон", value: clientFilter.q, type: "search", enterkeyhint: "search" });
  const fetchList = async () => {
    const token = ++renderToken;
    listBox.replaceChildren(...Array.from({ length: 5 }, () => h("div", { class: "skel skel-item" })));
    try {
      const qs = new URLSearchParams({ status: clientFilter.status, q: clientFilter.q });
      const d = await api("/api/clients?" + qs);
      if (token !== renderToken) return;
      const total = Object.values(d.counts).reduce((a, b) => a + b, 0);
      chipsBox.replaceChildren(...[["", "Все", total], ...Object.keys(ST).map((k) => [k, ST_IC[k] + " " + ST[k], d.counts[k] || 0])].map(([k, t, n]) =>
        h("div", { class: "chip" + (clientFilter.status === k ? " on" : ""), onclick: () => { haptic("select"); clientFilter.status = k; fetchList(); } }, t, h("span", { class: "n" }, n))));
      if (!d.items.length) {
        listBox.replaceChildren(emptyState(clientFilter.q ? "🔍" : "👥", clientFilter.q ? "Ничего не найдено" : "Пока пусто — добавьте первого клиента"));
        return;
      }
      listBox.replaceChildren(...d.items.map((c) => h("div", { class: "item", onclick: () => push((p) => ClientScreen(c.id, p)) },
        h("div", { class: "avatar s-" + c.status }, initials(c.name)),
        h("div", { class: "grow" }, h("div", { class: "name ellipsis" }, c.name),
          h("div", { class: "sub ellipsis" }, [c.phone, ME.admin && c.worker ? "👷 " + c.worker : null].filter(Boolean).join(" · "))),
        c.paid ? h("div", { class: "right", style: "color:var(--green)" }, money(c.paid)) : h("span", { class: "chev" }, "›"))));
      stagger(listBox);
    } catch (e) { listBox.replaceChildren(emptyState("😕", e.message)); }
  };
  input.addEventListener("input", debounce(() => { clientFilter.q = input.value.trim(); fetchList(); }, 300));
  mount(h("div", null,
    h("div", { class: "title" }, ME.admin ? "Клиенты" : "Мои клиенты"),
    h("div", { class: "search" }, "🔍", input), chipsBox, listBox,
    h("button", { class: "fab", onclick: () => newClientSheet() }, "+")));
  fetchList();
}

async function newClientSheet() {
  let team = [];
  if (ME.admin) { try { team = (await api("/api/team")).items.filter((u) => u.state === "active"); } catch (_) {} }
  const name = h("input", { class: "input", placeholder: "Иван Петров", autocomplete: "off" });
  const phone = h("input", { class: "input", placeholder: "+380 67 123 45 67", type: "tel", inputmode: "tel" });
  const comment = h("textarea", { class: "input", placeholder: "Маршрут, дата поездки, детали — необязательно" });
  let worker = ME.user.id;
  const workerBox = ME.admin && team.length > 1 ? h("div", { class: "options" }) : null;
  const drawWorkers = () => workerBox && workerBox.replaceChildren(...team.map((u) => h("div", { class: "opt" + (u.id === worker ? " on" : ""), onclick: () => { worker = u.id; haptic("select"); drawWorkers(); } },
    h("span", { class: "radio" }), h("div", { class: "grow" }, u.id === ME.user.id ? "Себе" : u.nick), h("span", { class: "muted small" }, u.percent + "%"))));
  drawWorkers();
  const save = h("button", { class: "btn primary block", style: "margin-top:6px" }, "Добавить клиента");
  save.onclick = () => withLoading(save, async () => {
    if (!name.value.trim()) { name.classList.add("err"); setTimeout(() => name.classList.remove("err"), 400); throw new Error("Укажите имя"); }
    if (phone.value.replace(/\D/g, "").length < 7) { phone.classList.add("err"); setTimeout(() => phone.classList.remove("err"), 400); throw new Error("Проверьте телефон"); }
    const r = await api("/api/clients", { method: "POST", body: { name: name.value, phone: phone.value, comment: comment.value, worker_id: worker } });
    closeSheet(); toast("✅ Клиент добавлен");
    if (currentTab !== "clients") { currentTab = "clients"; renderTabs(window.__badge); }
    stack.length = 0; push((p) => ClientScreen(r.id, p));
  });
  openSheet("Новый клиент", h("div", null, field("Имя", name), field("Телефон", phone), field("Комментарий", comment),
    workerBox ? field("Кому отдать", workerBox) : null, save));
  setTimeout(() => name.focus(), 350);
}

function ClientScreen(id) {
  load(async () => {
    const c = await api("/api/clients/" + id);
    const seg = h("div", { class: "seg" });
    const ind = h("div", { class: "ind" });
    const drawSeg = () => {
      const keys = Object.keys(ST);
      seg.replaceChildren(ind, ...keys.map((k) => h("button", { class: (c.status === k ? "on " : "") + k, onclick: async () => {
        if (c.status === k) return;
        const prev = c.status; c.status = k; drawSeg(); haptic("medium");
        try { await api("/api/clients/" + id, { method: "PATCH", body: { status: k } }); toast(ST_IC[k] + " " + ST[k]); }
        catch (e) { c.status = prev; drawSeg(); toast(e.message, true); }
      } }, ST_IC[k] + " " + ST[k])));
      const i = keys.indexOf(c.status);
      ind.className = "ind " + c.status;
      ind.style.width = `calc((100% - 8px) / ${keys.length})`;
      ind.style.left = `calc(4px + (100% - 8px) / ${keys.length} * ${i})`;
    };
    drawSeg();

    const req = c.requisite;
    const reqCard = h("div", { class: "card" },
      h("div", { class: "row between" }, h("b", null, "💳 Реквизит для оплаты"),
        h("button", { class: "copy", onclick: () => pickRequisite(c) }, req ? "Сменить" : "Выбрать")),
      req ? h("div", null,
        ...[["IBAN", req.iban], ["Получатель", req.holder], ["ІПН", req.ipn]].map(([k, v]) =>
          h("div", { class: "kv" }, h("div", { class: "grow" }, h("div", { class: "k" }, k), h("div", { class: "mono" }, v)),
            h("button", { class: "copy", onclick: () => copy(v, k + " скопирован") }, "Копировать"))),
        h("button", { class: "btn block sm", style: "margin-top:8px", onclick: () => copy(`IBAN: ${req.iban}\nОтримувач: ${req.holder}\nІПН: ${req.ipn}`, "Реквизиты скопированы") }, "📋 Скопировать всё для клиента"),
        !req.active ? h("div", { class: "hint warn" }, "⚠️ Этот реквизит сейчас не рабочий — выберите другой") : null)
        : h("div", { class: "hint" }, "Выберите, куда клиент будет платить"));

    const paid = c.payments.filter((p) => p.status === "confirmed").reduce((a, p) => a + p.amount, 0);
    const pays = h("div", { class: "list" }, ...c.payments.map((p) => paymentRow(p)));
    const commentsBox = h("div", { class: "timeline" }, ...c.comments.slice().reverse().map(commentNode));
    const cInput = h("input", { class: "input", placeholder: "Написать комментарий…", enterkeyhint: "send" });
    const cSend = h("button", { class: "btn primary" }, "➤");
    const sendComment = () => withLoading(cSend, async () => {
      if (!cInput.value.trim()) return;
      const r = await api(`/api/clients/${id}/comments`, { method: "POST", body: { text: cInput.value } });
      cInput.value = ""; commentsBox.append(commentNode(r)); haptic("light");
    });
    cSend.onclick = sendComment;
    cInput.addEventListener("keydown", (e) => { if (e.key === "Enter") sendComment(); });

    return h("div", null,
      h("div", { class: "detail-head" },
        h("div", { class: "avatar lg s-" + c.status, style: "margin:0 auto" }, initials(c.name)),
        h("div", { class: "name" }, c.name),
        h("div", { class: "phone" }, c.phone || "—")),
      h("div", { class: "actions" },
        c.phone ? h("a", { class: "act", href: "tel:" + c.phone.replace(/[^\d+]/g, "") }, h("span", { class: "ic" }, "📞"), "Позвонить") : null,
        c.phone ? h("div", { class: "act", onclick: () => copy(c.phone, "Телефон скопирован") }, h("span", { class: "ic" }, "📋"), "Телефон") : null,
        h("div", { class: "act", onclick: () => receiptSheet(c) }, h("span", { class: "ic" }, "🧾"), "Квитанция"),
        c.can_manage ? h("div", { class: "act", onclick: () => clientMenu(c) }, h("span", { class: "ic" }, "⋯"), "Ещё") : null),
      seg,
      h("div", { class: "card" },
        h("div", { class: "kv" }, h("div", { class: "k" }, "Сотрудник"), h("div", { class: "v" }, c.worker ? c.worker.nick : "—")),
        h("div", { class: "kv" }, h("div", { class: "k" }, "Оплачено"), h("div", { class: "v", style: "color:var(--green)" }, money(paid))),
        h("div", { class: "kv" }, h("div", { class: "k" }, "Создан"), h("div", { class: "v" }, dt(c.created_at)))),
      reqCard,
      h("div", { class: "row between subtitle" }, h("span", null, "Оплаты"), h("button", { class: "copy", onclick: () => receiptSheet(c) }, "+ Квитанция")),
      c.payments.length ? pays : h("div", { class: "hint", style: "margin:0 4px" }, "Оплат пока нет"),
      h("div", { class: "subtitle" }, "Комментарии"),
      c.comments.length ? commentsBox : (commentsBox.append(h("div", { class: "hint" }, "Пока нет комментариев")), commentsBox),
      h("div", { class: "comment-box" }, cInput, cSend));
  }, true);
}

function commentNode(x) {
  return h("div", { class: "comment" }, h("div", { class: "who" }, `${x.author || "—"} · ${dt(x.at)}`), x.text);
}

function paymentRow(p) {
  const st = { pending: ["⏳", "На проверке"], confirmed: ["✅", "Подтверждена"], rejected: ["❌", "Отклонена"] }[p.status];
  return h("div", { class: "item", onclick: () => viewFile(p) },
    h("div", { class: "avatar s-" + p.status }, st[0]),
    h("div", { class: "grow" }, h("div", { class: "name" }, money(p.amount)), h("div", { class: "sub" }, `${st[1]} · ${dt(p.submitted_at)}`)),
    p.share != null ? h("div", { class: "right small muted" }, "💵 " + money(p.share)) : h("span", { class: "chev" }, "›"));
}

async function pickRequisite(c) {
  const d = await api("/api/requisites").catch((e) => toast(e.message, true));
  if (!d) return;
  const active = d.items.filter((r) => r.active);
  const box = h("div", { class: "options" }, ...active.map((r) => h("div", { class: "opt" + (c.requisite && c.requisite.id === r.id ? " on" : ""), onclick: async () => {
    try { await api("/api/clients/" + c.id, { method: "PATCH", body: { requisite_id: r.id } }); closeSheet(); toast("✅ Реквизит выбран"); refreshCurrent(); }
    catch (e) { toast(e.message, true); }
  } }, h("span", { class: "radio" }), h("div", { class: "grow" }, h("div", { class: "mono" }, "…" + r.iban.slice(-6)), h("div", { class: "small muted" }, r.holder)))));
  openSheet("Реквизит для клиента", active.length ? h("div", null, box,
    c.requisite ? h("button", { class: "btn red block", style: "margin-top:10px", onclick: async () => {
      await api("/api/clients/" + c.id, { method: "PATCH", body: { requisite_id: null } }); closeSheet(); refreshCurrent();
    } }, "Отвязать реквизит") : null) : emptyState("💳", "Нет рабочих реквизитов"));
}

async function clientMenu(c) {
  let team = [];
  try { team = (await api("/api/team")).items.filter((u) => u.state === "active"); } catch (_) {}
  const box = h("div", { class: "options" }, ...team.map((u) => h("div", { class: "opt" + (c.worker && c.worker.id === u.id ? " on" : ""), onclick: async () => {
    try { await api("/api/clients/" + c.id, { method: "PATCH", body: { worker_id: u.id } }); closeSheet(); toast("✅ Передан: " + u.nick); refreshCurrent(); }
    catch (e) { toast(e.message, true); }
  } }, h("span", { class: "radio" }), h("div", { class: "grow" }, u.nick), h("span", { class: "small muted" }, u.percent + "%"))));
  const del = h("button", { class: "btn red block", style: "margin-top:14px" }, "🗑 Удалить клиента");
  del.onclick = async () => {
    if (!await confirmAsk(`Удалить клиента «${c.name}»? Оплаты останутся в отчётах.`)) return;
    withLoading(del, async () => { await api("/api/clients/" + c.id, { method: "DELETE" }); closeSheet(); toast("🗑 Удалено"); back(); });
  };
  openSheet("Передать сотруднику", h("div", null, box, del));
}

/* ---------- новая квитанция ---------- */
async function receiptSheet(c) {
  let file = null, reqId = c.requisite ? c.requisite.id : null;
  const preview = h("div");
  const fileInput = h("input", { type: "file", accept: "image/*,application/pdf", class: "hidden" });
  const drop = h("div", { class: "upload", onclick: () => fileInput.click() }, h("div", { class: "ic" }, "📎"), h("div", null, "Выберите фото или файл квитанции"));
  fileInput.onchange = () => {
    file = fileInput.files[0]; if (!file) return;
    if (file.size > 20 * 1024 * 1024) { file = null; return toast("Файл больше 20 МБ", true); }
    haptic("light");
    preview.replaceChildren(file.type.startsWith("image/") ? h("img", { class: "preview", src: URL.createObjectURL(file) }) : h("div", { class: "pdf" }, "📄"),
      h("div", { class: "hint", style: "text-align:center" }, file.name, " · ", h("a", { style: "color:var(--accent2)", onclick: () => fileInput.click() }, "заменить")));
    drop.classList.add("hidden");
  };
  const amount = h("input", { class: "input amount-input", placeholder: "0 ₴", inputmode: "decimal" });
  let reqBox = null;
  if (!c.requisite) {
    const d = await api("/api/requisites").catch(() => ({ items: [] }));
    const active = d.items.filter((r) => r.active);
    if (active.length) {
      reqBox = h("div", { class: "options" });
      const draw = () => reqBox.replaceChildren(...active.map((r) => h("div", { class: "opt" + (reqId === r.id ? " on" : ""), onclick: () => { reqId = r.id; haptic("select"); draw(); } },
        h("span", { class: "radio" }), h("div", { class: "grow" }, h("span", { class: "mono" }, "…" + r.iban.slice(-6)), " ", h("span", { class: "small muted" }, r.holder)))));
      draw();
    }
  }
  const send = h("button", { class: "btn primary block", style: "margin-top:6px" }, "Отправить на проверку");
  send.onclick = () => withLoading(send, async () => {
    if (!file) { drop.classList.add("err"); throw new Error("Добавьте фото квитанции"); }
    const sum = amount.value.replace(/\s/g, "").replace(",", ".");
    if (!/^\d{1,9}(\.\d{1,2})?$/.test(sum) || Number(sum) <= 0) { amount.classList.add("err"); setTimeout(() => amount.classList.remove("err"), 400); throw new Error("Проверьте сумму"); }
    if (reqBox && !reqId) throw new Error("Выберите реквизит");
    const fd = new FormData(); fd.append("file", file); fd.append("amount", sum); if (reqId && !c.requisite) fd.append("requisite_id", reqId);
    await api(`/api/clients/${c.id}/payments`, { method: "POST", form: fd });
    closeSheet(); toast(ME.admin ? "✅ Квитанция добавлена" : "✅ Отправлено на проверку"); refreshCurrent();
  });
  openSheet("Квитанция · " + c.name, h("div", null, fileInput, drop, preview, h("div", { style: "height:12px" }),
    field("Сумма, ₴", amount), reqBox ? field("На какой реквизит пришли деньги", reqBox) : null, send));
}

async function viewFile(p) {
  try {
    const blob = await api(`/api/payments/${p.id}/file`);
    const url = URL.createObjectURL(blob);
    if (blob.type === "application/pdf") { window.open(url, "_blank"); return; }
    const v = h("div", { class: "viewer", onclick: () => { v.remove(); URL.revokeObjectURL(url); } }, h("img", { src: url }));
    document.body.append(v); haptic("light");
  } catch (e) { toast(e.message, true); }
}

/* ================= КВИТАНЦИИ ================= */
let receiptTab = "pending";
function Receipts() {
  const box = h("div");
  const tabs = h("div", { class: "seg" });
  const ind = h("div", { class: "ind" });
  const keys = [["pending", "⏳ На проверке"], ["confirmed", "✅ Приняты"], ["rejected", "❌ Отклонены"]];
  const drawTabs = () => {
    tabs.replaceChildren(ind, ...keys.map(([k, t]) => h("button", { class: receiptTab === k ? "on" : "", onclick: () => { receiptTab = k; haptic("select"); drawTabs(); fetchList(); } }, t)));
    const i = keys.findIndex(([k]) => k === receiptTab);
    ind.style.width = "calc((100% - 8px) / 3)"; ind.style.left = `calc(4px + (100% - 8px) / 3 * ${i})`;
  };
  const fetchList = async () => {
    const token = ++renderToken;
    box.replaceChildren(...Array.from({ length: 3 }, () => h("div", { class: "skel", style: "height:260px;margin-bottom:10px" })));
    try {
      const d = await api("/api/payments?status=" + receiptTab);
      if (token !== renderToken) return;
      if (receiptTab === "pending" && ME.admin) { window.__badge = d.items.length; renderTabs(window.__badge); }
      if (!d.items.length) { box.replaceChildren(emptyState(receiptTab === "pending" ? "✨" : "🗂", receiptTab === "pending" ? "Всё проверено" : "Пока пусто")); return; }
      box.replaceChildren(...d.items.map((p) => receiptCard(p, box)));
      [...box.children].forEach((el, i) => el.style.animationDelay = Math.min(i, 8) * 50 + "ms");
    } catch (e) { box.replaceChildren(emptyState("😕", e.message)); }
  };
  drawTabs();
  mount(h("div", null, h("div", { class: "title" }, "Квитанции"), tabs, box));
  fetchList();
}

function receiptCard(p, box) {
  const img = h("div", { class: "img skel" });
  (async () => {
    try {
      const blob = await api(`/api/payments/${p.id}/file`);
      if (blob.type === "application/pdf") img.replaceWith(h("div", { class: "pdf", onclick: () => viewFile(p) }, "📄"));
      else {
        const el = h("img", { class: "img", src: URL.createObjectURL(blob), alt: "", onclick: () => viewFile(p) });
        el.onerror = () => el.replaceWith(h("div", { class: "pdf", onclick: () => viewFile(p) }, "🖼"));
        img.replaceWith(el);
      }
    } catch (_) { img.replaceWith(h("div", { class: "pdf" }, "🖼")); }
  })();
  const card = h("div", { class: "card receipt" }, img,
    h("div", { class: "body" },
      h("div", { class: "row between" }, h("div", { class: "amount" }, money(p.amount)),
        h("span", { class: "badge s-" + p.status }, { pending: "⏳ На проверке", confirmed: "✅ Принята", rejected: "❌ Отклонена" }[p.status])),
      h("div", { class: "row", style: "margin-top:8px;cursor:pointer", onclick: () => p.client_id && push((x) => ClientScreen(p.client_id, x)) },
        h("div", { class: "grow" }, h("div", { class: "name" }, "👤 ", p.client_name || "—"), h("div", { class: "small muted" }, [p.phone, p.requisite ? "💳 …" + p.requisite.split(" ")[0].slice(-6) : null].filter(Boolean).join(" · "))),
        p.client_id ? h("span", { class: "chev" }, "›") : null),
      h("div", { class: "small muted", style: "margin-top:6px" }, `👷 ${p.worker || "—"} · ${dt(p.submitted_at)}`, p.reviewer ? ` · проверил ${p.reviewer}` : ""),
      p.share != null ? h("div", { class: "small", style: "margin-top:4px;color:var(--green)" }, `💵 Сотруднику ${money(p.share)} (${p.percent}%)`) : null,
      ME.admin && p.status === "pending" ? reviewButtons(p, () => { card.classList.add("gone"); setTimeout(() => { card.remove(); if (!box.children.length) box.replaceChildren(emptyState("✨", "Всё проверено")); }, 450); }) : null,
      ME.admin && p.status !== "pending" ? h("button", { class: "btn red sm", style: "margin-top:10px", onclick: async () => {
        if (!await confirmAsk("Удалить квитанцию? Она пропадёт из отчётов.")) return;
        try { await api("/api/payments/" + p.id, { method: "DELETE" }); card.classList.add("gone"); setTimeout(() => card.remove(), 450); toast("🗑 Удалено"); } catch (e) { toast(e.message, true); }
      } }, "🗑 Удалить") : null));
  return card;
}

function reviewButtons(p, onDone) {
  const ok = h("button", { class: "btn green" }, "✅ Подтвердить");
  const no = h("button", { class: "btn red" }, "Отклонить");
  const act = (btn, action) => withLoading(btn, async () => {
    await api(`/api/payments/${p.id}/review`, { method: "POST", body: { action } });
    toast(action === "ok" ? "✅ Подтверждено" : "❌ Отклонено");
    if (window.__badge) { window.__badge--; renderTabs(window.__badge); }
    onDone();
  });
  ok.onclick = () => act(ok, "ok");
  no.onclick = async () => { if (await confirmAsk(`Отклонить квитанцию на ${money(p.amount)}?`)) act(no, "no"); };
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
          h("div", { class: "meta" }, `${d.count} опл. · ${d.title}`)),
        h("div", { class: "kpis" },
          ME.admin ? kpi("Сотрудникам", money(d.share)) : kpi("Оплатили клиенты", money(d.total)),
          ME.admin ? kpi("Остаток", money(d.rest), "var(--green)") : kpi("Оплат", d.count),
          ME.admin ? kpi("Новых клиентов", d.new_clients) : null),
        d.series.length > 1 ? h("div", { class: "card", style: "margin-top:10px" }, h("div", { class: "small muted", style: "margin-bottom:6px" }, ME.admin ? "Оплаты по дням" : "Заработок по дням"),
          barChart(d.series.map((s) => ({ label: s.label, value: ME.admin ? s.amount : s.share })))) : null,
        ME.admin && d.workers && d.workers.length ? h("div", null, h("div", { class: "subtitle" }, "Сотрудники"), breakdown(d.workers.map((w) => ({ name: w.name, value: w.amount, sub: `${w.count} опл. · 💵 ${money(w.share)}` })))) : null,
        ME.admin && d.requisites && d.requisites.length ? h("div", null, h("div", { class: "subtitle" }, "Реквизиты"), breakdown(d.requisites.map((r) => ({ name: r.name, value: r.amount, sub: `${r.count} опл.` })))) : null,
        !d.count ? emptyState("📭", "За этот период оплат нет") : null].filter(Boolean));
      setTimeout(() => countUp(big, ME.admin ? d.total : d.share), 100);
    } catch (e) { body.replaceChildren(emptyState("😕", e.message)); }
  };
  const drawChips = () => chips.replaceChildren(...Object.entries(ME.periods).map(([k, t]) =>
    h("div", { class: "chip" + (reportPeriod === k ? " on" : ""), onclick: () => { reportPeriod = k; haptic("select"); drawChips(); fetchReport(); } }, t)));
  drawChips();
  mount(h("div", null, h("div", { class: "title" }, ME.admin ? "Отчёты" : "Мой доход"), chips, body));
  fetchReport();
}
function kpi(label, value, color) { return h("div", { class: "kpi" }, h("div", { class: "label" }, label), h("div", { class: "value", style: color ? "color:" + color : null }, value)); }

function barChart(data) {
  const W = 320, H = 150, pad = 18, n = data.length, max = Math.max(1, ...data.map((d) => d.value));
  const bw = (W - pad) / n;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H + 14}`); svg.setAttribute("class", "chart");
  const defs = document.createElementNS(svg.namespaceURI, "defs");
  const g = document.createElementNS(svg.namespaceURI, "linearGradient");
  g.id = "gb"; g.setAttribute("x1", "0"); g.setAttribute("y1", "0"); g.setAttribute("x2", "0"); g.setAttribute("y2", "1");
  [["0%", "#7c6cff"], ["100%", "#4aa8ff"]].forEach(([o, c]) => { const s = document.createElementNS(svg.namespaceURI, "stop"); s.setAttribute("offset", o); s.setAttribute("stop-color", c); g.append(s); });
  defs.append(g); svg.append(defs);
  const step = Math.ceil(n / 7);
  data.forEach((d, i) => {
    const hgt = Math.max(d.value ? 3 : 1, (d.value / max) * (H - 10));
    const r = document.createElementNS(svg.namespaceURI, "rect");
    r.setAttribute("x", (pad / 2 + i * bw + bw * 0.18).toFixed(1)); r.setAttribute("width", (bw * 0.64).toFixed(1));
    r.setAttribute("y", (H - hgt).toFixed(1)); r.setAttribute("height", hgt.toFixed(1)); r.setAttribute("rx", Math.min(5, bw * 0.3).toFixed(1));
    r.setAttribute("fill", d.value ? "url(#gb)" : "#262c3b"); r.setAttribute("class", "bar"); r.style.animationDelay = i * 25 + "ms";
    const t = document.createElementNS(svg.namespaceURI, "title"); t.textContent = `${d.label}: ${money(d.value)}`; r.append(t);
    svg.append(r);
    if (i % step === 0 || i === n - 1) {
      const tx = document.createElementNS(svg.namespaceURI, "text");
      tx.setAttribute("x", (pad / 2 + i * bw + bw / 2).toFixed(1)); tx.setAttribute("y", H + 12); tx.setAttribute("text-anchor", "middle"); tx.textContent = d.label;
      svg.append(tx);
    }
  });
  return svg;
}

function breakdown(items) {
  const max = Math.max(1, ...items.map((x) => x.value));
  const box = h("div", { class: "card" }, ...items.map((x) => {
    const bar = h("i");
    setTimeout(() => bar.style.width = (x.value / max * 100).toFixed(1) + "%", 80);
    return h("div", { style: "padding:8px 0" }, h("div", { class: "row between" }, h("div", { class: "ellipsis grow" }, x.name), h("b", null, money(x.value))),
      h("div", { class: "meter" }, bar), h("div", { class: "small muted", style: "margin-top:4px" }, x.sub));
  }));
  return box;
}

/* ================= ЕЩЁ / РЕКВИЗИТЫ / КОМАНДА ================= */
function More() {
  mount(h("div", null, h("div", { class: "title" }, "Ещё"),
    h("div", { class: "list" },
      h("div", { class: "item", onclick: () => push(RequisitesScreen) }, h("div", { class: "avatar s-work" }, "💳"), h("div", { class: "grow" }, h("div", { class: "name" }, "Реквизиты"), h("div", { class: "sub" }, "IBAN, получатели, статусы")), h("span", { class: "chev" }, "›")),
      h("div", { class: "item", onclick: () => push(TeamScreen) }, h("div", { class: "avatar s-paid" }, "👤"), h("div", { class: "grow" }, h("div", { class: "name" }, "Команда"), h("div", { class: "sub" }, "Сотрудники, проценты, доступ")), h("span", { class: "chev" }, "›"))),
    h("div", { class: "hint", style: "text-align:center;margin-top:30px" }, `${ME.user.nick} · ${ME.owner ? "главный админ" : "админ"}`)));
  stagger($app.querySelector(".list"));
}

function Requisites() { RequisitesScreen(false); }
function RequisitesScreen(pushed) {
  load(async () => {
    const d = await api("/api/requisites");
    const list = h("div", { class: "list" }, ...d.items.map((r) => {
      const sw = h("button", { class: "switch" + (r.active ? " on" : ""), onclick: async (e) => {
        e.stopPropagation(); if (!ME.admin) return;
        const next = !r.active; sw.classList.toggle("on", next); haptic("medium");
        try { await api("/api/requisites/" + r.id, { method: "PATCH", body: { active: next } }); r.active = next; toast(next ? "🟢 Рабочий" : "🔴 Не рабочий"); }
        catch (err) { sw.classList.toggle("on", r.active); toast(err.message, true); }
      } });
      return h("div", { class: "card", style: "animation:item-in .4s var(--ease) both" },
        h("div", { class: "row between" }, h("div", { class: "grow" }, h("div", { class: "name", style: "font-weight:650" }, r.holder), h("div", { class: "mono muted" }, r.iban)), ME.admin ? sw : null),
        h("div", { class: "row", style: "margin-top:10px;gap:6px;flex-wrap:wrap" },
          h("button", { class: "copy", onclick: () => copy(r.iban, "IBAN скопирован") }, "IBAN"),
          h("button", { class: "copy", onclick: () => copy(r.holder, "ФИО скопировано") }, "ФИО"),
          h("button", { class: "copy", onclick: () => copy(r.ipn, "ІПН скопирован") }, "ІПН " + r.ipn),
          h("button", { class: "copy", onclick: () => copy(`IBAN: ${r.iban}\nОтримувач: ${r.holder}\nІПН: ${r.ipn}`, "Реквизиты скопированы") }, "Всё")),
        r.comment ? h("div", { class: "hint" }, "📝 " + r.comment) : null,
        ME.admin ? h("div", { class: "row between small muted", style: "margin-top:10px" },
          h("span", null, `Сегодня ${money(r.today)} · всего ${money(r.total)} · 👥 ${r.clients}`),
          h("button", { class: "copy", style: "color:var(--red)", onclick: async () => {
            if (!await confirmAsk("Удалить реквизит? Клиенты будут отвязаны.")) return;
            try { await api("/api/requisites/" + r.id, { method: "DELETE" }); toast("🗑 Удалено"); refreshCurrent(); } catch (e) { toast(e.message, true); }
          } }, "Удалить")) : null);
    }));
    stagger(list);
    return h("div", null, h("div", { class: "title" }, "Реквизиты"),
      d.items.length ? list : emptyState("💳", ME.admin ? "Добавьте первый реквизит" : "Рабочих реквизитов нет"),
      ME.admin ? h("button", { class: "fab", onclick: requisiteSheet }, "+") : null);
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
  const save = h("button", { class: "btn primary block" }, "Добавить реквизит");
  save.onclick = () => withLoading(save, async () => {
    const r = await api("/api/requisites", { method: "POST", body: { iban: iban.value, holder: holder.value, ipn: ipn.value, comment: comment.value } });
    closeSheet(); toast(r.ipn_warning ? "✅ Добавлен. ⚠️ Проверьте ІПН" : "✅ Реквизит добавлен"); refreshCurrent();
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

function Team() { TeamScreen(false); }
const STATE = { active: ["✅", "в работе"], waiting: ["🔔", "ждёт подтверждения"], invited: ["⏳", "ещё не открыл бота"], expired: ["⌛", "приглашение истекло"], no_nick: ["⏳", "не указал ник"] };
const ROLE = { owner: "👑 Главный", admin: "🛡 Админ", worker: "👷 Сотрудник" };
function TeamScreen(pushed) {
  load(async () => {
    const d = await api("/api/team");
    const waiting = d.items.filter((u) => u.state === "waiting");
    const list = h("div", { class: "list" }, ...d.items.map((u) => h("div", { class: "item", onclick: () => memberSheet(u) },
      h("div", { class: "avatar " + (u.state === "active" ? "s-paid" : u.state === "waiting" ? "s-pending" : "") }, initials(u.nick || u.username)),
      h("div", { class: "grow" }, h("div", { class: "name ellipsis" }, u.nick || "@" + u.username), h("div", { class: "sub" }, `${ROLE[u.role]} · ${STATE[u.state][0]} ${STATE[u.state][1]}`)),
      h("div", { class: "right" }, u.percent + "%"))));
    stagger(list);
    return h("div", null, h("div", { class: "title" }, "Команда"),
      waiting.length ? h("div", { class: "banner", onclick: () => memberSheet(waiting[0]) }, "🔔", h("div", { class: "grow" }, `Ждут подтверждения: ${waiting.length}`), "›") : null,
      list, h("button", { class: "fab", onclick: () => inviteSheet(d.can_invite_admin) }, "+"));
  }, pushed);
}

function memberSheet(u) {
  const parts = [h("div", { class: "detail-head" }, h("div", { class: "avatar lg", style: "margin:0 auto" }, initials(u.nick || u.username)),
    h("div", { class: "name" }, u.nick || "@" + u.username), h("div", { class: "phone" }, `${ROLE[u.role]}${u.username ? " · @" + u.username : ""}`),
    h("div", { class: "small muted", style: "margin-top:4px" }, `${STATE[u.state][0]} ${STATE[u.state][1]} · клиентов ${u.clients} (в работе ${u.work})`))];
  if (u.state === "waiting" && u.can_approve) {
    const ok = h("button", { class: "btn green" }, "✅ Открыть доступ"), no = h("button", { class: "btn red" }, "Отклонить");
    ok.onclick = () => withLoading(ok, async () => { await api(`/api/team/${u.id}/approve`, { method: "POST", body: { ok: true } }); closeSheet(); toast("✅ Доступ открыт"); refreshCurrent(); });
    no.onclick = async () => { if (await confirmAsk("Отклонить запрос доступа?")) withLoading(no, async () => { await api(`/api/team/${u.id}/approve`, { method: "POST", body: { ok: false } }); closeSheet(); toast("Отклонено"); refreshCurrent(); }); };
    parts.push(h("div", { class: "hint", style: "text-align:center;margin:10px 0" }, "Убедитесь, что это нужный человек"), h("div", { class: "btns" }, no, ok));
  }
  if (u.can_percent) {
    const val = h("div", { style: "font-size:34px;font-weight:800;text-align:center" }, u.percent + "%");
    const range = h("input", { type: "range", class: "range", min: "0", max: "100", step: "1", value: String(u.percent) });
    range.addEventListener("input", () => { val.textContent = range.value + "%"; haptic("select"); });
    const presets = h("div", { class: "chips", style: "justify-content:center" }, ...[30, 40, 50, 60].map((p) => h("div", { class: "chip", onclick: () => { range.value = p; val.textContent = p + "%"; haptic("select"); } }, p + "%")));
    const save = h("button", { class: "btn primary block", style: "margin-top:8px" }, "Сохранить процент");
    save.onclick = () => withLoading(save, async () => { await api(`/api/team/${u.id}`, { method: "PATCH", body: { percent: Number(range.value) } }); closeSheet(); toast(`💯 Процент: ${range.value}%`); refreshCurrent(); });
    parts.push(h("div", { class: "subtitle" }, "Процент от оплат"), val, range, presets, save, h("div", { class: "hint", style: "text-align:center" }, "Действует для новых оплат"));
  }
  if (u.can_manage) {
    const del = h("button", { class: "btn red block", style: "margin-top:16px" }, "🗑 Удалить из команды");
    del.onclick = async () => { if (await confirmAsk(`Удалить ${u.nick || "@" + u.username}? Доступ к боту закроется.`)) withLoading(del, async () => { await api("/api/team/" + u.id, { method: "DELETE" }); closeSheet(); toast("🗑 Удалено"); refreshCurrent(); }); };
    parts.push(del);
  }
  openSheet(null, h("div", null, ...parts));
}

function inviteSheet(canAdmin) {
  let role = "worker";
  const user = h("input", { class: "input", placeholder: "@username", autocapitalize: "none", autocomplete: "off" });
  const roles = h("div", { class: "options" });
  const draw = () => roles.replaceChildren(...[["worker", "👷 Сотрудник", "Свои клиенты и квитанции"], ...(canAdmin ? [["admin", "🛡 Админ", "Всё, кроме управления админами"]] : [])].map(([k, t, s]) =>
    h("div", { class: "opt" + (role === k ? " on" : ""), onclick: () => { role = k; haptic("select"); draw(); } }, h("span", { class: "radio" }), h("div", { class: "grow" }, h("div", null, t), h("div", { class: "small muted" }, s)))));
  draw();
  const save = h("button", { class: "btn primary block", style: "margin-top:6px" }, "Пригласить");
  save.onclick = () => withLoading(save, async () => {
    await api("/api/team", { method: "POST", body: { username: user.value, role } });
    closeSheet(); toast("✅ Приглашение создано"); refreshCurrent();
    if (tg) tg.showAlert(`Попросите ${user.value.startsWith("@") ? user.value : "@" + user.value} открыть бота и нажать /start. Потом подтвердите доступ здесь.`);
  });
  openSheet("Пригласить", h("div", null, field("Username в Telegram", user), canAdmin ? field("Роль", roles) : null, save));
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
  if (!tg || !tg.initData) {
    mount(h("div", null, emptyState("🔒", "Откройте приложение через бота в Telegram")));
    return;
  }
  if (!API) await refreshApiUrl();
  try {
    ME = await api("/api/me");
  } catch (e) {
    mount(h("div", null, emptyState("😕", e.message, h("button", { class: "btn ghost", style: "margin-top:14px", onclick: () => location.reload() }, "Повторить"))));
    return;
  }
  go("home");
}
start();
