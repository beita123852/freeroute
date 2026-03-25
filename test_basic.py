#!/usr/bin/env python3
"""Basic test for FreeRoute components"""
import sys
import yaml
sys.path.insert(0, '.')

print("=" * 50)
print("FreeRoute Basic Test")
print("=" * 50)

# Load config
with open('config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

# Test 1: Provider Manager
print("\n[1/5] Testing ProviderManager...")
try:
    from providers.manager import ProviderManager
    pm = ProviderManager(config)
    providers = list(pm.providers)
    print(f"  OK - Loaded {len(providers)} providers")
    for p in providers:
        models = p.get("models", [])
        print(f"    - {p['name']}: {len(models)} models, priority={p['priority']}")
except Exception as e:
    print(f"  FAIL - {e}")
    pm = None

# Test 2: Quota Tracker
print("\n[2/5] Testing QuotaTracker...")
try:
    from utils.quota_tracker import QuotaTracker
    qt = QuotaTracker()
    qt.record_usage("nim", "daily", 100)
    can_use = qt.can_use("nim", "daily", 10000)
    print(f"  OK - can_use={can_use}, usage recorded")
except Exception as e:
    print(f"  FAIL - {e}")

# Test 3: Health Checker
print("\n[3/5] Testing HealthChecker...")
try:
    from utils.health_checker import HealthChecker
    hc_config = config.get("routing", {}).get("health_check", {})
    hc = HealthChecker(
        interval=hc_config.get("interval", 60),
        timeout=hc_config.get("timeout", 10),
    )
    print(f"  OK - HealthChecker initialized (interval={hc.interval}s, timeout={hc.timeout}s)")
except Exception as e:
    print(f"  FAIL - {e}")

# Test 4: Router
print("\n[4/5] Testing Router...")
try:
    from router import Router
    r = Router(pm, qt, hc, config)
    print(f"  OK - Router initialized")
    
    # Test routing strategy
    routing_config = config.get("routing", {})
    strategy_name = routing_config.get("strategy", "priority_fallback")
    print(f"  OK - Routing strategy: {strategy_name}")
except Exception as e:
    print(f"  FAIL - {e}")

# Test 5: FastAPI app
print("\n[5/5] Testing FastAPI app...")
try:
    from main import app
    routes = [r.path for r in app.routes]
    print(f"  OK - {len(routes)} routes: {routes}")
except Exception as e:
    print(f"  FAIL - {e}")

print("\n" + "=" * 50)
print("Test complete!")
print("=" * 50)
