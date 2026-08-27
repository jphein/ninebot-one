"""Base entity for Ninebot One."""
from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NinebotCoordinator


class NinebotEntity(CoordinatorEntity[NinebotCoordinator]):
    """Entity tied to one wheel's coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NinebotCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            name=coordinator.config_entry.title,
            manufacturer="Ninebot",
            model="One E",
            serial_number=coordinator.state.serial,
            sw_version=coordinator.state.firmware,
        )
