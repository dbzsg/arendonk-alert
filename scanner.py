import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time


# ============================================================
# INSTELLINGEN
# ============================================================

IMMO_DRIE_URL = "https://www.immodrie.be/nl/te-koop"

DOMESTIC_URL = "https://www.domestic.be/nl/te-koop/arendonk-2370"

SEEN_FILE = "seen_properties.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


# ============================================================
# HULPFUNCTIES
# ============================================================

def clean_text(text):
    return " ".join(text.split())


def extract_price(text):

    match = re.search(
        r"€\s*[\d\.\,]+",
        text
    )

    if match:
        return match.group(0).strip()

    return None


def extract_bedrooms(text):

    match = re.search(
        r"Slaapkamers\s*(\d+)",
        text,
        re.IGNORECASE
    )

    if match:
        return int(match.group(1))

    return None


def extract_area(text, label):

    pattern = (
        rf"{re.escape(label)}\s*"
        rf"(\d+(?:[.,]\d+)?)\s*m²"
    )

    match = re.search(
        pattern,
        text,
        re.IGNORECASE
    )

    if match:
        return match.group(1).replace(",", ".")

    return None


def extract_city(text):

    match = re.search(
        r"\b\d{4}\s+([A-Za-zÀ-ÿ'’\-]+)",
        text
    )

    if match:
        return match.group(1)

    return None


# ============================================================
# IMMO DRIE PAGINA OPHALEN
# ============================================================

def get_immo_drie_page(page):

    if page == 1:
        url = IMMO_DRIE_URL
    else:
        url = f"{IMMO_DRIE_URL}/pagina-{page}"

    print(
        f"Pagina {page} controleren..."
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/139.0 Safari/537.36"
        )
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    return response.text


# ============================================================
# VASTGOEDTYPE IMMO DRIE
# ============================================================

def extract_property_type(text):

    property_text = text

    remove_words = [
        "Nieuw",
        "Te koop",
        "In optie",
        "Verkocht",
        "Video",
        "Virtueel"
    ]

    for word in remove_words:

        property_text = re.sub(
            rf"\b{re.escape(word)}\b",
            "",
            property_text,
            flags=re.IGNORECASE
        )

    property_text = re.split(
        r"\b\d{4}\b",
        property_text,
        maxsplit=1
    )[0]

    property_text = clean_text(
        property_text
    )

    if property_text:
        return property_text

    return "Vastgoed"


# ============================================================
# IMMO DRIE ADVERTENTIES VINDEN
# ============================================================

def find_properties(html):

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

        if (
            "immodrie.be" not in href
            and not href.startswith("/")
        ):
            continue

        if href.startswith("/"):

            url = (
                "https://www.immodrie.be"
                + href
            )

        else:

            url = href

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

        city = extract_city(text)

        if not city:
            continue

        if city.lower() != "arendonk":
            continue

        status = "Onbekend"

        if re.search(
            r"\bNieuw\b",
            text,
            re.IGNORECASE
        ):

            status = "Nieuw"

        elif re.search(
            r"\bTe koop\b",
            text,
            re.IGNORECASE
        ):

            status = "Te koop"

        elif re.search(
            r"\bIn optie\b",
            text,
            re.IGNORECASE
        ):

            status = "In optie"

        elif re.search(
            r"\bVerkocht\b",
            text,
            re.IGNORECASE
        ):

            status = "Verkocht"

        if status not in [
            "Nieuw",
            "Te koop"
        ]:
            continue

        property_data = {

            "id": property_id,

            "source": "Immo Drie",

            "type": extract_property_type(
                text
            ),

            "city": city,

            "price": extract_price(
                text
            ),

            "bedrooms": extract_bedrooms(
                text
            ),

            "living_area": extract_area(
                text,
                "Leefruimte"
            ),

            "ground_area": extract_area(
                text,
                "Titles.surface_ground"
            ),

            "status": status,

            "url": url
        }

        properties.append(
            property_data
        )

    unique_properties = {}

    for property_data in properties:

        unique_properties[
            property_data["id"]
        ] = property_data

    return list(
        unique_properties.values()
    )


# ============================================================
# DATABASE LADEN
# ============================================================

