"""
PropertyOnion scraper using Playwright (sync API).

Primary scraper for Angular SPA — waits for network idle + DOM stability
before interacting with login form. Firecrawl failed because it fires events
before Angular hydrates the DOM.

Usage:
    from scrapers.po_scraper_playwright import run_playwright_scrape
    data = run_playwright_scrape()  # {county: {foreclosure: {date: [listings]}, ...}}
"""

import os
import re
import time

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

PROPERTYONION_BASE = "https://propertyonion.com"

COUNTY_PATHS = {
    "brevard":      "/property_search/Brevard-County",
    "hillsborough": "/property_search/Hillsborough-County",
    "orange":       "/property_search/Orange-County",
    "polk":         "/property_search/Polk-County",
    "palm_beach":   "/property_search/Palm-Beach-County",
}


def login_propertyonion(page) -> bool:
    """Login to PropertyOnion using Playwright.

    Handles Angular SPA hydration delays properly.
    Returns True if login successful.
    """
    print("Navigating to PropertyOnion login...")
    page.goto(f"{PROPERTYONION_BASE}/login", wait_until="networkidle",
              timeout=60000)

    # Wait for Angular to fully hydrate the login form
    page.wait_for_load_state("networkidle")
    time.sleep(3)  # extra buffer for Angular initialization

    # Debug: log page state
    print(f"  Page URL: {page.url}")
    print(f"  Page title: {page.title()}")
    # Log all input fields on the page for debugging
    try:
        inputs_info = page.evaluate("""
            Array.from(document.querySelectorAll('input')).map(inp => ({
                type: inp.type,
                name: inp.name,
                placeholder: inp.placeholder,
                id: inp.id,
                visible: inp.offsetParent !== null,
                attrs: Array.from(inp.attributes).map(a => a.name).join(',')
            }))
        """)
        print(f"  Input fields found: {len(inputs_info)}")
        for inp in inputs_info[:6]:
            print(f"    type={inp['type']} name={inp['name']} "
                  f"placeholder={inp['placeholder']} visible={inp['visible']} "
                  f"attrs=[{inp['attrs']}]")
    except Exception as e:
        print(f"  Input inspection failed: {str(e)[:100]}")

    # PrimeNG/Angular forms: use fill() which handles overlays and
    # dispatches proper input events. Use .first to disambiguate when
    # multiple elements match (PrimeNG renders duplicate inputs).
    email_selectors = [
        "input[type='email']",
        "input[name='email']",
        "input[formcontrolname='email']",  # Angular reactive forms
        "input[pinputtext][placeholder*='email' i]",  # PrimeNG
        "input[placeholder*='email' i]",
        "#email",
    ]

    email_filled = False
    for selector in email_selectors:
        try:
            loc = page.locator(selector).first
            loc.wait_for(timeout=3000, state="visible")
            print(f"  Email field found: {selector}")
            # fill() dispatches input+change events — works with Angular
            loc.fill(os.environ.get("PROPERTYONION_EMAIL", ""))
            email_filled = True
            print("  Email filled successfully")
            break
        except (PlaywrightTimeout, Exception) as e:
            print(f"  Selector {selector}: {str(e)[:80]}")
            continue

    if not email_filled:
        # Last resort: JS injection
        print("  Trying JS injection for email field...")
        email_val = os.environ.get("PROPERTYONION_EMAIL", "")
        try:
            page.evaluate(f"""
                const inputs = document.querySelectorAll('input');
                for (const inp of inputs) {{
                    const ph = (inp.placeholder || '').toLowerCase();
                    const nm = (inp.name || '').toLowerCase();
                    const tp = (inp.type || '').toLowerCase();
                    if (ph.includes('email') || nm.includes('email') || tp === 'email') {{
                        inp.value = '{email_val}';
                        inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                        break;
                    }}
                }}
            """)
            email_filled = True
            print("  Email filled via JS injection")
        except Exception as js_err:
            print(f"  JS injection failed: {str(js_err)[:100]}")

    if not email_filled:
        print("  ERROR: Email field not found with any selector")
        print("  Page title:", page.title())
        print("  Page URL:", page.url)
        page.screenshot(path="/tmp/po_login_debug.png")
        print("  Debug screenshot saved to /tmp/po_login_debug.png")
        return False

    time.sleep(0.5)

    # Password field — same approach: fill() + .first
    password_selectors = [
        "input[type='password']",
        "input[name='password']",
        "input[formcontrolname='password']",
        "p-password input",  # PrimeNG password component
        "input[placeholder*='password' i]",
        "#password",
    ]

    password_filled = False
    for selector in password_selectors:
        try:
            loc = page.locator(selector).first
            loc.wait_for(timeout=2000, state="visible")
            print(f"  Password field found: {selector}")
            loc.fill(os.environ.get("PROPERTYONION_PASSWORD", ""))
            password_filled = True
            print("  Password filled successfully")
            break
        except (PlaywrightTimeout, Exception) as e:
            print(f"  Selector {selector}: {str(e)[:80]}")
            continue

    if not password_filled:
        # JS injection fallback for password
        print("  Trying JS injection for password field...")
        pw_val = os.environ.get("PROPERTYONION_PASSWORD", "")
        try:
            page.evaluate(f"""
                const inputs = document.querySelectorAll('input');
                for (const inp of inputs) {{
                    if (inp.type === 'password' ||
                        (inp.name || '').toLowerCase().includes('password') ||
                        (inp.placeholder || '').toLowerCase().includes('password')) {{
                        inp.value = '{pw_val}';
                        inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                        break;
                    }}
                }}
            """)
            password_filled = True
            print("  Password filled via JS injection")
        except Exception as js_err:
            print(f"  JS injection failed: {str(js_err)[:100]}")

    if not password_filled:
        print("  ERROR: Password field not found")
        page.screenshot(path="/tmp/po_login_debug.png")
        return False

    time.sleep(0.5)

    # Submit — try button selectors with force=True for PrimeNG overlays
    submit_selectors = [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Login')",
        "button:has-text('Sign In')",
        "button:has-text('Log In')",
        ".login-btn",
        "p-button button",  # PrimeNG button
        ".submit-btn",
    ]

    submitted = False
    for selector in submit_selectors:
        try:
            loc = page.locator(selector).first
            loc.click(timeout=3000, force=True)
            submitted = True
            print(f"  Submit clicked: {selector}")
            break
        except (PlaywrightTimeout, Exception):
            continue

    if not submitted:
        # Try pressing Enter
        page.keyboard.press("Enter")
        submitted = True
        print("  Submit via Enter key")

    # Wait for navigation after login
    page.wait_for_load_state("networkidle")
    time.sleep(3)

    # Verify login succeeded
    current_url = page.url
    content = page.content().lower()
    success_signals = [
        "logout", "sign out", "my account", "dashboard",
        "premium", "welcome", "profile", "my profile",
    ]

    if any(s in content for s in success_signals):
        print(f"  LOGIN SUCCESS — URL: {current_url}")
        return True
    elif "login" in current_url or "signin" in current_url:
        print(f"  LOGIN FAILED — still on login page: {current_url}")
        print("  Possible wrong credentials or CAPTCHA")
        page.screenshot(path="/tmp/po_login_failed.png")
        return False
    else:
        # Redirected away from login — likely success
        print(f"  LOGIN SUCCESS (redirect) — URL: {current_url}")
        return True


