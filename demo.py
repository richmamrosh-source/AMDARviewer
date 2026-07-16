"""
demo.py — Synthetic ACARS en-route flight tracks for offline / --demo use.

Produces the same structure the real parser produces so the rest of the app is
identical:

    tracks : list of {"id": str, "pts": [[lat, lon, alt_m, temp_c, dew_c,
                                          wspd_kt, wdir_deg, epoch], ...]}
    generated_at : datetime (UTC)

Winds aloft are made realistic: generally westerly, strengthening with altitude
and within a jet-stream band near ~40N, so the color-by-speed wind barbs show
real structure.
"""

import math
import random
from datetime import datetime, timedelta, timezone

CITIES = [
    ("SEA", 47.45, -122.31), ("PDX", 45.59, -122.60), ("SFO", 37.62, -122.38),
    ("LAX", 33.94, -118.41), ("LAS", 36.08, -115.15), ("PHX", 33.43, -112.01),
    ("DEN", 39.86, -104.67), ("SLC", 40.79, -111.98), ("DFW", 32.90, -97.04),
    ("IAH", 29.99, -95.34), ("MSP", 44.88, -93.22), ("ORD", 41.97, -87.91),
    ("STL", 38.75, -90.37), ("MCI", 39.30, -94.71), ("ATL", 33.64, -84.43),
    ("MIA", 25.80, -80.29), ("CLT", 35.21, -80.94), ("DTW", 42.21, -83.35),
    ("JFK", 40.64, -73.78), ("BOS", 42.36, -71.01), ("PHL", 39.87, -75.24),
    ("IAD", 38.95, -77.46), ("BNA", 36.13, -86.68), ("MSY", 29.99, -90.26),
    ("SAN", 32.73, -117.19), ("PIT", 40.49, -80.23), ("OMA", 41.30, -95.89),
]

R_EARTH = 6371.0


def _gc_point(lat1, lon1, lat2, lon2, f):
    """Point fraction f along the great circle from 1 to 2."""
    p1, l1, p2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    d = 2 * math.asin(math.sqrt(
        math.sin((p2 - p1) / 2) ** 2 +
        math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2))
    if d == 0:
        return lat1, lon1
    a = math.sin((1 - f) * d) / math.sin(d)
    b = math.sin(f * d) / math.sin(d)
    x = a * math.cos(p1) * math.cos(l1) + b * math.cos(p2) * math.cos(l2)
    y = a * math.cos(p1) * math.sin(l1) + b * math.cos(p2) * math.sin(l2)
    z = a * math.sin(p1) + b * math.sin(p2)
    return (math.degrees(math.atan2(z, math.hypot(x, y))),
            math.degrees(math.atan2(y, x)))


def _gc_dist(lat1, lon1, lat2, lon2):
    p1, l1, p2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    d = 2 * math.asin(math.sqrt(
        math.sin((p2 - p1) / 2) ** 2 +
        math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2))
    return d * R_EARTH


def _wind(lat, lon, alt_m, rng):
    """Plausible wind: westerly, stronger aloft and in a ~40N jet band."""
    jet = math.exp(-((lat - 41.0) / 6.0) ** 2)           # 0..1 peak near 41N
    alt_frac = min(max(alt_m / 11000.0, 0), 1.2)
    base = 12 + 95 * jet * alt_frac                       # kt
    speed = base + rng.uniform(-8, 8) + 8 * math.sin(lon / 12.0)
    speed = max(2, speed)
    direction = (255 + 35 * jet - 22 * alt_frac + rng.uniform(-18, 18)) % 360
    return round(speed, 1), round(direction)


def _temp(alt_m, rng):
    return round(15 - 6.5 * min(alt_m, 11000) / 1000.0 +
                 (alt_m - 11000) / 1000.0 * (alt_m > 11000) + rng.uniform(-2, 2), 1)


