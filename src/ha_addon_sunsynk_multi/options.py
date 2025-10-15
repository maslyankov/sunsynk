"""Addon options."""

import logging

import attrs
from mqtt_entity.options import MQTTOptions

from .timer_schedule import Schedule

_LOG = logging.getLogger(__name__)


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
                self.serial_nr, self.connector
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
