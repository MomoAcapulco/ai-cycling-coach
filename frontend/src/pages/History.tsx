import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { clock, fmt } from '../format';
import type { Activity, ActivityType, HistoryWeek, LoadReport } from '../types';
import { LoadSection } from '../components/LoadSection';

const TYPE_LABEL: Record<ActivityType, string> = {
  ride: 'Bici', virtual_ride: 'Rodillo / virtual', run: 'Carrera', strength: 'Fuerza', workout: 'Entrenamiento', other: 'Otro',
};
const TYPE_COLOR: Record<ActivityType, string> = {
  ride: '#e9a15a', virtual_ride: '#6ce8af', run: '#7fb6ff', strength: '#c79bff', workout: '#aab5ff', other: '#8aa99e',
};
const ORDER: ActivityType[] = ['ride', 'virtual_ride', 'run', 'strength', 'workout', 'other'];
const WEEKS_SHOWN = 16;

const date = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('es-ES', { dateStyle: 'medium', timeStyle: 'short' }) : '—';

/** Hours per week by activity type: the last WEEKS_SHOWN weeks, including weeks without activity. */
function WeeksChart({ weeks }: { weeks: HistoryWeek[] }) {
  const byWeek = new Map(weeks.map((w) => [w.week, w]));
  const monday = (d: Date) => { const x = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate())); x.setUTCDate(x.getUTCDate() - ((x.getUTCDay() + 6) % 7)); return x; };
  const last = monday(new Date());
  const shown = Array.from({ length: WEEKS_SHOWN }, (_, i) => {
    const d = new Date(last); d.setUTCDate(d.getUTCDate() - 7 * (WEEKS_SHOWN - 1 - i));
    const key = d.toISOString().slice(0, 10);
    return byWeek.get(key) ?? { week: key, hours: {}, activities: 0, distanceKm: 0, ascentM: 0, workKj: 0 };
  });
  const total = (w: HistoryWeek) => Object.values(w.hours).reduce((a, b) => a + (b ?? 0), 0);
  const max = Math.max(2, ...shown.map(total));
  const W = 740, H = 180, left = 34, base = 150, bar = (W - left - 10) / WEEKS_SHOWN;
  const y = (h: number) => base - (h / max) * (base - 12);
  return (
    <svg role="img" aria-label="Horas por semana" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="weeks-chart">
      {[0, max / 2, max].map((h) => (
        <g key={h}>
          <line x1={left} x2={W - 10} y1={y(h)} y2={y(h)} stroke="#38504b" strokeDasharray="4 5" />
          <text x={left - 6} y={y(h) + 4} textAnchor="end" fill="#94aaa5" fontSize="11">{fmt(h, 0)} h</text>
        </g>
      ))}
      {shown.map((w, i) => {
        let top = base;
        return (
          <g key={w.week}>
            {ORDER.filter((t) => w.hours[t]).map((t) => {
              const h = (w.hours[t] ?? 0) / max * (base - 12);
              top -= h;
              return <rect key={t} x={left + i * bar + 3} y={top} width={bar - 6} height={h} fill={TYPE_COLOR[t]} opacity=".8"><title>{`${TYPE_LABEL[t]}: ${fmt(w.hours[t], 1)} h`}</title></rect>;
            })}
            {i % 2 === 0 && <text x={left + i * bar + bar / 2} y={base + 18} textAnchor="middle" fill="#9eafa9" fontSize="10">
              {new Date(w.week).toLocaleDateString('es-ES', { day: 'numeric', month: 'short' })}</text>}
          </g>
        );
      })}
    </svg>
  );
}

/**
 * Every activity: the sessions of this app and what was imported from outside (Strava export, FIT files).
 * Importing is a command (docs/IMPORTAR-historial.md); this page only shows it.
 */