def scrape_county_listings(page, county: str) -> dict:
    """Scrape all listings for a county from PropertyOnion.

    Returns {sale_type: {date: [listings]}}
    """
    url = f"{PROPERTYONION_BASE}{COUNTY_PATHS[county]}"
    print(f"\nScraping {county.upper()}: {url}")

    page.goto(url, wait_until="networkidle")
    page.wait_for_load_state("networkidle")
    time.sleep(3)  # Angular rendering buffer

    county_data = {"foreclosure": {}, "tax_deed": {}}
    page_num = 1

    while True:
        print(f"  Parsing page {page_num}...")

        # Wait for property cards to appear
        card_selectors = [
            ".property-card",
            ".listing-card",
            ".auction-item",
            ".property-listing",
            "[data-property]",
            ".card",
            "tr.property-row",
        ]

        cards_found = False
        listings = []
        for selector in card_selectors:
            count = page.locator(selector).count()
            if count > 0:
                print(f"  Found {count} cards with selector: {selector}")
                cards_found = True
                listings = parse_cards(page, selector, county)
                break

        if not cards_found:
            print(f"  No cards found. Page title: {page.title()}")
            print(f"  Page URL: {page.url}")
            text_content = page.inner_text("body")
            print(f"  Page text preview (first 500 chars):")
            print(text_content[:500])
            break

        # Add to county_data
        for listing in listings:
            if county == "orange" and is_timeshare(listing):
                continue
            sale_type = listing.get("sale_type", "foreclosure")
            sale_date = listing.get("sale_date", "unknown")
            if sale_date not in county_data[sale_type]:
                county_data[sale_type][sale_date] = []
            county_data[sale_type][sale_date].append(listing)

        # Check for next page
        next_selectors = [
            "a:has-text('Next')",
            "button:has-text('Next')",
            ".pagination-next",
            "[aria-label='Next page']",
            "a[rel='next']",
        ]

        has_next = False
        for selector in next_selectors:
            try:
                next_btn = page.locator(selector)
                if next_btn.count() > 0 and next_btn.is_enabled():
                    next_btn.click()
                    page.wait_for_load_state("networkidle")
                    time.sleep(2)
                    has_next = True
                    page_num += 1
                    break
            except Exception:
                continue

        if not has_next:
            print(f"  No more pages for {county}")
            break

    fc = sum(len(v) for v in county_data["foreclosure"].values())
    td = sum(len(v) for v in county_data["tax_deed"].values())
    print(f"  TOTAL: {fc} foreclosure | {td} tax deed")
    return county_data


