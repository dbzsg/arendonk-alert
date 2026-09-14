import os
import re
import json
import time
import hashlib
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup


# ============================================================
# INSTELLINGEN
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

DATABASE_FILE = "seen_properties.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "nl-BE,nl;q=0.9,en;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
}

REQUEST_TIMEOUT = 20


# ============================================================
# HTTP
# ============================================================

session = requests.Session()
session.headers.update(HEADERS)


def get_page(url, attempts=2, timeout=REQUEST_TIMEOUT):

    for attempt in range(1, attempts + 1):

        try:

            response = session.get(
                url,
                timeout=timeout,
                allow_redirects=True,
            )

            if response.status_code == 200:
                return response

            print(
                f"  HTTP {response.status_code} bij {url} "
                f"(poging {attempt}/{attempts})"
            )

        except requests.RequestException as error:

            print(
                f"  Poging {attempt}/{attempts} mislukt: "
                f"{type(error).__name__}: {error}"
            )

        if attempt < attempts:
            time.sleep(1.5)

    return None


# ============================================================
# ALGEMENE HULPFUNCTIES
# ============================================================

def clean_text(text):

    if not text:
        return ""

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def absolute_url(base_url, href):

    if not href:
        return None

    href = href.strip()

    if href.startswith(
        (
            "javascript:",
            "mailto:",
            "tel:",
            "#",
        )
    ):
        return None

    return urljoin(
        base_url,
        href,
    )


def normalize_url(url):

    if not url:
        return ""

    parsed = urlparse(url)

    return (
        f"{parsed.scheme}://"
        f"{parsed.netloc}"
        f"{parsed.path}"
    ).rstrip("/")


