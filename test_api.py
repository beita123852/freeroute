#!/usr/bin/env python3
"""Test API endpoints for cache functionality"""

import asyncio
import httpx
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

async def test_cache_endpoints():
    """Test cache-related API endpoints"""
    print("Testing cache API endpoints...")
    
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8090") as client:
        # Test cache stats endpoint
        try:
            response = await client.get("/api/cache/stats")
            print(f"Cache stats status: {response.status_code}")
            if response.status_code == 200:
                stats = response.json()
                print(f"Cache enabled: {stats.get('enabled', False)}")
                print(f"Hit count: {stats.get('hit_count', 0)}")
                print(f"Miss count: {stats.get('miss_count', 0)}")
                print("Cache stats endpoint working!")
            else:
                print(f"Cache stats failed: {response.text}")
        except Exception as e:
            print(f"Cache stats test failed: {e}")
        
        # Test clear cache endpoint
        try:
            response = await client.delete("/api/cache")
            print(f"Clear cache status: {response.status_code}")
            if response.status_code == 200:
                result = response.json()
                print(f"Clear cache result: {result.get('success', False)}")
                print("Clear cache endpoint working!")
            else:
                print(f"Clear cache failed: {response.text}")
        except Exception as e:
            print(f"Clear cache test failed: {e}")
        
        # Test status endpoint includes cache info
        try:
            response = await client.get("/status")
            print(f"Status endpoint status: {response.status_code}")
            if response.status_code == 200:
                status = response.json()
                if "cache" in status:
                    print("Status endpoint includes cache information!")
                    cache_info = status["cache"]
                    print(f"Cache enabled: {cache_info.get('enabled', False)}")
                else:
                    print("Status endpoint does not include cache info")
            else:
                print(f"Status endpoint failed: {response.text}")
        except Exception as e:
            print(f"Status endpoint test failed: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(test_cache_endpoints())
        print("\nAPI endpoint tests completed!")
    except Exception as e:
        print(f"\nTest failed: {e}")
        sys.exit(1)