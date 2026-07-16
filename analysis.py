"""
analysis.py — compute the standard Skew-T sounding parameters (CAPE, CIN,
LCL/LFC/EL, lifted index, shear, storm-relative helicity, etc.) from an ACARS
profile, similar to what the old NOAA/GSD ACARS Java page reported.

Pure NumPy, no external meteorology libraries. Inputs come from a sounding dict
whose levels carry p [Pa], T [K], Td [K], z [m], wdir [deg], wspd [m/s].
All moisture-dependent results require a dewpoint; many ACARS aircraft don't
report humidity, in which case those fields come back as None.
"""

import numpy as np

# constants
RD = 287.04
CP = 1004.0
G = 9.80665
EPS = 0.62198
P0 = 1000.0          # hPa reference for potential temperature
KAPPA = RD / CP
LV = 2.501e6


# --------------------------------------------------------------------------- #
#  basic thermodynamics (hPa, deg C unless noted)                              #
# --------------------------------------------------------------------------- #
def _es(Tc):
    """Saturation vapor pressure over water (Bolton 1980), hPa."""
    return 6.112 * np.exp(17.67 * Tc / (Tc + 243.5))


def _mixing_ratio(e_hPa, p_hPa):
    e = np.minimum(e_hPa, p_hPa * 0.999)
    return EPS * e / (p_hPa - e)


def _theta_K(Tc, p_hPa):
    return (Tc + 273.15) * (P0 / p_hPa) ** KAPPA


def _lcl(p_hPa, Tc, Tdc):
    """Lifted condensation level. Returns (p_lcl hPa, T_lcl K)."""
    Tk = Tc + 273.15
    Tdk = Tdc + 273.15
    Tlcl = 56.0 + 1.0 / (1.0 / (Tdk - 56.0) + np.log(Tk / Tdk) / 800.0)
    p_lcl = p_hPa * (Tlcl / Tk) ** (CP / RD)
    return p_lcl, Tlcl


def _moist_dTdp(Tk, p_hPa):
    """Pseudoadiabatic dT/dp (K per hPa) at saturation."""
    Tc = Tk - 273.15
    Lv = 2.501e6 - 2370.0 * Tc          # latent heat varies with temperature
    rs = _mixing_ratio(_es(Tc), p_hPa)
    num = 1.0 + Lv * rs / (RD * Tk)
    den = 1.0 + EPS * Lv * Lv * rs / (CP * RD * Tk * Tk)
    return (RD * Tk) / (CP * p_hPa) * num / den


def _moist_ascent(p_lcl, T_lcl_K, p_top, step=5.0):
    """Integrate a saturated parcel from the LCL up to p_top (RK4)."""
    ps, Ts = [p_lcl], [T_lcl_K]
    p, T = p_lcl, T_lcl_K
    while p > p_top + 1e-6:
        h = -step if (p - step) > p_top else (p_top - p)
        k1 = _moist_dTdp(T, p)
        k2 = _moist_dTdp(T + 0.5 * h * k1, p + 0.5 * h)
        k3 = _moist_dTdp(T + 0.5 * h * k2, p + 0.5 * h)
        k4 = _moist_dTdp(T + h * k3, p + h)
        T = T + (h / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)
        p = p + h
        ps.append(p); Ts.append(T)
    return np.array(ps), np.array(Ts)


def _parcel_T(p_levels, p_src, T_src_c, Td_src_c):
    """Parcel temperature (K) at each pressure level for a parcel lifted from
    (p_src, T_src, Td_src). p_levels descending. Returns (Tparcel_K, p_lcl)."""
    p_lcl, T_lcl = _lcl(p_src, T_src_c, Td_src_c)
    th = _theta_K(T_src_c, p_src)
    out = np.full(len(p_levels), np.nan)
    below = p_levels >= p_lcl
    out[below] = th * (p_levels[below] / P0) ** KAPPA          # dry adiabat
    if (~below).any():
        ptop = float(np.min(p_levels))
        pm, Tm = _moist_ascent(p_lcl, T_lcl, ptop)
        # interpolate moist curve (pm descending) onto the above-LCL levels
        out[~below] = np.interp(p_levels[~below], pm[::-1], Tm[::-1])
    return out, p_lcl


def _interp_p(p_desc, vals, ptarget):
    """Interpolate vals at ptarget using p (descending). NaN if out of range."""
    x = p_desc[::-1]
    y = np.asarray(vals)[::-1]
    if ptarget < x[0] or ptarget > x[-1]:
        return np.nan
    return float(np.interp(ptarget, x, y))


