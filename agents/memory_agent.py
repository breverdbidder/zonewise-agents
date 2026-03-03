"""
ZoneWise.AI — Memory Agent  
Hook Phase: INVESTMENT — makes product irreplaceable with every interaction

Tracks foreclosure and tax deed behavior SEPARATELY.
DO NOT merge or average across sale types.

Prompts: agents/prompts/investment_profile_learning.md
         agents/prompts/investment_pipeline_manager.md
         agents/prompts/investment_match_scorer.md

See TODO.md TASK-008 for implementation requirements.
"""

# TODO TASK-008: Implement all methods below

def update_profile(user_id: str, session_data: dict) -> dict:
    """Extract behavioral signal and update user_profiles in Supabase.
    
    CRITICAL: Write to foreclosure_profile and tax_deed_profile SEPARATELY.
    NEVER blend metrics across sale types.
    
    Recency weighting: last 7 days = 3x weight vs interactions > 30 days.
    Protected class rule: NEVER infer race, religion, age, gender, national origin.
    
    Returns updated profile JSON.
    """
    raise NotImplementedError("See TODO.md TASK-008")

def score_match(property_data: dict, user_profile: dict, sale_type: str) -> dict:
    """Score property/cert match against user profile.
    
    CRITICAL: Use SEPARATE scoring models:
    - sale_type == 'foreclosure': use foreclosure scoring model
      (county match, judgment range, bid ratio floor, HOA tolerance)
    - sale_type == 'tax_deed': use tax deed scoring model  
      (county match, opening bid range, min net spread, cert exposure tolerance)
    
    NEVER apply foreclosure model to tax deed or vice versa.
    
    Returns: {match_score, match_label, show_in_digest, match_reasoning}
    match_reasoning MUST reference specific profile data (not generic criteria)
    """
    raise NotImplementedError("See TODO.md TASK-008")