def generate(now=None, hours=6, n_aircraft=130):
    if now is None:
        now = datetime.now(timezone.utc)
    rng = random.Random(int(now.timestamp()) // 1800)     # stable ~30 min
    window_start = now - timedelta(hours=hours)
    tracks = []

    # sparse, clustered turbulence field for this run: a few cells give moderate
    # to severe EDR; only a minority of aircraft report EDR at all (mirroring the
    # real fleet, where only some aircraft carry the sensor)
    edr_cells = [(rng.choice(CITIES)[1] + rng.uniform(-2.5, 2.5),
                  rng.choice(CITIES)[2] + rng.uniform(-5.0, 5.0),
                  rng.uniform(150, 340), rng.uniform(0.30, 0.62))
                 for _ in range(rng.randint(3, 5))]

    for i in range(n_aircraft):
        o = rng.choice(CITIES)
        d = rng.choice(CITIES)
        if d[0] == o[0]:
            continue
        dist = _gc_dist(o[1], o[2], d[1], d[2])
        if dist < 350:
            continue
        cruise = rng.choice([9449, 10058, 10363, 10668, 11278, 11887])  # ~FL310-390
        ground_kt = rng.uniform(420, 500)
        dur_min = (dist / 1.852) / ground_kt * 60.0       # km->nm / kt -> hr -> min
        # depart so at least part of the flight is inside the window
        depart = window_start + timedelta(
            minutes=rng.uniform(-dur_min * 0.5, hours * 60))
        step = 4.0                                         # report every ~4 min
        n_steps = max(2, int(dur_min / step))
        tail = f"N{rng.randint(100, 899)}{chr(rng.randint(65,90))}{chr(rng.randint(65,90))}"
        reports_edr = rng.random() < 0.32          # only some of the fleet has EDR

        pts = []
        for s in range(n_steps + 1):
            t = window_start + timedelta(minutes=0)        # placeholder
            frac = s / n_steps
            tmin = depart + timedelta(minutes=s * step)
            if tmin < window_start or tmin > now:
                continue
            lat, lon = _gc_point(o[1], o[2], d[1], d[2], frac)
            # vertical profile: climb 0->0.12, cruise, descend 0.88->1
            if frac < 0.12:
                alt = cruise * (frac / 0.12)
            elif frac > 0.88:
                alt = cruise * (1 - (frac - 0.88) / 0.12)
            else:
                alt = cruise + rng.uniform(-120, 120)
            alt = max(600, alt)
            ws, wd = _wind(lat, lon, alt, rng)
            temp = _temp(alt, rng)
            dew = round(temp - rng.uniform(2, 18), 1)
            edr = None
            if reports_edr:
                e = 0.015 + rng.uniform(0, 0.045)      # smooth-air background
                for clat, clon, crad, cpk in edr_cells:
                    dd = _gc_dist(lat, lon, clat, clon)
                    if dd < crad * 1.7:
                        e += cpk * math.exp(-(dd / crad) ** 2)
                edr = round(min(e, 0.85), 3)
            pts.append([round(lat, 4), round(lon, 4), round(alt),
                        temp, dew, ws, wd, tmin.timestamp(), edr])

        if len(pts) >= 2:
            tracks.append({"id": tail, "pts": pts})

    return tracks, now


# --------------------------------------------------------------------------- #
#  Synthetic vertical profiles (soundings) for --demo mode                     #
#  Tied to a subset of the generated tracks so clicking those tracks works.    #
# --------------------------------------------------------------------------- #
def _std_pressure_pa(z_m):
    """Pressure (Pa) from height (m), US standard atmosphere troposphere."""
    return 101325.0 * (1.0 - 2.25577e-5 * z_m) ** 5.25588


def _nearest_city(lat, lon):
    best, bd = "APT", 1e9
    for name, la, lo in CITIES:
        d = (la - lat) ** 2 + (lo - lon) ** 2
        if d < bd:
            bd, best = d, name
    return best


def generate_profiles(tracks, fraction=0.45):
    """Build realistic soundings at one end of a subset of the given tracks.

    Returns a list of sounding dicts:
        {id, tail, time, lat, lon, airport, updown,
         levels: [{p, z, T, Td, wdir, wspd}, ...]}   # surface -> top
    """
    rng = random.Random(12345)
    out = []
    n = max(1, int(len(tracks) * fraction))
    chosen = rng.sample(tracks, min(n, len(tracks)))
    # a few hub airports get many soundings (like a real busy field), the rest
    # sit at their flight's departure/arrival city
    HUBS = [("ORD", 41.978, -87.904), ("ATL", 33.640, -84.427),
            ("DFW", 32.897, -97.038)]
    hub_weights = [0.55, 0.28, 0.17]
    for k, t in enumerate(chosen):
        updown = rng.choice(["UP", "DOWN"])
        end = t["pts"][0] if updown == "UP" else t["pts"][-1]
        t_epoch = end[7]
        if rng.random() < 0.5:                       # cluster at a hub
            code, hlat, hlon = rng.choices(HUBS, weights=hub_weights, k=1)[0]
            lat = hlat + rng.uniform(-0.13, 0.13)
            lon = hlon + rng.uniform(-0.13, 0.13)
            airport = code
        else:                                        # at the flight's own field
            lat, lon = end[0], end[1]
            airport = _nearest_city(lat, lon)

        # surface conditions vary a little by latitude/season-ish
        sfc_t = 24.0 - (lat - 33.0) * 0.5 + rng.uniform(-3, 3)        # deg C
        sfc_dep = rng.uniform(2.0, 9.0)                               # T - Td
        # ACARS profiles seldom climb above 300 hPa (~9.2 km); most top out a bit
        # below that, with the occasional higher one
        top_z = rng.choice([7700, 8200, 8200, 8700, 9000, 9000, 9300, 10300])
        trop = rng.uniform(9500, 11500)
        # wind: surface dir/speed, veering & strengthening aloft
        sfc_dir = rng.uniform(140, 230)
        jet_dir = rng.uniform(250, 300)
        jet_spd = rng.uniform(55, 120)

        levels = []
        z = 0.0
        step = 320.0
        while z <= top_z:
            p = _std_pressure_pa(z)
            if z <= trop:
                T = sfc_t - 6.5 * (z / 1000.0)
            else:
                T = sfc_t - 6.5 * (trop / 1000.0)                     # isothermal
            T += rng.uniform(-0.6, 0.6)
            dep = sfc_dep + (z / 1000.0) * 2.2 + rng.uniform(-1, 1)   # dries aloft
            dep = max(1.0, dep)
            Td = T - dep
            frac = min(z / max(top_z, 1.0), 1.0)
            wdir = (sfc_dir + (jet_dir - sfc_dir) * frac + rng.uniform(-8, 8)) % 360
            wspd = (6 + (jet_spd - 6) * (frac ** 1.3) + rng.uniform(-4, 4))  # m/s? -> store m/s
            wspd = max(0.0, wspd)
            levels.append({
                "p": round(p, 1),
                "z": round(z, 1),
                "T": round(T + 273.15, 2),       # Kelvin
                "Td": round(Td + 273.15, 2),     # Kelvin
                "wdir": round(wdir, 1),
                "wspd": round(wspd, 2),          # m/s
            })
            z += step

        out.append({
            "id": f"P{k:04d}",
            "tail": t["id"],
            "time": t_epoch,
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "airport": airport,
            "updown": updown,
            "levels": levels,
        })
    return out
