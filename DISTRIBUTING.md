# Running on another PC & sharing with others

There are two easy ways to give this to someone (or move it to another computer).
Pick the one that fits.

---

## Option 1 — The simple way (for you, or anyone who can install Python)

**Windows:** double-click **`Start ACARS Tracks.bat`**

That's it. The first time, it quietly sets up a small private environment and
downloads the packages it needs (this needs internet and takes a minute or two).
Every time after that, it starts in a couple of seconds. A black window opens —
that's the map server. Your browser opens to the map automatically. **Leave the
black window open while you use it; close it to stop.**

- To try it **without the live weather feed**, double-click
  **`Start ACARS Tracks (offline demo).bat`** instead. (It still needs internet
  for the map's background — see the note at the bottom.)

**Mac / Linux:** open a terminal in this folder and run `./start.sh`
(once, run `chmod +x start.sh` first). Add `--demo` for the offline demo.

To share this way, just send someone the whole folder (or a zip of it). They’ll
need Python installed — the launcher tells them how if it’s missing.

---

## Option 2 — Make a standalone app (for people who DON'T have Python)

This produces a self-contained app that runs on any Windows PC with **nothing
else installed** — no Python, no setup.

1. On a **Windows** PC that has Python, double-click **`Build-ACARS-EXE.bat`**.
2. Wait a few minutes. When it finishes you’ll have a ready-to-share zip:

       dist\ACARS-Tracks.zip

3. Send that **zip** to whoever you like. They **unzip it**, open the
   `ACARS-Tracks` folder, and double-click **`ACARS-Tracks.exe`**. The map opens
   in the browser. (A black window opens too — that’s the server; close it to stop.)

Good to know about the app:
- It’s **large** (a few hundred MB) because it carries Python, numpy, matplotlib
  and the NetCDF libraries inside it. The first launch on a new PC takes a few
  seconds — that’s normal.
- Keep the folder **together** — `ACARS-Tracks.exe` needs the files next to it.
  That’s why you share the whole zip, not just the .exe on its own.
- It saves its downloaded data in an **`acars_cache`** folder next to the .exe.
  You can delete that folder any time to clear the cache.

### “Windows protected your PC” / antivirus / Google Drive says it’s a virus

This is the single most common bump when sharing a homemade Windows app, and it’s
almost always a **false alarm** — not a real virus. Here’s the why and the what-to-do.

**Why it happens.** Tools like this are packaged with *PyInstaller*, which bundles
Python and all the libraries into the app. Antivirus engines (and Google Drive’s
scanner) use pattern-matching, and a bundled-Python app can resemble the
“packers” that real malware uses — so it gets flagged by *association*, even
though nothing is wrong. There is no way to make every antivirus on earth happy
with an unsigned homemade .exe; this is a known, documented quirk.

**What already helps (built into the build script):**
- The app is built in **one-folder mode**, which does *not* unpack itself at
  runtime — the behavior that most often trips the alarms. This alone clears most
  false positives.
- **UPX compression is disabled** and the **latest PyInstaller** is used, both of
  which further reduce flags.
- You share a **zip**, so the download isn’t a bare `.exe`.

**If a recipient still gets a warning:**
- **Google Drive “couldn’t scan / may be infected.”** Click **Download anyway**.
  (Drive scans files up to 100 MB and warns on anything it can’t clear; it does
  not mean a virus was confirmed.) Tip: sharing via a zip, or a service like
  OneDrive/Dropbox/WeTransfer, often avoids the message entirely.
- **Windows “protected your PC” (blue box).** Click **More info → Run anyway**.
  This appears for any program that isn’t code-signed; it’s about the *publisher
  being unknown*, not about anything being wrong.
- **Their antivirus quarantines it.** They can restore it from quarantine and add
  an exception/allow for the file. (Only do this for files from someone they
  trust — which, here, is you.)

**Want to prove it’s clean?** Upload the .exe to **[VirusTotal](https://www.virustotal.com)**
(free; handles files up to 650 MB). It scans with ~70 engines at once. A bundled
Python app typically gets a few of the lesser-known engines flagging it while the
major ones (Microsoft Defender, etc.) pass — the classic false-positive
fingerprint. You can send recipients the VirusTotal link for peace of mind.

**The only *complete* cure** is a **code-signing certificate** (you digitally sign
the app so Windows shows your name as a known publisher and the warnings stop).
They cost roughly $100–400/year from a certificate authority, so it’s usually
overkill for sharing with family or friends — but it’s the real fix if you ever
want to hand this out widely. Reporting the file to your antivirus vendor as a
false positive (most have a form) also gets it whitelisted within a few days.

### Where to host the download (this matters a lot)

**Don’t use Google Drive (or OneDrive) to hand out the app.** Those are built for
documents: they scan uploads and will **block or restrict** anything that looks
like an executable — including a perfectly clean bundled-Python app. If Drive
shows *“Your file may violate… Malware policy / Restricted file,”* that’s this
exact false positive. You can click **Request a review** (the Trust & Safety team
can clear it), but a freshly rebuilt app may get flagged again, so it’s better to
host somewhere meant for software:

- **GitHub Releases** — the standard, free home for app downloads. Make a free
  GitHub account, create a repository, then “Draft a new release” and attach your
  `ACARS-Tracks.zip` as a file. People download it from the release page; GitHub
  does **not** block executables. (This is the recommended option.)
- **itch.io** — free and very friendly for non-technical users; you get a tidy
  download page and it doesn’t block apps. Great if your audience isn’t technical.
- **A one-off send** — **WeTransfer** or a direct link from your own web space
  don’t block executables (WeTransfer links expire after a week or so).
- **SourceForge** — older, but also designed for distributing software.

On any of these, a recipient’s *local* antivirus or Windows SmartScreen might
still warn (see above) — but the **host won’t block the file**, which is the part
Google Drive was doing.

### If it keeps getting flagged: stronger options

The one-folder build already avoids most false positives. If a particular antivirus
(or Google) is still stubborn, in rough order of effort:

1. **Try a different PyInstaller version.** Some releases are flagged more than
   others. Version **5.13.2** is widely reported as much cleaner than the 6.x
   line. To use it, change the build script line `pip install --upgrade pyinstaller`
   to `pip install pyinstaller==5.13.2` (only works on Python ≤3.12).
2. **Report the false positive** to the vendor(s) flagging it (find them via a
   VirusTotal scan); they usually clear it within a few days.
3. **Switch the packager to Nuitka.** Instead of bundling, Nuitka *compiles* your
   Python to a real native program, which AV engines treat like any normal app —
   the most effective free way to stop persistent false positives. A ready-made
   script is included: run **`Build-ACARS-Nuitka.bat`** (it’s slower and needs a
   C compiler, which it offers to download automatically). It produces the same
   kind of shareable zip at `build_nuitka\ACARS-Tracks.zip`.
4. **Code-sign the app** (paid) — the only thing that removes the warnings for
   everyone, everywhere.

### Putting it on itch.io (recommended for non-technical friends)

itch.io is free, doesn’t block executables, and gives people a tidy download page.

1. Make a free account at **itch.io**, then **Dashboard → Create new project**.
2. Set **Kind of project = “Windows”** (a downloadable app) and give it a title.
3. Under **Uploads**, upload your **`ACARS-Tracks.zip`** and tick the **Windows**
   platform checkbox next to it. (A few hundred MB is fine.)
4. Set pricing to **free** (or “name your price”), set Visibility to **Public**
   (or keep it a secret/unlisted link if it’s just for family), and **Save**.
5. Share the project page link. People click **Download**, unzip, open the
   `ACARS-Tracks` folder, and run `ACARS-Tracks.exe`.

Recipients may still see Windows SmartScreen’s “More info → Run anyway” the first
time (any unsigned app does) — but nothing will *block* the download.

> Why can’t this ship as a ready-made .exe in the download? A Windows program has
> to be built on Windows, so the build step has to run on a Windows machine once.
> After that, the resulting app is fully shareable.

---

## Option 3 — Manual (advanced)

```
pip install -r requirements.txt
pip install -r requirements-optional.txt   # optional, nicer sounding plots
python server.py            # live data   (use --demo for offline synthetic data)
```

---

## One important note about internet

- **Live data** (real aircraft and soundings) needs internet to reach the NOAA
  MADIS feed.
- Even the **offline demo** still needs internet for the **map background tiles**,
  which load from the web. So “demo” means *no live weather feed required* — it is
  not a fully offline app.
- The fancy Skew-T renderer (**pyMeteo**) is **optional**. If it isn’t installed,
  the app automatically uses a clean built-in renderer instead — everything still
  works, the sounding plots just look slightly different.

## Notes for an IT / security review (e.g. NWS)

- **No Java.** This is a **Python** web server with a browser-based **JavaScript**
  interface. There is no Java, no Java Runtime (JRE), no browser applets, and no
  browser plugins of any kind. (JavaScript, despite the name, is unrelated to Java
  and is the standard scripting language every web browser already runs.)
- **The map library is bundled locally.** Leaflet is downloaded once from its
  official release and its **SHA-256 checksum is verified** before use, then stored
  in `static/vendor/leaflet/` and served locally — so at runtime the app makes **no
  external request for its interface code**. To prepare an offline copy, run the app
  (or `python vendor_leaflet.py`) once on a machine with internet, then distribute
  the folder (or the built `.exe`) with `static/vendor/leaflet/` included. The build
  scripts do this automatically. Until it’s vendored, the app falls back to the
  Leaflet CDN with a matching integrity hash.
- **Outbound connections at runtime** are only to government / open weather data
  sources: NOAA MADIS (aircraft data + archive), Iowa Environmental Mesonet and
  NOAA NCEI (radiosondes), the Aviation Weather Center (PIREPs + METARs), Open-Meteo (HRRR
  comparison), plus the map **background tiles** (CARTO). If your network blocks the
  tile host, the data overlays still work; only the base map imagery would be blank.
- **Runs entirely on the local machine.** The server listens only on
  `127.0.0.1` (localhost) — nothing is exposed to the network.
