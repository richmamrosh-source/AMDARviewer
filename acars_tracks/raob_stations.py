"""
raob_stations.py — radiosonde (upper-air) station directory.

A curated list of North American rawinsonde sites: WMO number, short id, name,
and location. The WMO number is what the data source is queried with; the
lat/lon are for placing the marker on the map. Stations launch balloons at
00Z and 12Z daily.

This list focuses on the U.S. network (the relevant set for comparing against
CONUS aircraft soundings) plus Alaska, Hawaii, and a few nearby sites. If a
station ever stops returning data, its WMO number here is the thing to check.
"""

# (wmo, id, name, lat, lon)
_STATIONS = [
    # --- Northeast / Mid-Atlantic ---
    ("72518", "ALB", "Albany, NY", 42.69, -73.83),
    ("72501", "OKX", "Upton, NY (New York City)", 40.87, -72.86),
    ("72528", "BUF", "Buffalo, NY", 42.93, -78.73),
    ("72520", "PIT", "Pittsburgh, PA", 40.53, -80.23),
    ("72403", "IAD", "Sterling, VA (Washington DC)", 38.98, -77.47),
    ("72402", "WAL", "Wallops Island, VA", 37.94, -75.48),
    ("72318", "RNK", "Blacksburg, VA", 37.21, -80.41),
    ("74389", "GYX", "Gray, ME (Portland)", 43.89, -70.25),
    ("72712", "CAR", "Caribou, ME", 46.87, -68.01),
    ("74494", "CHH", "Chatham, MA", 41.67, -69.97),
    # --- Southeast ---
    ("72317", "GSO", "Greensboro, NC", 36.08, -79.95),
    ("72305", "MHX", "Newport, NC", 34.78, -76.88),
    ("72208", "CHS", "Charleston, SC", 32.90, -80.03),
    ("72215", "FFC", "Peachtree City, GA (Atlanta)", 33.36, -84.57),
    ("72202", "MFL", "Miami, FL", 25.75, -80.38),
    ("72210", "TBW", "Tampa Bay, FL", 27.70, -82.40),
    ("72214", "TLH", "Tallahassee, FL", 30.45, -84.30),
    ("72206", "JAX", "Jacksonville, FL", 30.48, -81.70),
    ("72201", "KEY", "Key West, FL", 24.55, -81.75),
    ("72230", "BMX", "Birmingham, AL", 33.16, -86.77),
    ("72235", "JAN", "Jackson, MS", 32.32, -90.08),
    ("72233", "LIX", "Slidell, LA (New Orleans)", 30.34, -89.83),
    ("72240", "LCH", "Lake Charles, LA", 30.13, -93.22),
    ("72248", "SHV", "Shreveport, LA", 32.45, -93.84),
    ("72327", "BNA", "Nashville, TN", 36.25, -86.57),
    ("72340", "LZK", "Little Rock, AR", 34.84, -92.26),
    # --- Central / Plains ---
    ("72645", "GRB", "Green Bay, WI", 44.50, -88.11),
    ("72632", "DTX", "Detroit/White Lake, MI", 42.70, -83.47),
    ("72634", "APX", "Gaylord, MI", 44.91, -84.72),
    ("74455", "DVN", "Davenport, IA (Quad Cities)", 41.61, -90.58),
    ("74560", "ILX", "Lincoln, IL", 40.15, -89.34),
    ("72649", "MPX", "Chanhassen, MN (Minneapolis)", 44.85, -93.56),
    ("72747", "INL", "International Falls, MN", 48.57, -93.38),
    ("72558", "OAX", "Omaha/Valley, NE", 41.32, -96.37),
    ("72562", "LBF", "North Platte, NE", 41.13, -100.68),
    ("72456", "TOP", "Topeka, KS", 39.07, -95.62),
    ("72451", "DDC", "Dodge City, KS", 37.77, -99.97),
    ("72357", "OUN", "Norman, OK", 35.18, -97.44),
    ("72440", "SGF", "Springfield, MO", 37.23, -93.40),
    ("72659", "ABR", "Aberdeen, SD", 45.45, -98.41),
    ("72662", "RAP", "Rapid City, SD", 44.07, -103.21),
    ("72764", "BIS", "Bismarck, ND", 46.77, -100.75),
    # --- Texas ---
    ("72249", "FWD", "Fort Worth, TX", 32.80, -97.30),
    ("72363", "AMA", "Amarillo, TX", 35.23, -101.70),
    ("72265", "MAF", "Midland, TX", 31.94, -102.19),
    ("72261", "DRT", "Del Rio, TX", 29.37, -100.92),
    ("72251", "CRP", "Corpus Christi, TX", 27.77, -97.50),
    ("72250", "BRO", "Brownsville, TX", 25.92, -97.42),
    # --- Rockies / Southwest ---
    ("72469", "DNR", "Denver, CO", 39.77, -104.87),
    ("72476", "GJT", "Grand Junction, CO", 39.12, -108.53),
    ("72672", "RIW", "Riverton, WY", 43.06, -108.48),
    ("72365", "ABQ", "Albuquerque, NM", 35.04, -106.62),
    ("72274", "TWC", "Tucson, AZ", 32.23, -110.96),
    ("72376", "FGZ", "Flagstaff, AZ", 35.23, -111.82),
    ("72388", "VEF", "Las Vegas, NV", 36.05, -115.18),
    ("72572", "SLC", "Salt Lake City, UT", 40.77, -111.95),
    ("72582", "LKN", "Elko, NV", 40.87, -115.73),
    # --- West Coast / Northwest ---
    ("72293", "NKX", "San Diego, CA", 32.85, -117.12),
    ("72393", "VBG", "Vandenberg, CA", 34.75, -120.57),
    ("72493", "OAK", "Oakland, CA", 37.73, -122.22),
    ("72489", "REV", "Reno, NV", 39.56, -119.80),
    ("72597", "MFR", "Medford, OR", 42.37, -122.87),
    ("72694", "SLE", "Salem, OR", 44.92, -123.01),
    ("72681", "BOI", "Boise, ID", 43.57, -116.22),
    ("72786", "OTX", "Spokane, WA", 47.68, -117.63),
    ("72797", "UIL", "Quillayute, WA", 47.95, -124.55),
    ("72768", "GGW", "Glasgow, MT", 48.21, -106.62),
    ("72776", "TFX", "Great Falls, MT", 47.46, -111.39),
    # --- Alaska ---
    ("70273", "ANC", "Anchorage, AK", 61.16, -150.01),
    ("70261", "FAI", "Fairbanks, AK", 64.82, -147.87),
    ("70026", "BRW", "Utqiagvik (Barrow), AK", 71.29, -156.79),
    ("70200", "OME", "Nome, AK", 64.50, -165.43),
    ("70219", "BET", "Bethel, AK", 60.79, -161.84),
    ("70316", "CDB", "Cold Bay, AK", 55.21, -162.72),
    ("70326", "AKN", "King Salmon, AK", 58.68, -156.65),
    ("70398", "ANN", "Annette Island, AK", 55.04, -131.57),
    # --- Hawaii ---
    ("91165", "LIH", "Lihue, HI", 21.98, -159.34),
    ("91285", "ITO", "Hilo, HI", 19.72, -155.05),
]


