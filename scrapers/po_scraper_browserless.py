"""
PropertyOnion scraper using Browserless CDP.

Fallback scraper — runs real Chrome via CDP at chrome.browserless.io.
Used when Playwright is blocked by bot detection.

Usage:
    from scrapers.po_scraper_browserless import scrape_propertyonion_via_browserless
    result = scrape_propertyonion_via_browserless("/property_search/Brevard-County")
"""

import os
import json

import httpx

BROWSERLESS_API_KEY = os.environ.get("BROWSERLESS_API_KEY", "")
BROWSERLESS_URL = f"https://chrome.browserless.io/function?token={BROWSERLESS_API_KEY}"


def scrape_propertyonion_via_browserless(county_path: str) -> dict:
    """Use Browserless to scrape PropertyOnion with full browser execution.

    Sends a JavaScript function that runs inside a real Chrome instance.
    Password is passed via process.env to avoid embedding in JS string.

    Args:
        county_path: e.g. "/property_search/Brevard-County"

    Returns:
        dict with url, listing_count, listings[]
    """
    email = os.environ.get("PROPERTYONION_EMAIL", "")

    js_function = f"""
module.exports = async ({{ page }}) => {{
    // Set realistic user agent
    await page.setUserAgent(
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    );

    // Login
    await page.goto('https://propertyonion.com/login', {{
        waitUntil: 'networkidle2',
        timeout: 30000
    }});

    await page.waitForTimeout(3000); // Angular hydration

    // Find and fill email
    await page.waitForSelector(
        'input[type="email"], input[name="email"], input[formcontrolname="email"]'
    );
    const emailSel = await page.$('input[type="email"]') ||
                     await page.$('input[name="email"]') ||
                     await page.$('input[formcontrolname="email"]');

    await emailSel.click({{ clickCount: 3 }});
    await emailSel.type('{email}', {{ delay: 50 }});

    // Find and fill password
    const pwSel = await page.$('input[type="password"]') ||
                  await page.$('input[name="password"]');
    await pwSel.click({{ clickCount: 3 }});
    await pwSel.type(process.env.PROPERTYONION_PASSWORD, {{ delay: 50 }});

    // Submit
    const submitBtn = await page.$('button[type="submit"]') ||
                      await page.$('button:contains("Login")');
    await submitBtn.click();

    await page.waitForNavigation({{ waitUntil: 'networkidle2', timeout: 15000 }});
    await page.waitForTimeout(2000);

    const loginUrl = page.url();
    const loginOk = !loginUrl.includes('/login') && !loginUrl.includes('/signin');

    if (!loginOk) {{
        return {{ error: 'Login failed', url: loginUrl }};
    }}

    // Navigate to county page
    await page.goto('https://propertyonion.com{county_path}', {{
        waitUntil: 'networkidle2',
        timeout: 30000
    }});
    await page.waitForTimeout(4000);

    // Extract all listing data from DOM
    const listings = await page.evaluate(() => {{
        const cards = document.querySelectorAll(
            '.property-card, .listing-card, .auction-item, [data-property]'
        );

        return Array.from(cards).map(card => ({{
            identifier: card.dataset.case || card.dataset.id ||
                        card.dataset.caseNumber || '',
            address: card.querySelector(
                '.address, .property-address, h3, h4'
            )?.innerText || '',
            sale_date: card.querySelector(
                '.date, .auction-date, [class*="date"]'
            )?.innerText || '',
            judgment_amount: card.querySelector(
                '[class*="judgment"], [class*="amount"]'
            )?.innerText || '',
            opening_bid: card.querySelector(
                '[class*="bid"], [class*="opening"]'
            )?.innerText || '',
            assessed_value: card.querySelector(
                '[class*="assessed"]'
            )?.innerText || '',
            plaintiff: card.querySelector(
                '[class*="plaintiff"]'
            )?.innerText || '',
            property_type: card.querySelector(
                '[class*="type"]'
            )?.innerText || '',
            photo_url: card.querySelector('img')?.src || '',
            raw_text: card.innerText.substring(0, 500)
        }}));
    }});

    return {{
        url: page.url(),
        listing_count: listings.length,
        listings: listings
    }};
}};
"""

    resp = httpx.post(
        BROWSERLESS_URL,
        headers={"Content-Type": "application/javascript"},
        content=js_function,
        timeout=120,
    )

    if resp.status_code != 200:
        raise RuntimeError(
            f"Browserless error {resp.status_code}: {resp.text[:200]}"
        )

    return resp.json()
