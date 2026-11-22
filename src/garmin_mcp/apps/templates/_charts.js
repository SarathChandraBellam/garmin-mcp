/* Tiny SVG charts and DOM helpers. Data is only ever inserted as text, never as HTML. */
const NS = "http://www.w3.org/2000/svg";
function el(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids) if (k !== null && k !== undefined && k !== false) n.append(k);
  return n;
}
function svg(tag, attrs, text) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined) n.setAttribute(k, v);
  if (text !== undefined) n.textContent = text;
  return n;
}
const has = (v) => v !== null && v !== undefined && !Number.isNaN(v);
function fmt(v, digits) {
  if (!has(v)) return "–";
  const d = digits !== undefined ? digits : Math.abs(v) >= 100 ? 0 : 1;
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: d });
}
function pctText(p) {
  if (!has(p)) return "";
  return (p > 0 ? "+" : p < 0 ? "−" : "±") + fmt(Math.abs(p), Math.abs(p) >= 10 ? 0 : 1) + "%";
}
/* "Nice" axis ticks between lo and hi. */
function ticks(lo, hi, count) {
  if (lo === hi) { lo -= 1; hi += 1; }
  const raw = (hi - lo) / Math.max(1, count);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) || raw;
  const start = Math.floor(lo / step) * step, end = Math.ceil(hi / step) * step;
  const out = [];
  for (let v = start; v <= end + step / 2; v += step) out.push(Number(v.toFixed(6)));
  return out;
}
function shortNum(v) {
  const a = Math.abs(v);
  if (a >= 10000) return fmt(v / 1000, 0) + "k";
  if (a >= 1000) return fmt(v / 1000, 1) + "k";
  return fmt(v, a < 10 ? 1 : 0);
}

/* A placeholder that draws its chart at the container's real width (crisp axes and text),
   and redraws on resize. draw(width) returns an SVG element. */
function chartSlot(draw, height) {
  const slot = el("div", { class: "chart-slot" });
  slot.style.minHeight = (height || 40) + "px";
  slot._draw = draw;
  return slot;
}
function paintCharts(scope) {
  for (const slot of (scope || document).querySelectorAll(".chart-slot")) {
    const w = Math.max(120, Math.floor(slot.clientWidth || 300));
    if (slot._w === w && slot.firstChild) continue;
    slot._w = w;
    slot.replaceChildren(slot._draw(w));
  }
}
Bridge.onResize(() => requestAnimationFrame(() => paintCharts()));

/* Line/area chart. series = [{values: [number|null], cls}] plotted on x = index / (length-1),
   so shorter series end early instead of being stretched. */
function lineChart(series, opts) {
  const w = opts.width || 300, h = opts.height || 60;
  const axes = !!opts.axes;
  const padL = axes ? 38 : 2, padR = axes ? 8 : 4, padT = 6, padB = axes ? 22 : 4;
  const root = svg("svg", { width: w, height: h, viewBox: `0 0 ${w} ${h}`, role: "img",
    "aria-label": opts.label, class: "chart" });
  const all = series.flatMap((s) => s.values).filter(has);
  if (!all.length) {
    root.append(svg("text", { x: w / 2, y: h / 2 + 4, "text-anchor": "middle", class: "empty-text" }, "No data"));
    return root;
  }
  let lo = Math.min(...all), hi = Math.max(...all);
  if (has(opts.min)) lo = Math.min(lo, opts.min);
  if (has(opts.max)) hi = Math.max(hi, opts.max);
  const tk = axes ? ticks(lo, hi, 3) : null;
  if (tk) { lo = tk[0]; hi = tk[tk.length - 1]; }
  const span = hi - lo || 1;
  const y = (v) => padT + (1 - (v - lo) / span) * (h - padT - padB);
  const n = opts.length || Math.max(...series.map((s) => s.values.length));
  const x = (i) => (n <= 1 ? (padL + w - padR) / 2 : padL + (i * (w - padL - padR)) / (n - 1));
  if (tk) {
    for (const t of tk) {
      root.append(svg("line", { x1: padL, x2: w - padR, y1: y(t), y2: y(t), class: "grid-line" }));
      root.append(svg("text", { x: padL - 6, y: y(t) + 4, "text-anchor": "end", class: "tick" }, shortNum(t)));
    }
    for (const [i, label, anchor] of opts.xLabels || []) {
      root.append(svg("text", { x: x(i), y: h - 6, "text-anchor": anchor || "middle", class: "tick" }, label));
    }
  } else {
    root.append(svg("line", { x1: padL, x2: w - padR, y1: h - padB, y2: h - padB, class: "base" }));
  }
  series.forEach((s, si) => {
    const cls = s.cls || "s" + si;
    const runs = [];
    let run = [];
    s.values.forEach((v, i) => {
      if (has(v)) run.push([x(i), y(v)]);
      else if (run.length) { runs.push(run); run = []; }
    });
    if (run.length) runs.push(run);
    for (const r of runs) {
      const d = r.map(([px, py], i) => (i ? "L" : "M") + px.toFixed(1) + " " + py.toFixed(1)).join("");
      if (s.area && r.length > 1) {
        const base = y(Math.max(lo, Math.min(hi, has(opts.areaBase) ? opts.areaBase : lo)));
        root.append(svg("path", { d: d + `L${r[r.length - 1][0].toFixed(1)} ${base}L${r[0][0].toFixed(1)} ${base}Z`, class: "area " + cls }));
      }
      root.append(svg("path", { d, class: "line " + cls }));
      if (r.length === 1) root.append(svg("circle", { cx: r[0][0], cy: r[0][1], r: 3.5, class: "dot " + cls }));
    }
    const lastI = s.values.map(has).lastIndexOf(true);
    if (lastI >= 0 && s.lastDot !== false)
      root.append(svg("circle", { cx: x(lastI), cy: y(s.values[lastI]), r: 3.5, class: "dot " + cls }));
  });
  return root;
}

