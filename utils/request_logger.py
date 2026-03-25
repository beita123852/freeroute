import sqlite3
import threading
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class RequestLogger:
    def __init__(self, db_path: str = "data/requests.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        """Initialize database with required tables"""
        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    model TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    latency_ms INTEGER,
                    tokens_prompt INTEGER DEFAULT 0,
                    tokens_completion INTEGER DEFAULT 0,
                    tokens_total INTEGER DEFAULT 0,
                    error_message TEXT,
                    client_ip TEXT
                )
            """)
            conn.commit()
            conn.close()

    def log_request(
        self,
        model: str,
        provider: str,
        status: str,
        latency_ms: Optional[int] = None,
        tokens_prompt: int = 0,
        tokens_completion: int = 0,
        tokens_total: int = 0,
        error_message: Optional[str] = None,
        client_ip: Optional[str] = None
    ):
        """Log a request to the database"""
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                conn.execute(
                    """
                    INSERT INTO requests 
                    (model, provider, status, latency_ms, tokens_prompt, tokens_completion, tokens_total, error_message, client_ip)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (model, provider, status, latency_ms, tokens_prompt, tokens_completion, tokens_total, error_message, client_ip)
                )
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error(f"Failed to log request: {e}")

    def get_recent(self, limit: int = 100) -> List[Dict]:
        """Get recent request logs"""
        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT 
                    id, timestamp, model, provider, status, latency_ms,
                    tokens_prompt, tokens_completion, tokens_total, error_message, client_ip
                FROM requests 
                ORDER BY timestamp DESC 
                LIMIT ?
                """,
                (limit,)
            )
            rows = cursor.fetchall()
            conn.close()
            
            return [
                {
                    "id": row[0],
                    "timestamp": row[1],
                    "model": row[2],
                    "provider": row[3],
                    "status": row[4],
                    "latency_ms": row[5],
                    "tokens_prompt": row[6],
                    "tokens_completion": row[7],
                    "tokens_total": row[8],
                    "error_message": row[9],
                    "client_ip": row[10]
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Failed to get recent logs: {e}")
            return []

    def get_stats(self, hours: int = 24) -> Dict:
        """Get request statistics for the given time period"""
        try:
            since_time = datetime.now() - timedelta(hours=hours)
            
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.cursor()
            
            # Total requests
            cursor.execute(
                "SELECT COUNT(*) FROM requests WHERE timestamp >= ?",
                (since_time.isoformat(),)
            )
            total_requests = cursor.fetchone()[0]
            
            # Successful requests
            cursor.execute(
                "SELECT COUNT(*) FROM requests WHERE timestamp >= ? AND status = 'success'",
                (since_time.isoformat(),)
            )
            successful_requests = cursor.fetchone()[0]
            
            # Failed requests
            cursor.execute(
                "SELECT COUNT(*) FROM requests WHERE timestamp >= ? AND status = 'fail'",
                (since_time.isoformat(),)
            )
            failed_requests = cursor.fetchone()[0]
            
            # Average latency
            cursor.execute(
                "SELECT AVG(latency_ms) FROM requests WHERE timestamp >= ? AND latency_ms IS NOT NULL",
                (since_time.isoformat(),)
            )
            avg_latency = cursor.fetchone()[0] or 0
            
            # Total tokens
            cursor.execute(
                "SELECT SUM(tokens_total) FROM requests WHERE timestamp >= ?",
                (since_time.isoformat(),)
            )
            total_tokens = cursor.fetchone()[0] or 0
            
            conn.close()
            
            return {
                "total_requests": total_requests,
                "successful_requests": successful_requests,
                "failed_requests": failed_requests,
                "success_rate": successful_requests / total_requests * 100 if total_requests > 0 else 0,
                "avg_latency_ms": round(avg_latency, 2),
                "total_tokens": total_tokens
            }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "success_rate": 0,
                "avg_latency_ms": 0,
                "total_tokens": 0
            }

    def get_provider_stats(self, hours: int = 24) -> Dict[str, Dict]:
        """Get request statistics by provider"""
        try:
            since_time = datetime.now() - timedelta(hours=hours)
            
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.cursor()
            
            cursor.execute(
                """
                SELECT 
                    provider,
                    COUNT(*) as total_requests,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful_requests,
                    SUM(CASE WHEN status = 'fail' THEN 1 ELSE 0 END) as failed_requests,
                    AVG(latency_ms) as avg_latency,
                    SUM(tokens_total) as total_tokens
                FROM requests 
                WHERE timestamp >= ?
                GROUP BY provider
                """,
                (since_time.isoformat(),)
            )
            
            rows = cursor.fetchall()
            conn.close()
            
            stats = {}
            for row in rows:
                provider = row[0]
                stats[provider] = {
                    "total_requests": row[1],
                    "successful_requests": row[2],
                    "failed_requests": row[3],
                    "avg_latency_ms": round(row[4] or 0, 2),
                    "total_tokens": row[5] or 0,
                    "success_rate": row[2] / row[1] * 100 if row[1] > 0 else 0
                }
            
            return stats
        except Exception as e:
            logger.error(f"Failed to get provider stats: {e}")
            return {}

    def get_model_stats(self, hours: int = 24) -> Dict[str, Dict]:
        """Get request statistics by model"""
        try:
            since_time = datetime.now() - timedelta(hours=hours)
            
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.cursor()
            
            cursor.execute(
                """
                SELECT 
                    model,
                    COUNT(*) as total_requests,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful_requests,
                    SUM(CASE WHEN status = 'fail' THEN 1 ELSE 0 END) as failed_requests,
                    AVG(latency_ms) as avg_latency,
                    SUM(tokens_total) as total_tokens
                FROM requests 
                WHERE timestamp >= ?
                GROUP BY model
                """,
                (since_time.isoformat(),)
            )
            
            rows = cursor.fetchall()
            conn.close()
            
            stats = {}
            for row in rows:
                model = row[0]
                stats[model] = {
                    "total_requests": row[1],
                    "successful_requests": row[2],
                    "failed_requests": row[3],
                    "avg_latency_ms": round(row[4] or 0, 2),
                    "total_tokens": row[5] or 0,
                    "success_rate": row[2] / row[1] * 100 if row[1] > 0 else 0
                }
            
            return stats
        except Exception as e:
            logger.error(f"Failed to get model stats: {e}")
            return {}