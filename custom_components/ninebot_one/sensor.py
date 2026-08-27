"""Sensors for Ninebot One telemetry."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfPower,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import NinebotConfigEntry, NinebotCoordinator
from .entity import NinebotEntity
from .protocol import WheelState


@dataclass(frozen=True, kw_only=True)
class NinebotSensorDescription(SensorEntityDescription):
    value_fn: Callable[[WheelState], float | int | str | None]
    restore: bool = False
    restore_fn: Callable[[WheelState, float | int | str], None] | None = None


def _seed(attr: str) -> Callable[[WheelState, float | int | str], None]:
    def seed(state: WheelState, value: float | int | str) -> None:
        if getattr(state, attr) is None:
            setattr(state, attr, value)

    return seed


SENSORS: tuple[NinebotSensorDescription, ...] = (
    NinebotSensorDescription(
        key="battery",
        name="Battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda s: s.battery,
        restore=True,
        restore_fn=_seed("battery"),
    ),
    NinebotSensorDescription(
        key="voltage",
        name="Voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=1,
        value_fn=lambda s: s.voltage,
        restore=True,
        restore_fn=_seed("voltage"),
    ),
    NinebotSensorDescription(
        key="speed",
        name="Speed",
        device_class=SensorDeviceClass.SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        suggested_display_precision=1,
        value_fn=lambda s: s.speed,
    ),
    NinebotSensorDescription(
        key="total_distance",
        name="Total distance",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=1,
        value_fn=lambda s: s.total_distance,
        restore=True,
        restore_fn=_seed("total_distance"),
    ),
    NinebotSensorDescription(
        key="current",
        name="Current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=1,
        value_fn=lambda s: s.current,
    ),
    NinebotSensorDescription(
        key="power",
        name="Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        value_fn=lambda s: s.power,
    ),
    NinebotSensorDescription(
        key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda s: s.temperature,
        restore=True,
        restore_fn=_seed("temperature"),
    ),
    NinebotSensorDescription(
        key="serial",
        name="Serial number",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:identifier",
        value_fn=lambda s: s.serial,
        restore=True,
        restore_fn=_seed("serial"),
    ),
    NinebotSensorDescription(
        key="firmware",
        name="Firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:chip",
        value_fn=lambda s: s.firmware,
        restore=True,
        restore_fn=_seed("firmware"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinebotConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(NinebotSensor(coordinator, desc) for desc in SENSORS)


class NinebotSensor(NinebotEntity, RestoreSensor):
    """A telemetry sensor; sticky values survive HA restarts via restore."""

    entity_description: NinebotSensorDescription

    def __init__(
        self, coordinator: NinebotCoordinator, description: NinebotSensorDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.address}_{description.key}"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if not self.entity_description.restore or self.entity_description.restore_fn is None:
            return
        if self.entity_description.value_fn(self.coordinator.state) is not None:
            return
        last = await self.async_get_last_sensor_data()
        if last is not None and last.native_value is not None:
            self.entity_description.restore_fn(self.coordinator.state, last.native_value)
            self.async_write_ha_state()

    @property
    def native_value(self) -> float | int | str | None:
        return self.entity_description.value_fn(self.coordinator.state)
