"""Developer helper: render the Mullins public-skate schedule and save its DOM.

Run when the page changes:
    python -m scraper.capture_mullins_fixture
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "https://mullinscenter.finnlyconnect.com/schedule/428"
OUT = Path(__file__).parent / "tests" / "fixtures" / "mullins.html"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(URL, wait_until="networkidle", timeout=60_000)
        try:
            page.wait_for_selector("text=Public Skate", timeout=30_000)
        except Exception:
            pass
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(page.content())
        print(f"wrote {OUT}")
        browser.close()


if __name__ == "__main__":
    main()
