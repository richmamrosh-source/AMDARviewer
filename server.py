#!/usr/bin/env python3
"""
server.py — Local web server for the ACARS flight-track + wind-barb map with
clickable aircraft soundings.

Run:
    pip install -r requirements.txt
    python server.py                 # live: tracks + soundings from MADIS
    python server.py --demo          # synthetic demo data (no network)
    python server.py --hours 6 --port 5001

Then open http://localhost:5001 .

Tracks come from the ACARS en-route feed; soundings (clickable) come from the
ACARS profiles feed and are plotted as Skew-T/Log-P diagrams with pyMeteo.
"""

import argparse
import base64
import json
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from threading import Timer

from flask import Flask, jsonify, request, send_from_directory, abort

from paths import app_dir, cache_root
import analysis
import demo
import hrrr
import pireps
import places
import raob
import metars
import raob_stations
import sounding_plot
import vendor_leaflet

try:
    import acars
    _HAVE_ACARS = True
except Exception:
    _HAVE_ACARS = False
try:
    import profiles
    _HAVE_PROFILES = True
except Exception:
    _HAVE_PROFILES = False

STATIC_DIR = os.path.join(app_dir(), "static")
app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
# This is a local tool that people re-download/replace in place. Never let the
# browser serve a stale app.js/style.css/index.html from cache, or a new build
# looks broken until a hard refresh.
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


@app.after_request
def _no_cache(resp):
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp

SND_DIR = os.path.join(cache_root(), "soundings")
os.makedirs(SND_DIR, exist_ok=True)

_state = {
    "tracks": [], "generated_at": None, "source": "starting", "version": 0,
    "soundings": [], "sound_by_id": {}, "sound_meta": [], "snd_source": "—",
    "phase": "",
}
_lock = threading.Lock()
_cfg = {"hours": 6, "demo": False, "demo_start": False, "max_tracks": None,
        "refresh": 900, "auto": True, "archive": False, "end_time": None}
_png_cache = {}
_raob_cache = {}        # "RAOB:wmo" -> (time_key, png, renderer, info, an, hodo)


def _arc_label():
    et = _cfg["end_time"]
    return f"MADIS archive {et:%Y-%m-%d %H:%MZ}" if et else "MADIS archive"


def _load_tracks():
    if _cfg["archive"] and _HAVE_ACARS:
        et = _cfg["end_time"] or datetime.now(timezone.utc)
        try:
            tracks, gen = acars.fetch(_cfg["hours"], _cfg["max_tracks"],
                                      end_time=et, archive=True)
            if tracks:
                return tracks, gen, _arc_label()
            print("[tracks] archive returned no tracks for that date/time.")
            return [], et, _arc_label() + " — no data"
        except Exception as e:
            print(f"[tracks] archive unavailable ({e}).")
            return [], et, _arc_label() + " — unavailable"
    if not _cfg["demo"] and _HAVE_ACARS:
        try:
            tracks, gen = acars.fetch(_cfg["hours"], _cfg["max_tracks"])
            if tracks:
                return tracks, gen, "MADIS live"
            print("[tracks] MADIS returned no tracks; using demo data.")
        except Exception as e:
            print(f"[tracks] MADIS unavailable ({e}); using demo data.")
    tracks, gen = demo.generate(hours=_cfg["hours"])
    return tracks, gen, "demo (synthetic)"


def _load_soundings(tracks):
    if _cfg["archive"] and _HAVE_PROFILES:
        et = _cfg["end_time"] or datetime.now(timezone.utc)
        try:
            snd, _ = profiles.fetch(_cfg["hours"], end_time=et, archive=True)
            if snd:
                return snd, _arc_label()
            print("[soundings] archive profiles returned none for that date/time.")
            return [], _arc_label() + " — no data"
        except Exception as e:
            print(f"[soundings] archive profiles unavailable ({e}).")
            return [], _arc_label() + " — unavailable"
    if not _cfg["demo"] and _HAVE_PROFILES:
        try:
            snd, _ = profiles.fetch(_cfg["hours"])
            if snd:
                return snd, "MADIS live"
            print("[soundings] MADIS profiles returned none; using demo soundings.")
        except Exception as e:
            print(f"[soundings] MADIS profiles unavailable ({e}); using demo soundings.")
    return demo.generate_profiles(tracks), "demo (synthetic)"


def _set_phase(msg):
    with _lock:
        _state["phase"] = msg


# --------------------------------------------------------------------------- #
#  Faulty-moisture-sensor detection (the level-3 check MADIS doesn't do)        #
# --------------------------------------------------------------------------- #
# MADIS takes dewpoint only to QC level 2 — validity and internal consistency.
# Level 3 (temporal/spatial "buddy" checks) is never applied to moisture. So an
# airframe whose humidity sensor is stuck dry reports dewpoints that are
# individually in-range and internally consistent (Td < T) and sail straight
# through. The fix is to do the missing check ourselves: compare each aircraft's
# boundary-layer moisture against the OTHER aircraft sounding the same airport at
# nearly the same time. One dry sounding can be weather; being the driest
# aircraft at every airport, day after day, is a broken sensor.
MOIST_EXCESS_K = 12.0        # drier than the peer median by this much => suspect
METAR_DRY_K = 10.0           # drier than the airport's own METAR => suspect
HRRR_DRY_K = 12.0            # drier than the model by this much => suspect
HRRR_MAX_CHECKS = 12         # model checks per load (each is a network call)
METAR_MAX_AGL = 600.0        # only compare aircraft obs this close to the ground
# MADIS QC levels 1-2 are per-observation checks. A couple of flagged obs on a
# 50-level profile is normal noise and means nothing about the sounding overall,
# so only surface it when at least this share of the profile is affected.
QC_NOTE_MIN_FRAC = 0.20
MOIST_MIN_PEERS = 2          # need at least this many peers to judge
MOIST_LEDGER = os.path.join(cache_root(), "moisture_tails.json")


