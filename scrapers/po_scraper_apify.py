"""
PropertyOnion scraper using Apify Web Scraper actor.

Last-resort scraper — uses residential proxies for bot detection bypass.

Usage:
    from scrapers.po_scraper_apify import scrape_via_apify
    results = scrape_via_apify("https://propertyonion.com")
"""

import os
import time

import httpx

APIFY_API_TOKEN = os.environ.get("APIFY_API_TOKEN", "")
APIFY_BASE = "https://api.apify.com/v2"


def scrape_via_apify(county_url: str) -> dict:
    """Use Apify Web Scraper actor to handle Angular SPA.

    Apify uses residential proxies — no bot detection.

    Args:
        county_url: Base PropertyOnion URL

    Returns:
        list of result dicts from Apify dataset
    """
    resp = httpx.post(
        f"{APIFY_BASE}/acts/apify~web-scraper/runs",
        headers={"Authorization": f"Bearer {APIFY_API_TOKEN}"},
        json={
            "startUrls": [{"url": "https://propertyonion.com/login"}],
            "pseudoUrls": [
                {"purl": "https://propertyonion.com/property_search/[.*]"}
            ],
            "pageFunction": """
async function pageFunction(context) {
    const { page, request } = context;

    if (request.url.includes('/login')) {
        await page.waitForTimeout(3000);
        await page.type(
            'input[type="email"]',
            process.env.PROPERTYONION_EMAIL,
            {delay: 50}
        );
        await page.type(
            'input[type="password"]',
            process.env.PROPERTYONION_PASSWORD,
            {delay: 50}
        );
        await page.click('button[type="submit"]');
        await page.waitForNavigation({waitUntil: 'networkidle2'});
        return { logged_in: true };
    }

    await page.waitForTimeout(4000);
    const listings = await page.$$eval(
        '.property-card, .listing-card',
        cards => cards.map(c => ({
            text: c.innerText.substring(0, 300),
            id: c.dataset.case || c.dataset.id || ''
        }))
    );
    return { url: request.url, count: listings.length, listings };
}
""",
            "proxyConfiguration": {
                "useApifyProxy": True,
                "apifyProxyGroups": ["RESIDENTIAL"],
            },
        },
        timeout=30,
    )

    run_id = resp.json()["data"]["id"]
    print(f"Apify run started: {run_id}")

    # Poll for completion
    status = "RUNNING"
    for _ in range(60):
        status_resp = httpx.get(
            f"{APIFY_BASE}/acts/apify~web-scraper/runs/{run_id}",
            headers={"Authorization": f"Bearer {APIFY_API_TOKEN}"},
        )
        status = status_resp.json()["data"]["status"]

        print(f"  Apify status: {status}")
        if status in ["SUCCEEDED", "FAILED", "ABORTED"]:
            break
        time.sleep(15)

    if status != "SUCCEEDED":
        raise RuntimeError(
            f"Apify run {run_id} ended with status: {status}"
        )

    # Get results
    results = httpx.get(
        f"{APIFY_BASE}/acts/apify~web-scraper/runs/{run_id}/dataset/items",
        headers={"Authorization": f"Bearer {APIFY_API_TOKEN}"},
    ).json()

    return results
