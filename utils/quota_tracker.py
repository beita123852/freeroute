import time
from typing import Dict, Tuple
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class QuotaTracker:
    def __init__(self):
        self.usage: Dict[str, Dict[str, int]] = {}  # provider_name -> {"daily": count, "monthly": count}
        self.reset_times: Dict[str, Dict[str, float]] = {}  # provider_name -> {"daily": timestamp, "monthly": timestamp}

    def _ensure_provider_exists(self, provider_name: str):
        if provider_name not in self.usage:
            self.usage[provider_name] = {"daily": 0, "monthly": 0}
        if provider_name not in self.reset_times:
            self.reset_times[provider_name] = {"daily": 0, "monthly": 0}

    def _check_and_reset_quota(self, provider_name: str, quota_type: str):
        """Check if quota needs reset and reset if necessary"""
        self._ensure_provider_exists(provider_name)
        
        now = time.time()
        last_reset = self.reset_times[provider_name].get(quota_type, 0)
        
        if quota_type == "daily":
            # Reset daily at midnight
            if datetime.fromtimestamp(now).date() != datetime.fromtimestamp(last_reset).date():
                self.usage[provider_name]["daily"] = 0
                self.reset_times[provider_name]["daily"] = now
        elif quota_type == "monthly":
            # Reset monthly on 1st day of month
            if datetime.fromtimestamp(now).month != datetime.fromtimestamp(last_reset).month:
                self.usage[provider_name]["monthly"] = 0
                self.reset_times[provider_name]["monthly"] = now

    def can_use(self, provider_name: str, quota_type: str, limit: int) -> bool:
        """Check if provider can be used within quota limits"""
        self._check_and_reset_quota(provider_name, quota_type)
        
        current_usage = self.usage[provider_name].get(quota_type, 0)
        return current_usage < limit

    def record_usage(self, provider_name: str, quota_type: str, tokens_used: int):
        """Record token usage for a provider"""
        self._ensure_provider_exists(provider_name)
        self._check_and_reset_quota(provider_name, quota_type)
        
        self.usage[provider_name][quota_type] += tokens_used
        logger.info(f"Recorded {tokens_used} tokens usage for {provider_name} ({quota_type})")

    def get_usage(self, provider_name: str, quota_type: str) -> int:
        """Get current usage for a provider"""
        self._check_and_reset_quota(provider_name, quota_type)
        return self.usage[provider_name].get(quota_type, 0)

    def get_status(self) -> Dict[str, Dict[str, int]]:
        """Get usage status for all providers"""
        status = {}
        for provider_name in self.usage.keys():
            self._check_and_reset_quota(provider_name, "daily")
            self._check_and_reset_quota(provider_name, "monthly")
            status[provider_name] = {
                "daily": self.usage[provider_name]["daily"],
                "monthly": self.usage[provider_name]["monthly"]
            }
        return status