#!/usr/bin/env python3
"""
inspect_profiles.py — show what's actually inside a MADIS ACARS *profiles* file.

Run this if the map shows "0 soundings" with live data. It downloads the most
recent profiles file and prints its dimensions and every variable (name, the
dimensions it uses, its shape, and units). Copy the output back and it can be
used to fix the parser for your exact file.

Usage (in this folder, after `pip install -r requirements.txt`):

    python inspect_profiles.py

That's it — no options needed.
"""

import gzip
import sys
from datetime import datetime, timedelta, timezone

BASE_URL = ("https://madis-data.ncep.noaa.gov/madisPublic1/data/point/"
            "acarsProfiles/netcdf/")


def http_get(url, timeout=90):
    try:
        import requests
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "acars-inspect/1.0"})
        return r.content if r.status_code == 200 else None
    except ImportError:
        import urllib.request
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "acars-inspect/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception:
            return None


def main():
    try:
        import netCDF4  # noqa: F401
        import numpy as np
    except Exception:
        print("This needs netCDF4 and numpy. Run:  pip install -r requirements.txt")
        sys.exit(1)
    from netCDF4 import Dataset, chartostring

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    blob = name = None
    for i in range(0, 7):
        fn = (now - timedelta(hours=i)).strftime("%Y%m%d_%H00.gz")
        print(f"trying {fn} ...")
        b = http_get(BASE_URL + fn)
        if b:
            blob, name = b, fn
            break

    if blob is None:
        print("\nCould not download any profiles file. Check your internet. A 403 means\n"
              "MADIS is rate-limiting anonymous users; free registration removes it:\n"
              "  https://madis.ncep.noaa.gov/madis_restrictions.shtml")
        sys.exit(1)

    print(f"\nDownloaded {name} ({len(blob):,} bytes compressed). Opening...\n")
    ds = Dataset("inmem", mode="r", memory=gzip.decompress(blob))

    print("================ GLOBALS ================")
    print("dimensions:")
    for k, v in ds.dimensions.items():
        print(f"    {k} = {len(v)}{'  (unlimited)' if v.isunlimited() else ''}")

    print("\n================ VARIABLES ================")
    print(f"{'name':<26} {'dims':<28} {'shape':<16} units")
    print("-" * 84)
    for vn in sorted(ds.variables):
        v = ds.variables[vn]
        print(f"{vn:<26} {str(tuple(v.dimensions)):<28} {str(tuple(v.shape)):<16} "
              f"{getattr(v, 'units', '')}")

    # show a few sample values for the most relevant fields, if present
    print("\n================ SAMPLES (first profile) ================")
    interesting = ["tailNumber", "en_tailNumber", "staLoc", "stationName",
                   "profileType", "nLevels", "latitude", "longitude", "pressure",
                   "altitude", "temperature", "dewpoint", "windDir", "windSpeed",
                   "timeObs"]
    for vn in interesting:
        if vn not in ds.variables:
            continue
        v = ds.variables[vn]
        try:
            if v.dtype.kind in ("S", "U"):           # character
                s = chartostring(v[:])
                s = np.atleast_1d(s)
                print(f"  {vn}: {repr(str(s[0]))}  (n={len(s)})")
            elif v.ndim == 2:
                row = np.ma.filled(v[0].astype('float64'), np.nan)
                good = row[np.isfinite(row) & (np.abs(row) < 1e30)][:6]
                print(f"  {vn}[0, :6 valid]: {np.array2string(good, precision=2)}")
            else:
                arr = np.ma.filled(v[:].astype('float64'), np.nan)
                good = arr[np.isfinite(arr) & (np.abs(arr) < 1e30)][:6]
                print(f"  {vn}[:6 valid]: {np.array2string(good, precision=2)}")
        except Exception as e:
            print(f"  {vn}: (could not sample: {e})")

    _scan_time_vars(ds, np)
    _scan_qc_vars(ds, np, chartostring)

    ds.close()
    print("\nDone. Copy everything above to get the parser tuned to your file.")


