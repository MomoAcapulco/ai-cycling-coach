import { average, fmt, timeTicks } from '../format';
import type { Sample } from '../types';

type Field = 'power' | 'heart' | 'cadence' | 'speed';

const W = 740;
/** Labels at the edges grow inwards, so «0 min» and «10 min» are never cut. */
const anchor = (x: number) => (x < 40 ? 'start' : x > W - 40 ? 'end' : 'middle');

/** Line chart of one field over the whole session; the dashed line marks the current position. */
export function TraceChart({ points, field, color, unit, current, duration, fullView }: {
  points: Sample[]; field: Field; color: string; unit: string; current: number; duration: number; fullView: boolean;
}) {
  const targets = field === 'power' ? points.filter((p) => p.target != null) : [];
  const valid = [...points.map((p) => p[field]), ...targets.map((p) => p.target)].filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
  if (!valid.length) return <div className="chart-empty">No hay datos disponibles</div>;
  const H = 170, padX = 12, padY = 12, axis = 16;
  const max = Math.max(1, ...valid) * 1.08;
  const min = Math.min(0, ...valid);
  const span = Math.max(1, duration);
  const x = (t: number) => padX + (t / span) * (W - 2 * padX);
  const y = (v: number) => H - axis - padY - ((v - min) / (max - min || 1)) * (H - axis - 2 * padY);
  const visible = fullView ? points : points.filter((p) => p.t <= current);
  let d = '';
  let drawing = false;
  for (const p of visible) {
    const v = p[field];
    if (v == null) { drawing = false; continue; } // a gap stays a gap: no invented values
    d += `${drawing ? 'L' : 'M'}${x(p.t).toFixed(2)},${y(v).toFixed(2)} `;
    drawing = true;
  }
  // the workout's target, as a dashed line under the power (a gap where there was no target)
  let targetPath = '';
  let onTarget = false;
  for (const p of (fullView ? points : visible)) {
    if (field !== 'power' || p.target == null) { onTarget = false; continue; }
    targetPath += `${onTarget ? 'L' : 'M'}${x(p.t).toFixed(2)},${y(p.target).toFixed(2)} `;
    onTarget = true;
  }
  const pointer = x(Math.max(0, Math.min(current, span)));
  const shown = visible.filter((p) => p[field] != null).length;
  const values = points.map((p) => p[field]).filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
  return (
    <div className="chart-wrapper">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Gráfico de ${field}`} preserveAspectRatio="none">
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} x1={padX} x2={W - padX} y1={(H - axis) * f} y2={(H - axis) * f} stroke="#2c4745" strokeDasharray="4 6" />
        ))}
        {timeTicks(span, 6).map(([t, label]) => (
          <text key={t} x={x(t)} y={H - 2} fontSize="10" textAnchor={anchor(x(t))} fill="#7f9a94">{label}</text>
        ))}
        {!shown && !fullView && (
          <text x={W / 2} y={(H - axis) / 2} fontSize="13" textAnchor="middle" fill="#8aa99e">
            Se dibuja al reproducir · «Análisis completo» la muestra entera
          </text>
        )}
        {targetPath && <path d={targetPath} fill="none" stroke="#e8f1ee" strokeOpacity=".7" strokeWidth="1.6" strokeDasharray="6 4" />}
        <path d={d} fill="none" stroke={color} strokeWidth="2.3" strokeLinejoin="round" />
        <line x1={pointer} x2={pointer} y1="0" y2={H - axis} stroke="#e0e8d8" strokeWidth="1.5" strokeDasharray="5 4" />
      </svg>
      <span>{shown} de {values.length} muestras · media total {fmt(average(values), 1)} {unit}{targetPath ? ' · ┄ objetivo' : ''}</span>
    </div>
  );
}

/** A "nice" grid step for a span: about 4-8 lines whatever the values (no fixed top). */
const niceStep = (span: number) => [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000].find((s) => span / s <= 7) ?? 2000;

/** Colour of a road grade, the usual climb colours. */
export const GRADE_BANDS: [number, string, string][] = [
  [-Infinity, '#7fb6ff', 'bajada (< −2 %)'],
  [-2, '#81d8b2', 'llano (−2 … 2 %)'],
  [2, '#e9d27a', '2 … 5 %'],
  [5, '#f2a65a', '5 … 8 %'],
  [8, '#ef7b6b', '≥ 8 %'],
];
export const gradeColor = (g: number) => [...GRADE_BANDS].reverse().find(([from]) => g >= from)?.[1] ?? '#81d8b2';

/**
 * Grade over time. With the virtual road it is the ROAD grade (what you are climbing), with the grade the trainer
 * applies (after the difficulty) as a thin dashed line. Old recordings: the grade ordered to the trainer.
 * The axis follows the data both ways (descents included): it has no fixed top.
 */
export function GradeProfile({ points, current, duration, kind }: {
  points: Sample[]; current: number; duration: number; kind?: string;
}) {
  const H = 195, left = 42, right = 12, top = 17, base = 157;
  const span = Math.max(1, duration);
  const commands = points.filter((p) => p.grade != null);
  const effective = points.filter((p) => p.effective != null);
  const values = [...commands.map((p) => p.grade as number), ...effective.map((p) => p.effective as number)];
  const step = niceStep(Math.max(4, Math.max(0, ...values) - Math.min(0, ...values)));
  const hi = Math.max(step * 2, Math.ceil((Math.max(0, ...values) + 0.5) / step) * step);
  const lo = Math.min(0, Math.floor((Math.min(0, ...values) - 0.5) / step) * step);
  const x = (t: number) => left + (t / span) * (W - left - right);
  const y = (v: number) => base - ((v - lo) / (hi - lo)) * (base - top);
  const line = (pts: Sample[], key: 'grade' | 'effective') =>
    pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(p[key] as number).toFixed(1)}`).join(' ');
  const first = commands[0]?.t ?? span;
  const last = commands[commands.length - 1]?.t ?? span;
  const path = line(commands, 'grade');
  const filled = commands.length ? `${path} L${x(last)},${y(0)} L${x(first)},${y(0)} Z` : '';
  const gradeNow = points.reduce<number | null>((g, p) => (p.t <= current ? p.grade : g), null);
  const marker = x(Math.max(0, Math.min(current, span)));
  const road = kind === 'ROAD' || points.some((p) => p.distance != null);
  const grid: number[] = [];
  for (let g = lo; g <= hi + 1e-9; g += step) grid.push(Math.round(g * 10) / 10);
  return (
    <div className="grade-profile">
      <div className="profile-top">
        <div>
          <h2>{road ? 'Pendiente de la carretera' : 'Pendiente ordenada al rodillo'}</h2>
          <p>{road ? `La que eliges, con transición por distancia${effective.length > 1 ? ' · discontinua: la que aplica el rodillo' : ''}` : 'Registro antiguo: órdenes al rodillo, no pendiente medida'}</p>
        </div>
        <strong>{fmt(gradeNow, 1)} <small>%</small></strong>
      </div>
      <svg role="img" aria-label="Pendiente a lo largo del tiempo" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        <rect x={left} y={top} width={Math.max(0, x(first) - left)} height={base - top} fill="#ffffff" opacity=".035" />
        {grid.map((g) => (
          <g key={g}>
            <line x1={left} x2={W - right} y1={y(g)} y2={y(g)} stroke={g === 0 ? '#5d7c75' : '#38504b'} strokeDasharray={g === 0 ? '' : '4 5'} />
            <text x={left - 8} y={y(g) + 4} textAnchor="end" fill="#94aaa5" fontSize="11">{fmt(g, step < 1 ? 1 : 0)}%</text>
          </g>
        ))}
        {filled && <path d={filled} fill="#81d8b2" opacity=".15" />}
        {path && <path d={path} stroke="#81d8b2" strokeWidth="2.6" fill="none" strokeLinejoin="round" />}
        {effective.length > 1 && <path d={line(effective, 'effective')} stroke="#f6c180" strokeWidth="1.4" strokeDasharray="5 4" fill="none" />}
        <line x1={marker} x2={marker} y1={top} y2={base} stroke="#f6c180" strokeWidth="2" strokeDasharray="5 4" />
        {timeTicks(span).map(([t, label]) => (
          <text key={t} x={x(t)} y={base + 20} fontSize="11" textAnchor={anchor(x(t))} fill="#9eafa9">{label}</text>
        ))}
      </svg>
      <div className="profile-legend">
        {commands.length
          ? <span>▨ Sin datos hasta {fmtMinutes(first)}</span>
          : <span>▨ Esta sesión no tiene pendiente registrada</span>}
        <span>— {road ? 'Carretera' : 'Pendiente ordenada'}</span>
        {effective.length > 1 && <span>- - Rodillo (tras la dificultad)</span>}
        <span>│ Posición actual</span>
      </div>
    </div>
  );
}

