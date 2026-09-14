import requests
from bs4 import BeautifulSoup


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

    links = soup.find_all("a", href=True)

    print(f"Aantal links gevonden: {len(links)}")

    for link in links:

        href = link["href"]

        if "immodrie.be" not in href:
            if href.startswith("/"):
                href = "https://www.immodrie.be" + href
            else:
                continue

        text = link.get_text(" ", strip=True)

        if text:
            print(
                f"\n{text[:200]}"
                f"\n{href}"
            )


if __name__ == "__main__":

    print("Vastgoed scanner gestart!")

    scan_immo_drie()
