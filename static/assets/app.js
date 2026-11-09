/* ==========================================================================
   Rozaneh · روزنه — panel application (v1.08)
   Vanilla ES2019+, no build step, no external assets.
   ========================================================================== */
(function () {
  "use strict";

  /* ── tiny helpers ─────────────────────────────────────────────────────── */

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.prototype.slice.call((root || document).querySelectorAll(sel));
  const h = (v) =>
    v == null
      ? ""
      : String(v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const I18N = window.ROZANEH_I18N || { fa: {}, en: {} };
  const LS_LANG = "rz.lang";
  const LS_THEME = "rz.theme";

  const S = {
    meta: null,
    lang: "fa",
    theme: "slate",
    route: "dashboard",
    adminTab: "links",
    feeds: [],
    topics: [],
    dests: [],
    jobs: [],
    analyses: [],
    currentAnalysis: null,
    settings: {},
    creators: [],
    edu: null,
    creatorEditor: { configured: false, authenticated: false, botConfigured: false },
    archive: { status: "all", q: "" },
    draft: null,
  };

  const COLORS = {
    teal: "#2dd4bf", sky: "#38bdf8", amber: "#f59e0b", rose: "#fb7185",
    violet: "#a78bfa", emerald: "#34d399", orange: "#fb923c", slate: "#94a3b8",
  };
  const ICO_CHEV = '<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>';
  const EMOJIS = ["📰", "🌍", "💹", "⚽", "🎬", "🧪", "🏛️", "💻", "🩺", "✈️", "🔥", "📡"];

  function tint(hex, a) {
    const n = parseInt((hex || "#94a3b8").slice(1), 16);
    return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")";
  }
  function colorOf(name) { return COLORS[name] || COLORS.slate; }
  function t(key, params) {
    const dict = I18N[S.lang] || I18N.fa;
    let out = dict[key] != null ? dict[key] : (I18N.fa[key] != null ? I18N.fa[key] : key);
    if (params) out = out.replace(/\{(\w+)\}/g, (m, k) => (params[k] !== undefined && params[k] !== null ? params[k] : m));
    return out;
  }
  const isFa = () => S.lang === "fa";
  function num(v) {
    const n = Number(v || 0);
    try { return n.toLocaleString(isFa() ? "fa-IR" : "en-US"); } catch (e) { return String(n); }
  }
  function panelTimezone() {
    return (S.settings && S.settings.timezone) || (S.meta && S.meta.defaults && S.meta.defaults.timezone) || "UTC";
  }
  function fmtDate(iso, withTime) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    const opt = { year: "numeric", month: "short", day: "2-digit", timeZone: panelTimezone() };
    if (withTime !== false) { opt.hour = "2-digit"; opt.minute = "2-digit"; }
    try {
      const out = d.toLocaleString(isFa() ? "fa-IR" : "en-US", opt);
      return isFa() ? out.replace(/,\s*/g, "، ") : out;
    } catch (e) { return d.toISOString(); }
  }
  function fmtTime(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    try { return d.toLocaleTimeString(isFa() ? "fa-IR" : "en-US", { hour: "2-digit", minute: "2-digit", timeZone: panelTimezone() }); }
    catch (e) { return d.toISOString().slice(11, 16); }
  }
  function fmtLogTime(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso).slice(0, 16);
    const today = new Date().toDateString() === d.toDateString();
    const loc = isFa() ? "fa-IR" : "en-US";
    try {
      if (today) return d.toLocaleTimeString(loc, { hour: "2-digit", minute: "2-digit" });
      return d.toLocaleDateString(loc, { month: "short", day: "2-digit" }) + " " +
        d.toLocaleTimeString(loc, { hour: "2-digit", minute: "2-digit" });
    } catch (e) { return d.toISOString().slice(5, 16).replace("T", " "); }
  }
  function relTime(iso) {
    if (!iso) return t("common.never");
    const d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    const diff = (d.getTime() - Date.now()) / 1000;
    const abs = Math.abs(diff);
    const rtf = (() => { try { return new Intl.RelativeTimeFormat(isFa() ? "fa" : "en", { numeric: "auto" }); } catch (e) { return null; } })();
    const units = [["day", 86400], ["hour", 3600], ["minute", 60]];
    for (const [unit, secs] of units) {
      if (abs >= secs || unit === "minute") {
        const val = Math.round(diff / secs);
        return rtf ? rtf.format(val, unit) : String(val) + " " + unit;
      }
    }
    return fmtDate(iso);
  }
  /* Render a Telegram-style HTML message safely inside the panel. */
  function prettyHtml(raw) {
    let out = h(String(raw || ""));
    out = out.replace(/&lt;b&gt;([\s\S]*?)&lt;\/b&gt;/gi, "<b>$1</b>");
    out = out.replace(/&lt;strong&gt;([\s\S]*?)&lt;\/strong&gt;/gi, "<b>$1</b>");
    out = out.replace(/&lt;i&gt;([\s\S]*?)&lt;\/i&gt;/gi, "<em>$1</em>");
    out = out.replace(/&lt;em&gt;([\s\S]*?)&lt;\/em&gt;/gi, "<em>$1</em>");
    out = out.replace(/&lt;code&gt;([\s\S]*?)&lt;\/code&gt;/gi, "<code>$1</code>");
    out = out.replace(
      /&lt;a\s+href=&quot;([^"&]+)&quot;[^&]*?&gt;([\s\S]*?)&lt;\/a&gt;/gi,
      '<a href="$1" target="_blank" rel="noopener">$2</a>'
    );
    out = out.replace(/&lt;br\s*\/?&gt;/gi, "<br>");
    return out;
  }

  function safeJson(raw, fallback) {
    if (Array.isArray(raw)) return raw;
    if (raw == null || raw === "") return fallback;
    try { const v = JSON.parse(raw); return v == null ? fallback : v; } catch (e) { return fallback; }
  }
  function uptime(sec) {
    sec = Number(sec || 0);
    const d = Math.floor(sec / 86400), hr = Math.floor((sec % 86400) / 3600), mn = Math.floor((sec % 3600) / 60);
    if (isFa()) return (d ? d + " روز " : "") + (hr ? hr + " ساعت " : "") + mn + " دقیقه";
    return (d ? d + "d " : "") + (hr ? hr + "h " : "") + mn + "m";
  }
  function bytes(n) {
    n = Number(n || 0);
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
    return (n / 1048576).toFixed(2) + " MB";
  }

  /* ── icons ────────────────────────────────────────────────────────────── */

  const P = {
    grid: '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
    newspaper: '<path d="M4 3h16v18H4z"/><path d="M8 7h8M8 11h8M8 15h5"/><path d="M2 7v13a2 2 0 0 0 2 2"/>',
    rss: '<path d="M4 11a9 9 0 0 1 9 9"/><path d="M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1.4"/>',
    tag: '<path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L2 12V2h10l8.6 8.6a2 2 0 0 1 0 2.8z"/><circle cx="7" cy="7" r="1.3"/>',
    send: '<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4z"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.2 2"/>',
    inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1z"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13"/><path d="M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
    sliders: '<path d="M4 21v-6M4 11V3M12 21v-9M12 8V3M20 21v-4M20 13V3"/><path d="M1.5 15h5M9.5 8h5M17.5 17h5"/>',
    shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
    users: '<circle cx="9" cy="8" r="3.6"/><path d="M2.5 21v-1a6.5 6.5 0 0 1 13 0v1"/><path d="M16.5 4.6a3.6 3.6 0 0 1 0 6.8"/><path d="M18 21v-1a6.6 6.6 0 0 0-2-4.7"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/>',
    play: '<path d="M7 4.5 19.5 12 7 19.5z"/>',
    eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
    trash: '<path d="M3 6h18M8 6V4h8v2"/><path d="M6 6l1 14h10l1-14"/>',
    edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    external: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6"/><path d="M10 14 21 3"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>',
    upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5"/><path d="M12 3v12"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 0 1 0 18 14 14 0 0 1 0-18z"/>',
    sun: '<circle cx="12" cy="12" r="4.2"/><path d="M12 2v2M12 20v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M2 12h2M20 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"/>',
    palette: '<path d="M12 3a9 9 0 1 0 0 18h1.2a2 2 0 0 0 1.5-3.3 1.9 1.9 0 0 1 1.5-3.1h.8A4 4 0 0 0 21 10.7 7.7 7.7 0 0 0 12 3z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10" cy="7.5" r="1"/><circle cx="15" cy="8" r="1"/>',
    moon: '<path d="M21 12.8A8.6 8.6 0 1 1 11.2 3a6.6 6.6 0 0 0 9.8 9.8z"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.6-3.6"/>',
    image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/>',
    alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>',
    link: '<path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>',
    layers: '<path d="M12 2 2 7l10 5 10-5z"/><path d="M2 17l10 5 10-5M2 12l10 5 10-5"/>',
    activity: '<path d="M22 12h-4l-3 8-4-16-3 8H2"/>',
    database: '<ellipse cx="12" cy="5.5" rx="8.5" ry="3"/><path d="M3.5 5.5v13c0 1.7 3.8 3 8.5 3s8.5-1.3 8.5-3v-13"/><path d="M3.5 12c0 1.7 3.8 3 8.5 3s8.5-1.3 8.5-3"/>',
    key: '<circle cx="7.5" cy="16.5" r="4"/><path d="M10.5 13.5 21 3"/><path d="M16 4l3 3M18.5 6.5 21 4"/>',
    logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>',
    filter: '<path d="M22 3H2l8 9.5V19l4 2v-8.5z"/>',
    copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    zap: '<path d="M13 2 3 14h7l-1 8 10-12h-7z"/>',
    folder: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
    mail: '<rect x="2" y="4" width="20" height="16" rx="2.5"/><path d="M22 6.5 12 13.5 2 6.5"/>',
    code: '<path d="M16 18l6-6-6-6M8 6l-6 6 6 6"/>',
    arrowUp: '<path d="M12 19V5M5 12l7-7 7 7"/>',
    arrowDown: '<path d="M12 5v14M5 12l7 7 7-7"/>',
    sparkles: '<path d="M12 3l1.9 4.6L18.5 9.5 13.9 11.4 12 16l-1.9-4.6L5.5 9.5l4.6-1.9z"/><path d="M18.5 16.5l.8 1.9 1.9.8-1.9.8-.8 1.9-.8-1.9-1.9-.8 1.9-.8z"/>',
    book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
    server: '<rect x="2" y="3" width="20" height="7" rx="2"/><rect x="2" y="14" width="20" height="7" rx="2"/><path d="M6 6.5h.01M6 17.5h.01"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2.5"/><path d="M16 3v4M8 3v4M3 11h18"/>',
    radio: '<circle cx="12" cy="12" r="2"/><path d="M5 19a10 10 0 0 1 0-14M19 5a10 10 0 0 1 0 14M8 16a6 6 0 0 1 0-8M16 8a6 6 0 0 1 0 8"/>',
    telegram: '<path d="M21.6 3.4 2.5 10.9c-1 .4-1 1.7.1 2l4.6 1.5 1.8 5.4c.3.9 1.4 1.1 2 .4l2.4-2.5 4.6 3.4c.8.6 1.9.1 2.1-.9l3-15c.2-1-.8-1.8-1.5-1.8zM8.6 14.2l9.4-6.8-7.2 7.6-.3 3.1z"/>',
    bale: '<path d="M20.5 11.6a8.5 8.5 0 0 1-8.9 8.4 9 9 0 0 1-3.9-.9L3 21l1.8-4.6A8.4 8.4 0 0 1 12 3h.6a8.4 8.4 0 0 1 7.9 8.6z"/><path d="M8.4 9.5h7.2M8.4 13.4h4.6"/>',
    eitaa: '<path d="M3 5.5 21 12 3 18.5l2.6-6.5z"/><path d="M5.6 12 21 12"/>',
    rubika: '<path d="M12 2.4 21.6 12 12 21.6 2.4 12z"/><path d="M12 7.5 16.5 12 12 16.5 7.5 12z"/>',
    webhook: '<path d="M12 3v6"/><path d="M6.3 6.3 9 9"/><path d="M3 12h6"/><circle cx="12" cy="16" r="4"/><path d="M12 20v1"/>',
    hash: '<path d="M4 9h16M4 15h16M10 3 8 21M16 3l-2 18"/>',
    bookmark: '<path d="M6 3h12a1 1 0 0 1 1 1v17l-7-4.5L5 21V4a1 1 0 0 1 1-1z"/>',
    message: '<path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 9 9 0 0 1-3.9-.9L3 21l1.9-4.6A8.4 8.4 0 0 1 12 3h1a8.4 8.4 0 0 1 8 8.5z"/>',
  };
  const FILLED = {
    play: '<path d="M7 4.5 19.5 12 7 19.5z"/>',
    telegram: P.telegram,
    eitaa: P.eitaa,
    rubika: P.rubika,
    sparkles: P.sparkles,
  };
  function ico(name, cls) {
    const filled = FILLED[name];
    const body = filled || P[name] || P.grid;
    const attrs = filled
      ? 'fill="currentColor" stroke="none"'
      : 'fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"';
    return '<svg viewBox="0 0 24 24" class="' + (cls || "") + '" aria-hidden="true" ' + attrs + ">" + body + "</svg>";
  }
  function platIcon(id) {
    const map = { telegram: "telegram", bale: "bale", eitaa: "eitaa", rubika: "rubika", webhook: "webhook" };
    return ico(map[id] || "send");
  }
  function platName(p) {
    if (!p) return "";
    return isFa() ? p.name_fa : p.name_en;
  }
  function platform(id) {
    const list = (S.meta && S.meta.platforms) || [];
    return list.find((p) => p.id === id) || { id: id, name_fa: id, name_en: id, supports_photo: false };
  }

  /* ── http ─────────────────────────────────────────────────────────────── */

  async function api(path, opts) {
    opts = opts || {};
    const init = { method: opts.method || "GET", credentials: "same-origin", headers: {} };
    if (opts.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    let res;
    try {
      res = await fetch(path, init);
    } catch (e) {
      throw new Error("network_error");
    }
    if (res.status === 401 && !path.startsWith("/api/creators/auth/")) {
      location.replace("/login");
      throw new Error("auth_required");
    }
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (!res.ok) throw new Error((data && data.detail) || "unknown");
    return data;
  }
  function errMsg(e) {
    const code = (e && e.message) || "unknown";
    const dict = I18N[S.lang] || I18N.fa;
    return dict["err." + code] || code;
  }

  /* ── toast / modal ────────────────────────────────────────────────────── */

  function toast(msg, kind) {
    const box = $("#toastRoot") || $("#toasts");
    if (!box) return;
    const el = document.createElement("div");
    el.className = "toast " + (kind || "info");
    const icon = kind === "ok" ? "check" : kind === "err" ? "alert" : "info";
    el.innerHTML = '<span class="ti">' + ico(icon) + "</span><span>" + h(msg) + "</span>";
    box.appendChild(el);
    setTimeout(() => {
      el.classList.add("out");
      setTimeout(() => el.remove(), 260);
    }, kind === "err" ? 5200 : 3200);
  }

  let MODAL_ONCLOSE = null;
  function openModal(cfg) {
    const root = $("#modalRoot");
    MODAL_ONCLOSE = cfg.onClose || null;
    root.innerHTML =
      '<div class="modal-back" data-act="modal.backdrop">' +
        '<div class="modal' + (cfg.wide ? " wide" : "") + '" role="dialog" aria-modal="true">' +
          '<div class="modal-head"><h3>' + h(cfg.title || "") + "</h3>" +
            '<button class="x" data-act="modal.close" aria-label="close">' + ico("x") + "</button></div>" +
          '<div class="modal-body">' + (cfg.body || "") + "</div>" +
          (cfg.footer ? '<div class="modal-foot">' + cfg.footer + "</div>" : "") +
        "</div>" +
      "</div>";
    document.body.style.overflow = "hidden";
    if (typeof cfg.onMount === "function") {
      try { cfg.onMount(); } catch (e) { console.warn("modal onMount", e); }
    }
  }
  function closeModal() {
    $("#modalRoot").innerHTML = "";
    document.body.style.overflow = "";
    if (MODAL_ONCLOSE) { const fn = MODAL_ONCLOSE; MODAL_ONCLOSE = null; fn(); }
  }
  function confirmModal(message, onYes, danger) {
    openModal({
      title: t("common.confirm"),
      body: '<p style="margin:0;font-size:13px;line-height:1.8">' + h(message) + "</p>",
      footer:
        '<button class="btn ghost" data-act="modal.close">' + t("common.cancel") + "</button>" +
        '<button class="btn ' + (danger === false ? "primary" : "danger") + '" data-act="modal.yes">' + t("common.confirm") + "</button>",
    });
    $("#modalRoot").dataset.yes = "1";
    ACTIONS["modal.yes"] = async () => { closeModal(); await onYes(); };
  }

  /* ── chrome ───────────────────────────────────────────────────────────── */

  function applyTheme() {
    const themes = ["slate", "cyber", "emerald", "amber"];
    if (!themes.includes(S.theme)) S.theme = "slate";
    document.documentElement.dataset.theme = S.theme;
    $$(".theme-choice").forEach((button) => {
      const active = button.dataset.t === S.theme;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", S.theme === "amber" ? "#f3f5fa" : "#070b14");
  }

  function applyLang() {
    document.documentElement.lang = S.lang;
    document.documentElement.dir = isFa() ? "rtl" : "ltr";
    const brand = (S.meta && S.meta.defaults && S.meta.defaults.panel_title) || t("app.name");
    document.title = brand + " · Rozaneh";
    const brandNode = $("#brandTitle");
    if (brandNode) brandNode.textContent = brand;
    const languageButton = $("#langBtn");
    if (languageButton) languageButton.textContent = isFa() ? "EN" : "فا";
    const logout = $("#logoutBtn");
    if (logout) logout.textContent = t("nav.logout");
    const quickAnalyze = $("#quickAnalyzeBtn");
    if (quickAnalyze) quickAnalyze.textContent = "✨ " + t("top.quickAnalyze");
    const refresh = $("#refreshBtn");
    if (refresh) refresh.title = t("top.refresh");
    $$("[data-theme-label]").forEach((label) => {
      label.textContent = t("theme.short." + label.dataset.themeLabel);
    });
    $$(".theme-choice[data-theme-title]").forEach((button) => {
      const title = t("theme." + button.dataset.themeTitle);
      button.title = title;
      button.setAttribute("aria-label", title);
    });
    const themePopover = $("#themePopover");
    if (themePopover) themePopover.setAttribute("aria-label", t("top.theme"));
    const live = $("#liveTxt");
    if (live) live.textContent = t("nav.live");
    renderNav();
  }

  function setLang(lang) {
    S.lang = lang === "en" ? "en" : "fa";
    localStorage.setItem(LS_LANG, S.lang);
    applyLang();
    api("/api/settings", { method: "PATCH", body: { language: S.lang } }).catch(() => {});
    render();
  }

  function setTheme(theme) {
    S.theme = ["slate", "cyber", "emerald", "amber"].includes(theme) ? theme : "slate";
    localStorage.setItem(LS_THEME, S.theme);
    applyTheme();
    api("/api/settings", { method: "PATCH", body: { theme: S.theme } }).catch(() => {});
  }

  const NAV_SECTIONS = [
    { label: "nav.group.main", items: [
      { id: "dashboard", icon: "grid", label: "nav.dashboard" },
      { id: "analyzer", icon: "sparkles", label: "nav.analyzer", badge: "nav.badge.ai" },
      { id: "items", icon: "inbox", label: "nav.items" },
    ]},
    { label: "nav.group.config", items: [
      { id: "feeds", icon: "rss", label: "nav.feeds" },
      { id: "topics", icon: "tag", label: "nav.topics" },
      { id: "channels", icon: "send", label: "nav.destinations" },
      { id: "jobs", icon: "clock", label: "nav.jobs" },
    ]},
    { label: "nav.group.system", items: [
      { id: "settings", icon: "sliders", label: "nav.settings" },
      { id: "admin", icon: "shield", label: "nav.admin" },
      { id: "creators", icon: "users", label: "nav.creators" },
    ]},
  ];

  function renderNav() {
    const nav = $("#nav");
    if (!nav) return;
    nav.innerHTML = NAV_SECTIONS.map((section) =>
      '<div class="nav-group">' + h(t(section.label)) + "</div>" +
      section.items.map((item) => {
        const active = S.route === item.id || (item.id === "items" && S.route === "archive");
        return '<a href="#/' + item.id + '" data-act="nav.item" data-page="' + item.id + '"' +
          (active ? ' class="active" aria-current="page"' : "") + '>' +
          ico(item.icon) + '<span>' + h(t(item.label)) + '</span>' +
          (item.badge ? '<span class="badge ai-badge">' + h(t(item.badge)) + '</span>' : "") +
          "</a>";
      }).join("")
    ).join("");
  }

  function fitNav() {
    const nav = $("#nav");
    if (!nav) return;
    document.body.classList.remove("nav-tight", "nav-compact", "nav-off");
    if (window.innerWidth <= 1180) return;
    const overflowing = () => {
      const items = Array.prototype.slice.call(nav.children);
      if (!items.length) return false;
      const box = nav.getBoundingClientRect();
      const last = items[items.length - 1].getBoundingClientRect();
      const rtl = getComputedStyle(nav).direction === "rtl";
      return rtl ? last.left < box.left - 1 : last.right > box.right + 1;
    };
    document.body.classList.add("nav-tight");
    if (!overflowing()) return;
    document.body.classList.add("nav-compact");
    if (!overflowing()) return;
    document.body.classList.add("nav-off");
  }

  function dropItem(it, mobile) {
    const label = t(it.label);
    const desc = it.desc ? t(it.desc) : "";
    let attrs = 'data-act="';
    if (it.act) attrs += it.act + '"';
    else attrs += "nav.item\" data-page=\"" + (it.page || S.route) + '"';
    if (it.tab) attrs += ' data-tab="' + it.tab + '"';
    if (it.anchor) attrs += ' data-anchor="' + it.anchor + '"';
    return (
      '<button class="ditem" ' + attrs + ">" +
        '<span class="di">' + ico(it.icon) + "</span>" +
        '<span class="dtext"><b>' + h(label) + "</b>" + (desc ? "<span>" + h(desc) + "</span>" : "") + "</span>" +
      "</button>"
    );
  }

  function wireChrome() {
    const langBtn = $("#langBtn");
    if (langBtn) langBtn.addEventListener("click", () => setLang(isFa() ? "en" : "fa"));

    const themeSwitch = $("#themeSwitch");
    if (themeSwitch) themeSwitch.addEventListener("click", (ev) => {
      const choice = ev.target.closest("[data-t]");
      if (choice) {
        setTheme(choice.dataset.t);
        const popover = $("#themePopover");
        const trigger = $("#themeToggle");
        if (popover) popover.hidden = true;
        if (trigger) trigger.setAttribute("aria-expanded", "false");
        return;
      }
      if (ev.target.closest("#themeToggle")) {
        const popover = $("#themePopover");
        const trigger = $("#themeToggle");
        if (popover) popover.hidden = !popover.hidden;
        if (trigger) trigger.setAttribute("aria-expanded", popover && !popover.hidden ? "true" : "false");
      }
    });
    document.addEventListener("click", (ev) => {
      if (themeSwitch && !themeSwitch.contains(ev.target)) {
        const popover = $("#themePopover");
        const trigger = $("#themeToggle");
        if (popover) popover.hidden = true;
        if (trigger) trigger.setAttribute("aria-expanded", "false");
      }
    });

    const logout = $("#logoutBtn");
    if (logout) logout.addEventListener("click", async () => {
      try { await api("/api/logout", { method: "POST" }); } catch (e) {}
      location.replace("/login");
    });

    const refresh = $("#refreshBtn");
    if (refresh) refresh.addEventListener("click", () => render());
    const quickAnalyze = $("#quickAnalyzeBtn");
    if (quickAnalyze) quickAnalyze.addEventListener("click", () => go("analyzer"));

    const menuBtn = $("#menuBtn");
    if (menuBtn) menuBtn.addEventListener("click", () => {
      const sidebar = $("#sidebar");
      if (sidebar) sidebar.classList.toggle("open");
    });

    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") {
        if ($("#modalRoot") && $("#modalRoot").innerHTML) closeModal();
        const sidebar = $("#sidebar");
        if (sidebar) sidebar.classList.remove("open");
        const themePopover = $("#themePopover");
        const themeToggle = $("#themeToggle");
        if (themePopover) themePopover.hidden = true;
        if (themeToggle) themeToggle.setAttribute("aria-expanded", "false");
      }
    });
    window.addEventListener("hashchange", () => {
      const route = (location.hash || "").replace(/^#\/?/, "") || "dashboard";
      if (route !== S.route) {
        S.route = PAGES[route] ? route : "dashboard";
        renderNav();
        render();
      }
    });
  }

  /* ── routing ──────────────────────────────────────────────────────────── */

  const PAGES = {
    dashboard: renderDashboard,
    analyzer: renderAnalyzer,
    feeds: renderFeeds,
    topics: renderTopics,
    channels: renderChannels,
    jobs: renderJobs,
    items: renderArchive,
    archive: renderArchive,
    logs: renderLogs,
    settings: renderSettings,
    admin: renderAdmin,
    creators: renderCreators,
  };

  async function go(page, tab) {
    S.route = PAGES[page] ? page : "dashboard";
    if (tab) S.adminTab = tab;
    if (location.hash !== "#/" + S.route) location.hash = "#/" + S.route;
    renderNav();
    const sidebar = $("#sidebar");
    if (sidebar) sidebar.classList.remove("open");
    const anchor = arguments[2];
    await render(anchor);
    if (anchor) {
      const el = document.getElementById(anchor);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  async function render(anchor) {
    const view = $("#view") || $("#main");
    if (!view) return;
    const fn = PAGES[S.route] || renderDashboard;
    try {
      await fn(view);
    } catch (e) {
      view.innerHTML =
        '<div class="card"><div class="card-body"><div class="banner bad">' + ico("alert") +
        "<span>" + h(errMsg(e)) + "</span></div></div></div>";
    }
    if (anchor) {
      const el = document.getElementById(anchor);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  function pageHead(title, sub, actions) {
    const titleNode = $("#pageTitle");
    const subNode = $("#pageSub");
    if (titleNode) titleNode.textContent = title;
    if (subNode) subNode.textContent = sub || "";
    return (
      '<div class="page-intro"><div class="page-intro-copy"><h2>' + h(title) + "</h2><p>" + h(sub || "") + "</p></div>" +
      '<div class="page-actions">' + (actions || "") + "</div></div>"
    );
  }
  function btn(label, act, opts) {
    opts = opts || {};
    return (
      '<button class="btn ' + (opts.cls || "ghost") + (opts.sm ? " sm" : "") + '" data-act="' + act + '"' +
      (opts.id !== undefined ? ' data-id="' + opts.id + '"' : "") +
      (opts.extra || "") + ">" +
      (opts.icon ? ico(opts.icon) : "") + (label ? "<span>" + h(label) + "</span>" : "") +
      "</button>"
    );
  }
  function iconBtn(icon, act, id, cls, title) {
    return (
      '<button class="btn xs icon ' + (cls || "ghost") + '" data-act="' + act + '" data-id="' + id + '" title="' +
      h(title || "") + '">' + ico(icon) + "</button>"
    );
  }
  function toggleEl(name, on, act, id, extra) {
    return '<button type="button" class="toggle' + (on ? " on" : "") + '" data-act="' + (act || "tg") + '" data-tg="' + name +
      '"' + (id !== undefined && id !== null ? ' data-id="' + id + '"' : "") + ' aria-pressed="' +
      (on ? "true" : "false") + '"' + (extra || "") + "></button>";
  }
  function field(label, input, hint) {
    return (
      '<div class="field"><label>' + h(label) + "</label>" + input +
      (hint ? '<small class="fhint">' + h(hint) + "</small>" : "") + "</div>"
    );
  }
  function emptyBox(icon, title, text, action) {
    return (
      '<div class="empty"><div class="ei">' + ico(icon) + "</div><b>" + h(title) + "</b><p>" + h(text || "") + "</p>" +
      (action || "") + "</div>"
    );
  }
  function card(title, icon, body, extraHead) {
    return (
      '<section class="card"><div class="card-head"><h2>' + ico(icon) + h(title) + "</h2>" +
      (extraHead || "") + '</div><div class="card-body' + (extraHead === false ? " flush" : "") + '">' + body + "</div></section>"
    );
  }

  /* ── loaders ──────────────────────────────────────────────────────────── */

  async function loadFeeds() { S.feeds = (await api("/api/feeds")).feeds || []; return S.feeds; }
  async function loadTopics() { S.topics = (await api("/api/topics")).topics || []; return S.topics; }
  async function loadDests() { S.dests = (await api("/api/destinations")).destinations || []; return S.dests; }
  async function loadJobs() { S.jobs = (await api("/api/jobs")).jobs || []; return S.jobs; }
  async function loadSettings() { S.settings = (await api("/api/settings")).settings || {}; return S.settings; }

  /* ── dashboard ────────────────────────────────────────────────────────── */

  async function renderDashboard(view) {
    view.innerHTML = '<div class="card"><div class="card-body"><div class="skeleton" style="width:42%"></div></div></div>';
    const d = await api("/api/dashboard");
    const c = d.counts || {};
    const schedulerOn = Boolean(d.scheduler && d.scheduler.enabled);
    const recent = (d.recent_items || []).slice(0, 6);
    const analyses = d.recent_analyses || [];
    const logs = (d.logs || []).slice(0, 7);

    const stat = (label, value, sub, icon) =>
      '<div class="stat"><div class="stat-top"><span>' + h(label) + '</span><span class="stat-ico">' + ico(icon) +
      '</span></div><div class="stat-val">' + num(value || 0) + '</div><div class="stat-sub">' + h(sub || "") + '</div></div>';

    const headActions =
      btn(t("top.quickRun"), "runAll", { cls: "primary", icon: "play" }) +
      btn(t("top.refresh"), "reload", { cls: "ghost", icon: "refresh" });
    let html = pageHead(t("dash.title"), t("dash.sub"), headActions);

    html += '<section class="hero-banner"><div class="hero-top"><div>' +
      '<h2 class="hero-title">' + h(t("dash.hero.title")) + '</h2>' +
      '<p class="hero-sub">' + h(t("dash.hero.sub")) + '</p></div>' +
      '<span class="pill ' + (schedulerOn ? 'ok' : 'warn') + '"><span class="pulse"></span>' +
      h(schedulerOn ? t("dash.scheduler_on") : t("dash.scheduler_off")) + '</span></div>' +
      '<div class="hero-quickbar"><input id="dashAnalyzeInput" type="url" dir="ltr" placeholder="' + h(t("dash.hero.analyzePlaceholder")) + '">' +
      '<button class="btn btn-primary" type="button" data-act="analyzer.quick">' + ico("sparkles") + '<span>' +
      h(t("dash.hero.analyzeBtn")) + '</span></button></div></section>';

    html += '<div class="stats">' +
      stat(t("dash.kpi.feeds"), c.feeds, t("dash.kpi.feedsSub", { total: num(c.feeds_total) }), "rss") +
      stat(t("dash.kpi.destinations"), c.destinations, t("dash.kpi.destinationsSub"), "send") +
      stat(t("dash.kpi.sent"), c.sent, t("dash.kpi.sentSub", { img: num(c.with_image || 0) }), "check") +
      stat(t("dash.kpi.translated"), c.analyses, t("dash.kpi.translatedSub", { analyses: num(c.analyses), filtered: num(c.filtered) }), "sparkles") +
      '</div>';

    const byDay = {};
    (d.activity || []).forEach((row) => { byDay[row.day] = row; });
    let bars = "";
    for (let i = 13; i >= 0; i--) {
      const date = new Date(Date.now() - i * 86400000);
      const key = date.toISOString().slice(0, 10);
      const row = byDay[key] || { sent: 0, failed: 0, filtered: 0, total: 0 };
      const max = Math.max(1, ...Object.values(byDay).map((x) => Number(x.total || 0)));
      const height = Math.max(4, Math.round(Number(row.total || 0) / max * 100));
      bars += '<div class="bar-col" title="' + h(key) + ' · ' + num(row.total || 0) + '"><div class="bar-stack">' +
        '<span class="bar" style="height:' + height + '%"></span></div><span class="bar-lbl">' + key.slice(8) + '</span></div>';
    }

    const upcoming = d.upcoming || [];
    const scheduleCard = '<section class="card"><div class="card-head"><div><h2 class="card-title">' +
      ico("calendar") + h(t("dash.upcoming")) + '</h2><p class="card-sub">' + h(schedulerOn ? t("dash.scheduler_on") : t("dash.scheduler_off")) +
      '</p></div><a class="btn btn-sm" href="#/jobs" data-act="nav.item" data-page="jobs">' + h(t("nav.jobs")) + '</a></div>' +
      '<div class="card-body">' + (upcoming.length ? '<div class="stack">' + upcoming.map((job) =>
        '<div class="spread"><div class="inline"><span class="pill brand mono">' + h(fmtTime(job.next_run)) + '</span><b>' + h(job.name) +
        '</b></div><span class="tiny mute">' + h(relTime(job.next_run)) + '</span></div>').join("") + '</div>' :
        '<div class="empty">' + h(t("dash.noUpcoming")) + '</div>') + '</div></section>';

    const activityCard = '<section class="card"><div class="card-head"><div><h2 class="card-title">' +
      ico("activity") + h(t("dash.activity")) + '</h2><p class="card-sub">' + h(t("dash.activitySub")) + '</p></div></div>' +
      '<div class="card-body"><div class="bars">' + bars + '</div><div class="imeta" style="margin-top:12px">' +
      '<span class="pill ok">' + h(t("items.status.sent")) + ' · ' + num(c.sent) + '</span>' +
      '<span class="pill warn">' + h(t("items.status.filtered")) + ' · ' + num(c.filtered) + '</span>' +
      '<span class="pill err">' + h(t("items.status.failed")) + ' · ' + num(c.failed) + '</span></div></div></section>';

    const recentCard = '<section class="card"><div class="card-head"><div><h2 class="card-title">' +
      ico("inbox") + h(t("dash.recent")) + '</h2><p class="card-sub">' + h(t("dash.noRecent").split(";")[0]) + '</p></div>' +
      '<a class="btn btn-sm" href="#/items" data-act="nav.item" data-page="items">' + h(t("items.title")) + '</a></div>' +
      '<div class="card-body flush"><div class="rows">' + (recent.length ? recent.map((item) => itemRow(item, { compact: true })).join("") :
        '<div class="empty">' + h(t("dash.noRecent")) + '</div>') + '</div></div></section>';

    const analysisCard = '<section class="card"><div class="card-head"><div><h2 class="card-title">' +
      ico("sparkles") + h(t("an.history")) + '</h2></div><a class="btn btn-sm" href="#/analyzer" data-act="nav.item" data-page="analyzer">' +
      h(t("nav.analyzer")) + '</a></div><div class="card-body">' + (analyses.length ? '<div class="stack">' + analyses.map((a) =>
      '<button class="analysis-history-row" type="button" data-act="analyzer.open" data-id="' + a.id + '"><span class="pill brand">' +
      h(a.platform || "web") + '</span><span class="analysis-history-title">' + h(a.title || a.url) + '</span><span class="tiny mute">' +
      h(relTime(a.created_at)) + '</span></button>').join("") + '</div>' : '<div class="empty">' + h(t("an.empty")) + '</div>') + '</div></section>';

    const logsCard = '<section class="card"><div class="card-head"><div><h2 class="card-title">' +
      ico("list") + h(t("dash.logs")) + '</h2></div><a class="btn btn-sm" href="#/logs" data-act="nav.item" data-page="logs">' +
      h(t("logs.title")) + '</a></div><div class="card-body flush">' + (logs.length ? logs.map(logLine).join("") :
      '<div class="empty">' + h(t("dash.noLogs")) + '</div>') + '</div></section>';

    html += '<div class="grid cols-2 dashboard-panels"><div class="stack">' + scheduleCard + activityCard + '</div><div class="stack">' +
      recentCard + analysisCard + logsCard + '</div></div>';
    view.innerHTML = html;
  }

  let ANALYZER_POLL_TIMER = null;
  let ANALYZER_MODEL_FETCH = null;

  function stopAnalyzerPolling() {
    if (ANALYZER_POLL_TIMER) clearTimeout(ANALYZER_POLL_TIMER);
    ANALYZER_POLL_TIMER = null;
  }

  function startAnalyzerPolling(id) {
    stopAnalyzerPolling();
    const poll = async () => {
      try {
        const response = await api("/api/analyzer/" + id);
        S.currentAnalysis = response.analysis;
        if (S.route === "analyzer") {
          const root = $("#analysisResult");
          if (root) root.innerHTML = renderAnalysisDetail(S.currentAnalysis);
          if (S.currentAnalysis.status !== "processing") {
            const history = $("#analysisHistory");
            if (history) {
              const rows = await api("/api/analyzer?limit=40");
              S.analyses = rows.analyses || [];
              history.innerHTML = renderAnalysisHistory(S.analyses);
            }
          }
        }
        if (S.currentAnalysis && S.currentAnalysis.status === "processing") {
          ANALYZER_POLL_TIMER = setTimeout(poll, 1800);
        } else {
          ANALYZER_POLL_TIMER = null;
        }
      } catch (error) {
        if (S.route === "analyzer") toast(errMsg(error), "err");
        ANALYZER_POLL_TIMER = null;
      }
    };
    poll();
  }

  async function renderAnalyzer(view) {
    view.innerHTML = '<div class="card"><div class="card-body"><div class="skeleton" style="width:55%"></div></div></div>';
    const [list, _dests, settings] = await Promise.all([api("/api/analyzer?limit=40"), loadDests(), loadSettings()]);
    S.settings = settings || {};
    S.analyses = list.analyses || [];
    if (S.currentAnalysis) {
      const fresh = S.analyses.find((a) => Number(a.id) === Number(S.currentAnalysis.id));
      if (fresh) S.currentAnalysis = fresh;
    } else if (S.analyses.length) {
      S.currentAnalysis = S.analyses[0];
    }

    const aiSettings = S.settings || {};
    const analysisProvider = aiSettings.analysis_api_provider === "deepseek" ||
      String(aiSettings.analysis_api_base_url || "").toLowerCase().includes("api.deepseek.com") ? "deepseek" : "openai_compatible";
    const aiReady = Boolean(aiSettings.analysis_api_key_set || aiSettings.deepseek_key_set || aiSettings.openai_key_set);
    const imageApiReady = String(aiSettings.image_generation_enabled || "0") === "1" && Boolean(aiSettings.image_api_key_set);
    const aiStatusText = aiReady ? t("an.aiConfigured") : t("an.aiMissing");
    const form = '<section class="card analyzer-input-card"><div class="card-head"><div><h2 class="card-title">' + ico("link") +
      h(t("an.inputLabel")) + '</h2><p class="card-sub">' + h(t("an.sub")) + '</p></div></div><div class="card-body">' +
      '<form class="form" data-form="analyzer" id="analyzerForm">' +
      '<div class="field"><label for="analysisUrl">' + h(t("an.inputLabel")) + '</label><input class="input ltr" type="url" id="analysisUrl" name="url" required placeholder="' + h(t("an.inputPh")) + '"></div>' +
      '<div class="field"><label for="analysisCustomText">' + h(t("an.customLabel")) + '</label><textarea class="input" id="analysisCustomText" name="custom_text" rows="3" placeholder="' + h(t("an.customPh")) + '"></textarea></div>' +
      '<div class="analyzer-options"><label class="analyzer-option"><input type="checkbox" name="include_link" value="1"><span>' + h(t("an.includeLinkShort")) + '</span></label>' +
      '<label class="analyzer-option"><input type="checkbox" name="send_image" value="1" checked><span>' + h(t("an.sendImageShort")) + '</span></label></div>' +
      '<button class="btn btn-primary analyzer-submit" type="button" data-act="submit" data-form-id="analyzerForm">' + ico("sparkles") + '<span>' +
      h(t("an.submit")) + '</span></button></form>' +
      '<details class="analyzer-ai-settings" id="analyzerAiSettings"><summary><span class="ai-settings-title">' + ico("sparkles") + h(t("an.aiSettings")) +
      '</span><span class="chip ' + (aiReady ? 'ok' : 'warn') + '" id="analysisApiStatus">' + h(aiStatusText) + '</span></summary>' +
      '<div class="analyzer-ai-body"><p class="tiny mute">' + h(t("an.aiSettingsNote")) + '</p>' +
      '<form data-form="analyzer-ai" id="analyzerAiForm"><div class="ai-subhead">' + ico("book") + h(t("an.aiAnalysisProvider")) + '</div>' +
      '<div class="form-grid">' +
      '<div class="field"><label for="analysisApiProvider">' + h(t("an.aiProvider")) + '</label><select class="input" id="analysisApiProvider" name="analysis_api_provider" data-act="analyzer.ai.provider">' +
      '<option value="deepseek"' + (analysisProvider === "deepseek" ? ' selected' : '') + '>' + h(t("an.aiProviderDeepSeek")) + '</option>' +
      '<option value="openai_compatible"' + (analysisProvider !== "deepseek" ? ' selected' : '') + '>' + h(t("an.aiProviderCustom")) + '</option></select></div>' +
      '<div class="field"><label for="analysisApiBase">' + h(t("an.aiBaseUrl")) + '</label><input class="input ltr" id="analysisApiBase" type="url" name="analysis_api_base_url" data-act="analyzer.ai.basechange" value="' + h(aiSettings.analysis_api_base_url || 'https://api.openai.com/v1') + '"></div>' +
      '<div class="field"><label for="analysisApiModel">' + h(t("an.aiModel")) + '</label><input class="input ltr" id="analysisApiModel" type="text" name="analysis_api_model" list="analysisApiModels" value="' + h(aiSettings.analysis_api_model || 'gpt-4o-mini') + '"><datalist id="analysisApiModels"></datalist></div>' +
      '<div class="field span2"><label for="analysisApiKey">' + h(t("an.aiApiKey")) + '</label><input class="input ltr" id="analysisApiKey" type="password" name="analysis_api_key" data-act="analyzer.ai.keychange" value="' + h(aiSettings.analysis_api_key || '') + '" placeholder="' + h(aiSettings.analysis_api_key_set ? t("settings.key_set") : 'sk-…') + '" autocomplete="off"></div>' +
      '</div><div class="tiny mute" id="analysisModelDiscoveryStatus" aria-live="polite">' + h(t("an.aiDiscoverNote")) + '</div>' +
      '<div class="ai-subhead ai-image-subhead">' + ico("image") + h(t("an.aiImageProvider")) + '</div>' +
      '<p class="tiny mute">' + h(t("an.aiImageNote")) + '</p>' +
      '<div class="analyzer-ai-toggle">' + toggleEl("image_generation_enabled", String(aiSettings.image_generation_enabled || "0") === "1") + '<span>' + h(t("an.aiImageEnabled")) + '</span>' +
      '<span class="chip ' + (imageApiReady ? 'ok' : 'warn') + '" id="imageApiStatus">' + h(imageApiReady ? t("an.aiImageReady") : t("an.aiImageOptional")) + '</span></div>' +
      '<div class="form-grid">' +
      '<div class="field"><label for="imageApiBase">' + h(t("an.aiImageBaseUrl")) + '</label><input class="input ltr" id="imageApiBase" type="url" name="image_api_base_url" value="' + h(aiSettings.image_api_base_url || 'https://api.openai.com/v1') + '"></div>' +
      '<div class="field"><label for="imageApiModel">' + h(t("an.aiImageModel")) + '</label><input class="input ltr" id="imageApiModel" type="text" name="image_api_model" value="' + h(aiSettings.image_api_model || 'gpt-image-1') + '"></div>' +
      '<div class="field span2"><label for="imageApiKey">' + h(t("an.aiImageKey")) + '</label><input class="input ltr" id="imageApiKey" type="password" name="image_api_key" value="' + h(aiSettings.image_api_key || '') + '" placeholder="' + h(aiSettings.image_api_key_set ? t("settings.key_set") : 'sk-…') + '" autocomplete="off"></div>' +
      '</div><div class="analyzer-ai-actions"><button type="button" class="btn btn-sm btn-ghost" data-act="analyzer.ai.models">' + ico("refresh") + '<span>' + h(t("an.aiDiscoverModels")) + '</span></button>' +
      '<button type="button" class="btn btn-sm" data-act="analyzer.ai.save">' + ico("check") + '<span>' + h(t("an.aiSave")) + '</span></button>' +
      '<button type="button" class="btn btn-sm btn-ghost" data-act="analyzer.ai.test">' + ico("zap") + '<span>' + h(t("an.aiTest")) + '</span></button></div>' +
      '</form></div></details></div></section>';

    view.innerHTML = pageHead(t("an.title"), t("an.sub"),
      btn(t("top.refresh"), "reload", { cls: "ghost", icon: "refresh" })) +
      '<div class="analyzer-studio"><div class="stack">' + form + '<div id="analysisResult">' +
      renderAnalysisDetail(S.currentAnalysis) + '</div></div>' +
      '<div class="stack"><section class="card"><div class="card-head"><div><h2 class="card-title">' + ico("history") + h(t("an.history")) +
      '</h2></div></div><div class="card-body" id="analysisHistory">' + renderAnalysisHistory(S.analyses) + '</div></section>' +
      '<section class="card"><div class="card-head"><h2 class="card-title">' + ico("shield") + h(t("dest.rulesTitle")) +
      '</h2></div><div class="card-body"><p class="card-sub" style="margin:0">' + h(t("an.selectDests")) + '</p><div class="stack" style="margin-top:12px">' +
      (S.dests.filter((dest) => Number(dest.enabled)).length ? S.dests.filter((dest) => Number(dest.enabled)).map((dest) =>
        '<div class="spread"><span>' + h(dest.name) + '</span><span class="pill brand">' + h(platName(platform(dest.platform))) + '</span></div>').join("") :
        '<a class="btn btn-sm" href="#/channels" data-act="nav.item" data-page="channels">' + h(t("dest.add")) + '</a>') +
      '</div></div></section></div></div>';

    if (S.currentAnalysis && S.currentAnalysis.status === "processing") startAnalyzerPolling(S.currentAnalysis.id);
  }

  function updateAnalyzerPanels() {
    const result = $("#analysisResult");
    if (result) result.innerHTML = renderAnalysisDetail(S.currentAnalysis);
    const history = $("#analysisHistory");
    if (history) history.innerHTML = renderAnalysisHistory(S.analyses || []);
  }

  async function reloadAnalyzerHistory() {
    const rows = await api("/api/analyzer?limit=40");
    S.analyses = rows.analyses || [];
    if (S.currentAnalysis) {
      const fresh = S.analyses.find((item) => Number(item.id) === Number(S.currentAnalysis.id));
      if (fresh) S.currentAnalysis = fresh;
    }
    updateAnalyzerPanels();
  }

  function updateAnalyzerApiBadges() {
    const settings = S.settings || {};
    const aiReady = Boolean(settings.analysis_api_key_set || settings.deepseek_key_set || settings.openai_key_set);
    const aiStatus = $("#analysisApiStatus");
    if (aiStatus) {
      aiStatus.className = "chip " + (aiReady ? "ok" : "warn");
      aiStatus.textContent = aiReady ? t("an.aiConfigured") : t("an.aiMissing");
    }
    const imageReady = String(settings.image_generation_enabled || "0") === "1" && Boolean(settings.image_api_key_set);
    const imageStatus = $("#imageApiStatus");
    if (imageStatus) {
      imageStatus.className = "chip " + (imageReady ? "ok" : "warn");
      imageStatus.textContent = imageReady ? t("an.aiImageReady") : t("an.aiImageOptional");
    }
  }

  async function saveAnalyzerAiSettings() {
    const form = $("#analyzerAiForm");
    if (!form) throw new Error("analyzer_settings_missing");
    const values = fd(form);
    const patch = {
      analysis_api_provider: values.analysis_api_provider,
      analysis_api_base_url: values.analysis_api_base_url,
      analysis_api_model: values.analysis_api_model,
      image_generation_enabled: tgVal(form, "image_generation_enabled"),
      image_api_base_url: values.image_api_base_url,
      image_api_model: values.image_api_model,
    };
    // Empty secret fields mean “keep the stored key”; credentials are never
    // returned to the browser, even in partially masked form.
    if (String(values.analysis_api_key || "").trim()) patch.analysis_api_key = values.analysis_api_key.trim();
    if (String(values.image_api_key || "").trim()) patch.image_api_key = values.image_api_key.trim();
    const response = await api("/api/settings", { method: "PATCH", body: patch });
    S.settings = response.settings || S.settings;
    updateAnalyzerApiBadges();
    return S.settings;
  }

  function analyzerApiErrorText(error) {
    const code = String(error || "unknown");
    const status = code.match(/(?:llm|models)_http_(\d{3})/);
    if (status) {
      const mapped = {
        "400": "an.aiHttp400", "401": "an.aiHttp401", "402": "an.aiHttp402",
        "403": "an.aiHttp403", "404": "an.aiHttp404", "429": "an.aiHttp429",
      };
      if (mapped[status[1]]) return t(mapped[status[1]]);
      if (Number(status[1]) >= 500) return t("an.aiHttp5xx");
    }
    const known = {
      analysis_api_timeout: "an.aiApiTimeout",
      analysis_api_network: "an.aiApiNetwork",
      analysis_api_missing_key: "an.aiApiMissingKey",
      analysis_api_models_empty: "an.aiModelsEmpty",
      analysis_api_bad_response: "an.aiApiBadResponse",
      analysis_api_url_invalid: "an.aiApiUrlInvalid",
      analysis_api_provider_invalid: "an.aiApiProviderInvalid",
      analysis_api_failed: "an.aiApiFailed",
    };
    return known[code] ? t(known[code]) : code;
  }

  async function discoverAnalyzerModels() {
    if (ANALYZER_MODEL_FETCH) return ANALYZER_MODEL_FETCH;
    const form = $("#analyzerAiForm");
    const status = $("#analysisModelDiscoveryStatus");
    const button = $('[data-act="analyzer.ai.models"]');
    if (!form) return;
    const values = fd(form);
    const provider = values.analysis_api_provider || "openai_compatible";
    const hasTypedKey = Boolean(String(values.analysis_api_key || "").trim());
    const saved = S.settings || {};
    const hasStoredKey = Boolean(saved.analysis_api_key_set ||
      (provider === "deepseek" ? saved.deepseek_key_set : saved.openai_key_set));
    if (!hasTypedKey && !hasStoredKey) {
      if (status) status.textContent = t("an.aiApiMissingKey");
      return;
    }
    if (status) status.textContent = t("an.aiDiscovering");
    if (button) button.disabled = true;
    const payload = {
      provider: provider,
      base_url: values.analysis_api_base_url || "",
      api_key: String(values.analysis_api_key || "").trim(),
    };
    ANALYZER_MODEL_FETCH = (async () => {
      try {
        const result = await api("/api/analyzer/models", { method: "POST", body: payload });
        if (!result.ok) {
          if (status) status.textContent = t("an.aiDiscoverFail", { detail: analyzerApiErrorText(result.error) });
          return result;
        }
        const models = (result.models || []).slice(0, 200);
        const list = $("#analysisApiModels");
        if (list) list.innerHTML = models.map((model) => '<option value="' + h(model) + '"></option>').join("");
        const modelInput = $("#analysisApiModel");
        if (modelInput && models.length && !models.includes(modelInput.value.trim())) {
          modelInput.value = provider === "deepseek" && models.includes("deepseek-flash") ? "deepseek-flash" : models[0];
        }
        if (status) status.textContent = t("an.aiDiscoverOk", { count: models.length, model: modelInput ? modelInput.value : "" });
        return result;
      } catch (error) {
        if (status) status.textContent = t("an.aiDiscoverFail", { detail: analyzerApiErrorText(error.message) });
        return { ok: false, error: error.message || "unknown" };
      } finally {
        ANALYZER_MODEL_FETCH = null;
        if (button && button.isConnected) button.disabled = false;
      }
    })();
    return ANALYZER_MODEL_FETCH;
  }

  function renderAnalysisHistory(analyses) {
    if (!analyses || !analyses.length) return '<div class="empty">' + h(t("an.empty")) + '</div>';
    return '<div class="stack">' + analyses.map((analysis) => {
      const active = S.currentAnalysis && Number(S.currentAnalysis.id) === Number(analysis.id);
      const status = analysis.status === "processing" ? t("an.processing") :
        analysis.status === "published" ? t("an.posted") : analysis.status === "failed" ? t("an.failed") : t("an.ready");
      return '<button class="analysis-history-row' + (active ? ' active' : '') + '" type="button" data-act="analyzer.open" data-id="' + analysis.id + '">' +
        '<span class="pill ' + (analysis.status === 'failed' ? 'err' : analysis.status === 'published' ? 'ok' : analysis.status === 'processing' ? 'warn' : 'brand') + '">' +
        h(analysis.platform || 'web') + '</span><span class="analysis-history-title">' + h(analysis.title || analysis.url) + '</span>' +
        '<span class="tiny mute">' + h(status) + ' · ' + h(relTime(analysis.created_at)) + '</span></button>';
    }).join('') + '</div>';
  }

  function renderAnalysisDetail(analysis) {
    if (!analysis) return '<section class="card"><div class="card-body"><div class="empty">' + h(t("an.empty")) + '</div></div></section>';
    const statusLabel = analysis.status === "processing" ? t("an.processing") :
      analysis.status === "failed" ? t("an.failed") : analysis.status === "published" ? t("an.posted") : t("an.ready");
    const statusClass = analysis.status === "failed" ? "err" : analysis.status === "published" ? "ok" : analysis.status === "processing" ? "warn" : "brand";
    const points = Array.isArray(analysis.key_points) ? analysis.key_points : safeJson(analysis.key_points, []);
    const pointText = points.map((point) => typeof point === "string" ? point : (point.text || point.title || JSON.stringify(point))).filter(Boolean);
    const timeline = Array.isArray(analysis.timeline) ? analysis.timeline : safeJson(analysis.timeline, []);
    const draft = analysis.channel_draft || analysis.summary || "";
    const detail = analysis.status === "processing" ?
      '<div class="an-progress"><span class="spinner"></span><div><b>' + h(t("an.processing")) + '</b><div class="card-sub">' +
      h(analysis.progress_msg || t("common.loading")) + '</div></div></div>' :
      analysis.status === "failed" ? '<div class="pill err" style="white-space:normal">' + h(analysis.error || statusLabel) + '</div>' :
      '<div class="analysis-content">' +
        (analysis.image ? '<div class="media-card-cover"><img src="' + h(analysis.image) + '" alt="" loading="lazy"><span class="media-duration-badge">' +
          h(analysis.duration_fmt || analysis.platform || '') + '</span></div>' : '') +
        '<div class="analysis-metrics"><span class="pill brand">' + h(analysis.platform || 'web') + '</span>' +
          '<span class="pill ' + (analysis.analysis_mode === 'ai' ? 'ok' : '') + '">' + h(analysis.analysis_mode === 'ai' ? t("an.modeAI") : t("an.modeBasic")) + '</span>' +
          (analysis.author ? '<span class="pill">' + h(analysis.author) + '</span>' : '') +
          (analysis.duration_fmt ? '<span class="pill">' + h(t("an.duration", { d: analysis.duration_fmt })) + '</span>' : '') +
          '<span class="pill">' + h(t("an.chars", { n: num(analysis.transcript_len || 0) })) + '</span>' +
          '<a class="btn btn-xs" href="' + h(analysis.url) + '" target="_blank" rel="noopener">' + ico("external") + '<span>' + h(t("items.openSource")) + '</span></a>' +
        '</div>' +
        (analysis.summary ? '<div class="an-section"><h4>' + ico("sparkles") + h(t("an.execSummary")) + '</h4><div dir="auto">' + h(analysis.summary) + '</div></div>' : '') +
        (pointText.length ? '<div class="an-section"><h4>' + ico("list") + h(t("an.keyPoints")) + '</h4><ul class="an-bullets">' + pointText.map((point) => '<li dir="auto">' + h(point) + '</li>').join('') + '</ul></div>' : '') +
        (analysis.deep_analysis ? '<details class="an-section"><summary class="an-details-summary">' + ico("book") + h(t("an.deepAnalysis")) + '</summary><div class="analysis-longtext" dir="auto">' + h(analysis.deep_analysis) + '</div></details>' : '') +
        (timeline.length ? '<details class="an-section"><summary>' + h(t("an.rawTranscript")) + '</summary><div class="stack" style="margin-top:10px">' + timeline.map((entry) => {
          const line = typeof entry === 'string' ? entry : [entry.time || entry.timestamp || '', entry.text || entry.title || ''].filter(Boolean).join(' — ');
          return '<div class="timeline-row" dir="auto">' + h(line) + '</div>';
        }).join('') + '</div></details>' : '') +
      '</div>';

    const destinations = (S.dests || []).filter((dest) => Number(dest.enabled));
    return '<section class="card"><div class="card-head"><div><h2 class="card-title">' + h(analysis.title || t("an.title")) + '</h2>' +
      '<p class="card-sub"><span class="pill ' + statusClass + '">' + h(statusLabel) + '</span> · ' + h(relTime(analysis.created_at)) + '</p></div>' +
      '<button class="btn btn-xs btn-ghost" type="button" data-act="analyzer.delete" data-id="' + analysis.id + '" title="' + h(t("common.delete")) + '">' + ico("trash") + '</button></div>' +
      '<div class="card-body">' + detail +
      (analysis.status === "ready" || analysis.status === "published" ?
        '<div class="an-section"><h4>' + ico("edit") + h(t("an.channelDraft")) + '</h4>' +
        '<textarea class="input analysis-draft" id="analysisDraft" rows="6" dir="auto">' + h(draft) + '</textarea>' +
        '<div class="analysis-preview-label">' + h(t("an.livePreview")) + '</div><div class="previewbox" id="analysisPreview" dir="auto">' +
        h(draft).replace(/\n/g, '<br>') + '</div>' +
        '<div class="form-row" style="margin-top:12px"><label class="switch"><input type="checkbox" id="analysisIncludeLink"' + (Number(analysis.include_link) ? ' checked' : '') + '><span>' +
        h(t("an.includeLink")) + '</span></label><label class="switch"><input type="checkbox" id="analysisSendImage"' + (Number(analysis.send_image !== undefined ? analysis.send_image : 1) ? ' checked' : '') + '><span>' +
        h(t("an.sendImage")) + '</span></label></div>' +
        '<div class="analysis-destinations" id="analysisDests"><b>' + h(t("an.selectDests")) + '</b>' +
        (destinations.length ? '<div class="chips">' + destinations.map((dest) => '<label class="chip-check"><input type="checkbox" name="analysisDest" value="' + dest.id + '" checked><span>' +
          h(dest.name) + '</span></label>').join('') + '</div>' : '<a class="btn btn-sm" href="#/channels" data-act="nav.item" data-page="channels">' + h(t("dest.add")) + '</a>') +
        '</div><div class="inline" style="margin-top:12px"><button class="btn" type="button" data-act="analyzer.save" data-id="' + analysis.id + '">' + ico("check") + '<span>' +
        h(t("an.saveDraft")) + '</span></button><button class="btn btn-primary" type="button" data-act="analyzer.publish" data-id="' + analysis.id + '"' +
        (destinations.length ? '' : ' disabled') + '>' + ico("send") + '<span>' + h(t("an.publishBtn")) + '</span></button></div></div>' : '') +
      '</div></section>';
  }

  function logLine(l) {
    const lvl = (l.level || "info").toLowerCase();
    return (
      '<div class="logline"><span class="lt">' + h(fmtLogTime(l.created_at)) + '</span>' +
      '<span class="lv ' + h(lvl) + '">' + h(lvl) + "</span>" +
      '<span class="lm">' + h(l.message) + "</span></div>"
    );
  }

  function itemRow(it, opts) {
    opts = opts || {};
    const title = isFa() && it.title_fa ? it.title_fa : it.title;
    const summary = isFa() && it.summary_fa ? it.summary_fa : it.summary;
    const status = it.status || "new";
    const statusMap = {
      sent: ["ok", "items.status.sent"],
      failed: ["err", "items.status.failed"],
      filtered: ["warn", "items.status.filtered"],
      dry_run: ["info", "items.status.dry"],
      skipped: ["", "items.status.skipped"],
      new: ["info", "items.status.new"],
    };
    const st = statusMap[status] || ["info", "items.status.new"];
    const thumb = it.image
      ? '<img class="ithumb" src="' + h(it.image) + '" alt="" loading="lazy" onerror="this.remove()">'
      : '<span class="ithumb-placeholder">' + ico("image") + '</span>';
    const reason = it.filter_reason ? '<div class="filter-reason-box">' + ico("filter") + '<span>' + h(t("items.filterReason")) + h(it.filter_reason) + '</span></div>' : "";
    const source = it.link ? '<a href="' + h(it.link) + '" target="_blank" rel="noopener">' + h(t("items.openSource")) + '</a>' : "";
    const acts = opts.compact ? "" :
      '<div class="iact">' +
        iconBtn("eye", "item.preview", it.id, "ghost", t("items.preview")) +
        iconBtn("send", "item.publish", it.id, "primary", t("items.resend")) +
        iconBtn("trash", "item.del", it.id, "ghost", t("common.delete")) +
      '</div>';
    return '<article class="irow" data-item-id="' + it.id + '">' + thumb +
      '<div class="ibody"><h3 class="ititle" dir="auto">' + h(title || t("items.title")) + '</h3>' +
      (summary ? '<p class="isum" dir="auto">' + h(summary) + '</p>' : '') +
      '<div class="imeta"><span class="pill ' + st[0] + '">' + h(t(st[1])) + '</span>' +
      (it.topic ? '<span class="pill brand">' + h(String(it.topic).split("#")[0].trim()) + '</span>' : '') +
      (it.feed_title ? '<span>' + h(it.feed_title) + '</span>' : '') +
      '<span title="' + h(it.published ? t("items.sourceDate") : t("items.processedDate")) + '">' + h(it.published ? fmtDate(it.published, true) : relTime(it.posted_at || it.created_at)) + '</span>' + source +
      (it.error ? '<span class="pill err">' + h(String(it.error).slice(0, 90)) + '</span>' : '') +
      '</div>' + reason + '</div>' + acts + '</article>';
  }

  /* ── feeds ────────────────────────────────────────────────────────────── */

  async function renderFeeds(view) {
    view.innerHTML = '<div class="card"><div class="card-body"><div class="skeleton" style="width:35%"></div></div></div>';
    await loadFeeds();
    const rows = S.feeds.length
      ? S.feeds.map(feedRow).join("")
      : emptyBox("rss", t("feeds.empty"), t("feeds.empty_hint"), btn(t("feeds.add"), "feed.new", { cls: "primary sm", icon: "plus" }));

    view.innerHTML =
      pageHead(t("feeds.title"), t("feeds.subtitle"),
        btn(t("feeds.bulk"), "feed.bulk", { cls: "ghost", icon: "layers" }) +
        btn(t("feeds.test_url"), "feed.test", { cls: "ghost", icon: "search" }) +
        btn(t("feeds.add"), "feed.new", { cls: "primary", icon: "plus" })) +
      '<section class="card"><div class="card-body flush"><div class="rows">' +
      (S.feeds.length
        ? '<div class="frow fhead"><div></div><div>' + h(t("common.source")) + "</div><div>" + h(t("common.status")) +
          '</div><div class="c-md">' + h(t("feeds.fresh")) + '</div><div class="c-md">' + h(t("feeds.last_check")) +
          '</div><div style="text-align:end">' + h(t("common.actions")) + "</div></div>"
        : "") + rows + "</div></div></section>";
  }

  function feedRow(f) {
    const col = colorOf(f.color);
    const url = f.show_url ? f.url : "••••••••••••";
    const status = f.last_status && String(f.last_status).startsWith("error")
      ? '<span class="chip bad">' + h(t("feeds.broken")) + "</span>"
      : f.last_status
        ? '<span class="chip ok">' + h(t("feeds.healthy")) + "</span>"
        : '<span class="chip">' + h(t("feeds.not_checked")) + "</span>";
    return (
      '<div class="frow" data-feed-id="' + f.id + '">' +
        '<div class="favatar" style="background:' + tint(col, 0.14) + ";border-color:" + tint(col, 0.4) + ";color:" + col + '">' + h(f.icon || "📰") + "</div>" +
        '<div class="fname"><b dir="auto">' + h(f.title) + "</b>" +
          '<span class="' + (f.show_url ? "" : "hidden_url") + '" title="' + h(f.url) + '">' + h(url) + "</span></div>" +
        "<div>" + status + "</div>" +
        '<div class="c-md"><span class="mono tiny">' + num(f.last_count || 0) + "</span></div>" +
        '<div class="c-md tiny mute">' + h(f.last_checked ? relTime(f.last_checked) : t("common.never")) + "</div>" +
        '<div class="iact" style="justify-content:flex-end">' + toggleEl("feed-enabled-" + f.id, Number(f.enabled), "feed.toggle", f.id) +
          iconBtn("refresh", "feed.check", f.id, "ghost", t("feeds.check")) +
          iconBtn("edit", "feed.edit", f.id, "ghost", t("common.edit")) +
          iconBtn("trash", "feed.del", f.id, "ghost", t("common.delete")) + "</div>" +
      "</div>"
    );
  }

  function replaceFeedRow(feed) {
    if (!feed) return;
    const current = $('[data-feed-id="' + Number(feed.id) + '"]');
    if (!current) return;
    const holder = document.createElement("div");
    holder.innerHTML = feedRow(feed);
    const replacement = holder.firstElementChild;
    if (replacement) current.replaceWith(replacement);
  }

  function feedModal(feed) {
    const f = feed || { title: "", url: "", icon: "📰", color: "teal", show_url: 1, show_source: 0, custom_source_label: "", default_topic_id: 0, full_article: 1, enabled: 1 };
    S.draft = { feedId: feed ? feed.id : null, color: f.color || "teal", icon: f.icon || "📰" };
    const body =
      '<form data-form="feed" id="feedForm">' +
        field(t("feeds.field.title"), '<input type="text" name="title" value="' + h(f.title) + '" placeholder="' + h(t("feeds.name_ph")) + '" dir="auto" required>') +
        field(t("feeds.field.url"), '<input class="ltr" type="url" name="url" value="' + h(f.url) + '" placeholder="https://example.com/rss" required>', t("feeds.url_hint")) +
        '<div class="form-grid">' +
          field(t("feeds.field.defaultTopic"), '<select class="input" name="default_topic_id"><option value="0">' + h(t("feeds.field.autoTopic")) + '</option>' + (S.topics || []).map((topic) => '<option value="' + topic.id + '"' + (Number(topic.id) === Number(f.default_topic_id || 0) ? ' selected' : '') + '>' + h((topic.emoji || '') + ' ' + topic.name) + '</option>').join('') + '</select>') +
          field(t("feeds.field.customSource"), '<input type="text" name="custom_source_label" value="' + h(f.custom_source_label || '') + '" dir="auto" placeholder="' + h(t("feeds.field.customSource")) + '">') +
        '</div>' +
        '<div class="checkline">' + toggleEl("full_article", Number(f.full_article !== undefined ? f.full_article : 1)) + '<span class="ct"><b>' + h(t("feeds.field.fullArticle")) + '</b></span></div>' +
        '<div class="checkline">' + toggleEl("show_source", Number(f.show_source || 0)) + '<span class="ct"><b>' + h(t("feeds.field.showSource")) + '</b></span></div>' +
        '<div class="sep-row"></div>' +
        '<div class="spread" style="margin-bottom:10px"><b style="font-size:12.5px">' + h(t("feeds.appearance")) +
          '</b><span class="tiny mute">' + h(t("feeds.appearance_hint")) + "</span></div>" +
        '<div class="form-grid">' +
          '<div class="span2">' + field(t("common.icon"),
            '<div class="inline"><input type="text" name="icon" id="feedIcon" value="' + h(f.icon) + '" style="width:74px;text-align:center;font-size:17px" maxlength="4" dir="ltr">' +
            '<span class="inline" id="emojiRow">' + EMOJIS.map((e) => '<button type="button" class="pick" data-act="feed.emoji" data-emoji="' + e + '">' + e + "</button>").join("") + "</span></div>") + "</div>" +
          '<div class="span2">' + field(t("common.color"),
            '<div class="inline" id="colorRow">' + Object.keys(COLORS).map((ck) =>
              '<button type="button" class="pick' + (ck === (f.color || "teal") ? " on" : "") + '" data-act="feed.color" data-color="' + ck + '">' +
              '<span class="color-dot" style="background:' + COLORS[ck] + '"></span>' + h(ck) + "</button>").join("") + "</div>") + "</div>" +
        "</div>" +
        '<div class="checkline"><button type="button" class="toggle' + (Number(f.show_url) ? " on" : "") + '" data-act="tg" data-tg="show_url"></button>' +
          '<span class="ct"><b>' + h(t("feeds.show_url")) + "</b><span>" + h(t("feeds.show_url_hint")) + "</span></span></div>" +
        '<div class="checkline"><button type="button" class="toggle' + (Number(f.enabled) ? " on" : "") + '" data-act="tg" data-tg="enabled"></button>' +
          '<span class="ct"><b>' + h(t("common.enabled")) + "</b></span></div>" +
      "</form>";
    openModal({
      title: feed ? t("feeds.edit_title") : t("feeds.add_title"),
      wide: true,
      body: body,
      footer:
        '<button class="btn ghost" data-act="modal.close">' + t("common.cancel") + "</button>" +
        '<button class="btn primary" data-act="submit" data-form-id="feedForm">' + t("common.save") + "</button>",
    });
  }

  function feedTestModal() {
    openModal({
      title: t("feeds.test_url"),
      body:
        '<form data-form="feedtest" id="feedTestForm">' +
        field(t(("common.url")), '<input class="ltr" type="url" name="url" placeholder="https://feeds.bbci.co.uk/persian/rss.xml" required>') +
        '<div id="feedTestResult"></div></form>',
      footer:
        '<button class="btn ghost" data-act="modal.close">' + t("common.cancel") + "</button>" +
        '<button class="btn primary" data-act="submit" data-form-id="feedTestForm">' + t("common.test") + "</button>",
    });
  }

  function bulkModal() {
    openModal({
      title: t("feeds.bulk"),
      body:
        '<form data-form="bulk" id="bulkForm">' +
        field(t("feeds.bulk_hint"), '<textarea class="code" name="text" rows="7" placeholder="https://site.ir/rss\nhttps://other.com/feed"></textarea>') +
        "</form>",
      footer:
        '<button class="btn ghost" data-act="modal.close">' + t("common.cancel") + "</button>" +
        '<button class="btn primary" data-act="submit" data-form-id="bulkForm">' + t("common.add") + "</button>",
    });
  }

  /* ── topics ───────────────────────────────────────────────────────────── */

  async function renderTopics(view) {
    view.innerHTML = '<div class="card"><div class="card-body"><div class="skeleton" style="width:30%"></div></div></div>';
    await loadTopics();
    const cards = S.topics.map((tp) => {
      const kws = String(tp.keywords || "").split(/[,،]/).map((k) => k.trim()).filter(Boolean);
      return (
        '<div class="jobcard' + (Number(tp.enabled) ? "" : " off") + '">' +
          '<div class="jobtop"><div class="inline"><span class="emoji-tile" style="font-size:20px">' + h(tp.emoji || "🏷️") + "</span>" +
            '<div><b dir="auto">' + h(tp.name) + '</b><div class="tiny mute">' + h(tp.name_en || "") + "</div></div></div>" +
            toggleEl("topic-" + tp.id, Number(tp.enabled), "topic.toggle", tp.id) + "</div>" +
          '<div class="jobmeta">' + kws.slice(0, 7).map((k) => '<span class="chip">' + h(k) + "</span>").join("") +
            (kws.length > 7 ? '<span class="chip">+' + num(kws.length - 7) + "</span>" : "") + "</div>" +
          '<div class="jobfoot"><span class="tiny mute">' + h(t("topics.count_kw", { n: num(kws.length) })) + "</span><div class=\"btns\">" +
            iconBtn("edit", "topic.edit", tp.id, "ghost", t("common.edit")) +
            iconBtn("trash", "topic.del", tp.id, "ghost", t("common.delete")) + "</div></div>" +
        "</div>"
      );
    }).join("");

    view.innerHTML =
      pageHead(t("topics.title"), t("topics.subtitle"),
        btn(t("topics.test"), "topic.test", { cls: "ghost", icon: "zap" }) +
        btn(t("topics.add"), "topic.new", { cls: "primary", icon: "plus" })) +
      '<div class="grid c3">' + (cards || "") + "</div>" +
      (S.topics.length ? "" : '<section class="card"><div class="card-body">' + emptyBox("tag", t("common.empty"), "") + "</div></section>");
  }

  function topicModal(topic) {
    const tp = topic || { name: "", name_en: "", emoji: "🏷️", keywords: "", enabled: 1 };
    S.draft = { topicId: topic ? topic.id : null, emoji: tp.emoji || "🏷️" };
    openModal({
      title: topic ? t("topics.edit_title") : t("topics.add_title"),
      body:
        '<form data-form="topic" id="topicForm">' +
        '<div class="form-grid">' +
          '<div class="span2">' + field(t("topics.emoji"),
            '<div class="inline"><input type="text" name="emoji" id="topicEmoji" value="' + h(tp.emoji || "") + '" style="width:70px;text-align:center;font-size:16px" maxlength="4" dir="ltr">' +
            '<span class="inline">' + EMOJIS.map((e) => '<button type="button" class="pick" data-act="topic.emoji" data-emoji="' + e + '">' + e + "</button>").join("") + "</span></div>") + "</div>" +
          field(t("topics.name"), '<input type="text" name="name" value="' + h(tp.name) + '" dir="auto" required>') +
          field(t("topics.name_en"), '<input class="ltr" type="text" name="name_en" value="' + h(tp.name_en || "") + '">') +
          '<div class="span2">' + field(t("topics.keywords"),
            '<textarea name="keywords" rows="3" dir="auto" placeholder="' + h(t("topics.keywords_hint")) + '">' + h(tp.keywords || "") + "</textarea>", t("topics.keywords_hint")) + "</div>" +
        "</div>" +
        '<div class="checkline">' + toggleEl("enabled", Number(tp.enabled)) + '<span class="ct"><b>' + h(t("common.enabled")) + "</b></span></div>" +
        "</form>",
      wide: true,
      footer:
        '<button class="btn ghost" data-act="modal.close">' + t("common.cancel") + "</button>" +
        '<button class="btn primary" data-act="submit" data-form-id="topicForm">' + t("common.save") + "</button>",
    });
  }

  function topicTestModal() {
    openModal({
      title: t("topics.test"),
      body:
        '<form data-form="topictest" id="topicTestForm">' +
        field(t("topics.test_title_ph"), '<input id="tTitle" type="text" name="title" dir="auto" required>') +
        field(t("topics.test_summary_ph"), '<textarea id="tSum" name="summary" rows="2" dir="auto"></textarea>') +
        '<div id="topicTestResult"><div id="tOut"></div></div></form>',
      footer:
        '<button class="btn ghost" data-act="modal.close">' + t("common.cancel") + "</button>" +
        '<button class="btn" data-act="topic.runtest">' + t("topics.runTest") + "</button>" +
        '<button class="btn btn-primary" data-act="submit" data-form-id="topicTestForm">' + t("common.test") + "</button>",
    });
  }

  /* ── channels ─────────────────────────────────────────────────────────── */

  async function renderChannels(view) {
    view.innerHTML = '<div class="card"><div class="card-body"><div class="skeleton" style="width:30%"></div></div></div>';
    await loadDests();
    const cards = S.dests.map((d) => {
      const p = platform(d.platform);
      const testChip =
        d.last_test_ok === 1 ? '<span class="chip ok destination-test-status">' + ico("check") + h(t("channels.last_test_ok")) + "</span>"
          : d.last_test_ok === 0 ? '<span class="chip bad destination-test-status">' + ico("alert") + h(t("channels.last_test_fail")) + "</span>"
            : "";
      return (
        '<div class="chcard" data-dest-id="' + d.id + '">' +
          '<div class="spread"><div class="inline"><span class="plat">' + platIcon(d.platform) + "</span>" +
            "<div><b style=\"font-size:13px\" dir=\"auto\">" + h(d.name) + '</b><div class="tiny mute">' + h(platName(p)) + "</div></div></div>" +
            toggleEl("dest-" + d.id, Number(d.enabled), "dest.toggle", d.id) + "</div>" +
          '<div><div class="kv"><span>' + h(t("channels.chat_id")) + '</span><b>' + h(d.chat_id) + "</b></div>" +
            '<div class="kv"><span>' + h(t("channels.token")) + '</span><b>' + h(d.has_token ? d.bot_token : "—") + "</b></div>" +
            '<div class="kv"><span>' + h(t("channels.topic_filter")) + '</span><b class="txt">' + h(d.topic_filter || t("channels.all_topics")) + "</b></div>" +
            (d.footer ? '<div class="kv"><span>' + h(t("channels.footer")) + '</span><b class="txt">' + h(d.footer) + "</b></div>" : "") + "</div>" +
          '<div class="jobmeta">' +
            (p.supports_photo ? '<span class="chip ok">' + ico("image") + h(t("channels.photo_badge")) + "</span>" : '<span class="chip warn">' + h(t("channels.no_photo")) + "</span>") +
            (d.has_token ? '<span class="chip ok">' + h(t("channels.connected")) + "</span>" : '<span class="chip bad">' + h(t("channels.needs_token")) + "</span>") +
            testChip + "</div>" +
          '<div class="jobfoot"><span class="tiny mute">' + h(d.last_test_at ? relTime(d.last_test_at) : "") + '</span><div class="btns">' +
            iconBtn("shield", "dest.verify", d.id, "ghost", t("channels.verify")) +
            iconBtn("radio", "dest.test", d.id, "soft", t("common.test")) +
            iconBtn("edit", "dest.edit", d.id, "ghost", t("common.edit")) +
            iconBtn("trash", "dest.del", d.id, "ghost", t("common.delete")) + "</div></div>" +
        "</div>"
      );
    }).join("");

    view.innerHTML =
      pageHead(t("channels.title"), t("channels.subtitle"),
        btn(t("channels.add"), "dest.new", { cls: "primary", icon: "plus" })) +
      (S.dests.length ? '<div class="grid c3">' + cards + "</div>"
        : '<section class="card"><div class="card-body">' +
          emptyBox("send", t("channels.empty"), t("channels.empty_hint"), btn(t("channels.add"), "dest.new", { cls: "primary sm", icon: "plus" })) +
          "</div></section>") +
      '<section class="card" style="margin-top:16px"><div class="card-head"><h2>' + ico("book") + h(t("channels.guide")) + "</h2></div>" +
        '<div class="card-body"><div class="grid c3">' +
        ((S.meta && S.meta.platforms) || []).map((p) =>
          '<div class="chcard"><div class="inline"><span class="plat">' + platIcon(p.id) + "</span><b>" + h(platName(p)) + "</b></div>" +
          '<div class="tiny mute">' + h(isFa() ? p.hint_fa : p.hint_en) + "</div>" +
          '<div class="tiny mute">' + h(isFa() ? p.token_hint_fa : p.token_hint_en) + "</div></div>"
        ).join("") + "</div></div></section>";
  }

  function updateDestinationCard(destination) {
    if (!destination) return;
    const idx = S.dests.findIndex((item) => Number(item.id) === Number(destination.id));
    if (idx >= 0) S.dests[idx] = destination;
    const card = $('[data-dest-id="' + Number(destination.id) + '"]');
    if (!card) return;
    const meta = card.querySelector(".jobmeta");
    if (meta && destination.last_test_ok !== null && destination.last_test_ok !== undefined) {
      let chip = meta.querySelector(".destination-test-status");
      if (!chip) { chip = document.createElement("span"); meta.appendChild(chip); }
      const ok = Number(destination.last_test_ok) === 1;
      chip.className = "chip " + (ok ? "ok" : "bad") + " destination-test-status";
      chip.innerHTML = ico(ok ? "check" : "alert") + h(t(ok ? "channels.last_test_ok" : "channels.last_test_fail"));
    }
    const time = card.querySelector(".jobfoot .tiny.mute");
    if (time) time.textContent = destination.last_test_at ? relTime(destination.last_test_at) : "";
  }

  function num(v) {
    const n = Number(v);
    return Number.isFinite(n) ? String(n) : String(v);
  }

  function platformRule(id) {
    const list = (S.meta && S.meta.platform_rules) || [];
    return list.find((r) => r.id === id) || { text: 4096, caption: 1024, html: true, photo: "url_or_upload", min_interval: 3, notes_fa: "", notes_en: "" };
  }

  function destRulesHtml(platformId) {
    const r = platformRule(platformId);
    const photoLabel = r.photo === "none" ? t("channels.rule_no_photo")
      : r.photo === "upload" ? t("channels.rule_photo_upload")
        : t("channels.rule_photo_url");
    const rows = [
      [t("channels.rule_text"), num(r.text)],
      [t("channels.rule_caption"), num(r.caption)],
      [t("channels.rule_photo"), photoLabel],
      [t("channels.rule_interval"), num(r.min_interval) + "s"],
      [t("channels.rule_format"), r.html ? "HTML" : t("channels.rule_plain")],
    ];
    return '<div class="rules-head">' + ico("shield") + "<b>" + h(t("channels.rules_title")) + "</b></div>" +
      '<div class="rules-grid">' + rows.map(([k, v]) =>
        '<div class="kv"><span>' + h(k) + '</span><b dir="auto">' + h(String(v)) + "</b></div>").join("") + "</div>" +
      '<p class="tiny mute">' + h(isFa() ? r.notes_fa : r.notes_en) + "</p>" +
      (r.doc ? '<a class="tiny link" href="' + h(r.doc) + '" target="_blank" rel="noopener">' + h(t("channels.rules_doc")) + "</a>" : "");
  }

  function destModal(dest) {
    const d = dest || { name: "", platform: "telegram", chat_id: "", bot_token: "", topic_filter: "", footer: "", parse_mode: "HTML", enabled: 1 };
    openModal({
      title: dest ? t("channels.edit_title") : t("channels.add_title"),
      body:
        '<form data-form="dest" id="destForm">' +
        '<div class="form-grid">' +
          field(t("common.name"), '<input type="text" name="name" value="' + h(d.name) + '" dir="auto">') +
          field(t("channels.platform"),
            '<select name="platform" data-dest-platform>' + ((S.meta && S.meta.platforms) || []).map((p) =>
              '<option value="' + p.id + '"' + (p.id === d.platform ? " selected" : "") + ">" + h(platName(p)) + "</option>").join("") + "</select>") +
          '<div class="span2">' + field(t("channels.chat_id"),
            '<input class="ltr" type="text" name="chat_id" value="' + h(d.chat_id) + '" placeholder="' + h(t("channels.chat_ph")) + '" required>',
            t("channels.chat_hint")) + "</div>" +
          '<div class="span2">' + field(t("channels.token"),
            '<input class="ltr" type="text" name="bot_token" value="' + h(d.bot_token || "") + '" placeholder="' + h(t("channels.token_ph")) + '">',
            t("channels.token_hint")) + "</div>" +
          field(t("channels.topic_filter"), '<input type="text" name="topic_filter" value="' + h(d.topic_filter) + '" dir="auto" placeholder="' + h(t("channels.topic_filter_ph")) + '">', t("channels.topic_filter_hint")) +
          field(t("channels.parse_mode"), '<select name="parse_mode" data-dest-mode>' + ["HTML", "TEXT"].map((m) =>
            '<option value="' + m + '"' + (m === (String(d.parse_mode || "HTML").toUpperCase() === "HTML" ? "HTML" : "TEXT") ? " selected" : "") + ">" + m + "</option>").join("") + "</select>", t("channels.parse_mode_hint")) +
          '<div class="span2">' + field(t("channels.footer"), '<input type="text" name="footer" value="' + h(d.footer) + '" dir="auto" placeholder="' + h(t("channels.footer_none")) + '">') + "</div>" +
        "</div>" +
        '<div class="rules-box" id="destRules">' + destRulesHtml(d.platform) + "</div>" +
        '<div class="checkline">' + toggleEl("enabled", Number(d.enabled)) + '<span class="ct"><b>' + h(t("common.enabled")) + "</b></span></div>" +
        "</form>",
      wide: true,
      onMount: () => {
        const form = document.getElementById("destForm");
        if (!form) return;
        const plat = form.querySelector("[data-dest-platform]");
        const rules = document.getElementById("destRules");
        const mode = form.querySelector("[data-dest-mode]");
        const sync = () => {
          const id = plat ? plat.value : "telegram";
          if (rules) rules.innerHTML = destRulesHtml(id);
          const html = platformRule(id).html;
          if (mode) {
            mode.disabled = !html;
            if (!html) mode.value = "TEXT";
            else if (!mode.value) mode.value = "HTML";
          }
        };
        if (plat) plat.addEventListener("change", sync);
        sync();
      },
      footer:
        '<button class="btn ghost" data-act="modal.close">' + t("common.cancel") + "</button>" +
        '<button class="btn primary" data-act="submit" data-form-id="destForm">' + t("common.save") + "</button>",
    });
  }

  /* ── jobs ─────────────────────────────────────────────────────────────── */

  async function renderJobs(view) {
    view.innerHTML = '<div class="card"><div class="card-body"><div class="skeleton" style="width:30%"></div></div></div>';
    await Promise.all([loadJobs(), loadFeeds(), loadTopics(), loadDests()]);
    const cards = S.jobs.map(jobCard).join("");
    view.innerHTML =
      pageHead(t("jobs.title"), t("jobs.subtitle"),
        btn(t("jobs.add"), "job.new", { cls: "primary", icon: "plus" }) +
        btn(t("nav.sub.dry"), "job.dryAll", { cls: "ghost", icon: "eye" })) +
      (S.jobs.length ? '<div class="grid c2">' + cards + "</div>"
        : '<section class="card"><div class="card-body">' +
          emptyBox("clock", t("jobs.empty"), t("jobs.empty_hint"), btn(t("jobs.add"), "job.new", { cls: "primary sm", icon: "plus" })) +
          "</div></section>");
  }

  function jobCard(j) {
    const times = safeJson(j.schedule_times, []);
    const feedIds = (j.feed_ids || []).map(Number);
    const topicIds = (j.topic_ids || []).map(Number);
    const destIds = (j.destination_ids || []).map(Number);
    const liveFeeds = (S.feeds || []).filter((f) => Number(f.enabled)).map((f) => Number(f.id));
    const liveDests = (S.dests || []).filter((d) => Number(d.enabled)).map((d) => Number(d.id));
    const usableFeeds = feedIds.length ? feedIds.filter((id) => liveFeeds.indexOf(id) >= 0) : liveFeeds;
    const usableDests = destIds.length ? destIds.filter((id) => liveDests.indexOf(id) >= 0) : liveDests;

    const when = times.length
      ? times.map((x) => '<span class="tchip">' + h(x) + "</span>").join("")
      : Number(j.interval_minutes)
        ? '<span class="tchip">' + h(t("jobs.every", { n: num(j.interval_minutes) })) + "</span>"
        : '<span class="tchip">' + h(t("jobs.no_schedule")) + "</span>";

    const flags = [];
    if (Number(j.translate)) flags.push('<span class="chip accent">' + ico("globe") + h(t("jobs.translate_on")) + "</span>");
    if (Number(j.send_image)) flags.push('<span class="chip info">' + ico("image") + h(t("jobs.image_badge")) + "</span>");
    flags.push('<span class="chip accent">' + ico("filter") + h(t("jobs.filter." + (j.filter_mode || "smart"))) + "</span>");
    if (j.exclude_keywords) flags.push('<span class="chip warn">' + h(t("jobs.field.exclude")) + '</span>');
    flags.push('<span class="chip">' + ico("clock") + h(t("jobs.window_chip", { n: num(j.window_hours) })) + "</span>");

    const metric = (label, value, zero) =>
      '<div class="jc-m' + (zero ? " zero" : "") + '"><b dir="ltr">' + h(String(value)) + "</b><span>" + h(label) + "</span></div>";

    const warn = (text, page, action) =>
      '<div class="jcard-warn">' + ico("alert") + "<span>" + h(text) + "</span>" +
      '<button class="btn ghost sm" data-act="nav.item" data-page="' + page + '">' + h(action) + "</button></div>";

    const warnings = [];
    if (!usableFeeds.length) warnings.push(warn(t("jobs.warn_no_feeds"), "feeds", t("jobs.fix_feeds")));
    if (!usableDests.length) warnings.push(warn(t("jobs.warn_no_channels"), "channels", t("jobs.fix_channels")));

    const cap = Number(j.max_items) > 0 ? num(j.max_items) : "∞";

    return (
      '<div class="jcard' + (Number(j.enabled) ? "" : " off") + '">' +
        '<div class="jc-head"><div class="jc-id">' +
          '<b dir="auto">' + h(j.name) + "</b>" +
          '<div class="jc-line"><span class="jc-state ' + (Number(j.enabled) ? "on" : "off") + '">' +
            h(t(Number(j.enabled) ? "jobs.state_on" : "jobs.state_off")) + "</span><span>·</span>" +
            "<span>" + h(t("dash.next_run")) + ": " + h(j.next_run ? fmtDate(j.next_run) : t("jobs.no_schedule")) + "</span>" +
          "</div></div>" +
          toggleEl("job-" + j.id, Number(j.enabled), "job.toggle", j.id) +
        "</div>" +
        '<div class="jc-when">' + when + flags.join("") + "</div>" +
        '<div class="jc-metrics">' +
          metric(t("jobs.m_feeds"), usableFeeds.length, !usableFeeds.length) +
          metric(t("jobs.m_topics"), topicIds.length, false) +
          metric(t("jobs.m_channels"), usableDests.length, !usableDests.length) +
          metric(t("jobs.m_cap"), cap, false) +
        "</div>" +
        warnings.join("") +
        '<div class="jc-foot"><span class="tiny mute">' +
          h(j.last_run ? t("jobs.last_run") + ": " + relTime(j.last_run) : "—") + "</span>" +
          '<div class="btns">' +
            iconBtn("play", "job.run", j.id, "primary", t("jobs.run_now")) +
            iconBtn("eye", "job.dry", j.id, "ghost", t("jobs.dry_run")) +
            iconBtn("edit", "job.edit", j.id, "ghost", t("common.edit")) +
            iconBtn("trash", "job.del", j.id, "ghost", t("common.delete")) +
          "</div></div>" +
      "</div>"
    );
  }

  function picker(kind, items, selected, render) {
    if (!items.length) return '<div class="picker"><span class="tiny mute">' + h(t("common.empty")) + "</span></div>";
    return (
      '<div class="picker" data-kind="' + kind + '">' +
      items.map((it) => {
        const on = selected.indexOf(Number(it.id)) >= 0;
        return (
          '<button type="button" class="pick' + (on ? " on" : "") + '" data-act="draft.pick" data-kind="' + kind + '" data-id="' + it.id + '">' +
          '<span class="tick">' + (on ? ico("check") : "") + "</span>" + render(it) + "</button>"
        );
      }).join("") + "</div>"
    );
  }

  function jobModal(job) {
    const j = job || {
      name: "", enabled: 1, schedule_times: "[]", interval_minutes: 0, window_hours: 24,
      max_items: 8, translate: 1, include_summary: 1, full_text: 1, send_image: 1, show_topic: 1, only_unseen: 1,
      filter_mode: "smart", exclude_keywords: "", feed_ids: [], topic_ids: [], destination_ids: [],
    };
    S.draft = {
      jobId: job ? job.id : null,
      times: safeJson(j.schedule_times, []).slice(),
      feed_ids: (j.feed_ids || []).map(Number),
      topic_ids: (j.topic_ids || []).map(Number),
      destination_ids: (j.destination_ids || []).map(Number),
    };
    openModal({
      title: job ? t("jobs.edit_title") : t("jobs.add_title"),
      wide: true,
      body:
        '<form data-form="job" id="jobForm">' +
        '<div class="form-grid">' +
          '<div class="span2">' + field(t("jobs.name"), '<input type="text" name="name" value="' + h(j.name) + '" placeholder="' + h(t("jobs.name_ph")) + '" dir="auto" required>') + "</div>" +
          '<div class="span2">' + field(t("jobs.schedule"),
            '<div id="timeWrap" class="inline">' + draftTimes() + "</div>" +
            '<div class="inline" style="margin-top:8px"><input type="time" name="newtime" id="newTime" style="width:130px" dir="ltr">' +
            '<button type="button" class="btn sm ghost" data-act="draft.addtime">' + ico("plus") + "<span>" + h(t("jobs.add_time")) + "</span></button></div>",
            t("jobs.schedule_hint")) + "</div>" +
          field(t("jobs.interval"), '<input class="ltr" type="number" name="interval_minutes" min="0" step="5" value="' + Number(j.interval_minutes || 0) + '">', t("jobs.interval_hint")) +
          field(t("jobs.window"), '<input class="ltr" type="number" name="window_hours" min="1" max="168" value="' + Number(j.window_hours || 24) + '">', t("jobs.window_hint")) +
          field(t("jobs.max_items"), '<input class="ltr" type="number" name="max_items" min="0" max="40" value="' + Number(j.max_items !== undefined && j.max_items !== null ? j.max_items : 8) + '">') +
          field(t("jobs.field.filterMode"), '<select class="input" name="filter_mode">' +
            ['all', 'smart', 'strict'].map((mode) => '<option value="' + mode + '"' + ((j.filter_mode || 'smart') === mode ? ' selected' : '') + '>' +
              h(t('jobs.filter.' + mode)) + '</option>').join('') + '</select>') +
          '<div class="span2">' + field(t("jobs.field.exclude"), '<input type="text" name="exclude_keywords" value="' + h(j.exclude_keywords || '') + '" dir="auto" placeholder="' + h(t("jobs.field.exclude")) + '">') + '</div>' +
        "</div>" +
        '<div class="sep-row"></div>' +
        '<div class="form-grid">' +
          '<div class="span2">' + field(t("jobs.feeds_pick"), '<div id="pickFeeds">' + picker("feed_ids", S.feeds, S.draft.feed_ids, (f) => h(f.title)) + "</div>", t("jobs.picks_feeds_hint")) + "</div>" +
          '<div class="span2">' + field(t("jobs.topics_pick"), '<div id="pickTopics">' + picker("topic_ids", S.topics, S.draft.topic_ids, (x) => h((x.emoji || "") + " " + x.name)) + "</div>", t("jobs.picks_topics_hint")) + "</div>" +
          '<div class="span2">' + field(t("jobs.destinations_pick"), '<div id="pickDests">' + picker("destination_ids", S.dests, S.draft.destination_ids, (d) => h(d.name + " · " + d.chat_id)) + "</div>") + "</div>" +
        "</div>" +
        '<div class="sep-row"></div>' +
        '<div class="form-grid">' +
          '<div class="checkline">' + toggleEl("translate", Number(j.translate)) + '<span class="ct"><b>' + h(t("jobs.field.translate")) + "</b></span></div>" +
          '<div class="checkline">' + toggleEl("include_summary", Number(j.include_summary)) + '<span class="ct"><b>' + h(t("jobs.field.summary")) + "</b></span></div>" +
          '<div class="checkline">' + toggleEl("full_text", Number(j.full_text !== undefined ? j.full_text : 1)) + '<span class="ct"><b>' + h(t("jobs.field.fullText")) + "</b></span></div>" +
          '<div class="checkline">' + toggleEl("send_image", Number(j.send_image)) + '<span class="ct"><b>' + h(t("jobs.field.image")) + "</b></span></div>" +
          '<div class="checkline">' + toggleEl("show_topic", Number(j.show_topic !== undefined ? j.show_topic : 1)) + '<span class="ct"><b>' + h(t("jobs.field.showTopic")) + "</b></span></div>" +
          '<div class="checkline">' + toggleEl("only_unseen", Number(j.only_unseen)) + '<span class="ct"><b>' + h(t("jobs.field.unseen")) + "</b></span></div>" +
          '<div class="checkline">' + toggleEl("enabled", Number(j.enabled)) + '<span class="ct"><b>' + h(t("jobs.enabled")) + "</b></span></div>" +
        "</div>" +
        "</form>",
      footer:
        '<button class="btn ghost" data-act="modal.close">' + t("common.cancel") + "</button>" +
        '<button class="btn primary" data-act="submit" data-form-id="jobForm">' + t("common.save") + "</button>",
    });
  }

  function draftTimes() {
    if (!S.draft || !S.draft.times.length)
      return '<span class="tiny mute">' + h(t("jobs.no_time")) + "</span>";
    return S.draft.times
      .map((x) => '<span class="tchip" style="display:inline-flex;align-items:center;gap:5px">' + h(x) +
        '<button type="button" data-act="draft.rmtime" data-time="' + h(x) + '" style="border:0;background:transparent;color:inherit;cursor:pointer;padding:0;display:grid;place-items:center">' +
        '<svg viewBox="0 0 24 24" width="10" height="10" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg></button></span>')
      .join("");
  }

  function showReport(report) {
    if (!report || report.ok === false) {
      const code = (report && report.error_code) || "unknown";
      toast(t("err." + code) !== "err." + code ? t("err." + code) : errMsg({ message: code }), "err");
      if (!report || !report.events) return;
    }
    const bars = [
      ["jobs.result_fetched", report.fetched, "acc"],
      ["jobs.result_window", report.in_window, ""],
      ["jobs.result_new", report.matched || report.new, ""],
      ["jobs.result_translated", report.translated, "acc"],
      ["jobs.result_sent", report.sent, "ok"],
      ["jobs.result_failed", report.failed, "bad"],
      ["jobs.result_skipped", report.skipped, ""],
      ["jobs.result_images", report.images, ""],
    ]
      .map((b) => '<div class="runbar ' + b[2] + (Number(b[1] || 0) === 0 ? " zero" : "") + '"><b>' +
        num(b[1] || 0) + "</b><span>" + h(t(b[0])) + "</span></div>")
      .join("");

    const events = (report.events || []).map((ev) => {
      const key = "ev." + ev.code;
      const dict = I18N[S.lang] || I18N.fa;
      const text = dict[key] ? t(key, ev.params || {}) : ev.code;
      const lvl = ev.level === "error" ? "bad" : ev.level === "warn" ? "warn" : "";
      return '<div class="list-line ' + lvl + '">' + ico(ev.level === "error" ? "alert" : ev.level === "warn" ? "info" : "check") + "<span>" + h(text) + "</span></div>";
    }).join("");

    const startEv = (report.events || []).find((e) => e.code === "run_start") || { params: {} };
    const windowH = (startEv.params || {}).window;
    const goBtn = (label, page) =>
      '<button class="btn soft sm" data-act="nav.item" data-page="' + page + '">' + h(label) + "</button>";
    const diagBox = (kind, titleKey, bodyKey, actions, params) =>
      '<div class="diag ' + kind + '"><span class="di">' + ico("alert") + "</span>" +
      '<div class="dt"><b>' + h(t(titleKey)) + "</b><p>" + h(t(bodyKey, params || {})) + "</p>" +
      (actions && actions.length ? '<div class="btns">' + actions.join("") + "</div>" : "") +
      "</div></div>";

    let diag = "";
    const code = report.error_code || "";
    if (code === "no_feeds") {
      diag = diagBox("bad", "report.diag_no_feeds_t", "report.diag_no_feeds_b", [goBtn(t("report.go_feeds"), "feeds")]);
    } else if (code === "no_destinations") {
      diag = diagBox("bad", "report.diag_no_dest_t", "report.diag_no_dest_b", [goBtn(t("report.go_channels"), "channels")]);
    } else if (!report.sent && !(report.matched > 0) && (report.in_window || 0) > 0) {
      diag = diagBox("warn", "report.diag_no_match_t", "report.diag_no_match_b",
        [goBtn(t("report.go_job"), "jobs")],
        { fetched: num(report.fetched || 0), window: num(windowH || 0) });
    }

    const previews = (report.previews || []).map((p) => {
      const msg = p.caption || p.message || p.text || "";
      return '<div class="previewbox" style="margin-bottom:8px" dir="auto">' + prettyHtml(String(msg).slice(0, 1800)) + "</div>";
    }).join("");

    openModal({
      title: t("jobs.report") + (report.dry_run ? " · " + t("jobs.dry_run") : "") + (report.job_name ? " · " + report.job_name : ""),
      wide: true,
      body:
        diag +
        '<div class="runbars">' + bars + "</div>" +
        '<div class="sep-row"></div>' + (events || '<div class="tiny mute">' + h(t("common.empty")) + "</div>") +
        (previews ? '<div class="sep-row"></div><div style="font-size:12px;font-weight:700;margin-bottom:8px">' + h(t("jobs.preview_msg")) + "</div>" + previews : ""),
      footer: '<button class="btn primary" data-act="modal.close">' + t("common.close") + "</button>",
    });
  }

  /* ── archive ──────────────────────────────────────────────────────────── */

  async function renderArchive(view) {
    view.innerHTML = '<div class="card"><div class="card-body"><div class="skeleton" style="width:35%"></div></div></div>';
    const q = S.archive.q || "";
    const status = S.archive.status || "all";
    const data = await api("/api/items?status=" + encodeURIComponent(status) + "&q=" + encodeURIComponent(q) + "&limit=80");
    const counts = data.counts || {};
    const total = data.total || 0;
    const sent = counts.sent || 0;
    const tabs = [
      ["all", t("common.all")],
      ["sent", t("items.status.sent")],
      ["failed", t("items.status.failed")],
      ["filtered", t("items.status.filtered")],
    ]
      .map((x) => '<button class="tab' + (status === x[0] ? " on" : "") + '" data-act="archive.filter" data-status="' + x[0] + '">' + h(x[1]) + "</button>")
      .join("");

    view.innerHTML =
      pageHead(t("items.title"), t("items.sub") + " · " + num(total) + " / " + num(sent),
        '<div class="inline"><input class="input" type="search" id="archSearch" placeholder="' + h(t("common.search")) + '" value="' + h(q) + '" style="width:240px">' +
        btn(t("common.search"), "archive.search", { cls: "ghost", icon: "search" }) + "</div>" +
        btn(t("items.clear"), "archive.clear", { cls: "danger sm", icon: "trash" })) +
      '<div class="tabs">' + tabs + "</div>" +
      '<section class="card"><div class="card-body flush"><div class="rows">' +
      ((data.items || []).length ? data.items.map((it) => itemRow(it)).join("")
        : emptyBox("inbox", t("items.empty"), t("items.empty"))) +
      "</div></div></section>";

    const inp = $("#archSearch");
    if (inp) {
      inp.addEventListener("keydown", (ev) => { if (ev.key === "Enter") ACTIONS["archive.search"](); });
      inp.addEventListener("input", () => { S.archive.q = inp.value; });
    }
  }

  async function refreshArchiveItem(itemId) {
    if (S.route !== "archive" && S.route !== "items") return;
    const q = S.archive.q || "";
    const data = await api("/api/items?status=all&q=" + encodeURIComponent(q) + "&limit=200");
    const item = (data.items || []).find((row) => Number(row.id) === Number(itemId));
    const status = S.archive.status || "all";
    const visible = item && (status === "all" || item.status === status);
    const rows = $("#view .rows");
    const current = $('[data-item-id="' + Number(itemId) + '"]');
    if (rows) {
      if (!visible) {
        if (current) current.remove();
      } else {
        const holder = document.createElement("div");
        holder.innerHTML = itemRow(item);
        const replacement = holder.firstElementChild;
        if (replacement) {
          if (current) current.replaceWith(replacement);
          else {
            const next = Array.from(rows.querySelectorAll(".irow")).find((row) => Number(row.dataset.itemId) < Number(item.id));
            if (next) next.before(replacement);
            else rows.appendChild(replacement);
          }
        }
      }
      if (!rows.querySelector(".irow")) rows.innerHTML = emptyBox("inbox", t("items.empty"), t("items.empty"));
    }
    const counts = data.counts || {};
    const sub = $("#view .page-intro-copy p");
    if (sub) sub.textContent = t("items.sub") + " · " + num(data.total || 0) + " / " + num(counts.sent || 0);
  }

  /* ── logs ─────────────────────────────────────────────────────────────── */

  async function renderLogs(view) {
    const data = await api("/api/logs?limit=120");
    const logs = data.logs || [];
    view.innerHTML =
      pageHead(t("logs.title"), t("logs.subtitle"),
        btn(t("logs.send_to_creator"), "creators.bug", { cls: "ghost", icon: "alert" }) +
        btn("", "reload", { cls: "ghost", icon: "refresh" })) +
      '<section class="card"><div class="card-body flush">' +
      (logs.length ? logs.map(logLine).join("") : emptyBox("list", t("logs.empty"), "")) +
      "</div></section>";
  }

  /* ── settings ─────────────────────────────────────────────────────────── */

  async function renderSettings(view) {
    view.innerHTML = '<div class="card"><div class="card-body"><div class="skeleton" style="width:40%"></div></div></div>';
    const [s, rt] = await Promise.all([loadSettings(), api("/api/runtime")]);
    const providers = (S.meta && S.meta.translation_providers) || [];
    const provLabel = (id) => {
      const p = providers.find((x) => x.id === id);
      if (!p) return id;
      return isFa() ? p.name_fa : p.name_en;
    };
    const themes = (S.meta && S.meta.themes) || [];
    const langs = (S.meta && S.meta.languages) || [];

    const general =
      '<form data-form="settings-general" id="setGeneral">' +
      '<div class="form-grid">' +
        field(t("settings.panel_title"), '<input type="text" name="panel_title" value="' + h(s.panel_title) + '" dir="auto">') +
        field(t("common.timezone"), '<input class="ltr" type="text" name="timezone" value="' + h(s.timezone) + '" placeholder="Asia/Tehran">') +
        field(t("admin.default_theme"), '<select name="theme">' + themes.map((x) =>
          '<option value="' + x.id + '"' + (x.id === s.theme ? " selected" : "") + ">" + h(isFa() ? x.name_fa : x.name_en) + "</option>").join("") + "</select>") +
        field(t("admin.default_language"), '<select name="language">' + langs.map((x) =>
          '<option value="' + x.id + '"' + (x.id === s.language ? " selected" : "") + ">" + h(isFa() ? x.name_fa : x.name_en) + "</option>").join("") + "</select>") +
        '<div class="span2">' + field(t("settings.footer"), '<input type="text" name="global_footer" value="' + h(s.global_footer) + '" dir="auto">', t("settings.per_item_note")) + "</div>" +
        field(t("settings.max_chars"), '<input class="ltr" type="number" name="max_message_chars" min="400" max="4096" value="' + h(s.max_message_chars) + '">') +
        field(t("settings.feedback_webhook"), '<input class="ltr" type="url" name="feedback_webhook" value="" placeholder="' + h(s.feedback_webhook_set ? t("settings.key_set") : "https://") + '">', t("settings.feedback_hint")) +
      "</div>" +
      '<div class="checkline">' + toggleEl("signature_enabled", Number(s.signature_enabled)) +
        '<span class="ct"><b>' + h(t("settings.signature")) + "</b></span></div>" +
      '<div class="inline" style="margin-top:4px"><button class="btn primary" data-act="submit" data-form-id="setGeneral">' + ico("check") + "<span>" + h(t("common.save")) + "</span></button></div>" +
      "</form>";

    const translation =
      '<form data-form="settings-translation" id="setTrans">' +
      '<div class="form-grid">' +
        field(t("settings.provider"), '<select name="translate_provider">' + providers.map((p) =>
          '<option value="' + p.id + '"' + (p.id === s.translate_provider ? " selected" : "") + ">" + h(provLabel(p.id)) + "</option>").join("") + "</select>", t("settings.provider_hint")) +
        field(t("settings.fallback"), '<select name="translate_fallback">' + providers.map((p) =>
          '<option value="' + p.id + '"' + (p.id === s.translate_fallback ? " selected" : "") + ">" + h(provLabel(p.id)) + "</option>").join("") + "</select>") +
        field(t("settings.base_url"), '<input class="ltr" type="url" name="deepseek_base_url" value="' + h(s.deepseek_base_url) + '">') +
        field(t("settings.model"), '<input class="ltr" type="text" name="deepseek_model" value="' + h(s.deepseek_model) + '">') +
        '<div class="span2">' + field(t("settings.api_key"),
          '<input class="ltr" type="text" name="deepseek_api_key" value="' + h(s.deepseek_api_key || "") + '" placeholder="sk-…" autocomplete="off">',
          s.deepseek_key_set ? t("settings.key_set") : t("settings.key_missing")) + "</div>" +
        '<div class="span2">' + field(t("settings.glossary"), '<textarea name="translate_glossary" rows="2" dir="auto">' + h(s.translate_glossary) + "</textarea>", t("settings.glossary_hint")) + "</div>" +
      "</div>" +
      '<div class="checkline">' + toggleEl("translate_post_edit", Number(s.translate_post_edit)) +
        '<span class="ct"><b>' + h(t("settings.post_edit")) + "</b></span></div>" +
      '<div class="checkline">' + toggleEl("translate_preserve", Number(s.translate_preserve)) +
        '<span class="ct"><b>' + h(t("settings.preserve")) + "</b></span></div>" +
      '<div class="inline" style="margin-top:4px"><button class="btn primary" data-act="submit" data-form-id="setTrans">' + ico("check") + "<span>" + h(t("common.save")) + "</span></button>" +
      '<button type="button" class="btn ghost" data-act="translate.test">' + ico("zap") + "<span>" + h(t("settings.test_translation")) + "</span></button></div>" +
      "</form>";

    const security =
      '<form data-form="settings-security" id="setSec">' +
      '<div class="form-grid">' +
        field(t("settings.current_password"), '<input class="ltr" type="password" name="current_password" autocomplete="current-password" required>') +
        field(t("settings.new_password"), '<input class="ltr" type="password" name="new_password" minlength="5" autocomplete="new-password" required>') +
      "</div>" +
      '<button class="btn primary" data-act="submit" data-form-id="setSec">' + ico("key") + "<span>" + h(t("settings.change_password")) + "</span></button>" +
      "</form>";

    const runtime =
      '<div class="stack">' +
      [["common.version", "v" + rt.version], ["settings.data_dir", rt.data_dir], ["common.timezone", rt.timezone],
       ["settings.uptime", uptime(rt.uptime_seconds)],
       ["settings.health", (rt.scheduler && rt.scheduler.enabled ? t("dash.scheduler_on") : t("dash.scheduler_off"))]]
        .map((row) => '<div class="kv"><span>' + h(t(row[0])) + '</span><b class="txt mono" dir="ltr" style="font-size:11px">' + h(row[1]) + "</b></div>")
        .join("") + "</div>";

    view.innerHTML =
      pageHead(t("settings.title"), t("settings.subtitle"), btn(t("admin.title"), "nav.item", { cls: "ghost", icon: "shield", extra: ' data-page="admin"' })) +
      '<div class="grid side"><div class="stack">' +
        card(t("settings.general"), "sliders", general) +
        card(t("settings.translation"), "globe", translation) +
        card(t("settings.security"), "shield", security) +
      "</div><div class=\"stack\">" +
        card(t("settings.publish"), "send",
          '<div class="list-line">' + ico("check") + "<span>" + h(t("settings.per_item")) + "</span></div>" +
          '<div class="list-line">' + ico("check") + "<span>" + h(t("settings.per_item_note")) + "</span></div>" +
          '<div class="list-line">' + ico("check") + "<span>" + h(t("settings.token_note")) + "</span></div>") +
        card(t("settings.runtime"), "server", runtime) +
      "</div></div>";
  }

  /* ── admin ────────────────────────────────────────────────────────────── */

  async function renderAdmin(view) {
    view.innerHTML = '<div class="card"><div class="card-body"><div class="skeleton" style="width:35%"></div></div></div>';
    const ov = await api("/api/admin/overview");
    const tabs = [
      ["links", t("admin.tab.links"), "link"],
      ["appearance", t("admin.tab.appearance"), "sun"],
      ["data", t("admin.tab.data"), "database"],
      ["access", t("admin.tab.access"), "key"],
    ]
      .map((x) => '<button class="tab' + (S.adminTab === x[0] ? " on" : "") + '" data-act="admin.tab" data-tab="' + x[0] + '">' + h(x[1]) + "</button>")
      .join("");

    let body = "";
    if (S.adminTab === "links") body = await adminLinks();
    else if (S.adminTab === "appearance") body = await adminAppearance();
    else if (S.adminTab === "data") body = adminData(ov);
    else body = adminAccess(ov);

    view.innerHTML =
      pageHead(t("admin.title"), t("admin.subtitle"),
        '<span class="chip accent mono">v' + h(ov.version) + "</span>" +
        btn("", "reload", { cls: "ghost", icon: "refresh" })) +
      (ov.password_is_bootstrap ? '<div class="banner">' + ico("alert") + "<span>" + h(t("settings.bootstrap_warning")) + "</span></div>" : "") +
      '<div class="tabs">' + tabs + "</div>" + body;
  }

  async function adminLinks() {
    await loadFeeds();
    const rows = S.feeds.map((f, idx) => {
      const col = colorOf(f.color);
      return (
        '<div class="frow admin-feed-row" data-feed="' + f.id + '">' +
          '<div class="favatar admin-feed-avatar" style="width:30px;height:30px;background:' + tint(col, .14) + ";border-color:" + tint(col, .4) + ";color:" + col + ';font-size:14px">' + h(f.icon) + "</div>" +
          '<div class="fname admin-feed-name"><b dir="auto">' + h(f.title) + '</b><span>' + h(f.url) + "</span></div>" +
          '<label class="admin-feed-cell admin-feed-icon-edit"><span class="admin-feed-mobile-label">' + h(t("admin.icon")) + '</span><input type="text" value="' + h(f.icon) + '" maxlength="4" dir="ltr" style="text-align:center;min-height:30px;padding:2px 4px" data-act="admin.icon" data-id="' + f.id + '" title="' + h(t("admin.icon")) + '"></label>' +
          '<label class="admin-feed-cell admin-feed-color"><span class="admin-feed-mobile-label">' + h(t("admin.color")) + '</span><span class="inline admin-feed-color-select"><span class="color-dot" style="background:' + col + '"></span><select data-act="admin.color" data-id="' + f.id + '" style="min-height:30px;padding:2px 8px" title="' + h(t("admin.color")) + '">' +
            Object.keys(COLORS).map((ck) => '<option value="' + ck + '"' + (ck === f.color ? " selected" : "") + ">" + ck + "</option>").join("") + "</select></span></label>" +
          '<div class="admin-feed-cell admin-feed-show-url"><span class="admin-feed-mobile-label">' + h(t("admin.show_url")) + '</span><button class="toggle' + (Number(f.show_url) ? " on" : "") + '" data-act="admin.showurl" data-id="' + f.id + '" title="' + h(t("admin.show_url")) + '"></button></div>' +
          '<div class="iact admin-feed-actions">' +
            (idx > 0 ? iconBtn("arrowUp", "feed.up", f.id, "ghost", t("admin.move_up")) : "") +
            (idx < S.feeds.length - 1 ? iconBtn("arrowDown", "feed.down", f.id, "ghost", t("admin.move_down")) : "") +
            iconBtn("edit", "feed.edit", f.id, "ghost", t("common.edit")) +
            iconBtn("trash", "feed.del", f.id, "ghost", t("common.delete")) + "</div>" +
        "</div>"
      );
    }).join("");

    return (
      '<section class="card"><div class="card-head"><h2 class="admin-feed-title">' + ico("newspaper") + h(t("admin.newsSources")) + "</h2>" +
        '<div class="btns">' + btn(t("feeds.bulk"), "feed.bulk", { cls: "ghost sm", icon: "layers" }) +
        btn(t("feeds.add"), "feed.new", { cls: "primary sm", icon: "plus" }) + "</div></div>" +
        '<div class="card-body"><div class="tiny mute" style="margin-bottom:12px">' + h(t("admin.links_hint")) + "</div></div>" +
        '<div class="card-body flush"><div class="rows">' +
        (S.feeds.length
          ? '<div class="frow fhead admin-feed-head"><div></div><div>' + h(t("common.source")) +
            "</div><div>" + h(t("admin.icon")) + "</div><div>" + h(t("admin.color")) + "</div><div>" + h(t("admin.show_url")) +
            '</div><div style="text-align:end">' + h(t("common.actions")) + "</div></div>" + rows
          : emptyBox("link", t("feeds.empty"), t("feeds.empty_hint"))) +
        "</div></div></section>"
    );
  }

  async function adminAppearance() {
    const s = await loadSettings();
    const themes = (S.meta && S.meta.themes) || [];
    const langs = (S.meta && S.meta.languages) || [];
    const themeCards = themes.map((x) =>
      '<button type="button" class="pick opt' + (S.theme === x.id ? " on" : "") + '" data-act="theme.set" data-theme="' + x.id + '">' +
      '<span class="swatch ' + x.id + '"></span>' +
      "<span>" + h(isFa() ? x.name_fa : x.name_en) + "<small>" + (x.mode === "dark" ? "dark" : "light") + "</small></span>" +
      (S.theme === x.id ? '<span class="tick right">' + ico("check") + "</span>" : "") + "</button>").join("");
    const langCards = langs.map((x) =>
      '<button type="button" class="pick opt' + (S.lang === x.id ? " on" : "") + '" data-act="lang.set" data-lang="' + x.id + '">' +
      ico("globe") + "<span>" + h(isFa() ? x.name_fa : x.name_en) + "<small>" + h(x.dir.toUpperCase()) + "</small></span>" +
      (S.lang === x.id ? '<span class="tick right">' + ico("check") + "</span>" : "") + "</button>").join("");

    return (
      '<div class="grid side"><div class="stack">' +
        card(t("common.theme"), "sun", '<div class="opt-grid">' + themeCards + "</div>") +
        card(t("common.language"), "globe", '<div class="opt-grid">' + langCards + "</div>") +
      '</div><div class="stack">' +
        card(t("admin.tab.appearance"), "sliders",
          '<form data-form="admin-appearance" id="setAppear">' +
          field(t("common.timezone"), '<input class="ltr" type="text" name="timezone" value="' + h(s.timezone) + '">') +
          field(t("settings.panel_title"), '<input type="text" name="panel_title" value="' + h(s.panel_title) + '" dir="auto">') +
          '<button class="btn primary" data-act="submit" data-form-id="setAppear">' + ico("check") + "<span>" + h(t("common.save")) + "</span></button></form>",
          false) +
      "</div></div>"
    );
  }

  function adminData(ov) {
    const counts = ov.counts || {};
    const rows = Object.keys(counts).map((k) =>
      '<div class="kv"><span>' + h(k) + '</span><b>' + num(counts[k]) + "</b></div>").join("");
    return (
      '<div class="grid side"><div class="stack">' +
        card(t("admin.export"), "download",
          '<p class="tiny mute" style="margin:0 0 12px">' + h(t("admin.export_hint")) + "</p>" +
          '<button class="btn primary" data-act="admin.export">' + ico("download") + "<span>" + h(t("admin.export_btn")) + "</span></button>") +
        card(t("admin.import"), "upload",
          '<form data-form="admin-import" id="setImport">' +
          '<p class="tiny mute" style="margin:0 0 8px">' + h(t("admin.import_hint")) + "</p>" +
          '<textarea class="code" name="payload" rows="7" placeholder="{ ... }"></textarea>' +
          '<button class="btn danger" data-act="submit" data-form-id="setImport" style="margin-top:10px">' + ico("upload") + "<span>" + h(t("admin.import_btn")) + "</span></button></form>") +
      '</div><div class="stack">' +
        card(t("admin.counts"), "database",
          '<div class="stack">' + rows +
          '<div class="kv"><span>' + h(t("admin.db_size")) + '</span><b>' + h(bytes(ov.db_size)) + "</b></div>" +
          '<div class="kv"><span>' + h(t("settings.uptime")) + '</span><b class="txt">' + h(uptime(ov.uptime_seconds)) + "</b></div>" +
          '<div class="kv"><span>' + h(t("common.version")) + '</span><b>v' + h(ov.version) + "</b></div>" +
          "</div>") +
        card(t("admin.danger"), "alert",
          '<p class="tiny mute" style="margin:0 0 12px">' + h(t("admin.clear_archive_hint")) + "</p>" +
          '<button class="btn danger" data-act="admin.clearArchive">' + ico("trash") + "<span>" + h(t("admin.clear_archive")) + "</span></button>") +
      "</div></div>"
    );
  }

  function adminAccess(ov) {
    const sessions = ov.sessions || [];
    return (
      '<div class="grid side"><div class="stack">' +
        card(t("settings.security"), "key",
          '<form data-form="settings-security" id="setSecAdmin">' +
          '<div class="form-grid">' +
          field(t("settings.current_password"), '<input class="ltr" type="password" name="current_password" required autocomplete="current-password">') +
          field(t("settings.new_password"), '<input class="ltr" type="password" name="new_password" minlength="5" required autocomplete="new-password">') +
          "</div><button class=\"btn primary\" data-act=\"submit\" data-form-id=\"setSecAdmin\">" + ico("key") + "<span>" + h(t("settings.change_password")) + "</span></button></form>") +
      '</div><div class="stack">' +
        card(t("admin.sessions"), "shield",
          '<div class="tiny mute" style="margin-bottom:10px">' + h(t("admin.sessions_hint")) + "</div>" +
          '<div class="stack">' + (sessions.length
            ? sessions.map((s) => '<div class="kv"><span class="mono tiny">' + h(s.token) + "</span><b class=\"txt tiny\">" + h(fmtDate(s.created_at)) + "</b></div>").join("")
            : '<div class="tiny mute">' + h(t("common.none")) + "</div>") + "</div>" +
          '<button class="btn ghost" data-act="admin.clearSessions" style="margin-top:12px">' + ico("logout") + "<span>" + h(t("admin.clear_sessions")) + "</span></button>") +
        card(t("settings.runtime"), "server",
          '<div class="kv"><span>Python</span><b>' + h(ov.python) + "</b></div>" +
          '<div class="kv"><span>' + h(t("settings.data_dir")) + '</span><b class="txt tiny mono" style="max-width:60%;overflow:hidden;text-overflow:ellipsis">' + h(ov.data_dir) + "</b></div>") +
      "</div></div>"
    );
  }

  /* ── creators ─────────────────────────────────────────────────────────── */

  async function renderCreators(view) {
    const [data, editor] = await Promise.all([
      api("/api/creators"),
      api("/api/creators/auth/session"),
    ]);
    S.creators = data.creators || [];
    S.edu = data.edu || {};
    S.creatorEditor = Object.assign({ configured: false, authenticated: false, botConfigured: false }, editor || {});
    if (S.creatorEditor.authenticated) {
      const botStatus = await api("/api/creators/contact-bot");
      S.creatorEditor.botConfigured = Boolean(botStatus.configured);
      S.creatorEditor.botSource = botStatus.source || "";
    }
    const editorState = S.creatorEditor;
    const creatorCards = S.creators.map((creator) => {
      const name = creator.name ? creator.name.split("|").map((part) => part.trim())[isFa() ? 0 : 1] || creator.name : t("creators.slot", { n: creator.slot });
      const role = isFa() ? (creator.role_fa || "") : (creator.role_en || "");
      const bio = isFa() ? (creator.bio_fa || "") : (creator.bio_en || "");
      const quote = isFa() ? (creator.quote_fa || "") : (creator.quote_en || "");
      const skills = Array.isArray(creator.skills) ? creator.skills : String(creator.skills_raw || "").split(",").filter(Boolean);
      const avatar = creator.avatar ? '<img class="creator-avatar" src="' + h(creator.avatar) + '" alt="" loading="lazy" onerror="this.remove()">' :
        '<div class="creator-avatar-fallback">' + h(creator.slot === 1 ? 'N' : 'A') + '</div>';
      const links = [
        creator.telegram ? '<a class="btn btn-sm" href="' + h(creator.telegram.startsWith("http") ? creator.telegram : "https://t.me/" + creator.telegram.replace(/^@/, "")) + '" target="_blank" rel="noopener">' + ico("telegram") + '<span>Telegram</span></a>' : "",
        creator.github ? '<a class="btn btn-sm" href="' + h(creator.github.startsWith("http") ? creator.github : "https://github.com/" + creator.github.replace(/^@/, "")) + '" target="_blank" rel="noopener">' + ico("code") + '<span>GitHub</span></a>' : "",
        creator.email ? '<a class="btn btn-sm" href="mailto:' + h(creator.email) + '">' + ico("mail") + '<span>' + h(creator.email) + '</span></a>' : "",
        creator.website ? '<a class="btn btn-sm" href="' + h(creator.website) + '" target="_blank" rel="noopener">' + ico("globe") + '<span>Web</span></a>' : "",
      ].join("");
      return '<article class="creator-card"><div class="creator-header">' + avatar + '<div><h3 class="creator-name" dir="auto">' + h(name) + '</h3>' +
        '<div class="creator-role">' + h(role) + '</div></div></div>' +
        (quote ? '<blockquote class="creator-quote" dir="auto">' + h(quote) + '</blockquote>' : '') +
        (bio ? '<p class="creator-bio" dir="auto">' + h(bio) + '</p>' : '') +
        (skills.length ? '<div class="creator-skills">' + skills.map((skill) => '<span class="skill-chip">' + h(skill) + '</span>').join('') + '</div>' : '') +
        '<div class="creator-links">' + links + (editorState.authenticated ? '<button class="btn btn-sm creator-edit" type="button" data-act="creator.edit" data-slot="' + creator.slot + '">' + ico("edit") + '<span>' + h(t("creators.editProfile")) + '</span></button>' : '') + '</div></article>';
    }).join("");

    const edu = S.edu || {};
    const youtubeId = edu.youtube_id || "@nextgen-ain8n";
    const youtubeUrl = edu.youtube_url || "https://youtube.com/@nextgen-ain8n";
    const telegramId = edu.telegram_id || "@nextgen_ain8n";
    const telegramUrl = edu.telegram_url || "https://t.me/nextgen_ain8n";
    const eduTopics = isFa() ? (edu.topics_fa || "") : (edu.topics_en || "");
    const version = (S.meta && S.meta.version) || "1.08";
    let creatorActions = btn(t("creators.feedbackTitle"), "creators.bug", { cls: "ghost", icon: "message" });
    if (editorState.authenticated) {
      creatorActions = btn(t("creators.editorLogout"), "creator.logout", { cls: "ghost", icon: "logout" }) +
        btn(t("creators.contactBot"), "creator.contactBot", { cls: "ghost", icon: "key" }) +
        btn(t("creators.editEducation"), "creator.editEducation", { cls: "ghost", icon: "edit" }) + creatorActions;
    } else if (editorState.configured) {
      creatorActions = btn(t("creators.creatorLogin"), "creator.login", { cls: "primary", icon: "key" }) + creatorActions;
    }
    const editorSetupHint = !editorState.configured
      ? '<div class="banner creator-editor-hint">' + ico("info") + '<span>' + h(t("creators.editorNotConfigured")) + '</span></div>'
      : "";

    view.innerHTML = pageHead(t("creators.title"), t("creators.sub"), creatorActions) + editorSetupHint +
      '<section class="hero-banner creators-hero"><div class="hero-top"><div><h2 class="hero-title">' + h(t("creators.heroBadge")) + '</h2>' +
      '<p class="hero-sub">' + h(t("creators.sub")) + '</p></div><span class="pill brand">Rozaneh v' + h(version) + '</span></div></section>' +
      '<div class="grid cols-2 creator-grid">' + (creatorCards || '<div class="empty">' + h(t("creators.empty")) + '</div>') + '</div>' +
      '<section class="edu-banner" style="margin-top:20px"><div><span class="pill brand">NextGen AI · n8n</span>' +
      '<h2 class="hero-title" style="margin-top:12px">' + h(t("creators.eduTitle")) + '</h2>' +
      '<p class="hero-sub">' + h(t("creators.eduSub")) + '</p>' +
      (eduTopics ? '<div class="creator-skills" style="margin-top:15px">' + eduTopics.split(/[·,،]/).map((tag) => tag.trim()).filter(Boolean).map((tag) => '<span class="skill-chip">' + h(tag) + '</span>').join('') + '</div>' : '') +
      '</div><div class="stack"><div class="edu-channel-card"><div><div class="card-sub">YouTube</div><div class="edu-id ltr">' + h(youtubeId) + '</div></div>' +
      '<div class="inline"><button class="btn btn-sm" type="button" data-act="creators.copy" data-copy="' + h(youtubeId) + '">' + ico("copy") + '<span>' + h(t("creators.copyId")) + '</span></button>' +
      '<a class="btn btn-primary btn-sm" href="' + h(youtubeUrl) + '" target="_blank" rel="noopener">' + ico("play") + '<span>' + h(t("creators.youtubeBtn")) + '</span></a></div></div>' +
      '<div class="edu-channel-card"><div><div class="card-sub">Telegram</div><div class="edu-id ltr">' + h(telegramId) + '</div></div>' +
      '<div class="inline"><button class="btn btn-sm" type="button" data-act="creators.copy" data-copy="' + h(telegramId) + '">' + ico("copy") + '<span>' + h(t("creators.copyId")) + '</span></button>' +
      '<a class="btn btn-primary btn-sm" href="' + h(telegramUrl) + '" target="_blank" rel="noopener">' + ico("telegram") + '<span>' + h(t("creators.telegramBtn")) + '</span></a></div></div></div></section>' +
      '<div class="grid cols-2" style="margin-top:20px"><section class="card"><div class="card-head"><div><h2 class="card-title">' +
      ico("mail") + h(t("creators.feedbackTitle")) + '</h2><p class="card-sub">' + h(t("creators.feedbackSub")) + '</p></div></div><div class="card-body">' +
      '<form class="form" data-form="feedback" id="contactForm"><div class="form-row">' +
      field(t("creators.yourName"), '<input class="input" type="text" name="name" dir="auto">') +
      field(t("creators.contact"), '<input class="input" type="text" name="contact" dir="auto" placeholder="@username">') + '</div>' +
      field(t("creators.message"), '<textarea class="input" name="message" rows="4" dir="auto" placeholder="' + h(t("creators.message")) + '" required minlength="3"></textarea>') +
      '<button class="btn btn-primary" type="button" data-act="submit" data-form-id="contactForm">' + ico("send") + '<span>' + h(t("creators.send")) + '</span></button></form></div></section>' +
      '<section class="card"><div class="card-head"><h2 class="card-title">' + ico("sparkles") + h(t("creators.about")) + '</h2></div><div class="card-body">' +
      '<p class="creator-bio" dir="auto">' + h(isFa() ? "روزنه منابع خبری را می‌خواند، خبرها را هوشمندانه دسته‌بندی و ترجمه می‌کند، متن و تصویر واقعی مقاله را استخراج می‌کند و انتشار در کانال‌ها را زمان‌بندی می‌کند. تحلیلگر لینک و ویدیو نیز استخراج، خلاصه‌سازی و آماده‌سازی پیام قابل ویرایش را در یک محیط یکپارچه فراهم می‌کند." :
      "Rozaneh reads news sources, classifies and translates stories, extracts article text and images, and schedules channel publishing. Its link and video analyzer extracts, summarizes, and prepares editable channel drafts in one workspace.") + '</p>' +
      '<div class="kv"><span>' + h(t("common.version")) + '</span><b>v' + h(version) + '</b></div>' +
      '<div class="kv"><span>' + h(t("creators.built_with")) + '</span><b class="txt">FastAPI · SQLite · Vanilla JS</b></div>' +
      '<div class="kv"><span>' + h(t("admin.deployReady")) + '</span><b class="txt">Docker · Railway · Render · Fly.io · Cloudflare</b></div>' +
      '<div class="kv"><span>' + h(t("creators.license")) + '</span><b class="txt">MIT</b></div></div></section></div>';
  }

  function creatorModal(slot) {
    const c = (S.creators || []).find((x) => Number(x.slot) === Number(slot)) || { slot: slot };
    openModal({
      title: t("creators.slot", { n: slot }),
      wide: true,
      body:
        '<form data-form="creator" id="creatorForm" data-slot="' + slot + '">' +
        '<div class="form-grid">' +
        field(t("creators.name"), '<input type="text" name="creator' + slot + '_name" value="' + h(c.name) + '" dir="auto">') +
        field(t("creators.roleFa"), '<input type="text" name="creator' + slot + '_role_fa" value="' + h(c.role_fa) + '" dir="auto">') +
        field(t("creators.roleEn"), '<input class="ltr" type="text" name="creator' + slot + '_role_en" value="' + h(c.role_en) + '">') +
        field(t("creators.telegram"), '<input class="ltr" type="url" name="creator' + slot + '_telegram" value="' + h(c.telegram) + '" placeholder="https://t.me/username">') +
        field(t("creators.github"), '<input class="ltr" type="url" name="creator' + slot + '_github" value="' + h(c.github) + '" placeholder="https://github.com/username">') +
        field(t("creators.email"), '<input class="ltr" type="email" name="creator' + slot + '_email" value="' + h(c.email) + '">') +
        field(t("creators.website"), '<input class="ltr" type="url" name="creator' + slot + '_website" value="' + h(c.website) + '">') +
        field(t("creators.avatar"), '<input class="ltr" type="url" name="creator' + slot + '_avatar" value="' + h(c.avatar) + '">') +
        '<div class="span2">' + field(t("creators.quoteFa"), '<input type="text" name="creator' + slot + '_quote_fa" value="' + h(c.quote_fa) + '" dir="auto">') + '</div>' +
        '<div class="span2">' + field(t("creators.quoteEn"), '<input class="ltr" type="text" name="creator' + slot + '_quote_en" value="' + h(c.quote_en) + '">') + '</div>' +
        '<div class="span2">' + field(t("creators.skills"), '<input type="text" name="creator' + slot + '_skills" value="' + h(c.skills_raw || '') + '" dir="auto" placeholder="Python, AI, n8n">') + '</div>' +
        '<div class="span2">' + field(t("creators.bioFa"), '<textarea name="creator' + slot + '_bio_fa" rows="3" dir="auto">' + h(c.bio_fa) + "</textarea>") + "</div>" +
        '<div class="span2">' + field(t("creators.bioEn"), '<textarea name="creator' + slot + '_bio_en" rows="3" dir="ltr">' + h(c.bio_en) + "</textarea>") + "</div>" +
        "</div></form>",
      footer:
        '<button class="btn ghost" data-act="modal.close">' + t("common.cancel") + "</button>" +
        '<button class="btn primary" data-act="submit" data-form-id="creatorForm">' + t("common.save") + "</button>",
    });
  }

  function creatorLoginModal() {
    openModal({
      title: t("creators.editorLoginTitle"),
      body: '<form class="form" data-form="creator-login" id="creatorLoginForm" autocomplete="on">' +
        field(t("creators.username"), '<input class="input ltr" type="text" name="username" maxlength="128" autocomplete="username" required>') +
        field(t("creators.password"), '<input class="input ltr" type="password" name="password" autocomplete="current-password" required>') +
        '</form>',
      footer: '<button class="btn ghost" data-act="modal.close">' + h(t("common.cancel")) + '</button>' +
        '<button class="btn primary" data-act="submit" data-form-id="creatorLoginForm">' + ico("key") + '<span>' + h(t("creators.creatorLogin")) + '</span></button>',
    });
  }

  function creatorEducationModal() {
    const edu = S.edu || {};
    openModal({
      title: t("creators.editEducation"),
      wide: true,
      body: '<form class="form" data-form="creator-edu" id="creatorEduForm"><div class="form-grid">' +
        field(t("creators.eduYoutubeId"), '<input class="input ltr" type="text" name="edu_youtube_id" value="' + h(edu.youtube_id || "") + '">') +
        field(t("creators.eduYoutubeUrl"), '<input class="input ltr" type="url" name="edu_youtube_url" value="' + h(edu.youtube_url || "") + '">') +
        field(t("creators.eduTelegramId"), '<input class="input ltr" type="text" name="edu_telegram_id" value="' + h(edu.telegram_id || "") + '">') +
        field(t("creators.eduTelegramUrl"), '<input class="input ltr" type="url" name="edu_telegram_url" value="' + h(edu.telegram_url || "") + '">') +
        '<div class="span2">' + field(t("creators.eduTopicsFa"), '<textarea class="input" name="edu_topics_fa" rows="3" dir="auto">' + h(edu.topics_fa || "") + '</textarea>') + '</div>' +
        '<div class="span2">' + field(t("creators.eduTopicsEn"), '<textarea class="input ltr" name="edu_topics_en" rows="3" dir="ltr">' + h(edu.topics_en || "") + '</textarea>') + '</div>' +
        '</div></form>',
      footer: '<button class="btn ghost" data-act="modal.close">' + h(t("common.cancel")) + '</button>' +
        '<button class="btn primary" data-act="submit" data-form-id="creatorEduForm">' + h(t("common.save")) + '</button>',
    });
  }

  function creatorContactBotModal() {
    const status = S.creatorEditor || {};
    openModal({
      title: t("creators.contactBot"),
      body: '<div class="banner ' + (status.botConfigured ? 'ok' : '') + '">' + ico(status.botConfigured ? "check" : "info") + '<span>' +
        h(t(status.botConfigured ? "creators.contactBotConfigured" : "creators.contactBotMissing")) + '</span></div>' +
        '<form class="form" data-form="creator-contact-token" id="creatorContactBotForm">' +
        field(t("creators.contactBotToken"), '<input class="input ltr" type="password" name="bot_token" autocomplete="new-password" placeholder="' + h(t(status.botConfigured ? "settings.key_set" : "creators.contactBotMissing")) + '" required>', t("creators.contactBotHint")) +
        '</form>',
      footer: '<button class="btn ghost" data-act="modal.close">' + h(t("common.cancel")) + '</button>' +
        '<button class="btn primary" data-act="submit" data-form-id="creatorContactBotForm">' + ico("check") + '<span>' + h(t("common.save")) + '</span></button>',
    });
  }

  function feedbackModal(prefill) {
    openModal({

      title: t("creators.bug_report"),
      body:
        '<form data-form="feedback" id="bugForm">' +
        field(t("creators.message"), '<textarea name="message" rows="7" dir="auto" required minlength="3">' + h(prefill || "") + "</textarea>") +
        '<div class="form-grid">' +
        field(t("creators.your_name"), '<input type="text" name="name" dir="auto">') +
        field(t("creators.your_contact"), '<input type="text" name="contact" dir="auto" placeholder="@username">') +
        "</div></form>",
      footer:
        '<button class="btn ghost" data-act="modal.close">' + t("common.cancel") + "</button>" +
        '<button class="btn primary" data-act="submit" data-form-id="bugForm">' + t("creators.send") + "</button>",
    });
  }

  /* ── forms ────────────────────────────────────────────────────────────── */

  function tgVal(form, name) {
    const el = form.querySelector('[data-tg="' + name + '"]');
    return el && el.classList.contains("on") ? 1 : 0;
  }
  function fd(form) {
    const out = {};
    new FormData(form).forEach((v, k) => { out[k] = typeof v === "string" ? v.trim() : v; });
    return out;
  }

  async function submitForm(form) {
    const kind = form.dataset.form;
    const v = fd(form);

    if (kind === "analyzer") {
      const url = (v.url || "").trim();
      if (!/^https?:\/\//i.test(url)) { toast(t("err.url_invalid"), "err"); return; }
      const button = form.querySelector('[data-act="submit"]');
      if (button) { button.disabled = true; button.dataset.oldLabel = button.innerHTML; button.innerHTML = '<span class="spinner" style="width:16px;height:16px"></span><span>' + h(t("an.processing")) + '</span>'; }
      try {
        const response = await api("/api/analyzer", { method: "POST", body: {
          url: url,
          custom_text: v.custom_text || "",
          include_link: v.include_link ? 1 : 0,
          send_image: v.send_image ? 1 : 0,
          wait: false,
        }});
        S.currentAnalysis = response.analysis;
        if (S.route !== "analyzer") await go("analyzer");
        else await reloadAnalyzerHistory();
        startAnalyzerPolling(response.id);
      } finally {
        if (button) { button.disabled = false; if (button.dataset.oldLabel) button.innerHTML = button.dataset.oldLabel; }
      }
      return;
    }

    if (kind === "feed") {
      const payload = {
        title: v.title,
        url: v.url,
        icon: (S.draft && S.draft.icon) || v.icon || "📰",
        color: (S.draft && S.draft.color) || "teal",
        show_url: tgVal(form, "show_url"),
        show_source: tgVal(form, "show_source"),
        custom_source_label: v.custom_source_label || "",
        default_topic_id: Number(v.default_topic_id || 0),
        full_article: tgVal(form, "full_article"),
        enabled: tgVal(form, "enabled"),
      };
      if (S.draft && S.draft.feedId) await api("/api/feeds/" + S.draft.feedId, { method: "PATCH", body: payload });
      else await api("/api/feeds", { method: "POST", body: payload });
      closeModal(); toast(t("common.ok"), "ok"); await render();
      return;
    }
    if (kind === "feedtest") {
      const box = $("#feedTestResult");
      box.innerHTML = '<div class="tiny mute">' + h(t("common.loading")) + "</div>";
      const r = await api("/api/feeds/test", { method: "POST", body: { url: v.url } });
      if (!r.ok) {
        box.innerHTML = '<div class="banner bad">' + ico("alert") + "<span>" + h(r.error || "") + "</span></div>";
        return;
      }
      box.innerHTML =
        '<div class="banner ok">' + ico("check") + "<span>" +
        h(t("feeds.test_ok", { n: num(r.total), w: num(r.in_window) })) + "</span></div>" +
        '<div class="tiny mute" style="margin-bottom:6px">' + h(t("feeds.samples")) + "</div>" +
        (r.samples || []).map((s) => '<div class="list-line">' + ico("link") + "<span>" + h(s.title) + "</span></div>").join("");
      return;
    }
    if (kind === "bulk") {
      const r = await api("/api/feeds/bulk", { method: "POST", body: { text: v.text } });
      closeModal(); toast(t("common.ok") + " · " + num(r.created), "ok"); await render();
      return;
    }
    if (kind === "topic") {
      const payload = { name: v.name, name_en: v.name_en, emoji: (S.draft && S.draft.emoji) || v.emoji, keywords: v.keywords, enabled: tgVal(form, "enabled") };
      if (S.draft && S.draft.topicId) await api("/api/topics/" + S.draft.topicId, { method: "PATCH", body: payload });
      else await api("/api/topics", { method: "POST", body: payload });
      closeModal(); toast(t("common.ok"), "ok"); await render();
      return;
    }
    if (kind === "topictest") {
      const r = await api("/api/topics/test", { method: "POST", body: { title: v.title, summary: v.summary } });
      const box = $("#tOut") || $("#topicTestResult");
      if (!r.matches || !r.matches.length) {
        box.innerHTML = '<div class="banner">' + ico("info") + "<span>" + h(t("topics.no_match")) + "</span></div>";
        return;
      }
      box.innerHTML =
        '<div class="banner ok">' + ico("check") + "<span>" + h(t("topics.best")) + ": " +
        h((r.matches[0].emoji || "") + " " + (isFa() ? r.matches[0].name : r.matches[0].name_en)) + "</span></div>" +
        r.matches.map((m) => '<div class="kv"><span>' + h((m.emoji || "") + " " + (isFa() ? m.name : m.name_en)) + "</span><b>" + h(t("topics.score", { n: num(m.score) })) + "</b></div>").join("");
      return;
    }
    if (kind === "dest") {
      const payload = {
        name: v.name, platform: v.platform, chat_id: v.chat_id, bot_token: v.bot_token,
        topic_filter: v.topic_filter, footer: v.footer, parse_mode: v.parse_mode, enabled: tgVal(form, "enabled"),
      };
      if (form.id === "destForm" && S.draft && S.draft.destId) await api("/api/destinations/" + S.draft.destId, { method: "PATCH", body: payload });
      else if (S.draft && S.draft.destId) await api("/api/destinations/" + S.draft.destId, { method: "PATCH", body: payload });
      else await api("/api/destinations", { method: "POST", body: payload });
      closeModal(); toast(t("common.ok"), "ok"); await render();
      return;
    }
    if (kind === "job") {
      const times = (S.draft && S.draft.times) || [];
      const payload = {
        name: v.name,
        schedule_times: times,
        interval_minutes: Number(v.interval_minutes || 0),
        window_hours: Number(v.window_hours || 24),
        max_items: Number(v.max_items !== undefined && v.max_items !== "" ? v.max_items : 8),
        translate: tgVal(form, "translate"),
        include_summary: tgVal(form, "include_summary"),
        full_text: tgVal(form, "full_text"),
        send_image: tgVal(form, "send_image"),
        show_topic: tgVal(form, "show_topic"),
        only_unseen: tgVal(form, "only_unseen"),
        filter_mode: v.filter_mode || "smart",
        exclude_keywords: v.exclude_keywords || "",
        enabled: tgVal(form, "enabled"),
      };
      if (!payload.name) { toast(t("jobs.need_name"), "err"); return; }
      if (!times.length && !payload.interval_minutes) { toast(t("jobs.need_schedule"), "err"); return; }
      if (S.draft && S.draft.feed_ids.length) payload.feed_ids = S.draft.feed_ids;
      if (S.draft && S.draft.topic_ids.length) payload.topic_ids = S.draft.topic_ids;
      if (S.draft && S.draft.destination_ids.length) payload.destination_ids = S.draft.destination_ids;
      if (S.draft && S.draft.jobId) await api("/api/jobs/" + S.draft.jobId, { method: "PATCH", body: payload });
      else await api("/api/jobs", { method: "POST", body: payload });
      closeModal(); toast(t("common.ok"), "ok"); await render();
      return;
    }
    if (kind === "settings-general" || kind === "admin-appearance") {
      const body = {
        panel_title: v.panel_title,
        timezone: v.timezone,
      };
      if (v.theme) body.theme = v.theme;
      if (v.language) body.language = v.language;
      if (v.global_footer !== undefined) body.global_footer = v.global_footer;
      if (v.max_message_chars !== undefined) body.max_message_chars = v.max_message_chars;
      if (String(v.feedback_webhook || "").trim()) body.feedback_webhook = String(v.feedback_webhook).trim();
      if (form.querySelector('[data-tg="signature_enabled"]')) body.signature_enabled = tgVal(form, "signature_enabled");
      await api("/api/settings", { method: "PATCH", body: body });
      toast(t("settings.saved"), "ok");
      if (v.theme && v.theme !== S.theme) setTheme(v.theme);
      if (v.language && v.language !== S.lang) setLang(v.language);
      await render();
      return;
    }
    if (kind === "settings-translation") {
      const translationPatch = {
        translate_provider: v.translate_provider,
        translate_fallback: v.translate_fallback,
        deepseek_base_url: v.deepseek_base_url,
        deepseek_model: v.deepseek_model,
        translate_glossary: v.translate_glossary,
        translate_post_edit: tgVal(form, "translate_post_edit"),
        translate_preserve: tgVal(form, "translate_preserve"),
      };
      if (String(v.deepseek_api_key || "").trim()) translationPatch.deepseek_api_key = v.deepseek_api_key.trim();
      await api("/api/settings", { method: "PATCH", body: translationPatch });
      toast(t("settings.saved"), "ok");
      return;
    }
    if (kind === "settings-security") {
      try {
        await api("/api/password", { method: "POST", body: { current_password: v.current_password, new_password: v.new_password } });
        toast(t("settings.password_changed"), "ok");
        form.reset();
      } catch (e) { toast(errMsg(e), "err"); }
      return;
    }
    if (kind === "admin-import") {
      let payload;
      try { payload = JSON.parse(v.payload || "{}"); } catch (e) { toast(t("admin.nothing_to_import"), "err"); return; }
      const run = async () => {
        const r = await api("/api/admin/import", { method: "POST", body: { payload: payload, confirm: true } });
        toast(t("admin.import_done"), "ok"); closeModal(); await render();
      };
      confirmModal(t("admin.import_confirm"), run);
      return;
    }
    if (kind === "feedback") {
      const result = await api("/api/feedback", { method: "POST", body: { kind: "message", name: v.name || "", contact: v.contact || "", message: v.message || "" } });
      form.reset();
      const delivery = result.telegram || {};
      if (delivery.status === "sent") {
        toast(t("creators.feedbackSentAll"), "ok");
      } else if (delivery.status === "partial") {
        toast(t("creators.feedbackPartial", { sent: num(delivery.sent), total: num(delivery.total) }), "info");
      } else if (delivery.status === "not_configured") {
        toast(t("creators.feedbackNotConfigured"), "err");
      } else {
        toast(t("creators.feedbackFailed"), "err");
      }
      return;
    }
    if (kind === "creator-login") {
      const username = (form.elements.username && form.elements.username.value || "").trim();
      const password = form.elements.password ? form.elements.password.value : "";
      await api("/api/creators/auth/login", { method: "POST", body: { username: username, password: password } });
      if (form.elements.password) form.elements.password.value = "";
      closeModal();
      toast(t("creators.editorSignedIn"), "ok");
      await render();
      return;
    }
    if (kind === "creator-contact-token") {
      const result = await api("/api/creators/contact-bot", { method: "PUT", body: { bot_token: v.bot_token || "" } });
      S.creatorEditor.botConfigured = Boolean(result.configured);
      closeModal();
      toast(t("creators.contactBotSaved"), "ok");
      await render();
      return;
    }
    if (kind === "creator-edu") {
      const body = {};
      Object.keys(v).forEach((key) => { if (key.indexOf("edu_") === 0) body[key] = v[key]; });
      const result = await api("/api/creators", { method: "PATCH", body: body });
      S.edu = result.edu || S.edu;
      closeModal(); toast(t("common.ok"), "ok"); await render();
      return;
    }
    if (kind === "creator") {
      const slot = form.dataset.slot;
      const body = {};
      Object.keys(v).forEach((k) => { if (k.indexOf("creator" + slot + "_") === 0) body[k] = v[k]; });
      const r = await api("/api/creators", { method: "PATCH", body: body });
      S.creators = r.creators || S.creators;
      closeModal(); toast(t("common.ok"), "ok"); await render();
      return;
    }
  }

  /* ── actions ──────────────────────────────────────────────────────────── */

  const ACTIONS = {
    "nav.go": (el) => go(el.dataset.page),
    "lang.toggle": () => setLang(isFa() ? "en" : "fa"),
    "theme.toggle": () => {
      const themes = ["slate", "cyber", "emerald", "amber"];
      setTheme(themes[(themes.indexOf(S.theme) + 1) % themes.length]);
    },
    "logout": async () => {
      try { await api("/api/logout", { method: "POST" }); } catch (e) {}
      location.replace("/login");
    },
    "nav.item": (el) => go(el.dataset.page, el.dataset.tab, el.dataset.anchor),
    "mobile.toggle": (el) => {
      const g = el.closest(".mgroup");
      g.classList.toggle("open");
    },
    "reload": async () => { await render(); toast(t("common.refresh"), "info"); },
    "tg": (el) => {
      el.classList.toggle("on");
      el.setAttribute("aria-pressed", el.classList.contains("on") ? "true" : "false");
    },
    "modal.close": () => closeModal(),
    "modal.backdrop": (el, ev) => { if (ev && ev.target === el) closeModal(); },
    "modal.yes": async () => { closeModal(); },
    "submit": (el) => {
      const form = document.getElementById(el.dataset.formId);
      if (form) submitForm(form).catch((e) => toast(errMsg(e), "err"));
    },
    "runAll": async () => {
      const jobs = (await loadJobs()).filter((j) => Number(j.enabled));
      if (!jobs.length) { toast(t("jobs.empty"), "info"); return; }
      toast(t("common.loading"), "info");
      let last = null;
      for (const j of jobs) {
        try { last = await api("/api/jobs/" + j.id + "/run", { method: "POST", body: { dry_run: false } }); }
        catch (e) { last = { ok: false, error_code: e.message, events: [] }; }
      }
      await render();
      if (last) showReport(last);
    },
    "analyzer.ai.provider": async (el) => {
      const base = $("#analysisApiBase");
      const model = $("#analysisApiModel");
      if (el.value === "deepseek") {
        if (base) base.value = "https://api.deepseek.com";
        if (model && !model.value.startsWith("deepseek-")) model.value = "deepseek-flash";
      } else if (base && base.value.includes("api.deepseek.com")) {
        base.value = "https://api.openai.com/v1";
        if (model && model.value.startsWith("deepseek-")) model.value = "gpt-4o-mini";
      }
      if (( $("#analysisApiKey") || {}).value) await discoverAnalyzerModels();
    },
    "analyzer.ai.keychange": async (el) => {
      if (String(el.value || "").trim()) await discoverAnalyzerModels();
    },
    "analyzer.ai.basechange": async () => {
      const key = $("#analysisApiKey");
      if (key && String(key.value || "").trim()) await discoverAnalyzerModels();
    },
    "analyzer.ai.models": async () => { await discoverAnalyzerModels(); },
    "analyzer.ai.save": async () => {
      try {
        await saveAnalyzerAiSettings();
        toast(t("an.aiSettingsSaved"), "ok");
      } catch (error) { toast(errMsg(error), "err"); }
    },
    "analyzer.ai.test": async (el) => {
      const old = el.innerHTML;
      el.disabled = true;
      el.innerHTML = '<span class="spinner" style="width:14px;height:14px"></span><span>' + h(t("common.loading")) + '</span>';
      try {
        await saveAnalyzerAiSettings();
        const result = await api("/api/analyzer/llm/test", { method: "POST" });
        if (result.ok) toast(t("an.aiTestOk", { model: result.model || "" }), "ok");
        else toast(t("an.aiTestFail", { detail: analyzerApiErrorText(result.error || "unknown") }), "err");
      } catch (error) { toast(errMsg(error), "err"); }
      finally { if (el.isConnected) { el.disabled = false; el.innerHTML = old; } }
    },
    "analyzer.quick": async () => {
      const input = $("#dashAnalyzeInput");
      const value = input ? input.value.trim() : "";
      await go("analyzer");
      const target = $("#analysisUrl");
      if (target && value) {
        target.value = value;
        const form = $("#analyzerForm");
        if (form) await submitForm(form);
      } else if (target) target.focus();
    },
    "analyzer.open": async (el) => {
      const response = await api("/api/analyzer/" + el.dataset.id);
      S.currentAnalysis = response.analysis;
      if (S.route !== "analyzer") await go("analyzer");
      else {
        stopAnalyzerPolling();
        updateAnalyzerPanels();
        if (S.currentAnalysis.status === "processing") startAnalyzerPolling(S.currentAnalysis.id);
      }
    },
    "analyzer.save": async (el) => {
      const draft = $("#analysisDraft");
      const includeLink = $("#analysisIncludeLink");
      const sendImage = $("#analysisSendImage");
      const response = await api("/api/analyzer/" + el.dataset.id, { method: "PATCH", body: {
        channel_draft: draft ? draft.value : "",
        include_link: includeLink && includeLink.checked ? 1 : 0,
        send_image: sendImage && sendImage.checked ? 1 : 0,
      }});
      S.currentAnalysis = response.analysis;
      toast(t("common.saved"), "ok");
    },
    "analyzer.publish": async (el) => {
      const ids = $$("#analysisDests input[name='analysisDest']:checked").map((input) => Number(input.value));
      if (!ids.length) { toast(t("an.selectDests"), "err"); return; }
      const draft = $("#analysisDraft");
      const includeLink = $("#analysisIncludeLink");
      const sendImage = $("#analysisSendImage");
      const response = await api("/api/analyzer/" + el.dataset.id + "/publish", { method: "POST", body: {
        destination_ids: ids,
        channel_draft: draft ? draft.value : "",
        include_link: includeLink && includeLink.checked ? 1 : 0,
        send_image: sendImage && sendImage.checked ? 1 : 0,
      }});
      if (!response.ok) { toast(errMsg({ message: response.error_code || "unknown" }), "err"); return; }
      S.currentAnalysis = response.analysis;
      const sent = (response.results || []).filter((row) => row.ok).length;
      toast(t("an.publishedOk", { sent: num(sent) }), "ok");
      await reloadAnalyzerHistory();
    },
    "analyzer.delete": (el) => confirmModal(t("common.confirmDelete"), async () => {
      const wasCurrent = S.currentAnalysis && Number(S.currentAnalysis.id) === Number(el.dataset.id);
      await api("/api/analyzer/" + el.dataset.id, { method: "DELETE" });
      stopAnalyzerPolling();
      const rows = await api("/api/analyzer?limit=40");
      S.analyses = rows.analyses || [];
      if (wasCurrent) S.currentAnalysis = S.analyses[0] || null;
      updateAnalyzerPanels();
      if (S.currentAnalysis && S.currentAnalysis.status === "processing") startAnalyzerPolling(S.currentAnalysis.id);
    }),

    /* feeds */
    "feed.new": async () => { await loadTopics(); feedModal(null); },
    "feed.edit": async (el) => { await loadTopics(); feedModal(S.feeds.find((f) => Number(f.id) === Number(el.dataset.id))); },
    "feed.bulk": () => bulkModal(),
    "feed.test": () => feedTestModal(),
    "feed.emoji": (el) => {
      const input = $("#feedIcon");
      if (input) input.value = el.dataset.emoji;
      if (S.draft) S.draft.icon = el.dataset.emoji;
    },
    "feed.color": (el) => {
      if (S.draft) S.draft.color = el.dataset.color;
      $$("#colorRow .pick").forEach((b) => b.classList.toggle("on", b === el));
    },
    "feed.toggle": async (el) => {
      const id = el.dataset.id;
      const feed = S.feeds.find((f) => Number(f.id) === Number(id));
      el.classList.toggle("on");
      await api("/api/feeds/" + id, { method: "PATCH", body: { enabled: el.classList.contains("on") ? 1 : 0 } });
      if (feed) feed.enabled = el.classList.contains("on") ? 1 : 0;
    },
    "feed.check": async (el) => {
      const id = el.dataset.id;
      const original = el.innerHTML;
      el.disabled = true;
      el.innerHTML = '<span class="spinner" style="width:14px;height:14px"></span>';
      try {
        const r = await api("/api/feeds/" + id + "/check", { method: "POST" });
        if (r.feed) {
          const idx = S.feeds.findIndex((feed) => Number(feed.id) === Number(id));
          if (idx >= 0) S.feeds[idx] = r.feed;
          replaceFeedRow(r.feed);
        }
        if (r.ok) toast(t("feeds.test_ok", { n: num(r.total), w: num(r.in_window) }), "ok");
        else toast(r.error || t("feeds.broken"), "err");
      } catch (e) {
        el.disabled = false;
        el.innerHTML = original;
        toast(errMsg(e), "err");
      }
    },
    "feed.del": (el) => {
      const feed = S.feeds.find((f) => Number(f.id) === Number(el.dataset.id));
      confirmModal(t("feeds.delete_confirm", { name: feed ? feed.title : "" }), async () => {
        await api("/api/feeds/" + el.dataset.id, { method: "DELETE" });
        await render();
      });
    },
    "feed.up": (el) => moveFeed(el.dataset.id, -1),
    "feed.down": (el) => moveFeed(el.dataset.id, 1),

    /* topics */
    "topic.new": () => topicModal(null),
    "topic.edit": (el) => topicModal(S.topics.find((x) => Number(x.id) === Number(el.dataset.id))),
    "topic.test": () => topicTestModal(),
    "topic.runtest": () => { const form = $("#topicTestForm"); return form ? submitForm(form) : null; },
    "topic.emoji": (el) => {
      const input = $("#topicEmoji");
      if (input) input.value = el.dataset.emoji;
      if (S.draft) S.draft.emoji = el.dataset.emoji;
    },
    "topic.toggle": async (el) => {
      el.classList.toggle("on");
      await api("/api/topics/" + el.dataset.id, { method: "PATCH", body: { enabled: el.classList.contains("on") ? 1 : 0 } });
    },
    "topic.del": (el) => {
      const tp = S.topics.find((x) => Number(x.id) === Number(el.dataset.id));
      confirmModal(t("topics.delete_confirm", { name: tp ? tp.name : "" }), async () => {
        await api("/api/topics/" + el.dataset.id, { method: "DELETE" });
        await render();
      });
    },

    /* destinations */
    "dest.new": () => {
      S.draft = { destId: null };
      Promise.all([loadTopics()]).then(() => destModal(null));
    },
    "dest.edit": (el) => {
      const d = S.dests.find((x) => Number(x.id) === Number(el.dataset.id));
      S.draft = { destId: d ? d.id : null };
      destModal(d);
    },
    "dest.toggle": async (el) => {
      el.classList.toggle("on");
      await api("/api/destinations/" + el.dataset.id, { method: "PATCH", body: { enabled: el.classList.contains("on") ? 1 : 0 } });
    },
    "dest.verify": async (el) => {
      toast(t("common.loading"), "info");
      try {
        const r = await api("/api/destinations/" + el.dataset.id + "/verify", { method: "POST" });
        updateDestinationCard(r.destination);
        if (r.ok) {
          const info = r.info || {};
          const who = [info.bot ? "@" + info.bot : "", info.chat || ""].filter(Boolean).join(" → ");
          toast(who ? t("channels.verify_ok_who", { who }) : t("channels.verify_ok"), "ok");
        } else {
          toast(t("channels.verify_fail", { detail: r.detail || "" }), "err");
        }
      } catch (e) { toast(errMsg(e), "err"); }
    },
    "dest.test": async (el) => {
      toast(t("common.loading"), "info");
      try {
        const r = await api("/api/destinations/" + el.dataset.id + "/test", { method: "POST" });
        updateDestinationCard(r.destination);
        if (r.ok) toast(t("channels.test_ok"), "ok");
        else toast(t("channels.test_fail", { detail: r.detail || "" }), "err");
      } catch (e) { toast(errMsg(e), "err"); }
    },
    "dest.del": (el) => {
      const d = S.dests.find((x) => Number(x.id) === Number(el.dataset.id));
      confirmModal(t("channels.delete_confirm", { name: d ? d.name : "" }), async () => {
        await api("/api/destinations/" + el.dataset.id, { method: "DELETE" });
        await render();
      });
    },

    /* jobs */
    "job.new": async () => {
      await Promise.all([loadFeeds(), loadTopics(), loadDests()]);
      jobModal(null);
    },
    "job.edit": async (el) => {
      await Promise.all([loadFeeds(), loadTopics(), loadDests()]);
      jobModal(S.jobs.find((x) => Number(x.id) === Number(el.dataset.id)));
    },
    "job.toggle": async (el) => {
      el.classList.toggle("on");
      await api("/api/jobs/" + el.dataset.id, { method: "PATCH", body: { enabled: el.classList.contains("on") ? 1 : 0 } });
    },
    "job.run": async (el) => {
      toast(t("common.loading"), "info");
      try {
        const r = await api("/api/jobs/" + el.dataset.id + "/run", { method: "POST", body: { dry_run: false } });
        await render();
        showReport(r);
      } catch (e) { toast(errMsg(e), "err"); }
    },
    "job.dry": async (el) => {
      toast(t("common.loading"), "info");
      try {
        const r = await api("/api/jobs/" + el.dataset.id + "/run", { method: "POST", body: { dry_run: true } });
        showReport(r);
      } catch (e) { toast(errMsg(e), "err"); }
    },
    "job.dryAll": async () => {
      await loadJobs();
      if (!S.jobs.length) { toast(t("jobs.empty"), "info"); return; }
      const j = S.jobs.find((x) => Number(x.enabled)) || S.jobs[0];
      ACTIONS["job.dry"]({ dataset: { id: j.id } });
    },
    "job.del": (el) => {
      const j = S.jobs.find((x) => Number(x.id) === Number(el.dataset.id));
      confirmModal(t("jobs.delete_confirm", { name: j ? j.name : "" }), async () => {
        await api("/api/jobs/" + el.dataset.id, { method: "DELETE" });
        await render();
      });
    },
    "draft.pick": (el) => {
      const kind = el.dataset.kind, id = Number(el.dataset.id);
      if (!S.draft || !S.draft[kind]) return;
      const arr = S.draft[kind];
      const i = arr.indexOf(id);
      if (i >= 0) arr.splice(i, 1); else arr.push(id);
      el.classList.toggle("on", i < 0);
      const tick = el.querySelector(".tick");
      if (tick) tick.innerHTML = i < 0 ? ico("check") : "";
    },
    "draft.addtime": () => {
      const inp = $("#newTime");
      if (!inp || !inp.value) return;
      if (S.draft.times.indexOf(inp.value) < 0) S.draft.times.push(inp.value);
      S.draft.times.sort();
      inp.value = "";
      $("#timeWrap").innerHTML = draftTimes();
    },
    "draft.rmtime": (el) => {
      const time = el.dataset.time;
      S.draft.times = S.draft.times.filter((x) => x !== time);
      $("#timeWrap").innerHTML = draftTimes();
    },

    /* items */
    "item.preview": async (el) => {
      try {
        const r = await api("/api/items/" + el.dataset.id + "/preview", { method: "POST", body: {} });
        openModal({
          title: t("common.preview"),
          wide: true,
          body: (r.image ? '<img src="' + h(r.image) + '" alt="" style="width:100%;max-height:220px;object-fit:cover;border-radius:12px;margin-bottom:12px">' : "") +
            '<div class="previewbox" dir="auto">' + prettyHtml(r.message || "") + "</div>",
          footer: '<button class="btn primary" data-act="modal.close">' + t("common.close") + "</button>",
        });
      } catch (e) { toast(errMsg(e), "err"); }
    },
    "item.resend": async (el) => {
      try {
        const r = await api("/api/items/" + el.dataset.id + "/resend", { method: "POST", body: {} });
        const resendMessage = r.ok ? t("archive.resend_ok") :
          r.error_code === "image_required_unavailable" ? t("items.resendImageRequired") : t("archive.resend_fail");
        toast(resendMessage, r.ok ? "ok" : "err");
        await refreshArchiveItem(el.dataset.id);
      } catch (e) { toast(errMsg(e), "err"); }
    },
    "item.publish": async (el) => {
      const dests = await loadDests();
      const active = dests.filter((d) => Number(d.enabled));
      if (!active.length) { toast(t("dest.empty"), "err"); return; }
      openModal({
        title: t("items.resend"),
        body: '<div class="field"><label>' + h(t("an.selectDests")) + '</label><div class="chips">' + active.map((d) =>
          '<label class="chip-check"><input type="checkbox" name="manualDest" value="' + d.id + '" checked><span>' + h(d.name) + '</span></label>').join('') + '</div></div>',
        footer: '<button class="btn" data-act="modal.close">' + h(t("common.cancel")) + '</button><button class="btn btn-primary" data-act="item.publish.confirm" data-id="' + el.dataset.id + '">' +
          ico("send") + '<span>' + h(t("items.resend")) + '</span></button>',
      });
    },
    "item.publish.confirm": async (el) => {
      const ids = $$("input[name='manualDest']:checked").map((input) => Number(input.value));
      if (!ids.length) { toast(t("an.selectDests"), "err"); return; }
      const result = await api("/api/items/" + el.dataset.id + "/resend", { method: "POST", body: { destination_ids: ids } });
      closeModal();
      const resendMessage = result.ok ? t("archive.resend_ok") :
        result.error_code === "image_required_unavailable" ? t("items.resendImageRequired") : t("archive.resend_fail");
      toast(resendMessage, result.ok ? "ok" : "err");
      await refreshArchiveItem(el.dataset.id);
    },
    "item.del": (el) => {
      confirmModal(t("archive.delete_confirm"), async () => {
        await api("/api/items/" + el.dataset.id, { method: "DELETE" });
        await refreshArchiveItem(el.dataset.id);
      });
    },
    "archive.filter": (el) => {
      S.archive.status = el.dataset.status;
      render();
    },
    "archive.search": () => {
      const inp = $("#archSearch");
      S.archive.q = inp ? inp.value : "";
      render();
    },
    "archive.clear": () => {
      confirmModal(t("archive.clear_confirm"), async () => {
        await api("/api/admin/archive/clear", { method: "POST" });
        toast(t("admin.archived_cleared"), "ok");
        await render();
      });
    },

    /* admin */
    "admin.tab": (el) => { S.adminTab = el.dataset.tab; render(); },
    "admin.icon": async (el) => {
      const v = el.value.trim() || "📰";
      await api("/api/feeds/" + el.dataset.id, { method: "PATCH", body: { icon: v } });
      toast(t("common.ok"), "ok");
    },
    "admin.color": async (el) => {
      await api("/api/feeds/" + el.dataset.id, { method: "PATCH", body: { color: el.value } });
      await render();
    },
    "admin.showurl": async (el) => {
      el.classList.toggle("on");
      await api("/api/feeds/" + el.dataset.id, { method: "PATCH", body: { show_url: el.classList.contains("on") ? 1 : 0 } });
    },
    "admin.export": async () => {
      try {
        const data = await api("/api/admin/export?include_items=0");
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "rozaneh-backup-" + new Date().toISOString().slice(0, 10) + ".json";
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 2000);
        toast(t("admin.export_ready"), "ok");
      } catch (e) { toast(errMsg(e), "err"); }
    },
    "admin.clearArchive": () => {
      confirmModal(t("admin.clear_archive_hint"), async () => {
        const r = await api("/api/admin/archive/clear", { method: "POST" });
        toast(t("admin.archived_cleared") + " · " + num(r.deleted || 0), "ok");
        await render();
      });
    },
    "admin.clearSessions": () => {
      confirmModal(t("admin.sessions_hint"), async () => {
        await api("/api/admin/sessions", { method: "DELETE" });
        toast(t("admin.sessions_cleared"), "ok");
        await render();
      });
    },

    /* settings */
    "theme.set": (el) => { setTheme(el.dataset.theme); render(); },
    "lang.set": (el) => { setLang(el.dataset.lang); },
    "translate.test": async () => {
      openModal({
        title: t("settings.test_translation"),
        body: '<div id="trResult" class="tiny mute">' + h(t("common.loading")) + "</div>",
        footer: '<button class="btn primary" data-act="modal.close">' + t("common.close") + "</button>",
      });
      try {
        const r = await api("/api/translate/test", { method: "POST", body: { title: "Hello world, this is a translation test." } });
        $("#trResult").innerHTML =
          '<div class="kv"><span>provider</span><b>' + h(r.provider || "?") + "</b></div>" +
          '<div class="previewbox" dir="auto" style="margin-top:8px">' + h(r.text || r.result || JSON.stringify(r)) + "</div>";
      } catch (e) {
        $("#trResult").textContent = errMsg(e);
      }
    },

    /* creators / feedback */
    "creator.login": () => creatorLoginModal(),
    "creator.edit": (el) => creatorModal(Number(el.dataset.slot)),
    "creator.editEducation": () => creatorEducationModal(),
    "creator.contactBot": () => creatorContactBotModal(),
    "creator.logout": async () => {
      await api("/api/creators/auth/logout", { method: "POST" });
      S.creatorEditor = { configured: true, authenticated: false, botConfigured: false };
      toast(t("creators.editorLogout"), "ok");
      await render();
    },
    "creators.copy": async (el) => {
      const value = el.dataset.copy || "";
      try {
        if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(value);
        else {
          const temp = document.createElement("textarea");
          temp.value = value; temp.style.position = "fixed"; temp.style.opacity = "0";
          document.body.appendChild(temp); temp.select(); document.execCommand("copy"); temp.remove();
        }
        toast(t("common.copy"), "ok");
      } catch (e) { toast(value, "info"); }
    },
    "creators.bug": () => {
      const logs = $$(".logline .lm").slice(0, 6).map((el) => "· " + el.textContent).join("\n");
      feedbackModal(logs ? t("logs.title") + ":\n" + logs + "\n\n" : "");
    },
  };

  async function moveFeed(id, dir) {
    const ids = S.feeds.map((f) => Number(f.id));
    const i = ids.indexOf(Number(id));
    const j = i + dir;
    if (i < 0 || j < 0 || j >= ids.length) return;
    ids.splice(j, 0, ids.splice(i, 1)[0]);
    await api("/api/feeds/reorder", { method: "POST", body: { ids: ids } });
    await render();
  }

  /* ── event wiring ─────────────────────────────────────────────────────── */

  document.addEventListener("click", (ev) => {
    const target = ev.target instanceof Element ? ev.target : null;
    const el = target && target.closest("[data-act]");
    if (!el) return;
    const name = el.dataset.act;
    const fn = ACTIONS[name];
    if (!fn) return;
    if (el.tagName === "BUTTON" && !el.hasAttribute("type")) el.setAttribute("type", "button");
    ev.preventDefault();
    try {
      const result = fn(el, ev);
      if (result && typeof result.catch === "function") result.catch((e) => toast(errMsg(e), "err"));
    } catch (e) { toast(errMsg(e), "err"); }
  });

  document.addEventListener("input", (ev) => {
    if (ev.target && ev.target.id === "analysisDraft") {
      const preview = $("#analysisPreview");
      if (preview) preview.innerHTML = h(ev.target.value).replace(/\n/g, "<br>");
    }
  });

  document.addEventListener("change", (ev) => {
    const target = ev.target instanceof Element ? ev.target : null;
    const el = target && target.closest("[data-act]");
    if (!el || !/^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) return;
    const fn = ACTIONS[el.dataset.act];
    if (fn) {
      try {
        const result = fn(el, ev);
        if (result && typeof result.catch === "function") result.catch((e) => toast(errMsg(e), "err"));
      } catch (e) { toast(errMsg(e), "err"); }
    }
  });

  document.addEventListener("submit", (ev) => {
    const form = ev.target.closest("form[data-form]");
    if (!form) return;
    ev.preventDefault();
    submitForm(form).catch((e) => toast(errMsg(e), "err"));
  });

  // hover-intent dropdowns on desktop
  document.addEventListener("mouseover", (ev) => {
    const item = ev.target.closest(".mitem");
    if (!item || window.innerWidth <= 1180) return;
    $$(".mitem.open").forEach((el) => { if (el !== item) el.classList.remove("open"); });
  });

  /* ── boot ─────────────────────────────────────────────────────────────── */

  async function boot() {
    let meta;
    try {
      meta = await api("/api/meta");
    } catch (e) {
      if (e.message === "auth_required") return;
      document.body.innerHTML = '<div style="padding:40px;font-family:sans-serif">Rozaneh · ' + h(errMsg(e)) + "</div>";
      return;
    }
    S.meta = meta;
    if (!meta.authenticated) { location.replace("/login"); return; }

    const storedLang = localStorage.getItem(LS_LANG) || localStorage.getItem("rozaneh.lang");
    const storedTheme = localStorage.getItem(LS_THEME) || localStorage.getItem("rozaneh.theme");
    S.lang = (storedLang === "en" || storedLang === "fa") ? storedLang : ((meta.defaults && meta.defaults.language) || "fa");
    S.theme = ["slate", "cyber", "emerald", "amber"].includes(storedTheme)
      ? storedTheme : ((meta.defaults && meta.defaults.theme) || "slate");

    const version = "v" + (meta.version || "1.08");
    const badge = $("#verBadge");
    const footer = $("#verFoot");
    if (badge) badge.textContent = version;
    if (footer) footer.textContent = version;

    applyTheme();
    applyLang();
    wireChrome();

    const route = (location.hash || "").replace(/^#\/?/, "") || "dashboard";
    S.route = PAGES[route] ? route : "dashboard";
    renderNav();
    await render();

    // bootstrap-password notice (once per session)
    if (meta.bootstrap_password && !sessionStorage.getItem("rozaneh.pw")) {
      sessionStorage.setItem("rozaneh.pw", "1");
      setTimeout(() => toast(t("settings.bootstrap_warning"), "info"), 900);
    }
  }

  window.Rozaneh = { go: go, render: render, state: S, toast: toast };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
