"""
hrrr.py — retrieve a HRRR model forecast sounding at a point/time, to compare
against an aircraft (ACARS) sounding.

ZERO-INSTALL design
--------------------
HRRR's native files are GRIB2, which would force every user to install a binary
GRIB reader (eccodes/pygrib) — a non-starter for people without admin rights or
the know-how. Instead we pull the HRRR forecast as plain **JSON** from the
free, key-less **Open-Meteo** API, which reprocesses NOAA's HRRR (3 km CONUS,
hourly) onto pressure levels. Decoding is pure standard-library JSON, so the
feature works the moment the app is unzipped — no extra packages, no admin.

Open-Meteo is free for non-commercial use and requires no API key. Data origin
is NOAA HRRR (https://rapidrefresh.noaa.gov/hrrr/), served via Open-Meteo
(https://open-meteo.com). Outside the CONUS HRRR area we fall back to GFS so a
model sounding still appears.

Returns a sounding dict in the app's format:
    {id, kind:"hrrr", levels:[{p(Pa), z(m), T(K), Td(K), wdir, wspd(m/s)}...],
     tail, time(valid epoch), model, source, valid, name, nlev}
"""

import math
from datetime import datetime, timezone

try:
    import requests
except Exception:                       # pragma: no cover
    requests = None

_UA = {"User-Agent": "ACARS-tracks/1.0 (HRRR sounding comparison)"}

# Open-Meteo hosts: live/recent forecast, plus the historical archive for older days.
_LIVE_URL = "https://api.open-meteo.com/v1/gfs"
_ARCHIVE_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"

# pressure levels to request (troposphere + low stratosphere; smooth enough for a
# comparison curve and CAPE, without a giant query string)
_LEVELS_MB = [1000, 975, 950, 925, 900, 875, 850, 825, 800, 775, 750, 700, 650,
              600, 550, 500, 450, 400, 350, 300, 250, 200, 150, 100]

_VARS = ["temperature", "dew_point", "geopotential_height",
         "wind_speed", "wind_direction", "relative_humidity"]

# model preference: HRRR first (3 km CONUS), then GFS seamless as a fallback so
# locations outside the HRRR domain still get a model sounding.
_MODELS = ["gfs_hrrr", "gfs_seamless"]
_MODEL_LABEL = {"gfs_hrrr": "HRRR", "gfs_seamless": "GFS"}


class HrrrUnavailable(Exception):
    """No model sounding could be retrieved (out of range, network, no data)."""


# kept for backward compatibility with older callers; never raised now that the
# feature needs no GRIB reader.
class GribReaderMissing(Exception):
    pass


def reader_name():
    """Identifies the data path (used in the UI footer)."""
    return "open-meteo"


# --------------------------------------------------------------------------- #
#  helpers                                                                     #
# --------------------------------------------------------------------------- #
def _hourly_param():
    return ",".join("%s_%dhPa" % (v, mb) for v in _VARS for mb in _LEVELS_MB)


def _td_from_rh(T_c, rh):
    if T_c is None or rh is None:
        return None
    es = 6.112 * math.exp(17.67 * T_c / (T_c + 243.5))
    e = max(1e-6, (rh / 100.0) * es)
    return 243.5 * math.log(e / 6.112) / (17.67 - math.log(e / 6.112))


def _val(hourly, key):
    arr = hourly.get(key)
    if isinstance(arr, list) and arr:
        return arr[0]
    return None


def _build_levels(hourly):
    """Turn one hour's Open-Meteo pressure-level values into sounding levels."""
    levels = []
    for mb in _LEVELS_MB:
        Tc = _val(hourly, "temperature_%dhPa" % mb)
        if Tc is None:
            continue
        z = _val(hourly, "geopotential_height_%dhPa" % mb)
        Tdc = _val(hourly, "dew_point_%dhPa" % mb)
        if Tdc is None:
            Tdc = _td_from_rh(Tc, _val(hourly, "relative_humidity_%dhPa" % mb))
        wspd = _val(hourly, "wind_speed_%dhPa" % mb)          # m/s (unit requested)
        wdir = _val(hourly, "wind_direction_%dhPa" % mb)      # deg, meteorological
        levels.append({
            "p": float(mb) * 100.0,
            "z": (float(z) if z is not None else None),
            "T": float(Tc) + 273.15,
            "Td": (float(Tdc) + 273.15 if Tdc is not None else None),
            "wdir": (round(wdir) if wdir is not None else None),
            "wspd": (float(wspd) if wspd is not None else None),
        })
    return levels


