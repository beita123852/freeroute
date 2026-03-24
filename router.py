import time
import json
import asyncio
import logging
from typing import Dict, List, Optional, AsyncGenerator
import httpx

logger = logging.getLogger(__name__)


def _is_retryable(status_code: int, error_message: str, retryable_errors: list) -> bool:
    """Check if an error is retryable based on config"""
    msg_lower = (error_message or "").lower()
    # Timeout errors
    if "timeout" in msg_lower:
        return "timeout" in retryable_errors
    # 5xx server errors
    if status_code >= 500:
        return "5xx" in retryable_errors
    return False


class Router:
    def __init__(self, provider_manager, quota_tracker, health_checker, config: dict):
        self.pm = provider_manager
        self.qt = quota_tracker
        self.hc = health_checker
        routing_config = config.get("routing", {})
        self.timeout = routing_config.get("health_check", {}).get("timeout", 30)
        # Retry config
        retry_config = routing_config.get("retry", {})
        self.retry_max_attempts = retry_config.get("max_attempts", 3)
        self.retry_backoff_base = retry_config.get("backoff_base", 1)
        self.retryable_errors = retry_config.get("retryable_errors", ["timeout", "5xx"])

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

    async def _forward_request(self, client: httpx.AsyncClient, provider: dict, payload: dict) -> dict:
        """Forward request to provider and return response (async)"""
        url = f"{provider['base_url']}/chat/completions"
        headers = {
            "Authorization": f"Bearer {provider['api_key']}",
            "Content-Type": "application/json",
        }

        start = time.time()
        try:
            resp = await client.post(url, json=payload, headers=headers)
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
        except httpx.TimeoutException as e:
            latency = (time.time() - start) * 1000
            logger.warning(f"TIMEOUT provider={provider['name']} latency={latency:.0f}ms error={e}")
            return {
                "success": False,
                "error": f"Timeout: {e}",
                "status_code": 0,
                "provider": provider["name"],
                "is_timeout": True,
            }
        except Exception as e:
            latency = (time.time() - start) * 1000
            logger.warning(f"ERROR provider={provider['name']} latency={latency:.0f}ms error={e}")
            return {
                "success": False,
                "error": str(e),
                "status_code": 0,
                "provider": provider["name"],
            }

    async def _forward_stream(self, client: httpx.AsyncClient, provider: dict, payload: dict) -> AsyncGenerator[str, None]:
        """Forward streaming request and yield SSE lines (async)"""
        url = f"{provider['base_url']}/chat/completions"
        headers = {
            "Authorization": f"Bearer {provider['api_key']}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                raise Exception(f"Provider returned {resp.status_code}")
            async for line in resp.aiter_lines():
                if line:
                    yield f"{line}\n"

    async def route_request(self, model: str, messages: list, **kwargs) -> dict:
        """Route a non-streaming request through available providers with retry"""
        providers = self.pm.get_providers_for_model(model)
        if not providers:
            return self._error_response(f"Model '{model}' not found in any provider")

        last_error = None
        attempt = 0

        async with httpx.AsyncClient(timeout=self.timeout) as client:
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

                # Retry loop for this provider
                for attempt in range(1, self.retry_max_attempts + 1):
                    result = await self._forward_request(client, provider, payload)
                    if result["success"]:
                        return result

                    last_error = result
                    status_code = result.get("status_code", 0)
                    error_msg = result.get("error", "")

                    # Mark unhealthy on connection error
                    if status_code == 0 and not result.get("is_timeout"):
                        self.pm.mark_unhealthy(provider["name"])
                        break  # Don't retry unhealthy providers

                    # Check if retryable
                    if _is_retryable(
                        status_code if not result.get("is_timeout") else 0,
                        error_msg,
                        self.retryable_errors,
                    ):
                        if attempt < self.retry_max_attempts:
                            backoff = self.retry_backoff_base * (2 ** (attempt - 1))
                            logger.warning(
                                f"RETRY provider={provider['name']} attempt={attempt}/{self.retry_max_attempts} "
                                f"backoff={backoff}s error={error_msg}"
                            )
                            await asyncio.sleep(backoff)
                            continue
                        else:
                            logger.warning(
                                f"RETRY EXHAUSTED provider={provider['name']} attempts={attempt}"
                            )
                    else:
                        # Non-retryable error (e.g. 4xx auth), skip to next provider
                        logger.warning(
                            f"NON-RETRYABLE provider={provider['name']} status={status_code} error={error_msg}"
                        )
                        break

        return self._error_response(
            f"All providers failed. Last error: {last_error.get('error', 'unknown')}"
        )

    async def route_stream(self, model: str, messages: list, **kwargs) -> AsyncGenerator[str, None]:
        """Route a streaming request through available providers (async)"""
        providers = self.pm.get_providers_for_model(model)
        if not providers:
            yield f"data: {json.dumps({'error': f'Model {model} not found'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        async with httpx.AsyncClient(timeout=None) as client:
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

                # Retry loop for streaming
                for attempt in range(1, self.retry_max_attempts + 1):
                    try:
                        async for chunk in self._forward_stream(client, provider, payload):
                            yield chunk
                        logger.info(f"STREAM OK provider={provider['name']}")
                        return
                    except Exception as e:
                        logger.warning(
                            f"STREAM FAIL provider={provider['name']} attempt={attempt}/{self.retry_max_attempts} error={e}"
                        )
                        if attempt < self.retry_max_attempts:
                            backoff = self.retry_backoff_base * (2 ** (attempt - 1))
                            logger.info(f"STREAM RETRY backoff={backoff}s")
                            await asyncio.sleep(backoff)
                        else:
                            self.pm.mark_unhealthy(provider["name"])
                            break

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
