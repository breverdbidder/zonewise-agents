#!/usr/bin/env python3
"""
Autonomous Test Suite for ZoneWise County Router MCP

Runs comprehensive tests on MCP deployment. Designed for Claude Code
to execute autonomously once DEEPSEEK_API_KEY is configured.

Exit codes:
  0 = All tests passed
  1 = DeepSeek API key missing (expected, not a failure)
  2 = Critical test failures
  3 = Partial failures (some tests passed)
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime


class TestResult:
    """Track test execution results."""
    
    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.tests_failed = 0
        self.tests_skipped = 0
        self.failures = []
    
    def record_pass(self, test_name: str):
        self.tests_run += 1
        self.tests_passed += 1
        print(f"  ✅ {test_name}")
    
    def record_fail(self, test_name: str, error: str):
        self.tests_run += 1
        self.tests_failed += 1
        self.failures.append({"test": test_name, "error": error})
        print(f"  ❌ {test_name}: {error}")
    
    def record_skip(self, test_name: str, reason: str):
        self.tests_skipped += 1
        print(f"  ⏭️  {test_name}: {reason}")
    
    def summary(self):
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        print(f"Total: {self.tests_run}")
        print(f"Passed: {self.tests_passed} ✅")
        print(f"Failed: {self.tests_failed} ❌")
        print(f"Skipped: {self.tests_skipped} ⏭️")
        
        if self.tests_failed > 0:
            print("\nFAILURES:")
            for f in self.failures:
                print(f"  • {f['test']}: {f['error']}")
        
        if self.tests_failed == 0 and self.tests_passed > 0:
            print("\n🎉 ALL TESTS PASSED")
            return 0
        elif self.tests_failed > 0 and self.tests_passed > 0:
            print("\n⚠️  PARTIAL FAILURES")
            return 3
        elif self.tests_failed > 0:
            print("\n💥 CRITICAL FAILURES")
            return 2
        else:
            print("\n⏭️  ALL TESTS SKIPPED")
            return 1


async def test_file_structure(result: TestResult):
    """Verify all deployed files exist."""
    print("\n[1] File Structure Tests")
    
    required_files = [
        "mcp/county_router_mcp.py",
        "mcp/requirements.txt",
        "mcp/README.md",
        "app/prompts/template.md",
        "app/prompts/scraper_agent.md",
        "app/prompts/analysis_agent.md",
        "app/prompts/report_agent.md",
        "app/prompts/qa_agent.md",
        "app/langgraph/nodes/mcp_integration.py"
    ]
    
    for filepath in required_files:
        if Path(filepath).exists():
            result.record_pass(f"File exists: {filepath}")
        else:
            result.record_fail(f"File missing: {filepath}", "File not found on filesystem")


async def test_prompt_templates(result: TestResult):
    """Validate prompt template structure."""
    print("\n[2] Prompt Template Tests")
    
    required_sections = [
        "## TASK",
        "## EXPECTED OUTCOME",
        "## CONTEXT",
        "## CONSTRAINTS",
        "## MUST DO",
        "## MUST NOT DO",
        "## OUTPUT FORMAT"
    ]
    
    prompt_files = [
        "app/prompts/scraper_agent.md",
        "app/prompts/analysis_agent.md",
        "app/prompts/report_agent.md",
        "app/prompts/qa_agent.md"
    ]
    
    for prompt_file in prompt_files:
        try:
            content = Path(prompt_file).read_text()
            
            # Check all sections present
            missing_sections = [s for s in required_sections if s not in content]
            
            if not missing_sections:
                result.record_pass(f"7-section structure: {Path(prompt_file).name}")
            else:
                result.record_fail(
                    f"7-section structure: {Path(prompt_file).name}",
                    f"Missing sections: {missing_sections}"
                )
        except Exception as e:
            result.record_fail(f"Template validation: {Path(prompt_file).name}", str(e))


async def test_mcp_imports(result: TestResult):
    """Verify MCP server can be imported."""
    print("\n[3] Python Import Tests")
    
    try:
        # Add mcp directory to path
        sys.path.insert(0, str(Path("mcp").absolute()))
        
        # Test imports
        from county_router_mcp import CountyRouterMCP, FLORIDA_COUNTIES
        
        result.record_pass("Import CountyRouterMCP class")
        
        # Verify 67 counties
        if len(FLORIDA_COUNTIES) == 67:
            result.record_pass("67 Florida counties configured")
        else:
            result.record_fail(
                "County count",
                f"Expected 67, got {len(FLORIDA_COUNTIES)}"
            )
        
        # Test router instantiation (without API key)
        router = CountyRouterMCP()
        result.record_pass("Instantiate CountyRouterMCP (no API key)")
        
    except Exception as e:
        result.record_fail("MCP imports", str(e))


async def test_environment_vars(result: TestResult):
    """Check environment variable configuration."""
    print("\n[4] Environment Variable Tests")
    
    # Required vars
    required = {
        "DEEPSEEK_API_KEY": "DeepSeek API key",
        "SUPABASE_URL": "Supabase URL",
        "SUPABASE_SERVICE_ROLE_KEY": "Supabase service role key",
        "AGENTQL_API_KEY": "AgentQL API key"
    }
    
    for var, description in required.items():
        value = os.getenv(var)
        if value:
            # Mask sensitive values
            masked = f"{value[:8]}...{value[-4:]}" if len(value) > 12 else "***"
            result.record_pass(f"{description}: {masked}")
        else:
            if var == "DEEPSEEK_API_KEY":
                # Expected to be missing initially
                result.record_skip(
                    f"{description}",
                    "Not configured yet - add to GitHub Secrets"
                )
            else:
                result.record_fail(f"{description}", "Environment variable not set")


async def test_mcp_server_basic(result: TestResult):
    """Test basic MCP server functionality (without API calls)."""
    print("\n[5] MCP Server Basic Tests")
    
    if not os.getenv("DEEPSEEK_API_KEY"):
        result.record_skip(
            "MCP server functionality",
            "DeepSeek API key required - skipping live tests"
        )
        return
    
    try:
        sys.path.insert(0, str(Path("mcp").absolute()))
        from county_router_mcp import CountyRouterMCP
        
        router = CountyRouterMCP()
        
        # Test prompt loading
        try:
            prompt = router.load_agent_prompt(
                "scraper",
                county_name="Brevard",
                clerk_system_type="Benchmark",
                county_population="606,612",
                avg_monthly_foreclosures=50,
                last_scraped_at="Never",
                last_record_count=0,
                known_issues="None",
                rate_limit_rpm=10,
                max_concurrent=5,
                timeout_seconds=30,
                max_api_calls=100,
                anti_bot_measures="Cloudflare",
                agentql_api_key="***REDACTED***"
            )
            
            if "## TASK" in prompt and "Brevard" in prompt:
                result.record_pass("Load and format scraper prompt")
            else:
                result.record_fail("Prompt formatting", "Missing expected content")
        
        except Exception as e:
            result.record_fail("Load agent prompt", str(e))
    
    except Exception as e:
        result.record_fail("MCP server basic tests", str(e))


async def test_mcp_live_call(result: TestResult):
    """Test live MCP call to DeepSeek (requires API key)."""
    print("\n[6] MCP Live Call Tests")
    
    if not os.getenv("DEEPSEEK_API_KEY"):
        result.record_skip(
            "Live MCP call",
            "DeepSeek API key required - add key and re-run"
        )
        return
    
    try:
        sys.path.insert(0, str(Path("mcp").absolute()))
        from county_router_mcp import CountyRouterMCP
        
        router = CountyRouterMCP()
        
        # Test scraper call (Brevard County)
        scrape_result = await router.scrape_county(
            county="Brevard",
            context={
                "clerk_system": "Benchmark (Odyssey)",
                "rate_limit": 10,
                "timeout": 30,
                "last_scraped": "Never"
            },
            mode="advisory"
        )
        
        if scrape_result["success"]:
            result.record_pass("Live scraper call (Brevard)")
            print(f"    → Cost: ${scrape_result.get('cost_usd', 0):.4f}")
            print(f"    → Tokens: {scrape_result.get('tokens_used', 0)}")
        else:
            result.record_fail(
                "Live scraper call",
                scrape_result.get("error", "Unknown error")
            )
    
    except Exception as e:
        result.record_fail("Live MCP call", str(e))


async def test_langgraph_integration(result: TestResult):
    """Test LangGraph node integration."""
    print("\n[7] LangGraph Integration Tests")
    
    try:
        sys.path.insert(0, str(Path("app").absolute()))
        from langgraph.nodes.mcp_integration import (
            scraper_node_mcp,
            analysis_node_mcp,
            report_node_mcp,
            qa_node_mcp
        )
        
        result.record_pass("Import LangGraph MCP nodes")
        
        # Verify nodes are async functions
        if asyncio.iscoroutinefunction(scraper_node_mcp):
            result.record_pass("scraper_node_mcp is async")
        else:
            result.record_fail("scraper_node_mcp", "Not an async function")
        
        if asyncio.iscoroutinefunction(analysis_node_mcp):
            result.record_pass("analysis_node_mcp is async")
        else:
            result.record_fail("analysis_node_mcp", "Not an async function")
    
    except Exception as e:
        result.record_fail("LangGraph integration", str(e))


async def main():
    """Run all tests."""
    print("="*60)
    print("ZONEWISE MCP DEPLOYMENT TEST SUITE")
    print("="*60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Working Directory: {Path.cwd()}")
    print()
    
    result = TestResult()
    
    # Run test suites
    await test_file_structure(result)
    await test_prompt_templates(result)
    await test_mcp_imports(result)
    await test_environment_vars(result)
    await test_mcp_server_basic(result)
    await test_mcp_live_call(result)
    await test_langgraph_integration(result)
    
    # Print summary
    exit_code = result.summary()
    
    # Save results to JSON
    results_json = {
        "timestamp": datetime.now().isoformat(),
        "tests_run": result.tests_run,
        "tests_passed": result.tests_passed,
        "tests_failed": result.tests_failed,
        "tests_skipped": result.tests_skipped,
        "failures": result.failures,
        "exit_code": exit_code
    }
    
    Path("test_results.json").write_text(json.dumps(results_json, indent=2))
    print(f"\nResults saved to: test_results.json")
    
    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
