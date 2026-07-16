"""
sounding_plot.py — Render an ACARS vertical profile as a Skew-T/Log-P diagram.

Primary renderer is **pyMeteo** (pymeteo.skewt.plot), exactly as the user asked.
pyMeteo's array entry point is:

    pymeteo.skewt.plot(None, z, th, p, qv, u, v, output)

with SI units: z [m], th [K] (potential temperature), p [Pa], qv [kg/kg]
(water-vapor mixing ratio), u/v [m/s]. We compute th, qv, u, v from the profile.

If pyMeteo isn't installed (or its call fails), we fall back to a clean built-in
matplotlib Skew-T so the page still works. requirements.txt lists pymeteo, so the
normal path uses pyMeteo.
"""

import math
import os
from datetime import datetime, timezone

os.environ.setdefault("MPLBACKEND", "Agg")
import numpy as np
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["savefig.dpi"] = 150          # crisper output for zooming
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

P0 = 100000.0       # reference pressure, Pa
RD_CP = 0.2854      # Rd/cp for potential temperature

# distinct, readable trace colors for overlaying multiple soundings (dark bg)
OVERLAY_COLORS = ["#f0c419", "#5dade2", "#2ecc71", "#e74c3c", "#bb8fce",
                  "#ff9f43", "#48dbfb", "#ec7063", "#a3cb38", "#f78fb3"]


# --------------------------------------------------------------------------- #
#  thermodynamics                                                              #
# --------------------------------------------------------------------------- #
def _theta_K(T_K, p_Pa):
    return T_K * (P0 / p_Pa) ** RD_CP


def _qv_from_Td(Td_K, p_Pa):
    """Water-vapor mixing ratio (kg/kg) from dewpoint (K) and pressure (Pa)."""
    Tc = Td_K - 273.15
    e = 611.2 * math.exp(17.67 * Tc / (Tc + 243.5))     # vapor pressure, Pa
    e = min(e, p_Pa * 0.99)
    return max(1e-6, 0.622 * e / (p_Pa - e))


def _uv(wspd_ms, wdir_deg):
    r = math.radians(wdir_deg)
    return (-wspd_ms * math.sin(r), -wspd_ms * math.cos(r))


def _prep(sounding):
    """Clean + convert levels into the SI arrays pyMeteo needs."""
    z, p, T, Td, th, qv, u, v = [], [], [], [], [], [], [], []
    wd, ws = [], []
    have_hum = False
    for L in sounding["levels"]:
        pp, tt = L.get("p"), L.get("T")
        if pp is None or tt is None or pp <= 0:
            continue
        zz = L.get("z")
        if zz is None:                                   # estimate z from p
            zz = (1.0 - (pp / 101325.0) ** (1 / 5.25588)) / 2.25577e-5
        tdv = L.get("Td")
        if tdv is None or tdv > tt + 0.5:                # no/!valid humidity
            q = 1e-6
            tdv_use = tt - 30.0
        else:
            q = _qv_from_Td(tdv, pp)
            tdv_use = tdv
            have_hum = True
        wdir = L.get("wdir"); wspd = L.get("wspd")
        if wdir is None or wspd is None:
            uu = vv = 0.0; wdir = 0.0; wspd = 0.0
        else:
            uu, vv = _uv(wspd, wdir)
        z.append(zz); p.append(pp); T.append(tt); Td.append(tdv_use)
        th.append(_theta_K(tt, pp)); qv.append(q); u.append(uu); v.append(vv)
        wd.append(wdir); ws.append(wspd)

    if len(p) < 3:
        return None

    order = np.argsort(p)[::-1]                           # surface -> top
    g = lambda a: np.asarray(a, dtype=float)[order]
    return {
        "z": g(z), "p": g(p), "T": g(T), "Td": g(Td), "th": g(th),
        "qv": g(qv), "u": g(u), "v": g(v), "wd": g(wd), "ws": g(ws),
        "have_hum": have_hum,
    }


# --------------------------------------------------------------------------- #
#  pyMeteo renderer (primary)                                                  #
# --------------------------------------------------------------------------- #
def _plot_pymeteo(a, out_path, title):
    import pymeteo.skewt as skewt          # raises ImportError if not installed
    skewt.plot(None, a["z"], a["th"], a["p"], a["qv"], a["u"], a["v"], out_path)
    return "pyMeteo"


