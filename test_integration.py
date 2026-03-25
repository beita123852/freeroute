#!/usr/bin/env python3
"""Integration test for cache functionality"""

import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from utils.cache import CacheManager

def test_cache_integration():
    """Test cache integration with router-like functionality"""
    print("Testing cache integration...")
    
    config = {
        "enabled": True,
        "ttl_seconds": 60,
        "max_entries": 100,
        "exclude_models": [],
        "cleanup_interval": 60
    }
    
    cache = CacheManager(config)
    
    # Simulate router request
    def simulate_router_request(model, messages, **kwargs):
        """Simulate router request with caching"""
        # Generate cache key
        cache_key = cache.generate_key(model, messages, **kwargs)
        if cache_key:
            cached_response = cache.get(cache_key)
            if cached_response:
                print(f"Cache hit for {model}")
                return {
                    "success": True,
                    "data": cached_response["response"],
                    "provider": "cache",
                    "cached": True
                }
        
        # Simulate actual provider response
        print(f"Cache miss for {model}, simulating provider call...")
        response_data = {
            "choices": [{"message": {"content": f"Response to: {messages[0]['content']}"}}],
            "usage": {"total_tokens": len(messages[0]['content']) + 10}
        }
        
        # Cache the response
        if cache_key:
            cache.set(cache_key, response_data)
            print(f"Cached response for {model}")
        
        return {
            "success": True,
            "data": response_data,
            "provider": "simulated-provider",
            "cached": False
        }
    
    # Test repeated requests
    model = "test-model"
    messages = [{"role": "user", "content": "Hello, how are you?"}]
    kwargs = {"temperature": 0.7}
    
    # First request - should miss cache
    result1 = simulate_router_request(model, messages, **kwargs)
    assert not result1["cached"], "First request should not be cached"
    assert result1["provider"] == "simulated-provider", "First request should come from provider"
    print("First request handled correctly")
    
    # Second request - should hit cache
    result2 = simulate_router_request(model, messages, **kwargs)
    assert result2["cached"], "Second request should be cached"
    assert result2["provider"] == "cache", "Second request should come from cache"
    assert result2["data"] == result1["data"], "Cached response should match original"
    print("Second request cached correctly")
    
    # Test different request - should miss cache
    different_kwargs = {"temperature": 0.8}
    result3 = simulate_router_request(model, messages, **different_kwargs)
    assert not result3["cached"], "Different request should not hit cache"
    print("Different request handled correctly")
    
    # Check cache statistics
    stats = cache.stats()
    assert stats["hit_count"] == 1, f"Expected 1 hit, got {stats['hit_count']}"
    assert stats["miss_count"] == 2, f"Expected 2 misses, got {stats['miss_count']}"
    print("Cache statistics correct")
    
    cache.close()
    print("Integration test passed!")

def test_cache_exclusion():
    """Test model exclusion from caching"""
    print("\nTesting cache exclusion...")
    
    config = {
        "enabled": True,
        "ttl_seconds": 60,
        "max_entries": 100,
        "exclude_models": ["excluded-model"],
        "cleanup_interval": 60
    }
    
    cache = CacheManager(config)
    
    # Test excluded model
    key_excluded = cache.generate_key("excluded-model", [{"role": "user", "content": "test"}])
    assert key_excluded == "", "Excluded model should not generate cache key"
    print("Excluded model correctly skipped")
    
    # Test non-excluded model
    key_normal = cache.generate_key("normal-model", [{"role": "user", "content": "test"}])
    assert key_normal != "", "Non-excluded model should generate cache key"
    print("Non-excluded model correctly handled")
    
    cache.close()
    print("Cache exclusion test passed!")

if __name__ == "__main__":
    try:
        test_cache_integration()
        test_cache_exclusion()
        print("\nAll integration tests completed successfully!")
    except Exception as e:
        print(f"\nTest failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)