import os
import sys
import yaml
import json
import asyncio
import logging
import time
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, Security, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from slowapi import Limiter
from slowapi.util import get_remote_address

from typing import Optional
from providers.manager import ProviderManager
from utils.quota_tracker import QuotaTracker
from utils.health_checker import HealthChecker
from utils.cache import CacheManager
from utils.request_logger import RequestLogger
from utils.auto_discover import AutoDiscovery
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

# Global counters for dashboard
start_time = time.time()
total_requests = 0

# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------
quota_monitor_task = None

async def quota_monitor_loop():
    """Monitor and log quota resets"""
    while True:
        try:
            status = qt.get_status()
            for provider, quotas in status.items():
                daily = quotas.get("daily", 0)
                monthly = quotas.get("monthly", 0)
                if daily > 0 or monthly > 0:
                    logger.debug(f"Quota status: {provider} daily={daily} monthly={monthly}")
        except Exception as e:
            logger.error(f"Quota monitor error: {e}")
        await asyncio.sleep(300)  # 每5分钟检查一次

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

# Initialize cache
cache_config = config.get("cache", {})
cache_manager = CacheManager(cache_config)

# Initialize request logger
request_logger = RequestLogger()

# Initialize auto discovery
auto_discovery = AutoDiscovery(pm, config)

router = Router(pm, qt, hc, config, cache_manager)

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
    global health_check_task, quota_monitor_task
    await hc.start()
    logger.info("HealthChecker session initialized")
    if hc_config.get("enabled", True):
        health_check_task = asyncio.create_task(health_check_loop())
        logger.info("Health checker started")
    
    # Start quota monitor
    quota_monitor_task = asyncio.create_task(quota_monitor_loop())
    logger.info("Quota monitor started")
    
    # Start auto discovery
    await auto_discovery.start()
    
    yield
    
    if health_check_task:
        health_check_task.cancel()
    if quota_monitor_task:
        quota_monitor_task.cancel()
    await auto_discovery.stop()
    await hc.close()
    logger.info("HealthChecker session closed")

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="FreeRoute", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter


@app.post("/v1/chat/completions")
@limiter.limit("20/minute")
async def chat_completions(request: Request, _ = Security(verify_token)):
    global total_requests
    
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
        result = await router.route_request(model, messages, **extra_kwargs)
        total_requests += 1  # Increment request counter
        
        # Log the request
        try:
            client_ip = request.client.host if request.client else "unknown"
            request_logger.log_request(
                model=model,
                provider=result.get("provider", "unknown"),
                status="success" if result["success"] else "fail",
                latency_ms=result.get("latency_ms"),
                tokens_prompt=result.get("tokens_prompt", 0),
                tokens_completion=result.get("tokens_completion", 0),
                tokens_total=result.get("tokens_total", 0),
                error_message=result.get("error") if not result["success"] else None,
                client_ip=client_ip
            )
        except Exception as e:
            logger.error(f"Failed to log request: {e}")
        
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
        "cache": cache_manager.stats(),
        "discovery": auto_discovery.get_status(),
    }


