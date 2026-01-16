"""Web server for configuration GUI."""

import json
import logging
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from ..options import Options

_LOG = logging.getLogger(__name__)

# Global references
_app: web.Application | None = None
_runner: web.AppRunner | None = None
_site: web.TCPSite | None = None
_options: "Options | None" = None

# Port for the web GUI
WEB_GUI_PORT = 8099


async def get_config(_request: web.Request) -> web.Response:
    """Get current configuration."""
    if _options is None:
        return web.json_response({"error": "Options not initialized"}, status=500)

    config = {
        "mqtt": {
            "host": _options.mqtt_host,
            "port": _options.mqtt_port,
            "username": _options.mqtt_username,
            "password": "***" if _options.mqtt_password else "",
        },
        "driver": _options.driver,
        "timeout": _options.timeout,
        "debug": _options.debug,
        "manufacturer": _options.manufacturer,
        "sensor_definitions": _options.sensor_definitions,
        "number_entity_mode": _options.number_entity_mode,
        "read_sensors_batch_size": _options.read_sensors_batch_size,
        "read_allow_gap": _options.read_allow_gap,
        "sensors": _options.sensors,
        "sensors_first_inverter": _options.sensors_first_inverter,
        "inverters": [
            {
                "serial_nr": inv.serial_nr,
                "ha_prefix": inv.ha_prefix,
                "modbus_id": inv.modbus_id,
                "port": inv.port,
                "dongle_serial_number": inv.dongle_serial_number,
            }
            for inv in _options.inverters
        ],
        "schedules": [
            {
                "key": s.key,
                "read_every": s.read_every,
                "report_every": s.report_every,
                "change_any": s.change_any,
                "change_by": s.change_by,
                "change_percent": s.change_percent,
            }
            for s in _options.schedules
        ],
    }
    return web.json_response(config)


async def update_live_config(request: web.Request) -> web.Response:
    """Update configuration values that can be changed on-the-fly."""
    if _options is None:
        return web.json_response({"error": "Options not initialized"}, status=500)

    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    updated = []
    errors = []

    # Fields that can be updated without restart
    live_updatable = {
        "debug": int,
        "timeout": int,
        "read_sensors_batch_size": int,
        "read_allow_gap": int,
    }

    for field, converter in live_updatable.items():
        if field in data:
            try:
                value = converter(data[field])
                setattr(_options, field, value)
                updated.append(field)
                _LOG.info("Updated %s to %s", field, value)
            except (ValueError, TypeError) as err:
                errors.append(f"{field}: {err}")

    if errors:
        return web.json_response(
            {"updated": updated, "errors": errors},
            status=400 if not updated else 200,
        )

    return web.json_response({"updated": updated, "message": "Configuration updated"})


async def get_status(_request: web.Request) -> web.Response:
    """Get current system status."""
    from ..a_inverter import STATE  # noqa: PLC0415

    status = {
        "inverters": [],
        "web_gui_version": "1.0.0",
    }

    for inv in STATE:
        inv_status = {
            "index": inv.index,
            "ha_prefix": inv.opt.ha_prefix,
            "serial_nr": inv.opt.serial_nr,
            "connected": inv.inv.timeouts == 0,
            "timeouts": inv.inv.timeouts,
            "sensors_count": len(inv.ss),
        }
        status["inverters"].append(inv_status)

    return web.json_response(status)


async def get_sensor_values(_request: web.Request) -> web.Response:
    """Get current sensor values for all inverters."""
    from ..a_inverter import STATE  # noqa: PLC0415

    result = {}
    for inv in STATE:
        inv_values = {}
        for sensor_id, asensor in inv.ss.items():
            sen = asensor.opt.sensor
            value = inv.inv.state.get(sen)
            inv_values[sensor_id] = {
                "name": sen.name,
                "value": value,
                "unit": sen.unit if hasattr(sen, "unit") else None,
            }
        result[inv.opt.ha_prefix] = inv_values

    return web.json_response(result)


async def serve_frontend(_request: web.Request) -> web.Response:
    """Serve the frontend HTML."""
    return web.Response(text=FRONTEND_HTML, content_type="text/html")


def create_app(options: "Options") -> web.Application:
    """Create the web application."""
    global _options  # noqa: PLW0603
    _options = options

    app = web.Application()
    app.router.add_get("/", serve_frontend)
    app.router.add_get("/api/config", get_config)
    app.router.add_post("/api/config/live", update_live_config)
    app.router.add_get("/api/status", get_status)
    app.router.add_get("/api/sensors", get_sensor_values)

    return app


