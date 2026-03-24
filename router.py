import time
import json
import logging
from typing import Dict, List, Optional, Generator
import httpx

logger = logging.getLogger(__name__)


class Router:
    def __init__(self, provider_manager, quota_tracker, health_checker, config: dict):
        self.pm = provider_manager
        self.qt = quota_tracker
        self.hc = health_checker
        self.timeout = config.get("routing", {}).get("health_check", {}).get("timeout", 30)

    def _build_request(self, provider: dict, model: str, messages: list, **kwargs) -> dict:
        """Build OpenAI-compatible request for the provider"""
        payload = {
            "model": model,
            "messages": messages,
        }
        # Pass through optional parameters
        for key in ["temperature", "max_tokens", "top_p", "stream", "stop", "presence_penalty", "frequency_penalty"]:
            if key in kwargs:
                payload[key] = kwargs[key]
        return payload

    def _forward_request(self, provider: dict, payload: dict) -> dict:
        """Forward request to provider and return response"""
        url = f"{provider['base_url']}/chat/completions"
        headers = {
            "Authorization": f"Bearer {provider['api_key']}",
            "Content-Type": "application/json",
        }

        start = time.time()
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
            latency = (time.time() - start) * 1000

            if resp.status_code == 200:
                data = resp.json()
                # Record token usage
                usage = data.get("usage", {})
                tokens = usage.get("total_tokens", 0)
                if tokens > 0 and provider.get("free_quota"):
                    quota_type = provider["free_quota"].get("type", "daily")
                    self.qt.record_usage(provider["name"], quota_type, tokens)

                logger.info(
                    f"OK provider={provider['name']} latency={latency:.0f}ms tokens={tokens}"
                )
                return {"success": True, "data": data, "provider": provider["name"]}
            else:
                logger.warning(
                    f"FAIL provider={provider['name']} status={resp.status_code} latency={latency:.0f}ms"
                )
                return {
                    "success": False,
                    "error": f"Provider returned {resp.status_code}",
                    "status_code": resp.status_code,
                    "provider": provider["name"],
                }

    def _forward_stream(self, provider: dict, payload: dict) -> Generator[str, None, None]:
        """Forward streaming request and yield SSE lines"""
        url = f"{provider['base_url']}/chat/completions"
        headers = {
            "Authorization": f"Bearer {provider['api_key']}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        with httpx.Client(timeout=None) as client:
            with client.stream("POST", url, json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    raise Exception(f"Provider returned {resp.status_code}")
                for line in resp.iter_lines():
                    if line:
                        yield f"{line}\n"

    def route_request(self, model: str, messages: list, **kwargs) -> dict:
        """Route a non-streaming request through available providers"""
        providers = self.pm.get_providers_for_model(model)
        if not providers:
            return self._error_response(f"Model '{model}' not found in any provider")

        last_error = None
        for provider in providers:
            # Skip unhealthy
            if not provider["healthy"]:
                continue
            # Skip quota exhausted
            quota = provider.get("free_quota", {})
            if quota:
                qtype = quota.get("type", "daily")
                limit = quota.get("limit", 0)
                if limit > 0 and not self.qt.can_use(provider["name"], qtype, limit):
                    logger.info(f"SKIP provider={provider['name']} reason=quota_exhausted")
                    continue

            payload = self._build_request(provider, model, messages, **kwargs)
            result = self._forward_request(provider, payload)
            if result["success"]:
                return result
            else:
                last_error = result
                # Mark unhealthy if connection error
                if result.get("status_code", 0) == 0:
                    self.pm.mark_unhealthy(provider["name"])

        return self._error_response(
            f"All providers failed. Last error: {last_error.get('error', 'unknown')}"
        )

    def route_stream(self, model: str, messages: list, **kwargs) -> Generator[str, None, None]:
        """Route a streaming request through available providers"""
        providers = self.pm.get_providers_for_model(model)
        if not providers:
            yield f"data: {json.dumps({'error': f'Model {model} not found'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        for provider in providers:
            if not provider["healthy"]:
                continue
            quota = provider.get("free_quota", {})
            if quota:
                qtype = quota.get("type", "daily")
                limit = quota.get("limit", 0)
                if limit > 0 and not self.qt.can_use(provider["name"], qtype, limit):
                    continue

            kwargs["stream"] = True
            payload = self._build_request(provider, model, messages, **kwargs)
            try:
                for chunk in self._forward_stream(provider, payload):
                    yield chunk
                logger.info(f"STREAM OK provider={provider['name']}")
                return
            except Exception as e:
                logger.warning(f"STREAM FAIL provider={provider['name']} error={e}")
                self.pm.mark_unhealthy(provider["name"])
                continue

        yield f"data: {json.dumps({'error': 'All providers failed for streaming'})}\n\n"
        yield "data: [DONE]\n\n"

    def _error_response(self, message: str) -> dict:
        """Return standard OpenAI-format error"""
        return {
            "success": False,
            "data": {
                "error": {
                    "message": message,
                    "type": "api_error",
                    "code": "all_providers_failed",
                }
            },
        }