@app.get("/api/dashboard")
async def api_dashboard():
    """API endpoint for dashboard data"""
    provider_status = []
    health_status = hc.get_status()
    quota_status = qt.get_status()
    provider_status_info = pm.get_status()
    
    for provider_name in provider_status_info.keys():
        provider_info = pm.get_provider(provider_name)
        if provider_info:
            provider_status.append({
                "name": provider_name,
                "healthy": health_status.get(provider_name, {}).get("healthy", False),
                "latency_ms": health_status.get(provider_name, {}).get("latency_ms"),
                "quota": {
                    "used": quota_status.get(provider_name, {}).get("daily", 0),
                    "limit": provider_info.get("free_quota", {}).get("limit", 0),
                    "type": provider_info.get("free_quota", {}).get("type", "daily")
                },
                "models": provider_info.get("models", [])
            })
    
    return {
        "version": "0.2.0",
        "uptime_seconds": round(time.time() - start_time),
        "total_requests": total_requests,
        "providers": provider_status,
        "routing_strategy": config.get("routing", {}).get("strategy", "priority_fallback")
    }


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Dashboard HTML page"""
    html_content = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FreeRoute Dashboard</title>
    <style>
        :root {
            --bg-primary: #1a1a2e;
            --bg-card: #16213e;
            --text-primary: #e0e0e0;
            --text-secondary: #a0a0a0;
            --success: #4ade80;
            --danger: #f87171;
            --warning: #fbbf24;
            --info: #60a5fa;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            background-color: var(--bg-primary);
            color: var(--text-primary);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            padding: 20px;
        }
        
        .container {
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FreeRoute Dashboard</title>
    <style>
        :root {
            --bg: #0f172a; --card: #1e293b; --border: #334155;
            --text: #e2e8f0; --dim: #94a3b8;
            --green: #22c55e; --red: #ef4444; --yellow: #eab308; --blue: #3b82f6;
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        body { background:var(--bg); color:var(--text); font-family:system-ui,sans-serif; padding:20px; }
        h1 { font-size:24px; margin-bottom:20px; }
        .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px; margin-bottom:24px; }
        .card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; }
        .card h2 { font-size:14px; color:var(--dim); text-transform:uppercase; letter-spacing:1px; margin-bottom:12px; }
        .stat { font-size:36px; font-weight:700; }
        .stat small { font-size:14px; color:var(--dim); font-weight:400; }
        table { width:100%; border-collapse:collapse; }
        th,td { padding:10px 12px; text-align:left; border-bottom:1px solid var(--border); }
        th { color:var(--dim); font-size:12px; text-transform:uppercase; }
        .badge { display:inline-block; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:600; }
        .badge-green { background:#166534; color:#86efac; }
        .badge-red { background:#7f1d1d; color:#fca5a5; }
        .bar-bg { background:var(--border); border-radius:4px; height:8px; overflow:hidden; }
        .bar-fill { height:100%; border-radius:4px; transition:width 0.5s; }
        .refresh { color:var(--dim); font-size:12px; margin-top:16px; }
    </style>
</head>
<body>
    <h1>🚀 FreeRoute Dashboard</h1>
    <div class="grid">
        <div class="card">
            <h2>运行时间</h2>
            <div class="stat" id="uptime">--</div>
        </div>
        <div class="card">
            <h2>总请求数</h2>
            <div class="stat" id="requests">--</div>
        </div>
        <div class="card">
            <h2>健康 Provider</h2>
            <div class="stat" id="healthy">--</div>
        </div>
        <div class="card">
            <h2>路由策略</h2>
            <div class="stat" id="strategy" style="font-size:20px">--</div>
        </div>
    </div>
    <div class="card">
        <h2>Provider 状态</h2>
        <table>
            <thead><tr><th>Provider</th><th>状态</th><th>延迟</th><th>配额</th><th>模型</th></tr></thead>
            <tbody id="providers"></tbody>
        </table>
    </div>
    <div class="refresh">自动刷新: 10s | <span id="lastUpdate"></span></div>
    <script>
        function fmtTime(s) {
            if (!s) return '--';
            const h = Math.floor(s/3600), m = Math.floor((s%3600)/60);
            return h > 0 ? h+'h '+m+'m' : m+'m';
        }
        function render(d) {
            document.getElementById('uptime').textContent = fmtTime(d.uptime_seconds);
            document.getElementById('requests').textContent = d.total_requests || 0;
            const healthy = d.providers.filter(p=>p.healthy).length;
            document.getElementById('healthy').innerHTML = '<span style="color:var(--green)">'+healthy+'</span> / '+d.providers.length;
            document.getElementById('strategy').textContent = d.routing_strategy || '--';
            const tbody = document.getElementById('providers');
            tbody.innerHTML = d.providers.map(p => {
                const pct = p.quota.limit > 0 ? Math.min(100, p.quota.used/p.quota.limit*100) : 0;
                const color = p.healthy ? 'var(--green)' : 'var(--red)';
                const barColor = pct > 80 ? 'var(--red)' : pct > 50 ? 'var(--yellow)' : 'var(--green)';
                return `<tr>
                    <td><strong>${p.name}</strong></td>
                    <td><span class="badge ${p.healthy?'badge-green':'badge-red'}">${p.healthy?'健康':'异常'}</span></td>
                    <td>${p.latency_ms ? Math.round(p.latency_ms)+'ms' : '--'}</td>
                    <td>
                        <div style="display:flex;justify-content:space-between;margin-bottom:4px">
                            <span>${p.quota.used}/${p.quota.limit}</span>
                            <span style="color:var(--dim)">${p.quota.type}</span>
                        </div>
                        <div class="bar-bg"><div class="bar-fill" style="width:${pct}%;background:${barColor}"></div></div>
                    </td>
                    <td style="color:var(--dim);font-size:12px">${p.models.slice(0,2).join(', ')}${p.models.length>2?' +'+(p.models.length-2):''}</td>
                </tr>`;
            }).join('');
            document.getElementById('lastUpdate').textContent = '更新: '+new Date().toLocaleTimeString();
        }
        async function refresh() {
            try { const r = await fetch('/api/dashboard'); render(await r.json()); } catch(e) { console.error(e); }
        }
        refresh(); setInterval(refresh, 10000);
    </script>
</body>
</html>
    """
    return html_content

