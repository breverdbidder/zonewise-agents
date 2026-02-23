"""
County Research Agent — ZoneWise.AI
====================================
LangGraph workflow implementing CrossBeam 3-mode research pattern:
  Mode 1: Discovery (WebSearch ≤30s) → validate portal URL
  Mode 2: Extraction (WebFetch ≤90s) → parse Municode → UPSERT zone_standards
  Mode 3: AgentQL/Modal Fallback → anti-scrape counties

Circuit breaker: 3 mode failures → INSERT insights table (ESCALATE)
Data contract: {districts_upserted, standards_upserted, uses_upserted, mode_used, errors[]}

Author: Claude AI (Architect) — 2026-02-23
Issue: breverdbidder/zonewise#12
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional, TypedDict

import httpx
from anthropic import AsyncAnthropic
from tenacity import retry, stop_after_attempt, wait_exponential

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("county_research_agent")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class CountyResearchState(TypedDict, total=False):
    """LangGraph state for county research workflow."""
    # Input
    county_name: str          # "Brevard"
    county_slug: str          # "brevard"
    co_no: int                # 5
    portal_type: str          # "municode" | "arcgis" | "pdf"
    anti_scrape: bool
    rate_limit_rpm: int
    municode_url: str
    gis_url: str

    # Runtime
    mode_used: int            # 1, 2, or 3
    failures: int
    current_mode: int
    portal_validated: bool
    raw_html: str
    extracted_data: Dict[str, Any]

    # Output
    districts_upserted: int
    standards_upserted: int
    uses_upserted: int
    errors: List[str]
    escalated: bool
    completed_at: str
    duration_seconds: float


# ---------------------------------------------------------------------------
# Supabase client (REST)
# ---------------------------------------------------------------------------

class SupabaseClient:
    """Lightweight async Supabase REST client."""

    def __init__(self, url: str, service_key: str):
        self.url = url.rstrip("/")
        self.headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    async def rpc(self, function_name: str, params: Dict) -> Any:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{self.url}/rest/v1/rpc/{function_name}",
                headers=self.headers,
                json=params,
            )
            r.raise_for_status()
            return r.json()

    async def select(self, table: str, params: str) -> List[Dict]:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{self.url}/rest/v1/{table}?{params}",
                headers=self.headers,
            )
            r.raise_for_status()
            return r.json()

    async def upsert(self, table: str, records: List[Dict], on_conflict: str = "") -> List[Dict]:
        headers = {**self.headers, "Prefer": "resolution=merge-duplicates,return=representation"}
        params = f"on_conflict={on_conflict}" if on_conflict else ""
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{self.url}/rest/v1/{table}{'?' + params if params else ''}",
                headers=headers,
                json=records,
            )
            r.raise_for_status()
            return r.json() if r.text else []

    async def insert(self, table: str, record: Dict) -> Dict:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{self.url}/rest/v1/{table}",
                headers=self.headers,
                json=record,
            )
            r.raise_for_status()
            return r.json()[0] if r.text else {}

    async def update(self, table: str, filter_param: str, data: Dict) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.patch(
                f"{self.url}/rest/v1/{table}?{filter_param}",
                headers=self.headers,
                json=data,
            )
            r.raise_for_status()


# ---------------------------------------------------------------------------
# Mode 1 — Discovery (WebSearch via Brave/SerpAPI or fallback DuckDuckGo)
# ---------------------------------------------------------------------------

async def mode1_discovery(state: CountyResearchState) -> CountyResearchState:
    """
    Mode 1: Search for county zoning portal URL.
    Timeout: 30 seconds.
    Uses: httpx + DuckDuckGo HTML search (no API key needed)
    """
    county = state["county_name"]
    logger.info(f"[Mode 1] Starting discovery for {county} County")
    start = time.time()

    queries = [
        f"{county} County Florida municode zoning ordinance",
        f"{county} County Florida GIS ArcGIS zoning map",
        f"{county} County Florida zoning code online",
    ]

    found_url: Optional[str] = None
    portal_type = state.get("portal_type", "municode")

    async with httpx.AsyncClient(
        timeout=28,
        headers={"User-Agent": "Mozilla/5.0 (compatible; ZoneWiseBot/1.0; +https://zonewise.ai/bot)"},
        follow_redirects=True,
    ) as client:
        for query in queries:
            if time.time() - start > 28:
                break
            try:
                # DuckDuckGo HTML search
                r = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                )
                html = r.text

                # Extract municode URLs
                municode_pattern = r'https://library\.municode\.com/fl/[^"&\s<>]+'
                matches = re.findall(municode_pattern, html)
                if matches:
                    found_url = matches[0]
                    portal_type = "municode"
                    logger.info(f"[Mode 1] Found Municode URL: {found_url}")
                    break

                # Extract ArcGIS URLs
                arcgis_pattern = r'https://[^"&\s<>]+gis[^"&\s<>]+\.arcgis\.com[^"&\s<>]+'
                matches = re.findall(arcgis_pattern, html, re.IGNORECASE)
                if matches:
                    found_url = matches[0]
                    portal_type = "arcgis"
                    logger.info(f"[Mode 1] Found ArcGIS URL: {found_url}")
                    break

            except Exception as e:
                logger.warning(f"[Mode 1] Query failed: {e}")
                state.setdefault("errors", []).append(f"mode1_query: {str(e)}")

    # Use existing URL from SKILL.md if not found
    if not found_url:
        found_url = state.get("municode_url") or state.get("gis_url")
        if found_url:
            logger.info(f"[Mode 1] Using SKILL.md URL: {found_url}")
        else:
            logger.warning(f"[Mode 1] No URL found for {county} County")

    elapsed = time.time() - start
    logger.info(f"[Mode 1] Completed in {elapsed:.1f}s")

    state["portal_validated"] = bool(found_url)
    state["mode_used"] = 1
    state["current_mode"] = 1

    if found_url and not state.get("municode_url"):
        state["municode_url"] = found_url
    if portal_type:
        state["portal_type"] = portal_type

    return state


# ---------------------------------------------------------------------------
# Mode 2 — Extraction (WebFetch + Claude API)
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """You are a zoning code parser for ZoneWise.AI — a Florida zoning intelligence platform.

