"""Tests for the Ninebot One protocol (pure Python, no HA imports)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "ninebot_one"))

from protocol import (  # noqa: E402
    ADDR_APP,
    ADDR_CONTROLLER,
    PARAM_FIRMWARE,
    PARAM_LIVE_DATA,
    PARAM_SERIAL,
    REQUEST_LIVE_DATA,
    REQUEST_SERIAL,
    FrameUnpacker,
    NinebotDecoder,
    build_request,
    verify_frame,
    _checksum,
)


def make_response(param, payload, src=ADDR_CONTROLLER, dst=ADDR_APP):
    body = bytes([len(payload) + 2, src, dst, param]) + payload
    crc = _checksum(body)
    return b"\x55\xaa" + body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def make_live_payload(batt=87, speed_raw=0, dist_m=1234567, temp_dc=245,
                      volt_cv=5820, curr_ca=-120):
    p = bytearray(32)
    p[8:10] = batt.to_bytes(2, "little")
    p[10:12] = (speed_raw & 0xFFFF).to_bytes(2, "little")
    p[14:18] = dist_m.to_bytes(4, "little")
    p[22:24] = temp_dc.to_bytes(2, "little")
    p[24:26] = volt_cv.to_bytes(2, "little")
    p[26:28] = (curr_ca & 0xFFFF).to_bytes(2, "little")
    return bytes(p)


def test_request_frames_match_wheellog_shape():
    # 55 AA len src dst param payload crcL crcH, len = payload+2
    assert REQUEST_SERIAL[:2] == b"\x55\xaa"
    assert REQUEST_SERIAL[2] == 3  # 1-byte payload + 2
    assert REQUEST_SERIAL[3] == ADDR_APP
    assert REQUEST_SERIAL[4] == ADDR_CONTROLLER
    assert REQUEST_SERIAL[5] == PARAM_SERIAL
    assert REQUEST_SERIAL[6] == 0x0E
    body = REQUEST_SERIAL[2:-2]
    crc = REQUEST_SERIAL[-2] | (REQUEST_SERIAL[-1] << 8)
    assert crc == (sum(body) ^ 0xFFFF) & 0xFFFF
    assert REQUEST_LIVE_DATA[5] == PARAM_LIVE_DATA


def test_unpacker_and_verify_roundtrip():
    frame = make_response(PARAM_LIVE_DATA, make_live_payload())
    unpacker = FrameUnpacker()
    got = []
    for b in b"\x00\x55" + frame + b"\x99" + frame:
        raw = unpacker.add_byte(b)
        if raw:
            got.append(raw)
    assert got == [frame, frame]
    parsed = verify_frame(frame)
    assert parsed is not None and parsed.param == PARAM_LIVE_DATA


def test_verify_rejects_bad_crc():
    frame = bytearray(make_response(PARAM_LIVE_DATA, make_live_payload()))
    frame[-1] ^= 0xFF
    assert verify_frame(bytes(frame)) is None


def test_live_data_decoding():
    dec = NinebotDecoder()
    assert dec.handle_notification(
        make_response(PARAM_LIVE_DATA, make_live_payload(
            batt=87, speed_raw=15500, dist_m=1234567, temp_dc=245,
            volt_cv=5820, curr_ca=-120))
    )
    st = dec.state
    assert st.battery == 87
    assert st.speed == 15.5   # 15500 / 1000
    assert st.total_distance == 1234.567
    assert st.temperature == 24.5
    assert st.voltage == 58.2
    assert st.current == -1.2
    assert st.power == round(58.2 * -1.2, 1)


def test_negative_speed_absolute():
    dec = NinebotDecoder()
    dec.handle_notification(
        make_response(PARAM_LIVE_DATA, make_live_payload(speed_raw=-8000))
    )
    assert dec.state.speed == 8.0


def test_serial_and_firmware():
    dec = NinebotDecoder()
    dec.handle_notification(make_response(PARAM_SERIAL, b"N1E12345678901"))
    assert dec.state.serial == "N1E12345678901"
    dec.handle_notification(make_response(PARAM_FIRMWARE, bytes([0x23, 0x01, 0x00])))
    assert dec.state.firmware == "0.2.3"


def test_wrong_payload_length_ignored():
    dec = NinebotDecoder()
    assert not dec.handle_notification(make_response(PARAM_LIVE_DATA, bytes(10)))
    assert dec.state.battery is None


def test_zero_live():
    dec = NinebotDecoder()
    dec.handle_notification(
        make_response(PARAM_LIVE_DATA, make_live_payload(speed_raw=5000, curr_ca=300))
    )
    dec.state.zero_live()
    assert dec.state.speed == 0.0
    assert dec.state.current == 0.0
    assert dec.state.battery == 87


def test_segmented_live_data_fw425():
    from protocol import (
        PARAM_LIVE_BATT_SPEED,
        PARAM_LIVE_DISTANCE,
        PARAM_LIVE_TEMP,
        PARAM_LIVE_VOLT_CURR,
    )
    dec = NinebotDecoder()
    p = bytearray(6); p[2:4] = (91).to_bytes(2, "little"); p[4:6] = (12300).to_bytes(2, "little")
    assert dec.handle_notification(make_response(PARAM_LIVE_BATT_SPEED, bytes(p)))
    p = bytearray(6); p[2:6] = (2345678).to_bytes(4, "little")
    assert dec.handle_notification(make_response(PARAM_LIVE_DISTANCE, bytes(p)))
    p = bytearray(6); p[4:6] = (312).to_bytes(2, "little")
    assert dec.handle_notification(make_response(PARAM_LIVE_TEMP, bytes(p)))
    p = bytearray(4); p[0:2] = (5980).to_bytes(2, "little"); p[2:4] = (65536 - 250).to_bytes(2, "little")
    assert dec.handle_notification(make_response(PARAM_LIVE_VOLT_CURR, bytes(p)))
    st = dec.state
    assert st.battery == 91
    assert st.speed == 12.3
    assert st.total_distance == 2345.678
    assert st.temperature == 31.2
    assert st.voltage == 59.8
    assert st.current == -2.5
    assert st.power == round(59.8 * -2.5, 1)
