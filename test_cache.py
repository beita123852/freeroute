#!/usr/bin/env python3
"""Test script for cache functionality"""

import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from utils.cache import CacheManager

def test_cache_basic():
    """Test basic cache functionality"""
    print("Testing basic cache functionality...")
    
    config = {
        "enabled": True,
        "ttl_seconds": 60,
        "max_entries": 100,
        "exclude_models": [],
        "cleanup_interval": 60
    }
    
    cache = CacheManager(config)
    
    # Test key generation
    model = "test-model"
    messages = [{"role": "user", "content": "Hello"}]
    kwargs = {"temperature": 0.7}
    
    key1 = cache.generate_key(model, messages, **kwargs)
    print(f"Generated key: {key1[:16]}...")
    
    # Test same request generates same key
    key2 = cache.generate_key(model, messages, **kwargs)
    assert key1 == key2, "Same request should generate same key"
    print("Key generation is deterministic")
    
    # Test different request generates different key
    key3 = cache.generate_key(model, messages, temperature=0.8)
    assert key1 != key3, "Different requests should generate different keys"
    print("Different requests generate different keys")
    
    # Test cache set/get
    test_response = {
        "choices": [{"message": {"content": "Hello!"}}],
        "usage": {"total_tokens": 10}
    }
    
    # Set cache
    success = cache.set(key1, test_response)
    assert success, "Cache set should succeed"
    print("Cache set successful")
    
    # Get cache
    cached = cache.get(key1)
    assert cached is not None, "Cache should return data"
    assert cached["response"] == test_response, "Cache should return same data"
    assert cached["tokens_total"] == 10, "Cache should record token usage"
    print("Cache get successful")
    
    # Test cache miss
    cached_miss = cache.get("nonexistent_key")
    assert cached_miss is None, "Non-existent key should return None"
    print("Cache miss handled correctly")
    
    # Test stats
    stats = cache.stats()
    assert stats["hit_count"] == 1, f"Expected 1 hit, got {stats['hit_count']}"
    assert stats["miss_count"] == 1, f"Expected 1 miss, got {stats['miss_count']}"
    assert stats["total_saved_tokens"] == 10, f"Expected 10 saved tokens, got {stats['total_saved_tokens']}"
    print("Cache statistics correct")
    
    # Test cache clear
    success = cache.clear()
    assert success, "Cache clear should succeed"
    
    stats_after_clear = cache.stats()
    assert stats_after_clear["hit_count"] == 0, "Stats should reset after clear"
    assert stats_after_clear["miss_count"] == 0, "Stats should reset after clear"
    assert stats_after_clear["total_saved_tokens"] == 0, "Stats should reset after clear"
    print("Cache clear successful")
    
    cache.close()
    print("\nAll cache tests passed!")

def test_cache_expiry():
    """Test cache expiry functionality"""
    print("\nTesting cache expiry...")
    
    config = {
        "enabled": True,
        "ttl_seconds": 1,  # Very short TTL for testing
        "max_entries": 100,
        "exclude_models": [],
        "cleanup_interval": 1
    }
    
    cache = CacheManager(config)
    
    key = cache.generate_key("test", [{"role": "user", "content": "test"}])
    test_response = {"choices": [], "usage": {"total_tokens": 5}}
    
    cache.set(key, test_response)
    
    # Should be cached immediately
    cached = cache.get(key)
    assert cached is not None, "Cache should be available immediately"
    print("Cache available immediately after set")
    
    # Wait for expiry
    import time
    time.sleep(2)
    
    # Should be expired now
    cached_expired = cache.get(key)
    assert cached_expired is None, "Cache should expire after TTL"
    print("Cache expires correctly after TTL")
    
    cache.close()
    print("Cache expiry tests passed!")

def test_cache_disabled():
    """Test cache when disabled"""
    print("\nTesting cache disabled mode...")
    
    config = {
        "enabled": False,
        "ttl_seconds": 60,
        "max_entries": 100,
        "exclude_models": [],
        "cleanup_interval": 60
    }
    
    cache = CacheManager(config)
    
    key = cache.generate_key("test", [{"role": "user", "content": "test"}])
    assert key == "", "Cache should not generate keys when disabled"
    print("No key generation when cache disabled")
    
    test_response = {"choices": [], "usage": {"total_tokens": 5}}
    success = cache.set("test_key", test_response)
    assert not success, "Cache set should fail when disabled"
    print("No cache set when disabled")
    
    cached = cache.get("test_key")
    assert cached is None, "Cache get should return None when disabled"
    print("No cache get when disabled")
    
    stats = cache.stats()
    assert not stats["enabled"], "Stats should show cache disabled"
    print("Stats show cache disabled")
    
    cache.close()
    print("Cache disabled mode tests passed!")

if __name__ == "__main__":
    try:
        test_cache_basic()
        test_cache_expiry()
        test_cache_disabled()
        print("\nAll tests completed successfully!")
    except Exception as e:
        print(f"\nTest failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)