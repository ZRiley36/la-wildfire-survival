/* LA Wildfire Survival: MapLibre front end. Data built by `python -m wildfire web`. */

const COLORS = {
  destroyed: "#e34948", damaged: "#eda100", none: "#2a78d6", unscored: "#c3c2b7",
  risk: ["#fbe3cf", "#f5b08f", "#eb6834", "#c4401b", "#7f2a10"],
  zone: "rgba(117,107,177,0.8)", perimeter: "#0b0b0b",
};
const RISK_BREAKS = [0.5, 0.6, 0.7, 0.8];
const OUTCOME_LABEL = { destroyed: "Destroyed", damaged: "Damaged", none: "No damage" };
const FIRES = {
  both: [[-118.72, 34.02], [-118.0, 34.25]],
  palisades: [[-118.70, 34.025], [-118.50, 34.12]],
  eaton: [[-118.20, 34.15], [-118.02, 34.24]],
};
const FOOTPRINT_ZOOM = 15.5;

const $ = (id) => document.getElementById(id);
const dataUrl = (f) => new URL(`data/${f}`, location.href).href;
const fmtInt = (n) => Math.round(n).toLocaleString();
const pct = (v) => `${Math.round(v * 100)}%`;
const escapeHtml = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const map = new maplibregl.Map({
  container: "map",
  style: "https://tiles.openfreemap.org/styles/positron",
  bounds: FIRES.both,
  fitBoundsOptions: { padding: { top: 40, bottom: 40, left: window.innerWidth > 640 ? 400 : 20, right: 40 } },
  minZoom: 9,
  maxZoom: 18.5,
  maxBounds: [[-119.2, 33.7], [-117.6, 34.5]],
  hash: true,
  attributionControl: { compact: true },
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
map.addControl(new maplibregl.ScaleControl({ unit: "imperial" }), "bottom-right");

const byId = new Map();
let stats = null;
let mode = "outcome";

function step(prop, breaks, colors) {
  const e = ["step", ["to-number", ["get", prop]], colors[0]];
  breaks.forEach((b, i) => e.push(b, colors[i + 1]));
  return e;
}

function hatchImage(color, size = 12) {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const ctx = c.getContext("2d");
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.3;
  for (const o of [-size, 0, size]) { ctx.beginPath(); ctx.moveTo(o, size); ctx.lineTo(o + size, 0); ctx.stroke(); }
  return ctx.getImageData(0, 0, size, size);
}

function colorExpr() {
  if (mode === "risk") {
    // unscored homes have no risk; coalesce to -1 so the expression never compares against null
    const e = ["step", ["coalesce", ["get", "risk"], -1], COLORS.unscored, 0, COLORS.risk[0]];
    RISK_BREAKS.forEach((b, i) => e.push(b, COLORS.risk[i + 1]));
    return e;
  }
  return ["match", ["get", "outcome"], "destroyed", COLORS.destroyed, "damaged", COLORS.damaged, COLORS.none];
}

map.on("load", async () => {
  const firstLabel = map.getStyle().layers.find((l) => l.type === "symbol")?.id;
  map.addImage("hatch-zone", hatchImage(COLORS.zone), { pixelRatio: 2 });
  const [buildings, s, fuelBounds] = await Promise.all(["buildings.geojson", "stats.json", "fuel_bounds.json"]
    .map((f) => fetch(dataUrl(f)).then((r) => r.json())));
  stats = s;
  buildings.features.forEach((f) => byId.set(f.properties.id, f));

  map.addSource("zones", { type: "geojson", data: dataUrl("zones.geojson") });
  map.addSource("perim", { type: "geojson", data: dataUrl("perimeters.geojson") });
  map.addSource("buildings", { type: "geojson", data: buildings, promoteId: "id" });
  map.addSource("footprints", { type: "geojson", data: dataUrl("footprints.geojson"), promoteId: "id" });
  for (const fire of ["palisades", "eaton"]) {
    map.addSource(`fuel-${fire}`, { type: "image", url: dataUrl(`fuel_${fire}.png`), coordinates: fuelBounds[fire] });
    map.addLayer({ id: `fuel-${fire}`, type: "raster", source: `fuel-${fire}`, layout: { visibility: "none" },
      paint: { "raster-resampling": "nearest", "raster-opacity": 1 } }, firstLabel);
  }
  map.addLayer({ id: "zones", type: "fill", source: "zones", layout: { visibility: "none" },
    paint: { "fill-pattern": "hatch-zone" } }, firstLabel);
  map.addLayer({ id: "zones-line", type: "line", source: "zones", layout: { visibility: "none" },
    paint: { "line-color": COLORS.zone, "line-width": 1 } }, firstLabel);
  map.addLayer({ id: "perim", type: "line", source: "perim",
    paint: { "line-color": COLORS.perimeter, "line-width": ["interpolate", ["linear"], ["zoom"], 10, 1.2, 15, 2.5], "line-opacity": 0.85 } });

  map.addLayer({ id: "footprints", type: "fill", source: "footprints", minzoom: FOOTPRINT_ZOOM - 0.5,
    paint: { "fill-color": colorExpr(), "fill-opacity": ["interpolate", ["linear"], ["zoom"], FOOTPRINT_ZOOM - 0.5, 0, FOOTPRINT_ZOOM, 0.9] } });
  map.addLayer({ id: "footprints-line", type: "line", source: "footprints", minzoom: FOOTPRINT_ZOOM,
    paint: { "line-color": "#ffffff", "line-width": 0.6 } });
  map.addLayer({ id: "points", type: "circle", source: "buildings",
    paint: {
      "circle-color": colorExpr(),
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 1.4, 13, 2.8, 15.5, 5],
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 10, 0, 13, 0.5, 15.5, 1],
      "circle-opacity": ["interpolate", ["linear"], ["zoom"], FOOTPRINT_ZOOM, 1, FOOTPRINT_ZOOM + 0.6, 0],
      "circle-stroke-opacity": ["interpolate", ["linear"], ["zoom"], FOOTPRINT_ZOOM, 1, FOOTPRINT_ZOOM + 0.6, 0],
    } });
  map.addLayer({ id: "selected-fp", type: "line", source: "footprints", filter: ["==", ["get", "id"], -1],
    paint: { "line-color": "#0b0b0b", "line-width": 3 } });
  map.addLayer({ id: "selected-pt", type: "circle", source: "buildings", filter: ["==", ["get", "id"], -1],
    paint: { "circle-radius": 9, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#0b0b0b", "circle-stroke-width": 2.5 } });

  fillStats();
  wireControls();
  wireSearch();
});

function fillStats() {
  $("s-homes").textContent = fmtInt(stats.buildings);
  $("s-destroyed").textContent = `${Math.round(stats.destroyed_pct)}%`;
  $("s-auc-model").textContent = stats.auc.hgb.toFixed(2);
  $("s-auc-zone").textContent = stats.auc.fhsz_in_effect.toFixed(2);
  $("s-xfire").textContent = `${stats.xfire["eaton->palisades"].hgb.toFixed(2)} (Eaton → Palisades) and ${stats.xfire["palisades->eaton"].hgb.toFixed(2)} (the reverse)`;
  const rows = [
    ["Gradient boosting", stats.auc.hgb, "var(--risk-hi)"],
    ["Logistic regression", stats.auc.logistic, "var(--damaged)"],
    ["Hazard zone, Jan 2025", stats.auc.fhsz_in_effect, "var(--zone)"],
  ];
  $("compare").innerHTML = rows.map(([label, v, c]) => `<span>${label}</span>
    <span class="track"><span class="fill" style="--c:${c}; width:${Math.max(0, (v - 0.5) / 0.5 * 100)}%"></span></span>
    <span class="v">${v.toFixed(2)}</span>`).join("");
  const ticks = ["<50%", "50%", "60%", "70%", "80%+"];
  $("risk-ramp").innerHTML = COLORS.risk.map((c, i) => `<div><div class="bin" style="--c:${c}"></div><div class="tick">${ticks[i]}</div></div>`).join("");
}

function setMode(m) {
  mode = m;
  document.querySelectorAll("[data-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === m)));
  map.setPaintProperty("points", "circle-color", colorExpr());
  map.setPaintProperty("footprints", "fill-color", colorExpr());
  $("legend-outcome").hidden = m !== "outcome";
  $("legend-risk").hidden = m !== "risk";
}

function wireControls() {
  const vis = (ids, on) => ids.forEach((id) => map.setLayoutProperty(id, "visibility", on ? "visible" : "none"));
  document.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  document.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () =>
    map.fitBounds(FIRES[b.dataset.go], { padding: { top: 40, bottom: 40, left: window.innerWidth > 640 ? 400 : 20, right: 40 } })));
  $("lyr-perim").addEventListener("change", (e) => vis(["perim"], e.target.checked));
  $("lyr-zone").addEventListener("change", (e) => vis(["zones", "zones-line"], e.target.checked));
  $("lyr-fuel").addEventListener("change", (e) => vis(["fuel-palisades", "fuel-eaton"], e.target.checked));
  $("show-outside").addEventListener("change", (e) => {
    const f = e.target.checked ? null : ["==", ["get", "inside"], 1];
    map.setFilter("points", f);
    const ids = e.target.checked ? null : [...byId.values()].filter((b) => b.properties.inside === 1).map((b) => b.properties.id);
    map.setFilter("footprints", ids ? ["in", ["get", "id"], ["literal", ids]] : null);
    map.setFilter("footprints-line", ids ? ["in", ["get", "id"], ["literal", ids]] : null);
  });
  $("collapse").addEventListener("click", () => {
    const collapsed = $("panel").classList.toggle("collapsed");
    $("collapse").setAttribute("aria-expanded", String(!collapsed));
  });
  // Browsers restore form state on reload without firing change events. Push it to the map.
  ["lyr-perim", "lyr-zone", "lyr-fuel", "show-outside"].forEach((id) => $(id).dispatchEvent(new Event("change")));

  for (const layer of ["points", "footprints"]) {
    map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; });
  }
  map.on("click", (e) => {
    const pad = 6;
    const hit = map.queryRenderedFeatures([[e.point.x - pad, e.point.y - pad], [e.point.x + pad, e.point.y + pad]],
      { layers: ["footprints", "points"] })[0];
    if (hit) showBuilding(hit.properties.id, e.lngLat);
  });
}