# --------------------------------------------------------------------------- #
#  built-in fallback Skew-T (used only if pyMeteo is unavailable)              #
# --------------------------------------------------------------------------- #
SKEW = 70.0                 # degrees of skew (retuned for the 300 hPa top)
PB = 1050.0                 # bottom (surface), hPa
PT_DEFAULT = 300.0          # default top — ACARS soundings seldom climb above this
PT_FLOOR = 150.0            # extend no higher than this if data actually does
TMIN, TMAX = -40.0, 45.0    # temperature bounds at 1000 hPa, C
ISOBARS = [1000, 950, 900, 850, 800, 750, 700, 650, 600, 550,
           500, 450, 400, 350, 300, 250, 200, 150, 100, 70]
ISOBARS_MAJOR = {1000, 850, 700, 500, 400, 300, 250, 200, 150, 100, 70}


def _top_for(*preps, default=PT_DEFAULT, floor=PT_FLOOR):
    """Plot top in hPa: `default`, but extend upward if a sounding actually
    climbs higher (lower pressure), so real data is never clipped."""
    pmins = [float(np.min(a["p"])) / 100.0 for a in preps if len(a["p"])]
    pmin = min(pmins) if pmins else default
    if pmin < default:
        return max(floor, pmin - 15.0)
    return default


def _xfm(Tc, p_hPa):
    return Tc + SKEW * math.log10(1000.0 / p_hPa)


def _skewt_axes(title, p_top=PT_DEFAULT):
    """Create a dark Skew-T figure with isobars + skewed isotherms drawn."""
    fig = plt.figure(figsize=(8.6, 10.0), dpi=110)
    fig.patch.set_facecolor("#10161d")
    ax = fig.add_axes([0.10, 0.08, 0.74, 0.86])
    ax.set_facecolor("#0e141b")
    yb, yt = math.log10(PB), math.log10(p_top)
    ax.set_ylim(yb, yt)
    ax.set_xlim(TMIN, TMAX)
    for pp in ISOBARS:
        if pp < p_top - 0.5:
            continue
        major = pp in ISOBARS_MAJOR
        ax.plot([TMIN, TMAX], [math.log10(pp)] * 2,
                color="#2a3742" if major else "#1b2530",
                lw=0.7 if major else 0.5, zorder=1)
        if major:
            ax.text(TMIN + 0.4, math.log10(pp), f"{pp}", color="#6f7f8c",
                    fontsize=8, va="center", ha="left")
    for Tref in range(-100, 51, 10):
        xs = [_xfm(Tref, pp) for pp in (PB, p_top)]
        ax.plot(xs, [yb, yt], color="#243947" if Tref else "#3a5a2a", lw=0.7, zorder=1)
        if TMIN <= _xfm(Tref, 1000) <= TMAX:
            ax.text(Tref, yb + 0.002, f"{Tref}", color="#6f7f8c", fontsize=7,
                    ha="center", va="bottom")
    ax.set_yticks([])
    ax.set_xticks(range(int(TMIN), int(TMAX) + 1, 10))
    ax.tick_params(colors="#6f7f8c")
    for s in ax.spines.values():
        s.set_color("#2a3742")
    ax.set_xlabel("Temperature (°C, skewed)", color="#9fb0bd", fontsize=9)
    ax.set_title(title, color="#eef2f5", fontsize=11, pad=10)
    return fig, ax, yb, yt


