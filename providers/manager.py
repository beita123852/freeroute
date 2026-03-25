import os
import re
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class ProviderManager:
    def __init__(self, config: dict):
        self.providers: List[dict] = []
        self._load_providers(config.get("providers", []))
        # Build model -> providers index
        self._model_index: Dict[str, List[dict]] = {}
        self._rebuild_index()

    def _resolve_env_vars(self, value: str) -> str:
        """Resolve ${VAR_NAME} patterns from environment variables"""
        def replace(match):
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))
        return re.sub(r'\$\{(\w+)\}', replace, value)

    def _load_providers(self, provider_configs: list):
        for p in provider_configs:
            provider = {
                "name": p["name"],
                "type": p.get("type", "openai"),
                "base_url": p["base_url"],
                "api_key": self._resolve_env_vars(p.get("api_key", "")),
                "priority": p.get("priority", 99),
                "weight": p.get("weight", 1),  # Default weight=1
                "models": p.get("models", []),
                "healthy": True,  # assume healthy until proven otherwise
                "free_quota": p.get("free_quota", {}),
            }
            self.providers.append(provider)
            logger.info(f"Loaded provider: {provider['name']} (priority={provider['priority']}, weight={provider['weight']}, models={len(provider['models'])})")

    def _rebuild_index(self):
        """Rebuild model -> providers mapping, sorted by priority"""
        self._model_index = {}
        for provider in self.providers:
            for model in provider["models"]:
                if model not in self._model_index:
                    self._model_index[model] = []
                self._model_index[model].append(provider)
        # Sort each model's providers by priority
        for model in self._model_index:
            self._model_index[model].sort(key=lambda p: p["priority"])

    def get_providers_for_model(self, model_name: str) -> List[dict]:
        """Return providers supporting the model, sorted by priority"""
        return self._model_index.get(model_name, [])

    def get_all_models(self) -> List[str]:
        """Return all available model names"""
        return sorted(self._model_index.keys())

    def get_provider(self, name: str) -> Optional[dict]:
        """Get a single provider by name"""
        for p in self.providers:
            if p["name"] == name:
                return p
        return None

    def mark_unhealthy(self, name: str):
        provider = self.get_provider(name)
        if provider:
            provider["healthy"] = False
            logger.warning(f"Provider {name} marked unhealthy")

    def mark_healthy(self, name: str):
        provider = self.get_provider(name)
        if provider:
            provider["healthy"] = True
            logger.info(f"Provider {name} marked healthy")

    def is_healthy(self, name: str) -> bool:
        provider = self.get_provider(name)
        return provider["healthy"] if provider else False

    def get_status(self) -> dict:
        """Return status summary for all providers"""
        return {
            p["name"]: {
                "healthy": p["healthy"],
                "priority": p["priority"],
                "models": p["models"],
            }
            for p in self.providers
        }