Extract ALL zoning districts and their dimensional standards from this HTML content.

Return ONLY valid JSON in this exact structure:
{
  "districts": [
    {
      "code": "R-1",
      "name": "Single Family Residential",
      "category": "residential",
      "description": "Low-density single family"
    }
  ],
  "standards": [
    {
      "district_code": "R-1",
      "standard_type": "setback_front",
      "value": 25,
      "unit": "ft",
      "notes": ""
    }
  ],
  "uses": [
    {
      "district_code": "R-1",
      "use_name": "Single Family Dwelling",
      "permission_type": "permitted",
      "use_category": "residential"
    }
  ]
}

Standard types: setback_front, setback_side, setback_rear, max_height, min_lot_size, 
max_lot_coverage, max_far, min_unit_size, parking_spaces

Permission types: permitted, conditional, prohibited, special_exception

Categories: residential, commercial, industrial, agricultural, mixed_use, institutional, 
conservation, special

Extract as many records as possible. Return only JSON, no explanation."""


async def mode2_extraction(
    state: CountyResearchState,
    anthropic_client: AsyncAnthropic,
) -> CountyResearchState:
    """
    Mode 2: Fetch Municode HTML and extract zoning data via Claude API.
    Timeout: 90 seconds.
    """
    url = state.get("municode_url") or state.get("gis_url")
    if not url:
        logger.warning("[Mode 2] No URL available, skipping")
        state.setdefault("errors", []).append("mode2_no_url")
        return state

    county = state["county_name"]
    logger.info(f"[Mode 2] Fetching {url}")
    start = time.time()

    # Fetch HTML
    html_content = ""
    try:
        async with httpx.AsyncClient(
            timeout=45,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            },
            follow_redirects=True,
        ) as client:
            r = await client.get(url)
            html_content = r.text
            logger.info(f"[Mode 2] Fetched {len(html_content):,} chars in {time.time()-start:.1f}s")
    except Exception as e:
        logger.error(f"[Mode 2] Fetch failed: {e}")
        state.setdefault("errors", []).append(f"mode2_fetch: {str(e)}")
        return state

    if time.time() - start > 88:
        state.setdefault("errors", []).append("mode2_timeout_fetch")
        return state

    # Strip HTML tags for Claude
    clean_text = re.sub(r'<[^>]+>', ' ', html_content)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    # Limit to 80K chars to stay within context
    clean_text = clean_text[:80000]
    state["raw_html"] = clean_text

    # Extract with Claude
    try:
        response = await anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",  # Fast + cheap for extraction
            max_tokens=8000,
            system="You are a zoning code parser. Return only valid JSON.",
            messages=[
                {
                    "role": "user",
                    "content": f"{EXTRACTION_PROMPT}\n\n--- ZONING CODE CONTENT ({county} County, FL) ---\n{clean_text[:60000]}",
                }
            ],
        )
        raw = response.content[0].text.strip()

        # Clean JSON fences
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()

        extracted = json.loads(raw)
        state["extracted_data"] = extracted
        logger.info(
            f"[Mode 2] Extracted: {len(extracted.get('districts', []))} districts, "
            f"{len(extracted.get('standards', []))} standards, "
            f"{len(extracted.get('uses', []))} uses"
        )
    except json.JSONDecodeError as e:
        logger.error(f"[Mode 2] JSON parse error: {e}")
        state.setdefault("errors", []).append(f"mode2_json: {str(e)}")
    except Exception as e:
        logger.error(f"[Mode 2] Claude extraction error: {e}")
        state.setdefault("errors", []).append(f"mode2_claude: {str(e)}")

    state["mode_used"] = 2
    logger.info(f"[Mode 2] Completed in {time.time()-start:.1f}s")
    return state


# ---------------------------------------------------------------------------
# Mode 3 — AgentQL/Modal Fallback
# ---------------------------------------------------------------------------

async def mode3_agentql_fallback(
    state: CountyResearchState,
    agentql_api_key: str,
    modal_scraper_url: str,
) -> CountyResearchState:
    """
    Mode 3: AgentQL/Modal container for anti-scrape counties.
    Triggers Modal container with county config.
    """
    county = state["county_name"]
    county_slug = state["county_slug"]
    logger.info(f"[Mode 3] AgentQL fallback for {county} County (anti_scrape={state.get('anti_scrape')})")

    # Build Modal trigger payload
    payload = {
        "county_slug": county_slug,
        "co_no": state.get("co_no"),
        "portal_url": state.get("municode_url") or state.get("gis_url"),
        "anti_scrape": state.get("anti_scrape", False),
        "rate_limit_rpm": state.get("rate_limit_rpm", 10),
        "agentql_query": """{
  zoning_table {
    district_code
    district_name
    uses_permitted[]
    setback_front
    setback_side
    setback_rear
    max_height
  }
}""",
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{modal_scraper_url}/scrape-county",
                headers={
                    "Authorization": f"Bearer {agentql_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if r.status_code == 200:
                result = r.json()
                state["extracted_data"] = result.get("data", {})
                state["mode_used"] = 3
                logger.info(f"[Mode 3] Modal scrape succeeded: {result.get('records', 0)} records")
            else:
                state.setdefault("errors", []).append(
                    f"mode3_modal_http_{r.status_code}: {r.text[:200]}"
                )
                logger.error(f"[Mode 3] Modal returned {r.status_code}")
    except httpx.TimeoutException:
        state.setdefault("errors", []).append("mode3_modal_timeout")
        logger.error("[Mode 3] Modal timeout after 120s")
    except Exception as e:
        state.setdefault("errors", []).append(f"mode3_modal: {str(e)}")
        logger.error(f"[Mode 3] Modal error: {e}")

    return state


# ---------------------------------------------------------------------------
# Supabase persistence
# ---------------------------------------------------------------------------

async def persist_to_supabase(
    state: CountyResearchState,
    db: SupabaseClient,
) -> CountyResearchState:
    """
    Upsert extracted data to Supabase:
    - zoning_districts
    - zone_standards
    - permitted_uses
    """
    extracted = state.get("extracted_data", {})
    if not extracted:
        logger.warning("[Persist] No extracted data to persist")
        return state

    county = state["county_name"]
    county_slug = state["county_slug"]

    # Get jurisdiction IDs for this county
    try:
        jurisdictions = await db.select(
            "jurisdictions",
            f"county=ilike.%25{county}%25&select=id,name",
        )
    except Exception as e:
        state.setdefault("errors", []).append(f"persist_jurisdictions: {str(e)}")
        logger.error(f"[Persist] Failed to fetch jurisdictions: {e}")
        return state

    if not jurisdictions:
        logger.warning(f"[Persist] No jurisdictions found for {county} County")
        state.setdefault("errors", []).append("persist_no_jurisdictions")
        return state

    # Use first jurisdiction as primary (county-level)
    jurisdiction_id = jurisdictions[0]["id"]

    districts_upserted = 0
    standards_upserted = 0
    uses_upserted = 0

    # Upsert districts
    districts = extracted.get("districts", [])
    if districts:
        district_records = [
            {
                "jurisdiction_id": jurisdiction_id,
                "code": d["code"],
                "name": d.get("name", d["code"]),
                "category": d.get("category", "other"),
                "description": d.get("description", ""),
            }
            for d in districts
        ]
        try:
            result = await db.upsert(
                "zoning_districts",
                district_records,
                on_conflict="jurisdiction_id,code",
            )
            districts_upserted = len(result) if result else len(district_records)
            logger.info(f"[Persist] {districts_upserted} districts upserted")
        except Exception as e:
            state.setdefault("errors", []).append(f"persist_districts: {str(e)}")
            logger.error(f"[Persist] District upsert failed: {e}")

    # Fetch district IDs for standards/uses
    district_id_map: Dict[str, str] = {}
    if districts_upserted > 0:
        try:
            db_districts = await db.select(
                "zoning_districts",
                f"jurisdiction_id=eq.{jurisdiction_id}&select=id,code",
            )
            district_id_map = {d["code"]: d["id"] for d in db_districts}
        except Exception as e:
            logger.warning(f"[Persist] Could not fetch district IDs: {e}")

    # Upsert standards
    standards = extracted.get("standards", [])
    if standards and district_id_map:
        standard_records = []
        for s in standards:
            dist_id = district_id_map.get(s.get("district_code", ""))
            if dist_id:
                standard_records.append({
                    "zoning_district_id": dist_id,
                    "standard_type": s.get("standard_type", ""),
                    "value": s.get("value"),
                    "unit": s.get("unit", ""),
                    "notes": s.get("notes", ""),
                })
        if standard_records:
            try:
                result = await db.upsert(
                    "zone_standards",
                    standard_records,
                    on_conflict="zoning_district_id,standard_type",
                )
                standards_upserted = len(result) if result else len(standard_records)
                logger.info(f"[Persist] {standards_upserted} standards upserted")
            except Exception as e:
                state.setdefault("errors", []).append(f"persist_standards: {str(e)}")
                logger.error(f"[Persist] Standards upsert failed: {e}")

    # Upsert permitted uses
    uses = extracted.get("uses", [])
    if uses and district_id_map:
        use_records = []
        for u in uses:
            dist_id = district_id_map.get(u.get("district_code", ""))
            if dist_id:
                use_records.append({
                    "zoning_district_id": dist_id,
                    "use_name": u.get("use_name", ""),
                    "permission_type": u.get("permission_type", "permitted"),
                    "use_category": u.get("use_category", "other"),
                })
        if use_records:
            try:
                result = await db.upsert(
                    "permitted_uses",
                    use_records,
                    on_conflict="zoning_district_id,use_name",
                )
                uses_upserted = len(result) if result else len(use_records)
                logger.info(f"[Persist] {uses_upserted} uses upserted")
            except Exception as e:
                state.setdefault("errors", []).append(f"persist_uses: {str(e)}")
                logger.error(f"[Persist] Uses upsert failed: {e}")

    # Update skill_last_validated on jurisdictions
    try:
        await db.update(
            "jurisdictions",
            f"county=ilike.%25{county}%25",
            {"skill_last_validated": date.today().isoformat()},
        )
    except Exception as e:
        logger.warning(f"[Persist] skill_last_validated update failed: {e}")

    state["districts_upserted"] = districts_upserted
    state["standards_upserted"] = standards_upserted
    state["uses_upserted"] = uses_upserted

    return state


# ---------------------------------------------------------------------------
# Circuit breaker — escalate to Supabase insights
# ---------------------------------------------------------------------------

async def escalate_to_insights(
    state: CountyResearchState,
    db: SupabaseClient,
) -> CountyResearchState:
    """
    All 3 modes failed. Insert ESCALATE record into insights table.
    Marks data_completeness = -1 on jurisdiction.
    """
    county = state["county_name"]
    county_slug = state["county_slug"]
    errors = state.get("errors", [])

    logger.error(
        f"[CircuitBreaker] All modes failed for {county} County. Escalating. Errors: {errors}"
    )

    # Insert to insights
    try:
        await db.insert(
            "insights",
            {
                "type": "ESCALATE",
                "county": county_slug,
                "message": f"County Research Agent: All 3 modes failed for {county} County",
                "error": json.dumps(errors),
                "modes_attempted": [1, 2, 3],
                "action": f"Create Traycer GitHub Issue: [SKILL] Manual review {county} County portal",
                "created_at": datetime.utcnow().isoformat(),
            },
        )
        logger.info(f"[CircuitBreaker] Inserted ESCALATE insight for {county}")
    except Exception as e:
        logger.error(f"[CircuitBreaker] Failed to insert insight: {e}")

    # Mark jurisdiction data_completeness = -1
    try:
        await db.update(
            "jurisdictions",
            f"county=ilike.%25{county}%25",
            {"data_completeness": -1},
        )
    except Exception as e:
        logger.warning(f"[CircuitBreaker] data_completeness update failed: {e}")

    state["escalated"] = True
    return state


# ---------------------------------------------------------------------------
# Main LangGraph workflow
# ---------------------------------------------------------------------------

class CountyResearchAgent:
    """
    LangGraph-style county research agent.
    
    Implements CrossBeam 3-mode research pattern:
    Mode 1 (WebSearch) → Mode 2 (WebFetch+Claude) → Mode 3 (AgentQL/Modal)
    
    Usage:
        agent = CountyResearchAgent.from_env()
        result = await agent.run("Brevard", co_no=5, 
                                  portal_type="municode",
                                  anti_scrape=False,
                                  rate_limit_rpm=30)
    """

    def __init__(
        self,
        supabase_url: str,
        supabase_service_key: str,
        anthropic_api_key: str,
        agentql_api_key: str = "",
        modal_scraper_url: str = "https://zonewise-modal.modal.run",
    ):
        self.db = SupabaseClient(supabase_url, supabase_service_key)
        self.anthropic = AsyncAnthropic(api_key=anthropic_api_key)
        self.agentql_api_key = agentql_api_key
        self.modal_scraper_url = modal_scraper_url

    @classmethod
    def from_env(cls) -> "CountyResearchAgent":
        """Initialize from environment variables."""
        import os
        return cls(
            supabase_url=os.environ["SUPABASE_URL"],
            supabase_service_key=os.environ["SUPABASE_SERVICE_ROLE_KEY"],
            anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
            agentql_api_key=os.environ.get("AGENTQL_API_KEY", ""),
            modal_scraper_url=os.environ.get("MODAL_SCRAPER_URL", "https://zonewise-modal.modal.run"),
        )

    async def run(
        self,
        county_name: str,
        co_no: int,
        county_slug: str = "",
        portal_type: str = "municode",
        anti_scrape: bool = False,
        rate_limit_rpm: int = 30,
        municode_url: str = "",
        gis_url: str = "",
    ) -> Dict[str, Any]:
        """
        Run the county research workflow.
        
        Returns data contract:
        {
            districts_upserted: int,
            standards_upserted: int,
            uses_upserted: int,
            mode_used: int,
            errors: list[str],
            escalated: bool,
            duration_seconds: float
        }
        """
        start = time.time()

        if not county_slug:
            county_slug = re.sub(r"[^a-z0-9-]", "", county_name.lower().replace(" ", "-").replace(".", ""))

        state: CountyResearchState = {
            "county_name": county_name,
            "county_slug": county_slug,
            "co_no": co_no,
            "portal_type": portal_type,
            "anti_scrape": anti_scrape,
            "rate_limit_rpm": rate_limit_rpm,
            "municode_url": municode_url,
            "gis_url": gis_url,
            "failures": 0,
            "current_mode": 0,
            "portal_validated": False,
            "errors": [],
            "districts_upserted": 0,
            "standards_upserted": 0,
            "uses_upserted": 0,
            "escalated": False,
        }

        logger.info(f"County Research Agent: {county_name} County (co_no={co_no}, portal={portal_type}, anti_scrape={anti_scrape})")

        # ── Mode 1: Discovery ──────────────────────────────────────────────
        try:
            state = await asyncio.wait_for(
                mode1_discovery(state),
                timeout=32,
            )
        except asyncio.TimeoutError:
            state["failures"] += 1
            state.setdefault("errors", []).append("mode1_timeout")
            logger.error("[Mode 1] Timeout")
        except Exception as e:
            state["failures"] += 1
            state.setdefault("errors", []).append(f"mode1_exception: {str(e)}")
            logger.error(f"[Mode 1] Exception: {e}")

        # ── Mode 2: Extraction ─────────────────────────────────────────────
        try:
            state = await asyncio.wait_for(
                mode2_extraction(state, self.anthropic),
                timeout=95,
            )
        except asyncio.TimeoutError:
            state["failures"] += 1
            state.setdefault("errors", []).append("mode2_timeout")
            logger.error("[Mode 2] Timeout")
        except Exception as e:
            state["failures"] += 1
            state.setdefault("errors", []).append(f"mode2_exception: {str(e)}")
            logger.error(f"[Mode 2] Exception: {e}")

        # ── Mode 3: AgentQL/Modal (if no data yet OR anti_scrape) ──────────
        has_data = bool(state.get("extracted_data") and (
            state["extracted_data"].get("districts") or
            state["extracted_data"].get("standards")
        ))

        if not has_data or anti_scrape:
            logger.info(f"[Mode 3] Triggering: has_data={has_data}, anti_scrape={anti_scrape}")
            try:
                state = await asyncio.wait_for(
                    mode3_agentql_fallback(state, self.agentql_api_key, self.modal_scraper_url),
                    timeout=125,
                )
            except asyncio.TimeoutError:
                state["failures"] += 1
                state.setdefault("errors", []).append("mode3_timeout")
                logger.error("[Mode 3] Timeout")
            except Exception as e:
                state["failures"] += 1
                state.setdefault("errors", []).append(f"mode3_exception: {str(e)}")
                logger.error(f"[Mode 3] Exception: {e}")

        # ── Circuit Breaker ────────────────────────────────────────────────
        final_has_data = bool(state.get("extracted_data") and (
            state["extracted_data"].get("districts") or
            state["extracted_data"].get("standards")
        ))

        if not final_has_data:
            logger.warning(f"[CircuitBreaker] No data after all 3 modes. Failures: {state['failures']}")
            state = await escalate_to_insights(state, self.db)
        else:
            # ── Persist to Supabase ────────────────────────────────────────
            state = await persist_to_supabase(state, self.db)

        state["duration_seconds"] = round(time.time() - start, 2)
        state["completed_at"] = datetime.utcnow().isoformat()

        result = {
            "county": county_name,
            "co_no": co_no,
            "districts_upserted": state["districts_upserted"],
            "standards_upserted": state["standards_upserted"],
            "uses_upserted": state["uses_upserted"],
            "mode_used": state.get("mode_used", 0),
            "portal_validated": state.get("portal_validated", False),
            "errors": state.get("errors", []),
            "escalated": state.get("escalated", False),
            "duration_seconds": state["duration_seconds"],
            "completed_at": state["completed_at"],
        }

        logger.info(
            f"✅ {county_name} County done | "
            f"mode={result['mode_used']} | "
            f"districts={result['districts_upserted']} | "
            f"standards={result['standards_upserted']} | "
            f"uses={result['uses_upserted']} | "
            f"t={result['duration_seconds']}s"
        )
        return result


# ---------------------------------------------------------------------------
# Batch runner for nightly pipeline
# ---------------------------------------------------------------------------

async def run_batch(
    agent: CountyResearchAgent,
    counties: List[Dict[str, Any]],
    max_concurrent: int = 3,
) -> List[Dict[str, Any]]:
    """
    Run county research for a list of counties with concurrency control.
    
    Args:
        agent: CountyResearchAgent instance
        counties: List of county configs from Supabase/SKILL.md
        max_concurrent: Max simultaneous scrapes (default 3 — rate limit friendly)
    
    Returns:
        List of result dicts
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    results = []

    async def run_one(county_config: Dict) -> Dict:
        async with semaphore:
            return await agent.run(
                county_name=county_config["county_name"],
                co_no=county_config["co_no"],
                county_slug=county_config.get("county_slug", ""),
                portal_type=county_config.get("portal_type", "municode"),
                anti_scrape=county_config.get("anti_scrape", False),
                rate_limit_rpm=county_config.get("rate_limit_rpm", 30),
                municode_url=county_config.get("municode_url", ""),
                gis_url=county_config.get("gis_url", ""),
            )

    tasks = [run_one(c) for c in counties]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Convert exceptions to error dicts
    final = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            final.append({
                "county": counties[i].get("county_name", f"county_{i}"),
                "error": str(r),
                "escalated": True,
                "districts_upserted": 0,
                "standards_upserted": 0,
                "uses_upserted": 0,
            })
        else:
            final.append(r)

    return final