def _icao(sid):
    """ICAO id used by the data service. Lower-48 sites are K + 3-letter code;
    Alaska/Hawaii sites have their own prefixes."""
    return _ICAO_OVERRIDE.get(sid, "K" + sid)


# non-CONUS sites whose ICAO id isn't simply "K" + code
_ICAO_OVERRIDE = {
    "ANC": "PANC", "FAI": "PAFA", "BRW": "PABR", "OME": "PAOM", "BET": "PABE",
    "CDB": "PACD", "AKN": "PAKN", "ANN": "PANT", "LIH": "PHLI", "ITO": "PHTO",
}


# --------------------------------------------------------------------------- #
#  Global radiosonde stations (served from NOAA NCEI IGRA, NOT IEM).
#  (wmo, id, name, lat, lon, igra_id)  --  igra_id is the 11-char IGRA station ID
#  (for WMO sites: <FIPS country><"M000"><5-digit WMO>, e.g. De Bilt NLM00006260).
#  A solid starter set spanning every continent; easy to extend. If one ever
#  shows no data, its IGRA id likely needs a tweak (see igra2-station-list.txt).
# --------------------------------------------------------------------------- #
_GLOBAL = [
    # --- Europe ---
    ("06260", "DBLT", "De Bilt, Netherlands", 52.10, 5.18, "NLM00006260"),
    ("03808", "CAMB", "Camborne, UK", 50.22, -5.33, "UKM00003808"),
    ("03882", "HERS", "Herstmonceux, UK", 50.90, 0.32, "UKM00003882"),
    ("03005", "LERW", "Lerwick, UK", 60.13, -1.18, "UKM00003005"),
    ("07145", "TRAP", "Trappes (Paris), France", 48.77, 2.01, "FRM00007145"),
    ("10393", "LIND", "Lindenberg, Germany", 52.21, 14.12, "GMM00010393"),
    ("10410", "ESSN", "Essen, Germany", 51.40, 6.97, "GMM00010410"),
    ("10868", "MUNC", "München, Germany", 48.24, 11.55, "GMM00010868"),
    ("06610", "PAYR", "Payerne, Switzerland", 46.81, 6.94, "SZM00006610"),
    ("11035", "VIEN", "Wien (Vienna), Austria", 48.25, 16.36, "AUM00011035"),
    ("16245", "ROME", "Pratica di Mare (Rome), Italy", 41.65, 12.43, "ITM00016245"),
    ("08221", "MADR", "Madrid, Spain", 40.50, -3.58, "SPM00008221"),
    ("12374", "WARS", "Legionowo (Warsaw), Poland", 52.40, 20.96, "PLM00012374"),
    ("11520", "PRAG", "Praha (Prague), Czechia", 50.01, 14.45, "EZM00011520"),
    ("16716", "ATHN", "Athens, Greece", 37.90, 23.73, "GRM00016716"),
    ("01415", "STAV", "Stavanger, Norway", 58.87, 5.67, "NOM00001415"),
    ("26063", "STPB", "St. Petersburg, Russia", 59.95, 30.70, "RSM00026063"),
    ("27612", "MOSC", "Moscow, Russia", 55.75, 37.57, "RSM00027612"),
    ("33345", "KYIV", "Kyiv, Ukraine", 50.40, 30.57, "UPM00033345"),
    # --- Asia / Middle East ---
    ("47646", "TATE", "Tateno (Tsukuba), Japan", 36.06, 140.13, "JAM00047646"),
    ("47412", "SAPP", "Sapporo, Japan", 43.06, 141.33, "JAM00047412"),
    ("58362", "SHAN", "Shanghai, China", 31.40, 121.46, "CHM00058362"),
    ("54511", "BEIJ", "Beijing, China", 39.93, 116.28, "CHM00054511"),
    ("45004", "HKKP", "Hong Kong (King's Park)", 22.31, 114.17, "HKM00045004"),
    ("48698", "SING", "Singapore", 1.37, 103.98, "SNM00048698"),
    ("42182", "DELH", "New Delhi, India", 28.57, 77.20, "INM00042182"),
    ("43003", "MUMB", "Mumbai, India", 19.12, 72.85, "INM00043003"),
    ("40179", "BETD", "Bet Dagan, Israel", 32.00, 34.81, "ISM00040179"),
    ("17220", "IZMR", "Izmir, Turkey", 38.43, 27.17, "TUM00017220"),
    # --- Australia / Pacific / New Zealand ---
    ("94610", "PERT", "Perth, Australia", -31.92, 115.98, "ASM00094610"),
    ("94866", "MELB", "Melbourne, Australia", -37.69, 144.83, "ASM00094866"),
    ("94767", "SYDN", "Sydney, Australia", -33.94, 151.17, "ASM00094767"),
    ("94120", "DARW", "Darwin, Australia", -12.42, 130.89, "ASM00094120"),
    ("93417", "PARA", "Paraparaumu, New Zealand", -40.90, 174.98, "NZM00093417"),
    ("93844", "INVC", "Invercargill, New Zealand", -46.42, 168.33, "NZM00093844"),
    # --- South America ---
    ("87576", "EZEZ", "Ezeiza (Buenos Aires), Argentina", -34.82, -58.54, "ARM00087576"),
    ("83779", "SAOP", "São Paulo (Marte), Brazil", -23.51, -46.63, "BRM00083779"),
    ("85442", "ANTF", "Antofagasta, Chile", -23.43, -70.44, "CIM00085442"),
    ("80222", "BOGT", "Bogotá, Colombia", 4.70, -74.15, "COM00080222"),
    # --- Africa ---
    ("68816", "CAPT", "Cape Town, South Africa", -33.97, 18.60, "SFM00068816"),
    ("68263", "IRNE", "Irene (Pretoria), South Africa", -25.91, 28.22, "SFM00068263"),
    # --- Arctic / North Atlantic ---
    ("04320", "DNMK", "Danmarkshavn, Greenland", 76.77, -18.67, "GLM00004320"),
    ("04018", "KEFL", "Keflavík, Iceland", 63.97, -22.60, "ICM00004018"),
]


