/* MCP Apps bridge (io.modelcontextprotocol/ui): JSON-RPC 2.0 over postMessage with the host.
   All data requests go through the host's tools/call, so they reuse the same connection and
   key header. Nothing here stores or sees a key.

   Host context: applies theme, styles.variables (MCP Apps 2026-01-26 theming), styles.css.fonts,
   containerDimensions (compact layout below 560px) and displayMode, on initialize and on
   ui/notifications/host-context-changed.

   Sample-data mode: open the view with ?demo=1 (or #demo=1). The view then renders the
   built-in, clearly fake dataset from _demo.js, shows a "Sample data" badge and never calls
   tools/call or ui/message. Every screenshot, GIF and OG image is made this way. */
const Bridge = (() => {
  let nextId = 0;
  const pending = new Map();
  const handlers = {};
  const resizeHooks = [];
  const host = { width: null, displayMode: "inline" };
  const root = document.documentElement;
  const params = new URLSearchParams(location.search + "&" + location.hash.replace(/^#/, ""));
  const demo = params.get("demo") === "1";
  const hasParent = window.parent && window.parent !== window;
  const post = (msg) => { if (hasParent) window.parent.postMessage(msg, "*"); };

  function request(method, params, timeoutMs) {
    return new Promise((resolve, reject) => {
      if (!hasParent) { reject(new Error("No host")); return; }
      const id = ++nextId;
      pending.set(id, { resolve, reject });
      post({ jsonrpc: "2.0", id, method, params: params || {} });
      setTimeout(() => {
        if (pending.delete(id)) reject(new Error(method + " timed out"));
      }, timeoutMs || 60000);
    });
  }
  const notify = (method, params) => post({ jsonrpc: "2.0", method, params: params || {} });

  window.addEventListener("message", (ev) => {
    if (!hasParent || ev.source !== window.parent) return;
    const m = ev.data;
    if (!m || m.jsonrpc !== "2.0") return;
    if (m.method === undefined && m.id !== undefined && pending.has(m.id)) {
      const p = pending.get(m.id);
      pending.delete(m.id);
      m.error ? p.reject(new Error(m.error.message || "error")) : p.resolve(m.result);
      return;
    }
    const h = m.method && handlers[m.method];
    const out = h ? h(m.params || {}) : undefined;
    if (m.id !== undefined && m.method) post({ jsonrpc: "2.0", id: m.id, result: out || {} });
  });

  /* ---- host context ---- */
  function applyTheme(theme) {
    if (theme === "dark" || theme === "light") root.dataset.theme = theme;
  }
  function applyStyles(styles) {
    if (!styles || typeof styles !== "object") return;
    const vars = styles.variables;
    if (vars && typeof vars === "object") {
      let any = false;
      for (const [k, v] of Object.entries(vars)) {
        if (!/^--[\w-]+$/.test(k)) continue;
        if (v === null || v === undefined || v === "") root.style.removeProperty(k);
        else if (typeof v === "string" && v.length < 400) { root.style.setProperty(k, v); any = true; }
      }
      if (any) root.dataset.hostStyles = "";
    }
    const fonts = styles.css && styles.css.fonts;
    if (typeof fonts === "string") {
      let tag = document.getElementById("host-fonts");
      if (!tag) { tag = document.createElement("style"); tag.id = "host-fonts"; document.head.append(tag); }
      tag.textContent = fonts; // fonts from outside origins stay blocked by the CSP
    }
  }
  function updateSize() {
    const w = host.width || root.clientWidth || window.innerWidth;
    const size = w < 560 ? "compact" : "regular";
    if (root.dataset.size !== size) {
      root.dataset.size = size;
      resizeHooks.forEach((f) => f(size));
    } else resizeHooks.forEach((f) => f(size, true));
  }
  function applyHostContext(ctx) {
    if (!ctx || typeof ctx !== "object") return;
    applyTheme(ctx.theme);
    applyStyles(ctx.styles);
    const dims = ctx.containerDimensions;
    if (dims && typeof dims === "object") {
      const w = Number(dims.width || dims.maxWidth);
      host.width = w > 0 ? w : null;
    }
    if (typeof ctx.displayMode === "string") {
      host.displayMode = ctx.displayMode;
      root.dataset.display = ctx.displayMode;
    }
    updateSize();
  }
  let resizeTimer = 0;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(updateSize, 80);
  });
  updateSize();
  if (demo) {
    root.dataset.demo = "";
    applyTheme(params.get("theme"));
    if (Number(params.get("width")) > 0) host.width = Number(params.get("width"));
  }

  function structured(result) {
    if (!result) return null;
    if (result.structuredContent) return result.structuredContent;
    const texts = (result.content || []).filter((c) => c.type === "text").map((c) => c.text);
    for (let i = texts.length - 1; i >= 0; i--) {
      try { return JSON.parse(texts[i]); } catch (e) { /* not JSON */ }
    }
    return null;
  }

  async function init(name, onResult, onInput) {
    handlers["ui/notifications/tool-result"] = (p) => { if (!demo) onResult(structured(p)); };
    handlers["ui/notifications/tool-input"] = (p) => { if (onInput && !demo) onInput(p.arguments || {}); };
    handlers["ui/notifications/host-context-changed"] = (p) => applyHostContext(p);
    handlers["ui/resource-teardown"] = () => ({});
    if (hasParent) {
      try {
        const r = await request("ui/initialize", {
          protocolVersion: "2026-01-26",
          appInfo: { name, version: "2" },
          appCapabilities: {},
        }, demo ? 1500 : 60000);
        applyHostContext(r && r.hostContext);
      } catch (e) { /* older hosts: carry on */ }
      notify("ui/notifications/initialized");
      // Report the content's own size: scrollHeight never drops below the iframe's current
      // height, so a view could grow but never shrink.
      let lastH = 0;
      const ro = new ResizeObserver(() => {
        const box = root.getBoundingClientRect();
        const height = Math.ceil(box.height);
        if (height === lastH) return;
        lastH = height;
        notify("ui/notifications/size-changed", { width: Math.ceil(box.width), height });
      });
      ro.observe(document.body);
    }
    if (demo) setTimeout(() => onResult(Demo.opening(name)), 0);
  }

  async function callTool(name, args) {
    if (demo) return Demo.call(name, args || {});
    const r = await request("tools/call", { name, arguments: args || {} });
    if (r && r.isError) {
      const t = (r.content || []).map((c) => c.text || "").join(" ");
      throw new Error(t || "Tool error");
    }
    return structured(r);
  }

  const sendMessage = (text) => demo
    ? new Promise((resolve) => setTimeout(() => resolve({}), 250))
    : request("ui/message", { role: "user", content: [{ type: "text", text }] });

  const onResize = (f) => resizeHooks.push(f);
  const compact = () => root.dataset.size === "compact";

  return { init, callTool, sendMessage, onResize, compact, demo, applyHostContext };
})();
