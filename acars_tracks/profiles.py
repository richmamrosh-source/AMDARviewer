"""
profiles.py — Download + parse the MADIS ACARS *profiles* (soundings) feed.

    https://madis-data.ncep.noaa.gov/madisPublic1/data/point/acarsProfiles/netcdf/

Per the MADIS ACARS-Profiles variable list, each file holds vertical profiles
(aircraft ascents/descents). The level data (temperature, dewpoint, pressure,
pressure-altitude, wind, AND latitude/longitude/time) is stored **per level** as
2-D arrays [profile][level] (up to 200 levels). Per-profile values are the tail
number (TAILNUM), airport (STALOC), and profile type (PRFTYPE).

We turn each profile into a sounding dict with the same shape demo.generate_profiles
produces:

    {id, tail, time, lat, lon, airport, updown,
     levels: [{p, z, T, Td, wdir, wspd}, ...]}      # p[Pa] z[m] T,Td[K] wspd[m/s]

The location/time come from the surface (highest-pressure) level. We try the 2-D
layout first, fall back to a flat layout, resolve every field from candidate
names (matching the working en-route parser), auto-detect units, and -- if nothing
parses -- print the file's dimensions and variables so any mismatch is obvious.
"""

import gzip
import os
from datetime import datetime, timedelta, timezone

from paths import cache_root
LIVE_URL = ("https://madis-data.ncep.noaa.gov/madisPublic1/data/point/"
            "acarsProfiles/netcdf/")
ARCHIVE_ROOT = "https://madis-data.ncep.noaa.gov/madisPublic1/data/archive/"
ARCHIVE_SUB = "/point/acarsProfiles/netcdf/"
CACHE_DIR = os.path.join(cache_root(), "profiles")
os.makedirs(CACHE_DIR, exist_ok=True)

# candidate netCDF variable names (long MADIS names, matching the en-route feed)
CAND = {
    "tail":  ["tailNumber", "en_tailNumber", "rptStation", "stationName"],
    "apt":   ["staLoc", "stationLocation", "rptStation", "stationName", "airport"],
    "prftype": ["profileType", "prfType", "PRFTYPE", "profileTypeFlag"],
    "nlev":  ["nLevels", "numLevels", "levels", "nObs"],
    # level fields (2-D [profile][level], or 1-D in a flat file)
    "lat":   ["latitude", "trackLat", "Lat", "lat"],
    "lon":   ["longitude", "trackLon", "Lon", "lon"],
    "time":  ["timeObs", "obTimeStamp", "obsTime", "obTime", "relTime", "synTime",
              "validTime", "secondsSinceMidnight", "timeNominal", "time"],
    "p":     ["pressure", "obsPressure"],
    "z":     ["altitude", "pressureAltitude", "heightMSL", "GPSaltitude", "GPSheight", "height"],
    "T":     ["temperature", "obsTemperature", "temp"],
    "Td":    ["dewpoint", "dewpointTemperature", "dewPoint"],
    "wdir":  ["windDir", "windDirection", "wdir"],
    "wspd":  ["windSpeed", "windSpd", "wspd"],
}
_diag_done = False

# --------------------------------------------------------------------------- #
#  MADIS quality control                                                       #
# --------------------------------------------------------------------------- #
# MADIS runs its own QC and publishes the verdict next to each ob, either as a
# single-letter descriptor (<var>DD) or a bitmask of failed checks (<var>QCR).
# DD letters: V/S/C = passed (verified/screened/coarse), X = rejected on the
# gross-error check, Q = questioned (failed a consistency check), B = subjective
# bad, Z = no QC applied yet. We flag X/Q/B and leave everything else alone.
#
# This is all best-effort: if a file carries no QC companions, nothing is flagged
# and the app behaves exactly as before.
QC_BAD_LETTERS = ("X", "Q", "B")
_QC_SUFFIXES = ("DD", "QCR", "_DD", "_QCR")
_QC_FIELDS = ("T", "Td", "wdir", "wspd")      # level fields we actually plot
_QC_SEEN = {"fields": [], "reported": False}


def _resolved_name(ds, key, ndim=None):
    """The netCDF variable name actually used for a logical field in this file."""
    for n in CAND[key]:
        if n in ds.variables:
            if ndim is None or getattr(ds.variables[n], "ndim", 0) == ndim:
                return n
    return None


