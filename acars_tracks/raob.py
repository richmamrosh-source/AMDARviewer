"""
raob.py — fetch and parse the latest radiosonde (rawinsonde) soundings.

Source: Iowa Environmental Mesonet (IEM) JSON web service
(mesonet.agron.iastate.edu/json/raob.py), which is built for programmatic
access (CORS-enabled, no scraping) and returns clean JSON with labeled columns.
We parse it into the same level format the rest of the app uses, so a radiosonde
flows through the very same Skew-T / hodograph / analysis pipeline as an aircraft
sounding.

IEM serves the U.S. and Canada in near real time. For worldwide coverage, global
stations (marked src='igra') are pulled from NOAA NCEI's Integrated Global
Radiosonde Archive instead — see igra.py.

(The University of Wyoming archive used to be the go-to source, but its legacy
CGI now blocks automated access and serves a stale default page, so we use IEM.)

Radiosondes launch at 00Z and 12Z; this picks the most recent one likely to be
available and falls back to the previous launch if needed.

`demo_sounding()` makes a synthetic radiosonde so the offline demo works without
a network.
"""

from datetime import datetime, timedelta, timezone

import numpy as np

try:
    import requests
except Exception:                       # pragma: no cover
    requests = None

IEM_URL = "https://mesonet.agron.iastate.edu/json/raob.py"
# University of Wyoming upper-air archive — the canonical *global* radiosonde
# source (De Bilt and hundreds of other WMO stations worldwide). Used for any
# station tagged src="uwyo", and as a fallback when IEM has nothing. Same legacy
# CGI that siphon / RAOBget / RocketPy use; a browser UA + the region parameter
# are required (without region it redirects to a landing page).
UWYO_URL = "https://weather.uwyo.edu/cgi-bin/sounding"
_UA = {"User-Agent": "ACARS-tracks/1.0 (sounding comparison; local use)"}
_BROWSER_UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/124.0.0.0 Safari/537.36")}
KT = 0.514444                           # knots -> m/s

# The MADIS *public* radiosonde feed turned out to carry only the US NWS network
# (international GTS raobs are in its restricted tier), and US stations already use
# IEM — so trying MADIS first adds download overhead with no benefit for global
# stations. It's therefore OFF by default; enable with --madis-raob (e.g. if you
# have access to a feed that includes international raobs). See madis_raob.py.
PREFER_MADIS = False

# Real-time international soundings via DWD's open-data TEMP feed were tried but
# made international-station clicks slow (each click downloads a directory listing
# plus dozens of bulletin files). Reverted to OFF: global stations use the IGRA
# archive only, exactly as before. Flip to True (or pass nothing/--no-dwd controls
# it) to re-enable the experimental fresh feed. See dwd_temp.py.
PREFER_DWD = False


# --------------------------------------------------------------------------- #
#  timing                                                                      #
# --------------------------------------------------------------------------- #
def latest_synoptic(now=None, lag_hours=2.5):
    """Most recent 00Z/12Z launch likely to be available (allowing a data lag)."""
    now = now or datetime.now(timezone.utc)
    t = now - timedelta(hours=lag_hours)
    hour = 12 if t.hour >= 12 else 0
    return t.replace(hour=hour, minute=0, second=0, microsecond=0)


def _cycle_label(dt):
    """Human label for a synoptic cycle, e.g. '00Z Jun 27' (cross-platform)."""
    return "%02dZ %s %d" % (dt.hour, dt.strftime("%b"), dt.day)


# --------------------------------------------------------------------------- #
#  live fetch + parse (IEM JSON)                                               #
# --------------------------------------------------------------------------- #
def _find_levels(obj):
    """Recursively find the list of per-level dicts in the IEM JSON, so we don't
    depend on the exact wrapper key names."""
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and any(
                k in obj[0] for k in ("pressure_mb", "pressure", "pres")):
            return obj
        for it in obj:
            found = _find_levels(it)
            if found:
                return found
    elif isinstance(obj, dict):
        for v in obj.values():
            found = _find_levels(v)
            if found:
                return found
    return None