def _us(w, i, n, la, lo):
    return {"wmo": w, "id": i, "icao": _icao(i), "name": n, "lat": la, "lon": lo,
            "src": "iem"}


def _global(w, i, n, la, lo, gid):
    return {"wmo": w, "id": i, "icao": None, "name": n, "lat": la, "lon": lo,
            "src": "igra", "igra_id": gid}


def all_stations():
    """Whole directory: U.S./Canada (IEM, near real-time) + global (IGRA)."""
    out = [_us(w, i, n, la, lo) for (w, i, n, la, lo) in _STATIONS]
    out += [_global(w, i, n, la, lo, gid) for (w, i, n, la, lo, gid) in _GLOBAL]
    return out


def conus_stations():
    """Lower-48 subset (used for the offline demo markers)."""
    out = []
    for (w, i, n, la, lo) in _STATIONS:
        if 24.0 <= la <= 50.0 and -125.0 <= lo <= -66.0:
            out.append(_us(w, i, n, la, lo))
    return out


def by_wmo(wmo):
    wmo = str(wmo)
    for (w, i, n, la, lo) in _STATIONS:
        if w == wmo:
            return _us(w, i, n, la, lo)
    for (w, i, n, la, lo, gid) in _GLOBAL:
        if w == wmo:
            return _global(w, i, n, la, lo, gid)
    return None