async def start_web_server(options: "Options", port: int = WEB_GUI_PORT) -> None:
    """Start the web server."""
    global _app, _runner, _site  # noqa: PLW0603

    _app = create_app(options)
    _runner = web.AppRunner(_app)
    await _runner.setup()
    _site = web.TCPSite(_runner, "0.0.0.0", port)
    await _site.start()
    _LOG.info("Web GUI started at http://0.0.0.0:%d", port)


async def stop_web_server() -> None:
    """Stop the web server."""
    global _runner, _site  # noqa: PLW0603

    if _runner:
        await _runner.cleanup()
        _runner = None
        _site = None
        _LOG.info("Web GUI stopped")


# Embedded frontend HTML
FRONTEND_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sunsynk Configuration</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Space+Grotesk:wght@400;500;600;700&display=swap');

        :root {
            --bg-primary: #0d1117;
            --bg-secondary: #161b22;
            --bg-tertiary: #21262d;
            --border-color: #30363d;
            --text-primary: #e6edf3;
            --text-secondary: #8b949e;
            --accent-primary: #f97316;
            --accent-secondary: #fb923c;
            --accent-glow: rgba(249, 115, 22, 0.15);
            --success: #22c55e;
            --warning: #eab308;
            --error: #ef4444;
            --radius: 12px;
            --transition: all 0.2s ease;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Space Grotesk', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.6;
        }

        /* Animated background */
        body::before {
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background:
                radial-gradient(ellipse at 20% 20%, var(--accent-glow) 0%, transparent 50%),
                radial-gradient(ellipse at 80% 80%, rgba(34, 197, 94, 0.08) 0%, transparent 50%);
            pointer-events: none;
            z-index: -1;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }

        header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 2rem;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid var(--border-color);
        }

        .logo {
            display: flex;
            align-items: center;
            gap: 1rem;
        }

        .logo-icon {
            width: 48px;
            height: 48px;
            background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary));
            border-radius: var(--radius);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.5rem;
        }

        .logo h1 {
            font-size: 1.75rem;
            font-weight: 700;
            background: linear-gradient(135deg, var(--text-primary), var(--accent-secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .status-badge {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.5rem 1rem;
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 100px;
            font-size: 0.875rem;
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--success);
            animation: pulse 2s ease-in-out infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .tabs {
            display: flex;
            gap: 0.5rem;
            margin-bottom: 2rem;
            background: var(--bg-secondary);
            padding: 0.5rem;
            border-radius: var(--radius);
            border: 1px solid var(--border-color);
        }

        .tab {
            padding: 0.75rem 1.5rem;
            background: transparent;
            border: none;
            color: var(--text-secondary);
            font-family: inherit;
            font-size: 0.9rem;
            font-weight: 500;
            cursor: pointer;
            border-radius: 8px;
            transition: var(--transition);
        }

        .tab:hover {
            color: var(--text-primary);
            background: var(--bg-tertiary);
        }

        .tab.active {
            color: var(--accent-primary);
            background: var(--bg-tertiary);
        }

        .content {
            display: none;
        }

        .content.active {
            display: block;
            animation: fadeIn 0.3s ease;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 1.5rem;
        }

        .card {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: var(--radius);
            overflow: hidden;
            transition: var(--transition);
        }

        .card:hover {
            border-color: var(--accent-primary);
            box-shadow: 0 0 30px var(--accent-glow);
        }

        .card-header {
            padding: 1.25rem 1.5rem;
            background: var(--bg-tertiary);
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .card-title {
            font-size: 1rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }

        .card-icon {
            width: 32px;
            height: 32px;
            background: linear-gradient(135deg, var(--accent-glow), transparent);
            border: 1px solid var(--accent-primary);
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1rem;
        }

        .card-body {
            padding: 1.5rem;
        }

        .form-group {
            margin-bottom: 1.25rem;
        }

        .form-group:last-child {
            margin-bottom: 0;
        }

        label {
            display: block;
            font-size: 0.85rem;
            font-weight: 500;
            color: var(--text-secondary);
            margin-bottom: 0.5rem;
        }

        input, select {
            width: 100%;
            padding: 0.75rem 1rem;
            background: var(--bg-primary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            color: var(--text-primary);
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.9rem;
            transition: var(--transition);
        }

        input:focus, select:focus {
            outline: none;
            border-color: var(--accent-primary);
            box-shadow: 0 0 0 3px var(--accent-glow);
        }

        input:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .input-hint {
            font-size: 0.75rem;
            color: var(--text-secondary);
            margin-top: 0.35rem;
        }

        .btn {
            padding: 0.75rem 1.5rem;
            border: none;
            border-radius: 8px;
            font-family: inherit;
            font-size: 0.9rem;
            font-weight: 600;
            cursor: pointer;
            transition: var(--transition);
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
        }

        .btn-primary {
            background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary));
            color: white;
        }

        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 30px var(--accent-glow);
        }

        .btn-secondary {
            background: var(--bg-tertiary);
            color: var(--text-primary);
            border: 1px solid var(--border-color);
        }

        .btn-secondary:hover {
            border-color: var(--accent-primary);
        }

        .inverter-card {
            display: flex;
            align-items: center;
            gap: 1rem;
            padding: 1rem;
            background: var(--bg-tertiary);
            border-radius: 8px;
            margin-bottom: 1rem;
        }

        .inverter-card:last-child {
            margin-bottom: 0;
        }

        .inverter-status {
            width: 12px;
            height: 12px;
            border-radius: 50%;
        }

        .inverter-status.connected {
            background: var(--success);
            box-shadow: 0 0 10px var(--success);
        }

        .inverter-status.disconnected {
            background: var(--error);
            box-shadow: 0 0 10px var(--error);
        }

        .inverter-info {
            flex: 1;
        }

        .inverter-name {
            font-weight: 600;
            font-size: 0.95rem;
        }

        .inverter-details {
            font-size: 0.8rem;
            color: var(--text-secondary);
            font-family: 'JetBrains Mono', monospace;
        }

        .sensor-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 1rem;
        }

        .sensor-item {
            background: var(--bg-tertiary);
            padding: 1rem;
            border-radius: 8px;
            border: 1px solid var(--border-color);
        }

        .sensor-name {
            font-size: 0.8rem;
            color: var(--text-secondary);
            margin-bottom: 0.25rem;
        }

        .sensor-value {
            font-size: 1.5rem;
            font-weight: 600;
            font-family: 'JetBrains Mono', monospace;
            color: var(--accent-secondary);
        }

        .sensor-unit {
            font-size: 0.9rem;
            color: var(--text-secondary);
            margin-left: 0.25rem;
        }

        .toast {
            position: fixed;
            bottom: 2rem;
            right: 2rem;
            padding: 1rem 1.5rem;
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: var(--radius);
            display: flex;
            align-items: center;
            gap: 0.75rem;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
            transform: translateY(100px);
            opacity: 0;
            transition: var(--transition);
            z-index: 1000;
        }

        .toast.show {
            transform: translateY(0);
            opacity: 1;
        }

        .toast.success {
            border-color: var(--success);
        }

        .toast.error {
            border-color: var(--error);
        }

        .actions {
            display: flex;
            gap: 1rem;
            margin-top: 1.5rem;
            padding-top: 1.5rem;
            border-top: 1px solid var(--border-color);
        }

        @media (max-width: 768px) {
            .container {
                padding: 1rem;
            }

            .grid {
                grid-template-columns: 1fr;
            }

            header {
                flex-direction: column;
                gap: 1rem;
            }

            .tabs {
                flex-wrap: wrap;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">
                <div class="logo-icon">☀️</div>
                <h1>Sunsynk Control</h1>
            </div>
            <div class="status-badge">
                <div class="status-dot" id="connection-status"></div>
                <span id="status-text">Connected</span>
            </div>
        </header>

        <div class="tabs">
            <button class="tab active" data-tab="dashboard">Dashboard</button>
            <button class="tab" data-tab="config">Configuration</button>
            <button class="tab" data-tab="sensors">Sensors</button>
        </div>

        <div id="dashboard" class="content active">
            <div class="grid">
                <div class="card">
                    <div class="card-header">
                        <div class="card-title">
                            <div class="card-icon">⚡</div>
                            Inverters
                        </div>
                    </div>
                    <div class="card-body" id="inverters-list">
                        <div class="inverter-card">
                            <div class="inverter-status connected"></div>
                            <div class="inverter-info">
                                <div class="inverter-name">Loading...</div>
                                <div class="inverter-details">Fetching status...</div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="card">
                    <div class="card-header">
                        <div class="card-title">
                            <div class="card-icon">⚙️</div>
                            Quick Settings
                        </div>
                    </div>
                    <div class="card-body">
                        <div class="form-group">
                            <label>Debug Level</label>
                            <select id="quick-debug">
                                <option value="0">Off</option>
                                <option value="1">Basic</option>
                                <option value="2">Verbose</option>
                            </select>
                            <div class="input-hint">Changes take effect immediately</div>
                        </div>
                        <div class="form-group">
                            <label>Timeout (seconds)</label>
                            <input type="number" id="quick-timeout" min="5" max="60">
                        </div>
                        <div class="actions">
                            <button class="btn btn-primary" onclick="applyQuickSettings()">
                                Apply Changes
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <div id="config" class="content">
            <div class="grid">
                <div class="card">
                    <div class="card-header">
                        <div class="card-title">
                            <div class="card-icon">🔌</div>
                            MQTT Settings
                        </div>
                    </div>
                    <div class="card-body">
                        <div class="form-group">
                            <label>Host</label>
                            <input type="text" id="mqtt-host" disabled>
                            <div class="input-hint">Requires restart to change</div>
                        </div>
                        <div class="form-group">
                            <label>Port</label>
                            <input type="number" id="mqtt-port" disabled>
                        </div>
                        <div class="form-group">
                            <label>Username</label>
                            <input type="text" id="mqtt-username" disabled>
                        </div>
                    </div>
                </div>

                <div class="card">
                    <div class="card-header">
                        <div class="card-title">
                            <div class="card-icon">📡</div>
                            Modbus Settings
                        </div>
                    </div>
                    <div class="card-body">
                        <div class="form-group">
                            <label>Driver</label>
                            <input type="text" id="modbus-driver" disabled>
                            <div class="input-hint">Requires restart to change</div>
                        </div>
                        <div class="form-group">
                            <label>Timeout</label>
                            <input type="number" id="modbus-timeout" min="5" max="60">
                            <div class="input-hint">Can be changed on-the-fly</div>
                        </div>
                        <div class="form-group">
                            <label>Read Batch Size</label>
                            <input type="number" id="modbus-batch-size" min="1" max="100">
                        </div>
                        <div class="form-group">
                            <label>Allow Gap</label>
                            <input type="number" id="modbus-allow-gap" min="0" max="50">
                        </div>
                    </div>
                </div>

                <div class="card">
                    <div class="card-header">
                        <div class="card-title">
                            <div class="card-icon">🎛️</div>
                            General Settings
                        </div>
                    </div>
                    <div class="card-body">
                        <div class="form-group">
                            <label>Sensor Definitions</label>
                            <select id="sensor-definitions" disabled>
                                <option value="single-phase">Single Phase</option>
                                <option value="three-phase-hv">Three Phase HV</option>
                                <option value="three-phase-lv">Three Phase LV</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Manufacturer</label>
                            <input type="text" id="manufacturer" disabled>
                        </div>
                        <div class="form-group">
                            <label>Number Entity Mode</label>
                            <select id="number-entity-mode" disabled>
                                <option value="auto">Auto</option>
                                <option value="slider">Slider</option>
                                <option value="box">Box</option>
                            </select>
                        </div>
                    </div>
                </div>
            </div>

            <div class="actions">
                <button class="btn btn-primary" onclick="saveLiveConfig()">
                    💾 Save Live Changes
                </button>
                <button class="btn btn-secondary" onclick="loadConfig()">
                    🔄 Reload Config
                </button>
            </div>
        </div>

        <div id="sensors" class="content">
            <div class="card">
                <div class="card-header">
                    <div class="card-title">
                        <div class="card-icon">📊</div>
                        Live Sensor Values
                    </div>
                    <button class="btn btn-secondary" onclick="loadSensors()">
                        🔄 Refresh
                    </button>
                </div>
                <div class="card-body">
                    <div class="sensor-grid" id="sensor-grid">
                        <div class="sensor-item">
                            <div class="sensor-name">Loading...</div>
                            <div class="sensor-value">--</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <div class="toast" id="toast">
        <span id="toast-message"></span>
    </div>

    <script>
        // Tab switching
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.content').forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                document.getElementById(tab.dataset.tab).classList.add('active');
            });
        });

        // Toast notification
        function showToast(message, type = 'success') {
            const toast = document.getElementById('toast');
            const toastMessage = document.getElementById('toast-message');
            toastMessage.textContent = message;
            toast.className = 'toast show ' + type;
            setTimeout(() => toast.classList.remove('show'), 3000);
        }

        // Load configuration
        async function loadConfig() {
            try {
                const response = await fetch('/api/config');
                const config = await response.json();

                // MQTT
                document.getElementById('mqtt-host').value = config.mqtt?.host || '';
                document.getElementById('mqtt-port').value = config.mqtt?.port || '';
                document.getElementById('mqtt-username').value = config.mqtt?.username || '';

                // Modbus
                document.getElementById('modbus-driver').value = config.driver || '';
                document.getElementById('modbus-timeout').value = config.timeout || '';
                document.getElementById('modbus-batch-size').value = config.read_sensors_batch_size || '';
                document.getElementById('modbus-allow-gap').value = config.read_allow_gap || '';

                // General
                document.getElementById('sensor-definitions').value = config.sensor_definitions || '';
                document.getElementById('manufacturer').value = config.manufacturer || '';
                document.getElementById('number-entity-mode').value = config.number_entity_mode || '';

                // Quick settings
                document.getElementById('quick-debug').value = config.debug || '0';
                document.getElementById('quick-timeout').value = config.timeout || '';

                showToast('Configuration loaded');
            } catch (err) {
                showToast('Failed to load config: ' + err.message, 'error');
            }
        }

        // Load status
        async function loadStatus() {
            try {
                const response = await fetch('/api/status');
                const status = await response.json();

                const invertersList = document.getElementById('inverters-list');
                if (status.inverters && status.inverters.length > 0) {
                    invertersList.innerHTML = status.inverters.map(inv => `
                        <div class="inverter-card">
                            <div class="inverter-status ${inv.connected ? 'connected' : 'disconnected'}"></div>
                            <div class="inverter-info">
                                <div class="inverter-name">${inv.ha_prefix || 'Inverter ' + inv.index}</div>
                                <div class="inverter-details">
                                    Serial: ${inv.serial_nr || 'N/A'} |
                                    Sensors: ${inv.sensors_count} |
                                    Timeouts: ${inv.timeouts}
                                </div>
                            </div>
                        </div>
                    `).join('');
                }

                // Update connection status
                const hasConnected = status.inverters?.some(inv => inv.connected);
                const statusDot = document.getElementById('connection-status');
                const statusText = document.getElementById('status-text');
                if (hasConnected) {
                    statusDot.style.background = 'var(--success)';
                    statusText.textContent = 'Connected';
                } else {
                    statusDot.style.background = 'var(--warning)';
                    statusText.textContent = 'Connecting...';
                }
            } catch (err) {
                const statusDot = document.getElementById('connection-status');
                const statusText = document.getElementById('status-text');
                statusDot.style.background = 'var(--error)';
                statusText.textContent = 'Disconnected';
            }
        }

        // Load sensors
        async function loadSensors() {
            try {
                const response = await fetch('/api/sensors');
                const sensors = await response.json();

                const grid = document.getElementById('sensor-grid');
                let html = '';

                for (const [prefix, values] of Object.entries(sensors)) {
                    for (const [id, data] of Object.entries(values)) {
                        html += `
                            <div class="sensor-item">
                                <div class="sensor-name">${data.name || id}</div>
                                <div class="sensor-value">
                                    ${data.value !== null ? data.value : '--'}
                                    ${data.unit ? `<span class="sensor-unit">${data.unit}</span>` : ''}
                                </div>
                            </div>
                        `;
                    }
                }

                grid.innerHTML = html || '<div class="sensor-item"><div class="sensor-name">No sensors available</div></div>';
            } catch (err) {
                showToast('Failed to load sensors: ' + err.message, 'error');
            }
        }

        // Save live config
        async function saveLiveConfig() {
            try {
                const data = {
                    timeout: parseInt(document.getElementById('modbus-timeout').value),
                    read_sensors_batch_size: parseInt(document.getElementById('modbus-batch-size').value),
                    read_allow_gap: parseInt(document.getElementById('modbus-allow-gap').value),
                    debug: parseInt(document.getElementById('quick-debug').value),
                };

                const response = await fetch('/api/config/live', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data),
                });

                const result = await response.json();
                if (response.ok) {
                    showToast('Configuration updated: ' + result.updated.join(', '));
                } else {
                    showToast('Errors: ' + result.errors.join(', '), 'error');
                }
            } catch (err) {
                showToast('Failed to save config: ' + err.message, 'error');
            }
        }

        // Apply quick settings
        async function applyQuickSettings() {
            try {
                const data = {
                    debug: parseInt(document.getElementById('quick-debug').value),
                    timeout: parseInt(document.getElementById('quick-timeout').value),
                };

                const response = await fetch('/api/config/live', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data),
                });

                const result = await response.json();
                if (response.ok) {
                    showToast('Settings applied successfully');
                } else {
                    showToast('Failed to apply settings', 'error');
                }
            } catch (err) {
                showToast('Failed to apply settings: ' + err.message, 'error');
            }
        }

        // Initial load
        loadConfig();
        loadStatus();

        // Auto-refresh status every 30 seconds
        setInterval(loadStatus, 30000);
    </script>
</body>
</html>
"""