def _qc_bad_array(ds, key, ndim):
    """Boolean array marking obs MADIS flagged bad/questionable for one field.
    Returns (qc_var_name, bad_array), or (None, None) if this file has no QC
    companion for that field — in which case nothing gets flagged."""
    base = _resolved_name(ds, key, ndim)
    if not base:
        return None, None
    np = _np()
    for suf in _QC_SUFFIXES:
        qn = base + suf
        if qn not in ds.variables:
            continue
        qv = ds.variables[qn]
        try:
            raw = qv[:]
            if getattr(qv, "dtype", None) is not None and qv.dtype.kind in ("S", "U"):
                raw = np.ma.filled(raw, b" ") if np.ma.isMaskedArray(raw) else raw
                dec = np.char.upper(np.asarray(raw).astype("U1"))
                bad = np.isin(dec, list(QC_BAD_LETTERS))
            else:
                arr = np.ma.filled(np.ma.asarray(raw, dtype="float64"), 0.0)
                arr[np.abs(arr) > 1e30] = 0.0      # fill values are not failures
                bad = arr > 0                      # QCR bitmask: 0 = passed everything
            if getattr(bad, "ndim", 0) != ndim:
                continue
            return qn, bad
        except Exception:
            continue
    return None, None


def _qc_collect(ds, ndim):
    """QC 'bad' arrays for every level field that has them in this file."""
    masks, names = {}, []
    for key in _QC_FIELDS:
        try:
            qn, arr = _qc_bad_array(ds, key, ndim)
        except Exception:
            qn, arr = None, None
        if qn is not None:
            masks[key] = arr
            names.append(qn)
    if names and not _QC_SEEN["reported"]:
        _QC_SEEN["fields"] = names
        _QC_SEEN["reported"] = True
        print("  [profiles] MADIS QC fields found — flagging suspect levels: %s"
              % ", ".join(names))
    return masks


def _qc_flag_level(masks, lv, i, j):
    """Mark a level if any of its fields was flagged by MADIS QC."""
    for arr in masks.values():
        try:
            if bool(arr[i, j] if arr.ndim == 2 else arr[i]):
                lv["qc_bad"] = True
                return
        except Exception:
            continue


# --------------------------------------------------------------------------- #
#  WVSS-II reported moisture-sensor status  (MADIS "REPWVQC")                  #
# --------------------------------------------------------------------------- #
# The moisture sensor reports its OWN health with every ob. This is the field
# that can finger an airframe whose humidity sensor is broken -- heater failed,
# element contaminated, or (the classic) RH pinned at its floor, which yields a
# bone-dry, inverted-V profile that is individually "plausible" and therefore
# sails through MADIS's own QC.
CAND["wvqc"] = ["waterVaporQC", "repWVQC", "REPWVQC", "reportedWaterVaporQC",
                "reportedWVQC", "waterVaporQCFlag", "wvQC", "rhQC",
                "waterVaporQCCode", "moistureQC"]

# value -> (is_bad, meaning).  MADIS publishes two tables; they don't overlap,
# so the right one can be picked from the values actually present.
_WVQC_FSL = {
    45: (None, "missing"),
    48: (False, "normal (ground speed > 60 kt)"),
    49: (False, "normal, non-measurement mode"),
    50: (True, "RH below sensor floor — clamped to 1.5% (reads bone dry)"),
    51: (True, "humidity element WET"),
    52: (True, "humidity element CONTAMINATED"),
    53: (True, "HEATER FAIL"),
    54: (True, "HEATER FAIL + wet/contaminated element"),
    55: (True, "an input to the mixing-ratio calculation is invalid"),
    56: (True, "numeric error in the mixing-ratio calculation"),
    57: (True, "dewpoint greater than temperature"),
}
_WVQC_AWIPS = {
    0:  (False, "normal, measurement mode"),
    1:  (False, "normal, non-measurement mode"),
    2:  (True, "small RH (sensor at/near its floor — reads very dry)"),
    3:  (True, "humidity element WET"),
    4:  (True, "humidity element CONTAMINATED"),
    5:  (True, "HEATER FAIL"),
    6:  (True, "HEATER FAIL + wet/contaminated element"),
    7:  (True, "an input to the mixing-ratio calculation is invalid"),
    8:  (True, "numeric error"),
    9:  (True, "SENSOR NOT INSTALLED"),
    63: (None, "missing"),
}
_WV_SEEN = {"var": None, "table": None, "reported": False}


