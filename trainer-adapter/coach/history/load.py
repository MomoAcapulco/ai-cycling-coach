"""Training load of every activity, and fitness / fatigue / form (CTL / ATL / TSB) day by day.

Load of one activity, in TSS units so that everything adds up on one scale:
- **power** (rides with a power meter, when an FTP is known): TSS = hours × IF² × 100, IF = NP / FTP (Coggan).
- **hr** (heart rate, no usable power): Banister's TRIMP second by second (weight x·0.64·e^(1.92·x), x = heart
  rate reserve), scaled so that one hour at the threshold heart rate = 100, like hrTSS. 1.92 is Banister's
  coefficient for men (1.67 for women); the profile has no sex field yet.
- **hr_avg**: the same with the average heart rate when there is no per-second file.
- **estimate**: neither power nor heart rate: hours × a typical load per hour of the activity type (rides 50,
  runs 60, strength 35, other 40). Rough on purpose, and marked as such.
Thresholds: from the rider profile; if missing, FTP = 95 % of the best 20 min power of the last year, max heart
rate = the highest of the activities (but a lone spike more than 8 bpm above the next is ignored), resting heart
rate 60, threshold heart rate = 90 % of the max. Every value says where it came from.

Duplicates: the same ride recorded twice (a trainer session also uploaded to Strava) would count twice; two
activities of the same family overlapping by more than half of the shorter one keep only the one with more data.

Fitness, fatigue, form (Coggan / TrainingPeaks): CTL += (TSS − CTL) / 42 and ATL += (TSS − ATL) / 7 every day;
form (TSB) of a day = yesterday's CTL − ATL. Days are local days of this computer. Everything starts at 0 on the
first activity: the first weeks underestimate CTL.
"""
import csv
import gzip
import json
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from coach.history.fit_reader import FitError, read_fit
from coach.workouts.ramp_test import best_average

BANISTER_B = 1.92
ESTIMATE_TSS_PER_HOUR = {'ride': 50, 'virtual_ride': 50, 'run': 60, 'strength': 35, 'workout': 40, 'other': 40}
CYCLING = ('ride', 'virtual_ride')
CTL_DAYS, ATL_DAYS = 42, 7
DEFAULT_RESTING_HR = 60
SPIKE_BPM = 8
GAP_S = 3          # power older than this is a gap: a cut in the data
HR_GAP_S = 30      # heart rate changes slowly: carried forward up to 30 s. Measured: the Strava phone app records it
                   # every 5 s; with the 3 s of power, 75 % of those activities' heart rate was being dropped
ENRICH_VERSION = 2  # bump when the per-activity streams change, so they are read again


@dataclass
class Params:
    ftp: Optional[int]
    ftp_source: Optional[str]          # 'profile' | 'history' | None
    hr_rest: int
    hr_rest_source: str                # 'profile' | 'default'
    hr_max: Optional[int]
    hr_max_source: Optional[str]       # 'profile' | 'history' | None
    lthr: Optional[int]
    lthr_source: Optional[str]         # 'profile' | 'estimate' | None


# ---- per-activity streams, read once ---------------------------------------------------------

def _per_second(samples: List[Tuple[datetime, Optional[float], Optional[float]]]):
    """(hr, power) on a 1 s grid from (time, hr, power) samples: each carried forward while fresh (HR_GAP_S for
    heart rate, GAP_S for power), then a gap (None)."""
    out = []
    if not samples:
        return out
    samples.sort(key=lambda s: s[0])
    i, t = 0, samples[0][0]
    last_hr = last_power = None             # (time, value) of the latest sample that had each one
    while t <= samples[-1][0]:
        while i < len(samples) and samples[i][0] <= t:
            moment, hr, power = samples[i]
            if hr:
                last_hr = (moment, hr)
            if power is not None:
                last_power = (moment, power)
            i += 1
        hr = last_hr[1] if last_hr and (t - last_hr[0]).total_seconds() <= HR_GAP_S else None
        power = last_power[1] if last_power and (t - last_power[0]).total_seconds() <= GAP_S else None
        out.append((hr, power))
        t += timedelta(seconds=1)
    return out


