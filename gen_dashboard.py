#!/usr/bin/env python3
"""Generate dashboard HTML for FreeRoute"""

DASHBOARD_HTML = '''<!DOCTYPE html>
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
</html>'''

if __name__ == '__main__':
    print(DASHBOARD_HTML)
