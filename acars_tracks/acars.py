"""
acars.py — Download the last N hours of MADIS ACARS (en-route) netCDF files,
parse the individual aircraft observations, and group them into flight tracks by
aircraft id.

Output (same shape as demo.generate):
    tracks : list of {"id": str, "pts": [[lat, lon, alt_m, temp_c, dew_c,
                                          wspd_kt, wdir_deg, epoch, edr], ...]}
    generated_at : datetime (UTC)

`edr` is the maximum eddy dissipation rate (turbulence), cube-root form in
m^(2/3)/s, or None where the aircraft didn't report it (most do not — only a
subset of the fleet carries EDR).

Downloaded files are cached on disk; files outside the window are deleted.
Variable names vary between feeds, so each field is resolved from candidates.
"""

import gzip
import os
import re
from datetime import datetime, timedelta, timezone

from paths import cache_root
# real-time feed (latest ~24-48h) and the dated archive (older dates)
LIVE_URL = "https://madis-data.ncep.noaa.gov/madisPublic1/data/point/acars/netcdf/"
ARCHIVE_ROOT = "https://madis-data.ncep.noaa.gov/madisPublic1/data/archive/"
ARCHIVE_SUB = "/point/acars/netcdf/"
CACHE_DIR = os.path.join(cache_root(), "acars")
os.makedirs(CACHE_DIR, exist_ok=True)

MS_TO_KT = 1.943844

CANDIDATES = {
    "lat":  ["latitude", "Lat", "lat", "trackLat"],
    "lon":  ["longitude", "Lon", "lon", "trackLon"],
    "alt":  ["altitude", "GPSaltitude", "indAltitude", "flightLevel"],
    "temp": ["temperature", "temp"],
    "dew":  ["dewpoint", "dewpointTemperature", "dewPoint"],
    "wspd": ["windSpeed", "wspd"],
    "wdir": ["windDir", "wdir"],
    "edr":  ["maxEDR", "medEDR", "MAXEDR", "MEDEDR"],
    "time": ["timeObs", "obsTime", "time", "recptTime"],
    "tail": ["tailNumber", "en_tailNumber", "rptStation"],
}
_warned = set()


def _http_get(url, timeout=90):
    try:
        import requests
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": "acars-tracks/1.0"})
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


def _prune_cache(valid):
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


def _find(ds, key):
    for n in CANDIDATES[key]:
        if n in ds.variables:
            return ds.variables[n]
    return None


def _arr(var):
    import numpy as np
    a = np.ma.filled(np.ma.masked_invalid(np.ma.asarray(var[:], dtype=float)), np.nan)
    a[np.abs(a) > 1e30] = np.nan          # MADIS fill values (e.g. 3.4e38)
    return a


def _tails(var, n):
    import netCDF4
    import numpy as np
    try:
        out = netCDF4.chartostring(var[:])
        vals = [str(s).strip().strip("\x00") for s in np.atleast_1d(out)]
        if len(vals) == n:
            return vals
    except Exception:
        pass
    return None


def _parse(blob, fname, obs):
    import netCDF4
    import numpy as np
    ds = netCDF4.Dataset("inmem", mode="r", memory=gzip.decompress(blob))
    try:
        v_lat, v_lon = _find(ds, "lat"), _find(ds, "lon")
        v_time = _find(ds, "time")
        if v_lat is None or v_lon is None or v_time is None:
            if fname not in _warned:
                print(f"  [{fname}] missing lat/lon/time; vars="
                      f"{sorted(ds.variables)[:20]}")
                _warned.add(fname)
            return
        lat, lon, tm = _arr(v_lat), _arr(v_lon), _arr(v_time)
        n = len(lat)

        def col(key):
            v = _find(ds, key)
            return _arr(v) if v is not None else np.full(n, np.nan)

        alt = col("alt"); temp = col("temp"); dew = col("dew")
        wspd = col("wspd"); wdir = col("wdir"); edr = col("edr")
        v_tail = _find(ds, "tail")
        tails = _tails(v_tail, n) if v_tail is not None else None

        for i in range(n):
            if not (np.isfinite(lat[i]) and np.isfinite(lon[i]) and np.isfinite(tm[i])):
                continue
            if abs(lat[i]) > 90 or abs(lon[i]) > 180:   # drop fill/garbage coords
                continue
            tid = (tails[i] if tails else "") or "UNKNOWN"
            ws_kt = round(float(wspd[i]) * MS_TO_KT, 1) if np.isfinite(wspd[i]) else None
            # MADIS embeds "bad data" codes (~2.49-2.54) in the EDR field; real
            # cube-root EDR is ~0-1, so anything >= 2 (or negative) is a flag, not data
            e = float(edr[i]) if np.isfinite(edr[i]) else None
            edr_val = round(max(0.0, e), 3) if (e is not None and -0.1 < e < 2.0) else None
            obs.setdefault(tid, []).append([
                round(float(lat[i]), 4), round(float(lon[i]), 4),
                round(float(alt[i])) if np.isfinite(alt[i]) else None,
                round(float(temp[i]) - 273.15, 1) if np.isfinite(temp[i]) else None,
                round(float(dew[i]) - 273.15, 1) if np.isfinite(dew[i]) else None,
                ws_kt,
                round(float(wdir[i])) if np.isfinite(wdir[i]) else None,
                float(tm[i]),
                edr_val,
            ])
    finally:
        ds.close()


def fetch(hours=6, max_tracks=None, end_time=None, archive=False):
    """Download + parse + group. Returns (tracks, generated_at). Raises on hard failure.

    end_time/archive let you pull a historical day from the MADIS archive instead
    of the live feed; the window is the `hours` ending at end_time.
    """
    names = _hourly_names(hours, end_time)
    if not archive:
        _prune_cache([fn for fn, _ in names])

    obs = {}
    got = False
    for fname, dt in names:
        blob = _download(fname, dt, archive)
        if blob:
            got = True
            try:
                _parse(blob, fname, obs)
            except Exception as e:
                print(f"  [{fname}] parse error: {e}")
    if not got:
        raise RuntimeError("Could not download any ACARS files "
                           "(network blocked or feed unavailable).")

    end = end_time or datetime.now(timezone.utc)
    cutoff = (end - timedelta(hours=hours)).timestamp()
    tracks = []
    for tid, pts in obs.items():
        pts = [p for p in pts if p[7] >= cutoff]
        if len(pts) < 2:
            continue
        pts.sort(key=lambda p: p[7])
        # drop exact-duplicate fixes
        dedup = [pts[0]]
        for p in pts[1:]:
            if p[0] != dedup[-1][0] or p[1] != dedup[-1][1]:
                dedup.append(p)
        if len(dedup) >= 2:
            tracks.append({"id": tid, "pts": dedup})

    # most points first; optional cap to bound payload
    tracks.sort(key=lambda t: len(t["pts"]), reverse=True)
    if max_tracks:
        tracks = tracks[:max_tracks]
    return tracks, end
