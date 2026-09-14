import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time
import hashlib
from urllib.parse import urljoin, urlparse


# ============================================================
# INSTELLINGEN
# ============================================================

IMMO_DRIE_URL = "https://www.immodrie.be/nl/te-koop"

DOMESTIC_URL = "https://www.domestic.be/nl/te-koop/arendonk-2370"

HEYLEN_URL = "https://www.heylenvastgoed.be/kopen/arendonk"

HILLEWAERE_URL = (
    "https://www.hillewaere-vastgoed.be/vastgoed/alle/te-koop"
    "?search-label=Arendonk+%282370%29&view=list"
)

DEWAELE_URLS = [
    "https://www.dewaele.com/nl/te-koop/2370-arendonk",
    "https://www.dewaele.com/nl/te-koop/2370-arendonk/huis",
    "https://www.dewaele.com/nl/te-koop/2370-arendonk/appartement",
    "https://www.dewaele.com/nl/te-koop/2370-arendonk/grond",
    "https://www.dewaele.com/nl/te-koop/2370-arendonk/garage",
    "https://www.dewaele.com/nl/te-koop/2370-arendonk/bedrijfsvastgoed",
    "https://www.dewaele.com/nl/te-koop/2370-arendonk/kantoor",
    "https://www.dewaele.com/nl/te-koop/2370-arendonk/industrie",
]

CENTURY21_URLS = [
    "https://www.century21.be/nl/te-koop/huis/arendonk",
    "https://www.century21.be/nl/te-koop/appartement/arendonk",
    "https://www.century21.be/nl/te-koop/bouwgrond/arendonk",
    "https://www.century21.be/nl/te-koop/handelspand/arendonk",
    "https://www.century21.be/nl/te-koop/garage/arendonk",
    "https://www.century21.be/nl/te-koop/kantoor/arendonk",
    "https://www.century21.be/nl/te-koop/magazijn/arendonk",
]

SEEN_FILE = "seen_properties.json"

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN"
)

TELEGRAM_CHAT_ID = os.environ.get(
    "TELEGRAM_CHAT_ID"
)

REQUEST_TIMEOUT = 25

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    ),
    "Accept-Language": "nl-BE,nl;q=0.9,en;q=0.8",
}


# ============================================================
# HULPFUNCTIES
# ============================================================

def clean_text(text):
    return " ".join(text.split())


def absolute_url(base_url, href):
    return urljoin(base_url, href)


def make_hash_id(source, url):

    value = (
        f"{source}|{url}"
        .encode("utf-8")
    )

    return (
        f"{source.lower().replace(' ', '-')}-"
        f"{hashlib.sha1(value).hexdigest()[:12]}"
    )


def extract_price(text):

    if not text:
        return None

    match = re.search(
        r"€\s*[\d\.\s]+(?:,\d{1,2})?",
        text
    )

    if match:
        return clean_text(
            match.group(0)
        )

    return None


