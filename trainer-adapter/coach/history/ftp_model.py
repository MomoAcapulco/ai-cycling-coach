"""FTP notice: the FTP estimated from recent hard efforts, and what to do about it. It never changes the FTP by itself.

Estimate (critical power, the 2-parameter model of Monod and Scherrer, as used by intervals.icu or Golden Cheetah):
the best average power of each duration from 3 to 30 minutes (``MODEL_DURATIONS``) over the last ``WINDOW_DAYS``
days, fitted as work = CP × time + W′ (least squares). The estimated FTP is what the model gives for one hour:
CP + W′ / 3600. The fit is only trusted with efforts at both ends (one of 3–5 min and one of 12–30 min) and a
physiological W′ (``W_PRIME_RANGE``).

ONE long effort is also enough (as Zwift since 12-2024 and intervals.icu's eFTP do): the best of the efforts of 20 to
60 minutes (``SINGLE_DURATIONS``), each scaled to one hour with the power law P ∝ t^−k, k = ``POWER_LAW_K`` = 0.0467,
chosen so that 20 min gives the classic 95 % (30 min → 97 %, 60 min → 100 %). Not shorter: efforts of 8–15 min carry
much W′ (anaerobic work) and the power law overestimates them (a rider with W′ 20 kJ: +2 % from a 10 min effort);
Zwift accepts them from 8 min with lower factors. Those go to the model.
The estimate is the HIGHER of the two: the best powers come from rides that were not all maximal, and a sub-maximal
effort can only underestimate (measured with the real history: a 30 min best that was not all-out pulled the model
from 155 to 144 W while a maximal 20 min said 152 W).
Compared in 11-2026 with Zwift (only raises, proposes at the end of a ride), intervals.icu (eFTP: one maximal
effort of 3/5–30 min on a family of Morton 3-parameter curves, power at 1 h; eCP: Morton fitted to 3 efforts),
TrainerRoad (machine learning, can lower it) and Garmin (95 % of a 20 min record; criticised for lowering it after
long easy rides). The policy here is Zwift's; the estimate is closest to intervals.icu's eCP, with 2 parameters.

Indoor (trainer and virtual rides) and outdoor rides are estimated apart: on the trainer the FTP is usually 5–10 %
lower (heat, fixed position, no inertia), and the targets of the trainer workouts should use the trainer one. With
outdoor efforts only, the proposal is the outdoor estimate × ``OUTDOOR_TO_INDOOR`` (the cautious end of that gap).

Advice, in this order:
- no FTP in the profile → «set» (with the estimate) or «test» (no estimate);
- estimate ≥ FTP + 3 % (``RAISE_MARGIN``) → «raise»: a button proposes the new value;
- no maximal effort for ``MAX_EFFORT_DAYS`` days → «test»: sub-threshold workouts (sweet spot, tempo) say nothing about
  the FTP, so an estimate made only from them falls although the rider is fitter — it is never used to lower it;
- estimate below 90 % of the FTP → «test» too (maybe tired or ill, maybe the FTP is too high: only a test tells);
- else «ok».
A maximal effort is an FTP test, or a ride with an effort of 20–60 min whose one-hour estimate reaches 95 % of the
FTP, or whose best 5 min reaches 115 % of it (typical maximal 5 min power is 115–125 % of the FTP).
"""
import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

MMP_DURATIONS = (60, 180, 240, 300, 420, 480, 600, 720, 900, 1200, 1800, 2400, 3600)   # stored per activity (s)
MODEL_DURATIONS = (180, 240, 300, 420, 480, 600, 720, 900, 1200, 1800)
SINGLE_DURATIONS = (1200, 1800, 2400, 3600)
POWER_LAW_K = 0.0467
WINDOW_DAYS = 56
MAX_EFFORT_DAYS = 56
RAISE_MARGIN = 1.03
FALL_MARGIN = 0.90
W_PRIME_RANGE = (3000, 50000)          # J
INDOOR, OUTDOOR = ('virtual_ride',), ('ride',)
TEST_NAMES = ('Test de FTP (rampa)',)
OUTDOOR_TO_INDOOR = 0.95


def best_averages(powers: List[Optional[float]], durations=MMP_DURATIONS) -> Dict[int, float]:
    """Best mean power of each duration over consecutive live seconds (None breaks a window). O(n) per duration."""
    runs, run = [], []
    for p in powers:
        if p is None:
            if run:
                runs.append(run)
            run = []
        else:
            run.append(p)
    if run:
        runs.append(run)
    best: Dict[int, float] = {}
    for values in runs:
        prefix = [0.0]
        for v in values:
            prefix.append(prefix[-1] + v)
        for d in durations:
            if len(values) < d:
                continue
            top = max(prefix[i + d] - prefix[i] for i in range(len(values) - d + 1)) / d
            if top > best.get(d, 0.0):
                best[d] = round(top, 1)
    return best


def one_hour(watts: float, seconds: int) -> float:
    """One maximal effort of ``seconds`` scaled to one hour (power law, see the module docstring)."""
    return watts * (seconds / 3600) ** POWER_LAW_K


def _mmp(row: dict) -> Dict[int, float]:
    try:
        return {int(k): float(v) for k, v in json.loads(row.get('mmp') or '{}').items()}
    except (ValueError, TypeError):
        return {}


