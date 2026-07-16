"""
madis_raob.py — near-real-time global radiosondes from the MADIS public feed.

    https://madis-data.ncep.noaa.gov/madisPublic1/data/point/raob/netcdf/

This is the same flavor of public NOAA netCDF the app already pulls for aircraft
(see acars.py / profiles.py), so it needs no new dependency — just netCDF4, which
is already required. MADIS receives radiosonde reports off the GTS within a few
hours of launch, so this can deliver *fresh* soundings (last 00Z/12Z), unlike the
IGRA archive which lags ~2 days.

MADIS stores a raob split across level groups: mandatory levels carry pressure,
height, temperature, dewpoint, and wind together; significant-temperature levels
add extra thermodynamic detail. We merge the two by pressure into one descending
profile (p[Pa] z[m] T,Td[K] wdir[deg] wspd[m/s]).

`fetch_station(station)` scans the recent hourly files newest-first and returns the
most recent sounding for that station's WMO number, or None. When it finds nothing
it prints a one-line [madis-raob] diagnostic saying *why* (feed unreachable, the
station's WMO absent from the public feed, or a variable-name mismatch), so the
cause is unambiguous in the console.
"""

import gzip
import os
from datetime import datetime, timedelta, timezone

from paths import cache_root

LIVE_URL = "https://madis-data.ncep.noaa.gov/madisPublic1/data/point/raob/netcdf/"
ARCHIVE_ROOT = "https://madis-data.ncep.noaa.gov/madisPublic1/data/archive/"
ARCHIVE_SUB = "/point/raob/netcdf/"
CACHE_DIR = os.path.join(cache_root(), "raob_madis")
os.makedirs(CACHE_DIR, exist_ok=True)

_UA = {"User-Agent": "acars-tracks/1.0"}

CAND = {
    "wmo":   ["wmoStaNum", "wmoStat", "wmoStaId", "wmoId"],
    "name":  ["staName", "stationName", "staId"],
    "time":  ["relTime", "synTime", "timeObs", "timeNominal", "validTime"],
    "nman":  ["numMand", "nMand", "numMandatory", "numMandLvl"],
    "nsigt": ["numSigT", "nSigT", "numSigTLevel", "numSigTLvl"],
    "prMan": ["prMan"], "htMan": ["htMan"], "tpMan": ["tpMan"],
    "tdMan": ["tdMan"], "wdMan": ["wdMan"], "wsMan": ["wsMan"],
    "prSigT": ["prSigT"], "tpSigT": ["tpSigT"], "tdSigT": ["tdSigT"],
}


# --------------------------------------------------------------------------- #
#  download / cache  (mirrors profiles.py; returns a status for diagnostics)  #
# --------------------------------------------------------------------------- #
def _http_get(url, timeout=90):
    try:
        import requests
        r = requests.get(url, timeout=timeout, headers=_UA)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        return r.content
    except ImportError:
        import urllib.request
        req = urllib.request.Request(url, headers=_UA)
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


def _download(fname, dt, archive=False, timeout=90):
    """Return (blob_or_None, status). status is 'cache'/'200' on success or the
    error text (e.g. 'HTTP 404') on failure, for diagnostics."""
    dest = os.path.join(CACHE_DIR, fname)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        with open(dest, "rb") as fh:
            return fh.read(), "cache"
    try:
        blob = _http_get(_url_for(fname, dt, archive), timeout=timeout)
    except Exception as e:
        return None, (str(e) or type(e).__name__)
    try:
        with open(dest, "wb") as fh:
            fh.write(blob)
    except OSError:
        pass
    return blob, "200"


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


def _clean(x):
    np = _np()
    a = np.ma.masked_invalid(np.ma.asarray(x, dtype=float))
    out = np.ma.filled(a, np.nan)
    out[np.abs(out) > 1e30] = np.nan          # MADIS fill values (e.g. 3.4e38)
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


