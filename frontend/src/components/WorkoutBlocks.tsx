import { clock, fmt } from '../format';
import type { WorkoutBlock } from '../types';

/** Colour of a target by its training zone (% of FTP), the usual Coggan zones. */
export const ZONES: [number, string, string][] = [
  [0, '#7c8f9c', 'Recuperación (< 56 %)'],
  [56, '#7fb6ff', 'Resistencia (56–75 %)'],
  [76, '#6ce8af', 'Tempo (76–87 %)'],
  [88, '#e9d27a', 'Sweet spot (88–94 %)'],
  [95, '#f2a65a', 'Umbral (95–105 %)'],
  [106, '#ef7b6b', 'VO2 máx (> 105 %)'],
];
export const zoneColor = (pct: number) => [...ZONES].reverse().find(([from]) => pct >= from)?.[1] ?? '#7c8f9c';

/**
 * The workout as blocks: width = duration, height = target (% of FTP), colour = zone; ramps are slanted. With
 * ``position`` (seconds) the part already ridden is dimmed and a line marks where you are.
 */
export function WorkoutBlocks({ blocks, position = null, height = 70 }: { blocks: WorkoutBlock[]; position?: number | null; height?: number }) {
  const W = 740, top = 4, base = height - 2;
  const total = Math.max(1, blocks.reduce((a, b) => a + b.seconds, 0));
  const maxPct = Math.max(120, ...blocks.map((b) => Math.max(b.startPct, b.endPct)));
  const x = (t: number) => (t / total) * W;
  const y = (pct: number) => base - (pct / maxPct) * (base - top);
  let t = 0;
  return (
    <svg className="workout-blocks" viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" role="img" aria-label="Bloques del entrenamiento"
      style={{ height }}>
      <line x1={0} x2={W} y1={y(100)} y2={y(100)} stroke="#e8f1ee" strokeOpacity=".35" strokeDasharray="4 5" />
      {blocks.map((b, i) => {
        const a = t; t += b.seconds;
        const done = position != null && t <= position;
        const mid = (b.startPct + b.endPct) / 2;
        const title = `${b.name}: ${clock(b.seconds)} · ${b.startPct === b.endPct ? `${fmt(b.startPct, 0)} %` : `${fmt(b.startPct, 0)} → ${fmt(b.endPct, 0)} %`}`
          + (b.startW != null ? ` (${b.startW === b.endW ? b.startW : `${b.startW} → ${b.endW}`} W)` : '') + (b.cadence ? ` · ${b.cadence} rpm` : '');
        return (
          <path key={i} d={`M${x(a) + 0.6},${base} L${x(a) + 0.6},${y(b.startPct)} L${x(t) - 0.6},${y(b.endPct)} L${x(t) - 0.6},${base} Z`}
            fill={zoneColor(mid)} opacity={done ? 0.3 : 0.85}><title>{title}</title></path>
        );
      })}
      {position != null && <line x1={x(Math.min(position, total))} x2={x(Math.min(position, total))} y1={0} y2={height} stroke="#ffffff" strokeWidth="2" />}
    </svg>
  );
}

export function ZoneLegend() {
  return (
    <div className="profile-legend">
      {ZONES.map(([from, color, label]) => <span key={from}><span className="swatch" style={{ background: color }} /> {label}</span>)}
      <span>┄ 100 % del FTP</span>
    </div>
  );
}
