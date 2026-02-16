#!/usr/bin/env python3
"""
Test script for VLESS link generation with validation.

This script tests the build_vless_link function with various edge cases
to ensure it handles empty or missing fields correctly.
"""

import sys
from dataclasses import dataclass
from typing import Optional


@dataclass
class MockServer:
    """Mock Server object for testing."""
    name: str = "Test Server"
    host: str = "example.com"
    port: int = 443
    public_key: str = "test_public_key"
    short_ids: str = "abc123"
    domain: str = "example.com"
    network_type: Optional[str] = None
    security: Optional[str] = None
    flow: Optional[str] = None
    fingerprint: Optional[str] = None
    spider_x: str = "/"
    xhttp_host: Optional[str] = None
    xhttp_path: Optional[str] = None
    xhttp_mode: Optional[str] = None

    def get_first_short_id(self) -> str:
        return self.short_ids.split(",")[0].strip() if self.short_ids else ""


def build_vless_link_test(uuid: str, server: MockServer) -> str:
    """Test version of build_vless_link with validation."""
    import urllib.parse

    # Validate required fields - use defaults if empty or whitespace
    network_type = (server.network_type or "").strip() or "xhttp"
    security = (server.security or "").strip() or "reality"
    flow = (server.flow or "").strip() or "xtls-rprx-vision"
    fingerprint = (server.fingerprint or "").strip() or "chrome"

    params = {
        "encryption": "none",
        "security": security,
        "type": network_type,
        "pbk": server.public_key,
        "fp": fingerprint,
        "sni": server.domain,
        "sid": server.get_first_short_id(),
        "spx": server.spider_x,
        "flow": flow,
    }

    if server.xhttp_host:
        params["host"] = server.xhttp_host
    if server.xhttp_path:
        params["path"] = server.xhttp_path
    if server.xhttp_mode:
        params["mode"] = server.xhttp_mode

    query = "&".join([f"{k}={urllib.parse.quote(str(v), safe='/')}" for k, v in params.items() if v])
    remark = f"SWAGA - {server.name}"
    tag = urllib.parse.quote(remark, safe="")

    return f"vless://{uuid}@{server.host}:{server.port}?{query}#{tag}"


def run_tests():
    """Run test cases."""
    test_uuid = "12345678-1234-1234-1234-123456789abc"

    print("=" * 80)
    print("VLESS Link Generation Tests")
    print("=" * 80)

    # Test 1: Empty network_type (should use default "xhttp")
    print("\n[TEST 1] Empty network_type")
    server1 = MockServer(
        name="Empty Network Type",
        network_type="",  # Empty!
    )
    try:
        link1 = build_vless_link_test(test_uuid, server1)
        if "type=xhttp" in link1:
            print("✅ PASS: Default network_type 'xhttp' applied")
        else:
            print("❌ FAIL: Default network_type not applied")
        print(f"   Link: {link1[:100]}...")
    except Exception as e:
        print(f"❌ FAIL: {e}")

    # Test 2: None network_type (should use default "xhttp")
    print("\n[TEST 2] None network_type")
    server2 = MockServer(
        name="None Network Type",
        network_type=None,  # None!
    )
    try:
        link2 = build_vless_link_test(test_uuid, server2)
        if "type=xhttp" in link2:
            print("✅ PASS: Default network_type 'xhttp' applied")
        else:
            print("❌ FAIL: Default network_type not applied")
        print(f"   Link: {link2[:100]}...")
    except Exception as e:
        print(f"❌ FAIL: {e}")

    # Test 3: Valid network_type (should use provided value)
    print("\n[TEST 3] Valid network_type")
    server3 = MockServer(
        name="Valid Network Type",
        network_type="tcp",
    )
    try:
        link3 = build_vless_link_test(test_uuid, server3)
        if "type=tcp" in link3:
            print("✅ PASS: Provided network_type 'tcp' used")
        else:
            print("❌ FAIL: Provided network_type not used")
        print(f"   Link: {link3[:100]}...")
    except Exception as e:
        print(f"❌ FAIL: {e}")

    # Test 4: All fields empty (should use all defaults)
    print("\n[TEST 4] All optional fields empty")
    server4 = MockServer(
        name="All Defaults",
        network_type="",
        security="",
        flow="",
        fingerprint="",
    )
    try:
        link4 = build_vless_link_test(test_uuid, server4)
        checks = [
            ("type=xhttp", "network_type"),
            ("security=reality", "security"),
            ("flow=xtls-rprx-vision", "flow"),
            ("fp=chrome", "fingerprint"),
        ]
        all_pass = True
        for check, field in checks:
            if check in link4:
                print(f"   ✓ Default {field} applied")
            else:
                print(f"   ✗ Default {field} NOT applied")
                all_pass = False
        if all_pass:
            print("✅ PASS: All defaults applied correctly")
        else:
            print("❌ FAIL: Some defaults missing")
        print(f"   Link: {link4[:100]}...")
    except Exception as e:
        print(f"❌ FAIL: {e}")

    # Test 5: Whitespace-only fields (should use defaults)
    print("\n[TEST 5] Whitespace-only fields")
    server5 = MockServer(
        name="Whitespace Fields",
        network_type="   ",  # Whitespace!
        security="  ",
    )
    try:
        link5 = build_vless_link_test(test_uuid, server5)
        if "type=xhttp" in link5 and "security=reality" in link5:
            print("✅ PASS: Whitespace trimmed, defaults applied")
        else:
            print("❌ FAIL: Whitespace not handled correctly")
        print(f"   Link: {link5[:100]}...")
    except Exception as e:
        print(f"❌ FAIL: {e}")

    print("\n" + "=" * 80)
    print("Tests completed!")
    print("=" * 80)


if __name__ == "__main__":
    run_tests()
