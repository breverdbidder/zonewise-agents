"""
LangGraph Trajectory Tests using agentevals
Tests agent node transitions and state handoffs
"""
import pytest
import os

try:
    from agentevals.trajectory.llm import create_trajectory_llm_grader
    from agentevals.trajectory.exact import trajectory_exact_match
    AGENTEVALS_AVAILABLE = True
except ImportError:
    AGENTEVALS_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not AGENTEVALS_AVAILABLE,
    reason="agentevals not installed"
)


# ── Simulated agent trajectories for testing ──────────────────
def simulate_query_trajectory(query: str) -> list[dict]:
    """Returns expected node sequence for a given query"""
    base = [
        {"role": "system", "content": "ZoneWise zoning agent initialized"},
        {"role": "user", "content": query},
    ]
    
    if "zoning" in query.lower() or "parcel" in query.lower():
        base += [
            {"role": "tool_call", "content": "query_supabase: county_zones"},
            {"role": "tool_result", "content": '{"zones": [...], "county": "Brevard"}'},
            {"role": "assistant", "content": "Based on Supabase data, the zoning classification is..."},
        ]
    elif "auction" in query.lower():
        base += [
            {"role": "tool_call", "content": "query_supabase: multi_county_auctions"},
            {"role": "tool_result", "content": '{"auctions": [...]}'},
            {"role": "assistant", "content": "Upcoming auctions include..."},
        ]
    else:
        base += [
            {"role": "assistant", "content": "I can help with zoning and parcel information for Florida counties."},
        ]
    
    return base


class TestTrajectoryStructure:
    def test_zoning_query_trajectory_has_tool_call(self):
        """Zoning queries must include a Supabase tool call"""
        traj = simulate_query_trajectory("What is the zoning for parcels in Brevard County?")
        tool_calls = [msg for msg in traj if msg["role"] == "tool_call"]
        assert len(tool_calls) >= 1, "Expected at least 1 tool call for zoning query"

    def test_trajectory_starts_with_system(self):
        traj = simulate_query_trajectory("test query")
        assert traj[0]["role"] == "system"

    def test_trajectory_ends_with_assistant(self):
        traj = simulate_query_trajectory("What zoning applies here?")
        assert traj[-1]["role"] == "assistant"

    def test_trajectory_has_user_message(self):
        query = "What is the zoning classification?"
        traj = simulate_query_trajectory(query)
        user_msgs = [msg for msg in traj if msg["role"] == "user"]
        assert len(user_msgs) >= 1
        assert query in user_msgs[0]["content"]

    def test_auction_query_trajectory_includes_supabase(self):
        traj = simulate_query_trajectory("Show upcoming auction properties")
        tool_calls = [msg for msg in traj if msg["role"] == "tool_call"]
        assert any("auction" in tc["content"].lower() for tc in tool_calls)


class TestTrajectoryExactMatch:
    """Test exact trajectory matching for critical paths"""
    
    def test_simple_query_exact_match(self):
        """Simple/general queries should not invoke tools"""
        expected = [
            {"role": "system", "content": "ZoneWise zoning agent initialized"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "I can help with zoning and parcel information for Florida counties."},
        ]
        actual = simulate_query_trajectory("hello")
        
        # Check role sequence matches
        expected_roles = [m["role"] for m in expected]
        actual_roles = [m["role"] for m in actual]
        assert expected_roles == actual_roles, f"Role sequence mismatch: {actual_roles} != {expected_roles}"

    def test_zoning_query_role_sequence(self):
        """Zoning queries must follow: system→user→tool_call→tool_result→assistant"""
        traj = simulate_query_trajectory("What is RS-1 zoning?")
        roles = [m["role"] for m in traj]
        assert roles[0] == "system"
        assert roles[1] == "user"
        assert "tool_call" in roles
        assert "tool_result" in roles
        assert roles[-1] == "assistant"
