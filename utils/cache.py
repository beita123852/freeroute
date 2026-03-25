import sqlite3
import json
import hashlib
import time
import threading
from typing import Optional, Dict, Any
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class CacheManager:
    """SQLite-based response cache for FreeRoute"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.enabled = config.get("enabled", False)
        self.default_ttl = config.get("ttl_seconds", 3600)
        self.max_entries = config.get("max_entries", 10000)
        self.exclude_models = set(config.get("exclude_models", []))
        self.cleanup_interval = config.get("cleanup_interval", 3600)
        
        # Initialize counters
        self.hit_count = 0
        self.miss_count = 0
        self.total_saved_tokens = 0
        
        # Thread safety
        self._lock = threading.RLock()
        
        if self.enabled:
            self._init_db()
            self._start_cleanup_timer()
    
    def _init_db(self):
        """Initialize SQLite database"""
        data_dir = Path(__file__).parent.parent / "data"
        data_dir.mkdir(exist_ok=True)
        
        db_path = data_dir / "cache.db"
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                response TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                ttl_seconds INTEGER NOT NULL,
                tokens_total INTEGER DEFAULT 0
            )
        """)
        
        # Create indexes
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON cache(created_at)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_expiry ON cache(created_at + ttl_seconds)")
        self.conn.commit()
    
    def _start_cleanup_timer(self):
        """Start periodic cleanup timer"""
        def cleanup_loop():
            while True:
                time.sleep(self.cleanup_interval)
                self.cleanup()
        
        thread = threading.Thread(target=cleanup_loop, daemon=True)
        thread.start()
    
    def generate_key(self, model: str, messages: list, **kwargs) -> str:
        """Generate cache key from request parameters"""
        if not self.enabled:
            return ""
        
        if model in self.exclude_models:
            return ""
        
        # Create a canonical representation of the request
        request_data = {
            "model": model,
            "messages": messages,
            **kwargs
        }
        
        # Sort kwargs for consistent hashing
        sorted_kwargs = dict(sorted(kwargs.items()))
        request_data.update(sorted_kwargs)
        
        # Convert to JSON string and hash
        request_str = json.dumps(request_data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(request_str.encode('utf-8')).hexdigest()
    
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Get cached response if not expired"""
        if not self.enabled or not key:
            self.miss_count += 1
            return None
        
        with self._lock:
            try:
                cursor = self.conn.execute(
                    "SELECT response, created_at, ttl_seconds, tokens_total FROM cache WHERE key = ?",
                    (key,)
                )
                row = cursor.fetchone()
                
                if not row:
                    self.miss_count += 1
                    return None
                
                response_str, created_at, ttl_seconds, tokens_total = row
                
                # Check if expired
                current_time = int(time.time())
                if current_time > created_at + ttl_seconds:
                    # Remove expired entry
                    self.conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                    self.conn.commit()
                    self.miss_count += 1
                    return None
                
                # Cache hit
                self.hit_count += 1
                self.total_saved_tokens += tokens_total
                
                return {
                    "response": json.loads(response_str),
                    "tokens_total": tokens_total
                }
                
            except Exception as e:
                logger.error(f"Cache get error: {e}")
                self.miss_count += 1
                return None
    
    def set(self, key: str, response: Dict[str, Any], ttl_seconds: Optional[int] = None) -> bool:
        """Cache a response"""
        if not self.enabled or not key:
            return False
        
        ttl = ttl_seconds or self.default_ttl
        created_at = int(time.time())
        
        # Extract token usage for statistics
        tokens_total = response.get("usage", {}).get("total_tokens", 0)
        
        try:
            response_str = json.dumps(response)
            
            with self._lock:
                # Check if we need to evict oldest entries
                if self.max_entries > 0:
                    count = self.conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
                    if count >= self.max_entries:
                        # Remove oldest entries to make space
                        oldest_keys = self.conn.execute(
                            "SELECT key FROM cache ORDER BY created_at ASC LIMIT ?",
                            (count - self.max_entries + 1,)
                        ).fetchall()
                        
                        if oldest_keys:
                            placeholders = ','.join(['?'] * len(oldest_keys))
                            self.conn.execute(
                                f"DELETE FROM cache WHERE key IN ({placeholders})",
                                [key[0] for key in oldest_keys]
                            )
                
                # Insert or replace
                self.conn.execute(
                    """INSERT OR REPLACE INTO cache (key, response, created_at, ttl_seconds, tokens_total)
                       VALUES (?, ?, ?, ?, ?)""",
                    (key, response_str, created_at, ttl, tokens_total)
                )
                self.conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Cache set error: {e}")
            return False
    
    def clear(self) -> bool:
        """Clear all cache entries"""
        if not self.enabled:
            return False
        
        try:
            with self._lock:
                self.conn.execute("DELETE FROM cache")
                self.conn.commit()
                # Reset counters
                self.hit_count = 0
                self.miss_count = 0
                self.total_saved_tokens = 0
                return True
        except Exception as e:
            logger.error(f"Cache clear error: {e}")
            return False
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        if not self.enabled:
            return {"enabled": False}
        
        try:
            with self._lock:
                total_entries = self.conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
                total_size = self.conn.execute("SELECT SUM(LENGTH(response)) FROM cache").fetchone()[0] or 0
                
                return {
                    "enabled": True,
                    "hit_count": self.hit_count,
                    "miss_count": self.miss_count,
                    "hit_ratio": self.hit_count / (self.hit_count + self.miss_count) if (self.hit_count + self.miss_count) > 0 else 0,
                    "total_saved_tokens": self.total_saved_tokens,
                    "total_entries": total_entries,
                    "total_size_bytes": total_size,
                    "max_entries": self.max_entries,
                    "default_ttl": self.default_ttl,
                    "exclude_models": list(self.exclude_models)
                }
        except Exception as e:
            logger.error(f"Cache stats error: {e}")
            return {"enabled": False, "error": str(e)}
    
    def cleanup(self) -> int:
        """Remove expired cache entries"""
        if not self.enabled:
            return 0
        
        try:
            current_time = int(time.time())
            with self._lock:
                result = self.conn.execute(
                    "DELETE FROM cache WHERE created_at + ttl_seconds < ?",
                    (current_time,)
                )
                deleted_count = result.rowcount
                self.conn.commit()
                logger.info(f"Cache cleanup removed {deleted_count} expired entries")
                return deleted_count
        except Exception as e:
            logger.error(f"Cache cleanup error: {e}")
            return 0
    
    def close(self):
        """Close database connection"""
        if hasattr(self, 'conn'):
            self.conn.close()