import time
import json
import asyncio
import logging
import random
from typing import Dict, List, Optional, AsyncGenerator, Callable
import httpx

logger = logging.getLogger(__name__)


class RoutingStrategy:
    """Base class for routing strategies"""
    
    def __init__(self, provider_manager, quota_tracker, health_checker, config: dict):
        self.pm = provider_manager
        self.qt = quota_tracker
        self.hc = health_checker
        self.config = config
    
    def select_provider(self, model: str, available_providers: List[dict]) -> dict:
        """Select a provider from the available list"""
        raise NotImplementedError("Subclasses must implement select_provider")


class PriorityFallbackStrategy(RoutingStrategy):
    """Priority-based fallback strategy (current default)"""
    
    def select_provider(self, model: str, available_providers: List[dict]) -> dict:
        """Select provider based on priority (highest priority first)"""
        if not available_providers:
            raise ValueError("No available providers")
        return available_providers[0]


class RoundRobinStrategy(RoutingStrategy):
    """Round-robin strategy for load balancing"""
    
    def __init__(self, provider_manager, quota_tracker, health_checker, config: dict):
        super().__init__(provider_manager, quota_tracker, health_checker, config)
        self.counters: Dict[str, int] = {}  # model_name -> counter
    
    def select_provider(self, model: str, available_providers: List[dict]) -> dict:
        """Select provider using round-robin algorithm"""
        if not available_providers:
            raise ValueError("No available providers")
        
        # Initialize counter for this model if not exists
        if model not in self.counters:
            self.counters[model] = 0
        
        # Get the next provider using modulo
        index = self.counters[model] % len(available_providers)
        selected_provider = available_providers[index]
        
        # Increment counter for next request
        self.counters[model] += 1
        
        return selected_provider


class LeastLatencyStrategy(RoutingStrategy):
    """Select provider with lowest latency"""
    
    def select_provider(self, model: str, available_providers: List[dict]) -> dict:
        """Select provider with the lowest latency"""
        if not available_providers:
            raise ValueError("No available providers")
        
        # Get latency for each provider and sort by latency
        providers_with_latency = []
        for provider in available_providers:
            latency = self.hc.get_latency(provider["name"])
            providers_with_latency.append((provider, latency or float('inf')))
        
        # Sort by latency (lowest first)
        providers_with_latency.sort(key=lambda x: x[1])
        
        # Return the provider with lowest latency
        return providers_with_latency[0][0]


class RandomStrategy(RoutingStrategy):
    """Random selection strategy"""
    
    def select_provider(self, model: str, available_providers: List[dict]) -> dict:
        """Randomly select a provider"""
        if not available_providers:
            raise ValueError("No available providers")
        return random.choice(available_providers)


class WeightedStrategy(RoutingStrategy):
    """Weighted random selection strategy"""
    
    def select_provider(self, model: str, available_providers: List[dict]) -> dict:
        """Select provider using weighted random"""
        if not available_providers:
            raise ValueError("No available providers")
        
        # Get weights from provider config (default weight=1)
        weights = []
        for provider in available_providers:
            weight = provider.get("weight", 1)
            weights.append(weight)
        
        # Weighted random selection
        total_weight = sum(weights)
        if total_weight == 0:
            return random.choice(available_providers)
        
        rand_val = random.uniform(0, total_weight)
        cumulative_weight = 0
        
        for i, weight in enumerate(weights):
            cumulative_weight += weight
            if rand_val <= cumulative_weight:
                return available_providers[i]
        
        # Fallback to random if something went wrong
        return random.choice(available_providers)


