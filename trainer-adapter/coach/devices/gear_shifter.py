"""Native virtual shifting on the trainer (Zwift protocol), driven by the Zwift controllers or the UI.

Rules (validated with the supervised gear test, diagnostics/zwift_gear_test_20261112_155523.json):
- Full Zwift range, gears 1..24, start and neutral gear 12 (2.40), rider/bike weight from the profile.
- Presses are merged: a gear is sent only when no new press came for ``coalesce_s`` (80 ms, Serpentine);
  several quick presses become one jump to the final gear.
- Every gear is CONFIRMED by the trainer (answer 0x3C to HubRequest 520 carries the applied ratio). Without a
  confirmation within ``confirm_timeout_s`` the gear is re-sent, up to ``max_retries``; then the status is
  UNCONFIRMED and the UI keeps showing the last confirmed gear (never the requested one as if applied).
- Never harder without a live, pedalling trainer: if FTMS data is stale or cadence < ``min_cadence``, a harder
  request is refused (the requested gear snaps back to the confirmed one). Easier is always allowed.
- On start (and after a reconnect): Simulation 0.4 % (the trainer ignores gears before a non-zero incline),
  then the current gear and a confirmation request. On finish: gear 12 at 0.4 %.
- Writes go through ``SafeZwiftWriter``: only the Zwift SyncRx characteristic, only RideOn / HubRequest /
  HubCommand without a power target (no ERG here), never the firmware-update service. A grade other than
  0.4 % is only accepted when the writer was given ``incline_limits`` (the rider's min/max, used by
  coach.devices.grade_controller), and never outside -10 % .. +20 %; wind, CdA and Crr stay at the defaults.
"""
from time import monotonic
from typing import Optional

from coach.devices.zwift_hub import (DATA_ID_GEAR_RATIO, FORBIDDEN_SERVICES, GEAR_RATIOS, NEUTRAL_GEAR,
                                     OP_HUB_COMMAND, OP_HUB_REQUEST, RIDE_ON_TRAINER, SYNC_RX, Physical,
                                     Simulation, decode_hub_command, decode_hub_response, decode_riding_data,
                                     encode_hub_command, encode_hub_request, gear_ratio)

START_INCLINE_X100 = 40  # 0.4 %


def gear_for_ratio(ratio_x10000: int) -> Optional[int]:
    """The gear whose ratio matches (±2 for the trainer's rounding: it answers 26099 for 26100)."""
    for gear, ratio in enumerate(GEAR_RATIOS, start=1):
        if abs(round(ratio * 10000) - ratio_x10000) <= 2:
            return gear
    return None


HARD_INCLINE_LIMITS_X100 = (-1000, 2000)  # -10 % .. +20 %, whatever the rider profile says
DEFAULT_SIMULATION = Simulation()


def check_outgoing(uuid: str, data: bytes, incline_limits=None):
    """Raise PermissionError for anything this application must never write to the trainer.

    ``incline_limits``: None (shifting only: 0.4 % is the only grade) or (min_x100, max_x100)."""
    uuid = uuid.lower()
    if uuid in FORBIDDEN_SERVICES or uuid.startswith('8ec90003'):
        raise PermissionError('writing to the firmware-update service is forbidden')
    if uuid != SYNC_RX:
        raise PermissionError(f'only the Zwift SyncRx characteristic may be written, not {uuid}')
    data = bytes(data)
    if data == RIDE_ON_TRAINER:
        return
    if data[:1] == bytes([OP_HUB_REQUEST]):
        return
    if data[:1] == bytes([OP_HUB_COMMAND]):
        command = decode_hub_command(data) or {}
        if 'powerTarget' in command:
            raise PermissionError('power targets (ERG) are not allowed by the shifter')
        gear = command.get('physical', {}).get('gearRatioX10000')
        if gear is not None and gear_for_ratio(gear) is None:
            raise PermissionError(f'unknown gear ratio {gear}')
        simulation = command.get('simulation')
        if simulation is not None:
            if (simulation.get('windX100', 0) != DEFAULT_SIMULATION.wind_x100
                    or simulation.get('cwaX10000') != DEFAULT_SIMULATION.cwa_x10000
                    or simulation.get('crrX100000') != DEFAULT_SIMULATION.crr_x100000):
                raise PermissionError('only the incline may change in a Simulation (wind, CdA, Crr fixed)')
            incline = simulation.get('inclineX100', 0)
            if incline != START_INCLINE_X100:
                if incline_limits is None:
                    raise PermissionError('grade changes are not part of shifting')
                low = max(incline_limits[0], HARD_INCLINE_LIMITS_X100[0])
                high = min(incline_limits[1], HARD_INCLINE_LIMITS_X100[1])
                if not low <= incline <= high:
                    raise PermissionError(f'grade {incline / 100:g} % outside the allowed {low / 100:g}..{high / 100:g} %')
        return
    raise PermissionError(f'unexpected message {data.hex()}')


