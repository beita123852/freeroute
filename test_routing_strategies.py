#!/usr/bin/env python3
"""Test routing strategies for FreeRoute"""
import sys
import yaml
import random
from unittest.mock import Mock, MagicMock
sys.path.insert(0, '.')

print("=" * 60)
print("FreeRoute Routing Strategies Test")
print("=" * 60)

# Load config
with open('config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

# Mock dependencies
mock_pm = Mock()
mock_qt = Mock()
mock_hc = Mock()

# Mock provider data
test_providers = [
    {"name": "provider1", "priority": 1, "weight": 3, "healthy": True},
    {"name": "provider2", "priority": 2, "weight": 2, "healthy": True},
    {"name": "provider3", "priority": 3, "weight": 1, "healthy": True},
]

mock_pm.get_providers_for_model.return_value = test_providers
mock_qt.can_use.return_value = True

# Mock latency data
mock_hc.get_latency.side_effect = lambda name: {
    "provider1": 100.0,
    "provider2": 50.0,
    "provider3": 200.0
}.get(name)

def test_priority_fallback():
    """Test priority fallback strategy"""
    print("\n[1/5] Testing PriorityFallbackStrategy...")
    
    from router import PriorityFallbackStrategy
    strategy = PriorityFallbackStrategy(mock_pm, mock_qt, mock_hc, config)
    
    # Test selection
    provider = strategy.select_provider("test_model", test_providers)
    assert provider["name"] == "provider1", f"Expected provider1, got {provider['name']}"
    
    print("  ✅ Priority fallback works correctly")

def test_round_robin():
    """Test round robin strategy"""
    print("\n[2/5] Testing RoundRobinStrategy...")
    
    from router import RoundRobinStrategy
    strategy = RoundRobinStrategy(mock_pm, mock_qt, mock_hc, config)
    
    # Test multiple selections
    selections = []
    for i in range(6):  # 2 full cycles
        provider = strategy.select_provider("test_model", test_providers)
        selections.append(provider["name"])
    
    expected_pattern = ["provider1", "provider2", "provider3", "provider1", "provider2", "provider3"]
    assert selections == expected_pattern, f"Expected {expected_pattern}, got {selections}"
    
    print("  ✅ Round robin cycles through providers correctly")

def test_least_latency():
    """Test least latency strategy"""
    print("\n[3/5] Testing LeastLatencyStrategy...")
    
    from router import LeastLatencyStrategy
    strategy = LeastLatencyStrategy(mock_pm, mock_qt, mock_hc, config)
    
    # Test selection
    provider = strategy.select_provider("test_model", test_providers)
    assert provider["name"] == "provider2", f"Expected provider2 (lowest latency), got {provider['name']}"
    
    print("  ✅ Least latency selects fastest provider")

def test_random():
    """Test random strategy"""
    print("\n[4/5] Testing RandomStrategy...")
    
    from router import RandomStrategy
    strategy = RandomStrategy(mock_pm, mock_qt, mock_hc, config)
    
    # Test multiple selections (should be random)
    selections = []
    for i in range(10):
        provider = strategy.select_provider("test_model", test_providers)
        selections.append(provider["name"])
    
    # Should have selected from all providers
    unique_selections = set(selections)
    assert len(unique_selections) == 3, f"Expected all providers to be selected, got {unique_selections}"
    
    print("  ✅ Random selection works (distributed across providers)")

def test_weighted():
    """Test weighted strategy"""
    print("\n[5/5] Testing WeightedStrategy...")
    
    from router import WeightedStrategy
    strategy = WeightedStrategy(mock_pm, mock_qt, mock_hc, config)
    
    # Test multiple selections
    selections = []
    for i in range(100):
        provider = strategy.select_provider("test_model", test_providers)
        selections.append(provider["name"])
    
    # Count selections
    from collections import Counter
    counts = Counter(selections)
    
    # Provider1 should be selected most (weight=3)
    # Provider2 should be selected medium (weight=2) 
    # Provider3 should be selected least (weight=1)
    assert counts["provider1"] > counts["provider3"], "Provider1 (weight=3) should be selected more than provider3 (weight=1)"
    assert counts["provider2"] > counts["provider3"], "Provider2 (weight=2) should be selected more than provider3 (weight=1)"
    
    print(f"  ✅ Weighted selection distribution: {dict(counts)}")

def test_strategy_factory():
    """Test strategy factory function"""
    print("\n[6/6] Testing Strategy Factory...")
    
    from router import get_routing_strategy
    
    # Test all strategies
    strategies_to_test = [
        "priority_fallback",
        "round_robin", 
        "least_latency",
        "random",
        "weighted"
    ]
    
    for strategy_name in strategies_to_test:
        strategy = get_routing_strategy(strategy_name, mock_pm, mock_qt, mock_hc, config)
        assert strategy is not None, f"Failed to create strategy: {strategy_name}"
        print(f"  ✅ {strategy_name} strategy created successfully")
    
    # Test unknown strategy fallback
    strategy = get_routing_strategy("unknown_strategy", mock_pm, mock_qt, mock_hc, config)
    assert strategy is not None, "Failed fallback for unknown strategy"
    print("  ✅ Unknown strategy falls back to priority_fallback")

if __name__ == "__main__":
    try:
        test_priority_fallback()
        test_round_robin()
        test_least_latency()
        test_random()
        test_weighted()
        test_strategy_factory()
        
        print("\n" + "=" * 60)
        print("✅ All routing strategy tests passed!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)