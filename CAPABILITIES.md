# ACARS Tracks & Soundings — Capability Summary

**A desktop tool for viewing aircraft-based weather observations — and for finding
the aircraft whose sensors are defective.**

Built by a retired National Weather Service meteorologist. Runs locally on any
Windows PC. ~7,000 lines of Python and browser JavaScript. No Java, no plugins,
no server.

---

## Qulaity control that doesn't exist anywhere else

**MADIS quality-controls aircraft dewpoint only to QC level 2** — validity (is the
value in range?) and internal consistency (is Td ≤ T?). **Level 3, the
temporal/spatial "buddy" check, is never applied to moisture.** This is visible in
MADIS's own published variable table, where dewpoint's maximum QC level is 2.

The consequence: an airframe whose humidity sensor has failed — heater out,
element contaminated, or RH pinned at the sensor floor — reports dewpoints that
are *individually plausible* and *internally consistent*, and therefore pass QC
every single time, indefinitely. Known airframes have flown this way for years.
The signature is a bone-dry, inverted-V profile at a location where that is
meteorologically impossible: a 4,600 m LCL over New Orleans in July.

**This tool performs the check MADIS doesn't.** For each aircraft profile it
compares near-surface dewpoint against a three-rung ladder of references:

1. **The airport's own METAR** — ground truth, hourly, at every airport.
2. **The HRRR/GFS model** — where no surface ob is available, or where the profile
   never reaches the ground (matched level-by-level in pressure).
3. **Peer aircraft** at the same airport — last resort.

It then keeps a **per-airframe ledger across sessions**. This is the key
distinction: one dry sounding is weather; the same airframe reading 40 °C too dry
at every airport, day after day, is a broken sensor. Chronic offenders are named:

```
[soundings] aircraft with a PROBABLE FAULTY HUMIDITY SENSOR:
    FSL00012692      too dry on 11 of 12 checks, avg 44 C drier than truth
```

Where the WVSS-II sensor's own diagnostic code (MADIS `REPWVQC`) is present in the
feed, the tool decodes it directly — heater fail, contaminated element, RH clamped
to 1.5% — and names the fault.

**Why this matters, by audience:**

- **Airlines** — actionable maintenance: *which tail* has bad moisture hardware.
- **NWS / MADIS** — bad moisture observations are ingested into operational models.
  This is a blind spot in the ingest QC, not in the airlines' hardware alone.
- **Collins / sensor vendors** — continuous, automated fleet sensor-health
  monitoring from data already being collected.

---

## Everything else it does

- **Flight tracks** from the MADIS ACARS en-route feed; hover any report for FSL
  ID, flight level, temperature, dewpoint, wind, and EDR turbulence.
- **Skew-T/Log-P soundings** for any aircraft that climbed or descended, with
  CAPE/CIN parcel analysis, hodograph, and a live value readout that tracks the
  cursor up and down the profile.
- **Radiosondes** — all US/Canada sites (near-real-time) plus worldwide (archive),
  in the identical Skew-T view. Flags when a site *didn't launch* a synoptic cycle
  — increasingly common since the 2025 NWS balloon reductions.
- **HRRR model soundings** overlaid on any aircraft profile.
- **Comparison viewer** — overlay any mix of AMDAR, radiosonde, and HRRR soundings
  on one Skew-T (e.g. 12Z Dallas radiosonde vs. 12Z AMDAR vs. 12Z HRRR).
- **Wind barbs**, **EDR turbulence**, and live **PIREPs** overlays.
- **Archive mode** back 10 years, subject to MADIS retention.
- **Aircraft lookup** — find and flash any tail's track, for chasing bad data.

## Technical profile

- **Python + Flask backend, browser JavaScript frontend.** No Java, no JRE, no
  applets, no browser plugins. (Relevant for environments that restrict Java.)
- Serves on `127.0.0.1` only — nothing is exposed to the network.
- The map library (Leaflet) is **vendored locally and SHA-256 verified**, so the
  interface makes no external requests.
- Distributable as a standalone Windows executable, or run from source with
  `pip install -r requirements.txt`.

## Data sources

NOAA MADIS (aircraft reports + profiles, public feed), Iowa Environmental Mesonet
and NOAA NCEI IGRA (radiosondes), NOAA Aviation Weather Center (PIREPs, METARs),
Open-Meteo (HRRR). See `DATA-AND-LICENSING.md`.

**Important:** the tool is a *client*. Each user's own copy fetches data directly
from the public feeds; it does not redistribute data. Real-time ACARS/AMDAR is
restricted (48-hour rule), which is why it is distributed as an application rather
than hosted as a website.

---

## What I would like to see happen with this program

Identify an organization positioned to refine, support, and distribute this to the people
who would benefit — airline meteorology teams, NWS forecast offices, sensor
vendors — and to handle the data agreements that a hosted version would require.

I am happy to demonstrate it live, hand over the source, or support a transition.

*To try it yourself: see `GETTING-STARTED.md` — three steps, no programming.*

**Contact:** `Richard Mamrosh` · richmamrosh@gmail.com
