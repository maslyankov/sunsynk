"""Parse sensors from options."""

import logging
import traceback
from typing import Generator, Iterable

import attrs

from ha_addon_sunsynk_multi.helpers import import_mysensors
from ha_addon_sunsynk_multi.options import OPT
from ha_addon_sunsynk_multi.timer_schedule import SCHEDULES, Schedule, get_schedule
from sunsynk.definitions.single_phase import SENSORS as SENSORS_1PH
from sunsynk.definitions.three_phase_hv import SENSORS as SENSORS_3PHV
from sunsynk.definitions.three_phase_lv import SENSORS as SENSORS_3PHLV
from sunsynk.helpers import slug
from sunsynk.rwsensors import RWSensor
from sunsynk.sensors import Sensor, SensorDefinitions

_LOGGER = logging.getLogger(__name__)

DEFS = SensorDefinitions()
"""Sensor definitions (1ph / 3ph)."""


@attrs.define(slots=True)
class SensorOption:
    """Options for a sensor."""

    sensor: Sensor
    schedule: Schedule
    visible: bool = True
    startup: bool = False
    affects: set[Sensor] = attrs.field(factory=set)
    """Affect sensors due to dependencies."""
    first: bool = False
    """Only on the first inverter."""

    def __hash__(self) -> int:
        """Hash the sensor id."""
        return self.sensor.__hash__()


@attrs.define(slots=True)
class SensorOptions(dict[Sensor, SensorOption]):
    """A dict of sensors from the configuration."""

    startup: set[Sensor] = attrs.field(factory=set)

    def _add_sensor_with_deps(self, sensor: Sensor, visible: bool = False, path: set[Sensor] | None = None) -> None:
        """Add a sensor and all its dependencies recursively.
        
        Args:
            sensor: The sensor to add
            visible: Whether the sensor should be visible
            path: Set of sensors in the current dependency path to detect cycles
        """
        if path is None:
            path = set()

        if sensor in path:
            _LOGGER.warning("Circular dependency detected for sensor %s", sensor.name)
            return

        path.add(sensor)

        # Add to startup set regardless of visibility
        self.startup.add(sensor)

        # Check if sensor is explicitly included in any group using slugified names
        sensor_slug = slug(sensor.name)
        is_in_group = any(
            slug(name) == sensor_slug
            for group in SENSOR_GROUPS.values()
            for name in group
        )

        # Only add to SOPT if it's explicitly requested (visible) or a direct dependency
        if visible or len(path) <= 2 or is_in_group:  # Original sensor or direct dependency or in group
            if sensor not in self:
                self[sensor] = SensorOption(
                    sensor=sensor,
                    schedule=get_schedule(sensor, SCHEDULES),
                    visible=visible or is_in_group,  # Make visible if in group
                )

        if isinstance(sensor, RWSensor):
            for dep in sensor.dependencies:
                # Pass visibility if the dependency is also in a group
                dep_visible = visible or any(
                    slug(name) == slug(dep.name)
                    for group in SENSOR_GROUPS.values()
                    for name in group
                )
                self._add_sensor_with_deps(dep, visible=dep_visible, path=path.copy())
                if dep in self and sensor in self:  # Only track affects if both sensors are in SOPT
                    self[dep].affects.add(sensor)

        path.remove(sensor)

    def init_sensors(self) -> None:
        """Parse options and get the various sensor lists."""
        if not DEFS.all:
            import_definitions()
        self.clear()

        # Add startup sensors
        self.startup = {DEFS.rated_power, DEFS.serial}
        self._add_sensor_with_deps(DEFS.rated_power, visible=False)
        self._add_sensor_with_deps(DEFS.serial, visible=False)

        # Add sensors from config
        for sen in get_sensors(target=self, names=OPT.sensors):
            self._add_sensor_with_deps(sen, visible=True)

        # Add 1st inverter sensors
        for sen in get_sensors(target=self, names=OPT.sensors_first_inverter):
            if sen not in self:
                self[sen] = SensorOption(
                    sensor=sen,
                    schedule=get_schedule(sen, SCHEDULES),
                    visible=True,
                    first=True,
                )
                self._add_sensor_with_deps(sen, visible=True)

        # Info if we have hidden sensors
        if hidden := [s.sensor.name for s in self.values() if not s.visible]:
            _LOGGER.info(
                "Added hidden sensors as other sensors depend on it: %s",
                ", ".join(hidden),
            )


