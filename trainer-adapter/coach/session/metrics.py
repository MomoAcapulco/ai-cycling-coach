"""Session metrics from the 1 Hz samples, with explicit rules and standard formulas.

- Only LIVE samples count (``connected`` true). A dropout is a gap: nothing is invented to fill it.
- Time: ``elapsed`` = active session time (pauses excluded); ``moving`` = live samples with cadence or power > 0.
- Distance: from the virtual road (``rideDistanceKm``, physics speed) when the reading has it — differences
  between consecutive live samples, so pauses and dropouts add nothing; otherwise Σ trainer speed·dt (old
  recordings, FTMS test). Work (kJ) = Σ power·dt / 1000, over live samples.
- Elevation gain: differences of ``elevationGainM`` (road grade, not the difficulty-scaled one). VAM = gain /
  climbing time × 3600 (m/h), climbing time = live time while gaining height; only from 60 s of climbing.
- Best efforts: best mean power over 5 s, 1, 5 and 20 min of consecutive live 1 Hz samples (a dropout breaks
  the window). Estimated FTP = 95 % of the best 20 min (Allen & Coggan), only with 20 min of data.
- W/kg: average power and best 20 min divided by the rider's weight (profile).
- Average power: over all live samples (zeros included, as Garmin/TrainingPeaks) and over moving samples only.
  Average cadence excludes zeros (coasting). Max power and max heart rate over live samples.
- Normalized Power (Coggan): 30-sample rolling mean of 1 Hz power, raised to the 4th power, averaged, 4th root.
  Not computed with fewer than 30 samples (it would not be meaningful).
- IF = NP / FTP and TSS = hours × IF² × 100, only when the rider profile has an FTP.
"""
from collections import deque
from typing import Optional

NP_WINDOW = 30
BEST_EFFORT_SECONDS = (5, 60, 300, 1200)
MIN_CLIMB_SECONDS_FOR_VAM = 60


class SessionMetrics:
    def __init__(self):
        self.elapsed = 0.0
        self.moving = 0.0
        self.distance_km = 0.0
        self.work_j = 0.0
        self.powers = []          # live samples, 1 Hz
        self.moving_powers = []
        self.cadences = []        # > 0 only
        self.heart_rates = []
        self.gear_seconds = {}
        self._window = deque(maxlen=NP_WINDOW)
        self._rolling4 = []
        self.gain_m = 0.0
        self.climb_seconds = 0.0
        self.series = []          # 1 Hz power with None for dropouts: best efforts never span a gap
        self._last_ride = None    # (rideDistanceKm, elevationGainM) of the previous sample

    def restart_counters(self):
        """After a pause: the distance ridden while paused does not count."""
        self._last_ride = None

    def add(self, sample: dict, dt: float):
        dt = max(0.0, float(dt))
        self.elapsed += dt
        ride = (sample.get('rideDistanceKm'), sample.get('elevationGainM'))
        previous, self._last_ride = self._last_ride, ride if ride[0] is not None else None
        if not sample.get('connected'):
            self.series.append(None)
            return  # dropout: a gap, not zeros
        power = float(sample.get('powerWatts') or 0)
        cadence = float(sample.get('cadenceRpm') or 0)
        if ride[0] is not None:
            if previous is not None:
                self.distance_km += max(0.0, ride[0] - previous[0])
                climbed = max(0.0, (ride[1] or 0) - (previous[1] or 0))
                self.gain_m += climbed
                if climbed > 0:
                    self.climb_seconds += dt
        else:
            speed = float(sample.get('speedKph') or 0)
            self.distance_km += max(0.0, speed) * dt / 3600
        self.series.append(power)
        self.work_j += max(0.0, power) * dt
        self.powers.append(power)
        self._window.append(power)
        if len(self._window) == NP_WINDOW:
            self._rolling4.append((sum(self._window) / NP_WINDOW) ** 4)
        if cadence > 0 or power > 0:
            self.moving += dt
            self.moving_powers.append(power)
        if cadence > 0:
            self.cadences.append(cadence)
        heart = sample.get('heartRateBpm')
        if sample.get('heartRateConnected') and heart:
            self.heart_rates.append(float(heart))
        gear = sample.get('trainerGear')
        if gear:
            self.gear_seconds[int(gear)] = self.gear_seconds.get(int(gear), 0.0) + dt

    @staticmethod
    def _mean(values):
        return round(sum(values) / len(values), 1) if values else None

    def normalized_power(self) -> Optional[float]:
        if not self._rolling4:
            return None
        return round((sum(self._rolling4) / len(self._rolling4)) ** 0.25, 1)

    def best_efforts(self) -> dict:
        out = {}
        for window in BEST_EFFORT_SECONDS:
            best, total, run = None, 0.0, []
            for value in self.series:
                if value is None:
                    total, run = 0.0, []
                    continue
                run.append(value)
                total += value
                if len(run) > window:
                    total -= run.pop(0)
                if len(run) == window:
                    best = max(best or 0.0, total / window)
            out[str(window)] = round(best, 1) if best is not None else None
        return out

    def summary(self, ftp: Optional[int] = None, rider_kg: Optional[float] = None) -> dict:
        np_ = self.normalized_power()
        best = self.best_efforts()
        best20 = best['1200']
        avg = self._mean(self.powers)

        def per_kg(watts):
            return round(watts / rider_kg, 2) if watts and rider_kg else None
        intensity = round(np_ / ftp, 3) if np_ and ftp else None
        tss = round(self.elapsed / 3600 * intensity ** 2 * 100, 1) if intensity else None
        return {
            'elapsedSeconds': round(self.elapsed, 1),
            'movingSeconds': round(self.moving, 1),
            'distanceKm': round(self.distance_km, 3),
            'workKj': round(self.work_j / 1000, 1),
            'avgPowerW': self._mean(self.powers),
            'avgMovingPowerW': self._mean(self.moving_powers),
            'maxPowerW': max(self.powers) if self.powers else None,
            'avgCadenceRpm': self._mean(self.cadences),
            'avgHeartRateBpm': self._mean(self.heart_rates),
            'maxHeartRateBpm': max(self.heart_rates) if self.heart_rates else None,
            'normalizedPowerW': np_,
            'ftpWatts': ftp,
            'intensityFactor': intensity,
            'tss': tss,
            'liveSamples': len(self.powers),
            'avgSpeedKph': round(self.distance_km / (self.moving / 3600), 1) if self.moving >= 1 else None,
            'elevationGainM': round(self.gain_m, 1),
            'climbSeconds': round(self.climb_seconds, 1),
            'vamMh': round(self.gain_m / self.climb_seconds * 3600) if self.climb_seconds >= MIN_CLIMB_SECONDS_FOR_VAM else None,
            'riderWeightKg': rider_kg,
            'avgWattsPerKg': per_kg(avg),
            'bestEffortsW': best,
            'best20MinWattsPerKg': per_kg(best20),
            'estimatedFtpW': round(best20 * 0.95) if best20 else None,
            'gearSeconds': {str(g): round(s, 1) for g, s in sorted(self.gear_seconds.items())},
        }
