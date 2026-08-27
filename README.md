# ninebot-one — Home Assistant integration for the Ninebot One E/E+

Custom HA integration that connects to a Ninebot One electric unicycle over
BLE (via bluetooth proxies with active connections) and exposes its
telemetry as sensors.

## How it works

The Ninebot One bridges its controller bus over BLE (service `FFE0`,
characteristic `FFE1`) but — unlike Begode wheels — does **not** free-stream
telemetry: the client polls registers with framed requests and the wheel
answers on the same characteristic. Frame layout (both directions):

```
55 AA <len> <src> <dst> <param> <payload…> <crcL> <crcH>
len = payload_len + 2 · crc = (~sum(len…payload)) & 0xFFFF, little-endian
```

The coordinator requests serial number (`0x10`) and firmware (`0x1A`) once,
then polls live data (`0xB0`, 32-byte payload) every 5 s:

| Offset (LE) | Field | Scale |
|---|---|---|
| 8 | battery | % (direct — no voltage-curve estimation) |
| 10 | speed | /1000 km/h (signed; abs) |
| 14 | total distance | u32 meters |
| 22 | temperature | /10 °C |
| 24 | voltage | /100 V |
| 26 | current | /100 A (signed) |

Protocol ported from WheelLog's `NinebotAdapter`. Only the original One
E/E+ generation is supported — the Z/ES generations encrypt frames with a
session key and need a different handshake.

## Entities

Sensors: battery, voltage, speed, total distance, current, power,
temperature, serial + firmware diagnostics. Binary sensors: connected,
charging. Switch: **maintain connection** — the wheel accepts a single BLE
client, so turn it off to release the wheel to the Ninebot app before a
ride. Sticky values are restored across HA restarts; speed/current zero out
on disconnect.

## Deploying

```bash
tar cz -C custom_components ninebot_one | ssh <user>@<ha-host> "sudo tar xz -C /config/custom_components/"
# restart HA, then add via Settings → Devices & Services → Add → Ninebot One EUC
```

## Tests

```bash
python3 -m pytest tests/
```

## License

**GPL-3.0** (see LICENSE): `protocol.py` derives from WheelLog's
`NinebotAdapter` ([Wheellog/Wheellog.Android](https://github.com/Wheellog/Wheellog.Android),
GPL-3.0). Credit and thanks to the WheelLog contributors.