# ---------------------------------------------------------------------------
# FastAPI endpoint (integrates into zonewise-agents app)
# ---------------------------------------------------------------------------

def create_router(agent: CountyResearchAgent):
    """Create FastAPI router for county research endpoints."""
    from fastapi import APIRouter, BackgroundTasks, HTTPException
    from pydantic import BaseModel

    router = APIRouter(prefix="/county-research", tags=["County Research"])

    class CountyResearchRequest(BaseModel):
        county_name: str
        co_no: int
        county_slug: str = ""
        portal_type: str = "municode"
        anti_scrape: bool = False
        rate_limit_rpm: int = 30
        municode_url: str = ""
        gis_url: str = ""

    class BatchResearchRequest(BaseModel):
        counties: List[Dict[str, Any]]
        max_concurrent: int = 3

    @router.post("/run")
    async def run_county_research(req: CountyResearchRequest) -> Dict:
        """Run county research agent for a single county."""
        result = await agent.run(
            county_name=req.county_name,
            co_no=req.co_no,
            county_slug=req.county_slug,
            portal_type=req.portal_type,
            anti_scrape=req.anti_scrape,
            rate_limit_rpm=req.rate_limit_rpm,
            municode_url=req.municode_url,
            gis_url=req.gis_url,
        )
        return result

    @router.post("/batch")
    async def run_batch_research(req: BatchResearchRequest) -> Dict:
        """Run county research for multiple counties."""
        results = await run_batch(agent, req.counties, req.max_concurrent)
        total = len(results)
        succeeded = sum(1 for r in results if not r.get("escalated"))
        return {
            "total": total,
            "succeeded": succeeded,
            "failed": total - succeeded,
            "results": results,
        }

    @router.get("/status/{county_slug}")
    async def get_county_status(county_slug: str) -> Dict:
        """Get research status for a county from Supabase."""
        rows = await agent.db.select(
            "jurisdictions",
            f"county=ilike.%25{county_slug}%25&select=id,county,co_no,skill_file_path,skill_last_validated,data_completeness&limit=5",
        )
        return {"county_slug": county_slug, "jurisdictions": rows}

    return router


# ---------------------------------------------------------------------------
# CLI entrypoint (for testing / GitHub Actions)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import os

    parser = argparse.ArgumentParser(description="ZoneWise County Research Agent")
    parser.add_argument("--county", required=True, help="County name (e.g. Brevard)")
    parser.add_argument("--co-no", type=int, required=True, help="FDOR county number")
    parser.add_argument("--portal-type", default="municode", choices=["municode", "arcgis", "pdf"])
    parser.add_argument("--anti-scrape", action="store_true")
    parser.add_argument("--rate-limit", type=int, default=30)
    parser.add_argument("--municode-url", default="")
    parser.add_argument("--gis-url", default="")
    args = parser.parse_args()

    agent = CountyResearchAgent.from_env()
    result = asyncio.run(agent.run(
        county_name=args.county,
        co_no=args.co_no,
        portal_type=args.portal_type,
        anti_scrape=args.anti_scrape,
        rate_limit_rpm=args.rate_limit,
        municode_url=args.municode_url,
        gis_url=args.gis_url,
    ))

    print(json.dumps(result, indent=2))
    exit(0 if not result.get("escalated") else 1)
