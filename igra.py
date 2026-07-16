"""
igra.py — global radiosonde soundings from NOAA NCEI's Integrated Global
Radiosonde Archive (IGRA v2.2).

This gives the app worldwide radiosonde coverage (De Bilt, Camborne, Tateno,
Sydney, ...) to complement the U.S./Canada near-real-time soundings from IEM.

Robust file discovery: rather than guess each station's filename, we read the
year-to-date directory listing once and look up the exact file that contains the
station's 11-character IGRA ID (e.g. De Bilt = NLM00006260). We then download and
unzip it and parse the most recent sounding that actually has data. If the listing
can't be read, we fall back to guessed year-to-date names and finally to the
period-of-record file (whose naming is well established).

NCEI publishes IGRA expressly for programmatic download, so this is a sanctioned,
license-clean source. It is not real-time (files rebuild ~once a day), so we walk
back from the newest sounding to the last one with usable levels.
"""

import io
import os
import re
import time
import zipfile
from datetime import datetime, timezone

try:
    import requests
except Exception:                       # pragma: no cover
    requests = None

from paths import cache_root

_ACCESS = "https://www.ncei.noaa.gov/data/integrated-global-radiosonde-archive/access/"
Y2D_DIR = _ACCESS + "data-y2d/"                      # current-year files (small)
_POR_DIRS = [                                        # full record (confirmed naming)
    _ACCESS + "data-por/",
    "https://www1.ncdc.noaa.gov/pub/data/igra/data/data-por/",
]
_SUFFIXES = ["-data.txt.zip", "-y2d.txt.zip"]        # guesses if the listing fails

_UA = {"User-Agent": "ACARS-tracks/1.0 (radiosonde comparison; local use)"}

CACHE_DIR = os.path.join(cache_root(), "raob")
os.makedirs(CACHE_DIR, exist_ok=True)
_FRESH_SEC = 6 * 3600                    # re-download a station file at most every 6 h
_INDEX_FRESH = 12 * 3600                 # re-read the directory listing at most every 12 h
_MISSING = -8888                         # IGRA flags: -8888 / -9999 mean missing

_index = {"map": None, "ts": 0.0}        # {11-char IGRA id -> exact filename}


# --------------------------------------------------------------------------- #
#  directory listing -> exact filename                                        #
# --------------------------------------------------------------------------- #
def _load_index(session, timeout):
    if _index["map"] is not None and (time.time() - _index["ts"]) < _INDEX_FRESH:
        return _index["map"]
    hpath = os.path.join(CACHE_DIR, "_y2d_index.html")
    html = None
    if os.path.exists(hpath) and (time.time() - os.path.getmtime(hpath)) < _INDEX_FRESH:
        try:
            with open(hpath, "r", encoding="utf-8", errors="replace") as fh:
                html = fh.read()
        except OSError:
            html = None
    if html is None:
        try:
            r = session.get(Y2D_DIR, headers=_UA, timeout=timeout)
            if r.status_code == 200 and r.text:
                html = r.text
                try:
                    with open(hpath, "w", encoding="utf-8") as fh:
                        fh.write(html)
                except OSError:
                    pass
        except Exception:
            html = None
    if not html:
        return None
    mp = {}
    for fn in re.findall(r'href="([^"?]+?\.(?:zip|txt))"', html):
        fn = fn.split("/")[-1]
        if len(fn) >= 11:
            mp.setdefault(fn[:11], fn)
    _index["map"], _index["ts"] = mp, time.time()
    return mp


def _resolve_filename(igra_id, session, timeout):
    mp = _load_index(session, timeout)
    return mp.get(igra_id) if mp else None


# --------------------------------------------------------------------------- #
#  download + cache                                                           #
# --------------------------------------------------------------------------- #
def _get_one(url, session, timeout):
    try:
        r = session.get(url, headers=_UA, timeout=timeout, allow_redirects=True)
    except Exception as e:
        return None, type(e).__name__
    if r.status_code == 200 and r.content[:2] == b"PK":
        return r.content, 200
    return None, r.status_code


def _download_zip(igra_id, session, timeout):
    """Return (content_or_None, tried). Tries: exact name from the directory
    listing, then guessed y2d names, then the period-of-record file."""
    tried = []
    # 1) exact filename discovered from the directory listing (handles any naming)
    fn = _resolve_filename(igra_id, session, timeout)
    if fn:
        content, st = _get_one(Y2D_DIR + fn, session, timeout)
        tried.append(("y2d/" + fn, st))
        if content:
            return content, tried
    else:
        tried.append(("y2d-index", "not-found"))
    # 2) guessed year-to-date names
    for suf in _SUFFIXES:
        content, st = _get_one(Y2D_DIR + igra_id + suf, session, timeout)
        tried.append(("y2d" + suf, st))
        if content:
            return content, tried
    # 3) period-of-record fallback (full history, confirmed "<id>-data.txt.zip")
    for base in _POR_DIRS:
        content, st = _get_one(base + igra_id + "-data.txt.zip", session, max(timeout, 60))
        tried.append((base.split("/")[2] + "/por", st))
        if content:
            return content, tried
    return None, tried