/* Horizontal bars: items = [{label, value, cls, text}] */
function barList(items, opts) {
  const max = Math.max(1e-9, ...items.map((i) => i.value || 0));
  const list = el("div", { class: "bars", role: "list", "aria-label": opts.label });
  for (const it of items) {
    const fill = el("span", { class: "fill " + (it.cls || "") });
    fill.style.width = ((it.value || 0) / max) * 100 + "%";
    list.append(el("div", { class: "bar", role: "listitem" },
      el("span", { class: "bar-label", text: it.label, title: it.label }),
      el("span", { class: "track", "aria-hidden": "true" }, fill),
      el("span", { class: "bar-value", text: it.text !== undefined ? it.text : fmt(it.value) })));
  }
  return list;
}

/* Vertical stacked columns with a y grid: cols = [{label, parts: [{value, cls}], title}] */
function stackedColumns(cols, opts) {
  const w = opts.width || 600, h = opts.height || 150;
  const padL = 30, padR = 4, padT = 6, padB = 22;
  const totals = cols.map((c) => c.parts.reduce((a, p) => a + (p.value || 0), 0));
  const tk = ticks(0, Math.max(1, ...totals), 3);
  const max = tk[tk.length - 1];
  const root = svg("svg", { width: w, height: h, viewBox: `0 0 ${w} ${h}`, role: "img", "aria-label": opts.label, class: "chart" });
  const y = (v) => padT + (1 - v / max) * (h - padT - padB);
  for (const t of tk) {
    root.append(svg("line", { x1: padL, x2: w - padR, y1: y(t), y2: y(t), class: "grid-line" }));
    root.append(svg("text", { x: padL - 6, y: y(t) + 4, "text-anchor": "end", class: "tick" }, fmt(t, 0) + (opts.unit || "")));
  }
  const slot = (w - padL - padR) / Math.max(1, cols.length);
  const gap = Math.min(4, slot * 0.25), bw = Math.max(1, slot - gap);
  cols.forEach((c, i) => {
    let acc = 0;
    const g = svg("g", { class: "colg" });
    g.append(svg("title", {}, c.title || c.label));
    for (const p of c.parts) {
      const v = p.value || 0;
      if (v <= 0) continue;
      const top = y(acc + v), bottom = y(acc);
      g.append(svg("rect", { x: padL + i * slot + gap / 2, y: top, width: bw, height: Math.max(0.5, bottom - top - 1), rx: Math.min(2, bw / 3), class: "col " + p.cls }));
      acc += v;
    }
    root.append(g);
  });
  for (const [i, label, anchor] of opts.xLabels || []) {
    root.append(svg("text", { x: padL + i * slot + slot / 2, y: h - 6, "text-anchor": anchor || "middle", class: "tick" }, label));
  }
  return root;
}

/* A progress ring (inline SVG). Text sits in HTML on top so it never scales. */
function ring(value, max, opts) {
  const size = opts.size || 132, stroke = opts.stroke || 12, r = (size - stroke) / 2, c = 2 * Math.PI * r;
  const frac = has(value) ? Math.max(0, Math.min(1, value / max)) : 0;
  const s = svg("svg", { width: size, height: size, viewBox: `0 0 ${size} ${size}`, "aria-hidden": "true" });
  s.append(svg("circle", { cx: size / 2, cy: size / 2, r, fill: "none", "stroke-width": stroke, class: "ring-track" }));
  const arc = svg("circle", { cx: size / 2, cy: size / 2, r, fill: "none", "stroke-width": stroke, class: "ring-fill",
    "stroke-dasharray": c.toFixed(2), "stroke-dashoffset": c.toFixed(2), transform: `rotate(-90 ${size / 2} ${size / 2})` });
  s.append(arc);
  requestAnimationFrame(() => requestAnimationFrame(() => arc.setAttribute("stroke-dashoffset", (c * (1 - frac)).toFixed(2))));
  return el("div", { class: "ring", role: "img", "aria-label": opts.label },
    s, el("div", { class: "ring-center" }, el("b", { text: has(value) ? fmt(value, 0) : "–" }), el("span", { text: opts.caption || "" })));
}

/* A row of toggle buttons with roving tabindex and arrow-key navigation. */
function segmented(options, current, onPick, label) {
  const group = el("div", { class: "segmented", role: "radiogroup", "aria-label": label });
  const buttons = options.map(([value, text, title]) =>
    el("button", {
      type: "button", role: "radio", "aria-checked": String(value === current),
      tabindex: value === current ? "0" : "-1", text, title, "aria-label": title,
      onclick: () => { if (value !== current) onPick(value); },
    }));
  if (!buttons.some((b) => b.tabIndex === 0) && buttons[0]) buttons[0].tabIndex = 0;
  group.addEventListener("keydown", (e) => {
    const i = buttons.indexOf(document.activeElement);
    if (i < 0) return;
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const b = buttons[(i + step + buttons.length) % buttons.length];
    b.focus();
    b.click();
  });
  group.append(...buttons);
  return group;
}