def _wvqc_table(vals):
    """Pick the code table matching the values present (FSL 45–57 vs AWIPS 0–9/63)."""
    try:
        v = {int(x) for x in vals if x is not None and x == x}
    except Exception:
        return None, None
    if v & set(range(48, 58)):
        return _WVQC_FSL, "FSL"
    if v & set(range(0, 10)):
        return _WVQC_AWIPS, "AWIPS"
    return None, None


def _wvqc_array(ds, ndim):
    """The reported moisture-sensor status per ob, or None if absent."""
    np = _np()
    for n in CAND["wvqc"]:
        if n in ds.variables and getattr(ds.variables[n], "ndim", 0) == ndim:
            try:
                a = np.ma.filled(np.ma.asarray(ds.variables[n][:], dtype="float64"), np.nan)
                a[np.abs(a) > 1e30] = np.nan
                tbl, which = _wvqc_table(a[np.isfinite(a)].ravel()[:5000])
                if tbl is None:
                    continue
                if not _WV_SEEN["reported"]:
                    _WV_SEEN.update(var=n, table=which, reported=True)
                    print("  [profiles] moisture-sensor status field found: %s "
                          "(%s code table) — bad humidity sensors will be named"
                          % (n, which))
                return a, tbl
            except Exception:
                continue
    return None, None


def _wvqc_summary(arr, tbl, idx):
    """Summarise the sensor's self-reported health over one profile's obs.
    Returns None when the sensor said it was healthy (or said nothing)."""
    if arr is None or tbl is None:
        return None
    bad, tot, meaning = 0, 0, None
    counts = {}
    for v in idx:
        if v is None or v != v:
            continue
        code = int(v)
        ent = tbl.get(code)
        if ent is None or ent[0] is None:
            continue
        tot += 1
        if ent[0]:
            bad += 1
            counts[code] = counts.get(code, 0) + 1
    if not tot or not bad:
        return None
    top = max(counts, key=counts.get)
    meaning = tbl[top][1]
    return {"bad": bad, "total": tot, "code": top, "meaning": meaning,
            "frac": round(bad / float(tot), 3)}


# --------------------------------------------------------------------------- #
#  download / cache                                                           #
# --------------------------------------------------------------------------- #
def _http_get(url, timeout=90):
    try:
        import requests
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "acars-tracks/1.0"})
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        return r.content
    except ImportError:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "acars-tracks/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()


def _hourly_names(hours, end_time=None):
    end = (end_time or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)
    return [((end - timedelta(hours=i)).strftime("%Y%m%d_%H00.gz"),
             end - timedelta(hours=i)) for i in range(hours + 1)]


def _url_for(fname, dt, archive):
    if archive:
        return ARCHIVE_ROOT + dt.strftime("%Y/%m/%d") + ARCHIVE_SUB + fname
    return LIVE_URL + fname


def _prune(valid):
    keep = set(valid)
    for fn in os.listdir(CACHE_DIR):
        if fn.endswith(".gz") and fn not in keep:
            try:
                os.remove(os.path.join(CACHE_DIR, fn))
            except OSError:
                pass


def _download(fname, dt, archive=False):
    sub = os.path.join(CACHE_DIR, "archive") if archive else CACHE_DIR
    os.makedirs(sub, exist_ok=True)
    dest = os.path.join(sub, fname)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        with open(dest, "rb") as fh:
            return fh.read()
    try:
        blob = _http_get(_url_for(fname, dt, archive))
    except Exception:
        return None
    with open(dest, "wb") as fh:
        fh.write(blob)
    return blob


# --------------------------------------------------------------------------- #
#  helpers                                                                     #
# --------------------------------------------------------------------------- #
def _np():
    import numpy as np
    return np


def _find(ds, key):
    for n in CAND[key]:
        if n in ds.variables:
            return ds.variables[n]
    return None