def extract_bedrooms(text):

    if not text:
        return None

    patterns = [
        r"(\d+)\s*slaapkamers?",
        r"(\d+)\s*slpk(?:\.| )?",
        r"(\d+)\s*chambres?",
        r"(\d+)\s*bedrooms?",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:
            return int(
                match.group(1)
            )

    return None


def extract_area_by_label(
    text,
    labels
):

    if not text:
        return None

    for label in labels:

        pattern = (
            rf"{re.escape(label)}"
            rf"\s*[:\-]?\s*"
            rf"(\d+(?:[.,]\d+)?)"
            rf"\s*m²"
        )

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            return (
                match.group(1)
                .replace(",", ".")
            )

    return None


def is_arendonk(
    text,
    url=""
):

    combined = (
        f"{text} {url}"
        .lower()
    )

    return (
        "arendonk" in combined
        or "2370" in combined
    )


def is_for_sale(text):

    lowered = text.lower()

    if "verkocht" in lowered:
        return False

    if "sold" in lowered:
        return False

    if "verhuurd" in lowered:
        return False

    if "onder optie" in lowered:
        return False

    if "in optie" in lowered:
        return False

    return True


def extract_property_type(
    text,
    url=""
):

    combined = (
        f"{text} {url}"
        .lower()
    )

    types = [
        "opbrengsteigendom",
        "investeringsvastgoed",
        "bedrijfsvastgoed",
        "handelspand",
        "handelszaak",
        "commercieel",
        "eengezinswoning",
        "halfopen bebouwing",
        "open bebouwing",
        "bouwgrond",
        "projectgrond",
        "landbouwgrond",
        "appartement",
        "penthouse",
        "duplex",
        "triplex",
        "studio",
        "woning",
        "huis",
        "villa",
        "grond",
        "garage",
        "parking",
        "kantoor",
        "magazijn",
        "industrie",
        "chalet",
    ]

    for property_type in types:

        if property_type in combined:

            return property_type.title()

    return "Vastgoed"


def extract_generic_property_data(
    source,
    property_id,
    text,
    url
):

    living_area = extract_area_by_label(
        text,
        [
            "Bewoonbare oppervlakte",
            "Bewoonbare opp",
            "Woonoppervlakte",
            "Woonopp.",
            "Leefruimte",
            "Bewoonbare oppervlakte:"
        ]
    )

    ground_area = extract_area_by_label(
        text,
        [
            "Oppervlakte grond",
            "Grondoppervlakte",
            "Perceeloppervlakte",
            "Perceel opp",
        ]
    )

    return {

        "id": property_id,

        "source": source,

        "type": extract_property_type(
            text,
            url
        ),

        "city": "Arendonk",

        "price": extract_price(
            text
        ),

        "bedrooms": extract_bedrooms(
            text
        ),

        "living_area": living_area,

        "ground_area": ground_area,

        "status": "Te koop",

        "url": url,
    }


# ============================================================
# WEBSITE OPHALEN
# ============================================================

def get_page(
    url,
    timeout=REQUEST_TIMEOUT,
    attempts=2
):

    for attempt in range(
        1,
        attempts + 1
    ):

        try:

            response = requests.get(
                url,
                headers=HEADERS,
                timeout=timeout
            )

            response.raise_for_status()

            return response.text

        except requests.RequestException as error:

            print(
                f"  Poging {attempt}/{attempts} "
                f"mislukt: {error}"
            )

            if attempt < attempts:

                time.sleep(3)

    return None


# ============================================================
# IMMO DRIE
# ============================================================

def extract_immo_drie_type(text):

    property_text = text

    for word in [
        "Nieuw",
        "Te koop",
        "In optie",
        "Verkocht",
        "Video",
        "Virtueel"
    ]:

        property_text = re.sub(
            rf"\b{re.escape(word)}\b",
            "",
            property_text,
            flags=re.IGNORECASE
        )

    property_text = re.split(
        r"\b2370\b",
        property_text,
        maxsplit=1
    )[0]

    property_text = clean_text(
        property_text
    )

    if property_text:
        return property_text

    return "Vastgoed"


def find_immo_drie_properties(html):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    properties = []

    for link in soup.find_all(
        "a",
        href=True
    ):

        href = link.get(
            "href",
            ""
        ).strip()

        if not href:
            continue

        url = absolute_url(
            "https://www.immodrie.be",
            href
        )

        if "-te-koop-in-" not in url:
            continue

        text = clean_text(
            link.get_text(
                " ",
                strip=True
            )
        )

        if not text:
            continue

        id_matches = re.findall(
            r"(\d{6,})",
            url
        )

        if not id_matches:
            continue

        property_id = id_matches[-1]

        if not is_arendonk(
            text,
            url
        ):
            continue

        if re.search(
            r"\bIn optie\b",
            text,
            re.IGNORECASE
        ):
            continue

        if re.search(
            r"\bVerkocht\b",
            text,
            re.IGNORECASE
        ):
            continue

        property_data = {

            "id": property_id,

            "source": "Immo Drie",

            "type": extract_immo_drie_type(
                text
            ),

            "city": "Arendonk",

            "price": extract_price(
                text
            ),

            "bedrooms": extract_bedrooms(
                text
            ),

            "living_area": extract_area_by_label(
                text,
                [
                    "Leefruimte"
                ]
            ),

            "ground_area": extract_area_by_label(
                text,
                [
                    "Titles.surface_ground"
                ]
            ),

            "status": "Te koop",

            "url": url,
        }

        properties.append(
            property_data
        )

    unique = {}

    for property_data in properties:

        unique[
            property_data["id"]
        ] = property_data

    return list(
        unique.values()
    )


def scan_immo_drie():

    print(
        "Immo Drie controleren..."
    )

    all_properties = []

    for page in range(
        1,
        21
    ):

        if page == 1:

            url = IMMO_DRIE_URL

        else:

            url = (
                f"{IMMO_DRIE_URL}"
                f"/pagina-{page}"
            )

        print(
            f"Pagina {page} controleren..."
        )

        html = get_page(
            url
        )

        if not html:

            break

        properties = (
            find_immo_drie_properties(
                html
            )
        )

        print(
            f"  {len(properties)} "
            "vastgoedadvertenties gevonden."
        )

        if not properties:

            break

        all_properties.extend(
            properties
        )

    unique = {}

    for property_data in all_properties:

        unique[
            property_data["id"]
        ] = property_data

    result = list(
        unique.values()
    )

    print(
        f"TOTAAL Immo Drie: "
        f"{len(result)} unieke advertenties."
    )

    return result


# ============================================================
# DOMESTIC
# ============================================================

def find_domestic_properties(html):

    if not html:
        return []

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    properties = []

    category_paths = [
        "/woningen/",
        "/appartement/",
        "/gronden/",
        "/garages/",
        "/commercieel/",
        "/bedrijfsvastgoed/",
    ]

    for link in soup.find_all(
        "a",
        href=True
    ):

        href = link.get(
            "href",
            ""
        ).strip()

        if not href:
            continue

        url = absolute_url(
            "https://www.domestic.be",
            href
        )

        if "/nl/" not in url:
            continue

        if "te-koop" not in url.lower():
            continue

        if any(
            path in url.lower()
            for path in category_paths
        ):
            continue

        if url.rstrip(
            "/"
        ).lower().endswith(
            "arendonk-2370"
        ):
            continue

        id_matches = re.findall(
            r"(\d{5,})",
            url
        )

        if not id_matches:
            continue

        text = clean_text(
            link.get_text(
                " ",
                strip=True
            )
        )

        if not text:
            continue

        if not is_arendonk(
            text,
            url
        ):
            continue

        property_id = (
            "domestic-"
            + id_matches[-1]
        )

        property_data = (
            extract_generic_property_data(
                "Domestic",
                property_id,
                text,
                url
            )
        )

        properties.append(
            property_data
        )

    unique = {}

    for property_data in properties:

        unique[
            property_data["id"]
        ] = property_data

    return list(
        unique.values()
    )


def scan_domestic():

    print(
        "Domestic controleren..."
    )

    html = get_page(
        DOMESTIC_URL,
        timeout=60,
        attempts=3
    )

    if not html:

        print(
            "  Domestic is momenteel "
            "niet bereikbaar."
        )

        return []

    properties = (
        find_domestic_properties(
            html
        )
    )

    print(
        f"  {len(properties)} "
        "vastgoedadvertenties gevonden."
    )

    return properties


# ============================================================
# HEYLEN VASTGOED
# ============================================================

def find_heylen_properties(html):

    if not html:
        return []

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    properties = []

    for link in soup.find_all(
        "a",
        href=True
    ):

        href = link.get(
            "href",
            ""
        ).strip()

        if not href:
            continue

        url = absolute_url(
            "https://www.heylenvastgoed.be",
            href
        )

        if "/kopen/" not in url.lower():
            continue

        if url.rstrip(
            "/"
        ).lower().endswith(
            "/kopen/arendonk"
        ):
            continue

        text = clean_text(
            link.get_text(
                " ",
                strip=True
            )
        )

        if not text:
            continue

        if not is_arendonk(
            text,
            url
        ):
            continue

        if not is_for_sale(text):
            continue

        if "€" not in text:
            continue

        property_id = make_hash_id(
            "heylen",
            url
        )

        properties.append(
            extract_generic_property_data(
                "Heylen Vastgoed",
                property_id,
                text,
                url
            )
        )

    unique = {}

    for property_data in properties:

        unique[
            property_data["id"]
        ] = property_data

    return list(
        unique.values()
    )


def scan_heylen():

    print(
        "Heylen Vastgoed controleren..."
    )

    html = get_page(
        HEYLEN_URL
    )

    if not html:

        print(
            "  Heylen overgeslagen."
        )

        return []

    properties = (
        find_heylen_properties(
            html
        )
    )

    print(
        f"  {len(properties)} "
        "vastgoedadvertenties gevonden."
    )

    return properties


# ============================================================
# HILLEWAERE
# ============================================================

def find_hillewaere_properties(html):

    if not html:
        return []

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    properties = []

    for link in soup.find_all(
        "a",
        href=True
    ):

        href = link.get(
            "href",
            ""
        ).strip()

        if not href:
            continue

        url = absolute_url(
            "https://www.hillewaere-vastgoed.be",
            href
        )

        if "/vastgoed/" not in url.lower():
            continue

        id_match = re.search(
            r"/vastgoed/(\d+)(?:/|$)",
            url
        )

        if not id_match:
            continue

        text = clean_text(
            link.get_text(
                " ",
                strip=True
            )
        )

        if not text:
            continue

        if not is_arendonk(
            text,
            url
        ):
            continue

        if not is_for_sale(text):
            continue

        property_id = (
            "hillewaere-"
            + id_match.group(1)
        )

        properties.append(
            extract_generic_property_data(
                "Hillewaere",
                property_id,
                text,
                url
            )
        )

    unique = {}

    for property_data in properties:

        unique[
            property_data["id"]
        ] = property_data

    return list(
        unique.values()
    )


def scan_hillewaere():

    print(
        "Hillewaere controleren..."
    )

    html = get_page(
        HILLEWAERE_URL
    )

    if not html:

        print(
            "  Hillewaere overgeslagen."
        )

        return []

    properties = (
        find_hillewaere_properties(
            html
        )
    )

    print(
        f"  {len(properties)} "
        "vastgoedadvertenties gevonden."
    )

    return properties


# ============================================================
# CENTURY 21
# ============================================================

def find_century21_properties(html):

    if not html:
        return []

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    properties = []

    for link in soup.find_all(
        "a",
        href=True
    ):

        href = link.get(
            "href",
            ""
        ).strip()

        if not href:
            continue

        url = absolute_url(
            "https://www.century21.be",
            href
        )

        if "/nl/pand/te-koop/" not in (
            url.lower()
        ):
            continue

        if "/arendonk/" not in (
            url.lower()
        ):
            continue

        text = clean_text(
            link.get_text(
                " ",
                strip=True
            )
        )

        if not text:
            continue

        if not is_arendonk(
            text,
            url
        ):
            continue

        if not is_for_sale(text):
            continue

        property_id_match = re.search(
            r"/arendonk/([^/?#]+)",
            url,
            re.IGNORECASE
        )

        if property_id_match:

            property_id = (
                "century21-"
                + property_id_match.group(1)
            )

        else:

            property_id = make_hash_id(
                "century21",
                url
            )

        properties.append(
            extract_generic_property_data(
                "Century 21",
                property_id,
                text,
                url
            )
        )

    unique = {}

    for property_data in properties:

        unique[
            property_data["id"]
        ] = property_data

    return list(
        unique.values()
    )


def scan_century21():

    print(
        "Century 21 controleren..."
    )

    all_properties = []

    for url in CENTURY21_URLS:

        html = get_page(
            url
        )

        if not html:
            continue

        properties = (
            find_century21_properties(
                html
            )
        )

        all_properties.extend(
            properties
        )

    unique = {}

    for property_data in all_properties:

        unique[
            property_data["id"]
        ] = property_data

    result = list(
        unique.values()
    )

    print(
        f"  {len(result)} "
        "vastgoedadvertenties gevonden."
    )

    return result


# ============================================================
# DEWAELE
# ============================================================

def find_dewaele_properties(html):

    if not html:
        return []

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    properties = []

    category_paths = [
        "/nl/te-koop/2370-arendonk",
        "/nl/te-koop/2370-arendonk/huis",
        "/nl/te-koop/2370-arendonk/appartement",
        "/nl/te-koop/2370-arendonk/grond",
        "/nl/te-koop/2370-arendonk/garage",
        "/nl/te-koop/2370-arendonk/bedrijfsvastgoed",
        "/nl/te-koop/2370-arendonk/kantoor",
        "/nl/te-koop/2370-arendonk/industrie",
    ]

    for link in soup.find_all(
        "a",
        href=True
    ):

        href = link.get(
            "href",
            ""
        ).strip()

        if not href:
            continue

        url = absolute_url(
            "https://www.dewaele.com",
            href
        )

        if "/nl/te-koop/" not in (
            url.lower()
        ):
            continue

        path = urlparse(
            url
        ).path.lower().rstrip("/")

        if path in category_paths:
            continue

        text = clean_text(
            link.get_text(
                " ",
                strip=True
            )
        )

        if not text:
            continue

        if not is_arendonk(
            text,
            url
        ):
            continue

        if not is_for_sale(text):
            continue

        if "€" not in text:
            continue

        property_id = make_hash_id(
            "dewaele",
            url
        )

        properties.append(
            extract_generic_property_data(
                "Dewaele",
                property_id,
                text,
                url
            )
        )

    unique = {}

    for property_data in properties:

        unique[
            property_data["id"]
        ] = property_data

    return list(
        unique.values()
    )


def scan_dewaele():

    print(
        "Dewaele controleren..."
    )

    all_properties = []

    for url in DEWAELE_URLS:

        html = get_page(
            url
        )

        if not html:
            continue

        properties = (
            find_dewaele_properties(
                html
            )
        )

        all_properties.extend(
            properties
        )

    unique = {}

    for property_data in all_properties:

        unique[
            property_data["id"]
        ] = property_data

    result = list(
        unique.values()
    )

    print(
        f"  {len(result)} "
        "vastgoedadvertenties gevonden."
    )

    return result


# ============================================================
# IMMOWEB EN ZIMMO
#
# BEWUST NIET GEBRUIKT.
# ============================================================

def scan_immoweb():

    print(
        "Immoweb: uitgeschakeld."
    )

    return []


def scan_zimmo():

    print(
        "Zimmo: uitgeschakeld."
    )

    return []


# ============================================================
# DATABASE
# ============================================================

def load_state():

    if not os.path.exists(
        SEEN_FILE
    ):

        return set(), set()

    try:

        with open(
            SEEN_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        # ----------------------------------------------------
        # OUDE DATABASE
        # ----------------------------------------------------

        if isinstance(
            data,
            list
        ):

            seen = set(
                data
            )

            initialized_sources = set()

            if any(
                str(item).startswith(
                    "domestic-"
                )
                for item in seen
            ):

                initialized_sources.add(
                    "Domestic"
                )

            if any(
                str(item).isdigit()
                for item in seen
            ):

                initialized_sources.add(
                    "Immo Drie"
                )

            return (
                seen,
                initialized_sources
            )

        # ----------------------------------------------------
        # NIEUWE DATABASE
        # ----------------------------------------------------

        if isinstance(
            data,
            dict
        ):

            seen = set(
                data.get(
                    "seen",
                    []
                )
            )

            initialized_sources = set(
                data.get(
                    "initialized_sources",
                    []
                )
            )

            return (
                seen,
                initialized_sources
            )

    except Exception as error:

        print(
            "Database kon niet gelezen worden:"
        )

        print(error)

    return set(), set()


def save_state(
    seen,
    initialized_sources
):

    data = {

        "seen": sorted(
            list(seen)
        ),

        "initialized_sources": sorted(
            list(initialized_sources)
        )
    }

    with open(
        SEEN_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# TECHNISCHE DUBBELS BINNEN ÉÉN BRON
# ============================================================

def deduplicate_current_scan(
    properties
):

    unique = {}

    for property_data in properties:

        key = (
            property_data.get(
                "source"
            ),
            property_data.get(
                "id"
            )
        )

        unique[key] = property_data

    return list(
        unique.values()
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(
    property_data
):

    if not TELEGRAM_BOT_TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN ontbreekt."
        )

    if not TELEGRAM_CHAT_ID:

        raise RuntimeError(
            "TELEGRAM_CHAT_ID ontbreekt."
        )

    message_lines = [
        "🚨 NIEUW VASTGOED",
        ""
    ]

    property_type = (
        property_data.get(
            "type"
        )
    )

    if property_type:

        message_lines.append(
            f"🏠 {property_type}"
        )

    city = (
        property_data.get(
            "city"
        )
    )

    if city:

        message_lines.append(
            f"📍 {city}"
        )

    price = (
        property_data.get(
            "price"
        )
    )

    if price:

        message_lines.append(
            f"💰 {price}"
        )

    bedrooms = (
        property_data.get(
            "bedrooms"
        )
    )

    if bedrooms is not None:

        message_lines.append(
            f"🛏️ {bedrooms} slaapkamers"
        )

    living_area = (
        property_data.get(
            "living_area"
        )
    )

    if living_area:

        message_lines.append(
            f"📐 {living_area} m² leefruimte"
        )

    ground_area = (
        property_data.get(
            "ground_area"
        )
    )

    if ground_area:

        message_lines.append(
            f"🌳 {ground_area} m² grond"
        )

    message_lines.append("")

    source = (
        property_data.get(
            "source"
        )
    )

    if source:

        message_lines.append(
            f"🏢 {source}"
        )

    url = (
        property_data.get(
            "url"
        )
    )

    if url:

        message_lines.append("")

        message_lines.append(
            f"🔗 {url}"
        )

    message = "\n".join(
        message_lines
    )

    telegram_url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}"
        "/sendMessage"
    )

    response = requests.post(
        telegram_url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "disable_web_page_preview": False
        },
        timeout=30
    )

    response.raise_for_status()

    print(
        "Telegrammelding verstuurd voor "
        f"{property_data['id']}"
    )


