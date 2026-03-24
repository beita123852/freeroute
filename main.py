import os
import sys
import yaml
import json
import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, Security, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from slowapi import Limiter
from slowapi.util import get_remote_address

from typing import Optional
from providers.manager import ProviderManager
from utils.quota_tracker import QuotaTracker
from utils.health_checker import HealthChecker
from router import Router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# API Key Authentication
# ---------------------------------------------------------------------------
security = HTTPBearer(auto_error=False)

async def verify_token(credentials: Optional[HTTPAuthorizationCredentials] = Security(security)):
    api_key = os.environ.get("FREEROUTE_API_KEY", "")
    if not api_key:
        return  # 未配置key则跳过认证
    if credentials is None or credentials.credentials != api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CONFIG_PATH = Path(__file__).parent / "config.yaml"

def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

# Load .env if present
def load_dotenv():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value

load_dotenv()

config = load_config()

# ---------------------------------------------------------------------------
# Init components
# ---------------------------------------------------------------------------
pm = ProviderManager(config)
qt = QuotaTracker()
hc_config = config.get("routing", {}).get("health_check", {})
hc = HealthChecker(
    interval=hc_config.get("interval", 60),
    timeout=hc_config.get("timeout", 10),
)
router = Router(pm, qt, hc, config)

# ---------------------------------------------------------------------------
# Background health checker
# ---------------------------------------------------------------------------
health_check_task = None

async def health_check_loop():
    """Periodically check provider health"""
    interval = hc_config.get("interval", 60)
    while True:
        for provider in pm.providers:
            try:
                healthy = await hc.check_provider_health(
                    provider["name"],
                    provider["base_url"],
                    provider["api_key"],
                    provider["models"],
                )
                if healthy:
                    pm.mark_healthy(provider["name"])
                else:
                    pm.mark_unhealthy(provider["name"])
            except Exception as e:
                logger.error(f"Health check error for {provider['name']}: {e}")
        await asyncio.sleep(interval)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global health_check_task
    if hc_config.get("enabled", True):
        health_check_task = asyncio.create_task(health_check_loop())
        logger.info("Health checker started")
    yield
    if health_check_task:
        health_check_task.cancel()

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="FreeRoute", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter


@app.post("/v1/chat/completions")
@limiter.limit("20/minute")
async def chat_completions(request: Request, _ = Security(verify_token)):
    body = await request.json()
    model = body.get("model", "")
    messages = body.get("messages", [])
    stream = body.get("stream", False)

    # Input validation
    if not model:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "model is required", "type": "invalid_request"}},
        )
    
    if not messages:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "messages array cannot be empty", "type": "invalid_request"}},
        )
    
    if len(messages) > 100:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "messages array cannot exceed 100 items", "type": "invalid_request"}},
        )
    
    for i, message in enumerate(messages):
        if not isinstance(message, dict):
            return JSONResponse(
                status_code=400,
                content={"error": {"message": f"message at index {i} must be an object", "type": "invalid_request"}},
            )
        
        if "role" not in message or "content" not in message:
            return JSONResponse(
                status_code=400,
                content={"error": {"message": f"message at index {i} must have role and content fields", "type": "invalid_request"}},
            )
        
        content = message.get("content", "")
        if isinstance(content, str) and len(content.encode('utf-8')) > 100 * 1024:  # 100KB
            return JSONResponse(
                status_code=400,
                content={"error": {"message": f"message content at index {i} exceeds 100KB limit", "type": "invalid_request"}},
            )

    # Build kwargs from body, excluding model and messages
    extra_kwargs = {k: v for k, v in body.items() if k not in ("model", "messages")}

    if stream:
        return StreamingResponse(
            router.route_stream(model, messages, **extra_kwargs),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )
    else:
        result = router.route_request(model, messages, **extra_kwargs)
        if result["success"]:
            return JSONResponse(content=result["data"])
        else:
            status_code = result.get("data", {}).get("error", {}).get("status_code", 502)
            return JSONResponse(status_code=502, content=result["data"])


@app.get("/v1/models")
@limiter.limit("20/minute")
async def list_models(request: Request, _ = Security(verify_token)):
    models = pm.get_all_models()
    return {
        "object": "list",
        "data": [
            {"id": m, "object": "model", "owned_by": "freeroute"} for m in models
        ],
    }


@app.get("/health")
async def health():
    provider_status = {}
    for name, info in hc.get_status().items():
        provider_status[name] = {
            "healthy": info["healthy"],
            "latency_ms": round(info["latency_ms"], 2) if info["latency_ms"] else None,
        }
    return {
        "status": "ok",
        "providers": provider_status,
    }


@app.get("/status")
async def status():
    return {
        "providers": pm.get_status(),
        "quota": qt.get_status(),
        "health": hc.get_status(),
    }


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    server_cfg = config.get("server", {})
    host = server_cfg.get("host", "127.0.0.1")
    port = server_cfg.get("port", 8090)
    log_level = config.get("logging", {}).get("level", "info").lower()

    logger.info(f"FreeRoute starting on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level=log_level)
