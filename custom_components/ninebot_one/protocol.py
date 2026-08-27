"""Ninebot One (E/E+) BLE protocol decoder.

SPDX-License-Identifier: GPL-3.0-or-later

Ported from WheelLog's NinebotAdapter (reverse-engineered protocol):
https://github.com/Wheellog/Wheellog.Android (GPL-3.0).

Unlike Begode wheels, the Ninebot One does not free-stream telemetry: the
client polls registers with framed requests and the wheel answers on the
same characteristic. Frame layout (both directions):

    55 AA <len> <src> <dst> <param> <payload…> <crcL> <crcH>

where len = payload_len + 2, crc = (~sum(len..payload)) & 0xFFFF (LE).
This module targets the original Ninebot One E/E+ generation ("default"
protocol in WheelLog): no frame encryption (the Z/ES generations XOR with a
session key and are NOT supported here). Battery percent is reported
directly by the wheel — no voltage-curve estimation needed.
"""
from __future__ import annotations

from dataclasses import dataclass

SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"

ADDR_APP = 0x09
ADDR_CONTROLLER = 0x01

PARAM_SERIAL = 0x10
PARAM_SERIAL2 = 0x13
PARAM_SERIAL3 = 0x16
PARAM_FIRMWARE = 0x1A
PARAM_LIVE_DATA = 0xB0


def _u16le(buf: bytes, off: int) -> int:
    return buf[off] | (buf[off + 1] << 8)


def _s16le(buf: bytes, off: int) -> int:
    val = _u16le(buf, off)
    return val - 0x10000 if val >= 0x8000 else val


def _u32le(buf: bytes, off: int) -> int:
    return _u16le(buf, off) | (_u16le(buf, off + 2) << 16)


def _checksum(body: bytes) -> int:
    return (sum(body) ^ 0xFFFF) & 0xFFFF


def build_request(param: int, payload: bytes) -> bytes:
    """Build a request frame from App to Controller."""
    body = bytes([len(payload) + 2, ADDR_APP, ADDR_CONTROLLER, param]) + payload
    crc = _checksum(body)
    return b"\x55\xaa" + body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


REQUEST_SERIAL = build_request(PARAM_SERIAL, b"\x0e")
REQUEST_FIRMWARE = build_request(PARAM_FIRMWARE, b"\x02")
REQUEST_LIVE_DATA = build_request(PARAM_LIVE_DATA, b"\x20")


class FrameUnpacker:
    """Reassemble length-prefixed frames from the BLE notification stream."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._state = 0  # 0 hunting, 1 got header (next byte is len), 2 collecting
        self._len = 0
        self._prev = -1

    def add_byte(self, c: int) -> bytes | None:
        if self._state == 2:
            self._buf.append(c)
            if len(self._buf) == self._len + 6:
                self._state = 0
                return bytes(self._buf)
        elif self._state == 1:
            self._buf.append(c)
            self._len = c
            self._state = 2
        else:
            if c == 0xAA and self._prev == 0x55:
                self._buf = bytearray(b"\x55\xaa")
                self._state = 1
            self._prev = c
        return None


@dataclass
class Frame:
    src: int
    dst: int
    param: int
    payload: bytes


def verify_frame(buf: bytes) -> Frame | None:
    """Validate checksum and split a raw frame; None if corrupt."""
    if len(buf) < 9:
        return None
    body = buf[2:-2]
    crc = buf[-2] | (buf[-1] << 8)
    if _checksum(body) != crc:
        return None
    return Frame(src=buf[3], dst=buf[4], param=buf[5], payload=bytes(buf[6:-2]))


@dataclass
class WheelState:
    """Decoded wheel telemetry."""

    battery: int | None = None  # %, reported directly
    voltage: float | None = None  # V
    speed: float | None = None  # km/h
    total_distance: float | None = None  # km
    current: float | None = None  # A (negative = charging/regen)
    temperature: float | None = None  # °C
    serial: str | None = None
    firmware: str | None = None

    @property
    def power(self) -> float | None:
        if self.voltage is None or self.current is None:
            return None
        return round(self.voltage * self.current, 1)

    def zero_live(self) -> None:
        if self.speed is not None:
            self.speed = 0.0
        if self.current is not None:
            self.current = 0.0


class NinebotDecoder:
    """Feed BLE notification chunks, maintain a WheelState."""

    def __init__(self) -> None:
        self.state = WheelState()
        self._unpacker = FrameUnpacker()
        self._serial_parts: dict[int, bytes] = {}

    def handle_notification(self, data: bytes) -> bool:
        changed = False
        for byte in data:
            raw = self._unpacker.add_byte(byte)
            if raw is None:
                continue
            frame = verify_frame(raw)
            if frame is not None:
                changed = self._decode_frame(frame) or changed
        return changed

    def _decode_frame(self, frame: Frame) -> bool:
        st = self.state
        if frame.param == PARAM_LIVE_DATA and len(frame.payload) == 32:
            p = frame.payload
            st.battery = _u16le(p, 8)
            st.speed = round(abs(_s16le(p, 10)) / 1000.0, 2)
            st.total_distance = round(_u32le(p, 14) / 1000.0, 3)
            st.temperature = round(_u16le(p, 22) / 10.0, 1)
            st.voltage = round(_u16le(p, 24) / 100.0, 2)
            st.current = round(_s16le(p, 26) / 100.0, 2)
            return True
        if frame.param in (PARAM_SERIAL, PARAM_SERIAL2, PARAM_SERIAL3):
            self._serial_parts[frame.param] = frame.payload
            try:
                st.serial = b"".join(
                    self._serial_parts[k] for k in sorted(self._serial_parts)
                ).decode("ascii").strip("\x00 ")
            except UnicodeDecodeError:
                return False
            return True
        if frame.param == PARAM_FIRMWARE and len(frame.payload) >= 2:
            p = frame.payload
            # Best-effort BCD-style split (WheelLog formats S2/Mini this way;
            # the One E generation predates that code path).
            st.firmware = f"{p[1] >> 4}.{p[0] >> 4}.{p[0] & 0x0F}"
            return True
        return False
