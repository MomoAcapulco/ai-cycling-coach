"""Structured workouts without ERG: blocks with a power target (a % of the FTP); the rider reaches it with the gears.

A workout is a list of blocks (warm-up, work, recovery, cool-down). Each block lasts ``seconds`` and its target goes
from ``start_pct`` to ``end_pct`` of the FTP (equal for a steady block, different for a ramp), with an optional
cadence. The app shows the target, the time left and what comes next; it never sends a power target to the trainer.

Time only runs while the session is RUNNING («Pausar» pauses the workout too). Each block is scored when it ends:
average power against the average target («cumplimiento») and the share of seconds within ±10 % of the target
(«en rango»). Lost data counts as 0 W: a block ridden without data cannot look fulfilled.

The library (``LIBRARY``) is built for MTB marathons (long climbs, changes of pace): recovery, tempo, sweet spot,
threshold, VO2max, low-cadence climbs and over-unders. Percentages follow the usual Coggan zones.
"""
from dataclasses import dataclass
from time import monotonic
from typing import Dict, List, Optional, Tuple

IN_RANGE = 0.10           # ±10 % of the target counts as «en rango»: without ERG, holding a target is approximate
ROUND_W = 5               # targets in steps of 5 W: easier to read and to aim at


@dataclass(frozen=True)
class Block:
    name: str
    kind: str             # WARMUP | WORK | REST | COOLDOWN
    seconds: int
    start_pct: float
    end_pct: Optional[float] = None
    cadence: Optional[int] = None

    @property
    def last_pct(self) -> float:
        return self.start_pct if self.end_pct is None else self.end_pct

    def pct_at(self, t: float) -> float:
        frac = min(1.0, max(0.0, t / self.seconds))
        return self.start_pct + (self.last_pct - self.start_pct) * frac


@dataclass(frozen=True)
class WorkoutDef:
    id: str
    name: str
    goal: str
    blocks: Tuple[Block, ...]

    @property
    def seconds(self) -> int:
        return sum(b.seconds for b in self.blocks)

    def to_json(self, ftp: Optional[int] = None) -> dict:
        total = self.seconds
        work = sum(b.seconds for b in self.blocks if b.kind == 'WORK')
        # intensity factor and TSS if ridden exactly as planned (power-weighted like NP, per block)
        mean4 = sum(b.seconds * ((b.start_pct + b.last_pct) / 2 / 100) ** 4 for b in self.blocks) / total
        intensity = mean4 ** 0.25
        return {'id': self.id, 'name': self.name, 'goal': self.goal, 'seconds': total, 'workSeconds': work,
                'intensityFactor': round(intensity, 2), 'tss': round(total / 3600 * intensity ** 2 * 100),
                'blocks': [block_json(b, ftp) for b in self.blocks]}


def watts(pct: float, ftp: int) -> int:
    return int(round(ftp * pct / 100 / ROUND_W) * ROUND_W)


def block_json(b: Block, ftp: Optional[int]) -> dict:
    return {'name': b.name, 'kind': b.kind, 'seconds': b.seconds, 'startPct': b.start_pct, 'endPct': b.last_pct,
            'cadence': b.cadence,
            'startW': watts(b.start_pct, ftp) if ftp else None, 'endW': watts(b.last_pct, ftp) if ftp else None}


# ---- the library -------------------------------------------------------------------------------------------------
def _min(m: float) -> int:
    return int(round(m * 60))


def warmup(minutes=10, to_pct=70) -> List[Block]:
    return [Block('Calentamiento', 'WARMUP', _min(minutes), 45, to_pct, 90)]


def cooldown(minutes=8) -> List[Block]:
    return [Block('Vuelta a la calma', 'COOLDOWN', _min(minutes), 60, 40, 90)]


def repeats(n: int, work: Block, rest: Optional[Block]) -> List[Block]:
    out: List[Block] = []
    for i in range(1, n + 1):
        out.append(Block(f'{work.name} {i}/{n}', work.kind, work.seconds, work.start_pct, work.end_pct, work.cadence))
        if rest is not None and i < n:
            out.append(rest)
    return out


def over_unders(sets: int, reps: int, rest_min: float) -> List[Block]:
    out: List[Block] = []
    for s in range(1, sets + 1):
        for r in range(1, reps + 1):
            out.append(Block(f'Serie {s}/{sets} · bajo', 'WORK', _min(2), 95, cadence=85))
            out.append(Block(f'Serie {s}/{sets} · sobre', 'WORK', _min(1), 108, cadence=90))
        if s < sets:
            out.append(Block('Recuperación', 'REST', _min(rest_min), 55, cadence=90))
    return out