def get_routing_strategy(
    strategy_name: str, 
    provider_manager, 
    quota_tracker, 
    health_checker, 
    config: dict
) -> RoutingStrategy:
    """Factory function to get routing strategy instance"""
    strategies = {
        "priority_fallback": PriorityFallbackStrategy,
        "round_robin": RoundRobinStrategy,
        "least_latency": LeastLatencyStrategy,
        "random": RandomStrategy,
        "weighted": WeightedStrategy,
    }
    
    if strategy_name not in strategies:
        logger.warning(f"Unknown routing strategy '{strategy_name}', using 'priority_fallback'")
        strategy_name = "priority_fallback"
    
    strategy_class = strategies[strategy_name]
    return strategy_class(provider_manager, quota_tracker, health_checker, config)


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
    def __init__(self, provider_manager, quota_tracker, health_checker, config: dict, cache_manager=None):
        self.pm = provider_manager
        self.qt = quota_tracker
        self.hc = health_checker
        self.cache_manager = cache_manager
        routing_config = config.get("routing", {})
        self.timeout = routing_config.get("health_check", {}).get("timeout", 30)
        # Retry config
        retry_config = routing_config.get("retry", {})
        self.retry_max_attempts = retry_config.get("max_attempts", 3)
        self.retry_backoff_base = retry_config.get("backoff_base", 1)
        self.retryable_errors = retry_config.get("retryable_errors", ["timeout", "5xx"])
        
        # Routing strategy
        strategy_name = routing_config.get("strategy", "priority_fallback")
        self.strategy = get_routing_strategy(
            strategy_name, provider_manager, quota_tracker, health_checker, config
        )

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
                tokens_prompt = usage.get("prompt_tokens", 0)
                tokens_completion = usage.get("completion_tokens", 0)
                tokens_total = usage.get("total_tokens", 0)
                
                if tokens_total > 0 and provider.get("free_quota"):
                    quota_type = provider["free_quota"].get("type", "daily")
                    self.qt.record_usage(provider["name"], quota_type, tokens_total)

                logger.info(
                    f"OK provider={provider['name']} latency={latency:.0f}ms tokens={tokens_total}"
                )
                return {
                    "success": True, 
                    "data": data, 
                    "provider": provider["name"],
                    "latency_ms": latency,
                    "tokens_prompt": tokens_prompt,
                    "tokens_completion": tokens_completion,
                    "tokens_total": tokens_total
                }
            else:
                logger.warning(
                    f"FAIL provider={provider['name']} status={resp.status_code} latency={latency:.0f}ms"
                )
                return {
                    "success": False,
                    "error": f"Provider returned {resp.status_code}",
                    "status_code": resp.status_code,
                    "provider": provider["name"],
                    "latency_ms": latency
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
                "latency_ms": latency
            }
        except Exception as e:
            latency = (time.time() - start) * 1000
            logger.warning(f"ERROR provider={provider['name']} latency={latency:.0f}ms error={e}")
            return {
                "success": False,
                "error": str(e),
                "status_code": 0,
                "provider": provider["name"],
                "latency_ms": latency
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
        
        # Check cache first if enabled
        if self.cache_manager and self.cache_manager.enabled:
            cache_key = self.cache_manager.generate_key(model, messages, **kwargs)
            if cache_key:
                cached_response = self.cache_manager.get(cache_key)
                if cached_response:
                    logger.info(f"CACHE HIT model={model} key={cache_key[:8]}...")
                    return {
                        "success": True,
                        "data": cached_response["response"],
                        "provider": "cache",
                        "cached": True
                    }
                else:
                    logger.info(f"CACHE MISS model={model} key={cache_key[:8]}...")
        
        providers = self.pm.get_providers_for_model(model)
        if not providers:
            return self._error_response(f"Model '{model}' not found in any provider")

        last_error = None
        attempt = 0

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # Get available providers (healthy and with quota)
            available_providers = []
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
                available_providers.append(provider)

            if not available_providers:
                return self._error_response(f"No available providers for model '{model}'")

            # Use strategy to select provider
            try:
                provider = self.strategy.select_provider(model, available_providers)
            except Exception as e:
                logger.error(f"Strategy selection failed: {e}, falling back to priority")
                # Fallback to priority order
                available_providers.sort(key=lambda p: p["priority"])
                provider = available_providers[0]

            payload = self._build_request(provider, model, messages, **kwargs)

            # Retry loop for this provider
            for attempt in range(1, self.retry_max_attempts + 1):
                result = await self._forward_request(client, provider, payload)
                if result["success"]:
                    # Cache successful response
                    if self.cache_manager and self.cache_manager.enabled:
                        cache_key = self.cache_manager.generate_key(model, messages, **kwargs)
                        if cache_key:
                            self.cache_manager.set(cache_key, result["data"])
                            logger.info(f"CACHE SET model={model} key={cache_key[:8]}...")
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
            # Get available providers (healthy and with quota)
            available_providers = []
            for provider in providers:
                if not provider["healthy"]:
                    continue
                quota = provider.get("free_quota", {})
                if quota:
                    qtype = quota.get("type", "daily")
                    limit = quota.get("limit", 0)
                    if limit > 0 and not self.qt.can_use(provider["name"], qtype, limit):
                        continue
                available_providers.append(provider)

            if not available_providers:
                yield f"data: {json.dumps({'error': f'No available providers for model {model}'})}\n\n"
                yield "data: [DONE]\n\n"
                return

            # Use strategy to select provider
            try:
                provider = self.strategy.select_provider(model, available_providers)
            except Exception as e:
                logger.error(f"Strategy selection failed: {e}, falling back to priority")
                # Fallback to priority order
                available_providers.sort(key=lambda p: p["priority"])
                provider = available_providers[0]

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
