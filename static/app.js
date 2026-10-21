"use strict";
const ADMIN = location.pathname.startsWith("/admin");
const API = ADMIN ? "/admin/api" : "/api";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const view = $("#view");
const S = { config: null, facets: null, area: "", max: "", q: "", cuisine: "", sort: "", near: null, kind: "" };

// filters a viewer picked last time (per browser only)
const PREFS = "where-to-eat:prefs";
try { Object.assign(S, JSON.parse(localStorage.getItem(PREFS) || "{}")); } catch { /* storage off */ }
function savePrefs() { try { localStorage.setItem(PREFS, JSON.stringify({ area: S.area, max: S.max })); } catch { /* storage off */ } }

async function api(path, opts = {}) {
  const o = { headers: {}, ...opts };
  if (o.body && !(o.body instanceof FormData)) { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(o.body); }
  const r = await fetch((path.startsWith("/") ? "" : API + "/") + path, o);
  let data = null;
  try { data = await r.json(); } catch { /* not JSON */ }
  if (!r.ok) {
    if (r.status === 401 && ADMIN) toast((data && data.reason) || "Your sign-in expired. Reload the page to sign in again.");
    const e = new Error((data && data.error) || `Request failed (${r.status})`); e.status = r.status; e.data = data; throw e;
  }
  return data;
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 3600);
}
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const money = (n) => n == null ? "" : "$" + (Number.isInteger(n) ? n : n.toFixed(2));
const dollars = (n) => n ? "$".repeat(n) : "";
const cap = () => S.config ? S.config.cheap_under : 15;
const isDeal = (p) => p != null && p <= cap();
const priceHTML = (p) => p == null ? `<span class="price muted">–</span>` : `<span class="price ${isDeal(p) ? "deal" : ""}">${money(p)}</span>`;
const KIND = { meal: "Meal deal", special: "Special" };
const kindBadge = (k) => KIND[k] ? `<span class="badge ${k}">${KIND[k]}</span>` : "";
const img = (file, thumb = true) => file ? `<img loading="lazy" src="/photos/${thumb ? "t-" : ""}${esc(file)}" alt="">` : "";
const km = (k) => k == null ? "" : k < 1 ? `${Math.round(k * 1000)} m` : `${k.toFixed(k < 10 ? 1 : 0)} km`;
function ago(iso) {
  if (!iso) return "";
  const days = Math.round((Date.now() - new Date(iso + "T12:00:00")) / 864e5);
  if (days < 1) return "today";
  if (days < 45) return `${days} day${days === 1 ? "" : "s"} ago`;
  const m = Math.round(days / 30.4);
  return m < 18 ? `${m} month${m === 1 ? "" : "s"} ago` : `${Math.round(days / 365)} years ago`;
}
const daysSince = (iso) => (Date.now() - new Date(iso + "T12:00:00")) / 864e5;
const isStale = (iso) => iso && daysSince(iso) > 180;  // prices older than ~6 months get a clock mark: worth rechecking
const stars = (r) => r == null ? "" : `<span class="stars" title="${r} of 5">${"★".repeat(Math.floor(r))}${r % 1 ? "½" : ""}</span>`;

// line icons (24px grid), same style as Roasted
const ICONS = {
  bowl: '<path d="M3 11h18a9 9 0 0 1-18 0z"/><path d="M8 7c0-1.5 1-2 1-3.5M12 7c0-1.5 1-2 1-3.5M16 7c0-1.5 1-2 1-3.5"/>',
  camera: '<path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/><circle cx="12" cy="13" r="3.5"/>',
  images: '<rect x="3" y="5" width="14" height="12" rx="1.5"/><path d="M7 21h12a2 2 0 0 0 2-2V9"/><path d="M3 14l4-4 4 4 2-2 4 4"/>',
  pin: '<path d="M12 21s-6.5-6.2-6.5-11a6.5 6.5 0 0 1 13 0c0 4.8-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/>',
  locate: '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2.5"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  x: '<path d="M7 7l10 10M17 7L7 17"/>',
  star: '<path d="M12 4l2.4 5 5.4.6-4 3.7 1.1 5.3L12 16l-4.9 2.6 1.1-5.3-4-3.7 5.4-.6z"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  sparkle: '<path d="M11 3l1.8 5.2L18 10l-5.2 1.8L11 17l-1.8-5.2L4 10l5.2-1.8z"/><path d="M19 14l.8 2.2L22 17l-2.2.8L19 20l-.8-2.2L16 17l2.2-.8z"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  phone: '<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a1 1 0 0 1-1 1A16 16 0 0 1 4 5a1 1 0 0 1 1-1z"/>',
  route: '<circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="6" r="2.5"/><path d="M8.5 18H15a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h6.5"/>',
  note: '<path d="M5 4h14v16H5z"/><path d="M9 9h6M9 13h6M9 17h3"/>',
  lock: '<rect x="5" y="11" width="14" height="9" rx="1.5"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 5v6h-6"/>',
};
const icon = (n, cls = "") => `<svg class="ico ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n]}</svg>`;

async function config() { if (!S.config) S.config = await api("/api/config"); return S.config; }
async function facets(force) { if (!S.facets || force) S.facets = await api("facets"); return S.facets; }