def import_definitions() -> None:
    """Load definitions according to options."""
    DEFS.all.clear()
    DEFS.deprecated.clear()

    # Load DEFS
    if OPT.sensor_definitions == "three-phase":
        _LOGGER.info("Using three phase sensor definitions.")
        DEFS.all = dict(SENSORS_3PHLV.all)
        DEFS.deprecated = SENSORS_3PHLV.deprecated
    elif OPT.sensor_definitions == "three-phase-hv":
        _LOGGER.info("Using three phase HV sensor definitions.")
        DEFS.all = dict(SENSORS_3PHV.all)
        DEFS.deprecated = SENSORS_3PHV.deprecated
    else:
        _LOGGER.info("Using Single phase sensor definitions.")
        DEFS.all = dict(SENSORS_1PH.all)
        DEFS.deprecated = SENSORS_1PH.deprecated

    # Add custom sensors to DEFS
    try:
        mysensors = import_mysensors()
    except ImportError:
        _LOGGER.error("Unable to import import mysensors.py")
        traceback.print_exc()
    if mysensors:
        DEFS.all.update(mysensors)
        SENSOR_GROUPS["mysensors"] = list(mysensors)


SOPT = SensorOptions()
"""A dict of all options related to sensors."""

SENSOR_GROUPS: dict[str, list[str]] = {
    # https://sunsynk.wectrl.net/guide/energy-management
    "energy_management": [
        "total_battery_charge",
        "total_battery_discharge",
        "total_grid_export",
        "total_grid_import",
        "total_pv_energy",
    ],
    # https://sunsynk.wectrl.net/examples/lovelace#sunsynk-power-flow-card
    "power_flow_card": [
        "aux_power",
        "battery_1_soc",  # 3PH HV
        "battery_1_voltage",  # 3PH HV
        "battery_current",
        "battery_power",
        "battery_soc",  # 1PH & 3PH LV
        "battery_voltage",  # 1PH & 3PH LV
        "day_battery_charge",
        "day_battery_discharge",
        "day_grid_export",
        "day_grid_import",
        "day_load_energy",
        "day_pv_energy",
        "essential_power",
        "grid_connected",
        "grid_ct_power",
        "grid_frequency",
        "grid_l1_power",  # 3PH LV & HV
        "grid_l2_power",  # 3PH LV & HV
        "grid_l3_power",  # 3PH LV & HV
        "grid_power",
        "grid_voltage",
        "grid_current",
        "inverter_current",
        "inverter_power",
        "inverter_voltage",
        "load_frequency",
        "load_power",
        "load_l1_power",
        "load_l2_power",
        "load_l3_power",
        "load_l1_voltage",
        "load_l2_voltage",
        "load_l3_voltage",
        "non_essential_power",
        "overall_state",
        "priority_load",
        "pv_power",
        "pv1_current",
        "pv1_power",
        "pv1_voltage",
        "pv2_current",
        "pv2_power",
        "pv2_voltage",
        "pv3_current",
        "pv3_power",
        "pv3_voltage",
        "pv4_current",
        "pv4_power",
        "pv4_voltage",
        "use_timer",
    ],
    "settings": [
        "load_limit",
        "prog1_capacity",
        "prog1_charge",
        "prog1_power",
        "prog1_time",
        "prog2_capacity",
        "prog2_charge",
        "prog2_power",
        "prog2_time",
        "prog3_capacity",
        "prog3_charge",
        "prog3_power",
        "prog3_time",
        "prog4_capacity",
        "prog4_charge",
        "prog4_power",
        "prog4_time",
        "prog5_capacity",
        "prog5_charge",
        "prog5_power",
        "prog5_time",
        "prog6_capacity",
        "prog6_charge",
        "prog6_power",
        "prog6_time",
        "date_time",
        "grid_charge_battery_current",
        "grid_charge_start_battery_soc",
        "grid_charge_enabled",
        "use_timer",
        "solar_export",
        "export_limit_power",
        "battery_max_charge_current",
        "battery_max_discharge_current",
        "battery_capacity_current",
        "battery_shutdown_capacity",
        "battery_restart_capacity",
        "battery_low_capacity",
        "battery_type",
        "battery_wake_up",
        "battery_resistance",
        "battery_charge_efficiency",
        "grid_standard",
        "configured_grid_frequency",
        "configured_grid_phases",
        "ups_delay_time",
    ],
    "generator": [
        "generator_port_usage",
        "generator_off_soc",
        "generator_on_soc",
        "generator_max_operating_time",
        "generator_cooling_time",
        "min_pv_power_for_gen_start",
        "generator_charge_enabled",
        "generator_charge_start_battery_soc",
        "generator_charge_battery_current",
        "gen_signal_on",
    ],
    "diagnostics": [
        "inverter_l1_power",
        "inverter_l2_power",
        "inverter_l3_power",
        "grid_voltage",
        "grid_l1_voltage",
        "grid_l2_voltage",
        "grid_l3_voltage",
        "battery_temperature",
        "battery_voltage",
        "battery_soc",
        "battery_power",
        "battery_current",
        "fault",
        "dc_transformer_temperature",
        "radiator_temperature",
        "grid_relay_status",
        "inverter_relay_status",
        "battery_bms_alarm_flag",
        "battery_bms_fault_flag",
        "battery_bms_soh",
        "fan_warning",
        "grid_phase_warning",
        "lithium_battery_loss_warning",
        "parallel_communication_quality_warning",
    ],
    "battery": [
        "battery_type",
        "battery_capacity_current",
        "battery_max_charge_current",
        "battery_max_discharge_current",
        "battery_shutdown_capacity",
        "battery_restart_capacity",
        "battery_low_capacity",
        "battery_equalization_voltage",
        "battery_absorption_voltage",
        "battery_float_voltage",
        "battery_shutdown_voltage",
        "battery_low_voltage",
        "battery_restart_voltage",
        "battery_wake_up",
        "battery_resistance",
        "battery_charge_efficiency",
        "battery_equalization_days",
        "battery_equalization_hours",
    ],
}


def get_sensors(
    *, target: Iterable[Sensor], names: list[str], warn: bool = True
) -> Generator[Sensor, None, None]:
    """Add a sensor."""
    groups: set[str] = set()

    for sensor_def in names:
        if ":" in sensor_def:
            _LOGGER.error("Modifiers was replaced by schedules: %s", sensor_def)
            continue

        name = slug(sensor_def)

        # Recursive add for groups
        if name in SENSOR_GROUPS or name == "all":
            groups.add(name)
            continue

        # Warn on deprecated
        if name in DEFS.deprecated:
            if warn:
                _LOGGER.error(
                    "Your config includes deprecated sensors. Replace %s with %s",
                    name,
                    DEFS.deprecated[name],
                )
            continue

        if name in [t.name for t in target] and warn:
            _LOGGER.warning("Sensor %s only allowed once", name)
            continue

        sen = DEFS.all.get(name)
        if not isinstance(sen, Sensor):
            if warn:
                _LOGGER.error("Unknown sensor specified: %s", name)
            continue

        yield sen

    # Add groups at the end
    for name in groups:
        names = list(DEFS.all) if name == "all" else SENSOR_GROUPS[name]
        yield from get_sensors(target=target, names=names, warn=False)