def _row(ds, key, i):
    v = _find(ds, key)
    if v is None or getattr(v, "ndim", 0) != 2:
        return None
    try:
        return _clean(v[i, :])
    except Exception:
        return None


def _count(ds, key, i, default):
    v = _find(ds, key)
    if v is None or getattr(v, "ndim", 0) != 1:
        return default
    try:
        c = _clean(v[:])[i]
        return int(c) if c == c else default
    except Exception:
        return default


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


def _epoch_from(val, fname):
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    if v > 1e11:
        return v / 1000.0
    if v > 1e8:
        return v
    if 0 <= v <= 86401:
        try:
            d = datetime.strptime(fname[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
            return d.timestamp() + v
        except Exception:
            return None
    return v


# --------------------------------------------------------------------------- #
#  parse one station's sounding from a file                                   #
# --------------------------------------------------------------------------- #
def _levels_for_record(ds, i):
    np = _np()
    out = []
    pr = _row(ds, "prMan", i)
    if pr is not None:
        pr = _to_pa(pr)
        ht = _row(ds, "htMan", i); tp = _row(ds, "tpMan", i); td = _row(ds, "tdMan", i)
        wd = _row(ds, "wdMan", i); ws = _row(ds, "wsMan", i)
        tp = _to_K(tp) if tp is not None else None
        td = _to_K(td) if td is not None else None
        n = _count(ds, "nman", i, len(pr))
        for j in range(max(0, min(n, len(pr)))):
            lv = _level(pr[j],
                        ht[j] if ht is not None else np.nan,
                        tp[j] if tp is not None else np.nan,
                        td[j] if td is not None else np.nan,
                        wd[j] if wd is not None else np.nan,
                        ws[j] if ws is not None else np.nan)
            if lv:
                out.append(lv)
    prs = _row(ds, "prSigT", i)
    if prs is not None:
        prs = _to_pa(prs)
        tps = _row(ds, "tpSigT", i); tds = _row(ds, "tdSigT", i)
        tps = _to_K(tps) if tps is not None else None
        tds = _to_K(tds) if tds is not None else None
        n = _count(ds, "nsigt", i, len(prs))
        for j in range(max(0, min(n, len(prs)))):
            lv = _level(prs[j], np.nan,
                        tps[j] if tps is not None else np.nan,
                        tds[j] if tds is not None else np.nan,
                        np.nan, np.nan)
            if lv:
                out.append(lv)
    byp = {}
    for lv in out:
        key = round(lv["p"] / 50.0)
        if key in byp:
            ex = byp[key]
            for f in ("z", "T", "Td", "wdir", "wspd"):
                if ex[f] is None and lv[f] is not None:
                    ex[f] = lv[f]
        else:
            byp[key] = lv
    return sorted(byp.values(), key=lambda d: -d["p"])


def _make(station, levels, obs):
    nice = ((station.get("id") or "") + " " + (station.get("name") or "")).strip()
    return {"levels": levels, "icao": station.get("icao"),
            "wmo": (str(station.get("wmo")) if station.get("wmo") else None),
            "name": nice, "time": obs, "kind": "raob", "updown": "(radiosonde)"}


def _open(blob):
    import netCDF4
    return netCDF4.Dataset("inmem", mode="r", memory=gzip.decompress(blob))


def _wmo_array(ds):
    np = _np()
    wv = _find(ds, "wmo")
    if wv is None:
        return None
    wa = np.ma.filled(np.ma.masked_invalid(np.ma.asarray(wv[:], dtype="float64")), -1)
    return wa.astype("int64")


def _parse_station(blob, fname, wmo_i, station):
    np = _np()
    ds = _open(blob)
    try:
        wa = _wmo_array(ds)
        if wa is None:
            return None
        idxs = list(np.where(wa == wmo_i)[0])
        if not idxs:
            return None
        tv = _find(ds, "time")
        if tv is not None and len(idxs) > 1:
            ta = _clean(tv[:])
            idxs.sort(key=lambda k: (ta[k] if k < len(ta) and np.isfinite(ta[k]) else -1),
                      reverse=True)
        for i in idxs:
            levels = _levels_for_record(ds, int(i))
            if len(levels) >= 4:
                obs = None
                if tv is not None:
                    try:
                        obs = _epoch_from(_clean(tv[:])[int(i)], fname)
                    except Exception:
                        obs = None
                return _make(station, levels, obs)
        return None
    finally:
        ds.close()


# --------------------------------------------------------------------------- #
#  diagnostics — say *why* a station came up empty                            #
# --------------------------------------------------------------------------- #
def _inspect(blob, wmo_i):
    """Peek inside one file: WMO-id variable used, sounding count, a sample of the
    WMO numbers present, and whether the target is among them."""
    np = _np()
    ds = _open(blob)
    try:
        if _find(ds, "wmo") is None:
            return {"wmo_var": None, "vars": sorted(ds.variables)[:30]}
        wname = next((n for n in CAND["wmo"] if n in ds.variables), "?")
        wa = _wmo_array(ds)
        valid = sorted({int(x) for x in wa if x > 0})
        return {"wmo_var": wname, "n": int(len(wa)), "present": wmo_i in set(valid),
                "sample": valid[:14], "n_intl": sum(1 for w in valid
                                                     if not (70000 <= w <= 74999)),
                "has_prMan": "prMan" in ds.variables}
    finally:
        ds.close()


def _diagnose_miss(station, wmo_i, n_dl, last_status, newest_blob, n_files, names):
    sid = station.get("id", "") or str(station.get("wmo", ""))
    if n_dl == 0 or newest_blob is None:
        print(f"[madis-raob] {sid}: downloaded 0/{n_files} files (last status: "
              f"{last_status}; tried {names[0][0]} under the public raob feed) -> IGRA.")
        return
    try:
        info = _inspect(newest_blob, wmo_i)
    except Exception as e:
        print(f"[madis-raob] {sid}: got {n_dl} file(s) but couldn't inspect "
              f"({type(e).__name__}) -> IGRA.")
        return
    if info.get("wmo_var") is None:
        print(f"[madis-raob] {sid}: file has no WMO-id variable -> vars present: "
              f"{info['vars']}")
    elif info.get("present"):
        print(f"[madis-raob] {sid}: WMO {wmo_i} IS in the public feed but no sounding "
              f"parsed (prMan present: {info.get('has_prMan')}) -> variable-name mismatch.")
    else:
        print(f"[madis-raob] {sid}: {info.get('n')} raobs in newest public file "
              f"({info.get('n_intl')} non-US); WMO {wmo_i} not among them. "
              f"Sample WMOs: {info.get('sample')} -> IGRA.")


# --------------------------------------------------------------------------- #
#  public entry point                                                          #
# --------------------------------------------------------------------------- #
def fetch_station(station, hours_back=14, end_time=None, session=None, timeout=90):
    """Most recent MADIS public sounding for this station's WMO number, or None
    (with a one-line [madis-raob] reason printed) if the public feed has nothing."""
    if not isinstance(station, dict):
        return None
    wmo = station.get("wmo")
    if not wmo:
        return None
    try:
        wmo_i = int(str(wmo).lstrip("0") or "0")
    except ValueError:
        return None
    names = _hourly_names(hours_back, end_time)
    try:
        _prune([fn for fn, _ in names])
    except OSError:
        pass
    n_dl, newest_blob, last_status = 0, None, None
    for fname, dt in names:                       # newest first
        blob, status = _download(fname, dt, timeout=timeout)
        if blob is None:
            last_status = status
            continue
        n_dl += 1
        if newest_blob is None:
            newest_blob = blob
        try:
            snd = _parse_station(blob, fname, wmo_i, station)
        except Exception as e:
            print(f"[madis-raob] parse error on {fname}: {type(e).__name__}: {e}")
            continue
        if snd:
            return snd
    _diagnose_miss(station, wmo_i, n_dl, last_status, newest_blob, len(names), names)
    return None
