import os
import re
import json
import time
import hashlib
from urllib.parse import urljoin, urlparse
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
            time.sleep(2)

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

    return urljoin(base_url, href)


def normalize_url(url):
    if not url:
        return ""

    parsed = urlparse(url)

    clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    return clean.rstrip("/")


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
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def extract_price(text):
    if not text:
        return None

    patterns = [
        r"€\s*([\d\.\s]+)",
        r"EUR\s*([\d\.\s]+)",
        r"([\d\.\s]+)\s*€",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            number = re.sub(r"[^\d]", "", match.group(1))

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
        position = lower.find(keyword.lower())

        if position >= 0:
            section = text[position:position + 180]

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
        r"(\d+)\s*(?:slaapkamers?|slaapkamer)",
        r"(?:slaapkamers?|slaapkamer)\s*:?\s*(\d+)",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass

    return None


def extract_address(text):
    if not text:
        return ""

    patterns = [
        r"([A-ZÀ-ÿ][A-Za-zÀ-ÿ'’\-\s]{2,50}\s+\d+[A-Za-z]?)\s*,?\s*2370\s+Arendonk",
        r"([A-ZÀ-ÿ][A-Za-zÀ-ÿ'’\-\s]{2,50}\s+\d+[A-Za-z]?)\s+2370\s+Arendonk",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match:
            return clean_text(match.group(1))

    return ""


def contains_unavailable_status(text):
    """
    Sluit advertenties uit die niet meer normaal te koop zijn.
    """

    if not text:
        return False

    lower = normalize_for_compare(text)

    forbidden_phrases = [
        "in optie",
        "in option",
        "optie",
        "option",
        "verkocht",
        "vendu",
        "sold",
        "verhuurd",
        "loué",
        "gereserveerd",
        "reserveerd",
        "onder bod",
        "offre en cours",
    ]

    for phrase in forbidden_phrases:
        if phrase in lower:
            return True

    return False


def make_property_id(source, url):
    normalized = normalize_url(url)

    raw = f"{source}|{normalized}"

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:24]


def make_cross_source_key(property_data):
    """
    Voorzichtige deduplicatie.

    Een adres alleen is niet genoeg: appartementen op hetzelfde
    adres kunnen verschillende panden zijn.

    Daarom combineren we adres + prijs + woonoppervlakte.
    """

    address = property_data.get("address", "")

    if not address:
        return ""

    address_normalized = normalize_for_compare(address)

    if len(address_normalized) < 5:
        return ""

    price = property_data.get("price")
    living_area = property_data.get("living_area")

    if not price or not living_area:
        return ""

    return (
        f"{address_normalized}|"
        f"{price}|"
        f"{round(float(living_area))}"
    )


def create_property(
    source,
    url,
    title,
    text,
    property_type=None,
):
    url = normalize_url(url)

    title = clean_text(title)
    text = clean_text(text)

    if not title:
        title = property_type or "Vastgoed te koop"

    price = extract_price(text)
    bedrooms = extract_bedrooms(text)

    living_area = extract_area(
        text,
        [
            "bewoonbare oppervlakte",
            "bewoonbare opp",
            "woonoppervlakte",
            "woonopp",
            "leefruimte",
        ],
    )

    ground_area = extract_area(
        text,
        [
            "oppervlakte grond",
            "grondoppervlakte",
            "perceeloppervlakte",
            "perceel",
        ],
    )

    address = extract_address(text)

    property_data = {
        "id": make_property_id(
            source,
            url,
        ),
        "source": source,
        "url": url,
        "title": title,
        "type": property_type or "",
        "address": address,
        "price": price,
        "bedrooms": bedrooms,
        "living_area": living_area,
        "ground_area": ground_area,
        "text": text,
    }

    property_data["cross_source_key"] = (
        make_cross_source_key(property_data)
    )

    return property_data


# ============================================================
# ADVERTENTIEKAART TEKST
# ============================================================

def get_card_text(link, max_parents=8):
    """
    Zoekt de tekst van de advertentiekaart rond een link.
    """

    node = link
    best_text = ""

    for _ in range(max_parents):

        if node is None:
            break

        text = clean_text(
            node.get_text(
                " ",
                strip=True,
            )
        )

        if text:

            if (
                len(text) > len(best_text)
                and len(text) <= 3000
            ):
                best_text = text

            if (
                "2370" in text
                and "arendonk" in text.lower()
            ):
                return text

        node = node.parent

    return best_text


def is_arendonk(text):
    if not text:
        return False

    lower = text.lower()

    return (
        "arendonk" in lower
        or "2370" in lower
    )


# ============================================================
# IMMO DRIE
# ============================================================

def is_immo_drie_detail_url(url):
    """
    Alleen echte detailpagina's.

    Belangrijk:
    /nl/te-koop/woningen
    /nl/te-koop/appartementen
    /nl/te-koop/pagina-2

    zijn GEEN advertenties.
    """

    if not url:
        return False

    parsed = urlparse(url)
    path = parsed.path.lower().rstrip("/")

    if not path.startswith("/nl/te-koop/"):
        return False

    blocked_exact = [
        "/nl/te-koop/woningen",
        "/nl/te-koop/appartementen",
        "/nl/te-koop/gronden",
        "/nl/te-koop/kantoren",
        "/nl/te-koop/commercieel",
        "/nl/te-koop/garages",
        "/nl/te-koop/opbrengsteigendom",
    ]

    if path in blocked_exact:
        return False

    if re.search(
        r"/nl/te-koop/pagina-\d+$",
        path,
    ):
        return False

    # Categorie-/overzichtspagina's
    blocked_parts = [
        "woningen",
        "appartementen",
        "gronden",
        "kantoren",
        "garages",
        "commercieel",
        "opbrengsteigendom",
    ]

    last_part = path.split("/")[-1]

    if last_part in blocked_parts:
        return False

    # Echte Immo Drie detailpagina's bevatten doorgaans
    # meerdere URL-segmenten.
    segments = [
        part for part in path.split("/")
        if part
    ]

    if len(segments) < 4:
        return False

    return True


def scan_immo_drie():
    print("Immo Drie controleren...")

    base = "https://www.immodrie.be"

    properties = []
    seen_urls = set()

    for page in range(1, 21):

        if page == 1:
            url = f"{base}/nl/te-koop"
        else:
            url = (
                f"{base}/nl/te-koop"
                f"?page={page}"
            )

        response = get_page(
            url,
            attempts=1,
            timeout=15,
        )

        if not response:
            print(
                f"Pagina {page}: niet bereikbaar."
            )
            continue

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        page_count = 0

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

            full_url = normalize_url(full_url)

            if not is_immo_drie_detail_url(
                full_url
            ):
                continue

            if full_url in seen_urls:
                continue

            card_text = get_card_text(link)

            link_text = clean_text(
                link.get_text(
                    " ",
                    strip=True,
                )
            )

            combined = clean_text(
                f"{link_text} {card_text}"
            )

            if not is_arendonk(combined):
                continue

            if contains_unavailable_status(
                combined
            ):
                continue

            seen_urls.add(full_url)

            properties.append(
                create_property(
                    source="Immo Drie",
                    url=full_url,
                    title=link_text,
                    text=combined,
                )
            )

            page_count += 1

        print(
            f"Pagina {page}: {page_count}"
        )

    print(
        f"TOTAAL Immo Drie: "
        f"{len(properties)} unieke advertenties."
    )

    return properties


# ============================================================
# DOMESTIC
# ============================================================

def is_domestic_detail_url(url):
    if not url:
        return False

    path = urlparse(url).path.lower()

    # Domestic detailpagina's eindigen op een numeriek ID.
    return bool(
        re.search(
            r"/\d+$",
            path,
        )
    )


def scan_domestic():
    print("\nDomestic controleren...")

    base = "https://www.domestic.be"

    overview_urls = [
        f"{base}/nl/te-koop/arendonk-2370",
        f"{base}/nl/te-koop/woningen/arendonk-2370",
        f"{base}/nl/te-koop/appartementen/arendonk-2370",
        f"{base}/nl/te-koop/gronden/arendonk-2370",
        f"{base}/nl/te-koop/commercieel/arendonk-2370",
        f"{base}/nl/te-koop/garages/arendonk-2370",
        f"{base}/nl/te-koop/industrieel/arendonk-2370",
    ]

    properties = []
    seen_urls = set()

    for url in overview_urls:

        response = get_page(
            url,
            attempts=1,
            timeout=20,
        )

        if not response:
            print(
                f"  Domestic pagina niet bereikbaar: "
                f"{url}"
            )
            continue

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        page_count = 0

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

            full_url = normalize_url(full_url)

            if not is_domestic_detail_url(
                full_url
            ):
                continue

            if full_url in seen_urls:
                continue

            card_text = get_card_text(
                link,
                max_parents=8,
            )

            link_text = clean_text(
                link.get_text(
                    " ",
                    strip=True,
                )
            )

            combined = clean_text(
                f"{link_text} {card_text}"
            )

            if not is_arendonk(combined):
                continue

            if contains_unavailable_status(
                combined
            ):
                continue

            seen_urls.add(full_url)

            properties.append(
                create_property(
                    source="Domestic",
                    url=full_url,
                    title=link_text,
                    text=combined,
                )
            )

            page_count += 1

        print(
            f"  {page_count} advertenties gevonden "
            f"op {url}"
        )

    print(
        f"TOTAAL Domestic: "
        f"{len(properties)} unieke advertenties."
    )

    return properties


# ============================================================
# HEYLEN VASTGOED
# ============================================================

def is_heylen_detail_url(url):
    if not url:
        return False

    path = urlparse(url).path.lower()

    # Detailpagina's hebben /kopen/.../<nummer>
    return bool(
        re.search(
            r"/kopen/[^/]+/\d+$",
            path,
        )
    )


def scan_heylen():
    print("\nHeylen Vastgoed controleren...")

    base = "https://www.heylenvastgoed.be"

    url = f"{base}/kopen/arendonk"

    response = get_page(url)

    if not response:
        print(
            "  Heylen Vastgoed is momenteel "
            "niet bereikbaar."
        )
        return []

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    properties = []
    seen_urls = set()

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

        full_url = normalize_url(full_url)

        if not is_heylen_detail_url(
            full_url
        ):
            continue

        if full_url in seen_urls:
            continue

        card_text = get_card_text(
            link,
            max_parents=9,
        )

        link_text = clean_text(
            link.get_text(
                " ",
                strip=True,
            )
        )

        combined = clean_text(
            f"{link_text} {card_text}"
        )

        if not is_arendonk(combined):
            continue

        if contains_unavailable_status(
            combined
        ):
            continue

        seen_urls.add(full_url)

        properties.append(
            create_property(
                source="Heylen Vastgoed",
                url=full_url,
                title=link_text,
                text=combined,
            )
        )

    print(
        f"  {len(properties)} "
        f"vastgoedadvertenties gevonden."
    )

    return properties


# ============================================================
# HILLEWAERE
# ============================================================

def is_hillewaere_detail_url(url):
    if not url:
        return False

    path = urlparse(url).path.lower()

    return bool(
        re.search(
            r"/vastgoed/\d+",
            path,
        )
    )


def scan_hillewaere():
    print("\nHillewaere controleren...")

    base = "https://www.hillewaere-vastgoed.be"

    properties = []
    seen_urls = set()

    for page in range(1, 31):

        if page == 1:
            url = (
                f"{base}/vastgoed/alle/te-koop"
                f"?view=list"
            )
        else:
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

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        page_count = 0

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

            full_url = normalize_url(full_url)

            if not is_hillewaere_detail_url(
                full_url
            ):
                continue

            if full_url in seen_urls:
                continue

            card_text = get_card_text(
                link,
                max_parents=10,
            )

            link_text = clean_text(
                link.get_text(
                    " ",
                    strip=True,
                )
            )

            combined = clean_text(
                f"{link_text} {card_text}"
            )

            if not is_arendonk(combined):
                continue

            if contains_unavailable_status(
                combined
            ):
                continue

            seen_urls.add(full_url)

            properties.append(
                create_property(
                    source="Hillewaere",
                    url=full_url,
                    title=link_text,
                    text=combined,
                )
            )

            page_count += 1

        if page_count:
            print(
                f"  Pagina {page}: "
                f"{page_count} Arendonk-advertentie(s)"
            )

    print(
        f"  TOTAAL Hillewaere: "
        f"{len(properties)} "
        f"vastgoedadvertenties gevonden."
    )

    return properties


# ============================================================
# CENTURY 21
# ============================================================

def get_sitemap_urls():
    robots_url = (
        "https://www.century21.be/robots.txt"
    )

    sitemap_urls = []

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

    # Fallbacks
    sitemap_urls.extend(
        [
            "https://www.century21.be/sitemap.xml",
            "https://www.century21.be/sitemap_index.xml",
        ]
    )

    result = []

    for url in sitemap_urls:
        if url not in result:
            result.append(url)

    return result


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

    visited.add(sitemap_url)

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

    if root.tag.startswith("{"):
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

    elif root.tag.endswith("urlset"):

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


def is_century21_detail_url(url):
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
    print("\nCentury 21 controleren...")

    sitemap_urls = get_sitemap_urls()

    all_urls = []

    for sitemap_url in sitemap_urls:

        urls = parse_sitemap(
            sitemap_url
        )

        for url in urls:

            if url not in all_urls:
                all_urls.append(url)

    candidate_urls = []

    for url in all_urls:

        if is_century21_detail_url(
            url
        ):
            candidate_urls.append(url)

    candidate_urls = list(
        dict.fromkeys(candidate_urls)
    )

    print(
        f"  {len(candidate_urls)} "
        f"mogelijke Arendonk-pandpagina's "
        f"gevonden."
    )

    properties = []

    for index, url in enumerate(
        candidate_urls,
        start=1,
    ):

        response = get_page(
            url,
            attempts=1,
            timeout=15,
        )

        if not response:
            continue

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        text = clean_text(
            soup.get_text(
                " ",
                strip=True,
            )
        )

        if not is_arendonk(text):
            continue

        if "te koop" not in text.lower():
            continue

        if contains_unavailable_status(
            text
        ):
            continue

        title = ""

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
                soup.title.get_text()
            )

        properties.append(
            create_property(
                source="Century 21",
                url=url,
                title=title,
                text=text,
            )
        )

        print(
            f"  {index}/{len(candidate_urls)}: "
            f"{title[:80]}"
        )

    print(
        f"  TOTAAL Century 21: "
        f"{len(properties)} "
        f"vastgoedadvertenties gevonden."
    )

    return properties