def _get_text(igra_id, session, timeout):
    """Return (text_or_None, diag). Uses a short-lived disk cache."""
    zpath = os.path.join(CACHE_DIR, igra_id + ".zip")
    content, diag = None, ""
    fresh = (os.path.exists(zpath) and os.path.getsize(zpath) > 0
             and (time.time() - os.path.getmtime(zpath)) < _FRESH_SEC)
    if fresh:
        try:
            with open(zpath, "rb") as fh:
                content = fh.read()
        except OSError:
            content = None
    if content is None:
        content, tried = _download_zip(igra_id, session, timeout)
        if content:
            try:
                with open(zpath, "wb") as fh:
                    fh.write(content)
            except OSError:
                pass
        else:
            if os.path.exists(zpath):           # network failed -> stale copy
                try:
                    with open(zpath, "rb") as fh:
                        content = fh.read()
                except OSError:
                    content = None
            if content is None:
                diag = "download failed — " + ", ".join(f"{k}:{v}" for k, v in tried)
    if not content:
        return None, diag
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            return zf.read(zf.namelist()[0]).decode("utf-8", "replace"), ""
    except Exception as e:
        return None, f"file downloaded but could not be unzipped ({type(e).__name__})"


# --------------------------------------------------------------------------- #
#  parse (IGRA v2 fixed-width)                                                 #
# --------------------------------------------------------------------------- #
def _int(s):
    s = s.strip()
    if not s:
        return None
    try:
        v = int(s)
    except ValueError:
        return None
    return None if v <= _MISSING else v


def _header_time(line):
    try:
        year = int(line[13:17]); mon = int(line[18:20]); day = int(line[21:23])
        hour = int(line[24:26])
    except ValueError:
        return None
    if hour == 99:                               # nominal hour missing -> release time
        rt = _int(line[27:31])
        hour = (rt // 100) if rt is not None else 0
    try:
        return datetime(year, mon, day, hour % 24, tzinfo=timezone.utc)
    except ValueError:
        return None


def _levels_from(lines, idx):
    levels = []
    for ln in lines[idx + 1:]:
        if ln.startswith("#"):
            break
        if len(ln) < 51:
            continue
        press = _int(ln[9:15])               # Pa
        gph = _int(ln[16:21])                # m
        temp = _int(ln[22:27])               # tenths °C
        dpdp = _int(ln[34:39])               # tenths °C (dewpoint depression)
        wdir = _int(ln[40:45])               # deg
        wspd = _int(ln[46:51])               # tenths m/s
        if press is None or temp is None:
            continue
        tC = temp / 10.0
        td = (tC - dpdp / 10.0) if dpdp is not None else None
        levels.append({
            "p": float(press),
            "z": float(gph) if gph is not None else None,
            "T": tC + 273.15,
            "Td": (td + 273.15) if td is not None else None,
            "wdir": float(wdir) if wdir is not None else None,
            "wspd": (wspd / 10.0) if wspd is not None else None,
        })
    return levels


def _parse_latest(text, when=None):
    """Parse the station file and return (levels, obs_epoch). With no target time,
    walk back from the newest sounding to the last one with >=4 usable levels."""
    lines = text.splitlines()
    heads = []
    for i, ln in enumerate(lines):
        if ln.startswith("#"):
            dt = _header_time(ln)
            if dt is not None:
                heads.append((dt, i))
    if not heads:
        return [], None
    order = list(reversed(heads)) if when is None else \
        sorted(heads, key=lambda h: abs((h[0] - when).total_seconds()))
    best = None
    for dt, idx in order:
        levels = _levels_from(lines, idx)
        if len(levels) >= 4:
            return levels, dt.timestamp()
        if best is None and levels:
            best = (levels, dt.timestamp())
    return best if best else ([], None)


# --------------------------------------------------------------------------- #
#  public fetch                                                                #
# --------------------------------------------------------------------------- #
def fetch(station, when=None, session=None, timeout=30):
    """Fetch a global station's most recent IGRA sounding. `station` is a dict
    with an 'igra_id'. Returns a sounding dict (same shape as raob.fetch) or None.
    Prints a one-line [igra] diagnostic when it can't get data."""
    if requests is None:
        raise RuntimeError("the 'requests' package is required for live radiosonde data")
    igra_id = station.get("igra_id") if isinstance(station, dict) else None
    if not igra_id:
        return None
    text, diag = _get_text(igra_id, session or requests, timeout)
    if not text:
        print(f"[igra] {igra_id}: {diag or 'no data'}")
        return None
    levels, obs = _parse_latest(text, when)
    if len(levels) < 4:
        print(f"[igra] {igra_id}: downloaded OK but found no usable sounding "
              f"(parsed {len(levels)} levels).")
        return None
    nice = ((station.get("id") or "") + " " + (station.get("name") or "")).strip()
    return {"levels": levels, "icao": station.get("icao"),
            "wmo": (str(station.get("wmo")) if station.get("wmo") else None),
            "name": nice, "time": obs, "kind": "raob", "updown": "(radiosonde)"}
