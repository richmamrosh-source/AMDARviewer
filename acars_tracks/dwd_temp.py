"""
dwd_temp.py — fresh, global radiosondes by decoding DWD's open-data TEMP feed.

    https://opendata.dwd.de/weather/weather_reports/radiosonde/txt/

DWD relays the worldwide GTS upper-air stream as plain-text WMO TEMP bulletins
(files gda01-temp-<YYYYMMDDHHMM>.txt, refreshed every ~15 min, swelling near 00Z
and 12Z). These are the classic alphanumeric TEMP code (FM 35) — NOT a binary
format — so we can decode them in pure Python with no extra dependency, which is
exactly why this fits the app where BUFR/eccodes did not.

DWD open data may be reused commercially with attribution ("Source: Deutscher
Wetterdienst"), so it is clean to ship.

We decode the troposphere–to–100 hPa portion that the app actually plots:
  * TTAA — mandatory levels: pressure, temperature, dewpoint (from the depression),
           wind, plus the tropopause level.
  * TTBB — significant-temperature levels: pressure, temperature, dewpoint.
and merge them by pressure into the app's level format (p[Pa] T,Td[K] wdir[deg]
wspd[m/s]; height left to the plotter). High-altitude parts (TTCC/TTDD) and the
significant-wind section are left for a later pass.

`fetch_station(station)` reads the directory listing, downloads the recent files
that actually contain soundings, finds the requested WMO number's latest TTAA
(+TTBB), and returns a sounding dict — or None (with a one-line [dwd] reason) so
the caller can fall back to IGRA.
"""

import os
import re
import time
from datetime import datetime, timedelta, timezone

from paths import cache_root

DIR_URL = "https://opendata.dwd.de/weather/weather_reports/radiosonde/txt/"
CACHE_DIR = os.path.join(cache_root(), "raob_dwd")
os.makedirs(CACHE_DIR, exist_ok=True)
_UA = {"User-Agent": "acars-tracks/1.0 (radiosonde comparison; local use)"}
KT = 0.514444                                   # knots -> m/s

# pressure-indicator -> hPa for TEMP Part A (surface..100 hPa)
_PP_A = {"00": 1000, "92": 925, "85": 850, "70": 700, "50": 500, "40": 400,
         "30": 300, "25": 250, "20": 200, "15": 150, "10": 100}

_HEAD = re.compile(r"^[A-Z]{4}\d{2}\s+[A-Z]{4}\s+\d{6}")     # TTAAii CCCC DDHHMM
_FILE = re.compile(r"gda01-temp-(\d{12})\.txt")
_listing = {"items": None, "ts": 0.0, "bytes": 0}   # cached directory listing


# --------------------------------------------------------------------------- #
#  http + listing + download                                                  #
# --------------------------------------------------------------------------- #
def _http_get(url, timeout=90, text=False):
    try:
        import requests
        r = requests.get(url, timeout=timeout, headers=_UA)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        return r.text if text else r.content
    except ImportError:
        import urllib.request
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            return data.decode("ascii", "replace") if text else data