EASY = 55
LIBRARY: Dict[str, WorkoutDef] = {w.id: w for w in (
    WorkoutDef('recovery', 'Recuperación activa', 'Soltar piernas tras un día duro o una carrera. Siempre suave.',
               (Block('Suave', 'WARMUP', _min(5), 45, 55, 90), Block('Rodaje suave', 'WORK', _min(30), 55, cadence=90),
                Block('Suelta', 'COOLDOWN', _min(5), 50, 40, 90))),
    WorkoutDef('tempo-2x20', 'Tempo 2×20', 'Base de resistencia para maratón: ritmo sostenido que puedes mantener horas.',
               (*warmup(), *repeats(2, Block('Tempo', 'WORK', _min(20), 80, cadence=85),
                                    Block('Recuperación', 'REST', _min(5), EASY, cadence=90)), *cooldown(10))),
    WorkoutDef('sweetspot-3x12', 'Sweet spot 3×12', 'Mucho trabajo útil con poca fatiga: sube el FTP y el ritmo de subida.',
               (*warmup(), *repeats(3, Block('Sweet spot', 'WORK', _min(12), 90, cadence=85),
                                    Block('Recuperación', 'REST', _min(4), EASY, cadence=90)), *cooldown())),
    WorkoutDef('threshold-2x15', 'Umbral 2×15', 'Al límite sostenible: las subidas largas de la carrera.',
               (*warmup(12, 75), *repeats(2, Block('Umbral', 'WORK', _min(15), 97, cadence=85),
                                          Block('Recuperación', 'REST', _min(6), EASY, cadence=90)), *cooldown(10))),
    WorkoutDef('vo2-5x4', 'VO2 máx 5×4', 'Potencia aeróbica máxima: repechos y cambios de ritmo fuertes.',
               (*warmup(12, 75), *repeats(5, Block('VO2 máx', 'WORK', _min(4), 115, cadence=95),
                                          Block('Recuperación', 'REST', _min(4), 50, cadence=90)), *cooldown(10))),
    WorkoutDef('climbs-5x6', 'Subidas BTT 5×6 a baja cadencia', 'Fuerza en subida: marcha dura, 60–65 rpm, sentado.',
               (*warmup(), *repeats(5, Block('Subida', 'WORK', _min(6), 88, cadence=62),
                                    Block('Recuperación', 'REST', _min(4), EASY, cadence=90)), *cooldown())),
    WorkoutDef('over-unders-3x9', 'Cambios de ritmo 3×9', 'Over-unders: 2 min bajo el umbral y 1 min por encima, como un '
               'repecho dentro de una subida.', (*warmup(12, 75), *over_unders(3, 3, 5), *cooldown(10))),
)}