def _find_str(obj, *keys):
    """Find the first string value stored under any of `keys`, anywhere."""
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and isinstance(obj[k], str) and obj[k]:
                return obj[k]
        for v in obj.values():
            r = _find_str(v, *keys)
            if r:
                return r
    elif isinstance(obj, list):
        for it in obj:
            r = _find_str(it, *keys)
            if r:
                return r
    return None


def _num(row, *keys):
    for k in keys:
        if k in row and row[k] is not None:
            try:
                return float(row[k])
            except (TypeError, ValueError):
                pass
    return None


def _parse_iem(data, when=None):
    """Parse the IEM raob JSON -> (levels, station_name, obs_epoch)."""
    rows = _find_levels(data)
    if not rows:
        return [], "", None
    levels = []
    for row in rows:
        P = _num(row, "pressure_mb", "pressure", "pres")
        T = _num(row, "tmpc", "tmpc_c", "temp")
        if P is None or T is None:
            continue
        Td = _num(row, "dwpc", "dwpc_c", "dwpt")
        drct = _num(row, "drct", "wind_dir")
        sknt = _num(row, "speed_kts", "smps_kts", "sknt", "speed")
        z = _num(row, "height_m", "height", "hght")
        levels.append({
            "p": P * 100.0,
            "z": z,
            "T": T + 273.15,
            "Td": (Td + 273.15) if Td is not None else None,
            "wdir": drct,
            "wspd": (sknt * KT) if sknt is not None else None,
        })
    name = _find_str(data, "station", "name", "sid") or ""
    valid = _find_str(data, "valid", "utc_valid", "validUTC")
    obs = None
    if valid:
        try:
            obs = datetime.fromisoformat(valid.replace("Z", "+00:00")).timestamp()
        except ValueError:
            obs = None
    if obs is None and when is not None:
        obs = when.timestamp()
    return levels, name, obs


def fetch(station, when=None, session=None, tries=2, timeout=20):
    """Fetch a station's latest sounding. Returns a sounding dict or None.

    `station` is a station dict (with 'icao'/'wmo'/'name') or an ICAO string.
    U.S./Canada stations come from IEM (near real-time); global stations (marked
    src='igra') come from NOAA NCEI's Integrated Global Radiosonde Archive.
    Tries the chosen launch time, then the previous one(s) if empty.
    """
    if requests is None:
        raise RuntimeError("the 'requests' package is required for live radiosonde data")
    # Global stations: freshest-first.
    if isinstance(station, dict) and station.get("src") == "igra":
        if when is None and station.get("wmo"):
            # 1) DWD open-data TEMP feed — near-real-time, global, pure text.
            if PREFER_DWD:
                try:
                    import dwd_temp
                    snd = dwd_temp.fetch_station(
                        station, session=session, timeout=max(timeout, 60))
                    if snd and len(snd.get("levels", [])) >= 4:
                        return snd
                    # dwd_temp printed a one-line reason; fall through
                except Exception as e:
                    print(f"[raob] DWD feed unavailable ({type(e).__name__}); "
                          f"trying next source")
            # 2) MADIS public radiosonde feed (off by default; US-only tier).
            if PREFER_MADIS:
                try:
                    import madis_raob
                    snd = madis_raob.fetch_station(
                        station, session=session, timeout=max(timeout, 60))
                    if snd and len(snd.get("levels", [])) >= 4:
                        return snd
                except Exception as e:
                    print(f"[raob] MADIS raob unavailable ({type(e).__name__}); using IGRA")
        # 3) IGRA archive (global, ~2-day lag) — always-available fallback.
        try:
            import igra
        except Exception:
            return None
        return igra.fetch(station, when=when, session=session, timeout=max(timeout, 30))
    if isinstance(station, dict):
        icao = station.get("icao") or station.get("id") or ""
        wmo = station.get("wmo")
        nice = (station.get("id") or "") + " " + (station.get("name") or "")
    else:
        icao, wmo, nice = str(station), None, str(station)
    sess = session or requests
    base = when or latest_synoptic()
    for k in range(max(1, tries)):
        t = base - timedelta(hours=12 * k)
        params = {"station": icao, "ts": t.strftime("%Y-%m-%dT%H:00:00Z")}
        r = sess.get(IEM_URL, params=params, headers=_UA, timeout=timeout)
        if r.status_code != 200:
            continue
        try:
            data = r.json()
        except ValueError:
            continue
        levels, name, obs = _parse_iem(data, t)
        if len(levels) >= 4:
            snd = {"levels": levels, "icao": icao, "wmo": (str(wmo) if wmo else None),
                   "name": nice.strip() or name, "time": obs,
                   "kind": "raob", "updown": "(radiosonde)"}
            if k > 0:
                # the requested cycle(s) weren't launched; we fell back to an earlier one
                snd["launch_miss"] = _cycle_label(base)
                snd["shown_cycle"] = _cycle_label(t)
            return snd
    return None