/**
 * Altitude against DISTANCE, coloured by road grade, like a race profile. Distance and altitude come from the
 * virtual road (physics speed), relative to the first sample. Returns null when there is no road data
 * (old recordings): the caller then shows the grade over time instead.
 */
export function ElevationProfile({ points, current, fullView }: { points: Sample[]; current: number; fullView: boolean }) {
  const all = points.filter((p) => p.distance != null && p.altitude != null);
  if (all.length < 2) return null;
  const d0 = all[0].distance as number;
  const a0 = all[0].altitude as number;
  const rows = all.map((p) => ({ t: p.t, d: (p.distance as number) - d0, a: (p.altitude as number) - a0, g: p.grade ?? 0 }));
  const shownRows = fullView ? rows : rows.filter((r) => r.t <= current);
  const totalKm = Math.max(0.2, rows[rows.length - 1].d);
  // downsample long sessions for drawing only (figures use every sample)
  const every = Math.max(1, Math.ceil(shownRows.length / 1200));
  const drawn = shownRows.filter((_, i) => i % every === 0 || i === shownRows.length - 1);
  const H = 215, left = 46, right = 12, top = 14, base = 172;
  const alts = rows.map((r) => r.a);
  const minA = Math.min(0, ...alts);
  const maxA = Math.max(minA + 20, ...alts);
  const step = niceStep(maxA - minA);
  const lo = Math.floor(minA / step) * step;
  const hi = Math.ceil(maxA / step) * step;
  const x = (d: number) => left + (d / totalKm) * (W - left - right);
  const y = (a: number) => base - ((a - lo) / (hi - lo || 1)) * (base - top);
  const upTo = rows.filter((r) => r.t <= current);
  let gain = 0;
  upTo.forEach((r, i) => { if (i && r.a > upTo[i - 1].a) gain += r.a - upTo[i - 1].a; });
  const now = upTo[upTo.length - 1] ?? rows[0];
  const kmStep = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50].find((s) => totalKm / s <= 8) ?? 100;
  const kmTicks: number[] = [];
  for (let k = 0; k <= totalKm + 1e-9; k += kmStep) kmTicks.push(Math.round(k * 10) / 10);
  const grid: number[] = [];
  for (let a = lo; a <= hi + 1e-9; a += step) grid.push(a);
  return (
    <div className="grade-profile">
      <div className="profile-top">
        <div>
          <h2>Perfil del recorrido</h2>
          <p>Altitud según la distancia, coloreada por pendiente · {fmt(now.d, 2)} km · desnivel acumulado {fmt(gain, 0)} m</p>
        </div>
        <strong>{fmt(now.g, 1)} <small>%</small></strong>
      </div>
      <svg role="img" aria-label="Perfil de altitud según la distancia" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        {grid.map((a) => (
          <g key={a}>
            <line x1={left} x2={W - right} y1={y(a)} y2={y(a)} stroke="#38504b" strokeDasharray="4 5" />
            <text x={left - 8} y={y(a) + 4} textAnchor="end" fill="#94aaa5" fontSize="11">{fmt(a, 0)} m</text>
          </g>
        ))}
        {drawn.slice(1).map((r, i) => {
          const p = drawn[i];
          return <path key={r.t} d={`M${x(p.d)},${base} L${x(p.d)},${y(p.a)} L${x(r.d)},${y(r.a)} L${x(r.d)},${base} Z`} fill={gradeColor(r.g)} opacity=".55" />;
        })}
        <path d={drawn.map((r, i) => `${i ? 'L' : 'M'}${x(r.d).toFixed(1)},${y(r.a).toFixed(1)}`).join(' ')} stroke="#e8f1ee" strokeWidth="1.6" fill="none" />
        <line x1={x(now.d)} x2={x(now.d)} y1={top} y2={base} stroke="#f6c180" strokeWidth="2" strokeDasharray="5 4" />
        {kmTicks.map((k) => (
          <text key={k} x={x(k)} y={base + 20} fontSize="11" textAnchor={anchor(x(k))} fill="#9eafa9">{fmt(k, kmStep < 1 ? 1 : 0)} km</text>
        ))}
      </svg>
      <div className="profile-legend">
        {GRADE_BANDS.map(([from, color, label]) => (
          <span key={String(from)}><span className="swatch" style={{ background: color }} /> {label}</span>
        ))}
      </div>
    </div>
  );
}