def _cape_cin(p, Tv_env, Tv_par, p_lcl):
    """Integrate CAPE/CIN (J/kg) and find LFC/EL pressures. p descending.

    Returns (cape, cin, lfc, el, el_capped). `el_capped` is True when the parcel
    is still positively buoyant at the top of the data — i.e. the equilibrium
    level is above where the sounding ends, so CAPE is a truncated lower bound.
    """
    lnp = np.log(p)
    buoy = RD * (Tv_par - Tv_env)            # J/kg per unit d(-lnp)
    cape = cin = 0.0
    lfc = el = np.nan
    for i in range(len(p) - 1):
        b0, b1 = buoy[i], buoy[i + 1]
        if not (np.isfinite(b0) and np.isfinite(b1)):
            continue
        dlnp = lnp[i] - lnp[i + 1]           # > 0 going up
        layer = 0.5 * (b0 + b1) * dlnp
        pos = b0 > 0 or b1 > 0
        if pos and layer > 0:
            cape += layer
            if np.isnan(lfc) and p[i] <= p_lcl:
                lfc = p[i + 1] if b0 <= 0 else p[i]
            el = p[i + 1]
        elif layer < 0 and np.isnan(lfc):
            cin += layer
    if np.isnan(lfc):
        cin = 0.0          # parcel never reaches an LFC -> CIN is not meaningful
    # truncation: parcel still buoyant at the topmost finite level
    finite = np.isfinite(buoy)
    el_capped = bool(cape > 0 and finite.any() and buoy[finite][-1] > 0)
    return max(cape, 0.0), min(cin, 0.0), lfc, el, el_capped


# --------------------------------------------------------------------------- #
#  wind helpers (u,v in m/s; meteorological direction)                          #
# --------------------------------------------------------------------------- #
def _uv(wspd, wdir):
    r = np.radians(wdir)
    return -wspd * np.sin(r), -wspd * np.cos(r)


def _interp_z(z, arr, ztarget):
    if ztarget < z[0] or ztarget > z[-1]:
        return np.nan
    return float(np.interp(ztarget, z, arr))


def _kt(ms):
    return ms * 1.943844