# ---- riding one ---------------------------------------------------------------------------------------------------
class StructuredWorkout:
    """One workout being ridden, fed with the 1 Hz telemetry (``tick``) like the ramp test."""

    def __init__(self, definition: WorkoutDef, ftp: int, ftp_source: str = 'profile', clock=monotonic):
        self.definition, self.ftp, self.ftp_source, self.clock = definition, ftp, ftp_source, clock
        self.phase = 'RUNNING'
        self.reason: Optional[str] = None
        self.elapsed = 0.0                       # workout time: paused time does not count
        self.last: Optional[float] = None
        self.index = 0
        self.results: List[dict] = []
        self._reset_block()

    @property
    def running(self) -> bool:
        return self.phase == 'RUNNING'

    # ---- position ----
    def _starts(self) -> List[int]:
        out, t = [], 0
        for b in self.definition.blocks:
            out.append(t)
            t += b.seconds
        return out

    def block(self) -> Optional[Block]:
        return self.definition.blocks[self.index] if self.running else None

    def block_elapsed(self) -> float:
        return self.elapsed - self._starts()[self.index]

    def target_w(self) -> Optional[int]:
        b = self.block()
        return None if b is None else watts(b.pct_at(self.block_elapsed()), self.ftp)

    # ---- 1 Hz telemetry ----
    def tick(self, reading: dict):
        if not self.running:
            return
        now = self.clock()
        dt, self.last = (0.0 if self.last is None else min(5.0, now - self.last)), now
        if reading.get('sessionState', 'RUNNING') != 'RUNNING' or dt <= 0:
            return
        live = bool(reading.get('connected'))
        power = float(reading.get('powerWatts') or 0) if live else 0.0
        while dt > 1e-9 and self.running:
            b = self.definition.blocks[self.index]
            left = b.seconds - self.block_elapsed()
            step = min(dt, left)
            target = watts(b.pct_at(self.block_elapsed() + step / 2), self.ftp)
            self._acc['seconds'] += step
            self._acc['power'] += power * step
            self._acc['target'] += target * step
            if target and abs(power - target) <= IN_RANGE * target:
                self._acc['in_range'] += step
            self.elapsed += step
            dt -= step
            if step >= left - 1e-9:
                self._close_block()
                if self.index + 1 < len(self.definition.blocks):
                    self.index += 1
                else:
                    self.phase, self.reason = 'DONE', 'completed'

    def _reset_block(self):
        self._acc = {'seconds': 0.0, 'power': 0.0, 'target': 0.0, 'in_range': 0.0}

    def _close_block(self):
        a, b = self._acc, self.definition.blocks[self.index]
        if a['seconds'] >= 1:
            avg, target = a['power'] / a['seconds'], a['target'] / a['seconds']
            self.results.append({'name': b.name, 'kind': b.kind, 'seconds': round(a['seconds']),
                                 'plannedSeconds': b.seconds, 'avgW': round(avg), 'targetW': round(target),
                                 'compliancePct': round(100 * avg / target) if target else None,
                                 'inRangePct': round(100 * a['in_range'] / a['seconds'])})
        self._reset_block()

    # ---- end ----
    def finish(self, reason: str = 'rider finished'):
        if not self.running:
            return
        self._close_block()                      # the block being ridden counts for what was done of it
        self.phase, self.reason = 'DONE', reason

    def summary(self) -> dict:
        """What the session summary keeps (session_<stamp>.json → «workout»)."""
        work = [r for r in self.results if r['kind'] == 'WORK']
        return {'type': 'STRUCTURED', 'id': self.definition.id, 'name': self.definition.name, 'ftpW': self.ftp,
                'ftpSource': self.ftp_source, 'endReason': self.reason, 'completedPct': self.completed_pct(),
                'workCompliancePct': _weighted(work, 'compliancePct'), 'workInRangePct': _weighted(work, 'inRangePct'),
                'blocks': self.results}

    def completed_pct(self) -> int:
        return round(100 * min(self.elapsed, self.definition.seconds) / self.definition.seconds)

    def snapshot(self) -> dict:
        b = self.block()
        nxt = self.definition.blocks[self.index + 1] if self.running and self.index + 1 < len(self.definition.blocks) else None
        work = [r for r in self.results if r['kind'] == 'WORK']
        return {'workoutType': 'STRUCTURED', 'workoutId': self.definition.id, 'workoutName': self.definition.name,
                'workoutPhase': self.phase, 'workoutRunning': self.running,
                'workoutElapsedS': round(self.elapsed), 'workoutTotalS': self.definition.seconds,
                'workoutBlock': self.index + 1 if b else None, 'workoutBlockCount': len(self.definition.blocks),
                'workoutBlockName': b.name if b else None, 'workoutBlockKind': b.kind if b else None,
                'workoutStepRemainingS': max(0, round(b.seconds - self.block_elapsed())) if b else None,
                'targetPowerW': self.target_w(), 'targetCadenceRpm': b.cadence if b else None,
                'workoutNext': None if nxt is None else {'name': nxt.name, 'kind': nxt.kind, 'seconds': nxt.seconds,
                                                         'targetW': watts(nxt.start_pct, self.ftp), 'cadence': nxt.cadence},
                'workoutFtpW': self.ftp, 'workoutFtpSource': self.ftp_source,
                'workoutPlan': [block_json(x, self.ftp) for x in self.definition.blocks],
                'workoutResults': self.results, 'workoutCompliancePct': _weighted(work, 'compliancePct'),
                'workoutEndReason': self.reason}


def _weighted(rows: List[dict], key: str) -> Optional[int]:
    rows = [r for r in rows if r.get(key) is not None]
    total = sum(r['seconds'] for r in rows)
    return round(sum(r[key] * r['seconds'] for r in rows) / total) if total else None
