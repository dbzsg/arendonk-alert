import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re

IMMO_DRIE_URL = "https://www.immodrie.be/nl/te-koop/woningen"


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

    # Uniek woning-ID uit de URL
    match = re.search(r"/(\d+)$", url)
    if match:
        property_data["id"] = match.group(1)

    # Prijs
    match = re.search(r"€\s*([\d.]+)", text)
    if match:
        property_data["price"] = int(match.group(1).replace(".", ""))

    # Slaapkamers
    match = re.search(r"Slaapkamers\s*(\d+)", text)
    if match:
        property_data["bedrooms"] = int(match.group(1))

    # Leefruimte
    match = re.search(r"Leefruimte\s*([\d.]+)\s*m²", text)
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

    # Type woning
    type_text = text

    # Status verwijderen
    for word in ["Nieuw", "Te koop", "In optie", "Verkocht"]:
        type_text = type_text.replace(word, "")

    # Extra labels verwijderen
    for word in ["Video", "Virtueel"]:
        type_text = type_text.replace(word, "")

    # Postcode + gemeente + alles erna verwijderen
    type_text = re.sub(
        r"\d{4}\s+.+?\s+€.*",
        "",
        type_text
    )

    property_data["type"] = type_text.strip()

    return property_data


def scan_immo_drie():

    print("Immo Drie controleren...")

    soup = get_page(IMMO_DRIE_URL)

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

        url = urljoin(
            "https://www.immodrie.be",
            href
        )

        text = link.get_text(" ", strip=True)

        if not text:
            continue

        property_data = parse_property(text, url)

        properties.append(property_data)

    # Dubbele URL's verwijderen
    unique_properties = {}

    for property_data in properties:
        unique_properties[property_data["url"]] = property_data

    properties = list(unique_properties.values())

    print(f"{len(properties)} woningen gevonden.")

    for property_data in properties:

        print("\n----------------------------")

        print("ID:", property_data["id"])
        print("Type:", property_data["type"])
        print("Plaats:", property_data["city"])
        print("Prijs:", property_data["price"])
        print("Slaapkamers:", property_data["bedrooms"])
        print("Leefruimte:", property_data["living_area"])
        print("Grond:", property_data["ground_area"])
        print("URL:", property_data["url"])

    return properties


if __name__ == "__main__":

    print("Vastgoed scanner gestart!")

    scan_immo_drie()
