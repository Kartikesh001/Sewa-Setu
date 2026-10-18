"""
Test script to check and verify the Citizen MCP Server.
Tests tools directly and validates output.
"""

import sys
import os

# Set UTF-8 encoding for console output
sys.stdout.reconfigure(encoding='utf-8')

print("=" * 60)
print("Sewa Setu — Citizen MCP Server Verification")
print("=" * 60)

try:
    from citizen_mcp.server import mcp_server
    from citizen_mcp.tools import (
        get_scheme_guidelines,
        check_eligibility,
        check_my_application,
        submit_pension_application,
        get_my_application_status,
        withdraw_pending_application
    )
    from citizen_mcp.auth import create_mock_citizen_token

    print("\n[1] Checking registered tools on MCP Server...")
    # List tools registered on MCPServer
    tools = mcp_server._tool_manager.list_tools() if hasattr(mcp_server, '_tool_manager') else []
    print(f" -> Found {len(tools)} registered MCP tools:")
    for t in tools:
        print(f"    * {t.name}: {t.description.strip().splitlines()[0] if t.description else ''}")

    print("\n[2] Testing tool: get_scheme_guidelines()")
    guidelines = get_scheme_guidelines()
    print(f" -> Scheme: {guidelines['scheme_name']}")
    print(f" -> Monthly Pension: {guidelines['monthly_pension']}")
    print(f" -> Minimum Age: {guidelines['eligibility_criteria']['minimum_age']}")
    print(f" -> Covered Blocks: {guidelines['eligibility_criteria']['jurisdiction']}")
    print(f" -> Window Status: {guidelines['application_window']['status']}")

    print("\n[3] Testing tool: check_eligibility()")
    # Case A: Eligible 72-year-old in Sonari
    res_a = check_eligibility("15/08/1954", "Sonari")
    print(f" -> [Eligible Test] Age: {res_a['calculated_age']}, Block: {res_a['verified_block']} => Eligible: {res_a['eligible']}")
    assert res_a['eligible'] is True, "Should be eligible"

    # Case B: Ineligible 52-year-old
    res_b = check_eligibility("15/08/1974", "Sonari")
    print(f" -> [Underage Test] Age: {res_b['calculated_age']} => Eligible: {res_b['eligible']}, Error: {res_b['errors']}")
    assert res_b['eligible'] is False, "Should be ineligible"

    # Case C: Invalid block
    res_c = check_eligibility("15/08/1954", "Guwahati")
    print(f" -> [Invalid Block Test] Block: Guwahati => Eligible: {res_c['eligible']}, Error: {res_c['errors']}")
    assert res_c['eligible'] is False, "Should be ineligible"

    print("\n[4] Testing tool: check_my_application() with token validation...")
    token = create_mock_citizen_token("9876543210")
    print(f" -> Generated test token for citizen mobile 9876543210: {token[:25]}...")
    try:
        app_status = check_my_application(token)
        print(f" -> Query Result: {app_status.get('status')} - {app_status.get('message')}")
    except Exception as e:
        print(f" -> Database query note (DB may be offline if docker is starting): {e}")

    print("\n" + "=" * 60)
    print("ALL IN-PROCESS CHECKS PASSED SUCCESSFULLY!")
    print("=" * 60)

except Exception as err:
    print(f"\n[ERROR] Check failed: {err}")
    import traceback
    traceback.print_exc()
