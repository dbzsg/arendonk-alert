import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import json
import os

BASE_URL = "https://www.immodrie.be"
IMMO_DRIE_URL = f"{BASE_URL}/nl/te-koop/woningen"

SEEN_FILE = "seen_properties.json"


def get_page(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/139.0 Safari/537.36"
        )
    }

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    return BeautifulSoup(response.text, "html.parser")


def parse_property(text, url):

    property_data = {
        "url": url,
        "price": None,
        "bedrooms": None,
        "living_area": None,
        "ground_area": None,
        "city": None,
        "type": None,
        "id": None,
    }

    # Uniek ID
    match = re.search(r"/(\d+)$", url)

    if match:
        property_data["id"] = match.group(1)

    # Prijs
    match = re.search(r"€\s*([\d.]+)", text)

    if match:
        property_data["price"] = int(
            match.group(1).replace(".", "")
        )

    # Slaapkamers
    match = re.search(r"Slaapkamers\s*(\d+)", text)

    if match:
        property_data["bedrooms"] = int(match.group(1))

    # Leefruimte
    match = re.search(
        r"Leefruimte\s*([\d.]+)\s*m²",
        text
    )

    if match:
        property_data["living_area"] = int(
            match.group(1).replace(".", "")
        )

    # Grondoppervlakte
    match = re.search(
        r"Titles\.surface_ground\s*([\d.]+)\s*m²",
        text
    )

    if match:
        property_data["ground_area"] = int(
            match.group(1).replace(".", "")
        )

    # Postcode + gemeente
    match = re.search(
        r"(\d{4})\s+(.+?)\s+€",
        text
    )

    if match:
        property_data["city"] = match.group(2).strip()

    # Type
    type_text = text

    for word in [
        "Nieuw",
        "Te koop",
        "In optie",
        "Verkocht",
        "Video",
        "Virtueel"
    ]:
        type_text = type_text.replace(word, "")

    type_text = re.sub(
        r"\d{4}\s+.+?\s+€.*",
        "",
        type_text
    )

    property_data["type"] = type_text.strip()

    return property_data


def find_properties(soup):

    properties = []

    for link in soup.find_all("a", href=True):

        href = link["href"]

        if (
            "/huis-te-koop-in-" not in href
            and "/herenhuis-te-koop-in-" not in href
            and "/villa-te-koop-in-" not in href
            and "/gebouw-voor-gemengd-gebruik-te-koop-in-" not in href
        ):
            continue

        url = urljoin(BASE_URL, href)

        text = link.get_text(" ", strip=True)

        if not text:
            continue

        property_data = parse_property(text, url)

        if property_data["id"]:
            properties.append(property_data)

    return properties


def scan_immo_drie():

    print("Immo Drie controleren...")

    all_properties = {}

    for page_number in range(1, 21):

        if page_number == 1:
            url = IMMO_DRIE_URL
        else:
            url = f"{IMMO_DRIE_URL}/pagina-{page_number}"

        print(f"Pagina {page_number} controleren...")

        soup = get_page(url)

        properties = find_properties(soup)

        print(f"  {len(properties)} woningen gevonden.")

        if not properties:
            print("Geen woningen meer gevonden.")
            break

        for property_data in properties:
            all_properties[property_data["id"]] = property_data

    properties = list(all_properties.values())

    print()
    print(f"TOTAAL: {len(properties)} unieke woningen gevonden.")

    return properties


def load_seen():

    if not os.path.exists(SEEN_FILE):
        return set()

    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        return set(data)

    except Exception:
        return set()


def save_seen(seen):

    with open(SEEN_FILE, "w", encoding="utf-8") as file:
        json.dump(
            sorted(list(seen)),
            file,
            indent=2
        )


def send_telegram(property_data):

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("Telegram gegevens ontbreken.")
        return

    price = property_data["price"]

    if price:
        price_text = f"€{price:,.0f}".replace(",", ".")
    else:
        price_text = "Prijs onbekend"

    message = (
        "🚨 NIEUWE WONING\n\n"
        f"🏠 {property_data['type']}\n"
        f"📍 {property_data['city']}\n\n"
        f"💰 {price_text}\n"
        f"🛏️ {property_data['bedrooms'] or 'Onbekend'} slaapkamers\n"
        f"📐 {property_data['living_area'] or 'Onbekend'} m² leefruimte\n"
        f"🌳 {property_data['ground_area'] or 'Onbekend'} m² grond\n\n"
        "🏢 Immo Drie\n\n"
        f"👉 {property_data['url']}"
    )

    telegram_url = (
        f"https://api.telegram.org/bot{token}/sendMessage"
    )

    response = requests.post(
        telegram_url,
        data={
            "chat_id": chat_id,
            "text": message,
        },
        timeout=30
    )

    response.raise_for_status()

    print(
        f"Telegrammelding verstuurd voor "
        f"{property_data['id']}"
    )


def process_properties(properties):

    seen = load_seen()

    print(f"{len(seen)} woningen reeds gekend.")

    # Eerste keer = bestaande woningen initialiseren
    if not seen:

        print(
            "Eerste scan: bestaande woningen worden "
            "opgeslagen zonder Telegrammeldingen."
        )

        for property_data in properties:
            seen.add(property_data["id"])

        save_seen(seen)

        print(
            f"{len(properties)} woningen opgeslagen."
        )

        return

    # Nieuwe woningen zoeken
    new_properties = []

    for property_data in properties:

        property_id = property_data["id"]

        if property_id not in seen:
            new_properties.append(property_data)

    print(
        f"{len(new_properties)} nieuwe woningen gevonden."
    )

    # Nieuwe woningen melden
    for property_data in new_properties:

        send_telegram(property_data)

        seen.add(property_data["id"])

    # Nieuwe database opslaan
    save_seen(seen)


if __name__ == "__main__":

    print("Vastgoed scanner gestart!")

    properties = scan_immo_drie()

    process_properties(properties)
