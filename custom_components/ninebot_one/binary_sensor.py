"""Binary sensors for Ninebot One."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import NinebotConfigEntry, NinebotCoordinator
from .entity import NinebotEntity

CHARGING_CURRENT_THRESHOLD = -0.1
# A battery-% rise at standstill within this window also counts as charging
# (current readings fluctuate around zero on some wheels/chargers).
RISE_WINDOW_SECONDS = 900


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinebotConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [NinebotConnectedSensor(coordinator), NinebotChargingSensor(coordinator)]
    )


class NinebotConnectedSensor(NinebotEntity, BinarySensorEntity):
    """Whether HA currently holds the wheel's BLE connection."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_name = "Connected"

    def __init__(self, coordinator: NinebotCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_connected"

    @property
    def is_on(self) -> bool:
        return self.coordinator.connected


class NinebotChargingSensor(NinebotEntity, BinarySensorEntity):
    """Charging heuristic: negative current at standstill."""

    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING
    _attr_name = "Charging"

    def __init__(self, coordinator: NinebotCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_charging"

    @property
    def is_on(self) -> bool:
        coord = self.coordinator
        state = coord.state
        if not coord.connected:
            return False
        current_draw = (
            state.current is not None
            and state.current < CHARGING_CURRENT_THRESHOLD
            and (state.speed or 0.0) < 1.0
        )
        recent_rise = (
            coord.last_charge_rise > 0
            and coord.hass.loop.time() - coord.last_charge_rise < RISE_WINDOW_SECONDS
        )
        return current_draw or recent_rise
