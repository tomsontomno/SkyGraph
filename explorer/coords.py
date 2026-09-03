"""City coordinates (WGS84) for every city that appears in the Wizz scans in data/current/.

Covers the current scans in data/current/ and all 187 cities of the 330 usable archive scans in
data/archives/flight_graph/.

Keys are the city names exactly as the scanner writes them, so both spellings of a place are listed
where the scans disagree ('Warsaw' / 'Warsaw Chopin', 'Burgas' / 'Bourgas', ...).  Values are
the coordinates of the airport the scan means; for names without an airport qualifier the city
centre is used.  Accuracy is map accuracy (about one kilometre), which is all the explorer needs.

``missing(cities)`` reports names without an entry - ``explorer build`` aborts on a non-empty list.
"""
from __future__ import annotations

import math
from typing import Dict, Iterable, List, Tuple

CITY_COORDS: Dict[str, Tuple[float, float]] = {
    'Aberdeen': (57.202, -2.198),
    'Abu Dhabi': (24.433, 54.651),
    'Agadir': (30.381, -9.546),
    'Alesund': (62.560, 6.110),
    'Alexandria': (30.918, 29.696),
    'Alghero': (40.632, 8.291),
    'Alicante': (38.282, -0.558),
    'Almaty': (43.352, 77.041),
    'Amman': (31.723, 35.993),
    'Ancona': (43.616, 13.362),
    'Antalya': (36.899, 30.801),
    'Aqaba': (29.612, 35.018),
    'Astana': (51.022, 71.467),
    'Athens': (37.936, 23.947),
    'Bacau': (46.522, 26.910),
    'Baku': (40.468, 50.047),
    'Banja Luka': (44.941, 17.298),
    'Barcelona': (41.297, 2.078),
    'Bari': (41.139, 16.760),
    'Basel (BSL)': (47.590, 7.529),
    'Basel (MLH)': (47.590, 7.529),
    'Belgrade': (44.819, 20.309),
    'Bergen': (60.293, 5.218),
    'Berlin': (52.362, 13.501),
    'Bilbao': (43.301, -2.911),
    'Billund': (55.740, 9.152),
    'Birmingham': (52.454, -1.748),
    'Bishkek': (43.061, 74.478),
    'Bologna': (44.535, 11.289),
    'Bourgas': (42.570, 27.515),
    'Brasov': (45.690, 25.525),
    'Bremen': (53.047, 8.787),
    'Bratislava': (48.170, 17.213),
    'Brindisi': (40.658, 17.947),
    'Brussels': (50.901, 4.484),
    'Brussels Charleroi': (50.459, 4.454),
    'Bucharest': (44.571, 26.085),
    'Budapest': (47.437, 19.256),
    'Burgas': (42.570, 27.515),
    'Cairo': (30.112, 31.400),
    'Castellon': (40.214, 0.073),
    'Catania': (37.467, 15.066),
    'Chisinau': (46.928, 28.931),
    'Cluj-Napoca': (46.785, 23.686),
    'Cologne': (50.866, 7.143),
    'Comiso': (36.995, 14.607),
    'Constanta': (44.362, 28.488),
    'Copenhagen': (55.618, 12.656),
    'Craiova': (44.318, 23.889),
    'Dalaman': (36.713, 28.792),
    'Dammam': (26.471, 49.798),
    'Debrecen': (47.489, 21.615),
    'Dortmund': (51.518, 7.612),
    'Dubai': (25.253, 55.365),
    'Eindhoven': (51.450, 5.375),
    'Erbil': (36.238, 43.963),
    'Faro': (37.014, -7.966),
    'Frankfurt': (50.033, 8.571),
    'Friedrichshafen': (47.671, 9.512),
    'Fuerteventura': (28.453, -13.864),
    'Funchal': (32.694, -16.778),
    'Funchal (Madeira)': (32.694, -16.778),
    'Gdansk': (54.378, 18.466),
    'Genoa': (44.413, 8.837),
    'Geneva': (46.238, 6.109),
    'Glasgow': (55.872, -4.433),
    'Gothenburg': (57.663, 12.293),
    'Gran Canaria': (27.932, -15.387),
    'Grenoble': (45.363, 5.329),
    'Hamburg': (53.630, 9.988),
    'Haugesund': (59.345, 5.208),
    'Heraklion (Crete)': (35.340, 25.180),
    'Hurghada': (27.178, 33.799),
    'Iasi': (47.179, 27.621),
    'Istanbul': (40.976, 28.815),
    'Jeddah': (21.680, 39.157),
    'Karlsruhe/Baden-Baden': (48.779, 8.080),
    'Katowice': (50.474, 19.080),
    'Kaunas': (54.964, 24.085),
    'Kosice': (48.663, 21.241),
    'Krakow': (50.078, 19.785),
    'Kutaisi': (42.177, 42.483),
    'Larnaca': (34.875, 33.625),
    'Leeds': (53.866, -1.661),
    'Leipzig': (51.424, 12.236),
    'Lisbon': (38.774, -9.134),
    'Liverpool': (53.336, -2.850),
    'Ljubljana': (46.224, 14.458),
    'London Gatwick': (51.148, -0.190),
    'London Luton': (51.875, -0.368),
    'Lublin': (51.240, 22.714),
    'Lyon': (45.726, 5.081),
    'Madinah': (24.554, 39.705),
    'Madrid': (40.472, -3.561),
    'Malaga': (36.675, -4.499),
    'Male': (4.192, 73.529),
    'Mallorca': (39.552, 2.739),
    'Malmo': (55.537, 13.376),
    'Malta': (35.858, 14.478),
    'Marrakech': (31.607, -8.036),
    'Marrakesh': (31.607, -8.036),
    'Marsa Alam': (25.557, 34.584),
    'Medina': (24.554, 39.705),
    'Memmingen': (47.989, 10.240),
    'Milan Bergamo': (45.674, 9.704),
    'Milan Malpensa': (45.630, 8.723),
    'Naples': (40.884, 14.291),
    'Nice': (43.658, 7.216),
    'Nis': (43.337, 21.854),
    'Nuremberg': (49.499, 11.078),
    'Ohrid': (41.180, 20.742),
    'Oslo': (60.194, 11.100),
    'Oslo Gardermoen': (60.194, 11.100),
    'Oslo Sandefjord': (59.187, 10.259),
    'Oslo Sandefjord Torp': (59.187, 10.259),
    'Paris Beauvais': (49.454, 2.113),
    'Paris Orly': (48.726, 2.365),
    'Perugia': (43.096, 12.513),
    'Pescara': (42.432, 14.181),
    'Pisa': (43.684, 10.393),
    'Plovdiv': (42.068, 24.851),
    'Podgorica': (42.359, 19.252),
    'Poprad-Tatry': (49.074, 20.241),
    'Porto': (41.248, -8.681),
    'Poznan': (52.421, 16.826),
    'Prague': (50.101, 14.263),
    'Prishtina': (42.573, 21.036),
    'Pristina': (42.573, 21.036),
    'Radom': (51.389, 21.213),
    'Reykjavik': (63.985, -22.605),
    'Rhodes': (36.405, 28.086),
    'Riga': (56.924, 23.971),
    'Rimini': (44.020, 12.612),
    'Riyadh': (24.958, 46.699),
    'Rome Ciampino': (41.799, 12.595),
    'Rome Fiumicino': (41.800, 12.246),
    'Rzeszow': (50.110, 22.019),
    'Salerno': (40.620, 14.911),
    'Salzburg': (47.794, 12.998),
    'Samarkand': (39.700, 66.984),
    'Santander': (43.427, -3.820),
    'Sarajevo': (43.825, 18.331),
    'Satu Mare': (47.703, 22.886),
    'Sevilla': (37.418, -5.899),
    'Seville': (37.418, -5.899),
    'Sharm El Sheikh': (27.977, 34.395),
    'Sibiu': (45.786, 24.091),
    'Skopje': (41.962, 21.628),
    'Sofia': (42.695, 23.406),
    'Sohag': (26.343, 31.743),
    'Split': (43.539, 16.298),
    'Stavanger': (58.877, 5.638),
    'Stockholm Arlanda': (59.652, 17.919),
    'Stockholm Skavsta': (58.788, 16.912),
    'Stuttgart': (48.690, 9.222),
    'Suceava': (47.688, 26.354),
    'Szczecin': (53.585, 14.902),
    'Tallinn': (59.413, 24.833),
    'Tashkent': (41.258, 69.281),
    'Tel Aviv': (32.011, 34.887),
    'Tel-Aviv': (32.011, 34.887),
    'Tenerife': (28.044, -16.572),
    'Thessaloniki': (40.520, 22.971),
    'Timisoara': (45.810, 21.338),
    'Tirana': (41.415, 19.720),
    'Tirgu Mures': (46.468, 24.413),
    'Tirgu-Mures': (46.468, 24.413),
    'Trieste': (45.827, 13.472),
    'Tromso': (69.683, 18.919),
    'Trondheim': (63.458, 10.924),
    'Turin': (45.201, 7.650),
    'Turkistan': (43.313, 68.548),
    'Turku': (60.514, 22.263),
    'Tuzla': (44.459, 18.725),
    'Valencia': (39.489, -0.482),
    'Varna': (43.232, 27.825),
    'Venice Marco Polo': (45.505, 12.352),
    'Venice Treviso': (45.648, 12.194),
    'Verona': (45.396, 10.888),
    'Vienna': (48.110, 16.570),
    'Vilnius': (54.637, 25.286),
    'Warsaw': (52.166, 20.967),
    'Warsaw Chopin': (52.166, 20.967),
    'Wroclaw': (51.103, 16.886),
    'Yerevan': (40.147, 44.396),
    'Zakynthos': (37.751, 20.884),
    'Zaragoza': (41.660, -1.042),
}


