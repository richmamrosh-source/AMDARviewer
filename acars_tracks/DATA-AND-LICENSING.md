# Data sources, restrictions, and attribution

Read this before hosting this application anywhere, or before using its output
commercially. The **software** is MIT-licensed (see `LICENSE`). The **data** it
fetches is not the software's to license, and some of it is restricted.

---

## How this application relates to the data

This is a **client**. It runs on the user's own machine and fetches observations
directly from public feeds on the user's behalf, the way a browser does. Copies of
this program do not receive data from the author, and the author does not operate a
server.

That distinction matters legally. **Distributing this application is not
redistributing data.** Hosting it as a public website would be, because then one
server fetches the data and serves it onward to others.

---

## NOAA MADIS — Aircraft Based Observations (ACARS / AMDAR)

**Used for:** flight tracks, aircraft soundings, EDR turbulence.
**Endpoint:** `https://madis-data.ncep.noaa.gov/madisPublic1/data/point/acars/`
and `.../acarsProfiles/` (public feed; aircraft identifiers are encrypted by NOAA).

**This data is restricted.** Per NOAA's published ABO restrictions
(<https://madis.ncep.noaa.gov/acars_restrictions.shtml>):

- Publicly available ABO falls into two categories: **WVSS-II data is available to
  the public in real time**, and **all ABO data is available to the public once it
  is 48 hours old**.
- All other ABO is **proprietary to the airlines providing the data**. For
  real-time access to it: *the data may not be redistributed*, it *may not be made
  available to commercial entities*, and it *may not be used to develop products or
  services for sale*.
- NCEP further notes that a data restriction **remains in force regardless of any
  reformatting, rearrangement, or method of presentation** — plotting an
  observation on a Skew-T does not remove the restriction.

**What this means in practice:**

| You want to… | Position |
|---|---|
| Run the app yourself | Fine. You are fetching public data as an individual. |
| Give someone the app | Fine. They fetch their own data. |
| Host it publicly, showing **real-time** data | **Do not** without written clarification from MADIS. Most of what this app displays (tracks, temperature, wind, turbulence from all fleets) is not WVSS-II moisture and is not covered by the real-time carve-out. |
| Host it publicly, showing data **≥ 48 hours old** | Unrestricted. Archive mode does exactly this. |
| Build a product for sale on **real-time** ACARS | Prohibited. |

Note that this application does **not** currently enforce a 48-hour age gate — it
displays whatever the feed returns, including real-time reports from all fleets.
Any hosted deployment must add that gate or restrict itself to archive dates.

**Questions:** MADIS Support — <madis-support@noaa.gov>

## NOAA MADIS — Radiosonde (optional, off by default)

`madis_raob.py`, enabled with `--madis-raob`. Same account/restriction framework as
above. Off by default because US radiosondes are already served by IEM.

## Iowa Environmental Mesonet (IEM)

**Used for:** US/Canada radiosonde soundings.
**Endpoint:** `https://mesonet.agron.iastate.edu/json/raob.py`
Iowa State University; freely available. Please be considerate of their servers —
this app requests one station at a time, on demand.

## NOAA NCEI — IGRA v2.2

**Used for:** worldwide radiosonde soundings (~2-day lag).
US Government public domain data.

## NOAA Aviation Weather Center

**Used for:** PIREPs and METARs (the METARs are used as ground truth for the
aircraft moisture check).
**Endpoint:** `https://aviationweather.gov/api/data/`
US Government public domain data.

## Open-Meteo

**Used for:** HRRR/GFS model forecast soundings.
**Endpoint:** `https://api.open-meteo.com/`
Free for non-commercial use under CC-BY-4.0; commercial use requires their paid
tier. See <https://open-meteo.com/en/terms>. **If this application is ever
commercialised, this dependency needs review.**

## Deutscher Wetterdienst (DWD) — dormant

`dwd_temp.py` is present but disabled (`PREFER_DWD = False`). If re-enabled, DWD
open data may be reused commercially **with attribution**: "Source: Deutscher
Wetterdienst". The application already renders that credit on affected plots.

## CARTO / OpenStreetMap

**Used for:** base map tiles.
Attribution is rendered on the map, as their terms require.

## Leaflet

Bundled locally in `static/vendor/leaflet/` (BSD-2-Clause), downloaded and
SHA-256-verified by `vendor_leaflet.py` so the interface makes no external request
for its code.

---

## Summary for a security or legal review

- The software is MIT-licensed and contains no third-party code beyond Leaflet
  (BSD-2-Clause) and the pip packages in `requirements.txt`.
- It listens on `127.0.0.1` only.
- Outbound connections go only to the NOAA, IEM, Open-Meteo, and CARTO endpoints
  listed above.
- No Java, no JRE, no browser plugins.
- The one live legal constraint is the **48-hour ACARS/AMDAR restriction**, which
  binds any *hosted* deployment, not the distribution of the application itself.
