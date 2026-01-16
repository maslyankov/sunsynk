"""Web server for configuration GUI."""

import json
import logging
from pathlib import Path
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

# Config file path (for saving)
CONFIG_FILE = Path("/data/options.json")


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
                "index": idx,
                "serial_nr": inv.serial_nr,
                "ha_prefix": inv.ha_prefix,
                "modbus_id": inv.modbus_id,
                "port": inv.port,
                "dongle_serial_number": inv.dongle_serial_number,
            }
            for idx, inv in enumerate(_options.inverters)
        ],
        "schedules": [
            {
                "index": idx,
                "key": s.key,
                "read_every": s.read_every,
                "report_every": s.report_every,
                "change_any": s.change_any,
                "change_by": s.change_by,
                "change_percent": s.change_percent,
            }
            for idx, s in enumerate(_options.schedules)
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
        "web_gui_version": "1.1.0",
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


async def get_available_sensors(_request: web.Request) -> web.Response:
    """Get all available sensor definitions grouped by category."""
    from sunsynk.definitions import import_defs  # noqa: PLC0415

    if _options is None:
        return web.json_response({"error": "Options not initialized"}, status=500)

    # Get sensor definitions based on current config
    defs = import_defs(_options.sensor_definitions)

    # Group sensors by category
    categories: dict[str, list[dict]] = {}

    for sensor in defs.all.values():
        # Determine category from sensor type or name
        category = _categorize_sensor(sensor)
        if category not in categories:
            categories[category] = []

        categories[category].append(
            {
                "id": sensor.id,
                "name": sensor.name,
                "unit": sensor.unit if hasattr(sensor, "unit") else "",
                "addresses": list(sensor.address) if hasattr(sensor, "address") else [],
            }
        )

    # Sort sensors within each category
    for _cat, sensors in categories.items():
        sensors.sort(key=lambda x: x["name"])

    return web.json_response(
        {
            "sensor_definitions": _options.sensor_definitions,
            "categories": categories,
            "selected_sensors": _options.sensors,
            "first_inverter_sensors": _options.sensors_first_inverter,
        }
    )


def _categorize_sensor(sensor) -> str:  # noqa: PLR0911
    """Categorize a sensor based on its name or type."""
    name = sensor.name.lower()
    sensor_id = sensor.id.lower()

    if any(x in name for x in ["battery", "batt"]):
        return "Battery"
    if any(x in name for x in ["grid", "ct"]):
        return "Grid"
    if any(x in name for x in ["pv", "solar", "mppt"]):
        return "Solar/PV"
    if any(x in name for x in ["load", "essential", "non-essential"]):
        return "Load"
    if any(x in name for x in ["temp", "temperature"]):
        return "Temperature"
    if any(x in name for x in ["prog", "time", "slot"]):
        return "Programs/Time"
    if any(x in sensor_id for x in ["fault", "error", "warning"]):
        return "Faults/Warnings"
    if any(x in name for x in ["voltage", "current", "power", "energy", "frequency"]):
        return "Power/Energy"
    return "Other"


async def update_sensors(request: web.Request) -> web.Response:
    """Update the selected sensors list."""
    if _options is None:
        return web.json_response({"error": "Options not initialized"}, status=500)

    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    if "sensors" in data:
        _options.sensors = data["sensors"]
        _LOG.info("Updated sensors list: %d sensors", len(_options.sensors))

    if "sensors_first_inverter" in data:
        _options.sensors_first_inverter = data["sensors_first_inverter"]
        _LOG.info(
            "Updated first inverter sensors: %d sensors",
            len(_options.sensors_first_inverter),
        )

    return web.json_response(
        {
            "message": "Sensors updated",
            "sensors_count": len(_options.sensors),
            "first_inverter_count": len(_options.sensors_first_inverter),
            "requires_restart": True,
        }
    )


async def add_inverter(request: web.Request) -> web.Response:
    """Add a new inverter configuration."""
    if _options is None:
        return web.json_response({"error": "Options not initialized"}, status=500)

    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    from ..options import InverterOptions  # noqa: PLC0415

    # Validate required fields
    if not data.get("ha_prefix"):
        return web.json_response({"error": "ha_prefix is required"}, status=400)

    # Check for duplicate ha_prefix
    existing_prefixes = [inv.ha_prefix for inv in _options.inverters]
    if data["ha_prefix"].lower().strip() in existing_prefixes:
        return web.json_response(
            {"error": f"ha_prefix '{data['ha_prefix']}' already exists"}, status=400
        )

    # Create new inverter options
    new_inv = InverterOptions(
        port=data.get("port", ""),
        modbus_id=int(data.get("modbus_id", 1)),
        ha_prefix=data["ha_prefix"].lower().strip(),
        serial_nr=data.get("serial_nr", ""),
        dongle_serial_number=int(data.get("dongle_serial_number", 0)),
    )

    _options.inverters.append(new_inv)
    _LOG.info("Added new inverter: %s", new_inv.ha_prefix)

    return web.json_response(
        {
            "message": "Inverter added",
            "index": len(_options.inverters) - 1,
            "inverter": {
                "ha_prefix": new_inv.ha_prefix,
                "serial_nr": new_inv.serial_nr,
                "modbus_id": new_inv.modbus_id,
                "port": new_inv.port,
            },
            "requires_restart": True,
        }
    )


async def update_inverter(request: web.Request) -> web.Response:
    """Update an existing inverter configuration."""
    if _options is None:
        return web.json_response({"error": "Options not initialized"}, status=500)

    try:
        index = int(request.match_info["index"])
    except (KeyError, ValueError):
        return web.json_response({"error": "Invalid inverter index"}, status=400)

    if index < 0 or index >= len(_options.inverters):
        return web.json_response({"error": "Inverter not found"}, status=404)

    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    inv = _options.inverters[index]

    # Check for duplicate ha_prefix (excluding current inverter)
    if "ha_prefix" in data:
        new_prefix = data["ha_prefix"].lower().strip()
        for i, other_inv in enumerate(_options.inverters):
            if i != index and other_inv.ha_prefix == new_prefix:
                return web.json_response(
                    {"error": f"ha_prefix '{new_prefix}' already exists"}, status=400
                )
        inv.ha_prefix = new_prefix

    if "serial_nr" in data:
        inv.serial_nr = data["serial_nr"]
    if "modbus_id" in data:
        inv.modbus_id = int(data["modbus_id"])
    if "port" in data:
        inv.port = data["port"]
    if "dongle_serial_number" in data:
        inv.dongle_serial_number = int(data["dongle_serial_number"])

    _LOG.info("Updated inverter %d: %s", index, inv.ha_prefix)

    return web.json_response(
        {
            "message": "Inverter updated",
            "index": index,
            "requires_restart": True,
        }
    )


async def delete_inverter(request: web.Request) -> web.Response:
    """Delete an inverter configuration."""
    if _options is None:
        return web.json_response({"error": "Options not initialized"}, status=500)

    try:
        index = int(request.match_info["index"])
    except (KeyError, ValueError):
        return web.json_response({"error": "Invalid inverter index"}, status=400)

    if index < 0 or index >= len(_options.inverters):
        return web.json_response({"error": "Inverter not found"}, status=404)

    if len(_options.inverters) <= 1:
        return web.json_response(
            {"error": "Cannot delete the last inverter"}, status=400
        )

    deleted = _options.inverters.pop(index)
    _LOG.info("Deleted inverter %d: %s", index, deleted.ha_prefix)

    return web.json_response(
        {
            "message": "Inverter deleted",
            "deleted_prefix": deleted.ha_prefix,
            "requires_restart": True,
        }
    )


async def add_schedule(request: web.Request) -> web.Response:
    """Add a new schedule configuration."""
    if _options is None:
        return web.json_response({"error": "Options not initialized"}, status=500)

    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    from ..timer_schedule import Schedule  # noqa: PLC0415

    # Validate required fields
    if not data.get("key"):
        return web.json_response({"error": "key is required"}, status=400)

    new_schedule = Schedule(
        key=data["key"],
        read_every=int(data.get("read_every", 60)),
        report_every=int(data.get("report_every", 60)),
        change_any=bool(data.get("change_any", False)),
        change_by=float(data.get("change_by", 0)),
        change_percent=int(data.get("change_percent", 0)),
    )

    _options.schedules.append(new_schedule)
    _LOG.info("Added new schedule: %s", new_schedule.key)

    return web.json_response(
        {
            "message": "Schedule added",
            "index": len(_options.schedules) - 1,
            "requires_restart": True,
        }
    )


async def update_schedule(request: web.Request) -> web.Response:
    """Update an existing schedule configuration."""
    if _options is None:
        return web.json_response({"error": "Options not initialized"}, status=500)

    try:
        index = int(request.match_info["index"])
    except (KeyError, ValueError):
        return web.json_response({"error": "Invalid schedule index"}, status=400)

    if index < 0 or index >= len(_options.schedules):
        return web.json_response({"error": "Schedule not found"}, status=404)

    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    sched = _options.schedules[index]

    if "key" in data:
        sched.key = data["key"]
    if "read_every" in data:
        sched.read_every = int(data["read_every"])
    if "report_every" in data:
        sched.report_every = int(data["report_every"])
    if "change_any" in data:
        sched.change_any = bool(data["change_any"])
    if "change_by" in data:
        sched.change_by = float(data["change_by"])
    if "change_percent" in data:
        sched.change_percent = int(data["change_percent"])

    _LOG.info("Updated schedule %d: %s", index, sched.key)

    return web.json_response(
        {
            "message": "Schedule updated",
            "index": index,
            "requires_restart": True,
        }
    )


async def delete_schedule(request: web.Request) -> web.Response:
    """Delete a schedule configuration."""
    if _options is None:
        return web.json_response({"error": "Options not initialized"}, status=500)

    try:
        index = int(request.match_info["index"])
    except (KeyError, ValueError):
        return web.json_response({"error": "Invalid schedule index"}, status=400)

    if index < 0 or index >= len(_options.schedules):
        return web.json_response({"error": "Schedule not found"}, status=404)

    deleted = _options.schedules.pop(index)
    _LOG.info("Deleted schedule %d: %s", index, deleted.key)

    return web.json_response(
        {
            "message": "Schedule deleted",
            "deleted_key": deleted.key,
            "requires_restart": True,
        }
    )


async def export_config(_request: web.Request) -> web.Response:
    """Export configuration as JSON."""
    if _options is None:
        return web.json_response({"error": "Options not initialized"}, status=500)

    config = {
        "MQTT_HOST": _options.mqtt_host,
        "MQTT_PORT": _options.mqtt_port,
        "MQTT_USERNAME": _options.mqtt_username,
        "DRIVER": _options.driver,
        "TIMEOUT": _options.timeout,
        "DEBUG": _options.debug,
        "MANUFACTURER": _options.manufacturer,
        "SENSOR_DEFINITIONS": _options.sensor_definitions,
        "NUMBER_ENTITY_MODE": _options.number_entity_mode,
        "READ_SENSORS_BATCH_SIZE": _options.read_sensors_batch_size,
        "READ_ALLOW_GAP": _options.read_allow_gap,
        "SENSORS": _options.sensors,
        "SENSORS_FIRST_INVERTER": _options.sensors_first_inverter,
        "INVERTERS": [
            {
                "SERIAL_NR": inv.serial_nr,
                "HA_PREFIX": inv.ha_prefix,
                "MODBUS_ID": inv.modbus_id,
                "PORT": inv.port,
                "DONGLE_SERIAL_NUMBER": inv.dongle_serial_number,
            }
            for inv in _options.inverters
        ],
        "SCHEDULES": [
            {
                "KEY": s.key,
                "READ_EVERY": s.read_every,
                "REPORT_EVERY": s.report_every,
                "CHANGE_ANY": s.change_any,
                "CHANGE_BY": s.change_by,
                "CHANGE_PERCENT": s.change_percent,
            }
            for s in _options.schedules
        ],
    }

    return web.Response(
        text=json.dumps(config, indent=2),
        content_type="application/json",
        headers={"Content-Disposition": "attachment; filename=sunsynk-config.json"},
    )


async def serve_frontend(_request: web.Request) -> web.Response:
    """Serve the frontend HTML."""
    return web.Response(text=FRONTEND_HTML, content_type="text/html")


def create_app(options: "Options") -> web.Application:
    """Create the web application."""
    global _options  # noqa: PLW0603
    _options = options

    app = web.Application()

    # Frontend
    app.router.add_get("/", serve_frontend)

    # Config API
    app.router.add_get("/api/config", get_config)
    app.router.add_post("/api/config/live", update_live_config)
    app.router.add_get("/api/config/export", export_config)

    # Status API
    app.router.add_get("/api/status", get_status)

    # Sensors API
    app.router.add_get("/api/sensors", get_sensor_values)
    app.router.add_get("/api/sensors/available", get_available_sensors)
    app.router.add_post("/api/sensors/update", update_sensors)

    # Inverters API
    app.router.add_post("/api/inverters", add_inverter)
    app.router.add_put("/api/inverters/{index}", update_inverter)
    app.router.add_delete("/api/inverters/{index}", delete_inverter)

    # Schedules API
    app.router.add_post("/api/schedules", add_schedule)
    app.router.add_put("/api/schedules/{index}", update_schedule)
    app.router.add_delete("/api/schedules/{index}", delete_schedule)

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
            --blue: #3b82f6;
            --radius: 12px;
            --transition: all 0.2s ease;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: 'Space Grotesk', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.6;
        }

        body::before {
            content: '';
            position: fixed;
            inset: 0;
            background:
                radial-gradient(ellipse at 20% 20%, var(--accent-glow) 0%, transparent 50%),
                radial-gradient(ellipse at 80% 80%, rgba(34, 197, 94, 0.08) 0%, transparent 50%);
            pointer-events: none;
            z-index: -1;
        }

        .container { max-width: 1400px; margin: 0 auto; padding: 2rem; }

        header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 2rem;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid var(--border-color);
        }

        .logo { display: flex; align-items: center; gap: 1rem; }

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

        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }

        .tabs {
            display: flex;
            gap: 0.5rem;
            margin-bottom: 2rem;
            background: var(--bg-secondary);
            padding: 0.5rem;
            border-radius: var(--radius);
            border: 1px solid var(--border-color);
            flex-wrap: wrap;
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

        .tab:hover { color: var(--text-primary); background: var(--bg-tertiary); }
        .tab.active { color: var(--accent-primary); background: var(--bg-tertiary); }

        .content { display: none; }
        .content.active { display: block; animation: fadeIn 0.3s ease; }

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

        .card-body { padding: 1.5rem; }

        .form-group { margin-bottom: 1.25rem; }
        .form-group:last-child { margin-bottom: 0; }

        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
        }

        label {
            display: block;
            font-size: 0.85rem;
            font-weight: 500;
            color: var(--text-secondary);
            margin-bottom: 0.5rem;
        }

        input, select, textarea {
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

        input:focus, select:focus, textarea:focus {
            outline: none;
            border-color: var(--accent-primary);
            box-shadow: 0 0 0 3px var(--accent-glow);
        }

        input:disabled, select:disabled { opacity: 0.5; cursor: not-allowed; }

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

        .btn-secondary:hover { border-color: var(--accent-primary); }

        .btn-danger {
            background: var(--error);
            color: white;
        }

        .btn-danger:hover { opacity: 0.9; }

        .btn-sm {
            padding: 0.5rem 1rem;
            font-size: 0.8rem;
        }

        .inverter-card {
            display: flex;
            align-items: center;
            gap: 1rem;
            padding: 1rem;
            background: var(--bg-tertiary);
            border-radius: 8px;
            margin-bottom: 1rem;
            border: 1px solid var(--border-color);
        }

        .inverter-card:last-child { margin-bottom: 0; }

        .inverter-status {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            flex-shrink: 0;
        }

        .inverter-status.connected { background: var(--success); box-shadow: 0 0 10px var(--success); }
        .inverter-status.disconnected { background: var(--error); box-shadow: 0 0 10px var(--error); }
        .inverter-status.pending { background: var(--warning); box-shadow: 0 0 10px var(--warning); }

        .inverter-info { flex: 1; min-width: 0; }
        .inverter-name { font-weight: 600; font-size: 0.95rem; }
        .inverter-details {
            font-size: 0.8rem;
            color: var(--text-secondary);
            font-family: 'JetBrains Mono', monospace;
        }

        .inverter-actions { display: flex; gap: 0.5rem; }

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

        .sensor-name { font-size: 0.8rem; color: var(--text-secondary); margin-bottom: 0.25rem; }
        .sensor-value {
            font-size: 1.5rem;
            font-weight: 600;
            font-family: 'JetBrains Mono', monospace;
            color: var(--accent-secondary);
        }
        .sensor-unit { font-size: 0.9rem; color: var(--text-secondary); margin-left: 0.25rem; }

        /* Modal */
        .modal-overlay {
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.7);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
            opacity: 0;
            visibility: hidden;
            transition: var(--transition);
        }

        .modal-overlay.show { opacity: 1; visibility: visible; }

        .modal {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: var(--radius);
            width: 90%;
            max-width: 600px;
            max-height: 90vh;
            overflow-y: auto;
            transform: translateY(20px);
            transition: var(--transition);
        }

        .modal-overlay.show .modal { transform: translateY(0); }

        .modal-header {
            padding: 1.25rem 1.5rem;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .modal-title { font-size: 1.1rem; font-weight: 600; }

        .modal-close {
            background: none;
            border: none;
            color: var(--text-secondary);
            font-size: 1.5rem;
            cursor: pointer;
            transition: var(--transition);
        }

        .modal-close:hover { color: var(--text-primary); }

        .modal-body { padding: 1.5rem; }
        .modal-footer {
            padding: 1rem 1.5rem;
            border-top: 1px solid var(--border-color);
            display: flex;
            gap: 1rem;
            justify-content: flex-end;
        }

        /* Sensor Selection */
        .sensor-category {
            margin-bottom: 1.5rem;
        }

        .sensor-category-header {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.75rem;
            background: var(--bg-tertiary);
            border-radius: 8px;
            cursor: pointer;
            margin-bottom: 0.5rem;
        }

        .sensor-category-header:hover { background: var(--bg-primary); }

        .sensor-category-title {
            font-weight: 600;
            flex: 1;
        }

        .sensor-category-count {
            font-size: 0.8rem;
            color: var(--text-secondary);
            background: var(--bg-primary);
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
        }

        .sensor-list {
            display: none;
            flex-wrap: wrap;
            gap: 0.5rem;
            padding: 0.5rem;
        }

        .sensor-list.show { display: flex; }

        .sensor-chip {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.5rem 0.75rem;
            background: var(--bg-primary);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            font-size: 0.8rem;
            cursor: pointer;
            transition: var(--transition);
        }

        .sensor-chip:hover { border-color: var(--accent-primary); }
        .sensor-chip.selected {
            background: var(--accent-glow);
            border-color: var(--accent-primary);
            color: var(--accent-secondary);
        }

        .sensor-chip input { display: none; }

        /* Schedule Card */
        .schedule-card {
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 1rem;
            margin-bottom: 1rem;
        }

        .schedule-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 0.75rem;
        }

        .schedule-key {
            font-weight: 600;
            font-family: 'JetBrains Mono', monospace;
        }

        .schedule-details {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 0.5rem;
            font-size: 0.8rem;
            color: var(--text-secondary);
        }

        /* Toast */
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
            z-index: 1001;
        }

        .toast.show { transform: translateY(0); opacity: 1; }
        .toast.success { border-color: var(--success); }
        .toast.error { border-color: var(--error); }
        .toast.warning { border-color: var(--warning); }

        .actions {
            display: flex;
            gap: 1rem;
            margin-top: 1.5rem;
            padding-top: 1.5rem;
            border-top: 1px solid var(--border-color);
            flex-wrap: wrap;
        }

        .empty-state {
            text-align: center;
            padding: 3rem;
            color: var(--text-secondary);
        }

        .empty-state-icon { font-size: 3rem; margin-bottom: 1rem; }

        @media (max-width: 768px) {
            .container { padding: 1rem; }
            .grid { grid-template-columns: 1fr; }
            header { flex-direction: column; gap: 1rem; }
            .form-row { grid-template-columns: 1fr; }
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
            <button class="tab" data-tab="inverters">Inverters</button>
            <button class="tab" data-tab="sensors-config">Sensor Config</button>
            <button class="tab" data-tab="schedules">Schedules</button>
            <button class="tab" data-tab="config">Settings</button>
            <button class="tab" data-tab="sensors">Live Values</button>
        </div>

        <!-- Dashboard Tab -->
        <div id="dashboard" class="content active">
            <div class="grid">
                <div class="card">
                    <div class="card-header">
                        <div class="card-title">
                            <div class="card-icon">⚡</div>
                            Inverters Status
                        </div>
                    </div>
                    <div class="card-body" id="dashboard-inverters">
                        <div class="empty-state">
                            <div class="empty-state-icon">⏳</div>
                            <p>Loading inverter status...</p>
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
                            <button class="btn btn-primary" onclick="applyQuickSettings()">Apply Changes</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Inverters Tab -->
        <div id="inverters" class="content">
            <div class="card">
                <div class="card-header">
                    <div class="card-title">
                        <div class="card-icon">🔌</div>
                        Configured Inverters
                    </div>
                    <button class="btn btn-primary btn-sm" onclick="showAddInverterModal()">+ Add Inverter</button>
                </div>
                <div class="card-body" id="inverters-list">
                    <div class="empty-state">
                        <div class="empty-state-icon">🔌</div>
                        <p>No inverters configured</p>
                    </div>
                </div>
            </div>
        </div>

        <!-- Sensor Config Tab -->
        <div id="sensors-config" class="content">
            <div class="card">
                <div class="card-header">
                    <div class="card-title">
                        <div class="card-icon">📊</div>
                        Sensor Selection
                    </div>
                    <div style="display: flex; gap: 0.5rem;">
                        <button class="btn btn-secondary btn-sm" onclick="selectAllSensors()">Select All</button>
                        <button class="btn btn-secondary btn-sm" onclick="clearAllSensors()">Clear All</button>
                    </div>
                </div>
                <div class="card-body" id="sensor-selection">
                    <div class="empty-state">
                        <div class="empty-state-icon">📊</div>
                        <p>Loading available sensors...</p>
                    </div>
                </div>
                <div class="actions" style="padding: 1.5rem;">
                    <button class="btn btn-primary" onclick="saveSensorSelection()">💾 Save Sensor Selection</button>
                    <span class="input-hint" style="margin-left: 1rem;">Changes require addon restart</span>
                </div>
            </div>
        </div>

        <!-- Schedules Tab -->
        <div id="schedules" class="content">
            <div class="card">
                <div class="card-header">
                    <div class="card-title">
                        <div class="card-icon">⏱️</div>
                        Reading Schedules
                    </div>
                    <button class="btn btn-primary btn-sm" onclick="showAddScheduleModal()">+ Add Schedule</button>
                </div>
                <div class="card-body" id="schedules-list">
                    <div class="empty-state">
                        <div class="empty-state-icon">⏱️</div>
                        <p>No schedules configured</p>
                    </div>
                </div>
            </div>
        </div>

        <!-- Settings Tab -->
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
                        <div class="form-row">
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
                        </div>
                        <div class="form-row">
                            <div class="form-group">
                                <label>Timeout</label>
                                <input type="number" id="modbus-timeout" min="5" max="60">
                                <div class="input-hint">Live editable</div>
                            </div>
                            <div class="form-group">
                                <label>Batch Size</label>
                                <input type="number" id="modbus-batch-size" min="1" max="100">
                            </div>
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
                        <div class="form-row">
                            <div class="form-group">
                                <label>Manufacturer</label>
                                <input type="text" id="manufacturer" disabled>
                            </div>
                            <div class="form-group">
                                <label>Entity Mode</label>
                                <select id="number-entity-mode" disabled>
                                    <option value="auto">Auto</option>
                                    <option value="slider">Slider</option>
                                    <option value="box">Box</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="actions">
                <button class="btn btn-primary" onclick="saveLiveConfig()">💾 Save Live Changes</button>
                <button class="btn btn-secondary" onclick="loadConfig()">🔄 Reload</button>
                <button class="btn btn-secondary" onclick="exportConfig()">📥 Export Config</button>
            </div>
        </div>

        <!-- Live Values Tab -->
        <div id="sensors" class="content">
            <div class="card">
                <div class="card-header">
                    <div class="card-title">
                        <div class="card-icon">📊</div>
                        Live Sensor Values
                    </div>
                    <button class="btn btn-secondary btn-sm" onclick="loadSensorValues()">🔄 Refresh</button>
                </div>
                <div class="card-body">
                    <div class="sensor-grid" id="sensor-grid">
                        <div class="empty-state">
                            <div class="empty-state-icon">📊</div>
                            <p>Loading sensor values...</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Add/Edit Inverter Modal -->
    <div class="modal-overlay" id="inverter-modal">
        <div class="modal">
            <div class="modal-header">
                <div class="modal-title" id="inverter-modal-title">Add Inverter</div>
                <button class="modal-close" onclick="closeInverterModal()">&times;</button>
            </div>
            <div class="modal-body">
                <input type="hidden" id="inverter-edit-index" value="-1">
                <div class="form-group">
                    <label>HA Prefix *</label>
                    <input type="text" id="inv-ha-prefix" placeholder="e.g., ss1">
                    <div class="input-hint">Unique identifier for Home Assistant entities</div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Serial Number</label>
                        <input type="text" id="inv-serial" placeholder="Inverter serial">
                    </div>
                    <div class="form-group">
                        <label>Modbus ID</label>
                        <input type="number" id="inv-modbus-id" value="1" min="1" max="247">
                    </div>
                </div>
                <div class="form-group">
                    <label>Port / Connection</label>
                    <input type="text" id="inv-port" placeholder="tcp://192.168.1.100:502">
                    <div class="input-hint">Leave empty to use default debug_device</div>
                </div>
                <div class="form-group">
                    <label>Dongle Serial (for Solarman)</label>
                    <input type="number" id="inv-dongle-serial" value="0">
                    <div class="input-hint">Only for Solarman driver</div>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" onclick="closeInverterModal()">Cancel</button>
                <button class="btn btn-primary" onclick="saveInverter()">Save Inverter</button>
            </div>
        </div>
    </div>

    <!-- Add/Edit Schedule Modal -->
    <div class="modal-overlay" id="schedule-modal">
        <div class="modal">
            <div class="modal-header">
                <div class="modal-title" id="schedule-modal-title">Add Schedule</div>
                <button class="modal-close" onclick="closeScheduleModal()">&times;</button>
            </div>
            <div class="modal-body">
                <input type="hidden" id="schedule-edit-index" value="-1">
                <div class="form-group">
                    <label>Key / Sensor Pattern *</label>
                    <input type="text" id="sched-key" placeholder="e.g., battery_*, power">
                    <div class="input-hint">Use * as wildcard to match multiple sensors</div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Read Every (seconds)</label>
                        <input type="number" id="sched-read-every" value="60" min="5">
                    </div>
                    <div class="form-group">
                        <label>Report Every (seconds)</label>
                        <input type="number" id="sched-report-every" value="60" min="5">
                    </div>
                </div>
                <div class="form-group">
                    <label>Change Detection</label>
                    <div class="form-row">
                        <div>
                            <input type="checkbox" id="sched-change-any"> Report on any change
                        </div>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Change By (absolute)</label>
                        <input type="number" id="sched-change-by" value="0" step="0.1">
                    </div>
                    <div class="form-group">
                        <label>Change Percent (%)</label>
                        <input type="number" id="sched-change-percent" value="0" step="0.1">
                    </div>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" onclick="closeScheduleModal()">Cancel</button>
                <button class="btn btn-primary" onclick="saveSchedule()">Save Schedule</button>
            </div>
        </div>
    </div>

    <div class="toast" id="toast">
        <span id="toast-message"></span>
    </div>

    <script>
        // State
        let currentConfig = {};
        let availableSensors = {};
        let selectedSensors = new Set();
        let firstInverterSensors = new Set();

        // Tab switching
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.content').forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                document.getElementById(tab.dataset.tab).classList.add('active');

                // Load data for specific tabs
                if (tab.dataset.tab === 'sensors-config') loadAvailableSensors();
                if (tab.dataset.tab === 'sensors') loadSensorValues();
            });
        });

        // Toast
        function showToast(message, type = 'success') {
            const toast = document.getElementById('toast');
            document.getElementById('toast-message').textContent = message;
            toast.className = 'toast show ' + type;
            setTimeout(() => toast.classList.remove('show'), 3000);
        }

        // Load config
        async function loadConfig() {
            try {
                const response = await fetch('/api/config');
                currentConfig = await response.json();

                // Populate form fields
                document.getElementById('mqtt-host').value = currentConfig.mqtt?.host || '';
                document.getElementById('mqtt-port').value = currentConfig.mqtt?.port || '';
                document.getElementById('mqtt-username').value = currentConfig.mqtt?.username || '';
                document.getElementById('modbus-driver').value = currentConfig.driver || '';
                document.getElementById('modbus-timeout').value = currentConfig.timeout || '';
                document.getElementById('modbus-batch-size').value = currentConfig.read_sensors_batch_size || '';
                document.getElementById('modbus-allow-gap').value = currentConfig.read_allow_gap || '';
                document.getElementById('sensor-definitions').value = currentConfig.sensor_definitions || '';
                document.getElementById('manufacturer').value = currentConfig.manufacturer || '';
                document.getElementById('number-entity-mode').value = currentConfig.number_entity_mode || '';
                document.getElementById('quick-debug').value = currentConfig.debug || '0';
                document.getElementById('quick-timeout').value = currentConfig.timeout || '';

                renderInvertersList();
                renderSchedulesList();
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

                const container = document.getElementById('dashboard-inverters');
                if (status.inverters?.length > 0) {
                    container.innerHTML = status.inverters.map(inv => `
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
                } else {
                    container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🔌</div><p>No inverters running</p></div>';
                }

                const hasConnected = status.inverters?.some(inv => inv.connected);
                document.getElementById('connection-status').style.background = hasConnected ? 'var(--success)' : 'var(--warning)';
                document.getElementById('status-text').textContent = hasConnected ? 'Connected' : 'Connecting...';
            } catch (err) {
                document.getElementById('connection-status').style.background = 'var(--error)';
                document.getElementById('status-text').textContent = 'Disconnected';
            }
        }

        // Render inverters list
        function renderInvertersList() {
            const container = document.getElementById('inverters-list');
            const inverters = currentConfig.inverters || [];

            if (inverters.length === 0) {
                container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🔌</div><p>No inverters configured. Click "Add Inverter" to get started.</p></div>';
                return;
            }

            container.innerHTML = inverters.map((inv, idx) => `
                <div class="inverter-card">
                    <div class="inverter-status pending"></div>
                    <div class="inverter-info">
                        <div class="inverter-name">${inv.ha_prefix}</div>
                        <div class="inverter-details">
                            Serial: ${inv.serial_nr || 'N/A'} |
                            Modbus ID: ${inv.modbus_id} |
                            Port: ${inv.port || 'default'}
                        </div>
                    </div>
                    <div class="inverter-actions">
                        <button class="btn btn-secondary btn-sm" onclick="editInverter(${idx})">Edit</button>
                        <button class="btn btn-danger btn-sm" onclick="deleteInverter(${idx})">Delete</button>
                    </div>
                </div>
            `).join('');
        }

        // Render schedules list
        function renderSchedulesList() {
            const container = document.getElementById('schedules-list');
            const schedules = currentConfig.schedules || [];

            if (schedules.length === 0) {
                container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">⏱️</div><p>No schedules configured. Using defaults.</p></div>';
                return;
            }

            container.innerHTML = schedules.map((sched, idx) => `
                <div class="schedule-card">
                    <div class="schedule-header">
                        <div class="schedule-key">${sched.key}</div>
                        <div class="inverter-actions">
                            <button class="btn btn-secondary btn-sm" onclick="editSchedule(${idx})">Edit</button>
                            <button class="btn btn-danger btn-sm" onclick="deleteSchedule(${idx})">Delete</button>
                        </div>
                    </div>
                    <div class="schedule-details">
                        <div>Read: ${sched.read_every}s</div>
                        <div>Report: ${sched.report_every}s</div>
                        <div>Any Change: ${sched.change_any ? 'Yes' : 'No'}</div>
                        <div>Change By: ${sched.change_by}</div>
                        <div>Change %: ${sched.change_percent}%</div>
                    </div>
                </div>
            `).join('');
        }

        // Inverter Modal
        function showAddInverterModal() {
            document.getElementById('inverter-modal-title').textContent = 'Add Inverter';
            document.getElementById('inverter-edit-index').value = '-1';
            document.getElementById('inv-ha-prefix').value = '';
            document.getElementById('inv-serial').value = '';
            document.getElementById('inv-modbus-id').value = '1';
            document.getElementById('inv-port').value = '';
            document.getElementById('inv-dongle-serial').value = '0';
            document.getElementById('inverter-modal').classList.add('show');
        }

        function editInverter(index) {
            const inv = currentConfig.inverters[index];
            document.getElementById('inverter-modal-title').textContent = 'Edit Inverter';
            document.getElementById('inverter-edit-index').value = index;
            document.getElementById('inv-ha-prefix').value = inv.ha_prefix;
            document.getElementById('inv-serial').value = inv.serial_nr || '';
            document.getElementById('inv-modbus-id').value = inv.modbus_id;
            document.getElementById('inv-port').value = inv.port || '';
            document.getElementById('inv-dongle-serial').value = inv.dongle_serial_number || 0;
            document.getElementById('inverter-modal').classList.add('show');
        }

        function closeInverterModal() {
            document.getElementById('inverter-modal').classList.remove('show');
        }

        async function saveInverter() {
            const index = parseInt(document.getElementById('inverter-edit-index').value);
            const data = {
                ha_prefix: document.getElementById('inv-ha-prefix').value,
                serial_nr: document.getElementById('inv-serial').value,
                modbus_id: parseInt(document.getElementById('inv-modbus-id').value),
                port: document.getElementById('inv-port').value,
                dongle_serial_number: parseInt(document.getElementById('inv-dongle-serial').value) || 0,
            };

            if (!data.ha_prefix) {
                showToast('HA Prefix is required', 'error');
                return;
            }

            try {
                let response;
                if (index === -1) {
                    response = await fetch('/api/inverters', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(data),
                    });
                } else {
                    response = await fetch(`/api/inverters/${index}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(data),
                    });
                }

                const result = await response.json();
                if (response.ok) {
                    showToast(result.message + (result.requires_restart ? ' (restart required)' : ''), 'warning');
                    closeInverterModal();
                    loadConfig();
                } else {
                    showToast(result.error, 'error');
                }
            } catch (err) {
                showToast('Failed to save inverter: ' + err.message, 'error');
            }
        }

        async function deleteInverter(index) {
            if (!confirm('Are you sure you want to delete this inverter?')) return;

            try {
                const response = await fetch(`/api/inverters/${index}`, { method: 'DELETE' });
                const result = await response.json();
                if (response.ok) {
                    showToast(result.message, 'warning');
                    loadConfig();
                } else {
                    showToast(result.error, 'error');
                }
            } catch (err) {
                showToast('Failed to delete inverter: ' + err.message, 'error');
            }
        }

        // Schedule Modal
        function showAddScheduleModal() {
            document.getElementById('schedule-modal-title').textContent = 'Add Schedule';
            document.getElementById('schedule-edit-index').value = '-1';
            document.getElementById('sched-key').value = '';
            document.getElementById('sched-read-every').value = '60';
            document.getElementById('sched-report-every').value = '60';
            document.getElementById('sched-change-any').checked = false;
            document.getElementById('sched-change-by').value = '0';
            document.getElementById('sched-change-percent').value = '0';
            document.getElementById('schedule-modal').classList.add('show');
        }

        function editSchedule(index) {
            const sched = currentConfig.schedules[index];
            document.getElementById('schedule-modal-title').textContent = 'Edit Schedule';
            document.getElementById('schedule-edit-index').value = index;
            document.getElementById('sched-key').value = sched.key;
            document.getElementById('sched-read-every').value = sched.read_every;
            document.getElementById('sched-report-every').value = sched.report_every;
            document.getElementById('sched-change-any').checked = sched.change_any;
            document.getElementById('sched-change-by').value = sched.change_by;
            document.getElementById('sched-change-percent').value = sched.change_percent;
            document.getElementById('schedule-modal').classList.add('show');
        }

        function closeScheduleModal() {
            document.getElementById('schedule-modal').classList.remove('show');
        }

        async function saveSchedule() {
            const index = parseInt(document.getElementById('schedule-edit-index').value);
            const data = {
                key: document.getElementById('sched-key').value,
                read_every: parseInt(document.getElementById('sched-read-every').value),
                report_every: parseInt(document.getElementById('sched-report-every').value),
                change_any: document.getElementById('sched-change-any').checked,
                change_by: parseFloat(document.getElementById('sched-change-by').value),
                change_percent: parseFloat(document.getElementById('sched-change-percent').value),
            };

            if (!data.key) {
                showToast('Key is required', 'error');
                return;
            }

            try {
                let response;
                if (index === -1) {
                    response = await fetch('/api/schedules', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(data),
                    });
                } else {
                    response = await fetch(`/api/schedules/${index}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(data),
                    });
                }

                const result = await response.json();
                if (response.ok) {
                    showToast(result.message, 'warning');
                    closeScheduleModal();
                    loadConfig();
                } else {
                    showToast(result.error, 'error');
                }
            } catch (err) {
                showToast('Failed to save schedule: ' + err.message, 'error');
            }
        }

        async function deleteSchedule(index) {
            if (!confirm('Are you sure you want to delete this schedule?')) return;

            try {
                const response = await fetch(`/api/schedules/${index}`, { method: 'DELETE' });
                const result = await response.json();
                if (response.ok) {
                    showToast(result.message, 'warning');
                    loadConfig();
                } else {
                    showToast(result.error, 'error');
                }
            } catch (err) {
                showToast('Failed to delete schedule: ' + err.message, 'error');
            }
        }

        // Sensor selection
        async function loadAvailableSensors() {
            try {
                const response = await fetch('/api/sensors/available');
                const data = await response.json();
                availableSensors = data.categories || {};
                selectedSensors = new Set(data.selected_sensors || []);
                firstInverterSensors = new Set(data.first_inverter_sensors || []);
                renderSensorSelection();
            } catch (err) {
                showToast('Failed to load sensors: ' + err.message, 'error');
            }
        }

        function renderSensorSelection() {
            const container = document.getElementById('sensor-selection');
            const categories = Object.keys(availableSensors).sort();

            if (categories.length === 0) {
                container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📊</div><p>No sensors available</p></div>';
                return;
            }

            container.innerHTML = categories.map(category => {
                const sensors = availableSensors[category];
                const selectedCount = sensors.filter(s => selectedSensors.has(s.id)).length;
                return `
                    <div class="sensor-category">
                        <div class="sensor-category-header" onclick="toggleCategory('${category}')">
                            <span class="sensor-category-title">${category}</span>
                            <span class="sensor-category-count">${selectedCount}/${sensors.length}</span>
                        </div>
                        <div class="sensor-list" id="cat-${category.replace(/[^a-z0-9]/gi, '')}">
                            ${sensors.map(s => `
                                <label class="sensor-chip ${selectedSensors.has(s.id) ? 'selected' : ''}" onclick="toggleSensor('${s.id}', this)">
                                    <span>${s.name}</span>
                                    ${s.unit ? `<small>(${s.unit})</small>` : ''}
                                </label>
                            `).join('')}
                        </div>
                    </div>
                `;
            }).join('');
        }

        function toggleCategory(category) {
            const list = document.getElementById('cat-' + category.replace(/[^a-z0-9]/gi, ''));
            list.classList.toggle('show');
        }

        function toggleSensor(sensorId, element) {
            if (selectedSensors.has(sensorId)) {
                selectedSensors.delete(sensorId);
                element.classList.remove('selected');
            } else {
                selectedSensors.add(sensorId);
                element.classList.add('selected');
            }
            updateSensorCounts();
        }

        function updateSensorCounts() {
            document.querySelectorAll('.sensor-category').forEach(cat => {
                const header = cat.querySelector('.sensor-category-header');
                const chips = cat.querySelectorAll('.sensor-chip');
                const selectedCount = Array.from(chips).filter(c => c.classList.contains('selected')).length;
                const countEl = header.querySelector('.sensor-category-count');
                countEl.textContent = `${selectedCount}/${chips.length}`;
            });
        }

        function selectAllSensors() {
            Object.values(availableSensors).flat().forEach(s => selectedSensors.add(s.id));
            document.querySelectorAll('.sensor-chip').forEach(el => el.classList.add('selected'));
            updateSensorCounts();
        }

        function clearAllSensors() {
            selectedSensors.clear();
            document.querySelectorAll('.sensor-chip').forEach(el => el.classList.remove('selected'));
            updateSensorCounts();
        }

        async function saveSensorSelection() {
            try {
                const response = await fetch('/api/sensors/update', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        sensors: Array.from(selectedSensors),
                        sensors_first_inverter: Array.from(firstInverterSensors),
                    }),
                });

                const result = await response.json();
                if (response.ok) {
                    showToast(`Saved ${result.sensors_count} sensors (restart required)`, 'warning');
                } else {
                    showToast(result.error, 'error');
                }
            } catch (err) {
                showToast('Failed to save sensors: ' + err.message, 'error');
            }
        }

        // Load sensor values
        async function loadSensorValues() {
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

                grid.innerHTML = html || '<div class="empty-state"><div class="empty-state-icon">📊</div><p>No sensor data available</p></div>';
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
                    showToast('Errors: ' + (result.errors || []).join(', '), 'error');
                }
            } catch (err) {
                showToast('Failed to save config: ' + err.message, 'error');
            }
        }

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

                if (response.ok) {
                    showToast('Settings applied successfully');
                } else {
                    showToast('Failed to apply settings', 'error');
                }
            } catch (err) {
                showToast('Failed to apply settings: ' + err.message, 'error');
            }
        }

        function exportConfig() {
            window.location.href = '/api/config/export';
        }

        // Initialize
        loadConfig();
        loadStatus();
        setInterval(loadStatus, 30000);
    </script>
</body>
</html>
"""