function bar(label, value) {
  return `<div class="bar"><span class="bl">${label}</span>
    <span class="track"><span class="fill" style="width:${Math.round(value * 100)}%"></span></span><span class="bv">${pct(value)}</span></div>`;
}

function showBuilding(id, lngLat) {
  const f = byId.get(id);
  if (!f) return;
  const p = f.properties;
  map.setFilter("selected-fp", ["==", ["get", "id"], id]);
  map.setFilter("selected-pt", ["==", ["get", "id"], id]);
  const color = COLORS[p.outcome];
  const where = p.inside ? "inside the perimeter" : "just outside the perimeter";
  const model = p.risk == null
    ? `<p class="hint">Outside the perimeter, so the model didn't score it.</p>`
    : `<div class="bars">${bar("Predicted risk", p.risk)}${bar("Trained on the other fire", p.risk_x)}</div>`;
  new maplibregl.Popup({ maxWidth: "320px" }).setLngLat(lngLat ?? f.geometry.coordinates).setHTML(`<div class="pop">
    <h3>${escapeHtml(p.addr || "Address not recorded")}</h3>
    <div class="sub">${escapeHtml(p.comm)} · ${p.fire} fire · ${where}</div>
    <div class="tag" style="--c:${color}">${OUTCOME_LABEL[p.outcome]}${p.outcome === "damaged" ? ` (${escapeHtml(p.damage)})` : ""}</div>
    ${model}
    <dl>
      <dt>Year built</dt><dd>${p.yr ?? "unknown"}</dd>
      <dt>Nearest building</dt><dd>${p.near_m} m</dd>
      <dt>Buildings within 50 m</dt><dd>${p.n50}</dd>
      <dt>Distance to wildland</dt><dd>${fmtInt(p.wild_m)} m</dd>
      <dt>Slope</dt><dd>${p.slope}°</dd>
      <dt>Hazard zone (Jan 2025)</dt><dd>${escapeHtml(p.zone)}</dd>
    </dl></div>`).addTo(map).on("close", () => {
    map.setFilter("selected-fp", ["==", ["get", "id"], -1]);
    map.setFilter("selected-pt", ["==", ["get", "id"], -1]);
  });
}

