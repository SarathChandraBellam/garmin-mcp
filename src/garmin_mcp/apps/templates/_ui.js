/* Shared view components: icons, humanised dates and labels, the header, the period switcher,
   loading/empty/error states. Everything is built with el()/svg(); data goes in as text only. */
const ICONS = {
  pulse: ["M3 12h4l3-8 4 16 3-8h4"],
  timer: ["M12 21a8 8 0 1 0 0-16 8 8 0 0 0 0 16z", "M12 9v4l2.5 2.5", "M9.5 2h5"],
  moon: ["M20 14.5A8.5 8.5 0 1 1 9.5 4a6.6 6.6 0 0 0 10.5 10.5z"],
  trend: ["M3 17l6-6 4 4 8-8", "M15 7h6v6"],
  calendar: ["M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z", "M16 3v4M8 3v4M3 10h18"],
  heart: ["M12 20s-7-4.3-9-8.6A5 5 0 0 1 12 6.5a5 5 0 0 1 9 4.9C19 15.7 12 20 12 20z"],
  wave: ["M3 12h3l2-5 3 10 2.5-7 1.5 2h6"],
  gauge: ["M4.5 17a8 8 0 1 1 15 0", "M12 13l3.5-3.5"],
  battery: ["M4 7h13a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1z", "M21 10.5v3", "M11 9l-2.5 3.5h3L9 15"],
  steps: ["M7.5 20.5c-1.5 0-2.5-1-2.5-2.5v-.5h5v.5c0 1.5-1 2.5-2.5 2.5z", "M5 15c-.6-3-.3-7.5 2.5-7.5S10.6 12 10 15z",
    "M16.5 16.5c1.5 0 2.5-1 2.5-2.5v-.5h-5v.5c0 1.5 1 2.5 2.5 2.5z", "M14 11c-.6-3-.3-7.5 2.5-7.5S19.6 8 19 11z"],
  run: ["M15.5 5.5a1.75 1.75 0 1 0 0-3.5 1.75 1.75 0 0 0 0 3.5z", "M6 11l3-3 4 1 2.5 3.5L19 14", "M11.5 8.5L9.5 15l4 2.5V22", "M9.5 15L6 21"],
  ride: ["M5.5 20a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM18.5 20a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z", "M5.5 16.5L9 10h6l3.5 6.5", "M9 10l3 6.5h-6.5M13.5 6h2.5l1.5 4"],
  swim: ["M2 18c2 0 2-1.5 4-1.5s2 1.5 4 1.5 2-1.5 4-1.5 2 1.5 4 1.5 2-1.5 4-1.5", "M16.5 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4z", "M5 13.5l5-4.5 3 3 2.5-1.5"],
  hike: ["M3 20l6-10 4 6 3-4 5 8z"],
  strength: ["M6 7v10M18 7v10M3 10v4M21 10v4M6 12h12"],
  close: ["M6 6l12 12M18 6L6 18"],
  alert: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 7.5v5.5", "M12 16.5v.01"],
  check: ["M5 12.5l4.5 4.5L19 7.5"],
  retry: ["M20 11a8 8 0 1 0-2.3 5.7", "M20 4v7h-7"],
  search: ["M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13z", "M15.5 15.5L20 20"],
};
function icon(name, cls) {
  const s = svg("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "2",
    "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", class: cls || null });
  for (const d of ICONS[name] || ICONS.pulse) s.append(svg("path", { d }));
  return s;
}

