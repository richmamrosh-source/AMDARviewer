"""
places.py — turn a latitude/longitude into the nearest well-known city name.

Used to label each sounding with a friendly location (e.g. "Berlin", "Fort
Worth") based on the lat/lon of its lowest (near-surface) observation. It's a
small built-in list of major cities and aviation hubs, so it works offline with
no API calls. Matching is "nearest city within max_km".
"""

import math

# (name, latitude, longitude). English/common names. Coordinates are city
# centers (good enough to label the nearby airport a sounding ascends from).
CITIES = [
    # ---- United States ----
    ("New York", 40.71, -74.01), ("Newark", 40.74, -74.17), ("Boston", 42.36, -71.06),
    ("Providence", 41.82, -71.41), ("Hartford", 41.76, -72.69), ("Albany", 42.65, -73.75),
    ("Buffalo", 42.89, -78.88), ("Rochester", 43.16, -77.61), ("Syracuse", 43.05, -76.15),
    ("Philadelphia", 39.95, -75.16), ("Pittsburgh", 40.44, -79.99), ("Baltimore", 39.29, -76.61),
    ("Washington", 38.91, -77.04), ("Richmond", 37.54, -77.44), ("Norfolk", 36.85, -76.29),
    ("Raleigh", 35.78, -78.64), ("Charlotte", 35.23, -80.84), ("Greensboro", 36.07, -79.79),
    ("Columbia", 34.00, -81.03), ("Charleston", 32.78, -79.93), ("Savannah", 32.08, -81.09),
    ("Atlanta", 33.75, -84.39), ("Jacksonville", 30.33, -81.66), ("Orlando", 28.54, -81.38),
    ("Tampa", 27.95, -82.46), ("Miami", 25.76, -80.19), ("Fort Lauderdale", 26.12, -80.14),
    ("Fort Myers", 26.64, -81.87), ("Tallahassee", 30.44, -84.28), ("Pensacola", 30.42, -87.22),
    ("Birmingham, AL", 33.52, -86.81), ("Montgomery", 32.37, -86.30), ("Mobile", 30.69, -88.04),
    ("Jackson, MS", 32.30, -90.18), ("New Orleans", 29.95, -90.07), ("Baton Rouge", 30.45, -91.19),
    ("Memphis", 35.15, -90.05), ("Nashville", 36.16, -86.78), ("Knoxville", 35.96, -83.92),
    ("Chattanooga", 35.05, -85.31), ("Louisville", 38.25, -85.76), ("Lexington", 38.04, -84.50),
    ("Cincinnati", 39.10, -84.51), ("Columbus", 39.96, -82.99), ("Cleveland", 41.50, -81.69),
    ("Dayton", 39.76, -84.19), ("Toledo", 41.66, -83.56), ("Detroit", 42.33, -83.05),
    ("Grand Rapids", 42.96, -85.67), ("Indianapolis", 39.77, -86.16), ("Fort Wayne", 41.08, -85.14),
    ("Chicago", 41.88, -87.63), ("Milwaukee", 43.04, -87.91), ("Madison", 43.07, -89.40),
    ("Green Bay", 44.51, -88.01), ("Appleton", 44.26, -88.42), ("Rockford", 42.27, -89.09),
    ("Minneapolis", 44.98, -93.27), ("Duluth", 46.79, -92.10), ("Des Moines", 41.59, -93.62),
    ("Omaha", 41.26, -95.93), ("Kansas City", 39.10, -94.58), ("St. Louis", 38.63, -90.20),
    ("Springfield, MO", 37.21, -93.29), ("Wichita", 37.69, -97.34), ("Tulsa", 36.15, -95.99),
    ("Oklahoma City", 35.47, -97.52), ("Little Rock", 34.75, -92.29), ("Dallas", 32.78, -96.80),
    ("Fort Worth", 32.76, -97.33), ("Austin", 30.27, -97.74), ("San Antonio", 29.42, -98.49),
    ("Houston", 29.76, -95.37), ("Corpus Christi", 27.80, -97.40), ("El Paso", 31.76, -106.49),
    ("Lubbock", 33.58, -101.86), ("Amarillo", 35.22, -101.83), ("Albuquerque", 35.08, -106.65),
    ("Santa Fe", 35.69, -105.94), ("Denver", 39.74, -104.99), ("Colorado Springs", 38.83, -104.82),
    ("Salt Lake City", 40.76, -111.89), ("Boise", 43.62, -116.21), ("Billings", 45.78, -108.50),
    ("Phoenix", 33.45, -112.07), ("Tucson", 32.22, -110.97), ("Las Vegas", 36.17, -115.14),
    ("Reno", 39.53, -119.81), ("Los Angeles", 34.05, -118.24), ("San Diego", 32.72, -117.16),
    ("Santa Barbara", 34.42, -119.70), ("Bakersfield", 35.37, -119.02), ("Fresno", 36.74, -119.77),
    ("San Jose", 37.34, -121.89), ("San Francisco", 37.77, -122.42), ("Sacramento", 38.58, -121.49),
    ("Portland", 45.52, -122.68), ("Eugene", 44.05, -123.09), ("Seattle", 47.61, -122.33),
    ("Spokane", 47.66, -117.43), ("Anchorage", 61.22, -149.90), ("Fairbanks", 64.84, -147.72),
    ("Honolulu", 21.31, -157.86),
    # ---- Canada ----
    ("Toronto", 43.65, -79.38), ("Ottawa", 45.42, -75.70), ("Montreal", 45.50, -73.57),
    ("Quebec City", 46.81, -71.21), ("Halifax", 44.65, -63.58), ("Winnipeg", 49.90, -97.14),
    ("Calgary", 51.05, -114.07), ("Edmonton", 53.55, -113.49), ("Vancouver", 49.28, -123.12),
    ("Victoria", 48.43, -123.37),
    # ---- Mexico, Central America & Caribbean ----
    ("Mexico City", 19.43, -99.13), ("Guadalajara", 20.67, -103.35), ("Monterrey", 25.69, -100.32),
    ("Tijuana", 32.51, -117.04), ("Cancun", 21.16, -86.85), ("Havana", 23.11, -82.37),
    ("San Juan", 18.47, -66.11), ("Panama City", 8.98, -79.52), ("San Jose, CR", 9.93, -84.08),
    ("Guatemala City", 14.63, -90.51),
    # ---- South America ----
    ("Bogota", 4.71, -74.07), ("Medellin", 6.24, -75.58), ("Lima", -12.05, -77.04),
    ("Quito", -0.18, -78.47), ("Caracas", 10.49, -66.88), ("Sao Paulo", -23.55, -46.63),
    ("Rio de Janeiro", -22.91, -43.17), ("Brasilia", -15.79, -47.88), ("Belo Horizonte", -19.92, -43.94),
    ("Porto Alegre", -30.03, -51.23), ("Buenos Aires", -34.60, -58.38), ("Cordoba", -31.42, -64.18),
    ("Santiago", -33.45, -70.67), ("Montevideo", -34.90, -56.16), ("Asuncion", -25.28, -57.63),
    # ---- United Kingdom & Ireland ----
    ("London", 51.51, -0.13), ("Birmingham", 52.48, -1.90), ("Manchester", 53.48, -2.24),
    ("Liverpool", 53.41, -2.99), ("Leeds", 53.80, -1.55), ("Newcastle", 54.98, -1.61),
    ("Bristol", 51.45, -2.59), ("Edinburgh", 55.95, -3.19), ("Glasgow", 55.86, -4.25),
    ("Aberdeen", 57.15, -2.09), ("Belfast", 54.60, -5.93), ("Dublin", 53.35, -6.26),
    ("Cork", 51.90, -8.47), ("Shannon", 52.70, -8.92),
    # ---- France, Benelux ----
    ("Paris", 48.86, 2.35), ("Lille", 50.63, 3.06), ("Lyon", 45.76, 4.84), ("Marseille", 43.30, 5.37),
    ("Nice", 43.70, 7.27), ("Toulouse", 43.60, 1.44), ("Bordeaux", 44.84, -0.58),
    ("Nantes", 47.22, -1.55), ("Strasbourg", 48.58, 7.75), ("Amsterdam", 52.37, 4.90),
    ("Rotterdam", 51.92, 4.48), ("The Hague", 52.08, 4.30), ("Eindhoven", 51.44, 5.48),
    ("Brussels", 50.85, 4.35), ("Antwerp", 51.22, 4.40), ("Luxembourg", 49.61, 6.13),
    # ---- Germany, Switzerland, Austria ----
    ("Berlin", 52.52, 13.40), ("Hamburg", 53.55, 9.99), ("Bremen", 53.08, 8.80),
    ("Hannover", 52.37, 9.73), ("Cologne", 50.94, 6.96), ("Dusseldorf", 51.23, 6.78),
    ("Dortmund", 51.51, 7.47), ("Essen", 51.46, 7.01), ("Frankfurt", 50.11, 8.68),
    ("Stuttgart", 48.78, 9.18), ("Munich", 48.14, 11.58), ("Nuremberg", 49.45, 11.08),
    ("Leipzig", 51.34, 12.37), ("Dresden", 51.05, 13.74), ("Hahn", 49.95, 7.26),
    ("Zurich", 47.37, 8.54), ("Geneva", 46.20, 6.14), ("Basel", 47.56, 7.59),
    ("Bern", 46.95, 7.45), ("Vienna", 48.21, 16.37), ("Salzburg", 47.81, 13.04),
    ("Graz", 47.07, 15.44),
    # ---- Iberia & Italy ----
    ("Madrid", 40.42, -3.70), ("Barcelona", 41.39, 2.17), ("Valencia", 39.47, -0.38),
    ("Seville", 37.39, -5.99), ("Malaga", 36.72, -4.42), ("Bilbao", 43.26, -2.93),
    ("Palma", 39.57, 2.65), ("Lisbon", 38.72, -9.14), ("Porto", 41.15, -8.61),
    ("Faro", 37.02, -7.93), ("Rome", 41.90, 12.50), ("Milan", 45.46, 9.19),
    ("Turin", 45.07, 7.69), ("Venice", 45.44, 12.32), ("Bologna", 44.49, 11.34),
    ("Florence", 43.77, 11.26), ("Naples", 40.85, 14.27), ("Bari", 41.12, 16.87),
    ("Palermo", 38.12, 13.36), ("Catania", 37.50, 15.09),
    # ---- Nordics & Baltics ----
    ("Copenhagen", 55.68, 12.57), ("Aarhus", 56.16, 10.20), ("Stockholm", 59.33, 18.07),
    ("Gothenburg", 57.71, 11.97), ("Malmo", 55.60, 13.00), ("Oslo", 59.91, 10.75),
    ("Bergen", 60.39, 5.32), ("Helsinki", 60.17, 24.94), ("Reykjavik", 64.15, -21.94),
    ("Riga", 56.95, 24.11), ("Vilnius", 54.69, 25.28), ("Tallinn", 59.44, 24.75),
    # ---- Central & Eastern Europe ----
    ("Prague", 50.08, 14.44), ("Brno", 49.20, 16.61), ("Bratislava", 48.15, 17.11),
    ("Budapest", 47.50, 19.04), ("Warsaw", 52.23, 21.01), ("Lodz", 51.76, 19.46),
    ("Krakow", 50.06, 19.94), ("Wroclaw", 51.11, 17.03), ("Poznan", 52.41, 16.93),
    ("Gdansk", 54.35, 18.65), ("Katowice", 50.26, 19.02), ("Bucharest", 44.43, 26.10),
    ("Sofia", 42.70, 23.32), ("Belgrade", 44.79, 20.45), ("Zagreb", 45.81, 15.98),
    ("Ljubljana", 46.06, 14.51), ("Sarajevo", 43.86, 18.41), ("Skopje", 41.99, 21.43),
    ("Athens", 37.98, 23.73), ("Thessaloniki", 40.64, 22.94),
    # ---- Russia, Ukraine, Belarus, Caucasus ----
    ("Moscow", 55.76, 37.62), ("St. Petersburg", 59.94, 30.31), ("Kazan", 55.79, 49.12),
    ("Yekaterinburg", 56.84, 60.61), ("Novosibirsk", 55.01, 82.93), ("Kyiv", 50.45, 30.52),
    ("Lviv", 49.84, 24.03), ("Kharkiv", 49.99, 36.23), ("Odesa", 46.48, 30.72),
    ("Minsk", 53.90, 27.57), ("Tbilisi", 41.72, 44.79), ("Yerevan", 40.18, 44.51),
    ("Baku", 40.41, 49.87),
    # ---- Middle East & North Africa ----
    ("Istanbul", 41.01, 28.98), ("Ankara", 39.93, 32.86), ("Izmir", 38.42, 27.14),
    ("Antalya", 36.90, 30.70), ("Tel Aviv", 32.08, 34.78), ("Jerusalem", 31.77, 35.21),
    ("Amman", 31.95, 35.93), ("Beirut", 33.89, 35.50), ("Cairo", 30.04, 31.24),
    ("Riyadh", 24.71, 46.68), ("Jeddah", 21.49, 39.19), ("Dubai", 25.20, 55.27),
    ("Abu Dhabi", 24.45, 54.38), ("Doha", 25.29, 51.53), ("Kuwait City", 29.38, 47.99),
    ("Tehran", 35.69, 51.39), ("Baghdad", 33.32, 44.36), ("Casablanca", 33.57, -7.59),
    ("Algiers", 36.75, 3.06), ("Tunis", 36.81, 10.18),
    # ---- Sub-Saharan Africa ----
    ("Lagos", 6.52, 3.38), ("Abuja", 9.06, 7.50), ("Accra", 5.60, -0.19),
    ("Nairobi", -1.29, 36.82), ("Addis Ababa", 9.03, 38.74), ("Dar es Salaam", -6.79, 39.21),
    ("Johannesburg", -26.20, 28.05), ("Cape Town", -33.92, 18.42), ("Durban", -29.86, 31.02),
    # ---- South & Central Asia ----
    ("Delhi", 28.61, 77.21), ("Mumbai", 19.08, 72.88), ("Bangalore", 12.97, 77.59),
    ("Chennai", 13.08, 80.27), ("Kolkata", 22.57, 88.36), ("Hyderabad", 17.39, 78.49),
    ("Ahmedabad", 23.03, 72.58), ("Karachi", 24.86, 67.00), ("Lahore", 31.55, 74.34),
    ("Islamabad", 33.69, 73.06), ("Dhaka", 23.81, 90.41), ("Kathmandu", 27.72, 85.32),
    ("Colombo", 6.93, 79.86),
    # ---- East & Southeast Asia ----
    ("Tokyo", 35.68, 139.69), ("Osaka", 34.69, 135.50), ("Nagoya", 35.18, 136.91),
    ("Sapporo", 43.06, 141.35), ("Fukuoka", 33.59, 130.40), ("Seoul", 37.57, 126.98),
    ("Busan", 35.18, 129.08), ("Beijing", 39.90, 116.41), ("Shanghai", 31.23, 121.47),
    ("Guangzhou", 23.13, 113.26), ("Shenzhen", 22.54, 114.06), ("Chengdu", 30.57, 104.07),
    ("Hong Kong", 22.32, 114.17), ("Taipei", 25.03, 121.57), ("Bangkok", 13.76, 100.50),
    ("Singapore", 1.35, 103.82), ("Kuala Lumpur", 3.14, 101.69), ("Jakarta", -6.21, 106.85),
    ("Manila", 14.60, 120.98), ("Ho Chi Minh City", 10.82, 106.63), ("Hanoi", 21.03, 105.85),
    # ---- Oceania ----
    ("Sydney", -33.87, 151.21), ("Melbourne", -37.81, 144.96), ("Brisbane", -27.47, 153.03),
    ("Perth", -31.95, 115.86), ("Adelaide", -34.93, 138.60), ("Canberra", -35.28, 149.13),
    ("Auckland", -36.85, 174.76), ("Wellington", -41.29, 174.78), ("Christchurch", -43.53, 172.64),
]


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2)
    return 2 * R * math.asin(min(1.0, math.sqrt(a)))


def nearest(lat, lon, max_km=160.0):
    """Nearest city name to (lat, lon), or "" if none is within max_km."""
    if lat is None or lon is None:
        return ""
    try:
        lat = float(lat); lon = float(lon)
    except (TypeError, ValueError):
        return ""
    best, best_d = "", float("inf")
    for name, la, lo in CITIES:
        d = _haversine_km(lat, lon, la, lo)
        if d < best_d:
            best_d, best = d, name
    return best if best_d <= max_km else ""