def streams_from_file(row: dict, data_home: Path, recordings: Path) -> Tuple[Dict[int, int], Optional[float]]:
    """(seconds at each heart rate, best 20 min power) of one activity, from its original file."""
    samples = []
    name = row.get('file') or ''
    if row.get('source') == 'app':
        path = Path(recordings) / name
        with path.open(newline='', encoding='utf-8') as handle:
            for r in csv.DictReader(handle):
                if not r.get('recordedAtUtc'):
                    continue
                hr = float(r['heartRateBpm']) if r.get('heartRateBpm') and r.get('heartRateConnected') == 'True' else None
                pw = float(r['powerWatts']) if r.get('powerWatts') and r.get('connected') == 'True' else None
                samples.append((datetime.fromisoformat(r['recordedAtUtc']), hr, pw))
    elif '.fit' in name:
        raw = (Path(data_home) / name).read_bytes()
        fit = read_fit(gzip.decompress(raw) if name.endswith('.gz') else raw)
        samples = [(r['timestamp'], r.get('heart_rate'), r.get('power')) for r in fit.records if r.get('timestamp')]
    grid = _per_second(samples)
    hist: Dict[int, int] = {}
    for hr, _ in grid:
        if hr:
            hist[int(round(hr))] = hist.get(int(round(hr)), 0) + 1
    powers = [p for _, p in grid]
    best20 = best_average(powers, 1200) if any(p is not None for p in powers) else None
    return hist, best20


def enrich_missing(store, data_home: Path, recordings: Path) -> int:
    """Read the file of every activity not enriched yet (once; a few seconds for a hundred activities)."""
    done = 0
    for row in store.list(100000):
        if (row.get('enriched') or 0) >= ENRICH_VERSION:
            continue
        hist, best20 = {}, None
        if row.get('file'):
            try:
                hist, best20 = streams_from_file(row, data_home, recordings)
            except (OSError, FitError, ValueError, EOFError, KeyError):
                pass   # a missing or broken file: the activity keeps its averages
        store.update(row['id'], {'hr_hist': json.dumps(hist, separators=(',', ':')) if hist else None,
                                 'best20_w': best20, 'enriched': ENRICH_VERSION})
        done += 1
    return done


# ---- thresholds ------------------------------------------------------------------------------

def robust_max(values: List[float]) -> Optional[int]:
    values = sorted((v for v in values if v), reverse=True)
    if not values:
        return None
    if len(values) > 1 and values[0] - values[1] > SPIKE_BPM:
        return int(values[1])            # a lone spike of the strap, not the heart
    return int(values[0])


def derive_params(profile, rows: List[dict], today: Optional[date] = None) -> Params:
    today = today or datetime.now().astimezone().date()
    ftp, ftp_source = getattr(profile, 'ftp_watts', None), 'profile'
    if not ftp:
        year_ago = (today - timedelta(days=365)).isoformat()
        best = [r['best20_w'] for r in rows if r.get('best20_w') and r['type'] in CYCLING
                and (r.get('start_utc') or '') >= year_ago]
        ftp, ftp_source = (int(round(max(best) * 0.95)), 'history') if best else (None, None)
    hr_max, hr_max_source = getattr(profile, 'max_heart_rate', None), 'profile'
    if not hr_max:
        hr_max = robust_max([r.get('max_hr') for r in rows])
        hr_max_source = 'history' if hr_max else None
    hr_rest = getattr(profile, 'resting_heart_rate', None)
    hr_rest_source = 'profile' if hr_rest else 'default'
    hr_rest = hr_rest or DEFAULT_RESTING_HR
    lthr, lthr_source = getattr(profile, 'threshold_heart_rate', None), 'profile'
    if not lthr:
        lthr, lthr_source = (int(round(hr_max * 0.9)), 'estimate') if hr_max else (None, None)
    return Params(ftp, ftp_source, hr_rest, hr_rest_source, hr_max, hr_max_source, lthr, lthr_source)


# ---- load of one activity --------------------------------------------------------------------

def _trimp_per_second(hr: float, p: Params) -> float:
    x = min(1.0, max(0.0, (hr - p.hr_rest) / (p.hr_max - p.hr_rest)))
    return x * 0.64 * math.exp(BANISTER_B * x) / 60