const fmtMinutes = (t: number) => (t < 60 ? `${Math.round(t)} s` : `${fmt(t / 60, t % 60 ? 1 : 0)} min`);

/**
 * The whole route ahead, coloured by grade, with the rider's position: like a race profile. Used in the Panel
 * while a route is ridden and, small, in the Rutas page.
 */
export function RouteProfile({ profile, progressKm, title, compact = false }: {
  profile: { d: number; e: number; g: number }[]; progressKm: number | null; title?: string; compact?: boolean;
}) {
  if (profile.length < 2) return null;
  const H = compact ? 90 : 215, left = compact ? 6 : 46, right = 12, top = 10, base = compact ? 84 : 172;
  const total = Math.max(0.1, profile[profile.length - 1].d);
  const elevations = profile.map((p) => p.e);
  const minE = Math.min(...elevations), maxE = Math.max(minE + 20, ...elevations);
  const step = niceStep(maxE - minE);
  const lo = Math.floor(minE / step) * step, hi = Math.ceil(maxE / step) * step;
  const x = (d: number) => left + (d / total) * (W - left - right);
  const y = (e: number) => base - ((e - lo) / (hi - lo || 1)) * (base - top);
  const at = progressKm == null ? null : Math.min(progressKm, total);
  const here = at == null ? null : profile.reduce((best, p) => (Math.abs(p.d - at) < Math.abs(best.d - at) ? p : best), profile[0]);
  const grid: number[] = [];
  for (let e = lo; e <= hi + 1e-9; e += step) grid.push(e);
  const kmStep = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50].find((s) => total / s <= 8) ?? 100;
  const kmTicks: number[] = [];
  for (let k = 0; k <= total + 1e-9; k += kmStep) kmTicks.push(Math.round(k * 10) / 10);
  const svg = (
    <svg role="img" aria-label="Perfil de la ruta" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
      {!compact && grid.map((e) => (
        <g key={e}>
          <line x1={left} x2={W - right} y1={y(e)} y2={y(e)} stroke="#38504b" strokeDasharray="4 5" />
          <text x={left - 8} y={y(e) + 4} textAnchor="end" fill="#94aaa5" fontSize="11">{fmt(e, 0)} m</text>
        </g>
      ))}
      {compact && at == null && (   // a thumbnail: the shape only, in one colour (the grade colours, in the big one)
        <path d={`M${x(0)},${base} ${profile.map((p) => `L${x(p.d).toFixed(1)},${y(p.e).toFixed(1)}`).join(' ')} L${x(total)},${base} Z`}
          fill="#5fbf98" opacity=".28" />
      )}
      {!(compact && at == null) && profile.slice(1).map((p, i) => {
        const a = profile[i];
        const done = at != null && p.d <= at;
        return <path key={p.d} d={`M${x(a.d)},${base} L${x(a.d)},${y(a.e)} L${x(p.d)},${y(p.e)} L${x(p.d)},${base} Z`}
          fill={gradeColor(a.g)} opacity={done ? 0.25 : 0.6} />;
      })}
      <path d={profile.map((p, i) => `${i ? 'L' : 'M'}${x(p.d).toFixed(1)},${y(p.e).toFixed(1)}`).join(' ')} stroke="#e8f1ee" strokeWidth="1.4" fill="none" />
      {at != null && <line x1={x(at)} x2={x(at)} y1={top} y2={base} stroke="#f6c180" strokeWidth="2.5" />}
      {!compact && kmTicks.map((k) => (
        <text key={k} x={x(k)} y={base + 20} fontSize="11" textAnchor={anchor(x(k))} fill="#9eafa9">{fmt(k, kmStep < 1 ? 1 : 0)} km</text>
      ))}
    </svg>
  );
  if (compact) return <div className="route-mini">{svg}</div>;
  return (
    <div className="grade-profile">
      <div className="profile-top">
        <div>
          <h2>{title ?? 'Ruta'}</h2>
          <p>{at == null ? `${fmt(total, 1)} km` : `${fmt(at, 2)} de ${fmt(total, 1)} km · quedan ${fmt(total - at, 2)} km`}</p>
        </div>
        <strong>{fmt(here?.g ?? null, 1)} <small>%</small></strong>
      </div>
      {svg}
      <div className="profile-legend">
        {GRADE_BANDS.map(([from, color, label]) => (
          <span key={String(from)}><span className="swatch" style={{ background: color }} /> {label}</span>
        ))}
        <span>│ Tu posición</span>
      </div>
    </div>
  );
}
