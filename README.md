# ACARS Flight Tracks, Wind Barbs & Soundings

### ▶ Never run something from GitHub before? → **[GETTING-STARTED.md](GETTING-STARTED.md)**
*Step by step, written for meteorologists rather than programmers.*

## Run it in three steps

1. Click the green **`< > Code`** button near the top of this page → **Download ZIP**
2. Right-click the downloaded ZIP → **Extract All** — *don't run it from inside the ZIP*
3. Double-click **`Start ACARS Tracks.bat`**

That's it. The first run takes a few minutes to set itself up (and will tell you if
you need to install Python first); every run after that starts in about ten
seconds. Your browser opens to the map on its own.

**No internet?** Double-click `Start ACARS Tracks (offline demo).bat` for a
sample-data tour.

*Stuck? Every common snag is in
[GETTING-STARTED.md](GETTING-STARTED.md#if-something-goes-wrong).*

---

> **Other docs:** **[CAPABILITIES.md](CAPABILITIES.md)** is the one-page summary,
> including the aircraft moisture-sensor QC gap this tool was built to expose.
> **[DATA-AND-LICENSING.md](DATA-AND-LICENSING.md)** covers data sources and the
> 48-hour ACARS restriction. **[DISTRIBUTING.md](DISTRIBUTING.md)** covers building
> a standalone Windows app and notes for an IT/security review.
>
> *Screenshots: add yours to `docs/screenshots/` — see HOW-TO-PUBLISH.md.*

---

## What it does

An interactive map of recent aircraft weather reports from the NOAA MADIS **ACARS
en-route** feed. It connects the reports from each aircraft into a **flight
track**, lets you **hover any point** to read the data, has a **Wind barbs**
button that draws proper wind barbs **color-coded by wind speed in knots**, and a
**Turbulence** button that plots aircraft **EDR turbulence reports** colored by
severity, and a **PIREPs** button that overlays live **pilot reports** color-coded
for turbulence, icing, or smooth air.

Aircraft that climbed or descended recently also have a **vertical profile**
(sounding) in the MADIS **ACARS profiles** feed. Those tracks are **highlighted**;
**click one** (or its ▲/▼ marker) and the page plots that aircraft's
**Skew-T/Log-P sounding**, rendered with **pyMeteo**. A **Radiosondes** button
adds the weather-balloon launch sites too, so you can pull up the **latest 00Z/12Z
radiosonde** for any station and compare it, side by side, with a nearby aircraft
sounding in the identical Skew-T / hodograph / analysis view. A **＋ HRRR** button
inside the sounding panel goes one step further and overlays the **HRRR model
forecast** sounding for that same time and place, so you can compare the planes
against the model.

It downloads the **last few hours** of data (you choose how many, 1–12),
runs a tiny web server on your own PC, and opens the map in your browser.
Nothing is uploaded anywhere — the only internet traffic is your computer asking
NOAA (and, for radiosondes, the Iowa Environmental Mesonet) for the data files.

---

## What you need (one-time setup)

> **Just want to start it with one click — or share it with someone?**
> See **`DISTRIBUTING.md`**. On Windows you can simply double-click
> **`Start ACARS Tracks.bat`** (it sets everything up for you), or build a
> standalone **`.exe`** that runs on PCs without Python. The steps below are the
> manual way.

1. **Install Python 3** (if you haven't already) from https://www.python.org/downloads/ .
   On the first screen of the installer, tick **"Add python.exe to PATH"**, then
   click Install.

2. **Put this folder somewhere easy**, e.g. your Desktop.

3. **Open a terminal in this folder.** In File Explorer, open the folder, then
