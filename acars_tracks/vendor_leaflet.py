"""Vendor Leaflet locally so the app makes no external requests for its map
library at runtime — which is what a locked-down network (e.g. the NWS) wants.

Pure Python standard library (urllib + hashlib), no extra packages. Each file is
downloaded from the official Leaflet release and verified against the published
Subresource-Integrity (SRI) SHA-256 checksum before it is saved, so a corrupted
or tampered download is rejected rather than used.

Run once on a machine with internet:  python vendor_leaflet.py
After that, static/vendor/leaflet/ holds leaflet.js + leaflet.css and the app
serves them locally. server.py also calls ensure_leaflet() on startup, so the
first run that has internet vendors Leaflet automatically. Ship the populated
static/vendor/leaflet/ folder (or the built .exe) to offline machines.
"""

import base64
import hashlib
import os
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
VENDOR_DIR = os.path.join(_HERE, "static", "vendor", "leaflet")

# Pinned to Leaflet 1.9.4. The checksums are the official SRI sha256 hashes
# published on leafletjs.com/download.html for these exact files.
FILES = {
    "leaflet.css": ("https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
                    "sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="),
    "leaflet.js":  ("https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
                    "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="),
}


def _sri(data):
    """Subresource-Integrity string for some bytes, e.g. 'sha256-....'."""
    return "sha256-" + base64.b64encode(hashlib.sha256(data).digest()).decode()


def _path(name):
    return os.path.join(VENDOR_DIR, name)


def _verified(name, want):
    try:
        with open(_path(name), "rb") as fh:
            return _sri(fh.read()) == want
    except OSError:
        return False


def have_leaflet():
    """True if both Leaflet files are present locally (used to decide whether the
    page loads them locally or falls back to the CDN)."""
    return all(os.path.getsize(_path(n)) > 0
               for n in FILES if os.path.exists(_path(n))) and \
        all(os.path.exists(_path(n)) for n in FILES)


def ensure_leaflet(verbose=True):
    """Make sure the pinned, checksum-verified Leaflet files are present. Downloads
    any that are missing or fail verification. Best-effort: if there's no internet
    and the files aren't already here, it just reports and returns False (the app
    then falls back to the CDN, which still works when online)."""
    os.makedirs(VENDOR_DIR, exist_ok=True)
    for name, (url, want) in FILES.items():
        if _verified(name, want):
            continue
        try:
            if verbose:
                print("[vendor] fetching %s ..." % name)
            req = urllib.request.Request(url, headers={"User-Agent": "acars-tracks/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            got = _sri(data)
            if got != want:
                if verbose:
                    print("[vendor] checksum mismatch for %s (%s); not saving" % (name, got))
                continue
            with open(_path(name), "wb") as fh:
                fh.write(data)
            if verbose:
                print("[vendor] saved + verified %s" % name)
        except Exception as e:
            if verbose:
                print("[vendor] could not fetch %s (%s: %s)" % (name, type(e).__name__, e))
    return have_leaflet()


if __name__ == "__main__":
    ok = ensure_leaflet()
    if ok:
        print("Leaflet is vendored locally in static/vendor/leaflet/ — the app "
              "needs no internet for its map library.")
    else:
        print("Leaflet is NOT fully vendored yet. Run this once on a machine with "
              "internet; the app falls back to the CDN until then.")