def _find_2d(ds, key):
    for n in CAND[key]:
        if n in ds.variables and getattr(ds.variables[n], "ndim", 0) == 2:
            return ds.variables[n]
    return None


def _find_1d(ds, key):
    for n in CAND[key]:
        if n in ds.variables and getattr(ds.variables[n], "ndim", 0) == 1:
            return ds.variables[n]
    return None


def _clean(x):
    np = _np()
    a = np.ma.masked_invalid(np.ma.asarray(x, dtype=float))
    out = np.ma.filled(a, np.nan)
    out[np.abs(out) > 1e30] = np.nan          # MADIS fill values
    return out


def _to_pa(vals):
    np = _np()
    v = np.asarray(vals, float)
    fin = v[np.isfinite(v)]
    med = np.nanmedian(fin) if fin.size else 0
    return v * 100.0 if 0 < med < 2000 else v   # hPa -> Pa


def _to_K(vals):
    np = _np()
    v = np.asarray(vals, float)
    fin = v[np.isfinite(v)]
    med = np.nanmedian(fin) if fin.size else 0
    return v + 273.15 if -150 < med < 100 else v  # C -> K


def _strvals(var, n):
    """Decode a character variable to n strings, with/without netCDF4."""
    np = _np()
    try:
        data = var[:]
    except Exception:
        return None
    try:
        import netCDF4
        out = netCDF4.chartostring(data)
        vals = [str(s).strip().strip("\x00") for s in np.atleast_1d(out)]
        if len(vals) == n:
            return vals
    except Exception:
        pass
    try:
        arr = np.asarray(data)
        if arr.ndim == 2:
            rows = []
            for row in arr:
                if row.dtype.kind in ("S", "U"):
                    s = "".join(
                        (x.decode("ascii", "ignore") if isinstance(x, (bytes, bytearray))
                         else str(x)) for x in row)
                else:
                    s = bytes(int(c) for c in row if 0 < int(c) < 128).decode("ascii", "ignore")
                rows.append(s.strip().strip("\x00"))
            if len(rows) == n:
                return rows
        elif arr.ndim == 1 and arr.dtype.kind in ("S", "U"):
            vals = [(x.decode("ascii", "ignore") if isinstance(x, (bytes, bytearray)) else str(x)).strip().strip("\x00")
                    for x in arr]
            if len(vals) == n:
                return vals
    except Exception:
        pass
    return None


