"""
ZoneWise.AI — Action Agent
Hook Phase: ACTION — first value in under 60 seconds

Handles NLP chatbot queries and runs BID decision pipelines.
CRITICAL: foreclosure and tax deed pipelines are COMPLETELY SEPARATE.
Never apply foreclosure bid formula to a tax deed sale or vice versa.

Prompts: agents/prompts/action_nlp_chatbot.md
         agents/prompts/action_onboarding.md
         agents/prompts/action_bid_decision.md

See TODO.md TASK-009 for implementation requirements.
"""
from pathlib import Path

PROMPT_DIR = Path(__file__).parent / "prompts"

def load_prompt(filename: str) -> str:
    return (PROMPT_DIR / filename).read_text()

# TODO TASK-009: Implement all methods below

def classify_query(query: str, user_profile: dict) -> dict:
    """Classify query into one of 6 types. Determine sale type from context.
    
    Query types: COUNTY_SCAN | DEEP_DIVE | MARKET_QUESTION | 
                 PORTFOLIO | BID_DECISION | CLARIFICATION_NEEDED
    
    Sale type clues:
    - "Case #" format → foreclosure
    - "Cert #" format → tax deed  
    - User says "foreclosure" → foreclosure
    - User says "tax deed" or "tax sale" → tax deed
    - No specification → default to user_profile.sale_type_preference
    """
    raise NotImplementedError("See TODO.md TASK-009")

def foreclosure_bid_pipeline(case_number: str, county: str, user_profile: dict) -> dict:
    """Run 10-stage foreclosure BID analysis.
    
    Mandatory flags (NEVER omit):
    - HOA plaintiff detected → senior mortgage survival warning
    - < 3 comps found → recommend REVIEW not BID
    - Sale < 48hrs → timeline warning
    
    See agents/prompts/action_bid_decision.md for full spec.
    """
    raise NotImplementedError("See TODO.md TASK-009")

def tax_deed_bid_pipeline(cert_number: str, county: str, user_profile: dict) -> dict:
    """Run 10-stage tax deed BID analysis.
    
    Mandatory flags (NEVER omit):
    - Outstanding cert total > 15% ARV → material risk warning
    - Cert chain incomplete/unverifiable → recommend REVIEW not BID
    - Sale < 48hrs → timeline warning
    
    See agents/prompts/action_bid_decision.md for full spec.
    """
    raise NotImplementedError("See TODO.md TASK-009")