EARTH_DIAMETER_KM = 12742.0


def haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Great-circle distance in km between two ``(lat, lon)`` pairs.

    Precondition: both are valid degrees.  Postcondition: >= 0, symmetric, 0 for equal points.
    """
    rad = math.pi / 180.0
    lat1, lon1 = a
    lat2, lon2 = b
    h = (0.5 - math.cos((lat2 - lat1) * rad) / 2
         + math.cos(lat1 * rad) * math.cos(lat2 * rad) * (1 - math.cos((lon2 - lon1) * rad)) / 2)
    return EARTH_DIAMETER_KM * math.asin(math.sqrt(max(0.0, min(1.0, h))))


def distance_km(city_a: str, city_b: str) -> float:
    """Great-circle distance between two known cities.  Raises KeyError naming an unknown one."""
    return haversine_km(coords_of(city_a), coords_of(city_b))


def cities_within(center: str, radius_km: float, candidates: Iterable[str]) -> List[str]:
    """Cities of ``candidates`` no farther than ``radius_km`` from ``center``, nearest first.

    Preconditions: ``center`` has coordinates; ``radius_km >= 0``; candidates without coordinates are
    skipped rather than guessed.  Postcondition: ``center`` itself is always first when it is among
    the candidates, and the result is empty only if the centre is not a candidate.
    """
    if radius_km < 0:
        raise ValueError(f"radius must be >= 0, got {radius_km}")
    origin = coords_of(center)
    hits = []
    for city in candidates:
        point = CITY_COORDS.get(city)
        if point is None:
            continue
        distance = haversine_km(origin, point)
        if distance <= radius_km:
            hits.append((distance, city))
    return [city for _, city in sorted(hits)]


def missing(cities: Iterable[str]) -> List[str]:
    """City names without coordinates, sorted.  Empty list means the map can place everything."""
    return sorted({city for city in cities if city not in CITY_COORDS})


def coords_of(city: str) -> Tuple[float, float]:
    """(lat, lon) of ``city``.  Raises KeyError with the name when it is unknown."""
    try:
        return CITY_COORDS[city]
    except KeyError:
        raise KeyError(f"no coordinates for city {city!r}; add it to explorer/coords.py") from None