# ============================================================
# DEWAELE
# ============================================================

def is_dewaele_detail_url(url):
    if not url:
        return False

    path = urlparse(url).path.lower()

    # Filterpagina's mogen nooit als advertentie worden gezien.
    blocked = [
        "/te-koop/2370-arendonk",
        "/te-koop/2370-arendonk/",
    ]

    for blocked_path in blocked:
        if path.rstrip("/") == blocked_path.rstrip("/"):
            return False

    # Alleen links die duidelijk een pand voorstellen.
    # Dewaele detailpagina's bevatten meestal een numerieke
    # vastgoed-ID.
    return bool(
        re.search(
            r"/\d{5,}",
            path,
        )
    )


def scan_dewaele():
    print("\nDewaele controleren...")

    base = "https://www.dewaele.com"

    urls = [
        f"{base}/nl/te-koop/2370-arendonk",
        f"{base}/nl/te-koop/2370-arendonk/huis",
        f"{base}/nl/te-koop/2370-arendonk/appartement",
        f"{base}/nl/te-koop/2370-arendonk/grond",
        f"{base}/nl/te-koop/2370-arendonk/handelspand",
        f"{base}/nl/te-koop/2370-arendonk/industrie",
        f"{base}/nl/te-koop/2370-arendonk/kantoor",
        f"{base}/nl/te-koop/2370-arendonk/garage",
    ]

    properties = []
    seen_urls = set()

    for url in urls:

        response = get_page(
            url,
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

            full_url = absolute_url(
                base,
                link.get("href"),
            )

            if not full_url:
                continue

            full_url = normalize_url(
                full_url
            )

            if not is_dewaele_detail_url(
                full_url
            ):
                continue

            if full_url in seen_urls:
                continue

            card_text = get_card_text(
                link,
                max_parents=10,
            )

            link_text = clean_text(
                link.get_text(
                    " ",
                    strip=True,
                )
            )

            combined = clean_text(
                f"{link_text} {card_text}"
            )

            if not is_arendonk(combined):
                continue

            if contains_unavailable_status(
                combined
            ):
                continue

            seen_urls.add(full_url)

            properties.append(
                create_property(
                    source="Dewaele",
                    url=full_url,
                    title=link_text,
                    text=combined,
                )
            )

    print(
        f"  {len(properties)} "
        f"vastgoedadvertenties gevonden."
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

            data = json.load(file)

    except Exception as error:

        print(
            f"Database kon niet gelezen worden: "
            f"{error}"
        )

        return {
            "seen": [],
            "initialized_sources": [],
        }

    # Oude databasevorm
    if isinstance(data, list):

        return {
            "seen": data,
            "initialized_sources": [],
        }

    if isinstance(data, dict):

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


def save_database(database):

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

def send_telegram(property_data):

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
            f"  Telegram verbinding mislukt: "
            f"{error}"
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
        ).add(property_id)

    # --------------------------------------------------------
    # Eerste scan van een bron
    # --------------------------------------------------------

    for source, ids in (
        current_ids_by_source.items()
    ):

        if source not in initialized_sources:

            print(
                f"{source}: eerste scan."
            )

            for property_id in ids:
                seen.add(property_id)

            initialized_sources.add(
                source
            )

            print(
                f"  {len(ids)} bestaande "
                f"advertenties worden stil "
                f"als basis opgeslagen."
            )

    # --------------------------------------------------------
    # Bekende cross-source advertenties
    # --------------------------------------------------------

    known_cross_source_keys = set()

    # We kennen de volledige historische
    # advertentiegegevens niet meer uit de oude
    # database, dus cross-source deduplicatie
    # gebeurt vooral binnen de huidige scan.
    current_cross_source_keys = {}

    for property_data in properties:

        key = property_data.get(
            "cross_source_key",
            "",
        )

        if not key:
            continue

        current_cross_source_keys.setdefault(
            key,
            [],
        ).append(
            property_data
        )

    # --------------------------------------------------------
    # Bepaal nieuwe advertenties
    # --------------------------------------------------------

    new_properties = []

    for property_data in properties:

        property_id = property_data[
            "id"
        ]

        # Exact dezelfde URL reeds gekend
        if property_id in seen:
            continue

        cross_key = property_data.get(
            "cross_source_key",
            "",
        )

        # Als exact hetzelfde pand momenteel
        # bij meerdere makelaars staat, melden
        # we maar één versie.
        if cross_key:

            duplicates = (
                current_cross_source_keys.get(
                    cross_key,
                    [],
                )
            )

            if len(duplicates) > 1:

                # Kies deterministisch één makelaar.
                # De eerste in de scanvolgorde wint.
                first = duplicates[0]

                if (
                    property_data["id"]
                    != first["id"]
                ):

                    print(
                        "  Dubbele advertentie "
                        "over makelaars heen "
                        "genegeerd: "
                        f"{property_data.get('address', '')}"
                    )

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

        time.sleep(0.5)

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

    return new_properties


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
    # Exacte dubbele URL's verwijderen
    # --------------------------------------------------------

    unique_properties = []

    seen_scan_ids = set()

    for property_data in all_properties:

        property_id = property_data[
            "id"
        ]

        if property_id in seen_scan_ids:
            continue

        seen_scan_ids.add(
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
