#!/usr/bin/env python3
"""Demonstrate all routing strategies"""
import sys
import yaml
from unittest.mock import Mock
sys.path.insert(0, '.')

print("=" * 60)
print("FreeRoute Routing Strategies Demo")
print("=" * 60)

# Mock dependencies
mock_pm = Mock()
mock_qt = Mock()
mock_hc = Mock()

# Create test providers with different characteristics
test_providers = [
    {"name": "nim", "priority": 1, "weight": 5, "healthy": True},
    {"name": "openrouter", "priority": 2, "weight": 3, "healthy": True},
    {"name": "groq", "priority": 3, "weight": 4, "healthy": True},
    {"name": "cerebras", "priority": 4, "weight": 1, "healthy": True},
]

mock_pm.get_providers_for_model.return_value = test_providers
mock_qt.can_use.return_value = True

# Mock latency data
mock_hc.get_latency.side_effect = lambda name: {
    "nim": 120.0,
    "openrouter": 80.0,
    "groq": 60.0,
    "cerebras": 150.0
}.get(name)

def demo_strategy(strategy_name, strategy_class):
    """Demonstrate a specific strategy"""
    print(f"\n🔧 {strategy_name.upper()} Strategy")
    print("-" * 40)
    
    strategy = strategy_class(mock_pm, mock_qt, mock_hc, {})
    
    # Show 10 selections
    selections = []
    for i in range(10):
        provider = strategy.select_provider("test-model", test_providers)
        selections.append(provider["name"])
    
    # Count distribution
    from collections import Counter
    counts = Counter(selections)
    
    print(f"Selections: {selections}")
    print(f"Distribution: {dict(counts)}")
    
    if strategy_name == "least_latency":
        print(f"Latencies: nim=120ms, openrouter=80ms, groq=60ms, cerebras=150ms")
        print(f"Expected: groq (fastest at 60ms)")
    elif strategy_name == "weighted":
        print(f"Weights: nim=5, openrouter=3, groq=4, cerebras=1")
        print(f"Expected: nim selected most (weight=5)")

# Test all strategies
from router import (
    PriorityFallbackStrategy,
    RoundRobinStrategy,
    LeastLatencyStrategy,
    RandomStrategy,
    WeightedStrategy
)

strategies = [
    ("priority_fallback", PriorityFallbackStrategy),
    ("round_robin", RoundRobinStrategy),
    ("least_latency", LeastLatencyStrategy),
    ("random", RandomStrategy),
    ("weighted", WeightedStrategy),
]

for strategy_name, strategy_class in strategies:
    demo_strategy(strategy_name, strategy_class)

print("\n" + "=" * 60)
print("🎯 Strategy Summary:")
print("=" * 60)
print("• priority_fallback: Always selects highest priority provider")
print("• round_robin: Cycles through providers in sequence")
print("• least_latency: Selects provider with lowest latency")  
print("• random: Random selection from available providers")
print("• weighted: Weighted random selection based on provider weight")
print("\n📋 Config Usage:")
print("Set routing.strategy in config.yaml to one of:")
print("  - priority_fallback (default)")
print("  - round_robin")
print("  - least_latency") 
print("  - random")
print("  - weighted")
print("\n💡 For weighted strategy, add 'weight' field to provider configs")