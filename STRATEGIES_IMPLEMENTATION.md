# FreeRoute Load Balancing Strategies Implementation

## Overview

This implementation adds 5 load balancing strategies to FreeRoute using the Strategy Pattern, making it easy to extend with new strategies in the future.

## Implemented Strategies

### 1. `priority_fallback` (Default)
- **Behavior**: Selects highest priority provider first
- **Usage**: Maintains existing behavior for backward compatibility
- **Config**: No additional configuration needed

### 2. `round_robin`
- **Behavior**: Cycles through providers in sequence for each model
- **Features**: Maintains separate counters per model
- **Usage**: Good for equal distribution across providers

### 3. `least_latency`
- **Behavior**: Selects provider with lowest measured latency
- **Data Source**: Uses latency data from HealthChecker
- **Features**: Falls back to next best if optimal provider unavailable
- **Usage**: Best for performance-sensitive applications

### 4. `random`
- **Behavior**: Randomly selects from available providers
- **Features**: Simple uniform distribution
- **Usage**: Good for basic load balancing

### 5. `weighted`
- **Behavior**: Weighted random selection based on provider weights
- **Config**: Add `weight` field to provider configurations
- **Features**: Higher weight = higher probability of selection
- **Usage**: Fine-grained control over traffic distribution

## Configuration

### config.yaml Changes

```yaml
routing:
  strategy: "priority_fallback"  # Options: priority_fallback, round_robin, least_latency, random, weighted
```

### Provider Weight Configuration

Add `weight` field to provider configs for weighted strategy:

```yaml
providers:
  - name: nim
    weight: 5      # Higher weight = more traffic
    # ... other fields
  
  - name: groq  
    weight: 3      # Medium weight
    # ... other fields

  - name: cerebras
    weight: 1      # Lower weight
    # ... other fields
```

## Architecture

### Strategy Pattern Implementation

1. **Base Class**: `RoutingStrategy` with abstract `select_provider()` method
2. **Concrete Strategies**: 5 implemented strategy classes
3. **Factory Function**: `get_routing_strategy()` for strategy instantiation
4. **Router Integration**: Router class now uses strategy pattern

### Key Files Modified

- `router.py`: Added strategy classes and integrated with Router
- `providers/manager.py`: Added weight field support
- `config.yaml`: Added strategy configuration and provider weights
- `test_routing_strategies.py`: Comprehensive strategy tests
- `demo_strategies.py`: Strategy demonstration script

## Backward Compatibility

- Default strategy remains `priority_fallback`
- Existing configurations continue to work unchanged
- No breaking changes to API or behavior

## Testing

### Test Files

1. **test_routing_strategies.py**: Unit tests for all strategies
2. **test_basic.py**: Updated to include strategy testing
3. **demo_strategies.py**: Demonstration of all strategies

### Test Coverage

- ✅ Priority fallback selection
- ✅ Round robin cycling behavior
- ✅ Least latency selection
- ✅ Random distribution  
- ✅ Weighted distribution
- ✅ Strategy factory
- ✅ Error handling and fallbacks

## Usage Examples

### Basic Configuration
```yaml
routing:
  strategy: "round_robin"
```

### Weighted Configuration
```yaml
routing:
  strategy: "weighted"

providers:
  - name: primary_provider
    weight: 8
    # ...
  
  - name: secondary_provider  
    weight: 2
    # ...
```

### Performance-Optimized Configuration
```yaml
routing:
  strategy: "least_latency"
```

## Extending with New Strategies

1. Create new class inheriting from `RoutingStrategy`
2. Implement `select_provider()` method
3. Add to `get_routing_strategy()` factory
4. Update config validation if needed
5. Add tests

Example new strategy:
```python
class CustomStrategy(RoutingStrategy):
    def select_provider(self, model: str, available_providers: List[dict]) -> dict:
        # Custom selection logic
        return available_providers[0]
```

## Performance Considerations

- **Round Robin**: O(1) per selection
- **Least Latency**: O(n log n) for sorting (n = number of providers)
- **Random**: O(1) per selection  
- **Weighted**: O(n) per selection
- **Priority Fallback**: O(1) per selection

All strategies maintain the existing fallback and retry behavior.

## Commit Summary

- ✅ Added 5 load balancing strategies
- ✅ Implemented Strategy Pattern
- ✅ Updated configuration system
- ✅ Added comprehensive tests
- ✅ Maintained backward compatibility
- ✅ Added documentation and examples
- ✅ Pushed to GitHub repository

This implementation provides a flexible foundation for future routing enhancements while maintaining the existing FreeRoute functionality.