def fit_cp(points: Dict[int, float]) -> Optional[dict]:
    """Critical power and W′ from {seconds: watts}; None if the points cannot support the model."""
    pts = sorted((t, w) for t, w in points.items() if t in MODEL_DURATIONS)
    if len(pts) < 3 or pts[0][0] > 300 or pts[-1][0] < 720:
        return None
    xs = [t for t, _ in pts]
    ys = [t * w for t, w in pts]                     # work (J)
    n, mx, my = len(xs), sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    cp = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    w_prime = my - cp * mx
    if cp <= 0 or not W_PRIME_RANGE[0] <= w_prime <= W_PRIME_RANGE[1]:
        return None
    return {'cp': round(cp), 'wPrime': round(w_prime)}


def estimate(rows: List[dict], types, today: date) -> Optional[dict]:
    """FTP estimate from the rides of ``types`` in the last WINDOW_DAYS days, with the efforts it comes from."""
    since = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    curve: Dict[int, dict] = {}
    for row in rows:
        if row.get('type') not in types or (row.get('start_utc') or '') < since:
            continue
        for seconds, watts in _mmp(row).items():
            if watts > curve.get(seconds, {}).get('w', 0):
                curve[seconds] = {'w': watts, 'id': row['id'], 'date': (row.get('start_utc') or '')[:10],
                                  'name': row.get('name')}
    if not curve:
        return None
    efforts = [{'seconds': s, **curve[s]} for s in sorted(curve)]
    model = fit_cp({s: c['w'] for s, c in curve.items()})
    model_ftp = model['cp'] + model['wPrime'] / 3600 if model else None
    singles = [(one_hour(curve[s]['w'], s), s) for s in SINGLE_DURATIONS if s in curve]
    single_ftp, seconds = max(singles) if singles else (None, None)
    if model_ftp is None and single_ftp is None:
        return None
    use_model = model_ftp is not None and (single_ftp is None or model_ftp >= single_ftp)
    return {'ftp': int(round(model_ftp if use_model else single_ftp)), 'method': 'cp' if use_model else 'single',
            'seconds': seconds, 'cp': model['cp'] if model else None, 'wPrime': model['wPrime'] if model else None,
            'modelFtp': None if model_ftp is None else int(round(model_ftp)),
            'singleFtp': None if single_ftp is None else int(round(single_ftp)), 'efforts': efforts}


def is_max_effort(row: dict, ftp: int) -> bool:
    if row.get('name') in TEST_NAMES:
        return True
    mmp = _mmp(row)
    long = max((one_hour(mmp[s], s) for s in SINGLE_DURATIONS if s in mmp), default=0)
    return long >= 0.95 * ftp or mmp.get(300, 0) >= 1.15 * ftp


def estimated_ftp(rows: List[dict], today: Optional[date] = None) -> Optional[int]:
    """The FTP for the trainer estimated from recent efforts (indoor, else outdoor × OUTDOOR_TO_INDOOR), or None.
    The one used everywhere when the profile has no FTP (training load, workouts, zones)."""
    today = today or datetime.now().astimezone().date()
    indoor = estimate(rows, INDOOR, today)
    if indoor:
        return indoor['ftp']
    outdoor = estimate(rows, OUTDOOR, today)
    return int(round(outdoor['ftp'] * OUTDOOR_TO_INDOOR)) if outdoor else None


def ftp_advice(profile, rows: List[dict], today: Optional[date] = None) -> dict:
    today = today or datetime.now().astimezone().date()
    ftp = getattr(profile, 'ftp_watts', None)
    indoor, outdoor = estimate(rows, INDOOR, today), estimate(rows, OUTDOOR, today)
    where = 'indoor' if indoor else 'outdoor' if outdoor else None
    best_ftp = indoor['ftp'] if indoor else int(round(outdoor['ftp'] * OUTDOOR_TO_INDOOR)) if outdoor else None
    rides = sorted((r for r in rows if r.get('type') in INDOOR + OUTDOOR and r.get('start_utc')),
                   key=lambda r: r['start_utc'], reverse=True)
    last = next((r for r in rides if ftp and is_max_effort(r, ftp)), None)
    last_test = next((r for r in rides if r.get('name') in TEST_NAMES), None)
    days_since = (today - date.fromisoformat(last['start_utc'][:10])).days if last else None

    if not ftp:
        kind = 'set' if best_ftp else 'test'
        reason = 'no_ftp'
    elif best_ftp and best_ftp >= ftp * RAISE_MARGIN:
        kind, reason = 'raise', 'above'
    elif days_since is None or days_since > MAX_EFFORT_DAYS:
        kind, reason = 'test', 'no_max_effort'
    elif best_ftp and best_ftp < ftp * FALL_MARGIN:
        kind, reason = 'test', 'falling'
    else:
        kind, reason = 'ok', 'ok'
    return {
        'ftp': ftp, 'kind': kind, 'reason': reason, 'suggestedFtp': best_ftp if kind in ('raise', 'set') else None,
        'estimateFtp': best_ftp, 'estimateFrom': where, 'indoor': indoor, 'outdoor': outdoor,
        'lastMaxEffort': None if last is None else {'date': last['start_utc'][:10], 'name': last.get('name'),
                                                     'daysAgo': days_since},
        'lastTest': None if last_test is None else {'date': last_test['start_utc'][:10]},
        'windowDays': WINDOW_DAYS, 'maxEffortDays': MAX_EFFORT_DAYS,
    }