def normalize_for_compare(text):

    if not text:
        return ""

    text = text.lower()

    replacements = {
        "é": "e",
        "è": "e",
        "ë": "e",
        "ê": "e",
        "ï": "i",
        "ö": "o",
        "ü": "u",
        "à": "a",
        "á": "a",
        "â": "a",
        "ç": "c",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(
        r"[^a-z0-9\s]",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def is_arendonk(text):

    if not text:
        return False

    lower = text.lower()

    return (
        "arendonk" in lower
        or re.search(
            r"\b2370\b",
            lower,
        ) is not None
    )


def contains_unavailable_status(text):

    if not text:
        return False

    lower = normalize_for_compare(text)

    forbidden = [
        "in optie",
        "in option",
        "verkocht",
        "vendu",
        "sold",
        "verhuurd",
        "loue",
        "loué",
        "gereserveerd",
        "reserveerd",
        "onder bod",
        "offre en cours",
    ]

    for phrase in forbidden:

        if phrase in lower:
            return True

    return False


def is_for_sale(text):

    if not text:
        return False

    lower = normalize_for_compare(text)

    positive = [
        "te koop",
        "a vendre",
        "for sale",
    ]

    for phrase in positive:

        if phrase in lower:
            return True

    return False


def extract_price(text):

    if not text:
        return None

    patterns = [
        r"€\s*([\d\.\s]+)",
        r"EUR\s*([\d\.\s]+)",
        r"([\d\.\s]+)\s*€",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match:

            number = re.sub(
                r"[^\d]",
                "",
                match.group(1),
            )

            if number:

                try:
                    return int(number)

                except ValueError:
                    pass

    return None


def extract_area(text, keywords):

    if not text:
        return None

    lower = text.lower()

    for keyword in keywords:

        position = lower.find(
            keyword.lower()
        )

        if position >= 0:

            section = text[
                position:
                position + 250
            ]

            match = re.search(
                r"([\d\.,]+)\s*(?:m²|m2)",
                section,
                re.IGNORECASE,
            )

            if match:

                value = (
                    match.group(1)
                    .replace(".", "")
                    .replace(",", ".")
                )

                try:
                    return float(value)

                except ValueError:
                    pass

    return None


def extract_bedrooms(text):

    if not text:
        return None

    patterns = [
        r"(\d+)\s*slaapkamers?",
        r"slaapkamers?\s*:?\s*(\d+)",
        r"(\d+)\s*chambres?",
        r"chambres?\s*:?\s*(\d+)",
        r"(\d+)\s*bedrooms?",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match:

            try:
                return int(
                    match.group(1)
                )

            except ValueError:
                pass

    return None


def extract_address(text):

    if not text:
        return ""

    patterns = [

        r"([A-ZÀ-ÿ][A-Za-zÀ-ÿ'’\-\s]{2,60}\s+\d+[A-Za-z]?)\s*,?\s*2370\s+Arendonk",

        r"([A-ZÀ-ÿ][A-Za-zÀ-ÿ'’\-\s]{2,60}\s+\d+[A-Za-z]?)\s+2370\s+Arendonk",

        r"([A-ZÀ-ÿ][A-Za-zÀ-ÿ'’\-\s]{2,60}\s+\d+[A-Za-z]?)\s*,?\s*Arendonk",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match:

            return clean_text(
                match.group(1)
            )

    return ""


def extract_reference(text):

    if not text:
        return ""

    patterns = [
        r"Ref\.?\s*:?\s*([A-Za-z0-9\-/]+)",
        r"referentie\s*:?\s*([A-Za-z0-9\-/]+)",
        r"référence\s*:?\s*([A-Za-z0-9\-/]+)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match:
            return match.group(1)

    return ""


def make_property_id(
    source,
    url,
):

    raw = (
        f"{source}|"
        f"{normalize_url(url)}"
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:24]


def make_cross_source_key(
    property_data
):

    address = property_data.get(
        "address",
        "",
    )

    price = property_data.get(
        "price"
    )

    living_area = property_data.get(
        "living_area"
    )

    if not address:
        return ""

    if not price:
        return ""

    if not living_area:
        return ""

    address = normalize_for_compare(
        address
    )

    return (
        f"{address}|"
        f"{price}|"
        f"{round(float(living_area))}"
    )


def extract_property_type(text):

    if not text:
        return ""

    lower = text.lower()

    types = [
        ("bouwgrond", "Bouwgrond"),
        ("grond", "Grond"),
        ("villa", "Villa"),
        ("appartement", "Appartement"),
        ("penthouse", "Penthouse"),
        ("duplex", "Duplex"),
        ("woning", "Woning"),
        ("huis", "Huis"),
        ("studio", "Studio"),
        ("handelspand", "Handelspand"),
        ("commercieel", "Commercieel"),
        ("kantoor", "Kantoor"),
        ("garage", "Garage"),
        ("magazijn", "Magazijn"),
        ("industrie", "Industrieel"),
        ("opbrengsteigendom", "Opbrengsteigendom"),
        ("gebouw voor gemengd gebruik", "Gemengd gebruik"),
    ]

    for needle, label in types:

        if needle in lower:
            return label

    return ""


# ============================================================
# URL DETECTIE
# ============================================================

def unique_urls_from_html(
    html,
    base_url,
    pattern,
):

    if not html:
        return []

    found = set()

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    # --------------------------------------------------------
    # 1. Normale href's
    # --------------------------------------------------------

    for link in soup.find_all(
        "a",
        href=True,
    ):

        full_url = absolute_url(
            base_url,
            link.get("href"),
        )

        if not full_url:
            continue

        if re.search(
            pattern,
            full_url,
            re.IGNORECASE,
        ):

            found.add(
                normalize_url(
                    full_url
                )
            )

    # --------------------------------------------------------
    # 2. URLs rechtstreeks uit HTML
    #
    # Dit is belangrijk voor websites waarbij
    # advertenties via JavaScript/data-attributen
    # worden opgebouwd.
    # --------------------------------------------------------

    raw_patterns = [
        r'https?://[^"\'<>\s]+',
        r'["\'](/[^"\']+)["\']',
    ]

    for raw_pattern in raw_patterns:

        for match in re.finditer(
            raw_pattern,
            html,
            re.IGNORECASE,
        ):

            candidate = match.group(0)

            candidate = (
                candidate
                .strip(
                    "\"'<>"
                )
            )

            full_url = absolute_url(
                base_url,
                candidate,
            )

            if not full_url:
                continue

            if re.search(
                pattern,
                full_url,
                re.IGNORECASE,
            ):

                found.add(
                    normalize_url(
                        full_url
                    )
                )

    return sorted(
        found
    )


def discover_detail_urls_from_page(
    response,
    base_url,
    detail_pattern,
    exclude_patterns=None,
):

    if not response:
        return []

    if exclude_patterns is None:
        exclude_patterns = []

    urls = unique_urls_from_html(
        response.text,
        base_url,
        detail_pattern,
    )

    result = []

    for url in urls:

        lower = url.lower()

        excluded = False

        for pattern in exclude_patterns:

            if re.search(
                pattern,
                lower,
            ):
                excluded = True
                break

        if excluded:
            continue

        result.append(
            url
        )

    return result


# ============================================================
# DETAILPAGINA UITLEZEN
# ============================================================

def parse_detail_page(
    source,
    url,
    title_hint="",
    timeout=20,
):

    response = get_page(
        url,
        attempts=1,
        timeout=timeout,
    )

    if not response:
        return None

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    # Scripts/styles verwijderen
    for tag in soup(
        [
            "script",
            "style",
            "noscript",
            "svg",
        ]
    ):
        tag.decompose()

    text = clean_text(
        soup.get_text(
            " ",
            strip=True,
        )
    )

    if not text:
        return None

    # Moet effectief Arendonk zijn.
    if not is_arendonk(text):
        return None

    # Geen verhuuradvertentie.
    if "/te-huur/" in url.lower():
        return None

    if "te huur" in normalize_for_compare(
        text[:5000]
    ) and "te koop" not in normalize_for_compare(
        text[:5000]
    ):
        return None

    # Verkocht / optie / verhuurd uitsluiten.
    if contains_unavailable_status(
        text
    ):
        return None

    # Bij detailpagina's willen we effectief
    # een verkoopadvertentie zien.
    if not is_for_sale(text):
        return None

    title = title_hint

    if not title:

        h1 = soup.find("h1")

        if h1:
            title = clean_text(
                h1.get_text(
                    " ",
                    strip=True,
                )
            )

    if not title and soup.title:

        title = clean_text(
            soup.title.get_text(
                " ",
                strip=True,
            )
        )

    property_data = create_property(
        source=source,
        url=url,
        title=title,
        text=text,
        property_type=extract_property_type(
            text
        ),
    )

    return property_data


# ============================================================
# PROPERTY AANMAKEN
# ============================================================

def create_property(
    source,
    url,
    title,
    text,
    property_type=None,
):

    url = normalize_url(url)

    title = clean_text(
        title
    )

    text = clean_text(
        text
    )

    if not title:
        title = (
            property_type
            or "Vastgoed te koop"
        )

    property_data = {

        "id": make_property_id(
            source,
            url,
        ),

        "source": source,

        "url": url,

        "title": title,

        "type": property_type or "",

        "address": extract_address(
            text
        ),

        "price": extract_price(
            text
        ),

        "bedrooms": extract_bedrooms(
            text
        ),

        "living_area": extract_area(
            text,
            [
                "bewoonbare oppervlakte",
                "bewoonbare opp",
                "woonoppervlakte",
                "woonopp",
                "leefruimte",
                "bewoonbare oppervlakte",
            ],
        ),

        "ground_area": extract_area(
            text,
            [
                "grondoppervlakte",
                "oppervlakte grond",
                "perceeloppervlakte",
                "perceelopp",
                "perceel",
            ],
        ),

        "reference": extract_reference(
            text
        ),

        "text": text[:5000],
    }

    property_data[
        "cross_source_key"
    ] = make_cross_source_key(
        property_data
    )

    return property_data


# ============================================================
# IMMO DRIE
# ============================================================

def is_immo_drie_detail_url(
    url
):

    if not url:
        return False

    path = urlparse(
        url
    ).path.lower()

    # Voorbeeld:
    # /nl/huis-te-koop-in-arendonk/7791969
    #
    # Belangrijk:
    # /nl/te-koop/woningen
    # mag NOOIT als advertentie gelden.

    if not re.search(
        r"/\d+$",
        path,
    ):
        return False

    if "/te-koop/" in path:
        return False

    if "/te-huur/" in path:
        return False

    if "/nl/" not in path:
        return False

    return True


def scan_immo_drie():

    print(
        "\nImmo Drie controleren..."
    )

    base = (
        "https://www.immodrie.be"
    )

    seed_urls = [
        f"{base}/nl/te-koop",
        f"{base}/nl/te-koop/woningen",
        f"{base}/nl/te-koop/appartementen",
        f"{base}/nl/te-koop/gronden",
        f"{base}/nl/te-koop/commercieel",
        f"{base}/nl/te-koop/kantoren",
        f"{base}/nl/te-koop/garages",
        f"{base}/nl/te-koop/opbrengsteigendom",
    ]

    detail_urls = set()

    # --------------------------------------------------------
    # Eerst de normale overzichtspagina's.
    # --------------------------------------------------------

    for seed_url in seed_urls:

        response = get_page(
            seed_url,
            attempts=1,
            timeout=15,
        )

        if not response:
            continue

        found = discover_detail_urls_from_page(
            response=response,
            base_url=base,
            detail_pattern=r"/nl/[^\"'<>\s]+/\d+$",
            exclude_patterns=[
                r"/te-koop/",
                r"/te-huur/",
            ],
        )

        for url in found:

            if is_immo_drie_detail_url(
                url
            ):
                detail_urls.add(
                    url
                )

    # --------------------------------------------------------
    # De huidige site gebruikt meerdere pagina's.
    #
    # We zoeken niet blind 20 pagina's af.
    # We volgen de gevonden paginering uit de HTML.
    # --------------------------------------------------------

    pagination_urls = set()

    for seed_url in seed_urls:

        response = get_page(
            seed_url,
            attempts=1,
            timeout=15,
        )

        if not response:
            continue

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        for link in soup.find_all(
            "a",
            href=True,
        ):

            href = link.get(
                "href"
            )

            full_url = absolute_url(
                base,
                href,
            )

            if not full_url:
                continue

            lower = full_url.lower()

            if "/nl/te-koop" not in lower:
                continue

            if (
                "page="
                in lower
                or "pagina"
                in lower
            ):

                pagination_urls.add(
                    normalize_url(
                        full_url
                    )
                )

    # Maximaal 30 extra overzichtspagina's.
    # Zo kan een tijdelijke vreemde link nooit
    # een eindeloze scan veroorzaken.

    for page_url in sorted(
        pagination_urls
    )[:30]:

        response = get_page(
            page_url,
            attempts=1,
            timeout=15,
        )

        if not response:
            continue

        found = discover_detail_urls_from_page(
            response=response,
            base_url=base,
            detail_pattern=r"/nl/[^\"'<>\s]+/\d+$",
            exclude_patterns=[
                r"/te-koop/",
                r"/te-huur/",
            ],
        )

        for url in found:

            if is_immo_drie_detail_url(
                url
            ):
                detail_urls.add(
                    url
                )

    print(
        f"  {len(detail_urls)} "
        f"mogelijke detailpagina's gevonden."
    )

    properties = []

    for index, url in enumerate(
        sorted(detail_urls),
        start=1,
    ):

        property_data = parse_detail_page(
            source="Immo Drie",
            url=url,
        )

        if not property_data:
            continue

        properties.append(
            property_data
        )

        print(
            f"  {index}/{len(detail_urls)}: "
            f"{property_data.get('title', '')[:70]}"
        )

    # Exacte URL-dubbels verwijderen.
    unique = {}
    for property_data in properties:
        unique[
            property_data["url"]
        ] = property_data

    properties = list(
        unique.values()
    )

    print(
        f"TOTAAL Immo Drie: "
        f"{len(properties)} "
        f"unieke advertenties."
    )

    return properties


# ============================================================
# DOMESTIC
# ============================================================

def is_domestic_detail_url(
    url
):

    if not url:
        return False

    path = urlparse(
        url
    ).path.lower()

    return bool(
        re.search(
            r"/\d+$",
            path,
        )
    )


def scan_domestic():

    print(
        "\nDomestic controleren..."
    )

    base = (
        "https://www.domestic.be"
    )

    seed_urls = [
        f"{base}/nl/te-koop/arendonk-2370",
        f"{base}/nl/te-koop/woningen/arendonk-2370",
        f"{base}/nl/te-koop/appartementen/arendonk-2370",
        f"{base}/nl/te-koop/gronden/arendonk-2370",
        f"{base}/nl/te-koop/commercieel/arendonk-2370",
        f"{base}/nl/te-koop/garages/arendonk-2370",
        f"{base}/nl/te-koop/industrieel/arendonk-2370",
    ]

    detail_urls = set()

    for seed_url in seed_urls:

        response = get_page(
            seed_url,
            attempts=1,
            timeout=20,
        )

        if not response:
            continue

        found = discover_detail_urls_from_page(
            response=response,
            base_url=base,
            detail_pattern=r"/nl/[^\"'<>\s]+/\d+$",
        )

        for url in found:

            if is_domestic_detail_url(
                url
            ):
                detail_urls.add(
                    url
                )

    print(
        f"  {len(detail_urls)} "
        f"mogelijke detailpagina's gevonden."
    )

    properties = []

    for index, url in enumerate(
        sorted(detail_urls),
        start=1,
    ):

        property_data = parse_detail_page(
            source="Domestic",
            url=url,
        )

        if not property_data:
            continue

        properties.append(
            property_data
        )

        print(
            f"  {index}/{len(detail_urls)}: "
            f"{property_data.get('title', '')[:70]}"
        )

    unique = {}

    for property_data in properties:
        unique[
            property_data["url"]
        ] = property_data

    properties = list(
        unique.values()
    )

    print(
        f"TOTAAL Domestic: "
        f"{len(properties)} "
        f"unieke advertenties."
    )

    return properties


# ============================================================
# HEYLEN VASTGOED
# ============================================================

def is_heylen_detail_url(
    url
):

    if not url:
        return False

    path = urlparse(
        url
    ).path.lower()

    return bool(
        re.search(
            r"/kopen/[^/]+/\d+$",
            path,
        )
    )


def scan_heylen():

    print(
        "\nHeylen Vastgoed controleren..."
    )

    base = (
        "https://www.heylenvastgoed.be"
    )

    seed_urls = [
        f"{base}/kopen/arendonk",
    ]

    detail_urls = set()

    for seed_url in seed_urls:

        response = get_page(
            seed_url,
            attempts=2,
            timeout=20,
        )

        if not response:
            continue

        found = discover_detail_urls_from_page(
            response=response,
            base_url=base,
            detail_pattern=r"/kopen/[^\"'<>\s]+/\d+$",
        )

        for url in found:

            if is_heylen_detail_url(
                url
            ):
                detail_urls.add(
                    url
                )

    print(
        f"  {len(detail_urls)} "
        f"mogelijke detailpagina's gevonden."
    )

    properties = []

    for index, url in enumerate(
        sorted(detail_urls),
        start=1,
    ):

        property_data = parse_detail_page(
            source="Heylen Vastgoed",
            url=url,
        )

        if not property_data:
            continue

        properties.append(
            property_data
        )

        print(
            f"  {index}/{len(detail_urls)}: "
            f"{property_data.get('title', '')[:70]}"
        )

    unique = {}

    for property_data in properties:
        unique[
            property_data["url"]
        ] = property_data

    properties = list(
        unique.values()
    )

    print(
        f"TOTAAL Heylen Vastgoed: "
        f"{len(properties)} "
        f"unieke advertenties."
    )

    return properties


# ============================================================
# HILLEWAERE
# ============================================================

def is_hillewaere_detail_url(
    url
):

    if not url:
        return False

    path = urlparse(
        url
    ).path.lower()

    return bool(
        re.search(
            r"/vastgoed/\d+",
            path,
        )
    )


def scan_hillewaere():

    print(
        "\nHillewaere controleren..."
    )

    base = (
        "https://www.hillewaere-vastgoed.be"
    )

    seed_urls = [
        f"{base}/vastgoed/alle/te-koop",
        f"{base}/vastgoed/alle/te-koop?view=list",
        f"{base}/vastgoed/alle/te-koop?page=1&view=list",
    ]

    detail_urls = set()

    # --------------------------------------------------------
    # Eerst seedpagina's.
    # --------------------------------------------------------

    for seed_url in seed_urls:

        response = get_page(
            seed_url,
            attempts=1,
            timeout=20,
        )

        if not response:
            continue

        found = discover_detail_urls_from_page(
            response=response,
            base_url=base,
            detail_pattern=r"/vastgoed/\d+[^\"'<>\s]*",
        )

        for url in found:

            if is_hillewaere_detail_url(
                url
            ):
                detail_urls.add(
                    url
                )

    # --------------------------------------------------------
    # Omdat Hillewaere de resultaten over
    # verschillende pagina's verdeelt, scannen we
    # maximaal 30 pagina's.
    #
    # Dit is bewust alleen voor Hillewaere.
    # --------------------------------------------------------

    for page in range(
        1,
        31,
    ):

        url = (
            f"{base}/vastgoed/alle/te-koop"
            f"?page={page}&view=list"
        )

        response = get_page(
            url,
            attempts=1,
            timeout=15,
        )

        if not response:
            continue

        found = discover_detail_urls_from_page(
            response=response,
            base_url=base,
            detail_pattern=r"/vastgoed/\d+[^\"'<>\s]*",
        )

        before = len(
            detail_urls
        )

        for candidate in found:

            if is_hillewaere_detail_url(
                candidate
            ):
                detail_urls.add(
                    candidate
                )

        added = (
            len(detail_urls)
            - before
        )

        if added:

            print(
                f"  Pagina {page}: "
                f"{added} nieuwe detailpagina(s)"
            )

    print(
        f"  {len(detail_urls)} "
        f"mogelijke detailpagina's gevonden."
    )

    properties = []

    for index, url in enumerate(
        sorted(detail_urls),
        start=1,
    ):

        property_data = parse_detail_page(
            source="Hillewaere",
            url=url,
        )

        if not property_data:
            continue

        properties.append(
            property_data
        )

        print(
            f"  {index}/{len(detail_urls)}: "
            f"{property_data.get('title', '')[:80]}"
        )

    unique = {}

    for property_data in properties:
        unique[
            property_data["url"]
        ] = property_data

    properties = list(
        unique.values()
    )

    print(
        f"TOTAAL Hillewaere: "
        f"{len(properties)} "
        f"unieke advertenties."
    )

    return properties


# ============================================================
# CENTURY 21
# ============================================================

def get_sitemap_urls():

    sitemap_urls = []

    robots_url = (
        "https://www.century21.be/robots.txt"
    )

    response = get_page(
        robots_url,
        attempts=1,
        timeout=15,
    )

    if response:

        for line in response.text.splitlines():

            if line.lower().startswith(
                "sitemap:"
            ):

                sitemap = line.split(
                    ":",
                    1,
                )[1].strip()

                if sitemap:
                    sitemap_urls.append(
                        sitemap
                    )

    sitemap_urls.extend(
        [
            "https://www.century21.be/sitemap.xml",
            "https://www.century21.be/sitemap_index.xml",
        ]
    )

    return list(
        dict.fromkeys(
            sitemap_urls
        )
    )


def parse_sitemap(
    sitemap_url,
    visited=None,
    depth=0,
):

    if visited is None:
        visited = set()

    if depth > 3:
        return []

    if sitemap_url in visited:
        return []

    visited.add(
        sitemap_url
    )

    response = get_page(
        sitemap_url,
        attempts=1,
        timeout=20,
    )

    if not response:
        return []

    try:

        root = ET.fromstring(
            response.text
        )

    except ET.ParseError:

        return []

    namespace = ""

    if root.tag.startswith(
        "{"
    ):

        namespace = (
            root.tag.split(
                "}",
                1,
            )[0]
            + "}"
        )

    urls = []

    if root.tag.endswith(
        "sitemapindex"
    ):

        for sitemap in root.findall(
            f"{namespace}sitemap"
        ):

            loc = sitemap.find(
                f"{namespace}loc"
            )

            if (
                loc is not None
                and loc.text
            ):

                urls.extend(
                    parse_sitemap(
                        loc.text.strip(),
                        visited,
                        depth + 1,
                    )
                )

    elif root.tag.endswith(
        "urlset"
    ):

        for item in root.findall(
            f"{namespace}url"
        ):

            loc = item.find(
                f"{namespace}loc"
            )

            if (
                loc is not None
                and loc.text
            ):

                urls.append(
                    loc.text.strip()
                )

    return urls


def is_century21_detail_url(
    url
):

    if not url:
        return False

    lower = url.lower()

    return (
        "century21.be/nl/pand/"
        in lower
        and "/te-koop/"
        in lower
        and "/arendonk/"
        in lower
    )


def scan_century21():

    print(
        "\nCentury 21 controleren..."
    )

    base = (
        "https://www.century21.be"
    )

    candidates = set()

    # --------------------------------------------------------
    # Sitemap.
    # --------------------------------------------------------

    for sitemap_url in get_sitemap_urls():

        urls = parse_sitemap(
            sitemap_url
        )

        for url in urls:

            if is_century21_detail_url(
                url
            ):
                candidates.add(
                    normalize_url(
                        url
                    )
                )

    # --------------------------------------------------------
    # Officiële algemene koopsite als extra
    # bron voor links.
    # --------------------------------------------------------

    overview_urls = [
        f"{base}/nl/te-koop",
    ]

    for overview_url in overview_urls:

        response = get_page(
            overview_url,
            attempts=1,
            timeout=20,
        )

        if not response:
            continue

        found = discover_detail_urls_from_page(
            response=response,
            base_url=base,
            detail_pattern=(
                r"/nl/pand/te-koop/"
                r"[^\"'<>\s]+/arendonk/"
                r"[^\"'<>\s]+"
            ),
        )

        for url in found:

            if is_century21_detail_url(
                url
            ):
                candidates.add(
                    url
                )

    print(
        f"  {len(candidates)} "
        f"mogelijke Arendonk-pandpagina's gevonden."
    )

    properties = []

    for index, url in enumerate(
        sorted(candidates),
        start=1,
    ):

        property_data = parse_detail_page(
            source="Century 21",
            url=url,
        )

        if not property_data:
            continue

        properties.append(
            property_data
        )

        print(
            f"  {index}/{len(candidates)}: "
            f"{property_data.get('title', '')[:80]}"
        )

    unique = {}

    for property_data in properties:
        unique[
            property_data["url"]
        ] = property_data

    properties = list(
        unique.values()
    )

    print(
        f"TOTAAL Century 21: "
        f"{len(properties)} "
        f"unieke advertenties."
    )

    return properties


# ============================================================
# DEWAELE
# ============================================================

def is_dewaele_detail_url(
    url
):

    if not url:
        return False

    path = urlparse(
        url
    ).path.lower()

    # We sluiten de algemene Arendonk-
    # filterpagina's uit.
    if (
        "/te-koop/2370-arendonk"
        in path
    ):
        return False

    # Dewaele detailpagina's kunnen verschillende
    # slugs gebruiken. We accepteren alleen links
    # die niet naar algemene filters leiden.
    if "/te-koop/" not in path:
        return False

    return True


def scan_dewaele():

    print(
        "\nDewaele controleren..."
    )

    base = (
        "https://www.dewaele.com"
    )

    seed_urls = [
        f"{base}/nl/te-koop/2370-arendonk",
        f"{base}/nl/te-koop/2370-arendonk/huis",
        f"{base}/nl/te-koop/2370-arendonk/appartement",
        f"{base}/nl/te-koop/2370-arendonk/grond",
        f"{base}/nl/te-koop/2370-arendonk/handelspand",
        f"{base}/nl/te-koop/2370-arendonk/industrie",
        f"{base}/nl/te-koop/2370-arendonk/kantoor",
        f"{base}/nl/te-koop/2370-arendonk/garage",
    ]

    detail_urls = set()

    for seed_url in seed_urls:

        response = get_page(
            seed_url,
            attempts=1,
            timeout=15,
        )

        if not response:
            continue

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        # Dewaele is gevoeliger voor foutieve
        # links, daarom verzamelen we eerst alleen
        # echte href's.
        for link in soup.find_all(
            "a",
            href=True,
        ):

            full_url = absolute_url(
                base,
                link.get("href"),
            )

            if not full_url:
                continue

            path = urlparse(
                full_url
            ).path.lower()

            if not is_dewaele_detail_url(
                full_url
            ):
                continue

            # Alleen links die duidelijk niet
            # naar een filterpagina gaan.
            if path.rstrip("/") in [
                "/nl/te-koop",
                "/nl/te-koop/2370-arendonk",
                "/nl/te-koop/2370-arendonk/huis",
                "/nl/te-koop/2370-arendonk/appartement",
                "/nl/te-koop/2370-arendonk/grond",
                "/nl/te-koop/2370-arendonk/handelspand",
                "/nl/te-koop/2370-arendonk/industrie",
                "/nl/te-koop/2370-arendonk/kantoor",
                "/nl/te-koop/2370-arendonk/garage",
            ]:
                continue

            detail_urls.add(
                normalize_url(
                    full_url
                )
            )

    print(
        f"  {len(detail_urls)} "
        f"mogelijke detailpagina's gevonden."
    )

    properties = []

    for index, url in enumerate(
        sorted(detail_urls),
        start=1,
    ):

        property_data = parse_detail_page(
            source="Dewaele",
            url=url,
        )

        if not property_data:
            continue

        properties.append(
            property_data
        )

        print(
            f"  {index}/{len(detail_urls)}: "
            f"{property_data.get('title', '')[:80]}"
        )

    unique = {}

    for property_data in properties:
        unique[
            property_data["url"]
        ] = property_data

    properties = list(
        unique.values()
    )

    print(
        f"TOTAAL Dewaele: "
        f"{len(properties)} "
        f"unieke advertenties."
    )

    return properties


# ============================================================
# DATABASE
# ============================================================

def load_database():

    if not os.path.exists(
        DATABASE_FILE
    ):

        return {
            "seen": [],
            "initialized_sources": [],
        }

    try:

        with open(
            DATABASE_FILE,
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(
                file
            )

    except Exception as error:

        print(
            f"Database kon niet gelezen "
            f"worden: {error}"
        )

        return {
            "seen": [],
            "initialized_sources": [],
        }

    # Oude versie was een simpele lijst.
    if isinstance(
        data,
        list,
    ):

        return {
            "seen": data,
            "initialized_sources": [],
        }

    if isinstance(
        data,
        dict,
    ):

        return {
            "seen": data.get(
                "seen",
                [],
            ),
            "initialized_sources": data.get(
                "initialized_sources",
                [],
            ),
        }

    return {
        "seen": [],
        "initialized_sources": [],
    }


def save_database(
    database
):

    with open(
        DATABASE_FILE,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            database,
            file,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(
    property_data
):

    if (
        not TELEGRAM_BOT_TOKEN
        or not TELEGRAM_CHAT_ID
    ):

        print(
            "Telegram instellingen ontbreken."
        )

        return False

    source = property_data.get(
        "source",
        "",
    )

    title = property_data.get(
        "title",
        "Vastgoed te koop",
    )

    url = property_data.get(
        "url",
        "",
    )

    price = property_data.get(
        "price"
    )

    bedrooms = property_data.get(
        "bedrooms"
    )

    living_area = property_data.get(
        "living_area"
    )

    ground_area = property_data.get(
        "ground_area"
    )

    address = property_data.get(
        "address"
    )

    property_type = property_data.get(
        "type"
    )

    reference = property_data.get(
        "reference"
    )

    message_parts = [

        "🏠 <b>NIEUW VASTGOED IN ARENDONK</b>",

        "",

        f"<b>{title}</b>",
    ]

    if address:

        message_parts.append(
            f"📍 {address}, 2370 Arendonk"
        )

    if property_type:

        message_parts.append(
            f"🏷️ Type: {property_type}"
        )

    if price:

        formatted_price = (
            f"{price:,.0f}"
            .replace(",", ".")
        )

        message_parts.append(
            f"💶 € {formatted_price}"
        )

    if bedrooms:

        message_parts.append(
            f"🛏️ {bedrooms} slaapkamers"
        )

    if living_area:

        message_parts.append(
            f"📐 {living_area:g} m²"
        )

    if ground_area:

        message_parts.append(
            f"🌳 Perceel: {ground_area:g} m²"
        )

    if reference:

        message_parts.append(
            f"🔖 Ref.: {reference}"
        )

    message_parts.extend(
        [
            "",
            f"🏢 <b>{source}</b>",
            "",
            (
                f'🔗 <a href="{url}">'
                f"Bekijk de advertentie"
                f"</a>"
            ),
        ]
    )

    message = "\n".join(
        message_parts
    )

    telegram_url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}"
        "/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    try:

        response = session.post(
            telegram_url,
            json=payload,
            timeout=20,
        )

        if response.status_code == 200:

            print(
                f"  Telegram verzonden: "
                f"{title}"
            )

            return True

        print(
            f"  Telegram fout: "
            f"{response.status_code} - "
            f"{response.text[:300]}"
        )

    except requests.RequestException as error:

        print(
            f"  Telegram verbinding "
            f"mislukt: {error}"
        )

    return False


# ============================================================
# VERWERKING
# ============================================================

def process_properties(
    properties,
    database,
):

    seen = set(
        database.get(
            "seen",
            [],
        )
    )

    initialized_sources = set(
        database.get(
            "initialized_sources",
            [],
        )
    )

    # --------------------------------------------------------
    # Huidige advertenties per bron
    # --------------------------------------------------------

    current_ids_by_source = {}

    for property_data in properties:

        source = property_data[
            "source"
        ]

        property_id = property_data[
            "id"
        ]

        current_ids_by_source.setdefault(
            source,
            set(),
        ).add(
            property_id
        )

    # --------------------------------------------------------
    # Nieuwe bron?
    #
    # Bestaande advertenties van een nieuwe bron
    # worden niet allemaal tegelijk naar Telegram
    # gestuurd.
    # --------------------------------------------------------

    for source, ids in (
        current_ids_by_source.items()
    ):

        if source not in initialized_sources:

            print(
                f"{source}: eerste scan."
            )

            for property_id in ids:

                seen.add(
                    property_id
                )

            initialized_sources.add(
                source
            )

            print(
                f"  {len(ids)} bestaande "
                f"advertenties worden stil "
                f"als basis opgeslagen."
            )

    # --------------------------------------------------------
    # Cross-source duplicaten
    #
    # Als exact hetzelfde pand bij twee makelaars
    # staat, proberen we maar één melding te sturen.
    # --------------------------------------------------------

    groups = {}

    for property_data in properties:

        key = property_data.get(
            "cross_source_key",
            "",
        )

        if key:

            groups.setdefault(
                key,
                [],
            ).append(
                property_data
            )

    duplicate_ids = set()

    # Vaste voorkeursvolgorde.
    source_priority = {
        "Immo Drie": 1,
        "Domestic": 2,
        "Heylen Vastgoed": 3,
        "Hillewaere": 4,
        "Century 21": 5,
        "Dewaele": 6,
    }

    for key, group in groups.items():

        if len(group) <= 1:
            continue

        group = sorted(
            group,
            key=lambda item:
                source_priority.get(
                    item.get("source"),
                    99,
                ),
        )

        winner = group[0]

        for property_data in group[1:]:

            if (
                property_data["id"]
                != winner["id"]
            ):

                duplicate_ids.add(
                    property_data["id"]
                )

                print(
                    "  Dubbele advertentie "
                    "over makelaars heen "
                    "genegeerd:"
                )

                print(
                    f"    {property_data.get('source')} "
                    f"-> "
                    f"{property_data.get('address', '')}"
                )

    # --------------------------------------------------------
    # Nieuwe advertenties
    # --------------------------------------------------------

    new_properties = []

    for property_data in properties:

        property_id = property_data[
            "id"
        ]

        if property_id in seen:
            continue

        if property_id in duplicate_ids:

            seen.add(
                property_id
            )

            continue

        new_properties.append(
            property_data
        )

    print()

    print(
        f"{len(seen)} advertenties reeds gekend."
    )

    print(
        f"{len(new_properties)} nieuwe "
        f"advertenties gevonden."
    )

    # --------------------------------------------------------
    # Telegram
    # --------------------------------------------------------

    for property_data in new_properties:

        print(
            "NIEUW:",
            property_data.get(
                "source"
            ),
            "|",
            property_data.get(
                "title"
            ),
            "|",
            property_data.get(
                "url"
            ),
        )

        sent = send_telegram(
            property_data
        )

        if sent:

            seen.add(
                property_data["id"]
            )

        time.sleep(
            0.5
        )

    database["seen"] = sorted(
        seen
    )

    database[
        "initialized_sources"
    ] = sorted(
        initialized_sources
    )

    save_database(
        database
    )


# ============================================================
# HOOFDPROGRAMMA
# ============================================================

def main():

    print(
        "=========================================="
    )

    print(
        "Vastgoed scanner gestart!"
    )

    print(
        "=========================================="
    )

    print()

    database = load_database()

    all_properties = []

    scanners = [

        scan_immo_drie,

        scan_domestic,

        scan_heylen,

        scan_hillewaere,

        scan_century21,

        scan_dewaele,
    ]

    for scanner in scanners:

        try:

            properties = scanner()

            if properties:

                all_properties.extend(
                    properties
                )

        except Exception as error:

            print(
                f"  FOUT in "
                f"{scanner.__name__}: "
                f"{type(error).__name__}: "
                f"{error}"
            )

    # --------------------------------------------------------
    # Exacte dubbele URL's verwijderen.
    # --------------------------------------------------------

    unique_properties = []

    seen_ids = set()

    for property_data in all_properties:

        property_id = property_data[
            "id"
        ]

        if property_id in seen_ids:
            continue

        seen_ids.add(
            property_id
        )

        unique_properties.append(
            property_data
        )

    all_properties = (
        unique_properties
    )

    print()

    print(
        f"{len(all_properties)} advertenties "
        f"totaal verzameld."
    )

    print()

    print(
        "Immoweb: uitgeschakeld."
    )

    print(
        "Zimmo: uitgeschakeld."
    )

    process_properties(
        all_properties,
        database,
    )

    print()

    print(
        "=========================================="
    )

    print(
        "Scanner klaar."
    )

    print(
        "=========================================="
    )


if __name__ == "__main__":
    main()