/* ---------- nav / router ---------- */
function renderNav(path) {
  const items = [["#/", "Places"], ["#/deals", "Deals"], ["#/map", "Map"]]
    .concat(ADMIN ? [["#/more", "More"]] : [["/admin#/", S.editor ? "Edit" : "Sign in"]]);
  const sect = path.split("/")[0];
  const on = (h) => h === "#/" ? (sect === "" || sect === "place") : h.startsWith("#/") && sect === h.slice(2);
  $("#nav").innerHTML = items.map(([h, t]) => `<a href="${h}" class="${on(h) ? "on" : ""}">${t}</a>`).join("");
  $("#fab").classList.toggle("hidden", !ADMIN || sect === "add" || /edit/.test(path));
}
async function route() {
  const hash = location.hash.replace(/^#\/?/, "");
  const [path] = hash.split("?");
  renderNav(path);
  window.scrollTo(0, 0);
  let m;
  try {
    await config();
    if ((m = path.match(/^place\/(\d+)\/edit$/)) && ADMIN) return await editView(+m[1]);
    if ((m = path.match(/^place\/(\d+)$/))) return await placeView(+m[1]);
    if (path === "add" && ADMIN) return await editView(null);
    if (path === "deals") return await dealsView();
    if (path === "map") return await mapView();
    if (path === "more" && ADMIN) return await moreView();
    return await placesView();
  } catch (e) {
    view.innerHTML = `<div class="empty">${esc(e.message)}${e.status === 401 && !ADMIN ? `<br><br><a class="btn primary" href="/admin#/">Sign in</a>` : ""}</div>`;
  }
}
window.addEventListener("hashchange", route);

/* ---------- shared filters ---------- */
function filterQS(extra = {}) {
  const p = new URLSearchParams();
  if (S.area) p.set("area", S.area);
  if (S.max) p.set("max_price", S.max);
  if (S.q) p.set("q", S.q);
  if (S.cuisine) p.set("cuisine", S.cuisine);
  if (S.near) { p.set("lat", S.near.lat); p.set("lng", S.near.lng); }
  for (const [k, v] of Object.entries(extra)) if (v) p.set(k, v);
  return p.toString();
}
function filtersHTML(f, { sort = false, kinds = false } = {}) {
  const c = cap();
  const caps = [...new Set([10, c, 20].map(Number))].sort((a, b) => a - b);
  const areaChips = [["", "Everywhere"], ...f.areas.filter((a) => a.n || a.lat != null).map((a) => [a.name, a.name])];
  return `<div class="filters">
    <div class="chips" id="f-area">${areaChips.map(([v, t]) => `<button type="button" class="chip ${S.area === v ? "on" : ""}" data-v="${esc(v)}">${esc(t)}</button>`).join("")}
      <button type="button" class="chip ${S.near ? "on" : ""}" id="f-near">${icon("locate")} Near me</button></div>
    <div class="chips" id="f-max">${[["", "Any price"], ...caps.map((n) => [String(n), `Under $${n}`])]
      .map(([v, t]) => `<button type="button" class="chip ${String(S.max) === v ? "on" : ""}" data-v="${v}">${t}</button>`).join("")}
    </div>
    ${kinds ? `<div class="chips">` + [["", "All dishes"], ["meal", "Meal deals"], ["special", "Specials"]].map(([v, t]) => `<button type="button" class="chip kind ${S.kind === v ? "on" : ""}" data-k="${v}">${t}</button>`).join("") + `</div>` : ""}
    <div class="searchrow">
      <input type="search" id="f-q" placeholder="Search places and dishes (pho, burrito, Mission…)" value="${esc(S.q)}" aria-label="Search">
      <div class="selects">
        <select id="f-cuisine" aria-label="Cuisine"><option value="">All cuisines</option>${f.cuisines.map((x) => `<option ${fold(x.name) === fold(S.cuisine) ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select>
        ${sort ? `<select id="f-sort" aria-label="Sort">${sortOptions().map(([v, t]) => `<option value="${v}" ${S.sort === v ? "selected" : ""}>${t}</option>`).join("")}</select>` : ""}
      </div>
    </div></div>`;
}
// "" = the server's default: nearest when "Near me" is on, otherwise cheapest
const sortOptions = () => [["", S.near ? "Nearest" : "Cheapest"], [S.near ? "cheapest" : "near", S.near ? "Cheapest" : "Nearest"],
  ["rating", "Top rated"], ["new", "Newest"], ["name", "A–Z"]].filter(([v]) => v !== "near" || S.near);
const fold = (s) => (s || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
function wireFilters(rerender) {
  $$("#f-area .chip[data-v]").forEach((b) => b.onclick = () => { S.area = b.dataset.v; savePrefs(); rerender(); });
  $$("#f-max .chip[data-v]").forEach((b) => b.onclick = () => { S.max = b.dataset.v; savePrefs(); rerender(); });
  $$(".chip[data-k]").forEach((b) => b.onclick = () => { S.kind = b.dataset.k; rerender(); });
  $("#f-near").onclick = () => {
    if (S.near) { S.near = null; if (S.sort === "near") S.sort = ""; return rerender(); }
    locateMe((pos) => { S.near = pos; S.area = ""; rerender(); });
  };
  $("#f-q").oninput = debounce((e) => { S.q = e.target.value.trim(); rerender(true); }, 250);
  $("#f-cuisine").onchange = (e) => { S.cuisine = e.target.value; rerender(); };
  $("#f-sort") && ($("#f-sort").onchange = (e) => { S.sort = e.target.value; rerender(); });
}
function locateMe(done) {
  if (!navigator.geolocation) return toast("This browser can't share your location");
  toast("Finding you…");
  navigator.geolocation.getCurrentPosition(
    (p) => done({ lat: +p.coords.latitude.toFixed(5), lng: +p.coords.longitude.toFixed(5) }),
    (e) => toast(e.code === 1 ? "Location is blocked. Allow it for this site (it needs HTTPS)." : "Couldn't get your location"),
    { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 });
}

/* ---------- places ---------- */
function placeCard(p) {
  const meta = [p.cuisine, p.neighborhood || p.area, dollars(p.price_level)].filter(Boolean).map(esc).join(" · ");
  const items = (p.top_items || []).map((i) => `<div><span>${i.favorite ? icon("star", "fav") + " " : ""}${esc(i.name)}</span>${priceHTML(i.price)}</div>`).join("");
  return `<a class="card place ${p.deals ? "has-deal" : ""}" href="#/place/${p.id}">
    ${p.photo ? `<img class="thumb" loading="lazy" src="/photos/t-${esc(p.photo)}" alt="">` : `<span class="thumb ph-art">${icon("bowl", "lg")}</span>`}
    <div class="b">
      <div class="t">${esc(p.name)} ${p.closed ? `<span class="badge closed">Closed</span>` : ""}</div>
      <div class="m">${meta}${p.km != null ? ` · ${km(p.km)}` : ""} ${stars(p.rating)}</div>
      <div class="row" style="margin-top:2px">${p.cheapest != null ? `<span class="badge">from ${money(p.cheapest)}</span>` : `<span class="badge">no prices yet</span>`}
        ${p.deals ? `<span class="badge deal">${p.deals} under ${money(S.max ? +S.max : cap())}</span>` : ""}</div>
      ${items ? `<div class="items">${items}</div>` : ""}
    </div></a>`;
}
async function placesView() {
  const f = await facets();
  view.innerHTML = `${filtersHTML(f, { sort: true })}<div class="count" id="count"></div><div class="list" id="results"></div>`;
  const load = async (soft) => {
    if (!soft) { view.innerHTML = `${filtersHTML(f, { sort: true })}<div class="count" id="count"></div><div class="list" id="results"></div>`; wireFilters(load); }
    const d = await api("places?" + filterQS({ sort: S.sort }));
    $("#count").textContent = `${d.places.length} place${d.places.length === 1 ? "" : "s"}${S.near ? " · nearest first" : ""}`;
    $("#results").innerHTML = d.places.map(placeCard).join("") ||
      `<div class="empty">${f.areas.some((a) => a.n) ? "Nothing matches. Try another area or price." : ADMIN ? "No places yet. Tap + to add the first one." : "No places yet."}</div>`;
  };
  wireFilters(load);
  await load(true);
}

/* ---------- deals ---------- */
async function dealsView() {
  const f = await facets();
  const load = async (soft) => {
    if (!soft) { view.innerHTML = `${filtersHTML(f, { kinds: true })}<div class="count" id="count"></div><div class="deals" id="results"></div>`; wireFilters(load); }
    const d = await api("deals?" + filterQS({ kind: S.kind }));
    let items = d.items;
    if (S.near) {
      for (const i of items) i.km = i.lat != null ? haversine(S.near, i) : null;
      items = items.filter((i) => i.km == null || i.km < 5);
    }
    $("#count").textContent = `${items.length} dish${items.length === 1 ? "" : "es"}${S.max ? ` under $${S.max}` : ""}, cheapest first${S.near ? " · within 5 km" : ""}`;
    $("#results").innerHTML = items.map((i) => `<a class="card deal-row" href="#/place/${i.place_id}">
        ${i.photo ? img(i.photo) : `<span class="ph ph-art">${icon("bowl")}</span>`}
        <div><div class="t">${i.favorite ? icon("star", "fav") + " " : ""}${esc(i.name)} ${kindBadge(i.kind)}</div>
          <div class="m">${esc(i.place_name)}${i.neighborhood || i.area ? " · " + esc(i.neighborhood || i.area) : ""}${i.km != null ? " · " + km(i.km) : ""}</div>
          ${i.description || i.available ? `<div class="m">${[i.description, i.available].filter(Boolean).map(esc).join(" · ")}</div>` : ""}
          ${i.price_checked ? `<div class="m small ${isStale(i.price_checked) ? "stale" : ""}">price checked ${ago(i.price_checked)}</div>` : ""}
        </div>${priceHTML(i.price)}</a>`).join("") || `<div class="empty">No dishes match yet.</div>`;
  };
  view.innerHTML = `${filtersHTML(f, { kinds: true })}<div class="count" id="count"></div><div class="deals" id="results"></div>`;
  wireFilters(load);
  await load(true);
}
function haversine(a, b) {
  const r = (x) => x * Math.PI / 180, dLat = r(b.lat - a.lat), dLng = r(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(r(a.lat)) * Math.cos(r(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(h));
}

/* ---------- map ---------- */
function loadLeaflet() {
  if (window.L) return Promise.resolve();
  return new Promise((res, rej) => {
    const css = document.createElement("link"); css.rel = "stylesheet"; css.href = "/static/leaflet/leaflet.css"; document.head.appendChild(css);
    const s = document.createElement("script"); s.src = "/static/leaflet/leaflet.js"; s.onload = res; s.onerror = () => rej(new Error("Couldn't load the map library")); document.head.appendChild(s);
  });
}
const tiles = (map) => L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap contributors" }).addTo(map);
// The street map is light in both themes, so markers use fixed colours: red = something under the cap,
// black = the cheapest dish costs more, hollow = no prices yet. Red also differs from black in lightness.
const tok = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function markerStyle(p) {
  if (p.cheapest == null) return { radius: 8, color: "#000000", weight: 3, fillColor: "#ffffff", fillOpacity: 1 };
  return { radius: 9, color: "#ffffff", weight: 2, fillColor: isDeal(p.cheapest) ? "#f50537" : "#000000", fillOpacity: 1 };
}
async function mapView() {
  const f = await facets();
  const areas = f.areas.filter((a) => a.lat != null);
  view.innerHTML = `<div class="spread" style="margin-top:16px">
      <div class="chips" id="m-area">${areas.map((a) => `<button type="button" class="chip" data-a="${esc(a.name)}">${esc(a.name)}</button>`).join("")}
        <button type="button" class="chip" id="m-all">Show all</button><button type="button" class="chip" id="m-near">${icon("locate")} Near me</button></div>
      <div class="chips" id="m-max">${[["", "Any price"], [String(cap()), `Under $${cap()}`]].map(([v, t]) => `<button type="button" class="chip ${String(S.max) === v ? "on" : ""}" data-v="${v}">${t}</button>`).join("")}</div>
    </div>
    <div class="legend"><span><i class="dot deal"></i>Something under $${cap()}</span><span><i class="dot over"></i>Cheapest is more</span><span><i class="dot none"></i>No prices yet</span><span id="mcount"></span></div>
    <div id="map"></div>`;
  const [d] = await Promise.all([api("map"), loadLeaflet()]);
  const map = L.map("map", { scrollWheelZoom: true });
  tiles(map);
  const layer = L.layerGroup().addTo(map);
  let me = null;
  const draw = (fit) => {
    layer.clearLayers();
    const pts = d.points.filter((p) => !S.max || (p.cheapest != null && p.cheapest <= +S.max));
    for (const p of pts) {
      L.circleMarker([p.lat, p.lng], markerStyle(p)).addTo(layer).bindPopup(
        `${p.photo ? `<img src="/photos/t-${esc(p.photo)}" alt="">` : ""}<strong><a href="#/place/${p.id}">${esc(p.name)}</a></strong>
         ${p.closed ? " (closed)" : ""}<br><span style="opacity:.8">${[p.cuisine, p.neighborhood || p.area].filter(Boolean).map(esc).join(" · ")}</span><br>
         ${p.cheapest != null ? `from <b>${money(p.cheapest)}</b>${p.deals ? ` · ${p.deals} under $${cap()}` : ""}` : "No prices yet"}`);
    }
    $("#mcount").textContent = `${pts.length} on the map${d.unplaced ? ` · ${d.unplaced} without a location` : ""}`;
    if (fit) {
      const inArea = S.area ? areas.find((a) => a.name === S.area) : null;
      if (inArea) map.setView([inArea.lat, inArea.lng], 14);
      else if (pts.length) map.fitBounds(pts.map((p) => [p.lat, p.lng]), { padding: [30, 30], maxZoom: 15 });
      else if (areas.length) map.fitBounds(areas.map((a) => [a.lat, a.lng]), { padding: [40, 40] });
      else map.setView([37.85, -122.25], 10);
    }
  };
  draw(true);
  $$("#m-area [data-a]").forEach((b) => b.onclick = () => { const a = areas.find((x) => x.name === b.dataset.a); S.area = a.name; savePrefs(); map.setView([a.lat, a.lng], 14); });
  $("#m-all").onclick = () => { S.area = ""; savePrefs(); draw(true); };
  $("#m-near").onclick = () => locateMe((pos) => {
    S.near = pos;
    if (me) me.remove();
    me = L.layerGroup([L.circleMarker([pos.lat, pos.lng], { radius: 15, color: "#000000", weight: 2, fill: false }),
      L.circleMarker([pos.lat, pos.lng], { radius: 6, color: "#ffffff", weight: 3, fillColor: "#000000", fillOpacity: 1 })]).addTo(map).bindPopup("You are here");
    map.setView([pos.lat, pos.lng], 16);
  });
  $$("#m-max [data-v]").forEach((b) => b.onclick = () => {
    S.max = b.dataset.v; savePrefs();
    $$("#m-max [data-v]").forEach((x) => x.classList.toggle("on", x === b)); draw(false);
  });
}

/* ---------- place page ---------- */
function directions(p) {
  const dest = p.lat != null ? `${p.lat},${p.lng}` : [p.name, p.address].filter(Boolean).join(", ");
  return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(dest)}`;
}
function itemRow(i, p) {
  const thumbs = (i.photos || []).map((ph) => `<a href="/photos/${esc(ph.file)}" target="_blank" rel="noopener">${img(ph.file)}</a>`).join("");
  const checked = i.price_checked ? `<span class="${isStale(i.price_checked) ? "stale" : ""}">checked ${ago(i.price_checked)}</span>` : "";
  return `<tr data-id="${i.id}">
    <td class="s">${ADMIN ? `<button type="button" class="icon-btn" data-fav="${i.id}" title="${i.favorite ? "Unmark" : "Mark as a go-to"}" aria-label="Go-to dish" aria-pressed="${i.favorite}">${icon("star", i.favorite ? "fav" : "")}</button>` : i.favorite ? icon("star", "fav") : ""}</td>
    <td><div class="n">${esc(i.name)} ${kindBadge(i.kind)}</div>
      ${i.description || i.available ? `<div class="d">${[i.description, i.available].filter(Boolean).map(esc).join(" · ")}</div>` : ""}
      ${checked ? `<div class="d small">${checked}${ADMIN && i.price != null && daysSince(i.price_checked) > 30 ? ` · <button type="button" class="link small" data-ok="${i.id}">still ${money(i.price)}</button>` : ""}</div>` : ""}
      ${thumbs ? `<div class="item-thumbs">${thumbs}</div>` : ""}</td>
    <td class="p">${priceHTML(i.price)}</td>
    ${ADMIN ? `<td class="acts"><button type="button" class="icon-btn" data-edit="${i.id}" aria-label="Edit ${esc(i.name)}">${icon("edit")}</button></td>` : ""}
  </tr>`;
}
function itemFormHTML(i = {}) {
  return `<form class="item-form panel" data-item="${i.id || ""}">
    <label class="f name">Dish or deal<input name="name" required value="${esc(i.name)}" placeholder="e.g. Super burrito, Lunch combo #3" maxlength="120"></label>
    <label class="f">Price<input name="price" inputmode="decimal" value="${i.price ?? ""}" placeholder="11.50"></label>
    <label class="f">Type<select name="kind">${[["item", "Dish"], ["meal", "Meal deal"], ["special", "Special"]].map(([v, t]) => `<option value="${v}" ${i.kind === v ? "selected" : ""}>${t}</option>`).join("")}</select></label>
    <label class="f wide">Details <span class="hint">what comes with it, sizes</span><input name="description" value="${esc(i.description)}" placeholder="with rice, beans and a drink"></label>
    <label class="f wide">When <span class="hint">if it's only sometimes</span><input name="available" value="${esc(i.available)}" placeholder="Mon–Fri 11–3"></label>
    <div class="row wide"><label class="check"><input type="checkbox" name="favorite" ${i.favorite ? "checked" : ""}> Go-to dish</label></div>
    <div class="row wide"><button class="primary">${i.id ? "Save" : `${icon("plus")} Add`}</button>
      ${i.id ? `<button type="button" data-cancel>Cancel</button><button type="button" class="danger" data-del>${icon("trash")} Delete</button>` : ""}</div>
  </form>`;
}
const formItem = (form) => {
  const fd = new FormData(form);
  return { name: fd.get("name"), price: fd.get("price"), kind: fd.get("kind"), description: fd.get("description"),
    available: fd.get("available"), favorite: fd.get("favorite") === "on" };
};
const photoPicker = (cls, primary) => `<label class="btn ${primary ? "primary" : ""}">${icon("camera")} Take photo<input type="file" accept="image/*" capture="environment" class="${cls}"></label>
  <label class="btn">${icon("images")} Choose photos<input type="file" accept="image/*" multiple class="${cls}"></label>`;

async function placeView(id) {
  const p = await api("places/" + id);
  const cfg = await config();
  const facts = [
    p.address ? `<div class="row">${icon("pin")}<span>${esc(p.address)}</span></div>` : "",
    p.hours ? `<div class="row">${icon("clock")}<span>${esc(p.hours)}</span></div>` : "",
    p.phone ? `<div class="row">${icon("phone")}<a href="tel:${esc(p.phone.replace(/[^\d+]/g, ""))}">${esc(p.phone)}</a></div>` : "",
    p.website ? `<div class="row">${icon("link")}<a href="${esc(p.website)}" target="_blank" rel="noopener">${esc(p.website.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, ""))}</a></div>` : "",
    p.notes ? `<div class="row">${icon("note")}<span>${esc(p.notes)}</span></div>` : "",
    ADMIN && p.private_notes ? `<div class="row">${icon("lock")}<span>${esc(p.private_notes)} <span class="hint">(editors only)</span></span></div>` : "",
  ].join("");
  view.innerHTML = `
    ${p.photos.length ? `<a class="banner" href="/photos/${esc(p.photos[0].file)}" target="_blank" rel="noopener">${img(p.photos[0].file, false)}</a>` : ""}
    <div class="hero">
      <div>
        <h1>${esc(p.name)} ${p.closed ? `<span class="badge closed">Closed</span>` : ""}</h1>
        <div class="muted" style="margin-bottom:10px">${[p.cuisine, p.neighborhood, p.area, dollars(p.price_level)].filter(Boolean).map(esc).join(" · ")} ${stars(p.rating)}</div>
        <div class="facts">${facts}</div>
        <div class="row" style="margin-top:14px">
          <a class="btn primary" href="${directions(p)}" target="_blank" rel="noopener">${icon("route")} Directions</a>
          ${ADMIN ? `<a class="btn" href="#/place/${p.id}/edit">${icon("edit")} Edit place</a>` : ""}
        </div>
        ${ADMIN && p.added_by ? `<div class="hint" style="margin-top:8px">Added by ${esc(p.added_by)}</div>` : ""}
      </div>
      ${p.lat != null ? `<div id="mini" class="mini-map"></div>` : ADMIN && p.address ? `<div class="note">Couldn't find this address on the map. Check it in <a href="#/place/${p.id}/edit">Edit place</a>, or set the pin there.</div>` : ""}
    </div>

    <div class="section-h"><h2>What to get</h2><span class="muted small">cheapest first · <span class="price deal">$</span> = under $${cap()}</span></div>
    ${p.items.length ? `<table class="items-table"><tbody>${p.items.map((i) => itemRow(i, p)).join("")}</tbody></table>` : `<div class="empty" style="padding:16px">No dishes yet.</div>`}
    ${ADMIN ? `<div style="margin-top:12px" id="add-item">${itemFormHTML()}</div>
      ${cfg.menu_reading ? `<div class="panel" style="margin-top:12px"><div class="spread"><div><strong>${icon("sparkle")} Read a menu photo</strong>
        <div class="hint">Claude lists the dishes and prices; you pick which to add.</div></div>
        <div class="row">${photoPicker("menu-file")}</div></div>
        ${p.photos.length ? `<div class="hint" style="margin-top:8px">…or tap a photo below and choose <em>Read this menu</em>.</div>` : ""}
        <div id="menu-out"></div></div>` : ""}` : ""}

    <div class="section-h"><h2>Photos</h2>${ADMIN ? `<div class="row">${photoPicker("place-file", true)}</div>` : ""}</div>
    ${p.photos.length ? `<div class="photos">${p.photos.map((ph) => photoHTML(ph, p, cfg)).join("")}</div>` : `<div class="muted small">No photos yet.</div>`}
    <footer class="foot">${p.updated_at ? `Updated ${ago(p.updated_at.slice(0, 10))}.` : ""} Prices change: the date by each one says when it was last checked.</footer>`;

  if (p.lat != null) {
    loadLeaflet().then(() => {
      const m = L.map("mini", { scrollWheelZoom: false, zoomControl: false, attributionControl: true }).setView([p.lat, p.lng], 16);
      tiles(m); L.circleMarker([p.lat, p.lng], markerStyle({ cheapest: p.items[0]?.price ?? null })).addTo(m);
    }).catch(() => {});
  }
  if (!ADMIN) return;
  wireItems(p);
  wirePhotos(p, cfg);
}

function wireItems(p) {
  const reload = () => placeView(p.id);
  const add = $("#add-item form");
  add.onsubmit = async (e) => {
    e.preventDefault();
    try { await api(`places/${p.id}/items`, { method: "POST", body: formItem(add) }); toast("Added"); reload(); } catch (err) { toast(err.message); }
  };
  $$("[data-fav]").forEach((b) => b.onclick = async () => {
    const it = p.items.find((i) => i.id === +b.dataset.fav);
    try { await api("items/" + it.id, { method: "PUT", body: { favorite: !it.favorite } }); reload(); } catch (err) { toast(err.message); }
  });
  $$("[data-ok]").forEach((b) => b.onclick = async () => {
    try { await api(`items/${b.dataset.ok}/checked`, { method: "POST" }); toast("Price confirmed"); reload(); } catch (err) { toast(err.message); }
  });
  $$("[data-edit]").forEach((b) => b.onclick = () => {
    const it = p.items.find((i) => i.id === +b.dataset.edit);
    const tr = b.closest("tr");
    tr.innerHTML = `<td colspan="4">${itemFormHTML(it)}</td>`;
    const form = $("form", tr);
    form.onsubmit = async (e) => {
      e.preventDefault();
      try { await api("items/" + it.id, { method: "PUT", body: formItem(form) }); reload(); } catch (err) { toast(err.message); }
    };
    $("[data-cancel]", form).onclick = reload;
    $("[data-del]", form).onclick = async () => {
      if (!confirm(`Delete ${it.name}?`)) return;
      try { await api("items/" + it.id, { method: "DELETE" }); reload(); } catch (err) { toast(err.message); }
    };
  });
}

function photoHTML(ph, p, cfg) {
  const item = p.items.find((i) => i.id === ph.item_id);
  if (!ADMIN) return `<div class="photo"><a href="/photos/${esc(ph.file)}" target="_blank" rel="noopener">${img(ph.file)}</a>
    ${ph.caption || item ? `<div class="cap">${esc(ph.caption || item.name)}</div>` : ""}</div>`;
  return `<div class="photo" data-ph="${ph.id}">
    <a href="/photos/${esc(ph.file)}" target="_blank" rel="noopener">${img(ph.file)}</a>
    <div class="over">${p.photos[0].id !== ph.id ? `<button type="button" data-cover title="Make this the main photo" aria-label="Make main photo">${icon("star")}</button>` : ""}
      <button type="button" data-rm title="Delete photo" aria-label="Delete photo">${icon("trash")}</button></div>
    <div class="photo-edit">
      <select data-tag aria-label="Which dish"><option value="">Not a specific dish</option>${p.items.map((i) => `<option value="${i.id}" ${i.id === ph.item_id ? "selected" : ""}>${esc(i.name)}</option>`).join("")}</select>
      <input data-cap placeholder="Caption" value="${esc(ph.caption)}" aria-label="Caption">
      ${cfg.menu_reading ? `<button type="button" class="link small" data-read style="justify-self:start">${icon("sparkle")} Read this menu</button>` : ""}
    </div></div>`;
}

async function uploadFiles(url, files, extra = {}) {
  const fd = new FormData();
  for (const f of files) fd.append("file", f);
  for (const [k, v] of Object.entries(extra)) fd.append(k, v);
  toast(files.length > 1 ? `Uploading ${files.length} photos…` : "Uploading…");
  return api(url, { method: "POST", body: fd });
}

function wirePhotos(p, cfg) {
  const reload = () => placeView(p.id);
  $$(".place-file").forEach((inp) => inp.onchange = async () => {
    if (!inp.files.length) return;
    try { await uploadFiles(`places/${p.id}/photos`, inp.files); toast("Photo added"); reload(); } catch (e) { toast(e.message); }
  });
  $$("[data-ph]").forEach((el) => {
    const pid = el.dataset.ph, put = (body) => api("photos/" + pid, { method: "PUT", body });
    $("[data-tag]", el).onchange = async (e) => { try { await put({ item_id: e.target.value || null }); reload(); } catch (err) { toast(err.message); } };
    $("[data-cap]", el).onchange = async (e) => { try { await put({ caption: e.target.value }); toast("Caption saved"); } catch (err) { toast(err.message); } };
    $("[data-cover]", el) && ($("[data-cover]", el).onclick = async () => { await put({ cover: true }); reload(); });
    $("[data-rm]", el).onclick = async () => {
      if (!confirm("Delete this photo?")) return;
      try { await api("photos/" + pid, { method: "DELETE" }); reload(); } catch (err) { toast(err.message); }
    };
    $("[data-read]", el) && ($("[data-read]", el).onclick = () => readMenu(p, [p.photos.find((x) => x.id === +pid).file]));
  });
  if (cfg.menu_reading) {
    $$(".menu-file").forEach((inp) => inp.onchange = async () => {
      if (!inp.files.length) return;
      try {
        // keep the menu photo with the place (it's handy later), then read it
        const before = new Set(p.photos.map((x) => x.id));
        const np = await uploadFiles(`places/${p.id}/photos`, inp.files, { caption: "Menu" });
        p.photos = np.photos;
        readMenu(p, np.photos.filter((x) => !before.has(x.id)).map((x) => x.file));
      } catch (e) { toast(e.message); }
    });
  }
}

async function readMenu(p, files) {
  const out = $("#menu-out");
  out.scrollIntoView({ behavior: "smooth", block: "center" });
  out.innerHTML = `<p class="muted">${icon("sparkle")} Reading the menu… this takes 10–30 seconds.</p>`;
  let d;
  try { d = await api("menu/read", { method: "POST", body: { photos: files } }); } catch (e) { out.innerHTML = `<p class="note">${esc(e.message)}</p>`; return; }
  if (!d.items.length) { out.innerHTML = `<p class="note">No dishes with prices found on that photo.</p>`; return; }
  const have = new Set(p.items.map((i) => fold(i.name)));
  out.innerHTML = `<p class="small muted" style="margin:12px 0 6px">Found ${d.items.length}. Cheap ones are ticked; fix anything before adding.
      ${d.uncertain.length ? `<br><strong>Unsure about:</strong> <span>${d.uncertain.map(esc).join(", ")}</span>` : ""}</p>
    <div class="menu-rows">${d.items.map((it, n) => `<label>
      <input type="checkbox" data-n="${n}" ${isDeal(it.price) && !have.has(fold(it.name)) ? "checked" : ""}>
      <span><input type="text" data-name="${n}" value="${esc(it.name)}" aria-label="Name">
        <span class="hint">${[KIND[it.kind], it.description, it.available, have.has(fold(it.name)) ? "already listed" : ""].filter(Boolean).map(esc).join(" · ")}</span></span>
      <input type="text" inputmode="decimal" data-price="${n}" value="${it.price ?? ""}" aria-label="Price"></label>`).join("")}</div>
    <div class="row" style="margin-top:10px"><button type="button" class="primary" id="menu-add">${icon("plus")} Add ticked</button><button type="button" id="menu-cancel">Cancel</button></div>`;
  $("#menu-cancel").onclick = () => out.innerHTML = "";
  $("#menu-add").onclick = async () => {
    const items = $$("[data-n]", out).filter((c) => c.checked).map((c) => {
      const n = +c.dataset.n;
      return { ...d.items[n], name: $(`[data-name="${n}"]`, out).value, price: $(`[data-price="${n}"]`, out).value };
    });
    if (!items.length) return toast("Tick at least one");
    try { await api(`places/${p.id}/items`, { method: "POST", body: { items } }); toast(`Added ${items.length}`); placeView(p.id); } catch (e) { toast(e.message); }
  };
}

/* ---------- add / edit place ---------- */
async function editView(id) {
  const [p, f] = await Promise.all([id ? api("places/" + id) : Promise.resolve({}), facets()]);
  const areas = f.areas.map((a) => a.name);
  if (p.area && !areas.includes(p.area)) areas.push(p.area);
  let uploads = [], quick = [];
  view.innerHTML = `<h1 style="margin-top:16px">${id ? "Edit " + esc(p.name) : "Add a place"}</h1>
    <form class="form" id="pf">
      ${id ? "" : `<div class="panel"><div class="spread"><div><strong>At the restaurant?</strong><div class="hint">Fill this in from where you're standing.</div></div>
        <button type="button" id="here" class="primary">${icon("locate")} I'm here</button></div><div id="here-out"></div></div>`}
      <div class="panel"><strong>${id ? "Fill in from OpenStreetMap" : "Or look it up on OpenStreetMap"}</strong>
        <div class="hint">Search by name; picking a match fills in ${id ? "only the fields that are empty" : "the address, phone, hours and website it has"}.</div>
        <div class="row" style="flex-wrap:nowrap;margin-top:8px"><input id="osm-q" type="search" placeholder="Restaurant name, e.g. Los Gallos" value="${esc(p.name)}" aria-label="Restaurant name">
          <button type="button" id="osm-go">Search</button></div><div id="osm-out"></div></div>
      <label class="f">Name<input name="name" required value="${esc(p.name)}" maxlength="100" autocomplete="off"></label>
      <div class="grid2">
        <label class="f">Area<select name="area"><option value="">Pick from the map point</option>${areas.map((a) => `<option ${a === p.area ? "selected" : ""}>${esc(a)}</option>`).join("")}</select></label>
        <label class="f">Neighborhood<input name="neighborhood" value="${esc(p.neighborhood)}" placeholder="Mission, Todos Santos…"></label>
        <label class="f">Cuisine<input name="cuisine" list="cuisines" value="${esc(p.cuisine)}" placeholder="Mexican, Vietnamese…"><datalist id="cuisines">${f.cuisines.map((c) => `<option value="${esc(c.name)}">`).join("")}</datalist></label>
        <label class="f">Price range<select name="price_level"><option value="">–</option>${[1, 2, 3, 4].map((n) => `<option value="${n}" ${p.price_level === n ? "selected" : ""}>${"$".repeat(n)}</option>`).join("")}</select></label>
      </div>
      <label class="f">Address <span class="hint">the map pin comes from this unless you set it below</span>
        <div class="row" style="flex-wrap:nowrap"><input name="address" value="${esc(p.address)}" placeholder="1950 Grant St, Concord"><button type="button" id="find">${icon("pin")} Find</button></div></label>
      <input type="hidden" name="lat" value="${p.lat ?? ""}"><input type="hidden" name="lng" value="${p.lng ?? ""}">
      <div id="pin-map" class="mini-map ${p.lat != null ? "" : "hidden"}"></div>
      <div class="hint" id="pin-hint">${p.lat != null ? "Drag the pin if it's in the wrong spot." : ""}</div>
      <div class="grid2">
        <label class="f">Hours<input name="hours" value="${esc(p.hours)}" placeholder="Mon–Sat 10:30–8"></label>
        <label class="f">Phone<input name="phone" type="tel" value="${esc(p.phone)}"></label>
        <label class="f">Website<input name="website" inputmode="url" value="${esc(p.website)}"></label>
        <label class="f">Rating<select name="rating"><option value="">–</option>${[5, 4.5, 4, 3.5, 3, 2.5, 2, 1.5, 1].map((r) => `<option value="${r}" ${p.rating === r ? "selected" : ""}>${r} ★</option>`).join("")}</select></label>
      </div>
      <label class="f">Notes <span class="hint">public: what to know before going</span><textarea name="notes" placeholder="Order at the counter; line moves fast. Cash only.">${esc(p.notes)}</textarea></label>
      <label class="f">Private notes <span class="hint">editors only</span><textarea name="private_notes">${esc(p.private_notes)}</textarea></label>
      ${id ? `<label class="check"><input type="checkbox" name="closed" ${p.closed ? "checked" : ""}> Closed for good (hidden from the public list)</label>` : `
      <div class="panel"><strong>Photos</strong> <span class="hint">the storefront, the menu, the food</span>
        <div class="row" style="margin-top:8px">${photoPicker("stage-file", false)}</div><div class="staged" id="staged" style="margin-top:10px"></div></div>
      <div class="panel"><strong>Cheap things to order</strong> <span class="hint">optional now; you can add more (or read the menu photo) on the next page</span>
        <div id="quick" class="menu-rows" style="margin-top:8px"></div>
        <button type="button" id="quick-add" style="margin-top:8px">${icon("plus")} Another dish</button></div>`}
      <div class="row"><button class="primary" id="save">${id ? "Save" : "Save place"}</button><a class="btn" href="${id ? "#/place/" + id : "#/"}">Cancel</a>
        ${id ? `<button type="button" class="danger" id="del" style="margin-left:auto">${icon("trash")} Delete place</button>` : ""}</div>
    </form>`;

  const form = $("#pf");
  const F = (n) => form.elements[n];
  let pinMap = null, pin = null;
  const setPin = async (lat, lng, zoom = 17) => {
    F("lat").value = lat; F("lng").value = lng;
    $("#pin-map").classList.remove("hidden");
    $("#pin-hint").textContent = "Drag the pin if it's in the wrong spot.";
    await loadLeaflet();
    if (!pinMap) { pinMap = L.map("pin-map"); tiles(pinMap); }
    pinMap.setView([lat, lng], zoom);
    if (pin) pin.setLatLng([lat, lng]);
    else {
      pin = L.marker([lat, lng], { draggable: true, icon: L.divIcon({ className: "", html: `<span class="dot deal" style="width:20px;height:20px"></span>`, iconSize: [18, 18] }) }).addTo(pinMap);
      pin.on("dragend", () => { const ll = pin.getLatLng(); F("lat").value = ll.lat.toFixed(6); F("lng").value = ll.lng.toFixed(6); });
    }
    setTimeout(() => pinMap.invalidateSize(), 50);
  };
  if (p.lat != null) setPin(p.lat, p.lng);

  $("#find").onclick = async () => {
    const a = F("address").value.trim();
    if (!a) return toast("Type an address first");
    try {
      const g = await api("geocode?" + new URLSearchParams({ address: a, area: F("area").value }));
      setPin(g.lat, g.lng);
      if (!F("area").value && g.area) F("area").value = g.area;
    } catch (e) { toast(e.message); }
  };

  // fill only empty fields, so nothing typed (or saved) is overwritten
  const fill = (o) => {
    for (const k of ["name", "address", "cuisine", "website", "phone", "hours", "neighborhood"]) if (o[k] && !F(k).value) F(k).value = o[k];
    if (o.area) { if (![...F("area").options].some((x) => x.value === o.area)) F("area").add(new Option(o.area, o.area)); if (!F("area").value) F("area").value = o.area; }
  };
  const osmSearch = async () => {
    const q = $("#osm-q").value.trim(), out = $("#osm-out");
    if (!q) return toast("Type a name first");
    out.innerHTML = `<p class="muted small">Searching OpenStreetMap…</p>`;
    let d;
    try { d = await api("osm/search?" + new URLSearchParams({ q, area: F("area").value })); } catch (e) { out.innerHTML = `<p class="note">${esc(e.message)}</p>`; return; }
    out.innerHTML = d.results.length ? `<div class="pick-list" style="margin-top:8px">${d.results.map((o, n) => `<button type="button" data-r="${n}">
        <span><strong>${esc(o.name)}</strong><br><span class="hint">${[o.cuisine, o.address].filter(Boolean).map(esc).join(" · ")}</span>
          <br><span class="hint">${["phone", "hours", "website"].filter((k) => o[k]).join(", ") || "no phone, hours or website listed"}</span></span>
        ${o.known ? `<span class="hint">already in the list</span>` : ""}</button>`).join("")}</div>
        <p class="hint">Data © OpenStreetMap contributors. Missing something? Type it in.</p>`
      : `<p class="note" style="margin-top:8px">No match on OpenStreetMap${F("area").value ? ` in ${esc(F("area").value)}` : ""}. Type the details in.</p>`;
    $$("[data-r]", out).forEach((b) => b.onclick = () => {
      const o = d.results[+b.dataset.r];
      fill(o);
      if (o.lat != null && !F("lat").value) setPin(o.lat, o.lng);
      $$("[data-r]", out).forEach((x) => x.classList.toggle("primary", x === b));
      toast(`Filled from ${o.name}`);
    });
  };
  $("#osm-go").onclick = osmSearch;
  $("#osm-q").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); osmSearch(); } };

  if (!id) {
    $("#here").onclick = () => locateMe(async (pos) => {
      const out = $("#here-out");
      out.innerHTML = `<p class="muted small">Looking around…</p>`;
      let d;
      try { d = await api("nearby?" + new URLSearchParams(pos)); } catch (e) { out.innerHTML = `<p class="note">${esc(e.message)}</p>`; return; }
      setPin(d.lat, d.lng);
      fill({ area: d.area, address: d.address, neighborhood: d.neighborhood });
      out.innerHTML = `
        ${d.known.length ? `<p class="note" style="margin-top:10px">Already in the list nearby: ${d.known.map((k) => `<a href="#/place/${k.id}">${esc(k.name)}</a> (${k.m} m)`).join(", ")}</p>` : ""}
        ${d.osm.length ? `<p class="small muted" style="margin:10px 0 6px">Which one is it?</p><div class="pick-list">${d.osm.map((o, n) => `<button type="button" data-o="${n}">
            <span><strong>${esc(o.name)}</strong><br><span class="hint">${[o.cuisine, o.address].filter(Boolean).map(esc).join(" · ")}</span></span><span class="hint">${o.m} m</span></button>`).join("")}</div>` :
          `<p class="small muted" style="margin-top:8px">No restaurants listed on OpenStreetMap right here; type the name.</p>`}
        ${d.warnings.length ? `<p class="hint">${d.warnings.map(esc).join(" ")}</p>` : ""}`;
      $$("[data-o]", out).forEach((b) => b.onclick = () => {
        const o = d.osm[+b.dataset.o];
        F("name").value = o.name; F("address").value = "";
        fill(o);
        if (o.lat != null) setPin(o.lat, o.lng);
        $$("[data-o]", out).forEach((x) => x.classList.toggle("primary", x === b));
      });
    });

    const renderStaged = () => {
      $("#staged").innerHTML = uploads.map((t, n) => `<span><img src="/photos/t-${esc(t)}" alt=""><button type="button" data-rm="${n}" aria-label="Remove photo">${icon("x")}</button></span>`).join("");
      $$("#staged [data-rm]").forEach((b) => b.onclick = () => { uploads.splice(+b.dataset.rm, 1); renderStaged(); });
    };
    $$(".stage-file").forEach((inp) => inp.onchange = async () => {
      if (!inp.files.length) return;
      try { const r = await uploadFiles("uploads", inp.files); uploads = uploads.concat(r.uploads); renderStaged(); toast("Photo ready"); } catch (e) { toast(e.message); }
      inp.value = "";
    });
    const addQuick = () => {
      quick.push({});
      const n = quick.length - 1;
      $("#quick").insertAdjacentHTML("beforeend", `<label style="grid-template-columns:1fr 90px"><input type="text" data-qn="${n}" placeholder="Dish or deal" aria-label="Dish">
        <input type="text" inputmode="decimal" data-qp="${n}" placeholder="$" aria-label="Price"></label>`);
    };
    addQuick();
    $("#quick-add").onclick = addQuick;
  } else {
    $("#del").onclick = async () => {
      if (!confirm(`Delete ${p.name}, its dishes and its photos? This can't be undone.`)) return;
      try { await api("places/" + id, { method: "DELETE" }); S.facets = null; toast("Deleted"); location.hash = "#/"; } catch (e) { toast(e.message); }
    };
  }

  form.onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(form), body = {};
    for (const k of ["name", "area", "neighborhood", "cuisine", "price_level", "address", "hours", "phone", "website", "rating", "notes", "private_notes", "lat", "lng"]) body[k] = fd.get(k);
    if (id) {
      body.closed = fd.get("closed") === "on";
      // a new address without a moved pin: let the server look the address up again
      if (body.address !== (p.address || "") && body.lat === String(p.lat ?? "") && body.lng === String(p.lng ?? "")) { body.lat = ""; body.lng = ""; }
    } else {
      body.uploads = uploads;
      body.items = $$("[data-qn]").map((x) => ({ name: x.value.trim(), price: $(`[data-qp="${x.dataset.qn}"]`).value.trim() })).filter((x) => x.name);
    }
    $("#save").disabled = true;
    try {
      const r = await api(id ? "places/" + id : "places", { method: id ? "PUT" : "POST", body });
      S.facets = null;
      toast("Saved");
      location.hash = "#/place/" + r.id;
    } catch (err) { toast(err.message); $("#save").disabled = false; }
  };
}

