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

    async def check_provider_health(self, provider_name: str, base_url: str, api_key: str, provider_models: list) -> bool:
        """Check if a provider is healthy by sending a lightweight test request"""
        try:
            start_time = time.time()
            
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                
                # Try to get models list first
                async with session.get(
                    f"{base_url}/models", 
                    headers=headers, 
                    timeout=self.timeout
                ) as response:
                    if response.status == 200:
                        latency = (time.time() - start_time) * 1000
                        self.latencies[provider_name] = latency
                        self.health_status[provider_name] = True
                        self.last_check[provider_name] = time.time()
                        logger.info(f"Health check passed for {provider_name}, latency: {latency:.2f}ms")
                        return True
                    
                # If models endpoint fails, try a simple chat completion
                # Use the first available model from the provider
                test_model = provider_models[0] if provider_models else "gpt-3.5-turbo"
                payload = {
                    "model": test_model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 5
                }
                
                async with session.post(
                    f"{base_url}/chat/completions", 
                    headers=headers, 
                    json=payload,
                    timeout=self.timeout
                ) as response:
                    if response.status == 200:
                        latency = (time.time() - start_time) * 1000
                        self.latencies[provider_name] = latency
                        self.health_status[provider_name] = True
                        self.last_check[provider_name] = time.time()
                        logger.info(f"Health check passed for {provider_name}, latency: {latency:.2f}ms")
                        return True
        
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