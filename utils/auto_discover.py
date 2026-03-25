import asyncio
import aiohttp
import logging
from typing import Dict, List, Set
from datetime import datetime

logger = logging.getLogger(__name__)

class AutoDiscovery:
    """Periodically discover new models from provider APIs"""
    
    def __init__(self, provider_manager, config: dict):
        self.pm = provider_manager
        discovery_config = config.get("discovery", {})
        self.enabled = discovery_config.get("enabled", False)
        self.interval = discovery_config.get("interval", 3600)  # 1 hour
        self.webhook_url = discovery_config.get("webhook_url", "")
        self.known_models: Dict[str, Set[str]] = {}  # provider_name -> set of model IDs
        self._task = None
        self._session = None
        
        # Initialize known models from config
        for provider in self.pm.providers:
            self.known_models[provider["name"]] = set(provider["models"])
    
    async def start(self):
        """Start discovery loop"""
        if not self.enabled:
            return
        self._session = aiohttp.ClientSession()
        self._task = asyncio.create_task(self._discovery_loop())
        logger.info("Auto-discovery started")
    
    async def stop(self):
        """Stop discovery loop"""
        if self._task:
            self._task.cancel()
        if self._session:
            await self._session.close()
    
    async def _discovery_loop(self):
        """Periodic discovery loop"""
        while True:
            try:
                await self._scan_all_providers()
            except Exception as e:
                logger.error(f"Discovery scan error: {e}")
            await asyncio.sleep(self.interval)
    
    async def _scan_all_providers(self):
        """Scan all providers for model changes"""
        for provider in self.pm.providers:
            try:
                models = await self._fetch_models(provider)
                if models is None:
                    continue
                
                current = set(models)
                known = self.known_models.get(provider["name"], set())
                
                new_models = current - known
                removed_models = known - current
                
                if new_models:
                    logger.info(f"New models found for {provider['name']}: {new_models}")
                    # Add to provider config
                    provider["models"].extend(new_models)
                    self.pm._rebuild_index()
                    await self._notify(
                        f"🆕 新模型发现 - {provider['name']}\n"
                        f"新增: {', '.join(new_models)}\n"
                        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                    )
                
                if removed_models:
                    logger.info(f"Models removed from {provider['name']}: {removed_models}")
                    # Remove from provider config
                    provider["models"] = [m for m in provider["models"] if m not in removed_models]
                    self.pm._rebuild_index()
                    await self._notify(
                        f"⚠️ 模型下线 - {provider['name']}\n"
                        f"下线: {', '.join(removed_models)}\n"
                        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                    )
                
                self.known_models[provider["name"]] = current
                
            except Exception as e:
                logger.warning(f"Discovery scan failed for {provider['name']}: {e}")
    
    async def _fetch_models(self, provider: dict) -> List[str] | None:
        """Fetch model list from provider's /models endpoint"""
        try:
            url = f"{provider['base_url']}/models"
            headers = {"Authorization": f"Bearer {provider['api_key']}"}
            async with self._session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = data.get("data", [])
                    return [m["id"] for m in models if "id" in m]
        except Exception as e:
            logger.debug(f"Failed to fetch models for {provider['name']}: {e}")
        return None
    
    async def _notify(self, message: str):
        """Send notification via webhook"""
        if not self.webhook_url:
            logger.info(f"Notification (no webhook): {message}")
            return
        try:
            async with self._session.post(
                self.webhook_url,
                json={"msg_type": "text", "content": {"text": message}},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"Webhook notification failed: {resp.status}")
        except Exception as e:
            logger.warning(f"Webhook notification error: {e}")
    
    def get_status(self) -> dict:
        """Get discovery status"""
        return {
            "enabled": self.enabled,
            "interval": self.interval,
            "has_webhook": bool(self.webhook_url),
            "known_models": {k: list(v) for k, v in self.known_models.items()}
        }