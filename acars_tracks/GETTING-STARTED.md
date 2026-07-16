# Getting started

Written for meteorologists, not programmers. If you can install a program and
double-click a file, you can run this.

**Time needed:** about 15 minutes the first time (most of it waiting), then about
10 seconds every time after.

**You need:** a Windows PC and an internet connection. Nothing else.

---

## Step 1 — Download the files

On the GitHub page, find the green **`< > Code`** button near the top right.
Click it, then click **Download ZIP**.

> The green Code button is easy to miss — it's above the file list, on the right.
> You do **not** need a GitHub account, and you do not need to "clone" anything.

The file lands in your **Downloads** folder as `acars-tracks-main.zip`.

## Step 2 — Unzip it (don't skip this)

Right-click the ZIP file → **Extract All…** → **Extract**.

> **This step matters.** Windows lets you double-click *into* a ZIP file so it
> looks like an ordinary folder — but programs run from in there will fail with
> confusing errors. You must extract it first.

Move the extracted folder wherever you like — Desktop or Documents is fine. Avoid
OneDrive if you can; it sometimes interferes.

## Step 3 — Make sure Python is installed

You may already have it. **Skip to Step 4 and find out** — the launcher checks for
you and will say so plainly if it's missing.

If it tells you Python wasn't found:

1. Go to <https://www.python.org/downloads/> and click the big yellow download
   button.
2. Run the installer.
3. **On the very first screen, tick the box that says "Add python.exe to PATH".**
   It's at the bottom and it's easy to miss. If you skip it, the launcher won't
   find Python.
4. Click **Install Now**, then run Step 4 again.

> **No admin rights on a work PC?** The installer offers **"Install for me only"** —
> that works fine and doesn't need an administrator.
>
> **Blocked entirely by IT?** See `DISTRIBUTING.md`, which has a section written
> for a security review. The short version: this is Python and a web browser — no
> Java, no plugins, and it only talks to your own PC and NOAA.

## Step 4 — Double-click `Start ACARS Tracks.bat`

It's in the folder you extracted. A black window opens. **That's normal** — that
window *is* the program.

> If Windows says **"Windows protected your PC"**, click **More info** →
> **Run anyway**. This happens because the file came from the internet, not
> because anything is wrong with it.

## Step 5 — Wait, the first time only

The first run sets itself up: it builds a small private Python environment inside
the folder and downloads the packages it needs. **This takes 3–10 minutes** and
scrolls a lot of text past. That's normal — it isn't stuck.

You'll see lines like `Setting up for first use...` and `Installing required
packages...`. Let it finish.

**Every run after this one starts in about 10 seconds.** This only happens once.

## Step 6 — The map opens

Your web browser opens by itself to the map, and aircraft appear.

**Keep the black window open while you use it.** Closing it stops the program.
That's also how you quit when you're done.

---

## If something goes wrong

| What you see | What to do |
|---|---|
| "Python was not found on this PC" | Step 3. Remember the **Add python.exe to PATH** tick box. |
| "Windows protected your PC" | **More info** → **Run anyway**. |
| Black window flashes and vanishes | You're running it from *inside* the ZIP. Go back to Step 2 and extract it. |
| "Package install failed" | Check your internet, then double-click the launcher again. It picks up where it left off. |
| Map opens but is empty | Aircraft data is thin at some hours. Try the **Refresh** button, or raise the **hours** dropdown from 3 to 6. |
| Antivirus complains | See the antivirus section in `DISTRIBUTING.md`. |
| No internet at all | Double-click **`Start ACARS Tracks (offline demo).bat`** instead — it runs on built-in sample data so you can see how it works. |

---

## A two-minute tour once it's running

Worth doing in this order — it puts the interesting part first.

1. **Hover over any dot** on a flight path. You get that report's aircraft ID,
   flight level, temperature, dewpoint, wind, and turbulence.

2. **Click a highlighted (brighter) track.** Those aircraft climbed or descended,
   so they have a full sounding. You get a Skew-T with CAPE/CIN and a hodograph.
   **Move your cursor up and down the Skew-T** — the values at each level follow it.

3. **Watch for a red banner** reading *"Dewpoint likely bad — use with caution."*
   That's the part that doesn't exist in MADIS. It means that airframe's humidity
   sensor is reporting air far drier than the airport's own METAR says it is —
   i.e. the sensor is broken. Some of these have been flying that way for years.
   The black window also lists the offending tails as it finds them.

4. **Click `＋ HRRR`** inside a sounding to overlay the model for that same time
   and place.

5. **Click `Recent soundings`** at the top. Pick an aircraft sounding, then
   **shift-click** a nearby radiosonde and the HRRR chip — all three overlay on one
   Skew-T for comparison.

6. **Turn on `Radiosondes`** and click any balloon site for its latest 00Z/12Z
   sounding. If a site skipped a launch, it says so.

---

## Where to go next

- **`CAPABILITIES.md`** — one page on what this does and why the moisture QC
  matters.
- **`README.md`** — the full feature guide.
- **`DATA-AND-LICENSING.md`** — where the data comes from and the rules attached
  to it.
- **`DISTRIBUTING.md`** — building a standalone app, and notes for an IT/security
  review.