def _bl_dpd(s):
    """Median boundary-layer dewpoint depression (K) over the lowest 100 hPa.
    None when the aircraft reported no usable moisture."""
    lv = [l for l in (s.get("levels") or [])
          if l.get("T") is not None and l.get("Td") is not None and l.get("p")]
    if len(lv) < 2:
        return None
    p_sfc = max(l["p"] for l in lv)
    near = [l for l in lv if l["p"] >= p_sfc - 10000.0]      # lowest 100 hPa
    if len(near) < 2:
        return None
    d = sorted(l["T"] - l["Td"] for l in near)
    return d[len(d) // 2]


def _sfc_ob(s):
    """The aircraft's lowest level that reports moisture."""
    lv = [l for l in (s.get("levels") or [])
          if l.get("T") is not None and l.get("Td") is not None and l.get("p")]
    return max(lv, key=lambda l: l["p"]) if lv else None


def _ledger_load():
    try:
        with open(MOIST_LEDGER, encoding="utf-8") as fh:
            d = json.load(fh)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _ledger_save(d):
    try:
        with open(MOIST_LEDGER, "w", encoding="utf-8") as fh:
            json.dump(d, fh)
    except OSError:
        pass


def _metar_verdicts(soundings, stations):
    """Compare each aircraft's near-surface dewpoint against the airport's own
    METAR — ground truth, available hourly at every airport. Returns
    {sounding id: verdict}. This is the primary test: it needs no peer aircraft,
    which matters because only two US fleets carry the WVSS-II moisture sensor."""
    out = {}
    if not stations:
        return out
    for s in soundings:
        ob = _sfc_ob(s)
        if not ob or ob.get("z") is None:
            continue
        st = metars.nearest(stations, s.get("lat"), s.get("lon"), max_km=30.0)
        if not st:
            continue
        agl = ob["z"] - st["elev"]
        if not (-150.0 <= agl <= METAR_MAX_AGL):     # must actually be near the ground
            continue
        if s.get("time") and st.get("time") and abs(s["time"] - st["time"]) > 5400:
            continue                                  # METARs are hourly; stay within 90 min
        td_ac = ob["Td"] - 273.15
        out[s["id"]] = {
            "excess": float(st["td"] - td_ac),        # + => aircraft drier than reality
            "thresh": METAR_DRY_K,
            "src": "the METAR at " + (st["icao"] or st["name"] or "the airport"),
            "ref_td": round(st["td"], 1), "ac_td": round(td_ac, 1),
            "agl": int(agl),
        }
    return out


def _hrrr_moisture_gap(s, hs):
    """Median (model Td − aircraft Td) over the aircraft's lowest moisture levels,
    matched level-by-level in pressure. Positive => the aircraft is drier."""
    ac = [l for l in (s.get("levels") or []) if l.get("Td") is not None and l.get("p")]
    hl = [l for l in (hs.get("levels") or []) if l.get("Td") is not None and l.get("p")]
    if not ac or not hl:
        return None
    ac.sort(key=lambda l: -l["p"])
    diffs = []
    for l in ac[:6]:                                   # the lowest few levels
        m = min(hl, key=lambda x: abs(x["p"] - l["p"]))
        if abs(m["p"] - l["p"]) <= 5000.0:             # within 50 hPa
            diffs.append(m["Td"] - l["Td"])
    if len(diffs) < 2:
        return None
    diffs.sort()
    return diffs[len(diffs) // 2]                      # median: robust to one odd level


def _hrrr_verdicts(soundings, skip, ledger, session=None):
    """Compare the aircraft's low-level dewpoint against the HRRR/GFS model.

    This is the check a user could run by hand with the "+HRRR" button, done
    automatically. It covers what METARs can't: archive dates, airports with no
    surface ob, and profiles that never reach the ground (the model can be matched
    at any level). The model isn't truth and carries its own moisture bias, but a
    stuck-dry sensor misses by 30–50 °C, which dwarfs any model error — so only a
    wide margin is treated as a verdict.

    Each check is a network call, so only a few of the least-known tails are done
    per load; over a few loads every airframe still gets characterised.
    """
    out = {}
    cands = [s for s in soundings
             if s["id"] not in skip and _sfc_ob(s) is not None
             and s.get("lat") is not None and s.get("time")]
    if not cands:
        return out
    # spend the budget on the airframes we know least about
    cands.sort(key=lambda s: ledger.get(s.get("tail") or "?", {}).get("n", 0))
    cands = cands[:HRRR_MAX_CHECKS]
    _set_phase("Checking aircraft moisture sensors against the model…")
    for s in cands:
        try:
            hs = hrrr.fetch_sounding(s["lat"], s["lon"], s["time"], session=session)
        except Exception:
            continue
        gap = _hrrr_moisture_gap(s, hs)
        if gap is None:
            continue
        out[s["id"]] = {"excess": float(gap), "thresh": HRRR_DRY_K,
                        "src": "the %s model" % (hs.get("model") or "HRRR")}
    return out


def _peer_verdicts(soundings, skip):
    """Fallback where no METAR is nearby: compare against other aircraft sounding
    the same airport within +/-3 h."""
    out = {}
    dpd = {}
    for s in soundings:
        if s["id"] in skip:
            continue
        v = _bl_dpd(s)
        if v is not None:
            dpd[s["id"]] = v
    by_apt = {}
    for s in soundings:
        if s["id"] in dpd:
            apt = (s.get("airport") or "").strip().upper()
            if apt:
                by_apt.setdefault(apt, []).append(s)
    for apt, group in by_apt.items():
        for s in group:
            peers = [dpd[o["id"]] for o in group
                     if o["id"] != s["id"] and o.get("tail") != s.get("tail")
                     and o["id"] in dpd
                     and abs((o.get("time") or 0) - (s.get("time") or 0)) <= 3 * 3600]
            if len(peers) < MOIST_MIN_PEERS:
                continue
            peers.sort()
            out[s["id"]] = {
                "excess": float(dpd[s["id"]] - peers[len(peers) // 2]),
                "thresh": MOIST_EXCESS_K,
                "src": "%d other aircraft at %s" % (len(peers), apt),
            }
    return out


def _moisture_check(soundings, session=None):
    """Flag aircraft whose humidity sensor is reporting garbage, and remember the
    offenders across sessions so chronic ones stand out.

    MADIS only QCs dewpoint to level 2 (validity + internal consistency); there's
    no spatial check on moisture, so a stuck-dry sensor never trips it. This does
    the missing check — METAR first (ground truth), peers as a fallback.
    """
    with _lock:
        archive = _cfg["archive"]
    stations = [] if archive else metars.fetch(session=session)
    if not archive and not stations:
        print("[soundings] no surface obs available; judging moisture against the "
              "model and peer aircraft instead")

    verdicts = _metar_verdicts(soundings, stations)
    n_metar = len(verdicts)
    ledger = _ledger_load()
    try:
        verdicts.update(_hrrr_verdicts(soundings, set(verdicts), ledger, session))
    except Exception as e:
        print("[soundings] model moisture check skipped (%s)" % type(e).__name__)
    n_hrrr = len(verdicts) - n_metar
    verdicts.update(_peer_verdicts(soundings, skip=set(verdicts)))

    flagged = 0
    for s in soundings:
        v = verdicts.get(s["id"])
        if not v:
            continue
        tail = s.get("tail") or "?"
        e = ledger.setdefault(tail, {"n": 0, "bad": 0, "sum": 0.0})
        e["n"] += 1
        if v["excess"] >= v["thresh"]:
            e["bad"] += 1
            e["sum"] += v["excess"]
            s["moist_suspect"] = {"excess": round(v["excess"], 1), "src": v["src"],
                                  "ref_td": v.get("ref_td"), "ac_td": v.get("ac_td")}
            flagged += 1

    # Chronic offenders: judged several times and wrong most of them. This is what
    # separates "a dry day" from "this airframe's sensor is broken".
    chronic = {}
    for tail, e in ledger.items():
        if e.get("n", 0) >= 3 and e.get("bad", 0) >= 0.6 * e["n"]:
            chronic[tail] = {"n": e["n"], "bad": e["bad"],
                             "avg": round(e["sum"] / max(1, e["bad"]), 1)}
    for s in soundings:
        c = chronic.get(s.get("tail"))
        if c:
            s.setdefault("moist_suspect", {})["chronic"] = c
    _ledger_save(ledger)

    if verdicts:
        print("[soundings] moisture check: %d judged (%d vs METARs, %d vs model, "
              "%d vs peers), %d suspect"
              % (len(verdicts), n_metar, n_hrrr,
                 len(verdicts) - n_metar - n_hrrr, flagged))
    if chronic:
        print("[soundings] aircraft with a PROBABLE FAULTY HUMIDITY SENSOR:")
        for t, c in sorted(chronic.items(), key=lambda kv: -kv[1]["bad"]):
            print("    %-16s too dry on %d of %d checks, avg %.0f C drier than truth"
                  % (t, c["bad"], c["n"], c["avg"]))


def _augment_soundings(soundings, tracks):
    """The acarsProfiles feed often starts well above the ground. The en-route ACARS
    feed (already downloaded for the tracks) has the same aircraft's climb-out /
    descent reports at the lower levels. Match by tail and merge those lower obs into
    each profile so the sounding reaches nearer the surface. Track point layout:
    [lat, lon, alt_m, temp_C, dew_C, wspd_kt, wdir, epoch, edr]."""
    KT_TO_MS = 0.514444
    by_tail = {}
    for t in tracks:
        by_tail.setdefault(t.get("id"), []).append(t)

    filled = 0
    for s in soundings:
        tail = s.get("tail")
        levels = s.get("levels") or []
        if not tail or len(levels) < 2 or tail not in by_tail:
            continue
        lowest_p = max(l["p"] for l in levels)          # surface-most level we already have
        s_time = s.get("time") or 0
        s_lat, s_lon = s.get("lat"), s.get("lon")

        adds = []
        for t in by_tail[tail]:
            for p in t.get("pts", []):
                alt, tc = p[2], p[3]
                if alt is None or tc is None:
                    continue
                p_pa = 101325.0 * (1.0 - 2.25577e-5 * float(alt)) ** 5.25588
                if p_pa <= lowest_p + 100.0:            # only ADD levels below what we have
                    continue
                ep = p[7]
                if s_time and ep and abs(ep - s_time) > 45 * 60:   # same ascent/descent leg
                    continue
                if s_lat is not None and p[0] is not None and \
                        (abs(p[0] - s_lat) > 2.0 or abs(p[1] - s_lon) > 2.0):
                    continue
                dew, ws_kt, wd = p[4], p[5], p[6]
                adds.append({
                    "p": round(p_pa, 1), "z": round(float(alt), 1),
                    "T": round(tc + 273.15, 2),
                    "Td": (round(dew + 273.15, 2) if dew is not None else None),
                    "wdir": (round(float(wd), 1) if wd is not None else None),
                    "wspd": (round(ws_kt * KT_TO_MS, 2) if ws_kt is not None else None),
                })
        if not adds:
            continue
        # thin the added obs to ~5 hPa spacing so we don't pile up near-duplicates
        adds.sort(key=lambda d: -d["p"])
        buckets = {round(l["p"] / 500.0) for l in levels}
        merged = list(levels)
        for a in adds:
            b = round(a["p"] / 500.0)
            if b in buckets:
                continue
            buckets.add(b)
            merged.append(a)
        if len(merged) > len(levels):
            merged.sort(key=lambda d: -d["p"])
            s["levels"] = merged
            s["filled_low"] = True
            filled += 1
    if filled:
        print("[soundings] extended %d profile(s) to lower levels using en-route ACARS"
              % filled)


def refresh():
    t0 = time.time()
    _set_phase("Contacting MADIS and downloading aircraft data…")
    tracks, gen, source = _load_tracks()
    t1 = time.time()
    pts = sum(len(t["pts"]) for t in tracks)
    _set_phase("Decoded %s tracks / %s points — loading soundings…"
               % (format(len(tracks), ","), format(pts, ",")))
    soundings, snd_source = _load_soundings(tracks)
    t2 = time.time()
    if not _cfg["demo"]:                      # fill profile bottoms from en-route obs
        try:
            _augment_soundings(soundings, tracks)
        except Exception as e:
            print("[soundings] low-level augment skipped (%s)" % type(e).__name__)
        try:
            _moisture_check(soundings)         # catch stuck-dry humidity sensors
        except Exception as e:
            print("[soundings] moisture check skipped (%s)" % type(e).__name__)
    _set_phase("Finishing up…")
    for s in soundings:                      # friendly location from the surface ob
        s["place"] = places.nearest(s.get("lat"), s.get("lon"))
    by_id = {s["id"]: s for s in soundings}
    meta = [{
        "id": s["id"], "tail": s["tail"], "lat": s["lat"], "lon": s["lon"],
        "airport": s.get("airport", ""), "place": s.get("place", ""),
        "updown": s.get("updown", ""),
        "time": s.get("time"), "levels": len(s["levels"]),
        "qc_flagged": ((s.get("qc") or {}).get("flagged") or 0),
        "wvqc": s.get("wvqc"),
    } for s in soundings]
    nflag = sum(1 for m in meta if m["qc_flagged"])
    if nflag:
        print("[soundings] %d of %d soundings have MADIS QC-flagged levels"
              % (nflag, len(meta)))
    # Aircraft whose humidity sensor reported ITSELF faulty. These are the chronic
    # offenders — the same airframes turn up day after day, and their dewpoints
    # should not be trusted even though MADIS's own QC passes them.
    bad_wv = {}
    for s in soundings:
        w = s.get("wvqc")
        if w and w.get("frac", 0) >= 0.5:
            bad_wv.setdefault(s.get("tail"), w.get("meaning"))
    if bad_wv:
        print("[soundings] %d aircraft report a FAULTY moisture sensor "
              "(their dewpoints are unreliable):" % len(bad_wv))
        for t, m in sorted(bad_wv.items()):
            print("    %-16s %s" % (t, m))

    with _lock:
        _state.update(tracks=tracks, generated_at=gen, source=source,
                      soundings=soundings, sound_by_id=by_id, sound_meta=meta,
                      snd_source=snd_source)
        _state["version"] += 1
        _state["phase"] = ""
    _png_cache.clear()
    print(f"[data] {source}: {len(tracks)} tracks / {pts} pts | "
          f"soundings {snd_source}: {len(meta)} | {gen:%H:%M UTC}")
    print("[timing] MADIS aircraft (download+decode): %.1fs | soundings: %.1fs "
          "| server total: %.1fs  (browser render happens after this)"
          % (t1 - t0, t2 - t1, time.time() - t0))


def _loop(stop):
    # check often, but only re-download once the chosen interval has elapsed and
    # auto-update is on (and we're on the live feed, not a static archive)
    last = time.monotonic()
    while not stop.wait(15):
        if not _cfg.get("auto", True) or _cfg["archive"]:
            last = time.monotonic()
            continue
        if time.monotonic() - last >= _cfg["refresh"]:
            try:
                refresh()
            except Exception as e:
                print(f"[data] refresh error: {e}")
            last = time.monotonic()


def _display_levels(snd):
    """Compact levels in display units for the hover readout: pressure hPa, height m,
    T/Td °C, wind dir/kt. Sorted surface-first (highest pressure first)."""
    KT = 0.514444
    out = []
    for l in (snd.get("levels") or []):
        p = l.get("p")
        if p is None:
            continue
        out.append({
            "p": round(p / 100.0, 1),
            "z": (round(l["z"]) if l.get("z") is not None else None),
            "t": (round(l["T"] - 273.15, 1) if l.get("T") is not None else None),
            "td": (round(l["Td"] - 273.15, 1) if l.get("Td") is not None else None),
            "wdir": (round(l["wdir"]) if l.get("wdir") is not None else None),
            "wspd": (round(l["wspd"] / KT) if l.get("wspd") is not None else None),
            "qc": bool(l.get("qc_bad")),
        })
    out.sort(key=lambda d: -d["p"])
    return out


def _render_sounding(sid):
    with _lock:
        s = _state["sound_by_id"].get(sid)
        ver = _state["version"]
    if not s:
        return None
    c = _png_cache.get(sid)
    if c and c[0] == ver:
        return c[1], c[2], c[3], c[4], c[5]
    an = analysis.analyze(s)
    safe = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in sid)
    path = os.path.join(SND_DIR, safe + ".png")
    renderer, info = sounding_plot.make_png(s, path, analysis=an)
    hodo_path = os.path.join(SND_DIR, safe + "_hodo.png")
    try:
        if not sounding_plot.make_hodograph_png(s, hodo_path, analysis=an):
            hodo_path = None
    except Exception:
        hodo_path = None
    _png_cache[sid] = (ver, path, renderer, info, an, hodo_path)
    return path, renderer, info, an, hodo_path


def _render_multi(ids):
    with _lock:
        snds = [_state["sound_by_id"][i] for i in ids if i in _state["sound_by_id"]]
        ver = _state["version"]
        apt = (snds[0].get("place") or snds[0].get("airport", "")) if snds else ""
    if len(snds) < 2:
        return None
    key = "multi:" + ",".join(sorted(s["id"] for s in snds))
    c = _png_cache.get(key)
    if c and c[0] == ver:
        return c[1], c[2], c[3]
    import hashlib
    path = os.path.join(SND_DIR, "multi_" + hashlib.md5(key.encode()).hexdigest()[:16] + ".png")
    renderer, info = sounding_plot.make_png_multi(snds, path, apt)
    _png_cache[key] = (ver, path, renderer, info)
    return path, renderer, info


_LEAFLET_CDN_CSS = ('<link rel="stylesheet" '
                    'href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" '
                    'integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" '
                    'crossorigin="">')
_LEAFLET_CDN_JS = ('<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" '
                   'integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" '
                   'crossorigin=""></script>')
_LEAFLET_LOCAL_CSS = '<link rel="stylesheet" href="/static/vendor/leaflet/leaflet.css">'
_LEAFLET_LOCAL_JS = '<script src="/static/vendor/leaflet/leaflet.js"></script>'


@app.route("/")
def index():
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    if vendor_leaflet.have_leaflet():          # fully local — no external requests
        css, js = _LEAFLET_LOCAL_CSS, _LEAFLET_LOCAL_JS
    else:                                      # not vendored yet — fall back to CDN
        css, js = _LEAFLET_CDN_CSS, _LEAFLET_CDN_JS
    html = html.replace("<!--LEAFLET_CSS-->", css).replace("<!--LEAFLET_JS-->", js)
    return html


@app.route("/api/status")
def api_status():
    with _lock:
        pts = sum(len(t["pts"]) for t in _state["tracks"])
        return jsonify({
            "source": _state["source"], "snd_source": _state["snd_source"],
            "generated_at": (_state["generated_at"].strftime("%Y-%m-%d %H:%M UTC")
                             if _state["generated_at"] else None),
            "tracks": len(_state["tracks"]), "points": pts,
            "soundings": len(_state["sound_meta"]),
            "hours": _cfg["hours"], "version": _state["version"],
            "refresh": _cfg["refresh"], "auto": _cfg["auto"],
            "archive": _cfg["archive"],
            "archive_date": (_cfg["end_time"].strftime("%Y-%m-%d")
                             if _cfg["end_time"] else None),
            "archive_hour": (_cfg["end_time"].strftime("%H")
                             if _cfg["end_time"] else None),
            "phase": _state.get("phase", ""),
        })


@app.route("/api/tracks")
def api_tracks():
    with _lock:
        return jsonify({
            "source": _state["source"],
            "generated_at": (_state["generated_at"].strftime("%Y-%m-%d %H:%M UTC")
                             if _state["generated_at"] else None),
            "hours": _cfg["hours"], "version": _state["version"],
            "archive": _cfg["archive"],
            "archive_date": (_cfg["end_time"].strftime("%Y-%m-%d")
                             if _cfg["end_time"] else None),
            "tracks": _state["tracks"], "profiles": _state["sound_meta"],
        })


@app.route("/api/hrrr_sounding")
def api_hrrr_sounding():
    """Fetch a HRRR forecast sounding valid at an aircraft sounding's time/place
    and return a Skew-T overlay of the two (?id=<aircraft sounding id>)."""
    sid = request.args.get("id", "").strip()
    with _lock:
        s = _state["sound_by_id"].get(sid)
        s = dict(s) if s else None
    if not s:
        abort(404, description="sounding not found")
    lat, lon, t = s.get("lat"), s.get("lon"), s.get("time")
    if lat is None or lon is None or not t:
        return jsonify({"error": "This aircraft sounding has no location/time to match."})

    try:
        if _cfg["demo"]:
            hs = hrrr.demo_sounding(lat, lon, t)
        else:
            hs = hrrr.fetch_sounding(lat, lon, t)
    except hrrr.HrrrUnavailable as e:
        return jsonify({"error": f"No model sounding available for this time/place ({e})."})
    except Exception as e:
        return jsonify({"error": f"Could not retrieve the model sounding ({type(e).__name__})."})

    if not hs or len(hs.get("levels", [])) < 4:
        return jsonify({"error": "The model returned no usable profile for this point."})

    # overlay the aircraft sounding (s) with the model sounding (hs)
    import hashlib
    apt = s.get("place") or s.get("airport", "")
    path = os.path.join(SND_DIR, "hrrr_" + hashlib.md5(sid.encode()).hexdigest()[:16] + ".png")
    try:
        renderer, info = sounding_plot.make_png_multi([s, hs], path, apt)
    except Exception as e:
        return jsonify({"error": f"Could not render the comparison ({type(e).__name__})."})
    with open(path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode()
    an = analysis.analyze(hs)
    drop = ("parcel_p", "parcel_T", "storm_u_kt", "storm_v_kt", "mw_u_kt", "mw_v_kt")
    an_out = {k: v for k, v in (an or {}).items() if k not in drop}
    return jsonify({
        "id": sid, "overlay": True, "png": "data:image/png;base64," + b64,
        "renderer": renderer, "analysis": an_out,
        "model": hs.get("model", "HRRR"), "valid": hs.get("valid", ""),
        "name": hs.get("name", "HRRR"), "nlev": hs.get("nlev"),
        "source": hs.get("source", "Open-Meteo"),
    })


@app.route("/api/sounding")
def api_sounding():
    raw = request.args.get("id", "")
    ids = [x for x in raw.split(",") if x]
    if len(ids) >= 2:
        res = _render_multi(ids)
        if not res:
            abort(404, description="soundings not found")
        path, renderer, info = res
        with open(path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()
        return jsonify({
            "ids": ids, "overlay": True, "png": "data:image/png;base64," + b64,
            "renderer": renderer, "count": info.get("count"),
            "members": info.get("members", []), "airport": info.get("airport", ""),
        })

    sid = ids[0] if ids else ""
    res = _render_sounding(sid)
    if not res:
        abort(404, description="sounding not found")
    path, renderer, info, an, hodo_path = res
    with _lock:
        s = _state["sound_by_id"].get(sid, {})
    with open(path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode()
    hodo_uri = None
    if hodo_path:
        try:
            with open(hodo_path, "rb") as fh:
                hodo_uri = "data:image/png;base64," + base64.b64encode(fh.read()).decode()
        except OSError:
            hodo_uri = None
    t = s.get("time")
    tstr = (datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            if t else "")
    drop = ("parcel_p", "parcel_T", "storm_u_kt", "storm_v_kt", "mw_u_kt", "mw_v_kt")
    an_out = {k: v for k, v in (an or {}).items() if k not in drop}
    qc = s.get("qc")
    wv = s.get("wvqc")
    ms = s.get("moist_suspect")
    qc_note, note_level = None, None
    if wv and wv.get("frac", 0) >= 0.25:
        qc_note = ("Dewpoint likely bad — use with caution. The moisture sensor "
                   "reports itself faulty: %s (%d of %d obs)."
                   % (wv["meaning"], wv["bad"], wv["total"]))
        note_level = "alert"
    elif ms and ms.get("chronic"):
        c = ms["chronic"]
        qc_note = ("Dewpoint likely bad — use with caution. This airframe has read far "
                   "too dry on %d of its last %d checks (avg %.0f°C drier than the "
                   "surface truth) — probable faulty humidity sensor."
                   % (c["bad"], c["n"], c["avg"]))
        note_level = "alert"
    elif ms:
        detail = ""
        if ms.get("ac_td") is not None and ms.get("ref_td") is not None:
            detail = " (aircraft %.0f°C vs %.0f°C)" % (ms["ac_td"], ms["ref_td"])
        qc_note = ("Dewpoint likely bad — use with caution. Near the surface this "
                   "aircraft reads %.0f°C drier than %s%s."
                   % (ms["excess"], ms.get("src", "nearby observations"), detail))
        note_level = "alert"
    elif (qc and qc.get("flagged") and qc.get("total")
            and qc["flagged"] >= QC_NOTE_MIN_FRAC * qc["total"]):
        # MADIS levels 1-2 are per-OB checks: a couple of flagged obs on a 50-level
        # profile is routine and says nothing about the sounding as a whole. Only
        # mention it when a meaningful share of the profile is affected, and keep it
        # informational -- red is reserved for "this sensor is lying to you".
        qc_note = ("MADIS QC flagged %d of %d levels (%.0f%%) on this sounding."
                   % (qc["flagged"], qc["total"],
                      100.0 * qc["flagged"] / qc["total"]))
        note_level = "info"
    return jsonify({
        "id": sid, "png": "data:image/png;base64," + b64,
        "hodograph": hodo_uri,
        "renderer": renderer, "info": info, "analysis": an_out,
        "tail": s.get("tail", ""), "airport": s.get("airport", ""),
        "place": s.get("place", ""),
        "updown": s.get("updown", ""), "time": tstr,
        "levels": _display_levels(s), "geom": (info or {}).get("geom"),
        "qc": qc, "wvqc": wv, "moist_suspect": ms, "note": qc_note,
        "note_level": note_level,
    })


def _render_raob(snd):
    """Render a radiosonde sounding (cached by station + obs time). Returns
    (sid, png_path, renderer, info, analysis, hodo_path)."""
    sid = "RAOB:" + str(snd.get("wmo"))
    tkey = snd.get("time")
    c = _raob_cache.get(sid)
    if c and c[0] == tkey:
        return (sid,) + c[1:]
    an = analysis.analyze(snd)
    safe = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in sid)
    path = os.path.join(SND_DIR, safe + ".png")
    renderer, info = sounding_plot.make_png(snd, path, analysis=an)
    hodo_path = os.path.join(SND_DIR, safe + "_hodo.png")
    try:
        if not sounding_plot.make_hodograph_png(snd, hodo_path, analysis=an):
            hodo_path = None
    except Exception:
        hodo_path = None
    _raob_cache[sid] = (tkey, path, renderer, info, an, hodo_path)
    return sid, path, renderer, info, an, hodo_path


@app.route("/api/raob/stations")
def api_raob_stations():
    """Radiosonde station directory for the map markers."""
    if _cfg["demo"]:
        return jsonify({"stations": raob_stations.conus_stations(), "demo": True})
    return jsonify({"stations": raob_stations.all_stations(), "demo": False})


@app.route("/api/raob/sounding")
def api_raob_sounding():
    """Fetch + render the latest radiosonde for one station (?stn=WMO)."""
    wmo = request.args.get("stn", "").strip()
    stn = raob_stations.by_wmo(wmo)
    if not stn:
        abort(404, description="unknown radiosonde station")
    try:
        if _cfg["demo"]:
            snd = raob.demo_sounding(stn)
        else:
            when = None
            if _cfg["archive"] and _cfg["end_time"]:
                when = raob.latest_synoptic(_cfg["end_time"])
            snd = raob.fetch(stn, when=when)
        if not snd or len(snd.get("levels", [])) < 4:
            return jsonify({"error": "No radiosonde available for this station and time yet."})
    except Exception as e:
        return jsonify({"error": f"Could not retrieve the radiosonde ({type(e).__name__})."})

    snd.setdefault("name", f"{stn['id']} {stn['name']}")
    sid, path, renderer, info, an, hodo_path = _render_raob(snd)
    with open(path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode()
    hodo_uri = None
    if hodo_path:
        try:
            with open(hodo_path, "rb") as fh:
                hodo_uri = "data:image/png;base64," + base64.b64encode(fh.read()).decode()
        except OSError:
            hodo_uri = None
    t = snd.get("time")
    tstr = (datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            if t else "")
    note = None
    if snd.get("launch_miss"):
        shown = snd.get("shown_cycle")
        note = ("Site did not launch %s%s." %
                (snd["launch_miss"],
                 (" — showing %s" % shown) if shown else " — showing the most recent prior sounding"))
    drop = ("parcel_p", "parcel_T", "storm_u_kt", "storm_v_kt", "mw_u_kt", "mw_v_kt")
    an_out = {k: v for k, v in (an or {}).items() if k not in drop}
    return jsonify({
        "id": sid, "png": "data:image/png;base64," + b64, "hodograph": hodo_uri,
        "renderer": renderer, "info": info, "analysis": an_out,
        "station": stn, "name": snd.get("name", ""), "time": tstr, "kind": "raob",
        "note": note,
        "note_level": ("info" if note else None),
        "levels": _display_levels(snd), "geom": (info or {}).get("geom"),
    })


# --------------------------------------------------------------------------- #
#  Recent-soundings comparison viewer                                          #
# --------------------------------------------------------------------------- #
def _hhmmz(t):
    try:
        return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%H:%MZ")
    except Exception:
        return ""


@app.route("/api/recent_soundings")
def api_recent_soundings():
    """Pickable soundings for the comparison viewer: the most recent AMDAR (ACARS)
    profiles the app has loaded, plus the radiosonde station list (fetched on demand).
    HRRR is co-located with the anchor selection, so it needs no list."""
    with _lock:
        meta = [m for m in _state["sound_meta"] if m.get("time")]
    meta.sort(key=lambda m: m["time"], reverse=True)
    amdar = [{
        "ref": "acars:" + m["id"],
        "label": (m.get("place") or m.get("airport") or "AMDAR").strip() or "AMDAR",
        "sub": _hhmmz(m["time"]) + ((" " + m["updown"]) if m.get("updown") else ""),
        "lat": m.get("lat"), "lon": m.get("lon"), "time": m.get("time"),
    } for m in meta[:24]]
    raob = [{
        "ref": "raob:" + str(st["wmo"]),
        "label": st.get("id") or str(st["wmo"]),
        "sub": st.get("name", ""),
        "lat": st.get("lat"), "lon": st.get("lon"),
        "us": st.get("src") == "iem",
    } for st in raob_stations.all_stations()]
    # U.S./Canada first (most users), then international — each alphabetical by ID
    raob.sort(key=lambda r: (0 if r["us"] else 1, r["label"].upper()))
    return jsonify({"amdar": amdar, "raob": raob})


def _resolve_ref(ref):
    """Turn a typed reference (acars:ID | raob:WMO | hrrr:LAT:LON:EPOCH) into a
    sounding dict ready for overlay, with a source-labelled 'tail' for the legend."""
    kind, _, rest = ref.partition(":")
    if kind == "acars":
        with _lock:
            s = _state["sound_by_id"].get(rest)
        if not s:
            return None
        s = dict(s)
        s["id"] = ref
        s["tail"] = "AMDAR " + (s.get("tail") or "?")
        return s
    if kind == "raob":
        st = raob_stations.by_wmo(rest)
        if not st:
            return None
        with _lock:
            arch, end, demo = _cfg["archive"], _cfg["end_time"], _cfg["demo"]
        when = raob.latest_synoptic(end) if (arch and end) else None
        try:
            s = raob.demo_sounding(st) if demo else raob.fetch(st, when=when)
        except Exception:
            return None
        if not s:
            return None
        s = dict(s)
        s["id"] = "raob:" + rest
        s["tail"] = "RAOB " + (st.get("id") or rest)
        s.setdefault("updown", "(radiosonde)")
        return s
    if kind == "hrrr":
        parts = rest.split(":")
        if len(parts) < 3:
            return None
        try:
            lat, lon, t = float(parts[0]), float(parts[1]), int(float(parts[2]))
        except ValueError:
            return None
        with _lock:
            demo = _cfg["demo"]
        try:
            s = hrrr.demo_sounding(lat, lon, t) if demo else hrrr.fetch_sounding(lat, lon, t)
        except Exception:
            return None
        if not s:
            return None
        s = dict(s)
        s["id"] = ref
        s["tail"] = "HRRR"
        return s
    return None


@app.route("/api/compare")
def api_compare():
    """Overlay any mix of AMDAR / radiosonde / HRRR soundings (?refs=a,b,c)."""
    refs = [r for r in request.args.get("refs", "").split(",") if r]
    if not refs:
        return jsonify({"error": "No soundings selected."})
    snds, missed = [], []
    for ref in refs[:8]:
        s = _resolve_ref(ref)
        if s and len(s.get("levels", [])) >= 3:
            snds.append(s)
        else:
            missed.append(ref)
    if not snds:
        return jsonify({"error": "None of the selected soundings could be loaded."})
    import hashlib
    key = "cmp:" + ",".join(refs)
    path = os.path.join(SND_DIR, "cmp_" + hashlib.md5(key.encode()).hexdigest()[:16] + ".png")
    try:
        renderer, info = sounding_plot.make_png_multi(snds, path)
    except Exception as e:
        return jsonify({"error": "Could not render the comparison (%s)." % type(e).__name__})
    with open(path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode()
    # map each rendered member back to the ref that produced it (for chip colours)
    members = info.get("members", [])
    return jsonify({
        "png": "data:image/png;base64," + b64, "renderer": renderer,
        "count": info.get("count", len(snds)), "members": members,
        "missed": missed,
    })


@app.route("/api/pireps")
def api_pireps():
    """Recent pilot reports (PIREPs/AIREPs), classified turb/icing/both/nil/other."""
    hours = _cfg["hours"]
    try:
        if _cfg["demo"]:
            items = pireps.demo(hours)
        else:
            end = _cfg["end_time"] if _cfg["archive"] else None
            items = pireps.fetch(hours, end_time=end)
    except pireps.PirepHTTPError as e:
        body = (getattr(e, "body", "") or "").strip().replace("\n", " ")[:140]
        detail = (" — " + body) if body else ""
        return jsonify({"error": f"Could not fetch PIREPs (HTTP {e.status}){detail}",
                        "pireps": []})
    except Exception as e:
        return jsonify({"error": f"Could not fetch PIREPs ({type(e).__name__}).", "pireps": []})
    return jsonify({"pireps": items, "count": len(items)})


@app.route("/api/refresh", methods=["POST", "GET"])
def api_refresh():
    refresh()
    return api_status()


@app.route("/api/load", methods=["POST", "GET"])
def api_load():
    """Switch the data source. ?date=YYYY-MM-DD&hour=HH loads that archive day;
    ?date=live (or empty) goes back to the live feed. Optional &hours=N."""
    date = (request.args.get("date") or "").strip()
    hour = request.args.get("hour")
    hours = request.args.get("hours")
    if hours:
        try:
            _cfg["hours"] = max(1, min(24, int(hours)))
        except ValueError:
            pass
    if not date or date.lower() == "live":
        _cfg["archive"] = False
        _cfg["end_time"] = None
        _cfg["demo"] = _cfg["demo_start"]      # stay in demo if launched that way
    else:
        try:
            parts = [int(x) for x in date.replace("/", "-").split("-")]
            y, m, d = parts[0], parts[1], parts[2]
            hh = int(hour) if hour not in (None, "") else 23
            hh = max(0, min(23, hh))
            _cfg["end_time"] = datetime(y, m, d, hh, tzinfo=timezone.utc)
            _cfg["archive"] = True
            _cfg["demo"] = False
        except Exception as e:
            abort(400, description=f"bad date/hour ({e})")
    refresh()
    return api_status()


@app.route("/api/autorefresh", methods=["POST", "GET"])
def api_autorefresh():
    """Set auto-update. ?seconds=N turns it on with that interval; 0 turns it off."""
    secs = request.args.get("seconds")
    if secs is not None:
        try:
            n = int(secs)
        except ValueError:
            abort(400, description="bad seconds")
        if n <= 0:
            _cfg["auto"] = False
        else:
            _cfg["auto"] = True
            _cfg["refresh"] = max(60, min(7200, n))
    return jsonify({"auto": _cfg["auto"], "refresh": _cfg["refresh"]})


def _free_port(preferred):
    """Return the preferred port if free, otherwise the next available one."""
    import socket
    for p in [preferred] + list(range(preferred + 1, preferred + 25)):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    return preferred


def main():
    ap = argparse.ArgumentParser(description="ACARS flight-track + sounding map server")
    ap.add_argument("--hours", type=int, default=3)
    ap.add_argument("--port", type=int, default=5001)
    ap.add_argument("--refresh", type=int, default=900,
                    help="seconds between auto-updates of live data (default 900 = 15 min)")
    ap.add_argument("--max-tracks", type=int, default=None)
    ap.add_argument("--demo", action="store_true", help="force synthetic data (no network)")
    ap.add_argument("--date", default=None,
                    help="historical archive date YYYY-MM-DD (instead of live feed)")
    ap.add_argument("--hour", type=int, default=23,
                    help="end hour (UTC, 0-23) for --date; the window ends here")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--madis-raob", action="store_true",
                    help="also try the MADIS public radiosonde feed before IGRA "
                         "(note: its public tier is US-only; international still uses IGRA)")
    ap.add_argument("--no-dwd", action="store_true",
                    help="don't use the DWD open-data TEMP feed for global soundings "
                         "(use the IGRA archive only)")
    # when double-clicked as a packaged .exe there are no args; ignore unknown ones
    args, _ = ap.parse_known_args()

    if args.no_dwd:
        try:
            import raob
            raob.PREFER_DWD = False
            print("Global soundings: IGRA archive only (DWD TEMP feed disabled).")
        except Exception:
            pass

    if args.madis_raob:
        try:
            import raob
            raob.PREFER_MADIS = True
            print("MADIS public radiosonde feed enabled (US-only tier; "
                  "international soundings still use IGRA).")
        except Exception:
            pass

    _cfg.update(hours=args.hours, demo=args.demo, demo_start=args.demo,
                max_tracks=args.max_tracks)
    if args.refresh and args.refresh > 0:
        _cfg["refresh"] = max(60, args.refresh)
        _cfg["auto"] = True
    else:
        _cfg["auto"] = False
    if args.date:
        try:
            parts = [int(x) for x in args.date.replace("/", "-").split("-")]
            hh = max(0, min(23, args.hour))
            _cfg["end_time"] = datetime(parts[0], parts[1], parts[2], hh,
                                        tzinfo=timezone.utc)
            _cfg["archive"] = True
            _cfg["demo"] = False
            print(f"Archive mode: {_cfg['end_time']:%Y-%m-%d %H:%MZ} "
                  f"(last {args.hours}h)")
        except Exception as e:
            print(f"Ignoring bad --date '{args.date}' ({e}); using live feed.")

    # Make the map library local (verified download) so the app needs no outside
    # request for it once done. Runs in the background so it never delays startup;
    # if already vendored, nothing happens and no network call is made.
    try:
        if not vendor_leaflet.have_leaflet():
            threading.Thread(target=vendor_leaflet.ensure_leaflet, daemon=True).start()
    except Exception:
        pass

    print("Loading initial data (this can take a few seconds)...")
    refresh()
    stop = threading.Event()
    threading.Thread(target=_loop, args=(stop,), daemon=True).start()

    port = _free_port(args.port)
    url = f"http://localhost:{port}"
    print("\n  ===============================================================")
    print(f"   ACARS flight-track + sounding map is running at:  {url}")
    print("   Your web browser should open automatically.")
    print("   Keep this window open while you use it. Close it to stop.")
    print("  ===============================================================\n")
    if not args.no_browser:
        Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        app.run(host="127.0.0.1", port=port, threaded=True, debug=False)
    except Exception as e:
        print(f"\nThe server stopped unexpectedly: {e}")
        if getattr(sys, "frozen", False):
            input("Press Enter to close this window...")


if __name__ == "__main__":
    main()