def _request(url, lat, lon, hour_iso, model, session, timeout):
    params = {
        "latitude": "%.4f" % lat, "longitude": "%.4f" % lon,
        "hourly": _hourly_param(), "models": model,
        "wind_speed_unit": "ms", "timeformat": "unixtime", "timezone": "GMT",
        "start_hour": hour_iso, "end_hour": hour_iso,
    }
    r = session.get(url, params=params, headers=_UA, timeout=timeout)
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
#  top-level fetch                                                             #
# --------------------------------------------------------------------------- #
def fetch_sounding(lat, lon, valid_time, now=None, session=None, timeout=30):
    """Fetch a model sounding valid at `valid_time` for (lat, lon). Tries HRRR
    first, then GFS; live host first, then the historical archive for older
    times. Raises HrrrUnavailable if nothing usable comes back."""
    if requests is None:
        raise HrrrUnavailable("the 'requests' package is required")
    sess = session or requests
    now = now or datetime.now(timezone.utc)
    valid = datetime.fromtimestamp(valid_time, tz=timezone.utc).replace(
        minute=0, second=0, microsecond=0)
    hour_iso = valid.strftime("%Y-%m-%dT%H:%M")
    age_days = (now - valid).total_seconds() / 86400.0

    # for recent times use the live forecast host; for older, the archive host.
    hosts = [_LIVE_URL, _ARCHIVE_URL] if age_days <= 3 else [_ARCHIVE_URL, _LIVE_URL]

    last = None
    for model in _MODELS:
        for url in hosts:
            try:
                data = _request(url, lat, lon, hour_iso, model, sess, timeout)
            except Exception as e:
                last = e
                continue
            if not data:
                continue
            hourly = data.get("hourly") or {}
            if not hourly.get("time"):
                continue
            levels = _build_levels(hourly)
            if len(levels) >= 4:
                label = _MODEL_LABEL.get(model, "Model")
                return {
                    "id": "HRRR:%s" % label,
                    "kind": "hrrr", "levels": levels,
                    "tail": label,
                    "time": valid.timestamp(),
                    "model": label, "source": "Open-Meteo",
                    "valid": valid.strftime("%Y-%m-%d %H:%MZ"),
                    "name": "%s · valid %sZ" % (label, valid.strftime("%H:%M")),
                    "nlev": len(levels),
                }
    if isinstance(last, Exception):
        raise HrrrUnavailable("network error (%s)" % type(last).__name__)
    raise HrrrUnavailable("no model data for this time/place "
                          "(HRRR covers the CONUS; archive starts ~2021)")


# --------------------------------------------------------------------------- #
#  synthetic sounding (offline demo)                                          #
# --------------------------------------------------------------------------- #
def demo_sounding(lat, lon, valid_time, now=None):
    import random
    rng = random.Random(int((lat * 7 - lon * 3) * 100) ^ int(valid_time))
    sfcT = rng.uniform(19, 28)
    z_trop = rng.uniform(11500, 13000)
    T_trop = rng.uniform(-60, -54)
    levels = []
    for mb in (1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100):
        z = (1.0 - (mb / 1013.25) ** (1 / 5.25588)) / 2.25577e-5
        if z <= z_trop:
            T = sfcT + (T_trop - sfcT) * (z / z_trop)
        else:
            T = T_trop + 0.0012 * (z - z_trop)
        dep = min(7 + 6.0 * (z / 1000.0), 32)
        Td = T - dep
        wdir = (220 + z / 1000.0 * 8) % 360
        wspd = (8 + z / 1000.0 * 3.5) * 0.514444
        levels.append({"p": mb * 100.0, "z": round(z, 1),
                       "T": round(T + 273.15, 2), "Td": round(Td + 273.15, 2),
                       "wdir": round(wdir), "wspd": round(wspd, 2)})
    valid = datetime.fromtimestamp(valid_time, tz=timezone.utc).replace(
        minute=0, second=0, microsecond=0)
    return {"id": "HRRR:demo", "kind": "hrrr", "levels": levels, "tail": "HRRR",
            "time": valid.timestamp(), "model": "HRRR", "source": "demo",
            "valid": valid.strftime("%Y-%m-%d %H:%MZ"),
            "name": "HRRR (demo) · valid %sZ" % valid.strftime("%H:%M"),
            "nlev": len(levels)}