class SafeZwiftWriter:
    """``incline_limits``: None, or a callable returning (min_x100, max_x100) — read at every write, so a
    profile change applies at once."""
    def __init__(self, client, incline_limits=None):
        self.client = client
        self.incline_limits = incline_limits
        self.sent = []

    async def write(self, data: bytes, uuid: str = SYNC_RX):
        check_outgoing(uuid, data, self.incline_limits() if self.incline_limits else None)
        await self.client.write_gatt_char(uuid, bytes(data), response=False)
        self.sent.append(bytes(data))


class GearShifter:
    def __init__(self, controllers, rider_kg: float, bike_kg: float, clock=monotonic,
                 coalesce_s=0.08, confirm_timeout_s=1.0, max_retries=3, min_cadence=40):
        self.controllers = controllers
        self.rider_kg, self.bike_kg = rider_kg, bike_kg
        self.clock = clock
        self.coalesce_s, self.confirm_timeout_s = coalesce_s, confirm_timeout_s
        self.max_retries, self.min_cadence = max_retries, min_cadence
        self.confirmed_gear: Optional[int] = None
        self.pending_gear: Optional[int] = None
        self.sent_at = 0.0
        self.retries = 0
        self.status = 'STARTING'
        self.last_refusal: Optional[str] = None
        controllers.attach_shifter(self)

    # ---- messages from the trainer ----
    def on_message(self, raw: bytes):
        response = decode_hub_response(raw)
        if response and response.get('dataId') == DATA_ID_GEAR_RATIO and 'gearRatioX10000' in response:
            gear = gear_for_ratio(response['gearRatioX10000'])
            if gear is not None:
                self.confirmed_gear = gear
                if self.pending_gear == gear:
                    self.pending_gear = None
                    self.retries = 0
                    self.status = 'READY'
            return
        decode_riding_data(raw)  # RidingData: FTMS stays the source of truth for telemetry

    # ---- commands ----
    def _gear_message(self, gear):
        return encode_hub_command(physical=Physical.of(gear_ratio(gear), bike_kg=self.bike_kg, rider_kg=self.rider_kg))

    async def _send_gear(self, writer, gear):
        await writer.write(self._gear_message(gear))
        await writer.write(encode_hub_request(DATA_ID_GEAR_RATIO))
        self.pending_gear = gear
        self.sent_at = self.clock()
        self.status = 'WAITING_CONFIRMATION'

    async def start(self, writer):
        """After connecting (or reconnecting): RideOn, 0.4 %, then the gear the rider is in."""
        await writer.write(RIDE_ON_TRAINER)
        await writer.write(encode_hub_command(simulation=Simulation(incline_x100=START_INCLINE_X100)))
        self.retries = 0
        await self._send_gear(writer, self.controllers.requested_gear())

    async def tick(self, writer, trainer: dict):
        """Called every ~0.25 s by the trainer worker with the latest FTMS snapshot."""
        now = self.clock()
        target = self.controllers.requested_gear()
        reference = self.pending_gear or self.confirmed_gear or NEUTRAL_GEAR
        if target != reference:
            if target > reference and not self._pedalling(trainer):
                self.last_refusal = 'harder refused: not pedalling or no live trainer data'
                self.controllers.force_gear(reference)
                return
            if now - self.controllers.last_request_at() < self.coalesce_s:
                return  # more presses may follow: send only the final gear
            self.retries = 0
            await self._send_gear(writer, target)
            return
        if self.pending_gear is not None and now - self.sent_at > self.confirm_timeout_s:
            if self.retries < self.max_retries:
                self.retries += 1
                await self._send_gear(writer, self.pending_gear)
            else:
                self.status = 'UNCONFIRMED'
                self.pending_gear = None
                if self.confirmed_gear is not None:
                    self.controllers.force_gear(self.confirmed_gear)

    async def finish(self, writer):
        """Leave the trainer in the known neutral state (gear 12, 0.4 %)."""
        await writer.write(encode_hub_command(simulation=Simulation(incline_x100=START_INCLINE_X100)))
        await writer.write(self._gear_message(NEUTRAL_GEAR))
        self.controllers.force_gear(NEUTRAL_GEAR)
        self.status = 'STOPPED'

    def disconnected(self):
        self.pending_gear = None
        self.status = 'DISCONNECTED'

    def _pedalling(self, trainer: dict) -> bool:
        return bool(trainer.get('connected')) and (trainer.get('cadenceRpm') or 0) >= self.min_cadence

    def snapshot(self):
        gear = self.confirmed_gear
        return {'gearControlMode': 'TRAINER', 'trainerGear': gear,
                'trainerGearRatio': GEAR_RATIOS[gear - 1] if gear else None,
                'requestedGear': self.controllers.requested_gear(), 'gearStatus': self.status,
                'gearRetries': self.retries, 'gearLastRefusal': self.last_refusal}
