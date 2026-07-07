EUROPE_COUNTRIES = {
    "albania", "andorra", "armenia", "austria", "azerbaijan", "belarus", "belgium", "bosnia and herzegovina",
    "bulgaria", "croatia", "cyprus", "czech republic", "czechia", "denmark", "estonia", "finland", "france",
    "georgia", "germany", "greece", "hungary", "iceland", "ireland", "italy", "kosovo", "latvia", "liechtenstein",
    "lithuania", "luxembourg", "malta", "moldova", "monaco", "montenegro", "netherlands", "north macedonia",
    "norway", "poland", "portugal", "romania", "san marino", "serbia", "slovakia", "slovenia", "spain",
    "sweden", "switzerland", "turkey", "türkiye", "ukraine", "united kingdom", "uk", "vatican city", "holy see",
    "europe", "eu member states", "european union"
}

EUROPE_CITIES = {
    "rome", "milan", "turin", "paris", "lyon", "marseille", "brussels", "luxembourg", "vienna", "geneva",
    "zurich", "bern", "berlin", "bonn", "frankfurt", "munich", "hamburg", "copenhagen", "stockholm",
    "helsinki", "oslo", "amsterdam", "the hague", "rotterdam", "madrid", "barcelona", "lisbon", "dublin",
    "london", "warsaw", "prague", "budapest", "bucharest", "sofia", "zagreb", "ljubljana", "bratislava",
    "athens", "valletta", "nicosia", "riga", "vilnius", "tallinn", "strasbourg", "lille", "budva",
    "tirana", "sarajevo", "belgrade", "podgorica", "skopje", "ankara", "istanbul", "kyiv", "chisinau"
}


def is_europe_location(location: str, country: str = "") -> bool:
    text = f"{location} {country}".lower()
    return any(x in text for x in EUROPE_COUNTRIES | EUROPE_CITIES)