/* ---- dates and labels ---- */
const isoDate = (iso) => new Date(String(iso).slice(0, 10) + "T00:00:00Z");
const dtf = (o) => new Intl.DateTimeFormat(undefined, Object.assign({ timeZone: "UTC" }, o));
const shortDate = (iso) => (iso ? dtf({ month: "short", day: "numeric" }).format(isoDate(iso)) : "–");
const dayDate = (iso) => (iso ? dtf({ weekday: "short", month: "short", day: "numeric" }).format(isoDate(iso)) : "–");
function rangeText(start, end) {
  if (!start || !end) return "";
  if (start === end) return dayDate(start);
  const f = dtf({ month: "short", day: "numeric" });
  try { return f.formatRange(isoDate(start), isoDate(end)); } catch (e) { return f.format(isoDate(start)) + " – " + f.format(isoDate(end)); }
}
function clock(hhmm) {
  if (!hhmm || !/^\d{1,2}:\d{2}/.test(hhmm)) return hhmm || "–";
  const [h, m] = hhmm.split(":").map(Number);
  return dtf({ hour: "numeric", minute: "2-digit" }).format(new Date(Date.UTC(2000, 0, 1, h, m)));
}
function timeOf(local) {
  const m = /[ T](\d{2}:\d{2})/.exec(local || "");
  return m ? clock(m[1]) : "";
}
const PERIOD_LABELS = {
  today: ["1D", "Today"], last_1d: ["1D", "Today"], last_7d: ["7D", "Last 7 days"], last_15d: ["15D", "Last 15 days"],
  last_30d: ["30D", "Last 30 days"], last_90d: ["90D", "Last 90 days"], this_week: ["Week", "This week"],
  last_week: ["Last week", "Last week"], this_month: ["Month", "This month"], last_month: ["Last month", "Last month"],
  ytd: ["YTD", "Year to date"], previous: ["Previous", "The same length just before"],
};
const periodOptions = (keys) => keys.map((k) => [k, PERIOD_LABELS[k][0], PERIOD_LABELS[k][1]]);
const periodName = (p) => (PERIOD_LABELS[p] || [p, p])[1];
function windowText(w, unit) {
  if (!w || !w.start) return "";
  const n = w.days === 1 ? "1 " + (unit || "day") : `${w.days} ${unit || "day"}s`;
  return `${rangeText(w.start, w.end)} · ${n}`;
}
function titleCase(t) {
  const s = String(t || "").replace(/_/g, " ").trim();
  return s ? s[0].toUpperCase() + s.slice(1) : "";
}
function typeIcon(t) {
  const s = String(t || "");
  if (/swim/.test(s)) return "swim";
  if (/cycl|bik|ride|spin/.test(s)) return "ride";
  if (/hik|walk/.test(s)) return "hike";
  if (/strength|weight|gym/.test(s)) return "strength";
  if (/run|jog/.test(s)) return "run";
  return "pulse";
}
function unitText(u) {
  return { hours: "h", minutes: "min", steps: "", "0-100": "", "ml/kg/min": "ml/kg/min" }[u] ?? (u || "");
}

/* ---- header and shared bits ---- */
function mountChrome() {
  for (const n of document.querySelectorAll("[data-icon]")) n.replaceChildren(icon(n.dataset.icon));
  if (Bridge.demo) {
    const h = document.querySelector(".app-head h1");
    if (h) h.append(el("span", { class: "badge sample", title: "Built-in sample data. Not real Garmin data.", text: "Sample data" }));
  }
}
function setWindow(text, title) {
  const n = document.getElementById("window");
  n.textContent = text || "";
  if (title) n.title = title; else n.removeAttribute("title");
}
function announce(text) {
  const n = document.getElementById("status");
  if (n) n.textContent = text || "";
}
function setBusy(nodes, on) {
  for (const n of [].concat(nodes)) {
    if (!n) continue;
    n.classList.toggle("busy", !!on);
    if (on) n.setAttribute("aria-busy", "true"); else n.removeAttribute("aria-busy");
  }
}
function skeletonTiles(n, cls) {
  return Array.from({ length: n }, () => el("div", { class: "sk " + (cls || "tile"), "aria-hidden": "true" }));
}
function errorNotice(title, err, retry) {
  return el("div", { class: "notice error", role: "alert" }, icon("alert"),
    el("div", { class: "msg" }, el("b", { text: title }), el("span", { class: "muted", text: (err && err.message) || "" })),
    retry ? el("button", { type: "button", onclick: retry }, "Retry") : null);
}
function illustration(name) {
  const s = svg("svg", { viewBox: "0 0 112 80", "aria-hidden": "true" });
  s.append(svg("rect", { x: 6, y: 8, width: 100, height: 64, rx: 12, fill: "none", stroke: "currentColor", "stroke-opacity": ".28", "stroke-dasharray": "4 4" }));
  s.append(svg("path", { d: "M18 58h76", stroke: "currentColor", "stroke-opacity": ".22", "stroke-width": "2", "stroke-linecap": "round" }));
  s.append(svg("circle", { cx: 56, cy: 38, r: 20, fill: "var(--accent-soft)" }));
  const g = svg("g", { transform: "translate(44 26)", fill: "none", stroke: "var(--accent)", "stroke-width": "2", "stroke-linecap": "round", "stroke-linejoin": "round" });
  for (const d of ICONS[name] || ICONS.search) g.append(svg("path", { d }));
  s.append(g);
  return s;
}
function emptyState(name, title, text, action) {
  return el("div", { class: "empty enter" }, illustration(name), el("h3", { text: title }), el("p", { text }),
    action ? el("button", { type: "button", onclick: action[1] }, action[0]) : null);
}
function deltaChip(pct, higherBetter, previousText) {
  if (!has(pct)) return el("span", { class: "delta none", text: "No earlier data" });
  const flat = Math.abs(pct) < 0.5;
  const good = flat || higherBetter === null || higherBetter === undefined ? "" : (pct > 0) === higherBetter ? "good" : "bad";
  const arrow = flat ? "→" : pct > 0 ? "↑" : "↓";
  return el("span", { class: "delta " + (flat ? "flat" : good), title: previousText || null },
    el("span", { "aria-hidden": "true", text: arrow }), el("span", { text: flat ? "No change" : pctText(pct) }));
}