/* ---------- Search: addresses of inspected homes, matched in the browser ---------- */

function wireSearch() {
  const input = $("q"), list = $("results"), status = $("search-status");
  const index = [...byId.values()].filter((f) => f.properties.addr)
    .map((f) => ({ id: f.properties.id, addr: f.properties.addr, key: f.properties.addr.toUpperCase(), sub: `${f.properties.comm} · ${f.properties.fire}` }));
  let results = [], active = -1;
  const close = () => { list.hidden = true; input.setAttribute("aria-expanded", "false"); active = -1; };
  const highlight = (i) => {
    active = i;
    [...list.children].forEach((li, j) => li.setAttribute("aria-selected", String(j === i)));
    input.setAttribute("aria-activedescendant", i >= 0 ? `res-${i}` : "");
  };
  input.addEventListener("input", () => {
    const words = input.value.trim().toUpperCase().split(/\s+/).filter(Boolean);
    status.textContent = "";
    if (input.value.trim().length < 2) return close();
    results = index.filter((r) => words.every((w) => r.key.includes(w)))
      .sort((a, b) => Number(!a.key.startsWith(words[0])) - Number(!b.key.startsWith(words[0])) || a.key.localeCompare(b.key))
      .slice(0, 8);
    if (!results.length) { close(); status.textContent = "No inspected home at that address."; return; }
    list.innerHTML = results.map((r, i) => `<li id="res-${i}" role="option" aria-selected="false" data-i="${i}">${escapeHtml(r.addr)}<span class="boro">${escapeHtml(r.sub)}</span></li>`).join("");
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    highlight(-1);
  });
  input.addEventListener("keydown", (e) => {
    if (list.hidden) return;
    if (e.key === "ArrowDown") { e.preventDefault(); highlight(Math.min(active + 1, results.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); highlight(Math.max(active - 1, 0)); }
    else if (e.key === "Escape") close();
  });
  $("search").addEventListener("submit", (e) => { e.preventDefault(); if (results.length) choose(results[Math.max(active, 0)]); });
  list.addEventListener("mousedown", (e) => {
    const li = e.target.closest("li");
    if (li) { e.preventDefault(); choose(results[Number(li.dataset.i)]); }
  });
  input.addEventListener("blur", () => setTimeout(close, 150));
  function choose(r) {
    close();
    input.value = r.addr;
    const f = byId.get(r.id);
    const pad = window.innerWidth > 640 ? { left: 380, top: 0, right: 0, bottom: 0 } : { bottom: window.innerHeight * 0.5, top: 0, left: 0, right: 0 };
    map.flyTo({ center: f.geometry.coordinates, zoom: 17, padding: pad, essential: true });
    map.once("moveend", () => showBuilding(r.id));
  }
}
