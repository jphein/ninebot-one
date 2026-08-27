"""BLE polling coordinator for the Ninebot One.

Maintains an active GATT connection (routed through bluetooth proxies) and
polls the wheel's live-data register — Ninebot wheels answer requests
rather than free-streaming like Begode.

The wheel accepts only ONE BLE client at a time; the `enabled` flag
(exposed as a switch entity) releases it for the phone app.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    BleakError,
    establish_connection,
)

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.match import BluetoothCallbackMatcher
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, POLL_INTERVAL
from .protocol import (
    CHAR_UUID,
    REQUEST_FIRMWARE,
    REQUEST_LIVE_DATA,
    REQUEST_SERIAL,
    NinebotDecoder,
    WheelState,
)

_LOGGER = logging.getLogger(__name__)

RECONNECT_DELAY = 10.0
IDENTITY_POLL_INTERVAL = 0.6

type NinebotConfigEntry = ConfigEntry[NinebotCoordinator]


class NinebotCoordinator(DataUpdateCoordinator[WheelState]):
    """Push-based coordinator holding the wheel's BLE connection."""

    config_entry: NinebotConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: NinebotConfigEntry, address: str
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{address}",
            update_interval=None,
        )
        self.address = address
        self.decoder = NinebotDecoder()
        self.enabled = True
        self.connected = False
        self._client: BleakClient | None = None
        self._connect_lock = asyncio.Lock()
        self._poll_task: asyncio.Task | None = None
        self._reconnect_handle: asyncio.TimerHandle | None = None
        self._stopped = False
        self._unsub_bluetooth: Callable[[], None] | None = None
        self.async_set_updated_data(self.decoder.state)

    @property
    def state(self) -> WheelState:
        return self.decoder.state

    async def async_start(self) -> None:
        self._unsub_bluetooth = bluetooth.async_register_callback(
            self.hass,
            self._advertisement_seen,
            BluetoothCallbackMatcher(address=self.address, connectable=True),
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
        self.config_entry.async_on_unload(self._unsub_bluetooth)
        if bluetooth.async_ble_device_from_address(self.hass, self.address, True):
            self._spawn_connect()

    async def async_stop(self) -> None:
        self._stopped = True
        if self._reconnect_handle:
            self._reconnect_handle.cancel()
            self._reconnect_handle = None
        await self._disconnect()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            self.config_entry.async_create_background_task(
                self.hass, self._disconnect(), f"ninebot_disconnect_{self.address}"
            )
        elif bluetooth.async_ble_device_from_address(self.hass, self.address, True):
            self._spawn_connect()
        self.async_set_updated_data(self.decoder.state)

    def _spawn_connect(self) -> None:
        self.config_entry.async_create_background_task(
            self.hass, self._connect(), f"ninebot_connect_{self.address}"
        )

    @callback
    def _advertisement_seen(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        if self.enabled and not self.connected and not self._connect_lock.locked():
            self._spawn_connect()

    async def _connect(self) -> None:
        if self._stopped or not self.enabled or self.connected:
            return
        async with self._connect_lock:
            if self._stopped or not self.enabled or self.connected:
                return
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self.address, True
            )
            if ble_device is None:
                return
            try:
                client = await establish_connection(
                    BleakClientWithServiceCache,
                    ble_device,
                    self.address,
                    self._disconnected_callback,
                )
                await client.start_notify(CHAR_UUID, self._notification_handler)
            except (BleakError, TimeoutError) as err:
                _LOGGER.debug("Connection to %s failed: %s", self.address, err)
                self._schedule_reconnect()
                return
            self._client = client
            self.connected = True
            _LOGGER.info("Connected to Ninebot %s", self.address)
            self.async_set_updated_data(self.decoder.state)
            self._poll_task = self.config_entry.async_create_background_task(
                self.hass, self._poll_loop(), f"ninebot_poll_{self.address}"
            )

    async def _poll_loop(self) -> None:
        """Request identity once, then live data forever."""
        while self.connected and not self._stopped:
            st = self.state
            if st.serial is None:
                request, delay = REQUEST_SERIAL, IDENTITY_POLL_INTERVAL
            elif st.firmware is None:
                request, delay = REQUEST_FIRMWARE, IDENTITY_POLL_INTERVAL
            else:
                request, delay = REQUEST_LIVE_DATA, POLL_INTERVAL
            client = self._client
            if client is None:
                return
            try:
                await client.write_gatt_char(CHAR_UUID, request, response=False)
            except (BleakError, TimeoutError) as err:
                _LOGGER.debug("Poll write to %s failed: %s", self.address, err)
                return
            await asyncio.sleep(delay)

    def _notification_handler(
        self, _char: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        st = self.state
        had_identity = st.serial is not None and st.firmware is not None
        if self.decoder.handle_notification(bytes(data)):
            if not had_identity and st.serial and st.firmware:
                self._update_device_registry()
            self.async_set_updated_data(st)

    def _update_device_registry(self) -> None:
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(identifiers={(DOMAIN, self.address)})
        if device:
            registry.async_update_device(
                device.id,
                serial_number=self.state.serial or device.serial_number,
                sw_version=self.state.firmware or device.sw_version,
            )

    def _disconnected_callback(self, _client: BleakClient) -> None:
        self.connected = False
        self._client = None
        _LOGGER.info("Ninebot %s disconnected", self.address)
        self.state.zero_live()
        if not self._stopped:
            self.hass.loop.call_soon_threadsafe(self._handle_disconnect)

    def _handle_disconnect(self) -> None:
        self.async_set_updated_data(self.decoder.state)
        self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        if self._stopped or not self.enabled:
            return
        if self._reconnect_handle:
            self._reconnect_handle.cancel()
        self._reconnect_handle = self.hass.loop.call_later(
            RECONNECT_DELAY, self._retry_connect
        )

    def _retry_connect(self) -> None:
        self._reconnect_handle = None
        if self.enabled and not self.connected and not self._stopped:
            self._spawn_connect()

    async def _disconnect(self) -> None:
        client = self._client
        self._client = None
        self.connected = False
        if client is not None:
            try:
                await client.disconnect()
            except (BleakError, TimeoutError):
                pass
