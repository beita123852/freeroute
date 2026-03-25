import asyncio
import time
from typing import Dict, List, Optional
import aiohttp
import logging

logger = logging.getLogger(__name__)


class HealthChecker:
    def __init__(self, interval: int = 60, timeout: int = 10):
        self.interval = interval
        self.timeout = timeout
        self.health_status: Dict[str, bool] = {}  # provider_name -> is_healthy
        self.latencies: Dict[str, float] = {}  # provider_name -> latency_ms
        self.last_check: Dict[str, float] = {}  # provider_name -> last_check_time
        self._session: Optional[aiohttp.ClientSession] = None

    async def start(self):
        """Initialize persistent ClientSession"""
        if self._session is None:
            self._session = aiohttp.ClientSession()

    async def close(self):
        """Close persistent ClientSession"""
        if self._session:
            await self._session.close()
            self._session = None

    async def check_provider_health(self, provider_name: str, base_url: str, api_key: str, provider_models: list) -> bool:
        """Check if a provider is healthy via lightweight /models endpoint"""
        try:
            start_time = time.time()

            # Use persistent session if available, otherwise create temporary one
            session = self._session
            temp_session = None
            if session is None:
                temp_session = aiohttp.ClientSession()
                session = temp_session

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }

            try:
                async with session.get(
                    f"{base_url}/models",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    if response.status == 200:
                        latency = (time.time() - start_time) * 1000
                        self.latencies[provider_name] = latency
                        self.health_status[provider_name] = True
                        self.last_check[provider_name] = time.time()
                        logger.info(f"Health check passed for {provider_name}, latency: {latency:.2f}ms")
                        return True
                    else:
                        self.health_status[provider_name] = False
                        self.last_check[provider_name] = time.time()
                        logger.warning(f"Health check failed for {provider_name}: HTTP {response.status}")
                        return False
            finally:
                if temp_session:
                    await temp_session.close()

        except (aiohttp.ClientError, asyncio.TimeoutError, Exception) as e:
            logger.warning(f"Health check failed for {provider_name}: {e}")
            self.health_status[provider_name] = False
            self.last_check[provider_name] = time.time()
            return False

    def is_healthy(self, provider_name: str) -> bool:
        """Check if provider is currently healthy"""
        return self.health_status.get(provider_name, False)
    
    def get_latency(self, provider_name: str) -> Optional[float]:
        """Get last recorded latency for provider"""
        return self.latencies.get(provider_name)
    
    def get_last_check(self, provider_name: str) -> Optional[float]:
        """Get last check time for provider"""
        return self.last_check.get(provider_name)
    
    def get_status(self) -> Dict[str, Dict]:
        """Get health status for all providers"""
        status = {}
        for provider_name in self.health_status.keys():
            status[provider_name] = {
                "healthy": self.health_status[provider_name],
                "latency_ms": self.latencies.get(provider_name),
                "last_check": self.last_check.get(provider_name)
            }
        return status