def _epoch_from(val, fname):
    if val is None:
        return None
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    if v != v:                       # NaN
        return None
    if v > 1e11:                     # milliseconds since 1970
        return v / 1000.0
    if v > 1e8:                      # seconds since 1970 (epoch)
        return v
    if 0 <= v <= 86401:              # seconds since midnight UTC -> add file date
        try:
            d = datetime.strptime(fname[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
            return d.timestamp() + v
        except Exception:
            return None
    return v


def _level(p, z, T, Td, wd, ws):
    np = _np()
    if not (np.isfinite(p) and np.isfinite(T)):
        return None
    return {
        "p": round(float(p), 1),
        "z": (round(float(z), 1) if np.isfinite(z) else None),
        "T": round(float(T), 2),
        "Td": (round(float(Td), 2) if np.isfinite(Td) else None),
        "wdir": (round(float(wd), 1) if np.isfinite(wd) else None),
        "wspd": (round(float(ws), 2) if np.isfinite(ws) else None),
    }


# A real aircraft ascent/descent spans many thousands of feet. En-route (cruise)
# reports, and real profiles whose lower levels were QC'd out, span only a sliver
# of altitude and plot as a meaningless squiggle high on the Skew-T. Require a
# minimum vertical extent so those partial/degenerate "soundings" are dropped.
MIN_SPAN_M = 2500.0            # ~8,200 ft; tune here if needed
_SKIP = {"short": 0}           # count of profiles dropped for insufficient vertical span


def _std_alt(p_pa):
    """Approx. standard-atmosphere altitude (m) from pressure (Pa)."""
    try:
        return 44330.77 * (1.0 - (float(p_pa) / 101325.0) ** 0.190263)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _vspan(levels):
    """Vertical extent of a profile in metres, from its pressure range (pressure is
    always present, so this is more reliable than the optional geopotential z)."""
    ps = [d["p"] for d in levels if d.get("p")]
    if len(ps) < 2:
        return 0.0
    return _std_alt(min(ps)) - _std_alt(max(ps))     # min pressure = top of profile


def _time_like(var, N, L):
    """Return cleaned array if var is shaped (N,) or (N,L), numeric, and its
    values look like a time (epoch s, epoch ms, or seconds-since-midnight)."""
    np = _np()
    if getattr(var, "dtype", None) is None or var.dtype.kind not in ("f", "i", "u"):
        return None
    shp = tuple(getattr(var, "shape", ()))
    if shp not in ((N,), (N, L)):
        return None
    try:
        a = _clean(var[:])
    except Exception:
        return None
    fin = a[np.isfinite(a)]
    if fin.size == 0:
        return None
    med = float(np.median(fin))
    if (1e8 < med < 5e9) or (1e11 < med < 5e12) or (0 <= med <= 86401):
        return a
    return None


def _resolve_time(ds, N, L):
    """Find the per-ob time variable. Tries the known names first, then
    auto-detects any time-named field with plausible values. Returns
    ('2d'|'1d'|None, array|None)."""
    # 1) known names, 2-D (per level) then 1-D (per profile)
    v = _find_2d(ds, "time")
    if v is not None:
        a = _time_like(v, N, L)
        if a is not None:
            return "2d", a
    v = _find_1d(ds, "time")
    if v is not None:
        a = _time_like(v, N, L)
        if a is not None:
            return "1d", a
    # 2) auto-detect: any time-ish-named numeric var with time-like values
    KW = ("time", "tdaysec", "daysec", "second", "utc", "epoch", "tod")
    BAD = ("receipt", "recpt", "qc", "nominal", "creation", "process", "report")
    cands = []
    for name, var in ds.variables.items():
        nl = name.lower()
        if not any(k in nl for k in KW):
            continue
        a = _time_like(var, N, L)
        if a is None:
            continue
        score = 0
        if "ob" in nl:
            score += 2
        if "time" in nl:
            score += 1
        if any(b in nl for b in BAD):
            score -= 3
        shp = "2d" if tuple(var.shape) == (N, L) else "1d"
        cands.append((score, shp, a, name))
    if cands:
        cands.sort(key=lambda c: -c[0])
        score, shp, a, name = cands[0]
        print(f"  [profiles] auto-detected '{name}' as the ob-time variable")
        return shp, a
    return None, None


# --------------------------------------------------------------------------- #
#  parsers                                                                     #
# --------------------------------------------------------------------------- #
def _parse_2d(ds, out, fname):
    np = _np()
    Tvar = _find_2d(ds, "T")
    if Tvar is None:
        return False
    N, L = Tvar.shape

    def lv2d(key, conv=None):
        v = _find_2d(ds, key)
        if v is None:
            return None
        a = _clean(v[:])
        return conv(a) if conv else a

    T2 = _to_K(_clean(Tvar[:]))
    p2 = lv2d("p", _to_pa)
    z2 = lv2d("z")
    Td2 = lv2d("Td", _to_K)
    wd2 = lv2d("wdir"); ws2 = lv2d("wspd")
    lat2 = lv2d("lat"); lon2 = lv2d("lon")
    if p2 is None and z2 is None:
        return False                       # no vertical coordinate -> not this layout

    # find the ob-time field (per level=2-D, per profile=1-D, or auto-detected)
    ttype, tarr = _resolve_time(ds, N, L)
    tm2 = tarr if ttype == "2d" else None
    tm1 = tarr if ttype == "1d" else None

    vt = _find(ds, "tail"); tails = _strvals(vt, N) if vt is not None else None
    va = _find(ds, "apt"); apts = _strvals(va, N) if va is not None else None
    vn = _find_1d(ds, "nlev"); nlev = _clean(vn[:]) if vn is not None else None
    qc_masks = _qc_collect(ds, 2)          # {} when this file carries no QC fields
    wv_arr, wv_tbl = _wvqc_array(ds, 2)    # WVSS-II self-reported sensor health

    made = 0
    for i in range(N):
        nl = int(nlev[i]) if (nlev is not None and i < len(nlev) and np.isfinite(nlev[i])) else L
        nl = max(0, min(nl, L))
        levels, lats, lons, tms, zord = [], [], [], [], []
        for j in range(nl):
            p = p2[i, j] if p2 is not None else np.nan
            z = z2[i, j] if z2 is not None else np.nan
            T = T2[i, j]
            Td = Td2[i, j] if Td2 is not None else np.nan
            wd = wd2[i, j] if wd2 is not None else np.nan
            ws = ws2[i, j] if ws2 is not None else np.nan
            if not np.isfinite(p) and np.isfinite(z):
                p = 101325.0 * (1.0 - 2.25577e-5 * float(z)) ** 5.25588
            lv = _level(p, z, T, Td, wd, ws)
            if lv:
                _qc_flag_level(qc_masks, lv, i, j)
                levels.append(lv)
                lats.append(float(lat2[i, j]) if lat2 is not None and np.isfinite(lat2[i, j]) else None)
                lons.append(float(lon2[i, j]) if lon2 is not None and np.isfinite(lon2[i, j]) else None)
                tms.append(tm2[i, j] if tm2 is not None and np.isfinite(tm2[i, j]) else None)
                zord.append(lv["z"])
        if len(levels) < 3:
            continue
        if _vspan(levels) < MIN_SPAN_M:      # cruise noise / truncated fragment, not a real profile
            _SKIP["short"] += 1
            continue
        ps = [d["p"] for d in levels]
        si = int(np.argmax(ps))                          # surface = max pressure
        rep_lat, rep_lon = lats[si], lons[si]
        rep_tm = None
        if tm2 is not None and si < len(tms):
            rep_tm = _epoch_from(tms[si], fname)
        if rep_tm is None and tm1 is not None and i < len(tm1):
            rep_tm = _epoch_from(tm1[i], fname)
        zo = [z for z in zord if z is not None]
        updown = ("UP" if zo[-1] > zo[0] else "DOWN") if len(zo) >= 2 else ""
        levels.sort(key=lambda d: -d["p"])
        tid = (tails[i] if tails and i < len(tails) else "") or "UNKNOWN"
        nbad = sum(1 for d in levels if d.get("qc_bad"))
        wv = (_wvqc_summary(wv_arr, wv_tbl, [wv_arr[i, j] for j in range(nl)])
              if wv_arr is not None else None)
        out.append({
            "id": f"{fname[:-3]}_{i}",
            "tail": tid,
            "time": rep_tm,
            "lat": round(rep_lat, 4) if rep_lat is not None else None,
            "lon": round(rep_lon, 4) if rep_lon is not None else None,
            "airport": (apts[i].strip() if apts and i < len(apts) else "") or "",
            "updown": updown,
            "levels": levels,
            "qc": ({"flagged": nbad, "total": len(levels),
                    "fields": _QC_SEEN["fields"]} if qc_masks else None),
            "wvqc": wv,
        })
        made += 1
    return made > 0


def _parse_flat(ds, out, fname):
    """Fallback: each record is one level-ob; group by tail into a profile."""
    np = _np()
    v_lat = _find_1d(ds, "lat"); v_T = _find_1d(ds, "T")
    if v_lat is None or v_T is None:
        return False
    n = v_T.shape[0]
    lat = _clean(v_lat[:])
    v_lon = _find_1d(ds, "lon"); lon = _clean(v_lon[:]) if v_lon is not None else None
    _tt, _ta = _resolve_time(ds, n, 1); tm = _ta if _tt is not None else None

    def col(key, conv=None):
        v = _find_1d(ds, key)
        if v is None:
            return np.full(n, np.nan)
        a = _clean(v[:])
        return conv(a) if conv else a

    T = col("T", _to_K); Td = col("Td", _to_K); p = col("p", _to_pa)
    z = col("z"); wd = col("wdir"); ws = col("wspd")
    vt = _find(ds, "tail"); tails = _strvals(vt, n) if vt is not None else None
    qc_masks = _qc_collect(ds, 1)          # {} when this file carries no QC fields
    wv_arr, wv_tbl = _wvqc_array(ds, 1)    # WVSS-II self-reported sensor health

    groups = {}
    for i in range(n):
        if not np.isfinite(lat[i]):
            continue
        tid = (tails[i] if tails else "") or "UNKNOWN"
        groups.setdefault(tid, []).append(i)

    made = 0
    for tid, idx in groups.items():
        idx.sort(key=lambda i: (tm[i] if tm is not None and np.isfinite(tm[i]) else 0))
        levels = []
        for i in idx:
            pp = p[i]
            if not np.isfinite(pp) and np.isfinite(z[i]):
                pp = 101325.0 * (1.0 - 2.25577e-5 * float(z[i])) ** 5.25588
            lv = _level(pp, z[i], T[i], Td[i], wd[i], ws[i])
            if lv:
                _qc_flag_level(qc_masks, lv, i, 0)
                levels.append(lv)
        if len(levels) < 3:
            continue
        if _vspan(levels) < MIN_SPAN_M:
            _SKIP["short"] += 1
            continue
        i0 = idx[0]
        zo = [d["z"] for d in levels if d["z"] is not None]
        updown = ("UP" if zo[-1] > zo[0] else "DOWN") if len(zo) >= 2 else ""
        levels.sort(key=lambda d: -d["p"])
        nbad = sum(1 for d in levels if d.get("qc_bad"))
        wv = (_wvqc_summary(wv_arr, wv_tbl, [wv_arr[k] for k in idx])
              if wv_arr is not None else None)
        out.append({
            "id": f"{fname[:-3]}_{tid}",
            "tail": tid,
            "time": _epoch_from(tm[i0], fname) if tm is not None else None,
            "lat": round(float(lat[i0]), 4),
            "lon": round(float(lon[i0]), 4) if lon is not None and np.isfinite(lon[i0]) else None,
            "airport": "",
            "updown": updown,
            "levels": levels,
            "qc": ({"flagged": nbad, "total": len(levels),
                    "fields": _QC_SEEN["fields"]} if qc_masks else None),
            "wvqc": wv,
        })
        made += 1
    return made > 0


def _diagnose(ds, fname):
    global _diag_done
    if _diag_done:
        return
    _diag_done = True
    print(f"  [profiles] could not parse any soundings from {fname}.")
    print("  [profiles] dimensions: " +
          ", ".join(f"{k}={len(v)}" for k, v in ds.dimensions.items()))
    print("  [profiles] variables (name  dims  shape  units):")
    for vn in sorted(ds.variables):
        v = ds.variables[vn]
        print(f"      {vn}  dims={tuple(v.dimensions)} shape={tuple(v.shape)} "
              f"units={getattr(v, 'units', '')}")
    print("  [profiles] ^ please send this output to update the parser.")


def _parse(blob, fname, out):
    import netCDF4
    ds = netCDF4.Dataset("inmem", mode="r", memory=gzip.decompress(blob))
    try:
        if _parse_2d(ds, out, fname):
            return
        if _parse_flat(ds, out, fname):
            return
        _diagnose(ds, fname)
    finally:
        ds.close()


def fetch(hours=6, max_profiles=None, end_time=None, archive=False):
    """Returns (soundings, generated_at). Raises on hard download failure.

    end_time/archive pull a historical day from the MADIS archive instead of the
    live feed; the window is the `hours` ending at end_time.
    """
    names = _hourly_names(hours, end_time)
    if not archive:
        _prune([fn for fn, _ in names])
    _SKIP["short"] = 0
    out, got = [], False
    for fn, dt in names:
        blob = _download(fn, dt, archive)
        if blob:
            got = True
            try:
                _parse(blob, fn, out)
            except Exception as e:
                print(f"  [profiles] parse error on {fn}: {e}")
    if not got:
        raise RuntimeError("Could not download any ACARS profile files.")
    if _SKIP["short"]:
        print("  [profiles] skipped %d partial/degenerate profiles "
              "(vertical span < %.0f m)" % (_SKIP["short"], MIN_SPAN_M))

    out.sort(key=lambda s: (s["time"] or 0), reverse=True)
    seen, uniq = set(), []
    for s in out:
        key = (s["tail"], round((s["time"] or 0) / 600))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(s)
    if max_profiles:
        uniq = uniq[:max_profiles]
    return uniq, (end_time or datetime.now(timezone.utc))