# MADIS quality-control descriptor ("DD") letters, per the MADIS QC documentation.
# These are the single-character verdicts attached to each observation.
_DD_MEANING = {
    "Z": "no QC applied (preliminary)",
    "C": "coarse pass — passed level 1 (validity/range)",
    "S": "screened — passed levels 1 and 2 (internal consistency)",
    "V": "verified — passed levels 1, 2 and 3 (temporal/spatial)",
    "X": "REJECTED — failed level 1 (gross error)",
    "Q": "QUESTIONED — passed level 1, failed level 2 or 3",
    "G": "subjective good (forecaster flagged good)",
    "B": "SUBJECTIVE BAD (forecaster flagged bad)",
    "T": "virtual temperature could not be calculated",
    "K": "passed, but value was corrected/estimated",
}

_QC_HINTS = ("qcr", "qcd", "qca", "qct", "_dd", "dd", "qc", "flag",
             "datadescriptor", "errortype", "checksrun", "results")

# MADIS "REPWVQC" — the WVSS-II moisture sensor's own health report. This is the
# field that can identify an airframe with a broken humidity sensor.
_WVQC_FSL = {
    45: "missing", 48: "normal (ground speed > 60 kt)",
    49: "normal, non-measurement mode",
    50: "*** RH below sensor floor — clamped to 1.5% (reads bone dry) ***",
    51: "*** humidity element WET ***",
    52: "*** humidity element CONTAMINATED ***",
    53: "*** HEATER FAIL ***", 54: "*** HEATER FAIL + wet/contaminated ***",
    55: "*** input to mixing-ratio calc invalid ***",
    56: "*** numeric error ***", 57: "*** dewpoint greater than temperature ***",
}
_WVQC_AWIPS = {
    0: "normal, measurement mode", 1: "normal, non-measurement mode",
    2: "*** small RH (sensor at its floor — reads very dry) ***",
    3: "*** humidity element WET ***", 4: "*** humidity element CONTAMINATED ***",
    5: "*** HEATER FAIL ***", 6: "*** HEATER FAIL + wet/contaminated ***",
    7: "*** an input is invalid ***", 8: "*** numeric error ***",
    9: "*** SENSOR NOT INSTALLED ***", 63: "missing",
}


def _wv_decode(vals):
    """Decode reported-water-vapor QC codes if these values look like them."""
    v = {int(x) for x in vals}
    if v & set(range(48, 58)):
        return _WVQC_FSL, "FSL"
    if v & set(range(0, 10)) and not (v - set(range(0, 10)) - {63}):
        return _WVQC_AWIPS, "AWIPS"
    return None, None


def _looks_qc(name):
    n = name.lower()
    if n.endswith("dd") or n.endswith("qcr") or n.endswith("qcd") or n.endswith("qca"):
        return True
    return any(h in n for h in ("qc", "flag", "datadescriptor", "errortype"))