@app.delete("/api/cache")
async def clear_cache():
    """Clear all cache entries"""
    success = cache_manager.clear()
    return {"success": success, "message": "Cache cleared" if success else "Failed to clear cache"}


@app.get("/api/logs/recent")
async def get_recent_logs(limit: int = 100):
    """Get recent request logs"""
    logs = request_logger.get_recent(limit)
    return {
        "count": len(logs),
        "logs": logs
    }


@app.get("/api/logs/stats")
async def get_log_stats(hours: int = 24):
    """Get request statistics"""
    stats = request_logger.get_stats(hours)
    return stats


@app.get("/api/logs/stats/provider")
async def get_provider_stats(hours: int = 24):
    """Get request statistics by provider"""
    stats = request_logger.get_provider_stats(hours)
    return stats


@app.get("/api/logs/stats/model")
async def get_model_stats(hours: int = 24):
    """Get request statistics by model"""
    stats = request_logger.get_model_stats(hours)
    return stats


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    lines = []
    
    # Provider health
    for name, info in hc.get_status().items():
        healthy = 1 if info.get("healthy") else 0
        lines.append(f'freeroute_provider_healthy{{provider="{name}"}} {healthy}')
        latency = info.get("latency_ms")
        if latency is not None:
            lines.append(f'freeroute_provider_latency_ms{{provider="{name}"}} {latency:.2f}')
    
    # Quota usage
    for provider, quotas in qt.get_status().items():
        for qtype, usage in quotas.items():
            lines.append(f'freeroute_quota_usage{{provider="{provider}",type="{qtype}"}} {usage}')
    
    # Cache stats
    cs = cache_manager.stats()
    if cs.get("enabled"):
        lines.append(f'freeroute_cache_hit_total {cs["hit_count"]}')
        lines.append(f'freeroute_cache_miss_total {cs["miss_count"]}')
        lines.append(f'freeroute_cache_entries {cs["total_entries"]}')
        lines.append(f'freeroute_cache_saved_tokens {cs["total_saved_tokens"]}')
    
    # Request total and uptime
    lines.append(f'freeroute_requests_total {total_requests}')
    lines.append(f'freeroute_uptime_seconds {time.time() - start_time:.0f}')
    
    return Response(content="\n".join(lines) + "\n", media_type="text/plain")


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