# ============================================================
# ADVERTENTIES VERWERKEN
# ============================================================

def process_properties(
    properties
):

    seen, initialized_sources = (
        load_state()
    )

    print(
        f"{len(seen)} advertenties "
        "reeds gekend."
    )

    properties = (
        deduplicate_current_scan(
            properties
        )
    )

    # --------------------------------------------------------
    # GROEPEREN PER MAKELAAR
    # --------------------------------------------------------

    by_source = {}

    for property_data in properties:

        source = property_data[
            "source"
        ]

        by_source.setdefault(
            source,
            []
        ).append(
            property_data
        )

    # --------------------------------------------------------
    # NIEUWE MAKELAARS
    #
    # Bestaand aanbod wordt éénmalig stil
    # in de database opgenomen.
    # --------------------------------------------------------

    for source, source_properties in (
        by_source.items()
    ):

        if source not in (
            initialized_sources
        ):

            print(
                f"{source}: eerste scan."
            )

            print(
                "  Bestaand aanbod wordt "
                "stil als basis opgeslagen."
            )

            for property_data in (
                source_properties
            ):

                seen.add(
                    property_data[
                        "id"
                    ]
                )

            initialized_sources.add(
                source
            )

    # --------------------------------------------------------
    # NIEUWE ADVERTENTIES
    # --------------------------------------------------------

    new_properties = []

    for property_data in properties:

        property_id = (
            property_data[
                "id"
            ]
        )

        if property_id not in seen:

            new_properties.append(
                property_data
            )

    print(
        f"{len(new_properties)} nieuwe "
        "advertenties gevonden."
    )

    # --------------------------------------------------------
    # MELDINGEN
    # --------------------------------------------------------

    for property_data in (
        new_properties
    ):

        try:

            send_telegram(
                property_data
            )

            seen.add(
                property_data[
                    "id"
                ]
            )

            save_state(
                seen,
                initialized_sources
            )

        except Exception as error:

            print(
                "Fout bij Telegrammelding "
                f"voor "
                f"{property_data['id']}: "
                f"{error}"
            )

    # --------------------------------------------------------
    # DATABASE OPSLAAN
    # --------------------------------------------------------

    save_state(
        seen,
        initialized_sources
    )


