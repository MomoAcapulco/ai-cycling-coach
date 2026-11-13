# ADR-002 — Bluetooth autodiscovery

**Status:** Accepted (v4.3.0)

## Context
Until v4.2.2 the trainer, heart-rate strap and Zwift controllers were found by Mac-specific BLE UUIDs written in `.env` (or a name substring). Changing Mac, controller or trainer meant editing configuration by hand, and left/right controllers had to be known in advance.

## Decision
1. **Classify by advertisement, not by name** (`trainer-adapter/coach/bluetooth/discovery.py`), in this order:
   - Trainer: FTMS `0x1826`, Cycling Power `0x1818` or Wahoo `a026ee0b-…`. First, because trainers also advertise Heart Rate (relayed strap) and KICKR CORE 2 class trainers advertise the Zwift service.
   - Zwift controller: Zwift service `00000001-19ca-…` / `0xFC82` or manufacturer data of Zwift, Inc. (`0x094A`). First manufacturer byte = type: `0x02` Play right, `0x03` Play left, `0x07/0x08` Ride right/left, `0x09` Click, `0x0A/0x0B` Click v2 right/left, `0x0E` Play firmware 2 (no side). `0x0A/0x0B` are marked unconfirmed in BikeControl; **our scan of 2026-11-12 confirms them**: our controllers are two Zwift Click v2 advertising `0xFC82` with manufacturer data `0b…` (left) and `0a…` (right).
   - Heart rate: service `0x180D` only, last.
   - Advertisements of one address are merged: macOS delivers name, services and manufacturer data in separate packets.
2. **Side of a controller**: from the type byte; otherwise from the first button press. In our recordings the left (bits 0,1,2,3,9) and right (bits 4,5,6,8,13) button bits do not overlap, so packets are decoded correctly in either slot and the side is learned and remembered.
3. **Per-role resolution** (`coach/bluetooth/device_finder.py`): explicit ID in `.env` (never silently replaced) > remembered device > classified scan. (The optional name hints `WAHOO_DEVICE_NAME` / `HR_DEVICE_NAME` were removed on 2026-11-13, see the revision below.) Two controller slots never take the same device.
4. **Registry** (`coach/bluetooth/device_registry.py`) in `devices.json` of the data home (`ai-cycling-coach-data`, see `coach/app/paths.py`; `DEVICES_FILE`), outside the version folders; atomic writes; one device per role; damaged file ignored. Stores address plus name, kind and Zwift type, so a device can be recognised by class elsewhere (macOS addresses are per-Mac UUIDs).
5. **One scan at a time** through the shared lock of the single BLE event loop (`coach/bluetooth/ble_runtime.py`), as BikeControl and Serpentine serialise connects.
6. **Zwift handshake** unchanged: plain `RideOn` to `…0003` after subscribing to `…0002` (no encryption needed; BikeControl, Incyclist, zwiftplay, jat255). Battery: message `0x19`, protobuf field 2 — confirmed on our controllers (`19 10 50` = 80 %, equal to Battery Level `0x50`).

## Sources (read at the pinned commits, 2026-11-12)
| Project | Licence | Used as |
|---|---|---|
| [incyclist/devices](https://github.com/incyclist/devices) @07e0035 | MIT | type bytes, FTMS priority, reconnect by address |
| [chrisperkles/serpentine](https://github.com/chrisperkles/serpentine) @e4f2126 | MIT | role filters, sequential reconnects, address over name |
| [OpenBikeControl/bikecontrol](https://github.com/OpenBikeControl/bikecontrol) @341ad5c | Non-commercial (GPL-3.0 up to tag `gpl3`) | **ideas only**: classification order, merged adverts, remembered snapshot |
| [ajchellew/zwiftplay](https://github.com/ajchellew/zwiftplay) @f1c1fe4 | none (all rights reserved) | **ideas only**: protocol, plain handshake |
| [jat255/zwift_click_handling](https://github.com/jat255/zwift_click_handling) @7cf896d | MIT | handshake, battery field |
| [dadepro/zwift-virtual-shifting](https://github.com/dadepro/zwift-virtual-shifting) @9a852ef | MIT | Python/Bleak reference |
| [OpenBikeControl/openbikecontrol-protocol](https://github.com/OpenBikeControl/openbikecontrol-protocol) @b0dbbe8 | MIT | future: standard button protocol |

No code was copied; the rules above are re-implemented.

## Consequences
+ No device IDs needed in `.env`; a new Mac or controller is found and remembered automatically.
+ Left/right works even when the advertisement has no type byte.
- A controller with no type byte may be shown in the "wrong" slot until its first press; shifting still works, and the next start uses the learned side.
- Verified on hardware (2026-11-12): Click v2 left/right type bytes, HR50 strap (`0x180D`, name `HR50-…`). Not yet: the KICKR CORE 2 advertisement (it was not in the scan).

## Revision 2026-11-13: several devices per role, never guess

**Problem found in review.** One device was remembered per role. When it was not around, the scan took the FIRST
device that answered and replaced the remembered one. Using strap A one day and strap B the next worked, but
each switch cost an 8 s wait and forgot the other strap. Worse: with two unknown straps nearby (a training partner's,
a neighbour's), the app could record **someone else's pulse without saying so**. The same applied to trainers.
Besides, a name hint in `.env` (`HR_DEVICE_NAME=HR50`) is a strict filter: a strap of another brand is never found.

**Decision.**
- The registry keeps **every device used for each role**, with its last use and at most one `preferred`
  (file format version 2; version 1 files are read and converted, nothing is lost).
- **One scan** collects every candidate; it stops early when the best-ranked known device shows up.
  - A known device present: the preferred one, else the most recently used one.
  - None known and exactly one new device: use it and add it.
  - None known and several new devices: **no guess**. The candidates are shown in Ajustes (and the Panel says
    so) for the rider to choose; the worker looks again later.
  - Controllers: only several new controllers announcing the SAME side are ambiguous. Two controllers without a
    side are the rider's pair, and the first press puts each one in its place. A device known in another role
    never counts as a candidate.
- **"Usar este"** in Ajustes marks the preferred device. The heart-rate strap and the controllers switch at once;
  the trainer switches at its next connection (never in the middle of a ride).
- `.env` keeps priority with an ID, which fixes the device; Ajustes shows it.
- **Name hints removed** (`WAHOO_DEVICE_NAME`, `HR_DEVICE_NAME`): devices are found by TYPE only (what they
  advertise), any brand. The hints were a guard for "take the first that answers"; with every device remembered
  and no guessing they only got in the way (a strap of another brand was never found). Old `.env` files: the keys
  are ignored with a note at start-up.

**Consequences.**
+ Two straps or two trainers in turn: both remembered, recognised at once.
+ Never someone else's device by chance.
- With several unknown devices and none known, the rider has to choose once.
- Verified with fake scanners only (tests/test_device_choice.py); a check with two real straps is pending.
