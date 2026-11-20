"""Capture real screenshots of the running app with headless Chromium.

Run with the server already listening on 127.0.0.1:8000:

    python scripts/shots.py

Writes to docs/screenshots/. Fails loudly if the page does not render, so a
screenshot can never be a blank white rectangle that nobody checked.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
EMAIL = "abraz@example.com"
PASSWORD = "bharti-demo-2026"

console_errors: list[str] = []
failed_requests: list[str] = []


def sign_in(page) -> None:
    page.goto(BASE, wait_until="networkidle")
    page.fill('#login-form input[name="email"]', EMAIL)
    page.fill('#login-form input[name="password"]', PASSWORD)
    page.click('#login-form button[type="submit"]')
    page.wait_for_selector("#app:not(.is-hidden)", timeout=15000)
    page.wait_for_selector(".job-item", timeout=15000)
    # The app auto-selects the newest job, which may have no candidates yet.
    # Pick the first job that actually has some, so the screenshot shows the
    # product doing its job rather than an empty state.
    for item in page.locator(".job-item").all():
        if "0 candidates" not in (item.inner_text() or ""):
            item.click()
            break
    page.wait_for_selector(".cand", timeout=15000)
    page.wait_for_timeout(900)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})

        page.on(
            "console",
            lambda m: console_errors.append(m.text) if m.type == "error" else None,
        )
        page.on(
            "requestfailed",
            lambda r: failed_requests.append(f"{r.method} {r.url}"),
        )

        # --- 01 dashboard --------------------------------------------------
        sign_in(page)
        page.screenshot(path=str(OUT / "01-dashboard.png"), full_page=True)
        print("01-dashboard.png")

        # --- 02 score breakdown --------------------------------------------
        page.locator(".cand").first.click()
        page.wait_for_selector("#detail-modal:not(.is-hidden)", timeout=10000)
        page.wait_for_timeout(700)
        page.screenshot(path=str(OUT / "02-breakdown.png"), full_page=True)
        print("02-breakdown.png")
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)

        # --- 03 add candidate modal ----------------------------------------
        page.click("#add-candidate-btn")
        page.wait_for_selector("#candidate-modal:not(.is-hidden)", timeout=10000)
        page.wait_for_timeout(600)
        page.screenshot(path=str(OUT / "03-add-candidate.png"), full_page=True)
        print("03-add-candidate.png")
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)

        # --- 04 mobile -----------------------------------------------------
        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        sign_in(mobile)
        mobile.screenshot(path=str(OUT / "04-mobile.png"), full_page=True)
        print("04-mobile.png")

        overflow = mobile.evaluate(
            "() => document.documentElement.scrollWidth"
            " - document.documentElement.clientWidth"
        )
        print(f"mobile horizontal overflow: {overflow}px")

        browser.close()

    if console_errors:
        print("\nCONSOLE ERRORS:", file=sys.stderr)
        for e in console_errors:
            print(f"  {e}", file=sys.stderr)
    if failed_requests:
        print("\nFAILED REQUESTS:", file=sys.stderr)
        for r in failed_requests:
            print(f"  {r}", file=sys.stderr)

    if console_errors or failed_requests:
        return 1
    if overflow > 0:
        print(f"\nFAIL: {overflow}px horizontal overflow at 390px", file=sys.stderr)
        return 1

    print("\nclean: no console errors, no failed requests, no overflow")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