def activity_load(row: dict, p: Params) -> Tuple[float, str]:
    hours = (row.get('moving_s') or row.get('elapsed_s') or 0) / 3600
    if row['type'] in CYCLING and row.get('has_power') and row.get('np') and p.ftp:
        intensity = row['np'] / p.ftp
        return round(hours * intensity ** 2 * 100, 1), 'power'
    if p.hr_max and p.lthr and p.hr_max > p.hr_rest:
        per_hour_at_threshold = 3600 * _trimp_per_second(p.lthr, p)
        if row.get('hr_hist'):
            hist = json.loads(row['hr_hist'])
            trimp = sum(seconds * _trimp_per_second(float(hr), p) for hr, seconds in hist.items())
            recorded = sum(hist.values())
            duration = row.get('moving_s') or row.get('elapsed_s')
            if duration and recorded > duration * 1.2:
                # heart rate recorded far beyond the activity (a strap or watch left running: measured, 938 min of
                # heart rate on a 10 min activity): only the activity's share counts
                trimp *= duration / recorded
            return round(trimp / per_hour_at_threshold * 100, 1), 'hr'
        if row.get('avg_hr'):
            trimp = hours * 3600 * _trimp_per_second(row['avg_hr'], p)
            return round(trimp / per_hour_at_threshold * 100, 1), 'hr_avg'
    return round(hours * ESTIMATE_TSS_PER_HOUR.get(row['type'], 40), 1), 'estimate'


def duplicates(rows: List[dict]) -> Dict[str, str]:
    """{id dropped: id kept} for the same activity recorded twice (overlap > half of the shorter, same family)."""
    def family(row):
        return 'cycling' if row['type'] in CYCLING else row['type']

    def span(row):
        start = datetime.fromisoformat(row['start_utc'])
        return start, start + timedelta(seconds=row.get('elapsed_s') or row.get('moving_s') or 0)

    def quality(row):
        return (bool(row.get('has_power')), bool(row.get('has_hr')), row.get('elapsed_s') or 0)
    dropped = {}
    timed = sorted((r for r in rows if r.get('start_utc')), key=lambda r: r['start_utc'])
    for i, a in enumerate(timed):
        a_start, a_end = span(a)
        for b in timed[i + 1:]:
            b_start, b_end = span(b)
            if b_start >= a_end:
                break
            if family(a) != family(b) or a['id'] in dropped or b['id'] in dropped:
                continue
            overlap = (min(a_end, b_end) - max(a_start, b_start)).total_seconds()
            shorter = min((a_end - a_start).total_seconds(), (b_end - b_start).total_seconds())
            if shorter > 0 and overlap > shorter / 2:
                keep, drop = (a, b) if quality(a) >= quality(b) else (b, a)
                dropped[drop['id']] = keep['id']
    return dropped


# ---- fitness / fatigue / form ----------------------------------------------------------------

def local_day(start_utc: str) -> date:
    moment = datetime.fromisoformat(start_utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone().date()


def daily_series(loads: Dict[date, float], until: date) -> List[dict]:
    if not loads:
        return []
    out, ctl, atl = [], 0.0, 0.0
    day = min(loads)
    while day <= until:
        form = ctl - atl                                   # yesterday's values: the form you start the day with
        tss = loads.get(day, 0.0)
        ctl += (tss - ctl) / CTL_DAYS
        atl += (tss - atl) / ATL_DAYS
        out.append({'date': day.isoformat(), 'tss': round(tss, 1), 'ctl': round(ctl, 1), 'atl': round(atl, 1),
                    'tsb': round(form, 1)})
        day += timedelta(days=1)
    return out


def load_report(rows: List[dict], profile, days: int = 180, today: Optional[date] = None) -> dict:
    today = today or datetime.now().astimezone().date()
    p = derive_params(profile, rows, today)
    dropped = duplicates(rows)
    per_day: Dict[date, float] = {}
    activities = []
    methods: Dict[str, int] = {}
    for row in rows:
        if not row.get('start_utc'):
            continue
        tss, method = activity_load(row, p)
        duplicate_of = dropped.get(row['id'])
        activities.append({'id': row['id'], 'tss': tss, 'method': method, 'duplicateOf': duplicate_of})
        if duplicate_of:
            continue
        methods[method] = methods.get(method, 0) + 1
        day = local_day(row['start_utc'])
        per_day[day] = per_day.get(day, 0.0) + tss
    series = daily_series(per_day, today)
    last = series[-1] if series else {'ctl': 0.0, 'atl': 0.0, 'tsb': 0.0}
    week_ago = next((d for d in series if d['date'] == (today - timedelta(days=7)).isoformat()), None)
    return {
        'params': asdict(p),
        'today': {'ctl': last['ctl'], 'atl': last['atl'], 'tsb': last['tsb'],
                  'ctlChange7d': round(last['ctl'] - week_ago['ctl'], 1) if week_ago else None},
        'days': series[-days:],
        'activities': activities,
        'methods': methods,
        'duplicates': len(dropped),
    }
