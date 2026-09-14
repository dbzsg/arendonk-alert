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
    """
    Haalt een pagina op met beperkte retries.
    """

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
# HULPFUNCTIES
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
    """
    Normaliseert tekst zodat adressen tussen verschillende
    makelaars beter met elkaar vergeleken kunnen worden.
    """

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
    """
    Probeert bijvoorbeeld:
    182 m²
    182m2
    Bewoonbare oppervlakte 182 m²
    """

    if not text:
        return None

    lower = text.lower()

    for keyword in keywords:
        position = lower.find(keyword.lower())

        if position >= 0:
            section = text[position:position + 150]

            match = re.search(
                r"([\d\.,]+)\s*(?:m²|m2)",
                section,
                re.IGNORECASE,
            )

            if match:
                value = match.group(1).replace(".", "").replace(",", ".")

                try:
                    return float(value)
                except ValueError:
                    pass

    return None


def extract_bedrooms(text):
    if not text:
        return None

    patterns = [
        r"(\d+)\s*(?:slaapkamers?|kamers?)",
        r"(?:slaapkamers?|kamers?)\s*:?\s*(\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass

    return None


def extract_address(text):
    """
    Probeert een Belgisch adres uit een kaart/detailtekst te halen.

    We gebruiken dit bewust voorzichtig voor deduplicatie.
    Als we geen betrouwbaar adres vinden, wordt er NIET
    cross-source gededupliceerd.
    """

    if not text:
        return ""

    # Voorbeelden:
    # Schutterstraat 35, 2370 Arendonk
    # Kapelstraat 29, 2370 Arendonk
    # De Brulen 6, 2370 Arendonk

    patterns = [
        r"([A-ZÀ-ÿ][A-Za-zÀ-ÿ'’\-\s]{2,50}\s+\d+[A-Za-z]?)\s*,?\s*2370\s+Arendonk",
        r"([A-ZÀ-ÿ][A-Za-zÀ-ÿ'’\-\s]{2,50}\s+\d+[A-Za-z]?)\s+2370\s+Arendonk",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            return clean_text(match.group(1))

    return ""


def is_probably_sold(text):
    if not text:
        return False

    lower = text.lower()

    sold_words = [
        "verkocht",
        "vendu",
        "sold",
        "afgesloten",
    ]

    for word in sold_words:
        if re.search(rf"\b{re.escape(word)}\b", lower):
            return True

    return False


def make_property_id(source, url):
    """
    Unieke ID per advertentie.
    """

    normalized = normalize_url(url)

    raw = f"{source}|{normalized}"

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def make_cross_source_key(property_data):
    """
    Voorzichtige deduplicatie tussen makelaars.

    Alleen gebruiken wanneer er een betrouwbaar adres aanwezig is.
    """

    address = property_data.get("address", "")

    if not address:
        return ""

    address_normalized = normalize_for_compare(address)

    if len(address_normalized) < 5:
        return ""

    price = property_data.get("price")

    living_area = property_data.get("living_area")
    ground_area = property_data.get("ground_area")

    parts = [
        address_normalized,
        str(price or ""),
        str(living_area or ""),
        str(ground_area or ""),
    ]

    return "|".join(parts)


def create_property(
    source,
    url,
    title,
    text,
    property_type=None,
):
    """
    Maakt één uniforme advertentie-objectstructuur.
    """

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
            "woonoppervlakte",
            "leefruimte",
            "oppervlakte",
        ],
    )

    ground_area = extract_area(
        text,
        [
            "oppervlakte grond",
            "grondoppervlakte",
            "perceel",
            "perceeloppervlakte",
        ],
    )

    address = extract_address(text)

    property_id = make_property_id(source, url)

    property_data = {
        "id": property_id,
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

    property_data["cross_source_key"] = make_cross_source_key(
        property_data
    )

    return property_data


# ============================================================
# DATABASE
# ============================================================

def load_database():
    if not os.path.exists(DATABASE_FILE):
        return {
            "seen": [],
            "initialized_sources": [],
        }

    try:
        with open(DATABASE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

    except Exception as error:
        print(f"Database kon niet gelezen worden: {error}")

        return {
            "seen": [],
            "initialized_sources": [],
        }

    # Oude versie was een gewone lijst
    if isinstance(data, list):
        return {
            "seen": data,
            "initialized_sources": [],
        }

    if isinstance(data, dict):
        return {
            "seen": data.get("seen", []),
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
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram instellingen ontbreken.")
        return False

    source = property_data.get("source", "")
    title = property_data.get("title", "Vastgoed te koop")
    url = property_data.get("url", "")

    price = property_data.get("price")
    bedrooms = property_data.get("bedrooms")
    living_area = property_data.get("living_area")
    ground_area = property_data.get("ground_area")
    address = property_data.get("address")
    property_type = property_data.get("type")

    message_parts = [
        "🏠 <b>NIEUW VASTGOED IN ARENDONK</b>",
        "",
        f"<b>{title}</b>",
    ]

    if address:
        message_parts.append(f"📍 {address}, 2370 Arendonk")

    if property_type:
        message_parts.append(f"🏷️ Type: {property_type}")

    if price:
        message_parts.append(
            f"💶 € {price:,.0f}".replace(",", ".")
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
            f"🔗 <a href=\"{url}\">Bekijk de advertentie</a>",
        ]
    )

    message = "\n".join(message_parts)

    telegram_url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
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
                f"{property_data.get('title')}"
            )
            return True

        print(
            f"  Telegram fout: "
            f"{response.status_code} - {response.text[:300]}"
        )

    except requests.RequestException as error:
        print(f"  Telegram verbinding mislukt: {error}")

    return False


# ============================================================
# GENERIEKE HTML-LISTING PARSER
# ============================================================

def find_property_links(
    soup,
    base_url,
    patterns,
):
    """
    Zoekt links waarvan de URL overeenkomt met één van de
    meegegeven regex-patronen.
    """

    results = []

    seen_urls = set()

    for link in soup.find_all("a", href=True):
        href = link.get("href")

        if not href:
            continue

        url = absolute_url(base_url, href)

        if not url:
            continue

        normalized = normalize_url(url)

        if normalized in seen_urls:
            continue

        for pattern in patterns:
            if re.search(pattern, normalized, re.IGNORECASE):
                seen_urls.add(normalized)
                results.append(link)
                break

    return results


def get_card_text(link, max_parents=7):
    """
    Probeert de tekst van de advertentiekaart te vinden.
    """

    node = link

    best_text = ""

    for _ in range(max_parents):
        if node is None:
            break

        text = clean_text(node.get_text(" ", strip=True))

        if text:
            # Bewaar grootste redelijke kaarttekst
            if len(text) > len(best_text) and len(text) <= 2500:
                best_text = text

            if "2370" in text and "arendonk" in text.lower():
                return text

        node = node.parent

    return best_text


# ============================================================
# IMMO DRIE
# ============================================================

def scan_immo_drie():
    print("Immo Drie controleren...")

    base = "https://www.immodrie.be"
    properties = []
    seen_urls = set()

    for page in range(1, 21):

        if page == 1:
            url = f"{base}/nl/te-koop"
        else:
            url = f"{base}/nl/te-koop?page={page}"

        response = get_page(url)

        if not response:
            print(
                f"  Pagina {page}: niet bereikbaar."
            )
            continue

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        count_before = len(properties)

        for link in soup.find_all("a", href=True):

            href = link.get("href", "")

            full_url = absolute_url(base, href)

            if not full_url:
                continue

            if "/te-koop/" not in full_url.lower():
                continue

            if full_url.rstrip("/") in {
                f"{base}/nl/te-koop",
            }:
                continue

            text = get_card_text(link)

            combined = clean_text(
                f"{link.get_text(' ', strip=True)} {text}"
            )

            if (
                "arendonk" not in combined.lower()
                and "2370" not in combined
            ):
                continue

            if is_probably_sold(combined):
                continue

            normalized = normalize_url(full_url)

            if normalized in seen_urls:
                continue

            seen_urls.add(normalized)

            properties.append(
                create_property(
                    source="Immo Drie",
                    url=normalized,
                    title=link.get_text(
                        " ",
                        strip=True,
                    ),
                    text=combined,
                )
            )

        count = len(properties) - count_before

        print(
            f"Pagina {page}: {count}"
        )

        if count == 0 and page >= 5:
            # Niet onmiddellijk stoppen; sommige pagina's
            # kunnen tijdelijk leeg terugkomen.
            pass

    print(
        f"TOTAAL Immo Drie: "
        f"{len(properties)} unieke advertenties."
    )

    return properties


# ============================================================
# DOMESTIC
# ============================================================

def scan_domestic():
    print("\nDomestic controleren...")

    base = "https://www.domestic.be"

    urls = [
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

    for url in urls:

        response = get_page(
            url,
            attempts=2,
            timeout=20,
        )

        if not response:
            print(
                f"  Domestic pagina niet bereikbaar: {url}"
            )
            continue

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        links = find_property_links(
            soup,
            base,
            [
                r"/nl/te-koop/[^?#]+/\d+",
            ],
        )

        page_count = 0

        for link in links:

            full_url = normalize_url(
                absolute_url(
                    base,
                    link.get("href"),
                )
            )

            if not full_url:
                continue

            if full_url in seen_urls:
                continue

            card_text = get_card_text(link)

            combined = clean_text(
                f"{link.get_text(' ', strip=True)} "
                f"{card_text}"
            )

            if (
                "arendonk" not in combined.lower()
                and "2370" not in combined
            ):
                continue

            if is_probably_sold(combined):
                continue

            seen_urls.add(full_url)

            properties.append(
                create_property(
                    source="Domestic",
                    url=full_url,
                    title=link.get_text(
                        " ",
                        strip=True,
                    ),
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

def scan_heylen():
    print("\nHeylen Vastgoed controleren...")

    base = "https://www.heylenvastgoed.be"

    url = f"{base}/kopen/arendonk"

    response = get_page(url)

    if not response:
        print("  Heylen Vastgoed is momenteel niet bereikbaar.")
        return []

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    properties = []
    seen_urls = set()

    for link in soup.find_all("a", href=True):

        href = link.get("href", "")

        full_url = absolute_url(base, href)

        if not full_url:
            continue

        if "/kopen/" not in full_url.lower():
            continue

        if full_url.rstrip("/") == url.rstrip("/"):
            continue

        normalized = normalize_url(full_url)

        if normalized in seen_urls:
            continue

        card_text = get_card_text(link)

        combined = clean_text(
            f"{link.get_text(' ', strip=True)} "
            f"{card_text}"
        )

        if (
            "arendonk" not in combined.lower()
            and "2370" not in combined
        ):
            continue

        if is_probably_sold(combined):
            continue

        seen_urls.add(normalized)

        properties.append(
            create_property(
                source="Heylen Vastgoed",
                url=normalized,
                title=link.get_text(
                    " ",
                    strip=True,
                ),
                text=combined,
            )
        )

    print(
        f"  {len(properties)} vastgoedadvertenties gevonden."
    )

    return properties


# ============================================================
# HILLEWAERE
# ============================================================

def scan_hillewaere():
    print("\nHillewaere controleren...")

    base = "https://www.hillewaere-vastgoed.be"

    properties = []
    seen_urls = set()

    # Hillewaere gebruikt algemene pagina's met paginering.
    # Arendonk staat niet noodzakelijk op pagina 1.
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
            print(
                f"  Pagina {page}: niet bereikbaar."
            )
            continue

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        page_found = 0

        links = find_property_links(
            soup,
            base,
            [
                r"/vastgoed/\d+",
            ],
        )

        for link in links:

            full_url = normalize_url(
                absolute_url(
                    base,
                    link.get("href"),
                )
            )

            if not full_url:
                continue

            if full_url in seen_urls:
                continue

            card_text = get_card_text(
                link,
                max_parents=9,
            )

            combined = clean_text(
                f"{link.get_text(' ', strip=True)} "
                f"{card_text}"
            )

            if (
                "arendonk" not in combined.lower()
                and "2370" not in combined
            ):
                continue

            if is_probably_sold(combined):
                continue

            seen_urls.add(full_url)

            properties.append(
                create_property(
                    source="Hillewaere",
                    url=full_url,
                    title=link.get_text(
                        " ",
                        strip=True,
                    ),
                    text=combined,
                )
            )

            page_found += 1

        if page_found:
            print(
                f"  Pagina {page}: "
                f"{page_found} Arendonk-advertentie(s)"
            )

    print(
        f"  TOTAAL Hillewaere: "
        f"{len(properties)} vastgoedadvertenties gevonden."
    )

    return properties


# ============================================================
# CENTURY 21
# ============================================================

def get_sitemap_urls():
    """
    Leest robots.txt en zoekt sitemap-bestanden.
    """

    robots_urls = [
        "https://www.century21.be/robots.txt",
        "https://www.century21.be/robots.txt?x=1",
    ]

    sitemap_urls = []

    for robots_url in robots_urls:

        response = get_page(
            robots_url,
            attempts=1,
            timeout=15,
        )

        if not response:
            continue

        for line in response.text.splitlines():

            if line.lower().startswith("sitemap:"):
                sitemap = line.split(":", 1)[1].strip()

                if sitemap:
                    sitemap_urls.append(sitemap)

    # Standaardfallbacks
    sitemap_urls.extend(
        [
            "https://www.century21.be/sitemap.xml",
            "https://www.century21.be/sitemap_index.xml",
        ]
    )

    # Uniek maken
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
    """
    Ondersteunt sitemap én sitemap-index.
    """

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

    text = response.text.strip()

    # Sommige servers geven XML met encodingproblemen.
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []

    namespace = ""

    if root.tag.startswith("{"):
        namespace = root.tag.split("}", 1)[0] + "}"

    urls = []

    if root.tag.endswith("sitemapindex"):

        for sitemap in root.findall(
            f"{namespace}sitemap"
        ):
            loc = sitemap.find(
                f"{namespace}loc"
            )

            if loc is not None and loc.text:
                child_url = loc.text.strip()

                urls.extend(
                    parse_sitemap(
                        child_url,
                        visited=visited,
                        depth=depth + 1,
                    )
                )

    elif root.tag.endswith("urlset"):

        for item in root.findall(
            f"{namespace}url"
        ):
            loc = item.find(
                f"{namespace}loc"
            )

            if loc is not None and loc.text:
                urls.append(
                    loc.text.strip()
                )

    return urls


def scan_century21():
    print("\nCentury 21 controleren...")

    sitemap_urls = get_sitemap_urls()

    if not sitemap_urls:
        print(
            "  Geen sitemap gevonden."
        )
        return []

    all_urls = []

    for sitemap_url in sitemap_urls:

        urls = parse_sitemap(sitemap_url)

        for url in urls:
            if url not in all_urls:
                all_urls.append(url)

    # Alleen directe pandpagina's in Arendonk.
    candidate_urls = []

    for url in all_urls:

        lower = url.lower()

        if (
            "century21.be/nl/pand/" in lower
            and "/arendonk/" in lower
            and "/te-koop/" in lower
        ):
            candidate_urls.append(url)

    # Extra filter tegen vreemde URLs
    candidate_urls = list(
        dict.fromkeys(candidate_urls)
    )

    print(
        f"  {len(candidate_urls)} "
        f"mogelijke Arendonk-pandpagina's gevonden."
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
            soup.get_text(" ", strip=True)
        )

        if "arendonk" not in text.lower():
            continue

        if "te koop" not in text.lower():
            continue

        if is_probably_sold(text):
            continue

        title = ""

        if soup.title:
            title = clean_text(
                soup.title.get_text()
            )

        # Probeer betere titel te vinden
        h1 = soup.find("h1")

        if h1:
            h1_text = clean_text(
                h1.get_text(" ", strip=True)
            )

            if h1_text:
                title = h1_text

        property_data = create_property(
            source="Century 21",
            url=url,
            title=title,
            text=text,
        )

        properties.append(property_data)

        print(
            f"  {index}/{len(candidate_urls)}: "
            f"{title[:70]}"
        )

    print(
        f"  TOTAAL Century 21: "
        f"{len(properties)} vastgoedadvertenties gevonden."
    )

    return properties


# ============================================================
# DEWAELE
# ============================================================

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

        links = find_property_links(
            soup,
            base,
            [
                r"/nl/te-koop/",
                r"/nl/vastgoed/",
            ],
        )

        for link in links:

            full_url = normalize_url(
                absolute_url(
                    base,
                    link.get("href"),
                )
            )

            if not full_url:
                continue

            if full_url in seen_urls:
                continue

            card_text = get_card_text(
                link,
                max_parents=8,
            )

            combined = clean_text(
                f"{link.get_text(' ', strip=True)} "
                f"{card_text}"
            )

            if (
                "arendonk" not in combined.lower()
                and "2370" not in combined
            ):
                continue

            if is_probably_sold(combined):
                continue

            seen_urls.add(full_url)

            properties.append(
                create_property(
                    source="Dewaele",
                    url=full_url,
                    title=link.get_text(
                        " ",
                        strip=True,
                    ),
                    text=combined,
                )
            )

    print(
        f"  {len(properties)} "
        f"vastgoedadvertenties gevonden."
    )

    return properties


# ============================================================
# VERWERKING EN DEDUPLICATIE
# ============================================================

def process_properties(
    properties,
    database,
):
    """
    Bepaalt welke advertenties nieuw zijn.

    Nieuwe bron:
        huidige aanbod wordt stil als basis opgeslagen.

    Bestaande bron:
        alleen onbekende advertenties worden gemeld.
    """

    seen = set(database.get("seen", []))

    initialized_sources = set(
        database.get(
            "initialized_sources",
            [],
        )
    )

    # --------------------------------------------------------
    # Eerst alle huidige IDs verzamelen
    # --------------------------------------------------------

    current_ids_by_source = {}

    for property_data in properties:

        source = property_data["source"]
        property_id = property_data["id"]

        current_ids_by_source.setdefault(
            source,
            set(),
        ).add(property_id)

    # --------------------------------------------------------
    # Nieuwe bronnen initialiseren
    # --------------------------------------------------------

    for source, ids in current_ids_by_source.items():

        if source not in initialized_sources:

            print(
                f"{source}: eerste scan."
            )

            for property_id in ids:
                seen.add(property_id)

            initialized_sources.add(source)

            print(
                f"  {len(ids)} bestaande advertenties "
                f"worden stil als basis opgeslagen."
            )

    # --------------------------------------------------------
    # Bepaal echt nieuwe advertenties
    # --------------------------------------------------------

    new_properties = []

    # Cross-source sleutels van reeds bekende advertenties
    known_cross_source_keys = set()

    for property_data in properties:

        property_id = property_data["id"]

        if property_id in seen:
            cross_key = property_data.get(
                "cross_source_key",
                "",
            )

            if cross_key:
                known_cross_source_keys.add(
                    cross_key
                )

    for property_data in properties:

        property_id = property_data["id"]

        # Al bekend bij dezelfde makelaar
        if property_id in seen:
            continue

        cross_key = property_data.get(
            "cross_source_key",
            "",
        )

        # ----------------------------------------------------
        # Cross-source deduplicatie
        #
        # Alleen als we een betrouwbaar adres + dezelfde
        # relevante kenmerken hebben.
        # ----------------------------------------------------

        if (
            cross_key
            and cross_key in known_cross_source_keys
        ):
            print(
                "  Dubbele advertentie over makelaars "
                "heen genegeerd: "
                f"{property_data.get('address', '')}"
            )

            seen.add(property_id)
            continue

        new_properties.append(property_data)

    # --------------------------------------------------------
    # Meld nieuwe advertenties
    # --------------------------------------------------------

    print(
        f"\n{len(seen)} advertenties reeds gekend."
    )

    print(
        f"{len(new_properties)} nieuwe advertenties gevonden."
    )

    for property_data in new_properties:

        print(
            "NIEUW:",
            property_data.get("source"),
            "|",
            property_data.get("title"),
            "|",
            property_data.get("url"),
        )

        sent = send_telegram(property_data)

        # Alleen toevoegen als Telegram gelukt is.
        #
        # Zo wordt een tijdelijke Telegram-storing niet
        # permanent als 'gemeld' beschouwd.
        if sent:
            seen.add(property_data["id"])

            cross_key = property_data.get(
                "cross_source_key",
                "",
            )

            if cross_key:
                known_cross_source_keys.add(
                    cross_key
                )

        time.sleep(0.5)

    database["seen"] = sorted(seen)
    database["initialized_sources"] = sorted(
        initialized_sources
    )

    save_database(database)

    return new_properties


# ============================================================
# HOOFDPROGRAMMA
# ============================================================

def main():

    print("==========================================")
    print("Vastgoed scanner gestart!")
    print("==========================================")
    print()

    database = load_database()

    all_properties = []

    # --------------------------------------------------------
    # DIRECTE MAKELAARS
    # --------------------------------------------------------

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
                f"  FOUT in {scanner.__name__}: "
                f"{type(error).__name__}: {error}"
            )

    # --------------------------------------------------------
    # Duplicaten binnen dezelfde scan verwijderen
    # --------------------------------------------------------

    unique_properties = []
    seen_scan_ids = set()

    for property_data in all_properties:

        property_id = property_data["id"]

        if property_id in seen_scan_ids:
            continue

        seen_scan_ids.add(property_id)
        unique_properties.append(property_data)

    all_properties = unique_properties

    # --------------------------------------------------------
    # Overzicht
    # --------------------------------------------------------

    print()
    print(
        f"{len(all_properties)} advertenties "
        f"totaal verzameld."
    )

    # --------------------------------------------------------
    # Immoweb/Zimmo bewust NIET gebruiken
    # --------------------------------------------------------

    print()
    print("Immoweb: uitgeschakeld.")
    print("Zimmo: uitgeschakeld.")

    # --------------------------------------------------------
    # Verwerken
    # --------------------------------------------------------

    process_properties(
        all_properties,
        database,
    )

    print()
    print("==========================================")
    print("Scanner klaar.")
    print("==========================================")


if __name__ == "__main__":
    main()
