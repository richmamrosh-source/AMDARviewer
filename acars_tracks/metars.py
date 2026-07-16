"""METAR surface observations from the Aviation Weather Center (AWC).

Why this exists
---------------
MADIS takes aircraft dewpoint only to QC level 2 — validity (is it in range?) and
internal consistency (is Td <= T?). Level 3, the temporal/spatial "buddy" check,
is never applied to moisture. So an airframe whose humidity sensor is stuck dry
reports dewpoints that are individually plausible and internally consistent, and
they sail through QC forever. Comparing aircraft to each other doesn't rescue it
either: only two US fleets carry the WVSS-II moisture sensor, so a busy airport
may have just one or two moisture-reporting aircraft in a whole window.

The airport's own METAR is the way out. It is ground truth, it exists at every
airport, and it is updated hourly. If an aircraft climbing out of MSY says the
air near the runway is 40 C drier than the METAR at that same runway says, the
aircraft is wrong — no climatology or peer aircraft required.

Live observations only (this is the AWC's current-conditions feed), so the check
is skipped for archive dates.
"""

try:
    import requests
except ImportError:                                   # pragma: no cover
    requests = None

AWC_URL = "https://aviationweather.gov/api/data/metar"
# bbox order is lat0,lon0,lat1,lon1 = minLat,minLon,maxLat,maxLon, matching the
# AWC OpenAPI spec used for PIREPs. CONUS + a margin.
CONUS_BBOX = "20,-130,55,-60"
# aviationweather.gov filters non-browser User-Agents (returns 403).
_UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36 ACARS-tracks/1.0"),
    "Accept": "application/json, text/plain, */*",
}


def _num(v):
    try:
        f = float(v)
        return f if -1e30 < f < 1e30 else None
    except (TypeError, ValueError):
        return None


def _epoch(rec):
    for k in ("obsTime", "reportTime", "receiptTime"):
        v = rec.get(k)
        if isinstance(v, (int, float)) and v > 1e8:
            return float(v)
    return None


def parse(data):
    """Turn an AWC METAR payload into a compact station list. Keeps only stations
    that actually report both temperature and dewpoint (what we need to judge)."""
    if isinstance(data, dict):
        data = data.get("features") or data.get("data") or []
    out = []
    for rec in data or []:
        if not isinstance(rec, dict):
            continue
        if "properties" in rec and isinstance(rec["properties"], dict):
            rec = dict(rec["properties"], **{"geometry": rec.get("geometry")})
        t, td = _num(rec.get("temp")), _num(rec.get("dewp"))
        lat, lon = _num(rec.get("lat")), _num(rec.get("lon"))
        if lat is None or lon is None:
            geo = rec.get("geometry") or {}
            crd = geo.get("coordinates") or []
            if len(crd) >= 2:
                lon, lat = _num(crd[0]), _num(crd[1])
        if t is None or td is None or lat is None or lon is None:
            continue
        out.append({
            "icao": (rec.get("icaoId") or rec.get("station_id") or "").strip(),
            "lat": lat, "lon": lon,
            "elev": _num(rec.get("elev")) or 0.0,     # metres MSL
            "t": t, "td": td,                          # degrees C
            "time": _epoch(rec),
            "name": (rec.get("name") or "").strip(),
        })
    return out


def fetch(bbox=CONUS_BBOX, session=None, timeout=30):
    """Current METARs across the bbox. Returns a list (possibly empty); never
    raises for a routine failure, since this is an optional QC aid."""
    if requests is None:
        return []
    sess = session or requests
    for fmt in ("json", "geojson"):
        try:
            r = sess.get(AWC_URL, params={"bbox": bbox, "format": fmt},
                         headers=_UA, timeout=timeout)
        except Exception:
            continue
        if r.status_code != 200:
            continue
        try:
            return parse(r.json())
        except ValueError:
            continue
    return []


def nearest(stations, lat, lon, max_km=30.0):
    """The closest reporting station to a point, or None if none is close enough."""
    if lat is None or lon is None:
        return None
    best, bestd = None, None
    import math
    for st in stations:
        dlat = (st["lat"] - lat) * 111.0
        dlon = (st["lon"] - lon) * 111.0 * math.cos(math.radians(lat))
        d = math.hypot(dlat, dlon)
        if bestd is None or d < bestd:
            best, bestd = st, d
    if best is None or bestd > max_km:
        return None
    best = dict(best)
    best["dist_km"] = round(bestd, 1)
    return best
