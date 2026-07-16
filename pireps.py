"""
pireps.py — fetch recent pilot reports (PIREPs/AIREPs) and classify each as
turbulence, icing, both, smooth (nil), or other.

Source: NOAA/NWS Aviation Weather Center public Data API
(aviationweather.gov/api/data/pirep). These are real pilot observations — point
reports, no interpolation — and are public and current (updated every minute).

Each report is reduced to:
    {lat, lon, fl, cat, tb, ic, sev, ac, raw, time}
where `cat` is one of: turb | icing | both | nil | other, and `sev` (0-4) is the
strongest intensity reported, used to size the marker.

`demo()` makes synthetic PIREPs so the offline demo works without a network.
"""

import re
from datetime import datetime, timedelta, timezone

try:
    import requests
except Exception:                       # pragma: no cover
    requests = None

AWC_URL = "https://aviationweather.gov/api/data/pirep"
# The PIREP endpoint requires a bounding box. Order is lat0,lon0,lat1,lon1 =
# minLat,minLon,maxLat,maxLon (current AWC OpenAPI spec). CONUS + a margin.
CONUS_BBOX = "20,-130,55,-60"
# aviationweather.gov filters non-browser User-Agents (returns 403); use a
# browser-like UA that still identifies this app.
_UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36 ACARS-tracks/1.0"),
    "Accept": "application/json, text/plain, */*",
}


class PirepHTTPError(Exception):
    """Raised when the AWC API returns a 4xx/5xx so the status code can surface."""
    def __init__(self, status, body=""):
        self.status = status
        self.body = (body or "")[:300]
        super().__init__("HTTP %s" % status)

# turbulence / icing intensity -> 0..4 severity rank
_INT = {
    "NEG": 0, "NHN": 0, "NONE": 0, "SMTH": 0, "SMOOTH": 0, "SMTH-LGT": 0.5,
    "TRC": 0.5, "TRC-LGT": 0.75, "LGT": 1, "LGT-MOD": 1.5, "MOD": 2,
    "MOD-SEV": 2.5, "SEV": 3, "SEV-EXTM": 3.5, "EXTM": 4,
}


def _sev(code):
    if not code:
        return None
    return _INT.get(str(code).upper().strip().replace(" ", "-"))


def _from_raw(raw, tag):
    """Pull the intensity token after /TB or /IC in a raw PIREP."""
    if not raw:
        return None
    m = re.search(r"/%s\s+([A-Z][A-Z\-]*)" % tag, raw.upper())
    return m.group(1) if m else None


def _classify(tb, ic):
    """Return (cat, sev) from turbulence/icing intensity codes."""
    ts, isc = _sev(tb), _sev(ic)
    has_tb = ts is not None and ts > 0
    has_ic = isc is not None and isc > 0
    if has_tb and has_ic:
        cat = "both"
    elif has_tb:
        cat = "turb"
    elif has_ic:
        cat = "icing"
    elif ts == 0 or isc == 0:
        cat = "nil"                       # explicitly negative / smooth
    else:
        cat = "other"                     # position/wind/temp only, no hazard field
    sev = max(ts or 0, isc or 0)
    return cat, sev


def _norm(obj):
    """Normalize a GeoJSON feature or a flat JSON object into our report dict."""
    props = obj.get("properties", obj) if isinstance(obj, dict) else {}
    geom = obj.get("geometry") or {} if isinstance(obj, dict) else {}
    coords = geom.get("coordinates")
    if coords and len(coords) >= 2:
        lon, lat = coords[0], coords[1]
    else:
        lat, lon = props.get("lat"), props.get("lon")
    if lat is None or lon is None:
        return None
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if abs(lat) > 90 or abs(lon) > 180:
        return None

    raw = props.get("rawOb") or props.get("raw_text") or props.get("rawText") or ""
    tb = (props.get("tbInt1") or props.get("tbInt2") or props.get("tbInt")
          or _from_raw(raw, "TB"))
    ic = (props.get("icgInt1") or props.get("icgInt2") or props.get("icgInt")
          or _from_raw(raw, "IC"))
    cat, sev = _classify(tb, ic)

    fl = props.get("fltlvl") or props.get("flightLevel")
    try:
        fl = int(fl) if fl not in (None, "", "UNKN") else None
    except (TypeError, ValueError):
        fl = None

    t = props.get("obsTime") or props.get("observationTime")
    epoch = None
    if isinstance(t, (int, float)):
        epoch = float(t)
    elif isinstance(t, str) and t:
        try:
            epoch = datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
        except ValueError:
            epoch = None

    return {
        "lat": round(lat, 4), "lon": round(lon, 4), "fl": fl,
        "cat": cat, "sev": round(sev, 2),
        "tb": (str(tb).upper() if tb else None),
        "ic": (str(ic).upper() if ic else None),
        "tbType": props.get("tbType1") or None,
        "icType": props.get("icgType1") or None,
        "ac": props.get("acType") or props.get("aircraftRef") or None,
        "raw": raw, "time": epoch,
    }


