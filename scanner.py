import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


IMMO_DRIE_URL = "https://www.immodrie.be/nl/te-koop/woningen"


def get_page(url):
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

    return BeautifulSoup(
        response.text,
        "html.parser"
    )


def scan_immo_drie():

    print("Immo Drie controleren...")

    soup = get_page(IMMO_DRIE_URL)

    properties = []

    for link in soup.find_all("a", href=True):

        href = link["href"]

        # Alleen echte vastgoedpagina's
        if "/huis-te-koop-in-" not in href \
                and "/herenhuis-te-koop-in-" not in href \
                and "/villa-te-koop-in-" not in href \
                and "/gebouw-voor-gemengd-gebruik-te-koop-in-" not in href:

            continue

        url = urljoin(
            "https://www.immodrie.be",
            href
        )

        text = link.get_text(
            " ",
            strip=True
        )

        if not text:
            continue

        properties.append({
            "url": url,
            "text": text
        })


    # Dubbele links verwijderen
    unique_properties = {}

    for property in properties:
        unique_properties[property["url"]] = property


    properties = list(
        unique_properties.values()
    )


    print(
        f"{len(properties)} woningen gevonden."
    )


    for property in properties:

        print("\n----------------------------")

        print(property["text"])

        print(property["url"])


    return properties


if __name__ == "__main__":

    print("Vastgoed scanner gestart!")

    scan_immo_drie()
