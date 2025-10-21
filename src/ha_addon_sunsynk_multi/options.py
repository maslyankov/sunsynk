"""Addon options."""

import logging

import attrs
import cattrs
from mqtt_entity.options import CONVERTER, MQTTOptions, transform_error

from .timer_schedule import Schedule

_LOG = logging.getLogger(__name__)


def _convert_connectors(data: list) -> "list[ConnectorOptions]":
    """Convert list of dicts to list of ConnectorOptions."""
    _LOG.debug("_convert_connectors called with: %s (type: %s)", data, type(data))

    if not isinstance(data, list):
        _LOG.error("Expected list, got %s: %s", type(data), data)
        raise ValueError(f"Expected list, got {type(data)}")

    # Debug logging
    _LOG.debug("Converting connectors: %s", data)
    for i, item in enumerate(data):
        _LOG.debug("Connector[%d]: %s (type: %s)", i, item, type(item))
        if not isinstance(item, dict):
            _LOG.error(
                "Connector[%d] is not a dict: %s (type: %s)", i, item, type(item)
            )
            raise ValueError(
                f"Connector[{i}] is not a dict: {item} (type: {type(item)})"
            )

    return [cattrs.structure(item, ConnectorOptions) for item in data]


def _convert_inverters(data: list) -> "list[InverterOptions]":
    """Convert list of dicts to list of InverterOptions."""
    if not isinstance(data, list):
        raise ValueError(f"Expected list, got {type(data)}")
    return [cattrs.structure(item, InverterOptions) for item in data]


def _convert_schedules(data: list) -> "list[Schedule]":
    """Convert list of dicts to list of Schedule."""
    if not isinstance(data, list):
        raise ValueError(f"Expected list, got {type(data)}")
    return [cattrs.structure(item, Schedule) for item in data]


@attrs.define()
class ConnectorOptions:
    """Options for a connector."""

    name: str
    type: str  # tcp, serial, solarman
    host: str = ""
    port: int = 502
    driver: str = "pymodbus"
    timeout: int = 10
    dongle_serial: int = 0
    baudrate: int = 9600

    def __attrs_post_init__(self) -> None:
        """Validate connector configuration."""
        if self.type not in ("tcp", "serial", "solarman"):
            raise ValueError(f"Invalid connector type: {self.type}")
        if self.driver not in ("pymodbus", "umodbus", "solarman"):
            raise ValueError(f"Invalid driver: {self.driver}")
        if self.type == "solarman" and not self.dongle_serial:
            raise ValueError("Solarman connector requires dongle_serial")


@attrs.define()
class InverterOptions:
    """Options for an inverter."""

    connector: str = ""  # Reference to connector name
    port: str = ""  # Legacy: direct port (backwards compatibility)
    modbus_id: int = 0
    ha_prefix: str = ""
    serial_nr: str = ""
    dongle_serial_number: int = 0

    def __attrs_post_init__(self) -> None:
        """Do some checks."""
        self.ha_prefix = self.ha_prefix.lower().strip()

        # Validate connector vs port usage
        if self.connector and self.port:
            _LOG.warning(
                "%s: Both connector and port specified. Using connector: %s",
                self.serial_nr,
                self.connector,
            )
        # Legacy port handling
        if not self.connector:
            if self.dongle_serial_number:
                if self.port:
                    _LOG.warning(
                        "%s: No port expected when you specify a serial number."
                    )
                return
            if self.port == "":
                _LOG.warning(
                    "%s: Using port from debug_device: %s",
                    self.serial_nr,
                    OPT.debug_device,
                )
                self.port = OPT.debug_device
            ddev = self.port == ""
            if ddev:
                _LOG.warning("Empty port, will use the debug device")
            if ddev or self.port.lower().startswith(("serial:", "/dev")):
                _LOG.warning(
                    "Use mbusd instead of connecting directly to a serial port"
                )


