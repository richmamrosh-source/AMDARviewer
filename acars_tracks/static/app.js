/* ===========================================================================
   ACARS flight tracks + wind barbs + clickable soundings — frontend
   - loads per-aircraft flight tracks and draws them as polylines
   - hover any observation point for time / altitude / temp / wind
   - tracks whose aircraft has a vertical profile are highlighted; click a
     highlighted track (or its ▲/▼ marker) to plot that aircraft's sounding
     (Skew-T/Log-P, rendered server-side with pyMeteo) in a side panel
   - "Wind barbs" toggle renders proper wind barbs, color-coded by speed (kt)
   ========================================================================== */

(function () {
  "use strict";

  // ---- wind-speed color scale (knots) ------------------------------------
  const SPEED_BINS = [
    [10, "#6ca0dc"], [20, "#4fb0a5"], [30, "#5cb85c"], [40, "#c3d34a"],
    [50, "#f0c419"], [70, "#f0932b"], [90, "#e74c3c"], [9999, "#b33771"],
  ];
  function speedColor(kt) {
    for (const [lim, c] of SPEED_BINS) if (kt < lim) return c;
    return "#b33771";
  }

  // ---- wind barb SVG (verified geometry) ---------------------------------
  function speedBins(kt) {
    let s = Math.round(kt / 5) * 5;
    const pennants = Math.floor(s / 50); s -= pennants * 50;
    const fulls = Math.floor(s / 10); s -= fulls * 10;
    const half = s >= 5 ? 1 : 0;
    return { pennants, fulls, half };
  }
  function windBarbSVG(kt, dir, color, size) {
    size = size || 46;
    const cx = size / 2, cy = size / 2;
    if (kt < 2.5) {
      return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
        <circle cx="${cx}" cy="${cy}" r="4.5" fill="none" stroke="${color}" stroke-width="1.6"/></svg>`;
    }
    const Lstaff = 19, step = 4.4, barbLen = 12, halfLen = 6.5, pennLen = 12, lean = 0.55;
    const parts = [];
    parts.push(`<line x1="${cx}" y1="${cy}" x2="${cx}" y2="${cy - Lstaff}" stroke="${color}" stroke-width="1.7" stroke-linecap="round"/>`);
    const { pennants, fulls, half } = speedBins(kt);
    let y = cy - Lstaff;
    for (let i = 0; i < pennants; i++) {
      const y2 = y + step * 1.4;
      parts.push(`<polygon points="${cx},${y} ${cx},${y2} ${cx + pennLen},${y + 1}" fill="${color}" stroke="${color}" stroke-width="0.5" stroke-linejoin="round"/>`);
      y = y2 + 2.2;
    }
    if (pennants) y += 1.0;
    for (let i = 0; i < fulls; i++) {
      parts.push(`<line x1="${cx}" y1="${y}" x2="${cx + barbLen}" y2="${y - barbLen * lean}" stroke="${color}" stroke-width="1.7" stroke-linecap="round"/>`);
      y += step;
    }
    if (half) {
      if (pennants === 0 && fulls === 0) y += step;
      parts.push(`<line x1="${cx}" y1="${y}" x2="${cx + halfLen}" y2="${y - halfLen * lean}" stroke="${color}" stroke-width="1.7" stroke-linecap="round"/>`);
    }
    parts.push(`<circle cx="${cx}" cy="${cy}" r="1.7" fill="${color}"/>`);
    return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}"><g transform="rotate(${dir} ${cx} ${cy})">${parts.join("")}</g></svg>`;
  }

  // ---- map ----------------------------------------------------------------
  const map = L.map("map", {
    center: [39, -96], zoom: 4, zoomControl: true,
    worldCopyJump: true, minZoom: 3, maxZoom: 11, preferCanvas: true,
  });
  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a> &middot; ACARS data: NOAA MADIS',
    subdomains: "abcd", maxZoom: 19, className: "basemap-tiles",
  }).addTo(map);

  const canvasR = L.canvas({ padding: 0.5, tolerance: 6 });
  const svgR = L.svg({ padding: 0.5 });           // SVG so the highlight can CSS-flash
  const trackLayer = L.layerGroup().addTo(map);
  const dotLayer = L.layerGroup().addTo(map);
  const barbLayer = L.layerGroup().addTo(map);
  const edrR = L.canvas({ padding: 0.5 });        // turbulence dots, own canvas (drawn above)
  const edrLayer = L.layerGroup().addTo(map);
  const soundLayer = L.layerGroup().addTo(map);
  const raobLayer = L.layerGroup().addTo(map);
  const pirepLayer = L.layerGroup().addTo(map);
  const highlightLayer = L.layerGroup().addTo(map);   // "find aircraft" flash overlay

  // ---- state --------------------------------------------------------------
  let allTracks = [];
  let allObs = [];
  let barbsOn = false;
  let edrOn = false;
  let soundOn = true;
  let tracksOn = true;
  let lastVersion = null;
  let profileMetas = [];          // [{id,tail,lat,lon,airport,updown,time,levels}]
  let tailToProfiles = {};        // tail -> [meta, ...]
  let profileById = {};           // id -> meta
  let tailsWithSound = new Set();
  let airportGroups = {};         // groupKey -> [meta, ...] (most recent first)
  let groupKeyById = {};          // id -> groupKey

  // ---- altitude filter state ----
  const ALT_FLOOR = 0, ALT_CEIL = 45000, ALT_GAP = 500;   // feet
  const M_PER_FT = 0.3048;
  let altMinFt = ALT_FLOOR, altMaxFt = ALT_CEIL;
  const altFiltered = () => altMinFt > ALT_FLOOR || altMaxFt < ALT_CEIL;
  function altBoundsM() {
    return [altMinFt * M_PER_FT, altMaxFt >= ALT_CEIL ? Infinity : altMaxFt * M_PER_FT];
  }
  function altPassAlt(altM) {            // altM in meters, may be null
    if (!altFiltered()) return true;
    if (altM == null) return false;
    const b = altBoundsM();
    return altM >= b[0] && altM <= b[1];
  }
  const altPassObs = (o) => altPassAlt(o.alt);
  const altPassPt = (p) => altPassAlt(p[2]);

  // ---- wind speed filter state ----
  const WS_FLOOR = 0, WS_CEIL = 200, WS_GAP = 5;          // knots
  let wsMin = WS_FLOOR, wsMax = WS_CEIL;
  const wsFiltered = () => wsMin > WS_FLOOR || wsMax < WS_CEIL;
  function wsPass(ws) {                  // ws in knots, may be null
    if (!wsFiltered()) return true;
    if (ws == null) return false;
    const hi = wsMax >= WS_CEIL ? Infinity : wsMax;
    return ws >= wsMin && ws <= hi;
  }
  const wsPassObs = (o) => wsPass(o.ws);

  // ---- data density (thinning) state ----
  // higher = more points plotted (less thinning); lower = sparser / decluttered
  let density = 55;                       // 0..100
  function densParams() {
    const f = density / 100;
    return {
      dotSpacing: Math.round(24 - 20 * f),          // px between dots: 24 -> 4
      dotCap: Math.round(1200 + 4800 * f),          // 1200 -> 6000
      barbSpacing: Math.round(80 - 72 * f),         // px between barbs: 80 -> 8
      barbCap: Math.round(250 + 3250 * f * f),      // 250 -> 3500
    };
  }

  const $ = (id) => document.getElementById(id);

  // ---- build / draw -------------------------------------------------------
  function buildObs() {
    allObs = [];
    for (const t of allTracks) {
      for (const p of t.pts) {
        allObs.push({
          lat: p[0], lon: p[1], alt: p[2], temp: p[3], dew: p[4],
          ws: p[5], wd: p[6], epoch: p[7], edr: (p.length > 8 ? p[8] : null), id: t.id,
        });
      }
    }
  }

  function groupKeyOf(m) {
    if (m.airport && m.airport.trim()) return "apt:" + m.airport.trim().toUpperCase();
    if (m.lat != null && m.lon != null) return "@" + m.lat.toFixed(1) + "," + m.lon.toFixed(1);
    return "id:" + m.id;
  }

  function buildProfileIndex(profiles) {
    profileMetas = profiles || [];
    tailToProfiles = {};
    profileById = {};
    tailsWithSound = new Set();
    airportGroups = {};
    groupKeyById = {};
    for (const m of profileMetas) {
      profileById[m.id] = m;
      tailsWithSound.add(m.tail);
      (tailToProfiles[m.tail] = tailToProfiles[m.tail] || []).push(m);
      const k = groupKeyOf(m);
      groupKeyById[m.id] = k;
      (airportGroups[k] = airportGroups[k] || []).push(m);
    }
    for (const k in airportGroups) {
      airportGroups[k].sort((a, b) => (b.time || 0) - (a.time || 0));  // recent first
    }
  }

  function _haversineKm(a, b) {
    const R = 6371, toR = Math.PI / 180;
    const dLat = (b[0] - a[0]) * toR, dLon = (b[1] - a[1]) * toR;
    const h = Math.sin(dLat / 2) ** 2 +
      Math.cos(a[0] * toR) * Math.cos(b[0] * toR) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
  }
  function _validPt(p) {
    return Number.isFinite(p[0]) && Number.isFinite(p[1]) &&
      Math.abs(p[0]) <= 90 && Math.abs(p[1]) <= 180;
  }

  // Split a track into drawable segments. Breaks the line between two reports
  // when they can't be a single continuous leg: a ±180° wrap (drawn the wrong
  // way across the whole map), an impossible ground speed, or a huge gap when
  // there's no time to judge by. This removes the stray lines across the map.
  const MAX_KMH = 1400;   // above any airliner's ground speed (incl. jet-stream)
  const HARD_KM = 4000;   // backstop when timestamps are missing
  function trackSegments(pts) {
    const segs = [];
    let cur = [], prev = null, prevT = null;
    for (const p of pts) {
      if (!_validPt(p) || !altPassPt(p)) { if (cur.length) segs.push(cur); cur = []; prev = null; continue; }
      const ll = [p[0], p[1]], t = p[7];
      if (prev) {
        let brk = false;
        if (Math.abs(ll[1] - prev[1]) > 180) {
          brk = true;                                   // antimeridian wrap
        } else {
          const km = _haversineKm(prev, ll);
          if (prevT != null && t != null) {
            const dt = Math.abs(t - prevT) / 3600;      // hours
            if (km > 50 && (dt <= 0 || km / dt > MAX_KMH)) brk = true;
          } else if (km > HARD_KM) {
            brk = true;
          }
        }
        if (brk) { if (cur.length) segs.push(cur); cur = []; }
      }
      cur.push(ll);
      prev = ll; prevT = t;
    }
    if (cur.length) segs.push(cur);
    return segs.filter((s) => s.length >= 2);
  }

  // cached per-track bounding box [minLat, minLon, maxLat, maxLon]
  function trackBounds(t) {
    if (t._bb) return t._bb;
    let s = 90, w = 180, n = -90, e = -180;
    for (const p of t.pts) {
      if (!_validPt(p)) continue;
      if (p[0] < s) s = p[0];
      if (p[0] > n) n = p[0];
      if (p[1] < w) w = p[1];
      if (p[1] > e) e = p[1];
    }
    t._bb = [s, w, n, e];
    return t._bb;
  }

  let _drawSeq = 0;   // bumps on each drawTracks; lets an in-flight chunked draw bail
  function drawTracks() {
    trackLayer.clearLayers();
    _drawSeq++;
    if (!tracksOn) return;
    // 1) viewport cull: only tracks whose box overlaps the current view (like dots)
    const vb = map.getBounds();
    const vs = vb.getSouth(), vn = vb.getNorth(), vw = vb.getWest(), ve = vb.getEast();
    const vis = [];
    for (const t of allTracks) {
      const bb = trackBounds(t);
      if (bb[2] < vs || bb[0] > vn || bb[3] < vw || bb[1] > ve) continue;
      vis.push(t);
    }
    // 2) draw in chunks across animation frames so a big set never freezes the UI
    const seq = _drawSeq;
    const CHUNK = 400;
    let i = 0;
    (function drawChunk() {
      if (seq !== _drawSeq) return;                 // a newer draw superseded us
      const end = Math.min(i + CHUNK, vis.length);
      for (; i < end; i++) {
        const t = vis[i];
        const segs = trackSegments(t.pts);
        if (!segs.length) continue;
        const hasSnd = tailsWithSound.has(t.id);
        const line = L.polyline(segs, {
          renderer: canvasR,
          color: hasSnd ? "#9fc4ff" : "#5b8fd6",
          weight: hasSnd ? 2.0 : 1.3,
          opacity: hasSnd ? 0.92 : 0.45,
          lineCap: "round", lineJoin: "round",
          smoothFactor: 1.5,                        // mild simplification, fewer points to stroke
        });
        if (hasSnd) {
          line.on("click", (e) => { L.DomEvent.stop(e); openSoundingForTail(t.id, e.latlng); });
          line.on("mouseover", () => { map.getContainer().style.cursor = "pointer"; });
          line.on("mouseout", () => { map.getContainer().style.cursor = ""; });
        }
        line.addTo(trackLayer);
      }
      if (i < vis.length) requestAnimationFrame(drawChunk);
    })();
  }

  // ---- find / highlight one aircraft (by FSL/tail id) ---------------------
  let highlightId = null;

  function matchTracks(q) {
    const up = q.toUpperCase();
    let hits = allTracks.filter((t) => (t.id || "").toUpperCase() === up);
    if (!hits.length) hits = allTracks.filter((t) => (t.id || "").toUpperCase().includes(up));
    return hits;
  }

  function renderHighlight(hits) {
    highlightLayer.clearLayers();
    let latest = null, latestT = -Infinity;
    const allLL = [];
    for (const t of hits) {
      for (const seg of trackSegments(t.pts)) {
        allLL.push(...seg);
        // wide soft halo underneath
        L.polyline(seg, { renderer: svgR, color: "#ffcf4d", weight: 7,
          opacity: 0.28, lineCap: "round", lineJoin: "round", interactive: false })
          .addTo(highlightLayer);
        // bright flashing line on top
        L.polyline(seg, { renderer: svgR, color: "#ffcf4d", weight: 2.6,
          opacity: 1, lineCap: "round", lineJoin: "round", interactive: false,
          className: "track-flash" }).addTo(highlightLayer);
      }
      for (const p of t.pts) {                 // remember the most recent fix
        if (_validPt(p) && p[7] != null && p[7] > latestT) { latestT = p[7]; latest = p; }
      }
    }
    if (latest) {
      const icon = L.divIcon({ className: "find-pulse", iconSize: [0, 0],
        html: '<span class="ring"></span><span class="core"></span>' });
      L.marker([latest[0], latest[1]], { icon, interactive: false, keyboard: false })
        .addTo(highlightLayer);
    }
    return allLL;
  }

  function findAircraft(raw) {
    const q = (raw || "").trim();
    if (!q) { clearHighlight(); toast("Type an FSL / tail ID first (e.g. from a data point's hover box)"); return; }
    const hits = matchTracks(q);
    if (!hits.length) {
      clearHighlight();
      toast('No aircraft matching "' + q + '" in the current data');
      return;
    }
    highlightId = q;
    const allLL = renderHighlight(hits);
    $("btn-find-clear").style.display = "";
    if (allLL.length) {
      map.flyToBounds(L.latLngBounds(allLL), { padding: [60, 60], maxZoom: 8, duration: 0.6 });
    }
    const ids = [...new Set(hits.map((t) => t.id))];
    const label = ids.length === 1 ? ids[0] : hits.length + " tracks";
    const npts = hits.reduce((n, t) => n + t.pts.length, 0);
    toast("Highlighting " + label + " · " + npts + " reports");
  }

  // re-apply the highlight after data reloads (aircraft may have new points)
  function refreshHighlight() {
    if (!highlightId) return;
    const hits = matchTracks(highlightId);
    if (hits.length) renderHighlight(hits);
    else highlightLayer.clearLayers();
  }

  function clearHighlight() {
    highlightId = null;
    highlightLayer.clearLayers();
    $("btn-find-clear").style.display = "none";
  }

  // thin points to one per spacing-px grid cell within the current view
  function thinInView(obs, spacingPx, cap) {
    const b = map.getBounds();
    const s = b.getSouth(), n = b.getNorth(), w = b.getWest(), e = b.getEast();
    const cells = new Set();
    const out = [];
    for (const o of obs) {
      if (o.lat < s || o.lat > n || o.lon < w || o.lon > e) continue;
      const pt = map.latLngToContainerPoint([o.lat, o.lon]);
      const key = ((pt.x / spacingPx) | 0) + ":" + ((pt.y / spacingPx) | 0);
      if (cells.has(key)) continue;
      cells.add(key);
      out.push(o);
      if (out.length >= cap) break;
    }
    return out;
  }

  function obsHTML(o) {
    const ft = o.alt != null ? Math.round(o.alt * 3.28084) : null;
    const fl = ft != null ? "FL" + String(Math.round(ft / 100)).padStart(3, "0") : "";
    const tm = new Date(o.epoch * 1000).toISOString().slice(11, 16);
    const wind = (o.wd != null && o.ws != null)
      ? `<span class="wind">${String(o.wd).padStart(3, "0")}° @ ${Math.round(o.ws)} kt</span>`
      : '<span class="mut">wind n/a</span>';
    const altTxt = ft != null ? `${fl} · ${ft.toLocaleString()} ft` : '<span class="mut">altitude n/a</span>';
    const tTxt = o.temp != null ? `${o.temp}°C` : '<span class="mut">T n/a</span>';
    const dTxt = o.dew != null
      ? `<span class="mut">Td</span> ${o.dew}°C`
      : '<span class="mut">Td n/a</span>';
    // turbulence line only when the aircraft actually reported EDR
    let turb = "";
    if (o.edr != null) {
      const cat = edrCat(o.edr);
      turb = `<div><span class="mut">turbulence</span> ` +
        `<b style="color:${cat.c}">${cat.t}</b> ` +
        `<span class="mut">(EDR ${o.edr.toFixed(2)})</span></div>`;
    }
    const cue = tailsWithSound.has(o.id) ? '<div class="snd-cue">click for sounding ▸</div>' : "";
    return `<div><span class="id">${o.id}</span> <span class="mut">${tm}Z</span></div>
      <div>${altTxt}</div>
      <div>${tTxt} &nbsp; ${dTxt}</div>
      <div>${wind}</div>${turb}${cue}`;
  }

  function renderDots() {
    dotLayer.clearLayers();
    const src = (altFiltered() || wsFiltered())
      ? allObs.filter((o) => altPassObs(o) && wsPassObs(o)) : allObs;
    const dp = densParams();
    const sel = thinInView(src, dp.dotSpacing, dp.dotCap);
    for (const o of sel) {
      const hasSnd = tailsWithSound.has(o.id);
      const m = L.circleMarker([o.lat, o.lon], {
        renderer: canvasR, radius: hasSnd ? 3.0 : 2.6, weight: 0,
        fillColor: hasSnd ? "#cfe0ff" : "#a8c8ec", fillOpacity: 0.9,
      });
      m.bindTooltip(obsHTML(o), { className: "obs-tip", direction: "top", offset: [0, -3], sticky: true });
      m.on("click", (e) => {
        if (hasSnd) { L.DomEvent.stop(e); openSoundingForTail(o.id, e.latlng); }
      });
      m.addTo(dotLayer);
    }
  }

  function renderBarbs() {
    barbLayer.clearLayers();
    if (!barbsOn) return;
    const withWind = allObs.filter((o) => o.ws != null && o.wd != null
      && altPassObs(o) && wsPassObs(o));
    const dp = densParams();
    const sel = thinInView(withWind, dp.barbSpacing, dp.barbCap);
    for (const o of sel) {
      const html = `<div class="barb">${windBarbSVG(o.ws, o.wd, speedColor(o.ws), 46)}</div>`;
      const icon = L.divIcon({ className: "", html, iconSize: [46, 46], iconAnchor: [23, 23] });
      L.marker([o.lat, o.lon], { icon, interactive: false, keyboard: false }).addTo(barbLayer);
    }
  }

  // ---- turbulence (EDR) ---------------------------------------------------
  // severity bands for cube-root EDR (m^2/3 / s), the ICAO turbulence metric
  function edrCat(e) {
    if (e >= 0.60) return { c: "#e879f9", t: "extreme" };
    if (e >= 0.40) return { c: "#ff5252", t: "severe" };
    if (e >= 0.20) return { c: "#ff9e2c", t: "moderate" };
    if (e >= 0.10) return { c: "#ffe04d", t: "light" };
    return { c: "#4fd1c5", t: "smooth" };
  }

  function renderEdr() {
    edrLayer.clearLayers();
    if (!edrOn) return;
    // points that actually reported EDR, within the altitude band
    let src = allObs.filter((o) => o.edr != null && altPassObs(o));
    // strongest first so thinning keeps the worst bumps, not the calm ones
    src = src.slice().sort((a, b) => b.edr - a.edr);
    const dp = densParams();
    const sel = thinInView(src, dp.dotSpacing * 0.7, 1500);
    for (const o of sel) {
      const cat = edrCat(o.edr);
      const strong = o.edr >= 0.10;                // light or worse
      const r = 3 + Math.min(o.edr, 0.7) * 11;     // bigger dot = stronger
      const m = L.circleMarker([o.lat, o.lon], {
        renderer: edrR, radius: r, weight: strong ? 1.1 : 0.6, color: "#0a0e14",
        fillColor: cat.c, fillOpacity: strong ? 0.88 : 0.5,
      });
      m.bindTooltip(edrTip(o, cat), { className: "obs-tip", direction: "top", offset: [0, -3], sticky: true });
      m.addTo(edrLayer);
    }
  }

  function edrTip(o, cat) {
    const fl = (o.alt != null) ? "FL" + String(Math.round(o.alt * 3.28084 / 100)).padStart(3, "0") : "—";
    const iso = o.epoch ? new Date(o.epoch * 1000).toISOString() : null;
    const when = iso ? iso.slice(0, 10) + " " + iso.slice(11, 16) + "Z" : "";
    return `<b>${o.id}</b> · <b style="color:${cat.c}">${cat.t}</b> turbulence<br>` +
      `EDR <b>${o.edr.toFixed(2)}</b> m²ᐟ³·s⁻¹ · ${fl}` +
      (when ? `<br><span class="mut">${when}</span>` : "");
  }

  function updateEdrLegend() {
    const el = $("edr-legend");
    if (el) el.classList.toggle("show", edrOn);
  }

  // ---- pilot reports (PIREPs / AIREPs) ------------------------------------
  let pirepsOn = false;
  let pirepData = null;
  const PIREP_COLOR = {
    turb: "#f5a623", icing: "#38bdf8", both: "#c084fc", nil: "#34d399", other: "#94a3b8",
  };
  const PIREP_LABEL = {
    turb: "turbulence", icing: "icing", both: "turbulence + icing",
    nil: "smooth / negative", other: "report",
  };

  function loadPireps() {
    fetch("/api/pireps")
      .then((r) => r.json())
      .then((d) => {
        pirepData = (d && d.pireps) || [];
        drawPireps();
        if (d && d.error) toast("PIREPs: " + d.error);
        else if (pirepsOn && pirepData.length === 0) toast("No pilot reports in this window");
      })
      .catch(() => { if (pirepsOn) toast("Could not load PIREPs"); });
  }

  function drawPireps() {
    pirepLayer.clearLayers();
    if (!pirepsOn || !pirepData) return;
    for (const p of pirepData) {
      if (p.lat == null || p.lon == null) continue;
      const col = PIREP_COLOR[p.cat] || PIREP_COLOR.other;
      const faint = (p.cat === "other");
      const sz = (p.cat === "nil" || p.cat === "other") ? 9 : 10 + Math.min(p.sev || 0, 4) * 2.6;
      const icon = L.divIcon({
        className: "pirep-marker",
        html: `<div class="pirep-mk" style="--c:${col};--s:${sz}px;opacity:${faint ? 0.6 : 1}"></div>`,
        iconSize: [sz + 6, sz + 6], iconAnchor: [(sz + 6) / 2, (sz + 6) / 2],
      });
      L.marker([p.lat, p.lon], { icon, riseOnHover: true })
        .bindTooltip(pirepTip(p), { className: "obs-tip", direction: "top", offset: [0, -6], sticky: true })
        .addTo(pirepLayer);
    }
  }

  function pirepTip(p) {
    const col = PIREP_COLOR[p.cat] || PIREP_COLOR.other;
    const fl = (p.fl != null) ? "FL" + String(p.fl).padStart(3, "0") : "—";
    const when = p.time ? new Date(p.time * 1000).toISOString().slice(11, 16) + "Z" : "";
    const tb = (p.tb && p.tb !== "NEG") ? `Turb <b>${p.tb}</b>${p.tbType ? " " + p.tbType : ""}` : "";
    const ic = (p.ic && p.ic !== "NEG") ? `Icing <b>${p.ic}</b>${p.icType ? " " + p.icType : ""}` : "";
    const neg = (!tb && !ic && (p.tb === "NEG" || p.ic === "NEG")) ? "smooth / no hazard reported" : "";
    const hazard = [tb, ic].filter(Boolean).join(" · ") || neg;
    const raw = p.raw ? `<div class="praw">${p.raw}</div>` : "";
    return `<div><b>${p.ac || "PIREP"}</b> · <b style="color:${col}">${PIREP_LABEL[p.cat] || "report"}</b></div>` +
      (hazard ? `<div>${hazard}</div>` : "") +
      `<div>${fl}${when ? " · " + when : ""}</div>${raw}`;
  }

  function updatePirepLegend() {
    const el = $("pirep-legend");
    if (el) el.classList.toggle("show", pirepsOn);
  }

  // ---- sounding location markers -----------------------------------------
  function fmtTime(epoch) {
    if (!epoch) return "";
    return new Date(epoch * 1000).toISOString().slice(11, 16) + "Z";
  }

  function fmtAgo(epoch) {
    if (!epoch) return "";
    const s = Math.floor(Date.now() / 1000 - epoch);
    if (s < 0) return "";
    if (s < 3600) return Math.max(1, Math.floor(s / 60)) + "m ago";
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    return m ? `${h}h ${m}m ago` : `${h}h ago`;
  }

  // friendly location of a sounding: nearest city, else the raw airport code
  function placeOf(m) {
    return ((m && (m.place || m.airport)) || "").toString().trim();
  }
  // label for a whole airport group: "Berlin (EDDB)" when a code adds detail
  function groupLabelOf(g) {
    const name = (g[0].place || "").trim();
    const code = (g[0].airport || "").trim();
    if (name && code && code.toUpperCase() !== name.toUpperCase()) return `${name} (${code})`;
    return name || code || "this location";
  }

  function renderSoundMarkers() {
    soundLayer.clearLayers();
    if (!soundOn) return;
    for (const k in airportGroups) {
      const g = airportGroups[k];
      let sx = 0, sy = 0, c = 0;
      for (const m of g) if (m.lat != null && m.lon != null) { sx += m.lat; sy += m.lon; c++; }
      if (!c) continue;                       // no location -> still reachable via track click
      const lat = sx / c, lon = sy / c;
      const multi = g.length > 1;
      const apt = groupLabelOf(g);
      let badge, cls, tip;
      if (multi) {
        badge = String(g.length); cls = "badge multi";
        const times = g.map((x) => x.time).filter(Boolean);
        let span = "";
        if (times.length) {
          const lo = Math.min.apply(null, times), hi = Math.max.apply(null, times);
          span = (lo === hi ? fmtTime(hi) : `${fmtTime(lo)} – ${fmtTime(hi)}`);
          const ago = fmtAgo(hi);
          if (ago) span += `<br>latest ${ago}`;
        }
        tip = `<b>${apt || "soundings"}</b><br>${g.length} soundings` + (span ? "<br>" + span : "");
      } else {
        const m = g[0];
        badge = m.updown === "UP" ? "▲" : (m.updown === "DOWN" ? "▼" : "•");
        cls = "badge";
        const where = [placeOf(m), m.updown].filter(Boolean).join(" ");
        const ago = fmtAgo(m.time);
        tip = `<b>${m.tail}</b>${where ? "<br>" + where : ""}<br>` +
              `${fmtTime(m.time)}${ago ? " · " + ago : ""} · ${m.levels} lvl`;
      }
      const icon = L.divIcon({ className: "snd-marker", html: `<div class="${cls}">${badge}</div>`,
        iconSize: [24, 24], iconAnchor: [12, 12] });
      L.marker([lat, lon], { icon, riseOnHover: true })
        .bindTooltip(tip, { className: "snd-tip", direction: "top", offset: [0, -11] })
        .on("click", (e) => { L.DomEvent.stop(e); openSounding(g[0].id); })
        .addTo(soundLayer);
    }
  }

  // ---- radiosonde (RAOB) stations -----------------------------------------
  let raobOn = false;
  let raobStations = null;

  function drawRaobMarkers() {
    raobLayer.clearLayers();
    if (!raobOn || !raobStations) return;
    for (const s of raobStations) {
      if (s.lat == null || s.lon == null) continue;
      const icon = L.divIcon({
        className: "raob-marker",
        html: `<div class="raob-pill"><span class="raob-glyph"></span>${s.id || ""}</div>`,
        iconSize: [46, 20], iconAnchor: [23, 10],
      });
      L.marker([s.lat, s.lon], { icon, riseOnHover: true })
        .bindTooltip(`<b>${s.id || ""}</b> · ${s.name || ""}<br>radiosonde — click for its sounding`,
          { className: "snd-tip", direction: "top", offset: [0, -9] })
        .on("click", (e) => { L.DomEvent.stop(e); openRaob(s); })
        .addTo(raobLayer);
    }
  }

  function loadRaobMarkers() {
    fetch("/api/raob/stations")
      .then((r) => r.json())
      .then((d) => { raobStations = d.stations || []; drawRaobMarkers(); })
      .catch(() => toast("Could not load radiosonde stations"));
  }

  function openRaob(stn) {
    selGroupKey = null; selectedIds = [];          // detach from the aircraft tab strip
    renderTabs();
    hrrrTargetId = null; $("snd-hrrr").style.display = "none";
    const panel = $("sndpanel");
    panel.classList.add("open");
    panel.setAttribute("aria-hidden", "false");
    $("snd-loading").style.display = "";
    $("snd-img").style.display = "none"; $("snd-img").removeAttribute("src");
    $("snd-hodo").style.display = "none"; $("snd-hodo").removeAttribute("src");
    $("snd-error").style.display = "none";
    renderAnalysis(null);
    $("snd-tail").textContent = "Radiosonde";
    $("snd-where").textContent = [stn.id, stn.name].filter(Boolean).join(" ");
    $("snd-foot").textContent = "Fetching radiosonde…";

    const token = ++sndReqToken;
    fetch(`/api/raob/sounding?stn=${encodeURIComponent(stn.wmo)}`)
      .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then((d) => {
        if (token !== sndReqToken) return;
        if (d.error) {
          $("snd-loading").style.display = "none";
          const e = $("snd-error"); e.style.display = ""; e.textContent = d.error;
          $("snd-foot").textContent = "";
          toast("Radiosonde unavailable");
          return;
        }
        const img = $("snd-img");
        img.onload = () => {
          if (token !== sndReqToken) return;
          $("snd-loading").style.display = "none";
          img.style.display = "";
        };
        img.src = d.png;
        setSndHoverData(d);
        $("snd-tail").textContent = "Radiosonde";
        $("snd-where").textContent = (d.name || "") + (d.time ? " · " + d.time : "");
        setSndNote(d.note, d.note_level);
        const i = d.info || {};
        const hum = i.have_humidity ? "humidity ✓" : "no humidity reported";
        $("snd-foot").innerHTML =
          `<b>${i.levels ?? "?"}</b> levels · sfc <b>${i.sfc_p_hPa ?? "?"}</b> hPa → ` +
          `<b>${i.top_p_hPa ?? "?"}</b> hPa · radiosonde · ${hum} · renderer: <b>${d.renderer || "?"}</b>`;
        renderAnalysis(d.analysis, "radiosonde");
        const hodo = $("snd-hodo");
        if (d.hodograph) { hodo.src = d.hodograph; hodo.style.display = ""; }
        else { hodo.style.display = "none"; hodo.removeAttribute("src"); }
      })
      .catch((err) => {
        if (token !== sndReqToken) return;
        $("snd-loading").style.display = "none";
        const e = $("snd-error"); e.style.display = "";
        e.textContent = "Could not fetch the radiosonde (" + err.message + ").";
        toast("Radiosonde unavailable");
      });
  }

  function renderTabs() {
    const host = $("snd-tabs");
    const g = selGroupKey ? airportGroups[selGroupKey] : null;
    if (!g || g.length <= 1) { host.classList.remove("show"); host.innerHTML = ""; return; }
    const apt = groupLabelOf(g);
    const label = `<div class="snd-tabs-label"><b>${apt}</b> — ${g.length} soundings ` +
      `· <span class="snd-tabs-hint">shift-click to overlay</span></div>`;
    const tabs = g.map((m) => {
      const arr = m.updown === "UP" ? "▲" : (m.updown === "DOWN" ? "▼" : "•");
      const t = fmtTime(m.time);
      const act = selectedIds.indexOf(m.id) >= 0 ? " active" : "";
      return `<button class="snd-tab${act}" data-id="${m.id}">` +
             `<span class="arr">${arr}</span>${m.tail}${t ? " · " + t : ""}</button>`;
    }).join("");
    host.innerHTML = label + `<div class="snd-tabs-row">${tabs}</div>`;
    host.classList.add("show");
    host.querySelectorAll(".snd-tab").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const id = btn.getAttribute("data-id");
        if (e.shiftKey) toggleOverlay(id); else openSounding(id);
      });
    });
    if (selectedIds.length === 1) {
      const a = host.querySelector(".snd-tab.active");
      if (a) a.scrollIntoView({ inline: "center", block: "nearest" });
    }
  }

  // ---- sounding panel -----------------------------------------------------
  function openSoundingForTail(tail, latlng) {
    const metas = tailToProfiles[tail];
    if (!metas || !metas.length) { toast(`No vertical profile for ${tail}`); return; }
    let chosen = metas[0];
    if (metas.length > 1) {
      if (latlng) {
        let best = Infinity;
        for (const m of metas) {
          if (m.lat == null) continue;
          const d = (m.lat - latlng.lat) ** 2 + (m.lon - latlng.lng) ** 2;
          if (d < best) { best = d; chosen = m; }
        }
      } else {
        chosen = metas.reduce((a, b) => ((b.time || 0) > (a.time || 0) ? b : a), metas[0]);
      }
    }
    openSounding(chosen.id);
  }

  let sndReqToken = 0;
  let selectedIds = [];          // ids currently shown (1 = single, >=2 = overlay)
  let selGroupKey = null;        // group the current selection belongs to
  let hrrrTargetId = null;       // aircraft sounding id eligible for HRRR compare

  function openSounding(id) {              // fresh single open (marker / track / normal tab click)
    selGroupKey = groupKeyById[id] || null;
    selectedIds = [id];
    renderSelection();
  }

  function toggleOverlay(id) {             // shift-click a tab: add/remove from overlay
    const k = groupKeyById[id];
    if (k !== selGroupKey || selectedIds.length === 0) { openSounding(id); return; }
    const idx = selectedIds.indexOf(id);
    if (idx >= 0) {
      if (selectedIds.length > 1) selectedIds.splice(idx, 1);   // keep at least one
    } else {
      selectedIds.push(id);
    }
    renderSelection();
  }

  function fmtNum(v, unit) {
    return (v === null || v === undefined) ? "—" : (v + (unit ? " " + unit : ""));
  }
  function renderAnalysis(an, src) {
    const host = $("snd-analysis");
    if (!an || !an.ok) { host.classList.remove("show"); host.innerHTML = ""; return; }
    const cell = (k, v) => `<div class="ana-cell"><span class="ana-k">${k}</span><span class="ana-v">${v}</span></div>`;
    const group = (title, cells) => {
      const f = cells.filter(Boolean);
      return f.length ? `<div class="ana-group"><div class="ana-title">${title}</div><div class="ana-grid">${f.join("")}</div></div>` : "";
    };
    const moist = an.sb_cape !== null && an.sb_cape !== undefined;
    let html = "";
    if (moist) {
      const trunc = !!an.cape_truncated;
      const capeVal = (v) => (v == null ? "—" : (trunc ? "≥ " : "") + fmtNum(v, "J/kg"));
      html += group("Instability", [
        cell("SBCAPE", capeVal(an.sb_cape)),
        cell("MUCAPE", capeVal(an.mu_cape)),
        cell("SBCIN", fmtNum(an.sb_cin, "J/kg")),
        cell("Lifted Index", fmtNum(an.li, "°C")),
      ]);
      if (trunc) {
        html += `<div class="ana-note">⚠ Profile ends at ${an.cape_top_p} hPa with the parcel still buoyant, so CAPE is a <b>truncated lower bound</b> — shallow aircraft soundings can't capture full CAPE, and the real CAPE value may be much higher.</div>`;
      }
      html += group("Levels", [
        an.lcl_p != null ? cell("LCL", an.lcl_p + " hPa" + (an.lcl_z != null ? " · " + an.lcl_z + " m" : "")) : cell("LCL", "—"),
        cell("LFC", an.lfc_p != null ? an.lfc_p + " hPa" : "—"),
        cell("EL", an.el_p != null ? an.el_p + " hPa" : "—"),
        cell("Freezing lvl", fmtNum(an.fz_z, "m")),
        cell("−20°C lvl", fmtNum(an.m20_z, "m")),
      ]);
      html += group("Moisture & indices", [
        cell("Precip. water", fmtNum(an.pw, "mm")),
        cell("K index", fmtNum(an.k_index, "")),
        cell("Total Totals", fmtNum(an.total_totals, "")),
        cell("700–500 lapse", fmtNum(an.lr_700_500, "°C/km")),
        cell("0–3 km lapse", fmtNum(an.lr_0_3, "°C/km")),
      ]);
      html += group("Surface", [
        cell("Temp", fmtNum(an.sfc_T, "°C")),
        cell("Dewpoint", fmtNum(an.sfc_Td, "°C")),
        cell("RH", fmtNum(an.sfc_RH, "%")),
      ]);
    } else {
      html += group("Thermal · no humidity reported", [
        cell("Sfc temp", fmtNum(an.sfc_T, "°C")),
        cell("Freezing lvl", fmtNum(an.fz_z, "m")),
        cell("−20°C lvl", fmtNum(an.m20_z, "m")),
        cell("700–500 lapse", fmtNum(an.lr_700_500, "°C/km")),
        cell("0–3 km lapse", fmtNum(an.lr_0_3, "°C/km")),
      ]);
    }
    if (an.has_wind) {
      const mw = (an.mw_0_6_dir != null && an.mw_0_6_kt != null)
        ? String(an.mw_0_6_dir).padStart(3, "0") + "° · " + an.mw_0_6_kt + " kt" : "—";
      const sm = (an.storm_dir != null && an.storm_kt != null)
        ? String(an.storm_dir).padStart(3, "0") + "° · " + an.storm_kt + " kt" : "—";
      html += group("Wind & shear", [
        cell("0–1 km shear", fmtNum(an.shear_0_1, "kt")),
        cell("0–6 km shear", fmtNum(an.shear_0_6, "kt")),
        cell("Mean wind 0–6", mw),
        cell("Bunkers RM", sm),
        cell("SRH 0–1 km", fmtNum(an.srh_0_1, "m²/s²")),
        cell("SRH 0–3 km", fmtNum(an.srh_0_3, "m²/s²")),
      ]);
    }
    host.innerHTML = html +
      `<div class="ana-note">Computed from the ${src || "ACARS profile"} (surface-based parcel) — estimated values.</div>`;
    host.classList.add("show");
  }

  function renderSelection() {
    const ids = selectedIds.slice();
    const single = ids.length === 1;
    const panel = $("sndpanel");
    panel.classList.add("open");
    panel.setAttribute("aria-hidden", "false");
    $("snd-loading").style.display = "";
    $("snd-img").style.display = "none";
    $("snd-img").removeAttribute("src");
    $("snd-hodo").style.display = "none";
    $("snd-hodo").removeAttribute("src");
    $("snd-error").style.display = "none";
    renderAnalysis(null);
    renderTabs();
    hrrrTargetId = single ? ids[0] : null;
    $("snd-hrrr").style.display = single ? "" : "none";

    if (single) {
      const m = profileById[ids[0]];
      $("snd-tail").textContent = m ? m.tail : "…";
      $("snd-where").textContent = m
        ? [placeOf(m), m.updown].filter(Boolean).join(" ") + " · " + fmtTime(m.time) : "";
    } else {
      const apt = placeOf(profileById[ids[0]]);
      $("snd-tail").textContent = ids.length + " soundings";
      $("snd-where").textContent = (apt ? apt + " · " : "") + "overlaid by time";
    }
    $("snd-foot").textContent = "Rendering…";

    const token = ++sndReqToken;
    fetch(`/api/sounding?id=${encodeURIComponent(ids.join(","))}`)
      .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then((d) => {
        if (token !== sndReqToken) return;                  // superseded
        const img = $("snd-img");
        img.onload = () => {
          if (token !== sndReqToken) return;
          $("snd-loading").style.display = "none";
          img.style.display = "";
        };
        img.src = d.png;
        setSndHoverData(d.overlay ? null : d);
        if (!d.overlay) {
          $("snd-tail").textContent = d.tail || "—";
          $("snd-where").textContent =
            [d.place || d.airport, d.updown].filter(Boolean).join(" ") + (d.time ? " · " + d.time : "");
          setSndNote(d.note, d.note_level);
          const i = d.info || {};
          const hum = i.have_humidity ? "humidity ✓" : "no humidity reported";
          $("snd-foot").innerHTML =
            `<b>${i.levels ?? "?"}</b> levels · sfc <b>${i.sfc_p_hPa ?? "?"}</b> hPa → ` +
            `<b>${i.top_p_hPa ?? "?"}</b> hPa · ${hum} · renderer: <b>${d.renderer || "?"}</b>`;
          renderAnalysis(d.analysis);
          const hodo = $("snd-hodo");
          if (d.hodograph) { hodo.src = d.hodograph; hodo.style.display = ""; }
          else { hodo.style.display = "none"; hodo.removeAttribute("src"); }
        } else {
          const mem = d.members || [];
          const tsp = ids.map((i) => profileById[i] && profileById[i].time).filter(Boolean);
          let span = "";
          if (tsp.length >= 2) {
            const lo = Math.min.apply(null, tsp), hi = Math.max.apply(null, tsp);
            if (lo !== hi) span = ` · ${fmtTime(lo)} – ${fmtTime(hi)}`;
          }
          $("snd-tail").textContent = d.count + " soundings";
          $("snd-where").textContent = (d.airport ? d.airport + " · " : "") + "overlaid" + span;
          setSndNote(null);        // the warning belongs to a single sounding
          $("snd-foot").innerHTML = "overlay · " +
            mem.map((x) => `<span style="color:${x.color}">${x.tail}${x.time ? " " + x.time : ""}</span>`).join("  ") +
            "  · solid = T, dashed = Td";
        }
      })
      .catch((err) => {
        if (token !== sndReqToken) return;
        $("snd-loading").style.display = "none";
        const e = $("snd-error");
        e.style.display = "";
        e.textContent = "Could not render (" + err.message + ").";
        toast("Sounding unavailable");
      });
  }

  // ---- sounding hover readout (values as you scan up/down the Skew-T) ------
  let curSnd = { levels: null, geom: null };

  // The warning under the sounding header. Two tiers: "alert" (red, flashing) is
  // reserved for a sensor that's actually lying — a bad dewpoint. "info" (quiet
  // amber) is for things worth knowing but not alarming: MADIS per-ob QC flags, a
  // radiosonde site that didn't launch. Kept out of #snd-where because that line
  // is nowrap/ellipsis and would chop a long warning mid-sentence.
  function setSndNote(text, level) {
    const el = $("snd-note");
    if (!text) { el.style.display = "none"; el.textContent = ""; return; }
    el.className = "snd-note" + (level === "info" ? " info" : "");
    el.textContent = (level === "info" ? "" : "⚠ ") + text;
    el.style.display = "block";
    el.style.animation = "none";      // replay the flash for every new sounding,
    void el.offsetWidth;              // not just the first one (forces a reflow)
    el.style.animation = "";
  }

  function setSndHoverData(d) {
    curSnd = (d && d.geom && d.levels && d.levels.length)
      ? { levels: d.levels, geom: d.geom } : { levels: null, geom: null };
    if (!curSnd.geom) hideSndHover();
  }
  function hideSndHover() {
    $("snd-cross").style.display = "none";
    $("snd-readout").style.display = "none";
  }
  function _fyForP(g, p) {                    // image-fraction y for a pressure (log-p axis)
    const t = (Math.log10(p) - Math.log10(g.p_top)) /
              (Math.log10(g.p_bot) - Math.log10(g.p_top));
    return g.y0 + t * (g.y1 - g.y0);
  }
  function sndHoverMove(e) {
    const g = curSnd.geom, lv = curSnd.levels, img = $("snd-img");
    if (!g || !lv || img.style.display === "none") { hideSndHover(); return; }
    const r = img.getBoundingClientRect();
    if (r.height < 5) { hideSndHover(); return; }
    const fy = (e.clientY - r.top) / r.height;
    if (fy < g.y0 - 0.02 || fy > g.y1 + 0.02) { hideSndHover(); return; }
    const tt = Math.min(1, Math.max(0, (fy - g.y0) / (g.y1 - g.y0)));
    const pc = Math.pow(10, Math.log10(g.p_top) + tt * (Math.log10(g.p_bot) - Math.log10(g.p_top)));
    let best = lv[0], bd = Infinity;                 // snap to nearest reported level
    for (const L of lv) { const dd = Math.abs(L.p - pc); if (dd < bd) { bd = dd; best = L; } }
    const cy = r.top + _fyForP(g, best.p) * r.height;
    const cross = $("snd-cross");
    cross.style.display = "block";
    cross.style.left = (r.left + g.x0 * r.width) + "px";
    cross.style.width = ((g.x1 - g.x0) * r.width) + "px";
    cross.style.top = cy + "px";
    const ft = best.z != null ? Math.round(best.z * 3.28084) : null;
    let html = `<b>${best.p.toFixed(0)} hPa</b>`;
    if (best.z != null) html += ` <span class="mut">·</span> ${ft.toLocaleString()} ft`;
    html += `<br>T <b>${best.t != null ? best.t.toFixed(1) + "°C" : "—"}</b>`;
    html += `  <span class="mut">Td</span> ${best.td != null ? best.td.toFixed(1) + "°C" : "—"}`;
    if (best.wdir != null && best.wspd != null)
      html += `<br><span class="mut">wind</span> ${String(best.wdir).padStart(3, "0")}° / ${best.wspd} kt`;
    if (best.qc) html += `<br><b style="color:#ff6b6b">⚠ flagged by MADIS QC</b>`;
    const ro = $("snd-readout");
    ro.innerHTML = html;
    ro.style.display = "block";
    let rx = e.clientX + 16, ry = cy + 12;           // place near cursor, flip to stay on-screen
    if (rx + ro.offsetWidth > window.innerWidth - 8) rx = e.clientX - ro.offsetWidth - 16;
    if (ry + ro.offsetHeight > window.innerHeight - 8) ry = cy - ro.offsetHeight - 12;
    ro.style.left = rx + "px";
    ro.style.top = ry + "px";
  }

  function closeSounding() {
    sndReqToken++;
    hideSndHover();
    curSnd = { levels: null, geom: null };
    closeZoom();
    const panel = $("sndpanel");
    panel.classList.remove("open");
    panel.setAttribute("aria-hidden", "true");
  }

  // ---- zoom lightbox ------------------------------------------------------
  let zScale = 1, zTx = 0, zTy = 0, zMin = 0.2, zMax = 12;
  let zDrag = false, zPx = 0, zPy = 0, zSx = 0, zSy = 0, zMoved = false;

  function zApply() {
    $("zoom-img").style.transform = `translate(${zTx}px, ${zTy}px) scale(${zScale})`;
  }
  function zFit() {
    const zi = $("zoom-img");
    const w = window.innerWidth, h = window.innerHeight;
    const nw = zi.naturalWidth || 1290, nh = zi.naturalHeight || 1500;
    zScale = Math.min(w / nw, h / nh) * 0.92;
    zMin = zScale * 0.5; zMax = zScale * 12;
    zTx = (w - nw * zScale) / 2;
    zTy = (h - nh * zScale) / 2;
    zApply();
  }
  function zoomAround(cx, cy, factor) {
    const ns = Math.min(zMax, Math.max(zMin, zScale * factor));
    zTx = cx - (cx - zTx) * (ns / zScale);
    zTy = cy - (cy - zTy) * (ns / zScale);
    zScale = ns; zApply();
  }
  function openZoom(imgEl) {
    const img = (imgEl && imgEl.tagName === "IMG") ? imgEl : $("snd-img");
    const src = img.getAttribute("src");
    if (!src || img.style.display === "none") return;
    $("zoom-tail").textContent = $("snd-tail").textContent;
    $("zoom-where").textContent = $("snd-where").textContent;
    const overlay = $("sndzoom");
    overlay.classList.add("open");
    overlay.setAttribute("aria-hidden", "false");
    const zi = $("zoom-img");
    if (zi.getAttribute("src") === src && zi.complete && zi.naturalWidth) {
      zFit();
    } else {
      zi.onload = zFit;
      zi.src = src;
    }
  }
  function closeZoom() {
    const o = $("sndzoom");
    o.classList.remove("open");
    o.setAttribute("aria-hidden", "true");
  }

  // ---- legend -------------------------------------------------------------
  function buildLegend() {
    const seg = SPEED_BINS.map((b, i) => {
      const lower = i === 0 ? 0 : SPEED_BINS[i - 1][0];
      const label = b[0] === 9999 ? "90+" : String(lower);
      return `<div class="seg"><div class="bar" style="background:${b[1]}"></div><div class="num">${label}</div></div>`;
    }).join("");
    $("legend-scale").innerHTML = seg;
  }

  // ---- data load + status -------------------------------------------------
  let curHours = 3;
  let curArchive = false;
  function updateReadout(d, pts) {
    $("r-source").textContent = d.source || "—";
    $("r-source").classList.toggle("live", /live/i.test(d.source || ""));
    $("r-source").classList.toggle("archive", !!d.archive);
    $("r-updated").textContent = (d.generated_at || "").slice(11) || "—";
    const nTracks = typeof d.tracks === "number"
      ? d.tracks
      : (Array.isArray(d.tracks) ? d.tracks.length : allTracks.length);
    $("r-tracks").textContent = nTracks;
    if (pts != null) $("r-points").textContent = Number(pts).toLocaleString();
    const nSnd = typeof d.soundings === "number"
      ? d.soundings
      : (Array.isArray(d.profiles) ? d.profiles.length : profileMetas.length);
    $("r-snd").textContent = nSnd;
    if (d.hours && document.activeElement !== $("sel-hours")) {
      $("sel-hours").value = String(d.hours);
    }
    if (d.refresh != null && document.activeElement !== $("sel-auto")) {
      const want = d.auto ? String(d.refresh) : "0";
      const sa = $("sel-auto");
      if ([].some.call(sa.options, (o) => o.value === want)) sa.value = want;
    }
    $("hint-window").textContent = d.hours || 6;
    curHours = d.hours || curHours;
    curArchive = !!d.archive;
    // archive controls
    $("btn-live").style.display = d.archive ? "" : "none";
    const di = $("arc-date");
    if (d.archive && d.archive_date && document.activeElement !== di) di.value = d.archive_date;
  }

  function loadTracks() {
    fetch("/api/tracks")
      .then((r) => r.json())
      .then((d) => {
        allTracks = d.tracks || [];
        buildProfileIndex(d.profiles);
        buildObs();
        drawTracks();
        renderDots();
        renderBarbs();
        renderEdr();
        renderSoundMarkers();
        if (pirepsOn) loadPireps();
        refreshHighlight();
        updateReadout(d, allObs.length);
        lastVersion = d.version;
        $("loading").classList.add("hidden");
      })
      .catch(() => {
        $("loading").innerHTML = '<div style="color:#e74c3c">Could not load data. Is the server running?</div>';
      });
  }

  function pollStatus() {
    fetch("/api/status")
      .then((r) => r.json())
      .then((s) => {
        updateReadout(s, s.points);
        if (lastVersion !== null && s.version !== lastVersion) {
          loadTracks();
          toast("Data updated");
        }
      })
      .catch(() => {});
  }

  // ---- controls -----------------------------------------------------------
  $("btn-barbs").addEventListener("click", () => {
    barbsOn = !barbsOn;
    $("btn-barbs").classList.toggle("on", barbsOn);
    $("legend").classList.toggle("show", barbsOn);
    renderBarbs();
  });

  $("btn-edr").addEventListener("click", () => {
    edrOn = !edrOn;
    $("btn-edr").classList.toggle("on", edrOn);
    updateEdrLegend();
    renderEdr();
    if (edrOn) {
      const any = allObs.some((o) => o.edr != null);
      toast(any ? "Turbulence (EDR) on · larger dot = stronger"
                : "Turbulence on — but no aircraft in this window reported EDR");
    }
  });

  $("btn-snd").addEventListener("click", () => {
    soundOn = !soundOn;
    $("btn-snd").classList.toggle("on", soundOn);
    renderSoundMarkers();
    if (!soundOn) closeSounding();
  });

  $("btn-tracks").addEventListener("click", () => {
    tracksOn = !tracksOn;
    $("btn-tracks").classList.toggle("on", tracksOn);
    drawTracks();
  });

  $("btn-pirep").addEventListener("click", () => {
    pirepsOn = !pirepsOn;
    $("btn-pirep").classList.toggle("on", pirepsOn);
    updatePirepLegend();
    if (pirepsOn) {
      if (pirepData) drawPireps(); else loadPireps();
    } else {
      pirepLayer.clearLayers();
    }
  });

  $("btn-raob").addEventListener("click", () => {
    raobOn = !raobOn;
    $("btn-raob").classList.toggle("on", raobOn);
    if (raobOn) {
      if (raobStations) drawRaobMarkers(); else loadRaobMarkers();
      toast("Radiosonde stations on · click a balloon to view its sounding");
    } else {
      raobLayer.clearLayers();
    }
  });

  // ---- Recent-soundings comparison viewer ---------------------------------
  let cmpLoaded = false, cmpTok = 0;
  let cmpMeta = {};       // ref -> {lat, lon, time}
  let cmpChipEls = {};    // ref (or "hrrr") -> chip element
  let cmpSel = [];        // ordered selected refs (may include "hrrr")

  function _escc(s) { const d = document.createElement("div"); d.textContent = s == null ? "" : s; return d.innerHTML; }

  function openCompare() {
    $("cmp-modal").style.display = "grid";
    if (!cmpLoaded) loadCompareList();
  }
  function closeCompare() { $("cmp-modal").style.display = "none"; }

  function _cmpChip(ref, label, sub, group) {
    const el = document.createElement("div");
    el.className = "cmp-chip";
    el.innerHTML = `<span class="chlabel">${_escc(label)}</span>` +
      (sub ? `<span class="chsub">${_escc(sub)}</span>` : "");
    el.addEventListener("click", (e) => toggleCmp(ref, e.shiftKey));
    cmpChipEls[ref] = el;
    $(group).appendChild(el);
  }

  function loadCompareList() {
    fetch("/api/recent_soundings").then((r) => r.json()).then((d) => {
      cmpLoaded = true;
      $("cmp-amdar").innerHTML = ""; $("cmp-raob").innerHTML = ""; $("cmp-hrrr").innerHTML = "";
      cmpChipEls = {}; cmpMeta = {};
      (d.amdar || []).forEach((m) => {
        cmpMeta[m.ref] = { lat: m.lat, lon: m.lon, time: m.time };
        _cmpChip(m.ref, m.label, m.sub, "cmp-amdar");
      });
      (d.raob || []).forEach((m) => {
        cmpMeta[m.ref] = { lat: m.lat, lon: m.lon, time: null };
        _cmpChip(m.ref, m.label, m.sub, "cmp-raob");
      });
      _cmpChip("hrrr", "HRRR", "at anchor", "cmp-hrrr");
      if (!(d.amdar || []).length)
        $("cmp-empty").innerHTML = "No AMDAR soundings are loaded yet.<br>Load data (or a busier archive date), then reopen this.";
    }).catch(() => toast("Could not load the recent-soundings list"));
  }

  function toggleCmp(ref, shift) {
    if (shift) {
      const i = cmpSel.indexOf(ref);
      if (i >= 0) cmpSel.splice(i, 1); else cmpSel.push(ref);
    } else {
      cmpSel = (cmpSel.length === 1 && cmpSel[0] === ref) ? [] : [ref];
    }
    for (const k in cmpChipEls) cmpChipEls[k].classList.toggle("sel", cmpSel.includes(k));
    renderCompare();
  }

  function _resolveCmpRefs() {
    const anchor = cmpSel.find((r) => r !== "hrrr");
    const out = [];
    for (const r of cmpSel) {
      if (r !== "hrrr") { out.push(r); continue; }
      if (!anchor) continue;
      const m = cmpMeta[anchor];
      if (!m || m.lat == null) continue;
      const t = m.time || Math.floor(Date.now() / 1000);
      out.push("hrrr:" + m.lat + ":" + m.lon + ":" + Math.round(t));
    }
    return out;
  }

  function renderCompare() {
    if (cmpSel.includes("hrrr") && !cmpSel.find((r) => r !== "hrrr"))
      toast("Pick an AMDAR or radiosonde first — HRRR matches that location");
    const refs = _resolveCmpRefs();
    if (!refs.length) {
      $("cmp-img").style.display = "none";
      $("cmp-empty").style.display = "";
      for (const k in cmpChipEls) cmpChipEls[k].style.removeProperty("--chipcolor");
      return;
    }
    $("cmp-empty").style.display = "none";
    $("cmp-loading").style.display = "grid";
    const token = ++cmpTok;
    fetch("/api/compare?refs=" + encodeURIComponent(refs.join(","))).then((r) => r.json()).then((d) => {
      if (token !== cmpTok) return;
      $("cmp-loading").style.display = "none";
      if (d.error) { toast(d.error); return; }
      const img = $("cmp-img");
      img.onload = () => { if (token === cmpTok) img.style.display = ""; };
      img.src = d.png;
      for (const k in cmpChipEls) cmpChipEls[k].style.removeProperty("--chipcolor");
      (d.members || []).forEach((mem) => {
        const chipRef = (mem.id || "").startsWith("hrrr:") ? "hrrr" : mem.id;
        const el = cmpChipEls[chipRef];
        if (el) { el.style.setProperty("--chipcolor", mem.color); el.classList.add("sel"); }
      });
      if ((d.missed || []).length) toast((d.missed.length) + " selected sounding(s) had no data");
    }).catch(() => {
      if (token === cmpTok) { $("cmp-loading").style.display = "none"; toast("Comparison failed to render"); }
    });
  }

  $("btn-recent").addEventListener("click", openCompare);
  $("cmp-close").addEventListener("click", closeCompare);
  $("cmp-modal").addEventListener("click", (e) => { if (e.target === $("cmp-modal")) closeCompare(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && $("cmp-modal").style.display !== "none") closeCompare();
  });

  $("btn-refresh").addEventListener("click", () => {
    const btn = $("btn-refresh");
    btn.classList.add("spin");
    fetch("/api/refresh", { method: "POST" })
      .then((r) => r.json())
      .then((s) => { loadTracks(); toast("Data refreshed"); })
      .finally(() => setTimeout(() => btn.classList.remove("spin"), 600));
  });

  $("sel-auto").addEventListener("change", () => {
    const secs = +$("sel-auto").value;
    fetch("/api/autorefresh?seconds=" + secs, { method: "POST" })
      .then((r) => r.json())
      .then(() => toast(secs > 0
        ? "Auto-update on · every " + Math.round(secs / 60) + " min"
        : "Auto-update off"))
      .catch(() => toast("Could not change auto-update"));
  });

  // ---- archive (historical dates) ----------------------------------------
  function setArcBusy(busy) {
    $("btn-arc").disabled = busy;
    $("btn-live").disabled = busy;
    $("btn-refresh").disabled = busy;
    $("btn-arc").textContent = busy ? "Loading…" : "Load date";
  }

  function showLoading(msg, sub) {
    $("loading-msg").textContent = msg || "Loading…";
    $("loading-sub").textContent = sub || "";
    $("loading").classList.remove("hidden");
  }
  function setLoadingSub(text) { $("loading-sub").textContent = text || ""; }
  function hideLoading() { $("loading").classList.add("hidden"); }

  // Run a /api/load with a prominent overlay that shows the server's current phase
  // and elapsed seconds (the server does the slow part — MADIS download + decode).
  function runLoad(qs, headline) {
    setArcBusy(true);
    $("sel-hours").disabled = true;
    showLoading(headline, "Contacting MADIS…");
    const t0 = Date.now();
    const poll = setInterval(() => {
      const el = Math.round((Date.now() - t0) / 1000);
      fetch("/api/status").then((r) => r.json()).then((s) => {
        setLoadingSub((s.phase || "Working…") + "\n" + el +
          " s elapsed  ·  busy archive days can take a minute or two");
      }).catch(() => setLoadingSub(el + " s elapsed"));
    }, 1000);
    return fetch("/api/load?" + qs, { method: "POST" })
      .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then((s) => {
        clearInterval(poll);
        setLoadingSub("Drawing the map…");
        loadTracks();                         // hides the overlay once the map is populated
        return s;
      })
      .catch((e) => { clearInterval(poll); hideLoading(); toast("Load failed (" + e.message + ")"); throw e; })
      .finally(() => { setArcBusy(false); $("sel-hours").disabled = false; });
  }

  function loadArchive() {
    const date = $("arc-date").value;            // YYYY-MM-DD
    if (!date) { toast("Pick a date first"); return; }
    const hour = $("arc-hour").value;            // "" or 0-23
    const hrs = curHours || 3;
    const qs = "date=" + encodeURIComponent(date) +
               (hour !== "" ? "&hour=" + encodeURIComponent(hour) : "") + "&hours=" + hrs;
    runLoad(qs, "Loading archive — " + date + (hour !== "" ? " " + hour + "Z" : "") + "  ·  " + hrs + " h")
      .then((s) => {
        if ((s.tracks || 0) === 0 && (s.soundings || 0) === 0) {
          hideLoading();
          toast("No archive data found for that date/time");
        } else {
          toast("Loaded archive: " + (s.archive_date || date));
        }
      })
      .catch(() => {});
  }

  function goLive() {
    setArcBusy(true);
    fetch("/api/load?date=live", { method: "POST" })
      .then((r) => r.json())
      .then((s) => { loadTracks(); toast("Back to live data"); })
      .catch(() => {})
      .finally(() => setArcBusy(false));
  }

  function applyHours() {
    curHours = +$("sel-hours").value || 3;
    const inArchive = curArchive && $("arc-date").value;
    let qs, headline;
    if (inArchive) {
      const hour = $("arc-hour").value;
      qs = "date=" + encodeURIComponent($("arc-date").value) +
           (hour !== "" ? "&hour=" + encodeURIComponent(hour) : "") +
           "&hours=" + curHours;
      headline = "Loading " + curHours + " h — archive " + $("arc-date").value;
    } else {
      qs = "date=live&hours=" + curHours;
      headline = "Loading the last " + curHours + " h (live)";
    }
    runLoad(qs, headline)
      .then((s) => {
        toast("Showing the last " + (s.hours || curHours) + " h" + (inArchive ? " (archive)" : ""));
      })
      .catch(() => {});
  }
  $("sel-hours").addEventListener("change", applyHours);

  $("btn-arc").addEventListener("click", loadArchive);
  $("btn-find").addEventListener("click", () => findAircraft($("find-id").value));
  $("find-id").addEventListener("keydown", (e) => { if (e.key === "Enter") findAircraft($("find-id").value); });
  $("btn-find-clear").addEventListener("click", () => { $("find-id").value = ""; clearHighlight(); });
  $("btn-live").addEventListener("click", goLive);
  $("arc-date").addEventListener("keydown", (e) => { if (e.key === "Enter") loadArchive(); });
  $("arc-hour").addEventListener("keydown", (e) => { if (e.key === "Enter") loadArchive(); });
  // clamp the archive picker: no future dates, and offer up to 10 years back
  (function () {
    const t = new Date();
    const local = new Date(t.getTime() - t.getTimezoneOffset() * 60000);
    $("arc-date").max = local.toISOString().slice(0, 10);
    const floor = new Date(local);
    floor.setFullYear(floor.getFullYear() - 10);
    $("arc-date").min = floor.toISOString().slice(0, 10);
  })();

  $("snd-close").addEventListener("click", closeSounding);
  $("snd-img").addEventListener("click", openZoom);
  $("snd-img").addEventListener("mousemove", sndHoverMove);
  $("snd-img").addEventListener("mouseleave", hideSndHover);

  $("snd-hrrr").addEventListener("click", () => {
    const id = hrrrTargetId;
    if (!id) return;
    const btn = $("snd-hrrr");
    btn.disabled = true; btn.textContent = "HRRR…";
    const token = ++sndReqToken;
    $("snd-loading").style.display = "";
    $("snd-img").style.display = "none";
    $("snd-hodo").style.display = "none"; $("snd-hodo").removeAttribute("src");
    fetch(`/api/hrrr_sounding?id=${encodeURIComponent(id)}`)
      .then((r) => r.json())
      .then((d) => {
        btn.disabled = false; btn.textContent = "＋ HRRR";
        if (token !== sndReqToken || hrrrTargetId !== id) return;   // user moved on
        $("snd-loading").style.display = "none";
        if (d.error) {
          $("snd-img").style.display = "";
          toast(d.error);
          return;
        }
        const img = $("snd-img");
        img.onload = () => { if (token === sndReqToken) { $("snd-loading").style.display = "none"; img.style.display = ""; } };
        img.src = d.png;
        const cape = (d.analysis && d.analysis.sb_cape != null) ? d.analysis.sb_cape + " J/kg" : "—";
        const model = d.model || "HRRR";
        $("snd-foot").innerHTML =
          `<span style="color:#f0c419">aircraft</span> vs <span style="color:#5dade2">${model}</span> · ` +
          `valid ${d.valid || "—"} · model SBCAPE <b>${cape}</b> · ` +
          `${d.nlev || "?"} levels · source: ${d.source || "Open-Meteo"} · solid = T, dashed = Td`;
        toast(model + " forecast overlaid");
      })
      .catch(() => {
        btn.disabled = false; btn.textContent = "＋ HRRR";
        if (token === sndReqToken) $("snd-loading").style.display = "none";
        toast("HRRR unavailable");
      });
  });
  $("snd-hodo").addEventListener("click", () => openZoom($("snd-hodo")));
  $("snd-expand").addEventListener("click", openZoom);
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if ($("sndzoom").classList.contains("open")) closeZoom(); else closeSounding();
  });

  // zoom lightbox interactions
  (function () {
    const wrap = $("zoom-wrap");
    wrap.addEventListener("wheel", (e) => {
      e.preventDefault();
      const r = wrap.getBoundingClientRect();
      zoomAround(e.clientX - r.left, e.clientY - r.top, e.deltaY < 0 ? 1.15 : 1 / 1.15);
    }, { passive: false });
    wrap.addEventListener("pointerdown", (e) => {
      zDrag = true; zMoved = false;
      zPx = zSx = e.clientX; zPy = zSy = e.clientY;
      wrap.classList.add("grabbing");
      try { wrap.setPointerCapture(e.pointerId); } catch (_) {}
    });
    wrap.addEventListener("pointermove", (e) => {
      if (!zDrag) return;
      zTx += e.clientX - zPx; zTy += e.clientY - zPy;
      zPx = e.clientX; zPy = e.clientY;
      if (Math.abs(e.clientX - zSx) + Math.abs(e.clientY - zSy) > 4) zMoved = true;
      zApply();
    });
    function endDrag(e) {
      if (!zDrag) return;
      zDrag = false; wrap.classList.remove("grabbing");
      try { wrap.releasePointerCapture(e.pointerId); } catch (_) {}
      if (!zMoved && e.target === wrap) closeZoom();   // click empty area to close
    }
    wrap.addEventListener("pointerup", endDrag);
    wrap.addEventListener("pointercancel", () => { zDrag = false; wrap.classList.remove("grabbing"); });
    wrap.addEventListener("dblclick", zFit);
    $("zoom-in").addEventListener("click", () => zoomAround(innerWidth / 2, innerHeight / 2, 1.3));
    $("zoom-out").addEventListener("click", () => zoomAround(innerWidth / 2, innerHeight / 2, 1 / 1.3));
    $("zoom-reset").addEventListener("click", zFit);
    $("zoom-close").addEventListener("click", closeZoom);
    window.addEventListener("resize", () => { if ($("sndzoom").classList.contains("open")) zFit(); });
  })();

  // ---- toast --------------------------------------------------------------
  let toastTimer;
  function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 2200);
  }

  // ---- events -------------------------------------------------------------
  // altitude filter slider
  const altMinEl = $("altf-min"), altMaxEl = $("altf-max");
  const altFillEl = $("altf-fill"), altValEl = $("altf-val");
  const altSliderEl = altMinEl.parentElement;
  const fmtFt = (ft) => (ft === 0 ? "Surface" : ft.toLocaleString() + " ft");

  function updateAltUI() {
    const W = altSliderEl.clientWidth || 186, TH = 15;
    const frac = (v) => (v - ALT_FLOOR) / (ALT_CEIL - ALT_FLOOR);
    const cx = (v) => TH / 2 + frac(v) * (W - TH);
    altFillEl.style.left = cx(altMinFt) + "px";
    altFillEl.style.width = Math.max(0, cx(altMaxFt) - cx(altMinFt)) + "px";
    altValEl.textContent = fmtFt(altMinFt) + " – " +
      (altMaxFt >= ALT_CEIL ? "45,000 ft+" : fmtFt(altMaxFt));
    altValEl.classList.toggle("on", altFiltered());
    // keep both thumbs reachable when they bunch up near one end
    const minHigh = altMinFt > (ALT_FLOOR + ALT_CEIL) / 2;
    altMinEl.style.zIndex = minHigh ? 5 : 4;
    altMaxEl.style.zIndex = minHigh ? 4 : 5;
  }

  let altTimer = null;
  function applyAltFilter() {
    clearTimeout(altTimer);
    altTimer = setTimeout(() => { drawTracks(); renderDots(); renderBarbs(); renderEdr(); }, 60);
  }
  function onAltInput(e) {
    let lo = +altMinEl.value, hi = +altMaxEl.value;
    if (e.target === altMinEl && lo > hi - ALT_GAP) { lo = hi - ALT_GAP; altMinEl.value = lo; }
    if (e.target === altMaxEl && hi < lo + ALT_GAP) { hi = lo + ALT_GAP; altMaxEl.value = hi; }
    altMinFt = lo; altMaxFt = hi;
    updateAltUI(); applyAltFilter();
  }
  altMinEl.addEventListener("input", onAltInput);
  altMaxEl.addEventListener("input", onAltInput);
  $("altf-reset").addEventListener("click", () => {
    altMinFt = ALT_FLOOR; altMaxFt = ALT_CEIL;
    altMinEl.value = ALT_FLOOR; altMaxEl.value = ALT_CEIL;
    updateAltUI(); applyAltFilter();
  });

  // wind speed filter slider
  const wsMinEl = $("wsf-min"), wsMaxEl = $("wsf-max");
  const wsFillEl = $("wsf-fill"), wsValEl = $("wsf-val");
  const wsSliderEl = wsMinEl.parentElement;

  function updateWsUI() {
    const W = wsSliderEl.clientWidth || 186, TH = 15;
    const frac = (v) => (v - WS_FLOOR) / (WS_CEIL - WS_FLOOR);
    const cx = (v) => TH / 2 + frac(v) * (W - TH);
    wsFillEl.style.left = cx(wsMin) + "px";
    wsFillEl.style.width = Math.max(0, cx(wsMax) - cx(wsMin)) + "px";
    wsValEl.textContent = wsMin + " – " + (wsMax >= WS_CEIL ? "200 kt+" : wsMax + " kt");
    wsValEl.classList.toggle("on", wsFiltered());
    const minHigh = wsMin > (WS_FLOOR + WS_CEIL) / 2;
    wsMinEl.style.zIndex = minHigh ? 5 : 4;
    wsMaxEl.style.zIndex = minHigh ? 4 : 5;
  }

  let wsTimer = null;
  function applyWsFilter() {
    clearTimeout(wsTimer);
    wsTimer = setTimeout(() => { renderDots(); renderBarbs(); }, 60);
  }
  function onWsInput(e) {
    let lo = +wsMinEl.value, hi = +wsMaxEl.value;
    if (e.target === wsMinEl && lo > hi - WS_GAP) { lo = hi - WS_GAP; wsMinEl.value = lo; }
    if (e.target === wsMaxEl && hi < lo + WS_GAP) { hi = lo + WS_GAP; wsMaxEl.value = hi; }
    wsMin = lo; wsMax = hi;
    updateWsUI(); applyWsFilter();
  }
  wsMinEl.addEventListener("input", onWsInput);
  wsMaxEl.addEventListener("input", onWsInput);
  $("wsf-reset").addEventListener("click", () => {
    wsMin = WS_FLOOR; wsMax = WS_CEIL;
    wsMinEl.value = WS_FLOOR; wsMaxEl.value = WS_CEIL;
    updateWsUI(); applyWsFilter();
  });

  // data density slider (single handle)
  const densEl = $("dens-range"), densFillEl = $("dens-fill"), densValEl = $("dens-val");
  const densSliderEl = densEl.parentElement;
  function densLabel(d) {
    if (d >= 92) return "All data";
    if (d >= 72) return "Dense";
    if (d >= 45) return "Balanced";
    if (d >= 22) return "Sparse";
    return "Very sparse";
  }
  function updateDensUI() {
    const W = densSliderEl.clientWidth || 186, TH = 15;
    densFillEl.style.left = "0px";
    densFillEl.style.width = (TH / 2 + (density / 100) * (W - TH)) + "px";
    densValEl.textContent = densLabel(density);
  }
  let densTimer = null;
  function applyDensity() {
    clearTimeout(densTimer);
    densTimer = setTimeout(() => { renderDots(); renderBarbs(); renderEdr(); }, 60);
  }
  densEl.addEventListener("input", () => { density = +densEl.value; updateDensUI(); applyDensity(); });

  let moveTimer = null;
  map.on("moveend zoomend", () => {
    clearTimeout(moveTimer);
    moveTimer = setTimeout(() => {
      drawTracks();
      renderDots();
      renderBarbs();
      renderEdr();
    }, 180);
  });

  // ---- boot ---------------------------------------------------------------
  buildLegend();
  updateAltUI();
  updateWsUI();
  updateDensUI();
  loadTracks();
  pollStatus();
  setInterval(pollStatus, 15000);
})();
