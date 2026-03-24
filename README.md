# 🚀 FreeRoute

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-green.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-darkgreen.svg)](https://fastapi.tiangolo.com)

**FreeRoute** 是一个免费 LLM API 聚合代理，提供统一的 OpenAI 兼容接口，将请求智能路由到多个免费 API Provider，支持自动故障转移。

## ✨ 核心亮点

- **🎯 OpenAI 兼容** — 无缝对接任何使用 OpenAI SDK 的客户端，零改动迁移
- **🔄 智能路由** — 基于优先级的多 Provider 自动故障转移，一个挂了切下一个
- **📊 配额追踪** — 内置日/月配额管理，防止免费额度超限
- **💚 健康检查** — 定时检测 Provider 可用性，自动标记/恢复
- **⚡ 流式支持** — 完整支持 SSE 流式响应
- **🔐 可选认证** — 内置 Bearer Token 认证，一行配置开启
- **🛡️ 速率限制** — 内置请求频率限制（20 次/分钟）
- **📝 YAML 配置** — 一个文件搞定所有配置

## 🏗️ 架构简图

```
┌─────────────────────────────────────────────────────────────┐
│                      Client (OpenAI SDK)                     │
│                    ↓ POST /v1/chat/completions               │
├─────────────────────────────────────────────────────────────┤
│                       FreeRoute Server                       │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │ Rate     │→ │ Router       │→ │ Provider Manager       │ │
│  │ Limiter  │  │ (priority    │  │ (env var resolution,   │ │
│  └──────────┘  │  fallback)   │  │  health-aware routing) │ │
│                └──────────────┘  └────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  Background Tasks                                       ││
│  │  • Health Checker (periodic ping)                       ││
│  │  • Quota Tracker (daily/monthly usage)                  ││
│  └─────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────┤
│         ↓              ↓               ↓                     │
│  ┌──────────┐   ┌──────────┐    ┌───────────┐              │
│  │ NIM      │   │OpenRouter│    │ Ollama    │              │
│  │ (pri 1)  │   │ (pri 2)  │    │ (pri 3)   │              │
│  └──────────┘   └──────────┘    └───────────┘              │
└─────────────────────────────────────────────────────────────┘
```

## ⚡ 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/beita123852/freeroute.git
cd freeroute
```

### 2. 安装依赖

```bash
pip install fastapi uvicorn httpx pyyaml python-dotenv slowapi
```

### 3. 配置环境变量

创建 `.env` 文件（或在环境中设置）：

```bash
NIM_API_KEY=your_nvidia_api_key
OPENROUTER_API_KEY=your_openrouter_api_key
OLLAMA_CLOUD_API_KEY=your_ollama_api_key

# 可选：启用 API 认证
FREEROUTE_API_KEY=your_custom_key
```

> 💡 至少配置一个 Provider 的 API Key 即可运行。

### 4. 启动服务

```bash
python main.py
```

服务默认启动在 `http://127.0.0.1:8090`。

## 📖 配置说明

配置文件为 `config.yaml`，完整示例：

```yaml
server:
  host: "127.0.0.1"     # 监听地址
  port: 8090             # 监听端口

providers:
  - name: nim                         # Provider 名称（唯一标识）
    type: openai                      # API 类型（当前仅支持 openai）
    base_url: "https://integrate.api.nvidia.com/v1"  # API 端点
    api_key: "${NIM_API_KEY}"         # 支持环境变量引用 ${VAR_NAME}
    priority: 1                       # 优先级（数字越小越优先）
    models:                           # 该 Provider 支持的模型列表
      - deepseek-ai/deepseek-v3.1
      - meta/llama-3.3-70b-instruct
    free_quota:                       # 配额限制（可选）
      type: "daily"                   # daily | monthly
      limit: 1000                     # 请求次数上限

routing:
  strategy: "priority_fallback"       # 路由策略（目前仅此一种）
  health_check:
    enabled: true                     # 是否启用健康检查
    interval: 60                      # 检查间隔（秒）
    timeout: 10                       # 单次检查超时（秒）

logging:
  level: "INFO"                       # 日志级别
```

### 字段详解

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `server.host` | 服务监听地址 | `127.0.0.1` |
| `server.port` | 服务监听端口 | `8090` |
| `providers[].name` | Provider 唯一名称 | — |
| `providers[].type` | API 协议类型 | `openai` |
| `providers[].base_url` | API 基础 URL | — |
| `providers[].api_key` | API 密钥（支持 `${VAR}` 语法） | `""` |
| `providers[].priority` | 路由优先级（越小越优先） | `99` |
| `providers[].models` | 支持的模型 ID 列表 | `[]` |
| `providers[].free_quota.type` | 配额周期 | — |
| `providers[].free_quota.limit` | 配额上限（请求次数） | — |
| `routing.strategy` | 路由策略 | `priority_fallback` |
| `routing.health_check.enabled` | 启用健康检查 | `true` |
| `routing.health_check.interval` | 检查间隔（秒） | `60` |
| `routing.health_check.timeout` | 检查超时（秒） | `10` |
| `logging.level` | 日志级别 | `INFO` |

## 🔌 API 接口

### POST /v1/chat/completions

OpenAI 兼容的聊天补全接口。

**请求示例：**

```bash
curl -X POST http://127.0.0.1:8090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_key" \  # 如果启用了认证
  -d '{
    "model": "deepseek-ai/deepseek-v3.1",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ],
    "stream": false
  }'
```

**流式响应：**

```bash
curl -X POST http://127.0.0.1:8090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-ai/deepseek-v3.1",
    "messages": [{"role": "user", "content": "Tell me a story"}],
    "stream": true
  }'
```

**支持的参数：** `model`, `messages`, `stream`, `temperature`, `max_tokens`, `top_p`, `stop`, `presence_penalty`, `frequency_penalty`

### GET /v1/models

列出所有可用模型。

```bash
curl http://127.0.0.1:8090/v1/models
```

**响应：**

```json
{
  "object": "list",
  "data": [
    {"id": "deepseek-ai/deepseek-v3.1", "object": "model", "owned_by": "freeroute"},
    {"id": "meta/llama-3.3-70b-instruct", "object": "model", "owned_by": "freeroute"}
  ]
}
```

### GET /health

健康检查端点。

```bash
curl http://127.0.0.1:8090/health
```

### GET /status

完整状态（Provider、配额、健康状态）。

```bash
curl http://127.0.0.1:8090/status
```

## 📦 支持的 Provider

| Provider | Base URL | 免费额度 | 说明 |
|----------|----------|----------|------|
| **NVIDIA NIM** | `https://integrate.api.nvidia.com/v1` | 每日 1000 次 | 支持 DeepSeek-V3.1, Llama-3.3-70B, QwQ-32B 等 |
| **OpenRouter Free** | `https://openrouter.ai/api/v1` | 每月 1M 次 | 支持 GLM-4.5-Air 等免费模型 |
| **Ollama Cloud** | `https://api.ollama.com/v1` | 每日 500 次 | 支持 MiniMax-M2.5, Kimi-K2.5 等 |

> 💡 可以自由添加其他 OpenAI 兼容的免费 Provider，只需在 `config.yaml` 中配置即可。

## 🤝 贡献指南

欢迎贡献！以下方式参与：

1. **Fork & Clone**
   ```bash
   git clone https://github.com/your-username/freeroute.git
   ```

2. **创建分支**
   ```bash
   git checkout -b feature/your-feature
   ```

3. **提交更改**
   ```bash
   git commit -m "feat: add awesome feature"
   ```

4. **Push & PR**
   ```bash
   git push origin feature/your-feature
   ```
   然后在 GitHub 上创建 Pull Request。

### 开发规范

- Python 3.11+
- 代码风格：PEP 8
- 提交信息格式：`type: description`（feat/fix/docs/style/refactor/test/chore）
- 新功能请附带测试（`test_basic.py` 可作为参考）

### 报告问题

发现 Bug 或有功能建议？请在 [Issues](https://github.com/beita123852/freeroute/issues) 中提交。

## 📄 License

[MIT License](LICENSE) — 自由使用、修改、分发。

---

<p align="center">
  Made with ❤️ by <a href="https://github.com/beita123852">beita123852</a>
</p>