export function History() {
  const [activities, setActivities] = useState<Activity[] | null>(null);
  const [weeks, setWeeks] = useState<HistoryWeek[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [filter, setFilter] = useState<ActivityType | 'all'>('all');
  const [error, setError] = useState('');
  const [load, setLoad] = useState<LoadReport | null>(null);

  useEffect(() => {
    Promise.all([api.history(), api.historyWeeks()])
      .then(([h, w]) => { setActivities(h.activities); setCounts(h.counts); setWeeks(w.weeks); })
      .catch((e) => setError(`No se pudo leer el historial: ${e instanceof Error ? e.message : e}`));
    api.historyLoad(120).then(setLoad).catch((e) => setError(`No se pudo calcular la carga: ${e instanceof Error ? e.message : e}`));
  }, []);
  const loads = useMemo(() => new Map((load?.activities ?? []).map((a) => [a.id, a])), [load]);
  const METHOD: Record<string, string> = { power: 'potencia', hr: 'pulso', hr_avg: 'pulso medio', estimate: 'estimada' };

  const shown = useMemo(() => (activities ?? []).filter((a) => filter === 'all' || a.type === filter), [activities, filter]);
  const present = useMemo(() => ORDER.filter((t) => (activities ?? []).some((a) => a.type === t)), [activities]);

  return (
    <div className="admin">
      <div className="heading">
        <div>
          <p className="eyebrow">HISTORIAL</p>
          <h1>Todo lo que entrenas</h1>
          <p className="muted">Tus sesiones en el rodillo y lo importado de fuera ({Object.entries(counts).map(([k, v]) => `${k === 'app' ? 'esta aplicación' : k}: ${v}`).join(' · ') || 'nada todavía'}).
            Para importar tu exportación de Strava, sigue docs/IMPORTAR-historial.md.</p>
        </div>
      </div>
      {error && <div className="alert">{error}</div>}
      {load && <LoadSection report={load} />}
      <section className="panel">
        <div className="panel-heading"><h2>Horas por semana</h2><span>ÚLTIMAS {WEEKS_SHOWN} SEMANAS</span></div>
        <WeeksChart weeks={weeks} />
        <div className="profile-legend">
          {present.map((t) => <span key={t}><span className="swatch" style={{ background: TYPE_COLOR[t] }} /> {TYPE_LABEL[t]}</span>)}
        </div>
      </section>
      <div className="admin-actions">
        <button className={filter === 'all' ? 'primary' : ''} onClick={() => setFilter('all')}>Todo</button>
        {present.map((t) => <button key={t} className={filter === t ? 'primary' : ''} onClick={() => setFilter(t)}>{TYPE_LABEL[t]}</button>)}
      </div>
      <section className="panel">
        <table className="devices history-table">
          <thead><tr><th>Fecha</th><th>Tipo</th><th>Nombre</th><th>Tiempo</th><th>Distancia</th><th>Desnivel</th><th>Potencia (NP)</th><th>Pulso</th><th>Carga</th></tr></thead>
          <tbody>
            {shown.map((a) => (
              <tr key={a.id}>
                <td>{date(a.start_utc)}</td>
                <td><span className="swatch" style={{ background: TYPE_COLOR[a.type] }} /> {TYPE_LABEL[a.type]}</td>
                <td>{a.name ?? '—'}</td>
                <td>{clock(a.moving_s ?? a.elapsed_s)}</td>
                <td>{a.distance_m ? `${fmt(a.distance_m / 1000, 1)} km` : '—'}</td>
                <td>{a.ascent_m ? `${fmt(a.ascent_m, 0)} m` : '—'}</td>
                <td>{a.has_power ? `${fmt(a.avg_power, 0)} W (${fmt(a.np, 0)})` : '—'}</td>
                <td>{a.avg_hr ? `${fmt(a.avg_hr, 0)} / ${fmt(a.max_hr, 0)}` : '—'}</td>
                <td title={loads.get(a.id)?.duplicateOf ? 'Grabada dos veces: cuenta la otra' : `Calculada con ${METHOD[loads.get(a.id)?.method ?? ''] ?? '—'}`}>
                  {loads.get(a.id)?.duplicateOf ? 'duplicada' : loads.has(a.id) ? `${fmt(loads.get(a.id)?.tss, 0)} · ${METHOD[loads.get(a.id)?.method ?? '']}` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {activities && shown.length === 0 && <p className="muted">No hay actividades de este tipo.</p>}
      </section>
    </div>
  );
}
