"""Config flow for the Ninebot One integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS, CONF_NAME

from .const import DOMAIN
from .protocol import SERVICE_UUID


class NinebotConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Ninebot One."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a connectable device advertising the UART service."""
        current = self._async_current_ids(include_ignore=False)
        candidates: dict[str, str] = {}
        for info in bluetooth.async_discovered_service_info(self.hass, connectable=True):
            if info.address in current:
                continue
            if SERVICE_UUID in info.service_uuids:
                label = (
                    f"{info.name} ({info.address})"
                    if info.name != info.address
                    else info.address
                )
                candidates[info.address] = label

        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={CONF_ADDRESS: address},
            )

        if not candidates:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(candidates),
                    vol.Required(CONF_NAME, default="Ninebot One"): str,
                }
            ),
        )