# --------------------------------------------------------------------------- #
#  synthetic radiosonde (offline demo)                                         #
# --------------------------------------------------------------------------- #
def _std_z(p_pa):
    """Height (m) from pressure (Pa), US standard atmosphere troposphere."""
    return (1.0 - (p_pa / 101325.0) ** (1 / 5.25588)) / 2.25577e-5


def demo_sounding(station, when=None):
    """A plausible synthetic radiosonde for `station`, surface up to ~30 hPa."""
    when = when or latest_synoptic()
    wmo = str(station.get("wmo", "00000"))
    lat = float(station.get("lat", 42.0))
    rng = np.random.default_rng(int(wmo) ^ int(when.timestamp()) // 43200)

    sfc_p = 1010.0 - rng.uniform(0, 18) - max(0.0, (lat - 30) * 0.15)
    sfc_t = 26.0 - (lat - 35.0) * 0.55 + rng.uniform(-3, 4)
    sfc_dep = rng.uniform(4.0, 11.0)
    gamma = rng.uniform(5.6, 6.6) / 1000.0         # tropospheric lapse, K per m
    z_trop = rng.uniform(10500, 12800)             # tropopause height (m)
    strat_rate = rng.uniform(0.8, 1.8) / 1000.0    # stratospheric warming, K per m
    sfc_dir = rng.uniform(170, 250)
    jet_kt = 35 + 65 * rng.uniform(0.3, 1.0)
    t_trop = sfc_t - gamma * z_trop

    ladder = [sfc_p, 1000, 925, 850, 800, 700, 600, 500, 400, 350, 300,
              275, 250, 225, 200, 175, 150, 125, 100, 80, 70, 50, 30]
    levels = []
    seen = set()
    for p in sorted({round(x) for x in ladder if x <= sfc_p}, reverse=True):
        if p in seen:
            continue
        seen.add(p)
        z = _std_z(p * 100.0)
        if z <= z_trop:                            # troposphere: steady lapse rate
            T = sfc_t - gamma * z
            dep = sfc_dep + (z / z_trop) * 13.0 + rng.uniform(-1.2, 1.2)
        else:                                       # stratosphere: slight warming, very dry
            T = t_trop + (z - z_trop) * strat_rate
            dep = 22.0 + rng.uniform(0, 12)
        Td = T - max(0.6, dep)
        # winds: veer and strengthen to the jet near the tropopause, ease above
        h = z / 11000.0
        spd_kt = 6 + jet_kt * min(h, 1.0) * (1.6 - 0.6 * max(0.0, h - 1.0))
        direction = (sfc_dir + 50 * min(h, 1.2) + rng.uniform(-8, 8)) % 360
        levels.append({
            "p": p * 100.0, "z": round(z, 1),
            "T": round(T + 273.15, 2), "Td": round(Td + 273.15, 2),
            "wdir": round(float(direction), 1), "wspd": round(max(0.0, spd_kt) * KT, 2),
        })
    return {"levels": levels, "wmo": wmo, "name": f"{station.get('id','')} {station.get('name','')}".strip(),
            "time": when.timestamp(), "kind": "raob", "updown": "(radiosonde, demo)"}