def _scan_qc_vars(ds, np, chartostring):
    """Find and decode MADIS quality-control fields, if this file carries them.

    MADIS runs its own QC and normally publishes the verdicts alongside the data:
      <var>DD   a single letter per ob  (V/S/C = passed, X/Q/B = suspect or bad)
      <var>QCR  bitmask of which checks FAILED
      <var>QCA  bitmask of which checks were APPLIED
      <var>QCD  the departure/difference each check computed
    """
    print("\n================ QUALITY-CONTROL (QC) FIELDS ================")
    print("MADIS attaches its own QC verdicts to each observation. Anything listed")
    print("here can be used to hide or highlight bad data.\n")

    qcvars = [vn for vn in sorted(ds.variables) if _looks_qc(vn)]
    if not qcvars:
        print("  (no QC-looking variables found in this file — paste the VARIABLES")
        print("   list above and they can still be identified by hand.)")
        return

    print(f"  Found {len(qcvars)} QC-looking variable(s):\n")
    for vn in qcvars:
        v = ds.variables[vn]
        units = getattr(v, "units", "")
        comment = getattr(v, "comment", "") or getattr(v, "long_name", "")
        print(f"  >> {vn}   dims={tuple(v.dimensions)} shape={tuple(v.shape)}"
              f"{('  units=' + units) if units else ''}")
        if comment:
            print(f"       description: {str(comment)[:160]}")
        # any attribute that documents the bit/flag meanings is gold — print it
        for att in v.ncattrs():
            if att.lower() in ("units", "comment", "long_name", "_fillvalue"):
                continue
            val = getattr(v, att)
            print(f"       {att}: {str(val)[:200]}")
        # sample the actual values so we can see what verdicts are really present
        try:
            if v.dtype.kind in ("S", "U"):                 # character DD flags
                arr = np.atleast_1d(chartostring(v[:]))
                flat = [str(x).strip() for x in arr.ravel() if str(x).strip()]
                counts = {}
                for c in flat:
                    for ch in c:                           # DD fields are per-letter
                        counts[ch] = counts.get(ch, 0) + 1
                if counts:
                    print("       values seen:")
                    for ch, n in sorted(counts.items(), key=lambda kv: -kv[1])[:10]:
                        mean = _DD_MEANING.get(ch.upper(), "unknown code")
                        print(f"         '{ch}' x{n:<7} {mean}")
            else:
                arr = np.ma.filled(v[:].astype("float64"), np.nan)
                fin = arr[np.isfinite(arr) & (np.abs(arr) < 1e30)]
                if fin.size:
                    uniq, cnt = np.unique(fin, return_counts=True)
                    order = np.argsort(-cnt)[:10]
                    pairs = ", ".join(f"{uniq[i]:g}(x{cnt[i]})" for i in order)
                    print(f"       values seen: {pairs}")
                    tbl, which = _wv_decode(uniq)
                    if tbl is not None:
                        print(f"       ^ these look like reported water-vapor QC "
                              f"codes ({which} table):")
                        for i in order:
                            code = int(uniq[i])
                            print(f"         {code:<4} x{cnt[i]:<8} "
                                  f"{tbl.get(code, 'unknown code')}")
                    if "qcr" in vn.lower():
                        print("         (QCR is a bitmask: 0 = passed everything;")
                        print("          non-zero = at least one QC check FAILED)")
                else:
                    print("       values seen: (all missing/fill)")
        except Exception as e:
            print(f"       (could not sample: {e})")
        print()

    print("  How to read the DD letters:")
    print("    V / S / C  = passed QC (verified / screened / coarse)")
    print("    X          = REJECTED, failed the gross-error check")
    print("    Q          = QUESTIONED, failed a consistency check")
    print("    B          = subjectively flagged bad;   Z = no QC applied yet")


def _scan_time_vars(ds, np):
    """Print every variable whose values look like a time, so the time field is
    easy to spot even if its name is unusual."""
    print("\n================ TIME-LIKE VARIABLES ================")
    print("(any field whose numbers look like a clock/epoch — the ob time is")
    print(" usually 'seconds since midnight UTC', i.e. values 0–86400)\n")
    found = False
    for vn in sorted(ds.variables):
        v = ds.variables[vn]
        try:
            if v.dtype.kind not in ("f", "i", "u"):
                continue
            arr = np.ma.filled(v[:].astype("float64"), np.nan)
            fin = arr[np.isfinite(arr) & (np.abs(arr) < 1e30)]
            if fin.size == 0:
                continue
            med = float(np.median(fin))
            lo, hi = float(np.min(fin)), float(np.max(fin))
            kind = None
            if 1e8 < med < 5e9:
                kind = "epoch seconds (since 1970)"
            elif 1e11 < med < 5e12:
                kind = "epoch milliseconds"
            elif 0 <= med <= 86401:
                kind = "seconds since midnight UTC"
            nm = vn.lower()
            timeish = any(k in nm for k in ("time", "sec", "day", "utc", "tod", "epoch"))
            if kind and timeish:
                found = True
                print(f"  >> {vn:<24} {kind:<28} range {lo:.0f}…{hi:.0f}")
        except Exception:
            continue
    if not found:
        print("  (none found by name — paste the VARIABLES list above and it can")
        print("   still be identified.)")


if __name__ == "__main__":
    main()