def load_seen():

    if not os.path.exists(
        SEEN_FILE
    ):
        return set()

    try:

        with open(
            SEEN_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        return set(data)

    except Exception:

        return set()


# ============================================================
# DATABASE OPSLAAN
# ============================================================

def save_seen(seen):

    with open(
        SEEN_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            sorted(list(seen)),
            file,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# TELEGRAM MELDING
# ============================================================

def send_telegram(property_data):

    message_lines = []

    message_lines.append(
        "🚨 NIEUW VASTGOED"
    )

    message_lines.append("")

    property_type = property_data.get(
        "type"
    )

    if property_type:
        message_lines.append(
            f"🏠 {property_type}"
        )

    city = property_data.get(
        "city"
    )

    if city:
        message_lines.append(
            f"📍 {city}"
        )

    message_lines.append("")

    price = property_data.get(
        "price"
    )

    if price:
        message_lines.append(
            f"💰 {price}"
        )

    bedrooms = property_data.get(
        "bedrooms"
    )

    if bedrooms is not None:
        message_lines.append(
            f"🛏️ {bedrooms} slaapkamers"
        )

    living_area = property_data.get(
        "living_area"
    )

    if living_area:
        message_lines.append(
            f"📐 {living_area} m² leefruimte"
        )

    ground_area = property_data.get(
        "ground_area"
    )

    if ground_area:
        message_lines.append(
            f"🌳 {ground_area} m² grond"
        )

    message_lines.append("")

    source = property_data.get(
        "source"
    )

    if source:
        message_lines.append(
            f"🏢 {source}"
        )

    url = property_data.get(
        "url"
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
# IMMO DRIE SCANNEN
# ============================================================

def scan_immo_drie():

    print(
        "Immo Drie controleren..."
    )

    all_properties = []

    for page in range(1, 21):

        try:

            html = get_immo_drie_page(
                page
            )

            properties = find_properties(
                html
            )

            print(
                f"  {len(properties)} "
                "vastgoedadvertenties gevonden."
            )

            if not properties:

                print(
                    "Geen vastgoed meer gevonden."
                )

                break

            all_properties.extend(
                properties
            )

        except requests.RequestException as error:

            print(
                f"Fout bij pagina {page}: "
                f"{error}"
            )

            break

    unique_properties = {}

    for property_data in all_properties:

        unique_properties[
            property_data["id"]
        ] = property_data

    result = list(
        unique_properties.values()
    )

    print(
        "TOTAAL: "
        f"{len(result)} unieke "
        "vastgoedadvertenties gevonden."
    )

    return result


# ============================================================
# DOMESTIC PAGINA OPHALEN
# ============================================================

def get_domestic_page():

    print(
        "Domestic controleren..."
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/139.0 Safari/537.36"
        )
    }

    max_attempts = 3

    for attempt in range(
        1,
        max_attempts + 1
    ):

        try:

            print(
                f"  Poging {attempt}/{max_attempts}..."
            )

            response = requests.get(
                DOMESTIC_URL,
                headers=headers,
                timeout=60
            )

            response.raise_for_status()

            print(
                "  Domestic succesvol bereikbaar."
            )

            return response.text

        except requests.RequestException as error:

            print(
                f"  Domestic poging {attempt} "
                f"mislukt: {error}"
            )

            if attempt < max_attempts:

                print(
                    "  Opnieuw proberen..."
                )

                time.sleep(5)

            else:

                print(
                    "  Domestic is momenteel "
                    "niet bereikbaar."
                )

    return None


# ============================================================
# DOMESTIC ADVERTENTIES VINDEN
# ============================================================

def find_domestic_properties(html):

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

        if href.startswith("/"):

            url = (
                "https://www.domestic.be"
                + href
            )

        elif "domestic.be" in href:

            url = href

        else:

            continue

        if (
            "/nl/" not in url
            or "te-koop" not in url.lower()
        ):
            continue

        category_paths = [
            "/woningen/",
            "/appartement/",
            "/gronden/",
            "/garages/",
            "/commercieel/"
        ]

        if any(
            path in url.lower()
            for path in category_paths
        ):
            continue

        id_matches = re.findall(
            r"(\d{5,})",
            url
        )

        if not id_matches:
            continue

        property_id = (
            "domestic-"
            + id_matches[-1]
        )

        if url.rstrip("/").lower().endswith(
            "arendonk-2370"
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

        if (
            "arendonk" not in text.lower()
            and "arendonk" not in url.lower()
        ):
            continue

        property_data = {

            "id": property_id,

            "source": "Domestic",

            "type": "Vastgoed",

            "city": "Arendonk",

            "price": extract_price(
                text
            ),

            "bedrooms": extract_bedrooms(
                text
            ),

            "living_area": extract_area(
                text,
                "Leefruimte"
            ),

            "ground_area": extract_area(
                text,
                "Grondoppervlakte"
            ),

            "status": "Te koop",

            "url": url
        }

        properties.append(
            property_data
        )

    unique_properties = {}

    for property_data in properties:

        unique_properties[
            property_data["id"]
        ] = property_data

    return list(
        unique_properties.values()
    )


# ============================================================
# DOMESTIC SCANNEN
# ============================================================

def scan_domestic():

    try:

        html = get_domestic_page()

        if not html:

            print(
                "  Domestic overgeslagen."
            )

            return []

        properties = find_domestic_properties(
            html
        )

        print(
            f"  {len(properties)} "
            "vastgoedadvertenties gevonden."
        )

        return properties

    except Exception as error:

        print(
            f"Fout bij Domestic: {error}"
        )

        return []


# ============================================================
# NIEUWE ADVERTENTIES VERWERKEN
# ============================================================

def process_properties(properties):

    seen = load_seen()

    print(
        f"{len(seen)} advertenties "
        "reeds gekend."
    )

    if not seen:

        print(
            "Database is leeg."
        )

        print(
            "Bestaand aanbod wordt "
            "opgeslagen zonder "
            "Telegrammeldingen."
        )

        for property_data in properties:

            seen.add(
                property_data["id"]
            )

        save_seen(seen)

        print(
            f"{len(properties)} advertenties "
            "aan database toegevoegd."
        )

        return

    new_properties = []

    for property_data in properties:

        property_id = (
            property_data["id"]
        )

        if property_id not in seen:

            new_properties.append(
                property_data
            )

    print(
        f"{len(new_properties)} nieuwe "
        "advertenties gevonden."
    )

    for property_data in new_properties:

        try:

            send_telegram(
                property_data
            )

            seen.add(
                property_data["id"]
            )

            save_seen(seen)

        except Exception as error:

            print(
                "Fout bij Telegrammelding "
                f"voor {property_data['id']}: "
                f"{error}"
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

    # --------------------------------------------------------
    # IMMO DRIE
    # --------------------------------------------------------

    immo_drie_properties = scan_immo_drie()

    print()

    # --------------------------------------------------------
    # DOMESTIC
    # --------------------------------------------------------

    domestic_properties = scan_domestic()

    print()

    # --------------------------------------------------------
    # ALLES SAMENVOEGEN
    # --------------------------------------------------------

    all_properties = (
        immo_drie_properties
        + domestic_properties
    )

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
