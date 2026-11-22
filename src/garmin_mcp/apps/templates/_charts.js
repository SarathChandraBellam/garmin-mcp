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
  for (const k of kids) if (k) n.append(k);
  return n;
}
function svg(tag, attrs) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
  return n;
}
function fmt(v, digits) {
  if (v === null || v === undefined) return "–";
  const d = digits !== undefined ? digits : Math.abs(v) >= 100 ? 0 : 1;
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: d });
}
function pctText(p) {
  if (p === null || p === undefined) return "";
  return (p > 0 ? "+" : "") + fmt(p, 1) + "%";
}
function scale(vals, h, pad) {
  const xs = vals.filter((v) => v !== null && v !== undefined);
  const lo = Math.min(...xs), hi = Math.max(...xs);
  const span = hi - lo || 1;
  return (v) => h - pad - ((v - lo) / span) * (h - 2 * pad);
}
/* Line chart of one or two series (arrays of numbers or null). */
function lineChart(series, opts) {
  const w = opts.width || 300, h = opts.height || 60, pad = 4;
  const root = svg("svg", { viewBox: `0 0 ${w} ${h}`, role: "img", "aria-label": opts.label, class: "chart" });
  const all = series.flatMap((s) => s.values);
  if (!all.some((v) => v !== null && v !== undefined)) {
    const t = svg("text", { x: w / 2, y: h / 2, "text-anchor": "middle", class: "muted-fill" });
    t.textContent = "No data";
    root.append(t);
    return root;
  }
  const y = scale(all, h, pad);
  const n = Math.max(...series.map((s) => s.values.length));
  const x = (i) => (n <= 1 ? w / 2 : pad + (i * (w - 2 * pad)) / (n - 1));
  series.forEach((s, si) => {
    let d = "";
    s.values.forEach((v, i) => {
      if (v === null || v === undefined) return;
      d += (d && s.values[i - 1] !== null && s.values[i - 1] !== undefined ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1);
    });
    root.append(svg("path", { d, class: "line s" + si, fill: "none" }));
    s.values.forEach((v, i) => {
      if (v !== null && v !== undefined && s.values.filter((q) => q !== null).length < 40)
        root.append(svg("circle", { cx: x(i), cy: y(v), r: 2, class: "dot s" + si }));
    });
  });
  return root;
}
/* Horizontal bars: items = [{label, value, cls}] */
function barList(items, opts) {
  const max = Math.max(1, ...items.map((i) => i.value || 0));
  const list = el("div", { class: "bars", role: "list", "aria-label": opts.label });
  for (const it of items) {
    const fill = el("span", { class: "fill " + (it.cls || "") });
    fill.style.width = ((it.value || 0) / max) * 100 + "%";
    list.append(el("div", { class: "bar", role: "listitem" },
      el("span", { class: "bar-label", text: it.label }),
      el("span", { class: "track" }, fill),
      el("span", { class: "bar-value", text: it.text !== undefined ? it.text : fmt(it.value) })));
  }
  return list;
}
/* Vertical stacked columns: cols = [{label, parts: [{value, cls, name}], title}] */
function stackedColumns(cols, opts) {
  const w = opts.width || 600, h = opts.height || 140, gap = 2;
  const max = Math.max(1, ...cols.map((c) => c.parts.reduce((a, p) => a + (p.value || 0), 0)));
  const bw = (w - gap * cols.length) / Math.max(1, cols.length);
  const root = svg("svg", { viewBox: `0 0 ${w} ${h}`, role: "img", "aria-label": opts.label, class: "chart" });
  cols.forEach((c, i) => {
    let y0 = h;
    const g = svg("g", {});
    const t = svg("title", {});
    t.textContent = c.title || c.label;
    g.append(t);
    for (const p of c.parts) {
      const ph = ((p.value || 0) / max) * (h - 4);
      y0 -= ph;
      g.append(svg("rect", { x: i * (bw + gap), y: y0, width: Math.max(1, bw), height: ph, class: p.cls }));
    }
    root.append(g);
  });
  return root;
}
/* A row of toggle buttons with arrow-key navigation. */
function segmented(options, current, onPick, label) {
  const group = el("div", { class: "segmented", role: "radiogroup", "aria-label": label });
  const buttons = options.map(([value, text]) =>
    el("button", {
      type: "button", role: "radio", "aria-checked": String(value === current),
      tabindex: value === current ? "0" : "-1", text,
      onclick: () => onPick(value),
    }));
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
function setStatus(node, text, isError) {
  node.textContent = text || "";
  node.className = "status" + (isError ? " error" : "");
}