def _parse_listing(html):
    """-> list of (filename, datetime, size). Parsed line-by-line so it tolerates
    whatever exact autoindex format the server uses; size = last number on the line."""
    items = []
    for line in html.splitlines():
        m = re.search(r"gda01-temp-(\d{12})\.txt", line)
        if not m:
            continue
        stamp = m.group(1)
        try:
            dt = datetime.strptime(stamp, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        nums = re.findall(r"\d+", line.split(".txt", 1)[-1])   # numbers AFTER the name
        size = int(nums[-1]) if nums else 0
        items.append(("gda01-temp-%s.txt" % stamp, dt, size))
    seen, out = set(), []
    for it in sorted(items, key=lambda x: x[1], reverse=True):
        if it[0] not in seen:
            seen.add(it[0])
            out.append(it)
    return out


def _listing_items(timeout):
    if _listing["items"] is not None and (time.time() - _listing["ts"]) < 300:
        return _listing["items"]
    try:
        html = _http_get(DIR_URL, timeout=timeout, text=True)
    except Exception as e:
        return {"error": str(e)}
    items = _parse_listing(html)
    _listing["items"], _listing["ts"], _listing["bytes"] = items, time.time(), len(html)
    return items


def _download(fname, timeout=90):
    """Return (text_or_None, status). status is 'cache'/'200' or the error text."""
    dest = os.path.join(CACHE_DIR, fname)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        with open(dest, "rb") as fh:
            return fh.read().decode("ascii", "replace"), "cache"
    try:
        txt = _http_get(DIR_URL + fname, timeout=timeout, text=True)
    except Exception as e:
        return None, (str(e) or type(e).__name__)
    try:
        with open(dest, "w", encoding="ascii", errors="replace") as fh:
            fh.write(txt)
    except OSError:
        pass
    return txt, "200"


def _prune(keep):
    keep = set(keep)
    for fn in os.listdir(CACHE_DIR):
        if fn.endswith(".txt") and fn not in keep:
            try:
                os.remove(os.path.join(CACHE_DIR, fn))
            except OSError:
                pass


# --------------------------------------------------------------------------- #
#  TEMP code decoding                                                         #
# --------------------------------------------------------------------------- #
def _signed_temp(ttt):
    if not ttt or "/" in ttt or len(ttt) < 3:
        return None
    try:
        v = int(ttt)
    except ValueError:
        return None
    t = v / 10.0
    return -t if (v % 2) else t                  # odd tenths digit -> negative


def _dewpoint_dep(dd):
    if not dd or "/" in dd or len(dd) < 2:
        return None
    try:
        v = int(dd)
    except ValueError:
        return None
    if v <= 50:
        return v / 10.0                          # 00-50 -> 0.0..5.0 C
    if v >= 56:
        return float(v - 50)                     # 56-99 -> 6..49 C
    return None                                  # 51-55 unused


def _temp_group(g):
    """TTTDD -> (T_C, Td_C)."""
    if not g or len(g) < 5:
        return None, None
    T = _signed_temp(g[0:3])
    dep = _dewpoint_dep(g[3:5])
    Td = (T - dep) if (T is not None and dep is not None) else None
    return T, Td


def _wind_group(g, knots):
    """dddff -> (dir_deg, spd_m/s). Encodes >=100 kt via a non-multiple-of-5 dir."""
    if not g or len(g) < 5 or g[0:3] == "///" or "/" in g[3:5]:
        return None, None
    try:
        ddd = int(g[0:3]); ff = int(g[3:5])
    except ValueError:
        return None, None
    rem = ddd % 5
    direction = ddd - rem
    speed = ff + 100 * rem
    if direction == 0 and speed == 0:
        return 0.0, 0.0
    return float(direction % 360), (speed * KT if knots else float(speed))


def _mk(p_hpa, T, Td, wd, ws):
    if T is None:
        return None
    return {"p": round(float(p_hpa) * 100.0, 1), "z": None,
            "T": round(T + 273.15, 2),
            "Td": (round(Td + 273.15, 2) if Td is not None else None),
            "wdir": (round(float(wd), 1) if wd is not None else None),
            "wspd": (round(float(ws), 2) if ws is not None else None)}


_STOP = {"31313", "41414", "51515", "61616", "21212"}


def _levels_ttaa(groups, knots):
    levels, i, n = [], 0, len(groups)
    while i < n:
        g = groups[i]
        if g in _STOP:
            break
        if g.startswith("88"):                   # tropopause: 88PPP TTTDD dddff
            if g == "88999" or len(g) < 5:
                i += 1; continue
            try:
                p = int(g[2:5])
            except ValueError:
                i += 1; continue
            T, Td = _temp_group(groups[i + 1]) if i + 1 < n else (None, None)
            wd, ws = _wind_group(groups[i + 2], knots) if i + 2 < n else (None, None)
            lv = _mk(p, T, Td, wd, ws)
            if lv:
                levels.append(lv)
            i += 3; continue
        if g.startswith("77") or g.startswith("66"):   # max wind (wind only) -> skip
            i += 2 if g not in ("77999", "66999") else 1
            continue
        pp = g[0:2]
        if pp == "99":                           # surface: 99PPP
            try:
                p = int(g[2:5])
            except ValueError:
                i += 1; continue
            if p < 100:
                p += 1000
            T, Td = _temp_group(groups[i + 1]) if i + 1 < n else (None, None)
            wd, ws = _wind_group(groups[i + 2], knots) if i + 2 < n else (None, None)
            lv = _mk(p, T, Td, wd, ws)
            if lv:
                levels.append(lv)
            i += 3; continue
        if pp in _PP_A:
            T, Td = _temp_group(groups[i + 1]) if i + 1 < n else (None, None)
            wd, ws = _wind_group(groups[i + 2], knots) if i + 2 < n else (None, None)
            lv = _mk(_PP_A[pp], T, Td, wd, ws)
            if lv:
                levels.append(lv)
            i += 3; continue
        break                                    # unknown group -> avoid misalignment
    return levels


def _levels_ttbb(groups):
    levels, i, n = [], 0, len(groups)
    while i + 1 < n:
        g = groups[i]
        if g in _STOP or len(g) < 5:
            break
        ppp = g[2:5]
        if "/" in ppp:
            i += 2; continue
        try:
            p = int(ppp)
        except ValueError:
            break
        if p == 0:
            p = 1000
        T, Td = _temp_group(groups[i + 1])
        lv = _mk(p, T, Td, None, None)
        if lv:
            levels.append(lv)
        i += 2
    return levels


# --------------------------------------------------------------------------- #
#  split a file into TEMP bulletins                                           #
# --------------------------------------------------------------------------- #
_PARTS = ("TTAA", "TTBB", "TTCC", "TTDD", "PPAA", "PPBB", "PPCC", "PPDD")


def _bulletins(text):
    """Yield (part, yyggid, station5, groups) for every TTAA/TTBB report — including
    each station inside a multi-station *collective* bulletin (the report part and
    nominal time carry over to stations that don't repeat them)."""
    lines = text.splitlines()
    i, n = 0, len(lines)
    out = []
    while i < n:
        if not _HEAD.match(lines[i].strip()):
            i += 1
            continue
        # collect the whole bulletin body (until the next heading)
        body, i = [], i + 1
        while i < n and not _HEAD.match(lines[i].strip()):
            body.append(lines[i].strip())
            i += 1
        toks = " ".join(body).replace("=", " = ").split()
        # split into reports at '=' and interpret each, carrying part/time forward
        cur_part = cur_yy = None
        rep = []
        for t in toks + ["="]:
            if t != "=":
                rep.append(t)
                continue
            if rep:
                if rep[0] in _PARTS:
                    cur_part = rep[0]
                    if len(rep) > 1:
                        cur_yy = rep[1]
                    rest = rep[2:]
                else:
                    rest = rep                       # continuation: station + groups
                if rest and cur_part in ("TTAA", "TTBB") and re.fullmatch(r"\d{5}", rest[0]):
                    out.append((cur_part, cur_yy, rest[0], rest[1:]))
            rep = []
    return out


def _merge(levels):
    byp = {}
    for lv in levels:
        key = round(lv["p"] / 50.0)              # ~0.5 hPa bins
        if key in byp:
            ex = byp[key]
            for f in ("z", "T", "Td", "wdir", "wspd"):
                if ex[f] is None and lv[f] is not None:
                    ex[f] = lv[f]
        else:
            byp[key] = lv
    return sorted(byp.values(), key=lambda d: -d["p"])


def _knots(yyggid):
    try:
        return int(yyggid[0:2]) > 50
    except (ValueError, IndexError):
        return True


def _obs_epoch(yyggid, ref):
    """Approx obs time from YYGGId (day, hour), anchored to a reference file date."""
    try:
        yy = int(yyggid[0:2]); hour = int(yyggid[2:4])
    except (ValueError, IndexError):
        return None
    day = yy - 50 if yy > 50 else yy
    if not (1 <= day <= 31 and 0 <= hour <= 23):
        return None
    try:
        dt = ref.replace(day=day, hour=hour, minute=0, second=0, microsecond=0)
    except ValueError:
        return None
    if dt - ref > timedelta(hours=12):           # rolled into previous month
        dt = (dt.replace(day=1) - timedelta(days=1)).replace(
            day=day, hour=hour, minute=0, second=0, microsecond=0)
    return dt.timestamp()


# --------------------------------------------------------------------------- #
#  public entry point                                                          #
# --------------------------------------------------------------------------- #
def fetch_station(station, hours_back=14, end_time=None, session=None, timeout=90):
    """Latest DWD TEMP sounding for this station's WMO number, or None (with a
    one-line [dwd] reason printed) if the feed has nothing for it in the window."""
    if not isinstance(station, dict):
        return None
    wmo = station.get("wmo")
    if not wmo:
        return None
    wmo5 = str(wmo).zfill(5)
    sid = station.get("id", "") or wmo5

    items = _listing_items(timeout)
    if isinstance(items, dict):                  # {"error": ...}
        print(f"[dwd] {sid}: cannot read the DWD listing ({items.get('error')}) -> IGRA.")
        return None
    if not items:
        print(f"[dwd] {sid}: DWD listing empty -> IGRA.")
        return None

    now = end_time or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours_back)
    # files within the window that are big enough to hold soundings, newest first
    sel = [it for it in items if it[1] >= cutoff and it[2] > 1500][:48]
    try:
        _prune([it[0] for it in items[:80]])
    except OSError:
        pass

    found = {}                                   # part -> (yyggid, levels)
    ref = sel[0][1] if sel else now
    files_seen = matches = 0
    first_status = None
    seen_wmos = set()
    block = wmo5[:2]                             # WMO block (country group), e.g. "06"
    for fname, dt, size in sel:
        text, status = _download(fname, timeout=timeout)
        if first_status is None:
            first_status = status
        if not text:
            continue
        files_seen += 1
        for part, yyggid, st, groups in _bulletins(text):
            seen_wmos.add(st)
            if st != wmo5:
                continue
            matches += 1
            if part == "TTAA" and "TTAA" not in found:
                found["TTAA"] = (yyggid, _levels_ttaa(groups, _knots(yyggid)), dt)
            elif part == "TTBB" and "TTBB" not in found:
                found["TTBB"] = (yyggid, _levels_ttbb(groups), dt)
        if "TTAA" in found and "TTBB" in found:
            break

    if "TTAA" not in found:
        newest = items[0][1].strftime("%m-%d %H:%MZ") if items else "-"
        if files_seen == 0:
            print(f"[dwd] {sid}: listing OK ({len(items)} files, "
                  f"{_listing.get('bytes', 0)//1024}KB, newest {newest}); "
                  f"{len(sel)} matched the window; "
                  f"first download: {first_status or 'none attempted'} -> IGRA.")
        else:
            near = sorted(w for w in seen_wmos if w[:2] == block)[:12]
            print(f"[dwd] {sid}: scanned {files_seen} files, {len(seen_wmos)} stations, "
                  f"WMO {wmo5} not among them. Block-{block} stations seen: "
                  f"{near or 'none'} -> IGRA.")
        return None

    yyggid, levels, ref = found["TTAA"]
    if "TTBB" in found and found["TTBB"][0] == yyggid:       # same cycle only
        levels = levels + found["TTBB"][1]
    levels = _merge(levels)
    if len(levels) < 4:
        print(f"[dwd] {sid}: decoded only {len(levels)} levels -> IGRA.")
        return None

    obs = _obs_epoch(yyggid, ref)
    nice = ((station.get("id") or "") + " " + (station.get("name") or "")).strip()
    return {"levels": levels, "icao": station.get("icao"),
            "wmo": wmo5, "name": nice, "time": obs,
            "kind": "raob", "updown": "(radiosonde)", "source": "DWD"}