# --------------------------------------------------------------------------- #
#  main entry                                                                  #
# --------------------------------------------------------------------------- #
def analyze(sounding):
    """Return a dict of sounding parameters (values None when not computable)."""
    lv = sorted((L for L in sounding.get("levels", []) if L.get("p") and L.get("T")),
                key=lambda L: -L["p"])
    if len(lv) < 4:
        return {"ok": False}

    p = np.array([L["p"] / 100.0 for L in lv])              # hPa, descending
    Tk = np.array([L["T"] for L in lv])
    Tc = Tk - 273.15
    has_td = np.array([L.get("Td") is not None for L in lv])
    Tdc = np.array([(L["Td"] - 273.15) if L.get("Td") is not None else np.nan for L in lv])
    z = np.array([L["z"] if L.get("z") is not None else np.nan for L in lv])
    if np.isnan(z).any():                                    # fill missing heights
        zest = (1.0 - (p / 1013.25) ** (1 / 5.25588)) / 2.25577e-5
        z = np.where(np.isnan(z), zest, z)
    zagl = z - z[0]

    out = {"ok": True}

    # ---- surface ----
    out["sfc_p"] = round(float(p[0]), 1)
    out["sfc_T"] = round(float(Tc[0]), 1)
    moisture = bool(has_td[0])
    if moisture:
        out["sfc_Td"] = round(float(Tdc[0]), 1)
        e = _es(Tdc[0]); esat = _es(Tc[0])
        out["sfc_RH"] = int(round(100.0 * e / esat))
    else:
        out["sfc_Td"] = None
        out["sfc_RH"] = None

    # ---- lapse rates / special levels (no moisture needed) ----
    T700 = _interp_p(p, Tc, 700.0); T500 = _interp_p(p, Tc, 500.0)
    z700 = _interp_p(p, z, 700.0); z500 = _interp_p(p, z, 500.0)
    if np.isfinite(T700) and np.isfinite(T500) and np.isfinite(z500 - z700) and z500 > z700:
        out["lr_700_500"] = round((T700 - T500) / ((z500 - z700) / 1000.0), 1)
    else:
        out["lr_700_500"] = None
    T3 = _interp_z(zagl, Tc, 3000.0)
    if np.isfinite(T3):
        out["lr_0_3"] = round((Tc[0] - T3) / 3.0, 1)
    else:
        out["lr_0_3"] = None

    # freezing level + -20C level (height AGL & pressure)
    out["fz_z"] = out["fz_p"] = out["m20_z"] = None
    for thr, kz, kp in ((0.0, "fz_z", "fz_p"), (-20.0, "m20_z", None)):
        for i in range(len(Tc) - 1):
            if (Tc[i] - thr) * (Tc[i + 1] - thr) <= 0 and Tc[i] != Tc[i + 1]:
                f = (Tc[i] - thr) / (Tc[i] - Tc[i + 1])
                out[kz] = int(round(zagl[i] + f * (zagl[i + 1] - zagl[i])))
                if kp:
                    out[kp] = round(float(p[i] + f * (p[i + 1] - p[i])), 0)
                break

    # ---- moisture-dependent thermodynamics ----
    if moisture:
        # environment virtual temperature
        e_env = np.where(has_td, _es(np.where(has_td, Tdc, 0.0)), 0.0)
        w_env = _mixing_ratio(e_env, p)
        w_env = np.where(has_td, w_env, 0.0)
        Tv_env = Tk * (1.0 + 0.608 * w_env)

        # surface-based parcel
        Tpar, p_lcl = _parcel_T(p, p[0], Tc[0], Tdc[0])
        w_par = np.where(p >= p_lcl, w_env[0],
                         _mixing_ratio(_es(np.clip(Tpar - 273.15, -120, 60)), p))
        Tv_par = Tpar * (1.0 + 0.608 * w_par)
        cape, cin, lfc, el, el_capped = _cape_cin(p, Tv_env, Tv_par, p_lcl)
        out["sb_cape"] = int(round(cape))
        out["sb_cin"] = int(round(cin))
        # CAPE is a truncated lower bound when the parcel is still buoyant at the
        # top of the data (common for shallow ACARS soundings that stop at 700/500 hPa).
        out["cape_truncated"] = bool(el_capped)
        out["cape_top_p"] = round(float(p[-1]), 0)
        out["parcel_p"] = [round(float(x), 1) for x in p]          # for plotting
        out["parcel_T"] = [round(float(x), 2) for x in (Tpar - 273.15)]
        out["lcl_p"] = round(float(p_lcl), 0)
        out["lcl_z"] = int(round(_interp_p(p, zagl, p_lcl))) if np.isfinite(_interp_p(p, zagl, p_lcl)) else None
        out["lfc_p"] = round(float(lfc), 0) if np.isfinite(lfc) else None
        out["el_p"] = round(float(el), 0) if np.isfinite(el) else None
        out["el_z"] = int(round(_interp_p(p, zagl, el))) if np.isfinite(el) and np.isfinite(_interp_p(p, zagl, el)) else None

        # lifted index: env 500 minus parcel 500
        Tpar500 = _interp_p(p, Tpar - 273.15, 500.0)
        if np.isfinite(T500) and np.isfinite(Tpar500):
            out["li"] = round(T500 - Tpar500, 1)
        else:
            out["li"] = None

        # most-unstable parcel in lowest 300 hPa (by max CAPE)
        mu = cape; mu_src = p[0]
        for i in range(len(p)):
            if p[i] < p[0] - 300.0:
                break
            if not has_td[i]:
                continue
            Tp_i, plcl_i = _parcel_T(p, p[i], Tc[i], Tdc[i])
            wpi = np.where(p >= plcl_i, w_env[i],
                           _mixing_ratio(_es(np.clip(Tp_i - 273.15, -120, 60)), p))
            Tvp_i = Tp_i * (1.0 + 0.608 * wpi)
            c_i, _, _, _, _ = _cape_cin(p, Tv_env, Tvp_i, plcl_i)
            if c_i > mu:
                mu, mu_src = c_i, p[i]
        out["mu_cape"] = int(round(mu))

        # precipitable water (mm)
        wcol = np.where(has_td, w_env, 0.0)
        dp = (p[:-1] - p[1:]) * 100.0                       # Pa, positive
        wmid = 0.5 * (wcol[:-1] + wcol[1:])
        out["pw"] = round(float(np.sum(wmid * dp) / G), 1)

        # K index and Total Totals
        Td850 = _interp_p(p, Tdc, 850.0); T850 = _interp_p(p, Tc, 850.0)
        Td700 = _interp_p(p, Tdc, 700.0)
        if all(np.isfinite(x) for x in (T850, T500, Td850, T700, Td700)):
            out["k_index"] = int(round((T850 - T500) + Td850 - (T700 - Td700)))
        else:
            out["k_index"] = None
        if all(np.isfinite(x) for x in (T850, T500, Td850)):
            out["total_totals"] = int(round((T850 - T500) + (Td850 - T500)))
        else:
            out["total_totals"] = None
    else:
        for k in ("sb_cape", "sb_cin", "mu_cape", "li", "lcl_p", "lcl_z",
                  "lfc_p", "el_p", "el_z", "pw", "k_index", "total_totals",
                  "parcel_p", "parcel_T", "cape_top_p"):
            out[k] = None
        out["cape_truncated"] = False

    # ---- kinematics ----
    has_wind = all(L.get("wspd") is not None and L.get("wdir") is not None for L in lv)
    out["has_wind"] = has_wind
    if has_wind:
        ws = np.array([L["wspd"] for L in lv]); wd = np.array([L["wdir"] for L in lv])
        u, v = _uv(ws, wd)

        def shear_kt(z0, z1):
            u0, u1 = _interp_z(zagl, u, z0), _interp_z(zagl, u, z1)
            v0, v1 = _interp_z(zagl, v, z0), _interp_z(zagl, v, z1)
            if not all(np.isfinite(x) for x in (u0, u1, v0, v1)):
                return None
            return round(_kt(np.hypot(u1 - u0, v1 - v0)), 0)

        out["shear_0_1"] = shear_kt(0.0, 1000.0)
        out["shear_0_6"] = shear_kt(0.0, 6000.0)

        # 0-6 km mean wind (mass-weighted ~ simple over fine z grid)
        zt = np.linspace(0, 6000, 25)
        um = np.nanmean([_interp_z(zagl, u, zz) for zz in zt])
        vm = np.nanmean([_interp_z(zagl, v, zz) for zz in zt])
        if np.isfinite(um) and np.isfinite(vm):
            out["mw_0_6_dir"] = int(round((np.degrees(np.arctan2(-um, -vm))) % 360))
            out["mw_0_6_kt"] = int(round(_kt(np.hypot(um, vm))))
        else:
            out["mw_0_6_dir"] = out["mw_0_6_kt"] = None

        # Bunkers right-mover storm motion
        u05, v05 = _interp_z(zagl, u, 500.0), _interp_z(zagl, v, 500.0)
        u6, v6 = _interp_z(zagl, u, 6000.0), _interp_z(zagl, v, 6000.0)
        cu = cv = None
        if all(np.isfinite(x) for x in (um, vm, u05, v05, u6, v6)):
            shru, shrv = u6 - u05, v6 - v05
            smag = np.hypot(shru, shrv)
            if smag > 0:
                cu = um + 7.5 * (shrv / smag)               # 7.5 m/s to the right
                cv = vm - 7.5 * (shru / smag)

        def srh(top):
            if cu is None:
                return None
            zl = np.linspace(0, top, 40)
            uu = np.array([_interp_z(zagl, u, zz) for zz in zl])
            vv = np.array([_interp_z(zagl, v, zz) for zz in zl])
            if np.isnan(uu).any() or np.isnan(vv).any():
                return None
            s = 0.0
            for i in range(len(zl) - 1):
                s += ((uu[i + 1] - cu) * (vv[i] - cv) -
                      (uu[i] - cu) * (vv[i + 1] - cv))
            return int(round(s))

        out["srh_0_1"] = srh(1000.0)
        out["srh_0_3"] = srh(3000.0)

        # storm-motion + mean-wind vectors (knots, u/v) for the hodograph
        if cu is not None:
            out["storm_u_kt"] = round(_kt(cu), 1)
            out["storm_v_kt"] = round(_kt(cv), 1)
            out["storm_dir"] = int(round(np.degrees(np.arctan2(-cu, -cv)) % 360))
            out["storm_kt"] = int(round(_kt(np.hypot(cu, cv))))
        else:
            out["storm_u_kt"] = out["storm_v_kt"] = out["storm_dir"] = out["storm_kt"] = None
        if np.isfinite(um) and np.isfinite(vm):
            out["mw_u_kt"] = round(_kt(um), 1)
            out["mw_v_kt"] = round(_kt(vm), 1)
        else:
            out["mw_u_kt"] = out["mw_v_kt"] = None
    else:
        for k in ("shear_0_1", "shear_0_6", "mw_0_6_dir", "mw_0_6_kt",
                  "srh_0_1", "srh_0_3", "storm_u_kt", "storm_v_kt",
                  "storm_dir", "storm_kt", "mw_u_kt", "mw_v_kt"):
            out[k] = None

    return out