@attrs.define()
class Options(MQTTOptions):
    """HASS Addon Options."""

    number_entity_mode: str = "auto"
    prog_time_interval: int = 15
    connectors: list[ConnectorOptions] = attrs.field(factory=list)
    inverters: list[InverterOptions] = attrs.field(factory=list)
    sensor_definitions: str = "single-phase"
    sensors: list[str] = attrs.field(factory=list)
    sensors_first_inverter: list[str] = attrs.field(factory=list)
    read_allow_gap: int = 2
    read_sensors_batch_size: int = 20
    schedules: list[Schedule] = attrs.field(factory=list)
    timeout: int = 10
    debug: int = 0
    driver: str = "pymodbus"
    manufacturer: str = "Sunsynk"
    debug_device: str = ""

    def __attrs_post_init__(self) -> None:
        """Do some checks."""
        if self.driver == "umodbus":
            _LOG.warning("Try *pymodbus* if your encounter any issues with *umodbus*")

    def load_dict(
        self, value: dict, log_lvl: int = logging.DEBUG, log_msg: str = ""
    ) -> None:
        """Load configuration with custom handling for complex types."""
        _LOG.log(log_lvl, "%s: %s", log_msg or "Loading config", value)

        # Create a copy to avoid modifying the original
        config = value.copy()

        # Handle connectors conversion
        if "connectors" in config:
            _LOG.debug(
                "Raw connectors data: %s (type: %s)",
                config["connectors"],
                type(config["connectors"]),
            )
            config["connectors"] = _convert_connectors(config["connectors"])

        # Handle inverters conversion
        if "inverters" in config:
            config["inverters"] = _convert_inverters(config["inverters"])

        # Handle schedules conversion
        if "schedules" in config:
            config["schedules"] = _convert_schedules(config["schedules"])

        # Use cattrs to structure the remaining configuration (excluding complex fields)
        try:
            # Create a copy without the complex types for cattrs processing
            simple_config = {
                k: v
                for k, v in config.items()
                if k not in ("connectors", "inverters", "schedules")
            }

            # Create a temporary class without the complex fields for cattrs
            @attrs.define()
            class SimpleOptions(MQTTOptions):
                """Temporary options class without complex fields."""

                number_entity_mode: str = "auto"
                prog_time_interval: int = 15
                sensor_definitions: str = "single-phase"
                sensors: list[str] = attrs.field(factory=list)
                sensors_first_inverter: list[str] = attrs.field(factory=list)
                read_allow_gap: int = 2
                read_sensors_batch_size: int = 20
                timeout: int = 10
                debug: int = 0
                driver: str = "pymodbus"
                manufacturer: str = "Sunsynk"
                debug_device: str = ""

            val = CONVERTER.structure(simple_config, SimpleOptions)
        except Exception as exc:
            msg = "Error loading config: " + "\n".join(transform_error(exc))
            _LOG.error(msg)
            raise ValueError(msg) from None

        # Set attributes from the structured object (excluding already set complex fields)
        for key in simple_config:
            setattr(self, key.lower(), getattr(val, key.lower()))

        # Set the complex fields directly
        for key in ("connectors", "inverters", "schedules"):
            if key in config:
                setattr(self, key.lower(), config[key])


OPT = Options()


async def init_options() -> None:
    """Load the options & setup the logger."""
    await OPT.init_addon()

    # check ha_prefix is unique
    all_prefix = set()
    for inv in OPT.inverters:
        if inv.ha_prefix in all_prefix:
            raise ValueError("HA_PREFIX should be unique")
        all_prefix.add(inv.ha_prefix)

    # check connector names are unique
    connector_names = set()
    for conn in OPT.connectors:
        if conn.name in connector_names:
            raise ValueError(f"Connector name '{conn.name}' should be unique")
        connector_names.add(conn.name)

    # validate inverter connector references
    for inv in OPT.inverters:
        if inv.connector and inv.connector not in connector_names:
            raise ValueError(
                f"Inverter '{inv.serial_nr}' references unknown connector "
                f"'{inv.connector}'"
            )