def fetch(hours=6, end_time=None, session=None, timeout=30):
    """Fetch recent PIREPs/AIREPs. Returns a list of report dicts (possibly empty).

    The AWC PIREP endpoint *requires* a bounding box (`bbox`) — without one it
    returns no data ("no bounding box"). bbox order is lat0,lon0,lat1,lon1 i.e.
    minLat,minLon,maxLat,maxLon (per the current AWC OpenAPI spec). We cover CONUS
    plus a margin. The "hours back" parameter name differs by endpoint, so we try
    `age` then `hours`, then a bbox-only "latest" call, falling through on any 4xx.
    PirepHTTPError (status + body) is raised only if every attempt fails.
    """
    if requests is None:
        raise RuntimeError("the 'requests' package is required for live PIREP data")
    sess = session or requests
    hrs = max(1, int(hours))
    date = end_time.strftime("%Y%m%d_%H%M") if end_time is not None else None
    bbox = CONUS_BBOX

    attempts = []
    for fmt in ("geojson", "json"):                 # preferred: age (hours back)
        p = {"bbox": bbox, "age": hrs, "format": fmt}
        if date:
            p["date"] = date
        attempts.append(p)
    for fmt in ("geojson", "json"):                 # some endpoints use `hours`
        attempts.append({"bbox": bbox, "hours": hrs, "format": fmt})
    attempts.append({"bbox": bbox, "format": "geojson"})   # latest, bbox only
    attempts.append({"bbox": bbox, "format": "json"})

    last_err = None
    for params in attempts:
        try:
            r = sess.get(AWC_URL, params=params, headers=_UA, timeout=timeout)
        except Exception as e:                       # network/SSL/etc.
            last_err = e
            continue
        if r.status_code == 204:                     # valid request, no data
            return []
        if r.status_code >= 400:
            last_err = PirepHTTPError(r.status_code, getattr(r, "text", ""))
            continue
        try:
            data = r.json()
        except ValueError:
            last_err = RuntimeError("PIREP response was not JSON (HTTP %s)" % r.status_code)
            continue
        feats = data.get("features") if isinstance(data, dict) else data
        out = []
        for f in (feats or []):
            rec = _norm(f)
            if rec:
                out.append(rec)
        return out

    raise last_err or RuntimeError("PIREP fetch failed")


# --------------------------------------------------------------------------- #
#  synthetic PIREPs (offline demo)                                            #
# --------------------------------------------------------------------------- #
def demo(hours=6, now=None):
    import random
    now = now or datetime.now(timezone.utc)
    rng = random.Random(int(now.timestamp()) // 900)
    # weighted mix: lots of smooth/light, fewer moderate/severe
    bag = (["turb"] * 6 + ["icing"] * 5 + ["both"] * 2 + ["nil"] * 8 + ["other"] * 3)
    tb_opts = ["LGT", "LGT", "LGT-MOD", "MOD", "MOD", "MOD-SEV", "SEV"]
    ic_opts = ["TRC", "LGT", "LGT", "LGT-MOD", "MOD", "MOD", "SEV"]
    out = []
    for _ in range(rng.randint(45, 80)):
        lat = round(rng.uniform(26, 48), 4)
        lon = round(rng.uniform(-123, -69), 4)
        cat = rng.choice(bag)
        tb = ic = None
        if cat == "turb":
            tb = rng.choice(tb_opts)
        elif cat == "icing":
            ic = rng.choice(ic_opts)
        elif cat == "both":
            tb = rng.choice(tb_opts); ic = rng.choice(ic_opts)
        elif cat == "nil":
            tb, ic = "NEG", "NEG"
        _, sev = _classify(tb, ic)
        fl = rng.choice([90, 120, 180, 240, 300, 320, 340, 360, 380])
        t = now - timedelta(minutes=rng.uniform(0, hours * 60))
        ac = rng.choice(["B738", "A320", "CRJ9", "E75L", "B739", "C25B", "PC12", "GLF5"])
        raw = f"UA /OV --- /TM ---- /FL{fl:03d} /TP {ac}" + \
              (f" /TB {tb}" if tb else "") + (f" /IC {ic}" if ic else "")
        out.append({
            "lat": lat, "lon": lon, "fl": fl, "cat": cat, "sev": round(sev, 2),
            "tb": tb, "ic": ic, "tbType": None, "icType": None,
            "ac": ac, "raw": raw, "time": t.timestamp(),
        })
    return out