def _plot_fallback(a, sounding, out_path, title, analysis=None, p_top=None):
    if p_top is None:
        p_top = _top_for(a)
    fig, ax, yb, yt = _skewt_axes(title, p_top)
    p_hPa = a["p"] / 100.0
    yy = np.log10(p_hPa)
    xT = [_xfm(t, pp) for t, pp in zip(a["T"] - 273.15, p_hPa)]
    xTd = [_xfm(t, pp) for t, pp in zip(a["Td"] - 273.15, p_hPa)]

    drew_parcel = False
    if analysis and analysis.get("parcel_p") and a["have_hum"]:
        pp = np.array(analysis["parcel_p"], dtype=float)        # hPa, descending
        tp = np.array(analysis["parcel_T"], dtype=float)        # deg C
        order = np.argsort(pp)                                   # ascending p for fill
        pp, tp = pp[order], tp[order]
        ypar = np.log10(pp)
        xpar = np.array([_xfm(t, q) for t, q in zip(tp, pp)])
        envT_on = np.interp(pp, (a["p"] / 100.0)[::-1], (a["T"] - 273.15)[::-1])
        xenv = np.array([_xfm(t, q) for t, q in zip(envT_on, pp)])
        ax.fill_betweenx(ypar, xenv, xpar, where=(xpar > xenv),
                         color="#e74c3c", alpha=0.16, zorder=2)   # CAPE
        ax.fill_betweenx(ypar, xenv, xpar, where=(xpar < xenv),
                         color="#5dade2", alpha=0.13, zorder=2)   # CIN / negative
        ax.plot(xpar, ypar, color="#f5b800", lw=1.8, ls=(0, (5, 2)), zorder=6)

        def _mark(pval, label, col):
            if not pval:
                return
            yv = math.log10(pval)
            xv = float(np.interp(pval, pp, xpar))
            ax.plot([xv], [yv], marker="o", ms=4, color=col, zorder=7)
            ax.annotate(label, (xv, yv), textcoords="offset points", xytext=(6, 0),
                        color=col, fontsize=8, va="center", fontweight="bold")
        _mark(analysis.get("lcl_p"), "LCL", "#f5b800")
        _mark(analysis.get("lfc_p"), "LFC", "#ff7f50")
        _mark(analysis.get("el_p"), "EL", "#cfd8e0")
        drew_parcel = True

    ax.plot(xT, yy, color="#e74c3c", lw=2.2, zorder=5)
    if a["have_hum"]:
        ax.plot(xTd, yy, color="#2ecc71", lw=2.2, zorder=5)

    xw = TMAX + 4.5
    ax.set_xlim(TMIN, xw + 3)
    step = max(1, len(p_hPa) // 26)
    for i in range(0, len(p_hPa), step):
        _barb(ax, xw, math.log10(p_hPa[i]), a["ws"][i], a["wd"][i])

    leg = [Line2D([0], [0], color="#e74c3c", lw=2.2, label="Temperature")]
    if a["have_hum"]:
        leg.append(Line2D([0], [0], color="#2ecc71", lw=2.2, label="Dewpoint"))
    else:
        leg.append(Line2D([0], [0], color="#6f7f8c", lw=1, label="(no humidity reported)"))
    if drew_parcel:
        leg.append(Line2D([0], [0], color="#f5b800", lw=1.8, ls=(0, (5, 2)),
                          label="Parcel (surface)"))
    ax.legend(handles=leg, loc="upper right", fontsize=8,
              facecolor="#18212b", edgecolor="#2a3742", labelcolor="#cfd8e0")
    fig.text(0.5, 0.022, "Skew-T / Log-P  ·  built-in renderer (pyMeteo not installed)",
             color="#6f7f8c", fontsize=8, ha="center")
    fig.savefig(out_path, facecolor=fig.get_facecolor())
    plt.close(fig)
    return "built-in"


def _plot_multi(preps, labels, out_path, title):
    """Overlay several soundings' T (solid) and Td (dashed) on one Skew-T."""
    fig, ax, yb, yt = _skewt_axes(title, _top_for(*preps, floor=100.0))
    handles = []
    for i, a in enumerate(preps):
        c = OVERLAY_COLORS[i % len(OVERLAY_COLORS)]
        p_hPa = a["p"] / 100.0
        yy = np.log10(p_hPa)
        xT = [_xfm(t, pp) for t, pp in zip(a["T"] - 273.15, p_hPa)]
        ax.plot(xT, yy, color=c, lw=2.0, zorder=5)
        if a["have_hum"]:
            xTd = [_xfm(t, pp) for t, pp in zip(a["Td"] - 273.15, p_hPa)]
            ax.plot(xTd, yy, color=c, lw=1.5, ls=(0, (4, 2)), zorder=5)
        handles.append(Line2D([0], [0], color=c, lw=2.4, label=labels[i]))
    handles.append(Line2D([0], [0], color="#9fb0bd", lw=2.0, label="solid: T"))
    handles.append(Line2D([0], [0], color="#9fb0bd", lw=1.5, ls=(0, (4, 2)), label="dashed: Td"))
    ax.legend(handles=handles, loc="upper right", fontsize=8, facecolor="#18212b",
              edgecolor="#2a3742", labelcolor="#cfd8e0", framealpha=0.92)
    fig.text(0.5, 0.022, "Skew-T / Log-P  ·  overlay (oldest → newest)",
             color="#6f7f8c", fontsize=8, ha="center")
    fig.savefig(out_path, facecolor=fig.get_facecolor())
    plt.close(fig)
    return "built-in (overlay)"


def _barb(ax, x, y, spd_ms, wdir):
    """Northern-Hemisphere wind barb (knots), drawn in display space."""
    kt = spd_ms * 1.943844
    s = int(round(kt / 5.0) * 5)
    pend = s // 50; s -= pend * 50
    full = s // 10; s -= full * 10
    half = 1 if s >= 5 else 0

    ang = math.radians(wdir)
    d = np.array([math.sin(ang), math.cos(ang)])      # staff toward wind-from
    perp = np.array([d[1], -d[0]])                     # NH: right of staff

    base = ax.transData.transform((x, y))
    L = 26.0
    tip = base + d * L
    lines = [(base, tip)]                              # staff

    pos = tip.copy()
    if kt < 2.5:                                       # calm: just a short staff
        lines = [(base, base + d * 8)]
    for _ in range(pend):
        apex = pos + perp * 11 - d * 3
        nxt = pos - d * 7
        lines += [(pos, apex), (apex, nxt), (nxt, pos)]
        pos = pos - d * 8
    for _ in range(full):
        lines.append((pos, pos + perp * 11 - d * 3)); pos = pos - d * 6
    if half:
        if pend == 0 and full == 0:
            pos = pos - d * 5
        lines.append((pos, pos + perp * 6 - d * 1.6))

    inv = ax.transData.inverted()
    for a_pt, b_pt in lines:
        (x1, y1) = inv.transform(a_pt)
        (x2, y2) = inv.transform(b_pt)
        ax.add_line(Line2D([x1, x2], [y1, y2], color="#ffb000", lw=1.4, zorder=6))


# --------------------------------------------------------------------------- #
#  public entry point                                                          #
# --------------------------------------------------------------------------- #
def make_png(sounding, out_path, analysis=None):
    """Render `sounding` to out_path. Returns (renderer_name, info_dict)."""
    a = _prep(sounding)
    if a is None:
        raise ValueError("profile too sparse to plot (need >= 3 valid levels)")

    tail = sounding.get("tail", "—")
    loc = sounding.get("place") or sounding.get("airport", "")
    ud = sounding.get("updown", "")
    if sounding.get("kind") == "raob":
        title = ("Radiosonde · " + (sounding.get("name", "") or loc or "")).strip(" ·")
        if sounding.get("source") == "DWD":
            title += "  ·  Source: DWD"
        if sounding.get("launch_miss"):
            title += "  ·  %s not launched" % sounding["launch_miss"]
    else:
        title = f"ACARS sounding · {tail} · {loc} {ud}".strip()
    _wv = sounding.get("wvqc") or {}
    _ms = sounding.get("moist_suspect") or {}
    if _wv.get("frac", 0) >= 0.25 or _ms.get("chronic"):
        title += "  ·  DEWPOINT LIKELY BAD — use with caution"
    elif _ms:
        title += "  ·  dewpoint suspect (%.0f°C drier than peers)" % _ms.get("excess", 0)
    _qc = sounding.get("qc") or {}
    # same floor the UI uses: MADIS levels 1-2 are per-ob checks, so a couple of
    # flagged obs on a long profile isn't worth marking the plot over.
    if _qc.get("flagged") and _qc.get("total") \
            and _qc["flagged"] >= 0.20 * _qc["total"]:
        title += "  ·  %d of %d levels QC-flagged" % (_qc["flagged"], _qc["total"])

    p_top = 100.0 if sounding.get("kind") == "raob" else _top_for(a)
    geom = None
    try:
        renderer = _plot_pymeteo(a, out_path, title)
    except Exception as e:
        renderer = _plot_fallback(a, sounding, out_path, title, analysis, p_top)
        renderer += f" (pyMeteo unavailable: {type(e).__name__})"
        # geometry of the built-in Skew-T as fractions of the PNG, so the browser can
        # map a cursor's vertical position to pressure (the y-axis is log10(pressure))
        geom = {
            "scale": "logp",
            "x0": 0.10, "x1": 0.84,          # data area left / right edge
            "y0": 0.06, "y1": 0.92,          # data area top / bottom edge (image top = 0)
            "p_top": round(float(p_top), 1), # hPa at y0
            "p_bot": float(PB),              # hPa at y1
        }
    info = {
        "levels": int(len(a["p"])),
        "sfc_p_hPa": round(float(a["p"][0]) / 100.0, 1),
        "top_p_hPa": round(float(a["p"][-1]) / 100.0, 1),
        "have_humidity": bool(a["have_hum"]),
        "geom": geom,
    }
    return renderer, info


def make_png_multi(soundings, out_path, airport=""):
    """Overlay several soundings on one Skew-T. Returns (renderer, info).

    Always uses the built-in renderer (pyMeteo's high-level plot() draws a single
    profile, so overlays are drawn directly). Soundings are ordered oldest -> newest
    so the legend reads chronologically.
    """
    ordered = sorted(soundings, key=lambda s: (s.get("time") or 0))
    preps, labels, members = [], [], []
    for s in ordered:
        a = _prep(s)
        if a is None:
            continue
        c = OVERLAY_COLORS[len(preps) % len(OVERLAY_COLORS)]
        t = s.get("time")
        tstr = (datetime.fromtimestamp(t, tz=timezone.utc).strftime("%H:%MZ") if t else "")
        ud = s.get("updown", "")
        lab = s.get("tail", "?") + (f"  {tstr}" if tstr else "") + (f"  {ud}" if ud else "")
        preps.append(a); labels.append(lab)
        members.append({"id": s["id"], "tail": s.get("tail", ""), "time": tstr,
                        "updown": ud, "color": c})
    if not preps:
        raise ValueError("no plottable soundings in overlay")
    n = len(preps)
    title = (f"{airport} · " if airport else "") + f"{n} soundings overlaid"
    renderer = _plot_multi(preps, labels, out_path, title)
    return renderer, {"count": n, "members": members, "airport": airport}


# --------------------------------------------------------------------------- #
#  hodograph                                                                   #
# --------------------------------------------------------------------------- #
_MS_TO_KT = 1.943844

_HODO_BANDS = [
    (0.0, 1.0, "#ff4d4d", "0–1 km"),
    (1.0, 3.0, "#ff9f1c", "1–3 km"),
    (3.0, 6.0, "#ffe04d", "3–6 km"),
    (6.0, 9.0, "#4dd2ff", "6–9 km"),
    (9.0, 99.0, "#7f9fff", "9 km+"),
]


def _hodo_band_color(zkm):
    for lo, hi, c, _ in _HODO_BANDS:
        if lo <= zkm < hi:
            return c
    return _HODO_BANDS[-1][2]


def make_hodograph_png(sounding, out_path, analysis=None):
    """Render a hodograph (wind u/v vs height) for the sounding.

    Returns True on success, or False if the profile lacks enough wind data.
    """
    levels = sorted(
        (L for L in sounding.get("levels", [])
         if L.get("p") and L.get("wspd") is not None and L.get("wdir") is not None),
        key=lambda L: -L["p"])
    if len(levels) < 3:
        return False

    zs = []
    for L in levels:
        z = L.get("z")
        if z is None:
            z = (1.0 - (L["p"] / 101325.0) ** (1 / 5.25588)) / 2.25577e-5
        zs.append(z)
    z0 = zs[0]
    pts = []
    for L, z in zip(levels, zs):
        spd = L["wspd"] * _MS_TO_KT
        r = math.radians(L["wdir"])
        pts.append(((z - z0) / 1000.0, -spd * math.sin(r), -spd * math.cos(r)))
    capped = [p for p in pts if p[0] <= 12.0]
    pts = capped if len(capped) >= 3 else pts
    if len(pts) < 3:
        return False

    zkm = np.array([p[0] for p in pts])
    uu = np.array([p[1] for p in pts])
    vv = np.array([p[2] for p in pts])

    maxspd = float(np.nanmax(np.hypot(uu, vv)))
    R = max(40.0, math.ceil((maxspd + 8) / 10.0) * 10.0)

    fig = plt.figure(figsize=(6.0, 6.3), dpi=150)
    fig.patch.set_facecolor("#10161d")
    ax = fig.add_axes([0.12, 0.10, 0.85, 0.82])
    ax.set_facecolor("#0e141b")
    ax.set_aspect("equal")
    ax.set_xlim(-R, R)
    ax.set_ylim(-R, R)

    rr = 20.0
    while rr <= R + 0.1:
        ax.add_patch(plt.Circle((0, 0), rr, fill=False, color="#2a3742", lw=0.8, zorder=1))
        ax.text(0, rr, f"{int(rr)}", color="#6f7f8c", fontsize=7,
                ha="center", va="bottom", zorder=2)
        rr += 20.0
    ax.plot([-R, R], [0, 0], color="#243947", lw=0.8, zorder=1)
    ax.plot([0, 0], [-R, R], color="#243947", lw=0.8, zorder=1)

    for i in range(len(zkm) - 1):
        ax.plot(uu[i:i + 2], vv[i:i + 2], color=_hodo_band_color(zkm[i]),
                lw=2.4, solid_capstyle="round", zorder=5)
    ax.plot([uu[0]], [vv[0]], marker="o", ms=5, color="#ffffff", zorder=7)   # surface

    for hkm in (1, 3, 6, 9):
        if zkm.min() <= hkm <= zkm.max():
            ui = float(np.interp(hkm, zkm, uu))
            vi = float(np.interp(hkm, zkm, vv))
            ax.plot([ui], [vi], marker="o", ms=3, color="#cfd8e0", zorder=6)
            ax.annotate(f"{hkm}", (ui, vi), textcoords="offset points",
                        xytext=(4, 3), color="#cfd8e0", fontsize=7, zorder=6)

    if analysis:
        su, sv = analysis.get("storm_u_kt"), analysis.get("storm_v_kt")
        mu, mv = analysis.get("mw_u_kt"), analysis.get("mw_v_kt")
        if su is not None and sv is not None and abs(su) <= R and abs(sv) <= R:
            ax.plot([su], [sv], marker="o", ms=8, mfc="none", mec="#ff6ec7",
                    mew=1.8, zorder=7)
            ax.annotate("RM", (su, sv), textcoords="offset points", xytext=(7, -3),
                        color="#ff6ec7", fontsize=8, fontweight="bold", zorder=7)
        if mu is not None and mv is not None and abs(mu) <= R and abs(mv) <= R:
            ax.plot([mu], [mv], marker="s", ms=6, mfc="none", mec="#9fb0bd",
                    mew=1.5, zorder=7)
            ax.annotate("MW", (mu, mv), textcoords="offset points", xytext=(7, -3),
                        color="#9fb0bd", fontsize=8, zorder=7)

    leg = [Line2D([0], [0], color=c, lw=2.6, label=lbl)
           for lo, hi, c, lbl in _HODO_BANDS if np.any((zkm >= lo) & (zkm < hi))]
    if analysis and analysis.get("storm_u_kt") is not None:
        leg.append(Line2D([0], [0], marker="o", mfc="none", mec="#ff6ec7", mew=1.8,
                          ls="none", label="Bunkers RM"))
    if leg:
        ax.legend(handles=leg, loc="upper left", fontsize=7, facecolor="#18212b",
                  edgecolor="#2a3742", labelcolor="#cfd8e0", framealpha=0.92)

    ax.tick_params(colors="#6f7f8c", labelsize=7)
    for s in ax.spines.values():
        s.set_color("#2a3742")
    ax.set_xlabel("u  (kt, eastward →)", color="#6f7f8c", fontsize=8)
    ax.set_ylabel("v  (kt, northward →)", color="#6f7f8c", fontsize=8)

    tail = sounding.get("tail", "—")
    loc = sounding.get("place") or sounding.get("airport", "")
    ax.set_title(f"Hodograph · {tail} · {loc}".strip(), color="#cfd8e0",
                 fontsize=10, pad=8)
    fig.text(0.5, 0.015, "wind vs height (km AGL) · rings every 20 kt",
             color="#6f7f8c", fontsize=7, ha="center")
    fig.savefig(out_path, facecolor=fig.get_facecolor())
    plt.close(fig)
    return True
