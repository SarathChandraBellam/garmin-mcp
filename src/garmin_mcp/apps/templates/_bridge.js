/* MCP Apps bridge (io.modelcontextprotocol/ui): JSON-RPC 2.0 over postMessage with the host.
   All data requests go through the host's tools/call, so they reuse the same connection and
   key header. Nothing here stores or sees a key. */
const Bridge = (() => {
  let nextId = 0;
  const pending = new Map();
  const handlers = {};
  const post = (msg) => window.parent.postMessage(msg, "*");

  function request(method, params) {
    return new Promise((resolve, reject) => {
      const id = ++nextId;
      pending.set(id, { resolve, reject });
      post({ jsonrpc: "2.0", id, method, params: params || {} });
      setTimeout(() => {
        if (pending.delete(id)) reject(new Error(method + " timed out"));
      }, 60000);
    });
  }
  const notify = (method, params) => post({ jsonrpc: "2.0", method, params: params || {} });

  window.addEventListener("message", (ev) => {
    if (ev.source !== window.parent) return;
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

  function applyTheme(ctx) {
    const theme = ctx && ctx.theme;
    if (theme === "dark" || theme === "light") document.documentElement.dataset.theme = theme;
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
    handlers["ui/notifications/tool-result"] = (p) => { onResult(structured(p)); };
    handlers["ui/notifications/tool-input"] = (p) => { if (onInput) onInput(p.arguments || {}); };
    handlers["ui/notifications/host-context-changed"] = (p) => applyTheme(p);
    handlers["ui/resource-teardown"] = () => ({});
    try {
      const r = await request("ui/initialize", {
        protocolVersion: "2026-01-26",
        appInfo: { name, version: "1" },
        appCapabilities: {},
      });
      applyTheme(r && r.hostContext);
    } catch (e) { /* older hosts: carry on */ }
    notify("ui/notifications/initialized");
    const ro = new ResizeObserver(() => {
      notify("ui/notifications/size-changed", {
        width: document.documentElement.scrollWidth,
        height: document.documentElement.scrollHeight,
      });
    });
    ro.observe(document.body);
  }

  async function callTool(name, args) {
    const r = await request("tools/call", { name, arguments: args || {} });
    if (r && r.isError) {
      const t = (r.content || []).map((c) => c.text || "").join(" ");
      throw new Error(t || "Tool error");
    }
    return structured(r);
  }

  const sendMessage = (text) =>
    request("ui/message", { role: "user", content: [{ type: "text", text }] });

  return { init, callTool, sendMessage };
})();
