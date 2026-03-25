# FreeRoute Response Caching Feature

## Overview
FreeRoute now includes a sophisticated response caching layer that helps reduce API quota usage by caching identical requests.

## Features

- **SQLite-based Storage**: Uses local SQLite database for persistent caching
- **Smart Key Generation**: SHA256 hash of request parameters (model + messages + kwargs)
- **TTL Support**: Automatic expiration of cached responses
- **Statistics**: Track hits, misses, and token savings
- **Model Exclusion**: Configurable list of models to exclude from caching
- **Automatic Cleanup**: Background thread removes expired entries
- **Thread Safety**: Safe for concurrent access
- **API Endpoints**: RESTful endpoints for monitoring and management

## Configuration

Add the following to your `config.yaml`:

```yaml
cache:
  enabled: true
  ttl_seconds: 3600          # Default cache duration (1 hour)
  max_entries: 10000         # Maximum cache entries
  exclude_models: []         # Models to exclude from caching
  cleanup_interval: 3600     # Cleanup interval in seconds
```

## API Endpoints

### GET /api/cache/stats
Returns cache statistics:
```json
{
  "enabled": true,
  "hit_count": 5,
  "miss_count": 10,
  "hit_ratio": 0.333,
  "total_saved_tokens": 1500,
  "total_entries": 3,
  "total_size_bytes": 2048,
  "max_entries": 10000,
  "default_ttl": 3600,
  "exclude_models": []
}
```

### DELETE /api/cache
Clears all cache entries:
```json
{
  "success": true,
  "message": "Cache cleared"
}
```

### GET /status
Includes cache information in the status response.

## How It Works

1. **Request Processing**: When a non-streaming request arrives
2. **Key Generation**: Creates SHA256 hash of (model + sorted messages + sorted kwargs)
3. **Cache Check**: Looks for cached response
4. **Cache Hit**: Returns cached response immediately
5. **Cache Miss**: Forwards to providers, caches successful response
6. **Expiration**: Automatically removes entries after TTL

## Benefits

- **Reduced Quota Usage**: Identical requests use cached responses
- **Faster Response Times**: Cache hits return instantly
- **Cost Savings**: Reduces token consumption from providers
- **Statistics**: Monitor cache effectiveness

## Testing

Run the test suite:
```bash
python test_cache.py
python test_integration.py
```

## Notes

- Streaming requests are not cached due to complexity
- Cache keys are deterministic (same request = same key)
- Responses include token usage for accurate statistics
- Automatic cleanup prevents database bloat