# ============================================================
# START
# ============================================================

def main():

    print()

    print(
        "===================================="
    )

    print(
        "Vastgoed scanner gestart!"
    )

    print(
        "===================================="
    )

    print()

    all_properties = []

    # --------------------------------------------------------
    # IMMO DRIE
    # --------------------------------------------------------

    all_properties.extend(
        scan_immo_drie()
    )

    print()

    # --------------------------------------------------------
    # DOMESTIC
    # --------------------------------------------------------

    all_properties.extend(
        scan_domestic()
    )

    print()

    # --------------------------------------------------------
    # HEYLEN VASTGOED
    # --------------------------------------------------------

    all_properties.extend(
        scan_heylen()
    )

    print()

    # --------------------------------------------------------
    # HILLEWAERE
    # --------------------------------------------------------

    all_properties.extend(
        scan_hillewaere()
    )

    print()

    # --------------------------------------------------------
    # CENTURY 21
    # --------------------------------------------------------

    all_properties.extend(
        scan_century21()
    )

    print()

    # --------------------------------------------------------
    # DEWAELE
    # --------------------------------------------------------

    all_properties.extend(
        scan_dewaele()
    )

    print()

    # --------------------------------------------------------
    # IMMOWEB / ZIMMO
    # --------------------------------------------------------

    scan_immoweb()

    scan_zimmo()

    print()

    # --------------------------------------------------------
    # RESULTAAT
    # --------------------------------------------------------

    print(
        f"{len(all_properties)} "
        "advertenties totaal verzameld."
    )

    print()

    # --------------------------------------------------------
    # NIEUWE ADVERTENTIES VERWERKEN
    # --------------------------------------------------------

    process_properties(
        all_properties
    )

    print()

    print(
        "Scanner klaar."
    )

    print()


if __name__ == "__main__":

    main()