/* ---------- more (editors) ---------- */
async function moreView() {
  const [me, cfg, f] = await Promise.all([api("me"), config(), facets(true)]);
  const total = f.areas.reduce((n, a) => n + a.n, 0);
  view.innerHTML = `<h1 style="margin-top:16px">More</h1>
    <div class="form">
      <div class="panel"><strong>Signed in</strong><div class="muted">${me.email ? esc(me.email) : "On the home network (LAN editing)"}</div></div>
      <div class="panel"><strong>The list</strong>
        <div class="muted small">${total} place${total === 1 ? "" : "s"} · ${f.items} dish${f.items === 1 ? "" : "es"} · ${f.areas.filter((a) => a.n).map((a) => `${esc(a.name)} ${a.n}`).join(", ") || "no areas yet"}</div>
        <div class="row" style="margin-top:10px"><a class="btn" href="#/?closed=1" id="show-closed">Closed places</a>
          <a class="btn" href="/admin/api/export.csv">Download CSV</a><a class="btn" href="/admin/api/export.json">Download JSON</a></div></div>
      <div class="panel"><strong>Settings</strong> <span class="hint">in /etc/conf.d/lunch, then rc-service lunch restart</span>
        <div class="small" style="margin-top:6px;display:grid;gap:4px">
          <div>${icon(cfg.menu_reading ? "check" : "x")} Menu reading with Claude ${cfg.menu_reading ? "" : `<span class="hint">set ANTHROPIC_API_KEY</span>`}</div>
          <div>${icon(cfg.public_view ? "check" : "x")} ${cfg.public_view ? "Public list at /" : "Public list is off (PUBLIC_VIEW=0)"}</div>
          <div>${icon("check")} "Cheap" means under $${cfg.cheap_under} <span class="hint">CHEAP_UNDER</span></div>
          <div>${icon("check")} Areas: ${cfg.areas.map((a) => esc(a.name)).join(", ")} <span class="hint">AREAS</span></div>
        </div></div>
      <div class="panel"><strong>On your phone</strong><div class="small muted">Open ${esc(location.origin)}/admin in Chrome and choose <em>Install app</em> (or <em>Add to Home screen</em>). Location and the camera need the HTTPS address, not the LAN IP.</div></div>
    </div>`;
  $("#show-closed").onclick = async (e) => {
    e.preventDefault();
    const d = await api("places?closed=1&sort=name");
    const closed = d.places.filter((p) => p.closed);
    view.insertAdjacentHTML("beforeend", `<div class="section-h"><h2>Closed places</h2></div><div class="list">${closed.map(placeCard).join("") || `<div class="muted">None.</div>`}</div>`);
  };
}

/* ---------- start ---------- */
(async () => {
  if (!ADMIN) { try { S.editor = (await api("/api/me")).editor; } catch { /* ignore */ } }
  route();
})();
