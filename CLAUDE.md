# CLAUDE.md — ninebot-one

Custom Home Assistant integration for JP's Ninebot One E+ EUC over BLE via
the bluetooth proxies. Sibling of `~/Projects/begode` (same architecture);
see README.md for the protocol.

## Key facts

- **Polling, not streaming**: the wheel answers framed register requests
  (`55 AA len src dst param payload crc16LE`); no data arrives unrequested.
  Poll loop: serial → firmware once, then live data (0xB0) every 5 s.
- **BLE**: service `FFE0`, char `FFE1`; wheel advertises no local name.
  Wheel MAC is in the session memory, not this repo.
- **Battery % is reported directly** — no voltage-scale config needed
  (contrast with Begode's 67.2V-base scaling).
- **One BLE client**: HA connection blocks the Ninebot app; per-wheel
  "Maintain connection" switch releases it.
- Only the One E/E+ generation is supported (Z/ES encrypt frames).

## Workflow

Same as begode: edit under `custom_components/ninebot_one/`, run
`python3 -m pytest tests/`, deploy by tar-pipe to the HA VM's
`/config/custom_components/` (host in the `ha` skill), restart HA.