def parse_cards(page, selector: str, county: str) -> list:
    """Parse property cards into listing dicts."""
    listings = []
    cards = page.locator(selector).all()

    for i, card in enumerate(cards):
        try:
            text = card.inner_text()

            # Log first card structure for debugging
            if i == 0:
                print(f"  First card text preview: {text[:300]}")
                html = card.inner_html()
                print(f"  First card HTML preview: {html[:500]}")

            listing = extract_listing_fields(card, text, county)
            if listing:
                listings.append(listing)
        except Exception as e:
            print(f"  Card {i} parse error: {str(e)[:100]}")

    return listings


def extract_listing_fields(card, text: str, county: str) -> dict:
    """Extract all PropertyOnion fields from a single property card."""
    listing = {"county": county}

    # Sale type detection
    text_lower = text.lower()
    if "tax deed" in text_lower or "taxdeed" in text_lower:
        listing["sale_type"] = "tax_deed"
    else:
        listing["sale_type"] = "foreclosure"

    # Try data attributes first (most reliable)
    for attr in ["data-case", "data-id", "data-case-number", "data-cert"]:
        try:
            val = card.get_attribute(attr)
            if val:
                listing["identifier"] = val
                break
        except Exception:
            pass

    # Parse dates
    date_pattern = r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b'
    date_match = re.search(date_pattern, text)
    if date_match:
        listing["sale_date"] = date_match.group(1)

    # Parse dollar amounts
    money_pattern = r'\$[\d,]+(?:\.\d{2})?'
    amounts = re.findall(money_pattern, text)
    amounts_clean = [
        float(a.replace('$', '').replace(',', ''))
        for a in amounts
    ]

    if listing["sale_type"] == "foreclosure" and amounts_clean:
        listing["judgment_amount"] = amounts_clean[0]
    elif listing["sale_type"] == "tax_deed" and amounts_clean:
        listing["opening_bid"] = amounts_clean[0]

    # Photo URL
    try:
        img = card.locator("img").first
        if img.count() > 0:
            listing["photo_url"] = img.get_attribute("src")
    except Exception:
        pass

    # Address
    try:
        addr_selectors = [".address", ".property-address", "h3", "h4", ".title"]
        for sel in addr_selectors:
            addr_el = card.locator(sel).first
            if addr_el.count() > 0:
                listing["address"] = addr_el.inner_text().strip()
                break
    except Exception:
        pass

    return listing if listing.get("identifier") or listing.get("address") else None


def is_timeshare(listing: dict) -> bool:
    """Check if listing is a timeshare (excluded for Orange County)."""
    excluded = ["timeshare", "time share", "interval", "vacation ownership"]
    fields = [
        str(listing.get(f, "")).lower()
        for f in ["property_type", "address", "plaintiff"]
    ]
    return any(ex in field for field in fields for ex in excluded)


def run_playwright_scrape() -> dict:
    """Main entry point — login and scrape all 5 counties.

    Returns: {county: {foreclosure: {date: [listings]}, tax_deed: {date: [listings]}}}
    """
    all_data = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )

        page = context.new_page()

        # Login with retries
        success = False
        for attempt in range(3):
            try:
                success = login_propertyonion(page)
                if success:
                    break
                print(f"Login attempt {attempt + 1} failed — retrying...")
                time.sleep(5)
            except Exception as e:
                print(f"Login attempt {attempt + 1} error: {str(e)[:200]}")
                time.sleep(5)

        if not success:
            browser.close()
            raise RuntimeError(
                "PropertyOnion login failed after 3 attempts.\n"
                "Credentials are in GitHub Secrets: "
                "PROPERTYONION_EMAIL, PROPERTYONION_PASSWORD\n"
                "Check /tmp/po_login_failed.png for debug screenshot.\n"
                "Try Approach 2 (Browserless) if Playwright is also blocked."
            )

        # Scrape all counties
        for county in COUNTY_PATHS:
            try:
                all_data[county] = scrape_county_listings(page, county)
                time.sleep(5)  # polite delay between counties
            except Exception as e:
                print(f"ERROR scraping {county}: {str(e)[:200]}")
                all_data[county] = {"foreclosure": {}, "tax_deed": {}}

        browser.close()

    return all_data
