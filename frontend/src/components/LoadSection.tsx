import { fmt } from '../format';
import type { LoadDay, LoadReport } from '../types';

const W = 740;
const SOURCE: Record<string, string> = {
  profile: 'tu perfil', history: 'estimado con tu historial', estimate: 'estimado: 90 % del máximo', default: 'valor por defecto',
};

/** What today's form (TSB) means, with the usual ranges (Coggan / TrainingPeaks). */
export function formLabel(tsb: number): [string, string] {
  if (tsb > 25) return ['Mucho descanso', 'Llevas días sin cargar: estás fresco, pero empiezas a perder forma.'];
  if (tsb > 5) return ['Fresco', 'Buen momento para una carrera o un test.'];
  if (tsb >= -10) return ['Neutro', 'Equilibrio entre carga y recuperación.'];
  if (tsb >= -30) return ['Cargando', 'Fatiga productiva: así se gana forma. Recupera bien.'];
  return ['Sobrecarga', 'Mucha fatiga acumulada: riesgo de lesión o de enfermar. Toca descansar.'];
}

function Chart({ days }: { days: LoadDay[] }) {
  if (days.length < 2) return <div className="chart-empty">Aún no hay suficientes días</div>;
  const H = 200, left = 34, right = 10, top = 10, mid = 120, bottom = 170;
  const maxLine = Math.max(30, ...days.map((d) => Math.max(d.ctl, d.atl)));
  const maxTsb = Math.max(20, ...days.map((d) => Math.abs(d.tsb)));
  const x = (i: number) => left + (i / (days.length - 1)) * (W - left - right);
  const y = (v: number) => mid - (v / maxLine) * (mid - top);
  const yTsb = (v: number) => (bottom + mid) / 2 + 10 - (v / maxTsb) * 30;
  const line = (key: 'ctl' | 'atl') => days.map((d, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(d[key]).toFixed(1)}`).join(' ');
  const months = days.map((d, i) => [d, i] as const).filter(([d]) => d.date.endsWith('-01'));
  return (
    <svg role="img" aria-label="Forma, fatiga y frescura" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="load-chart">
      <line x1={left} x2={W - right} y1={mid} y2={mid} stroke="#38504b" />
      <text x={left - 6} y={y(maxLine) + 4} textAnchor="end" fill="#94aaa5" fontSize="11">{fmt(maxLine, 0)}</text>
      <line x1={left} x2={W - right} y1={yTsb(0)} y2={yTsb(0)} stroke="#38504b" strokeDasharray="4 5" />
      {days.map((d, i) => (
        <rect key={d.date} x={x(i) - 1} width={2} y={Math.min(yTsb(0), yTsb(d.tsb))} height={Math.abs(yTsb(d.tsb) - yTsb(0))}
          fill={d.tsb >= 0 ? '#7fb6ff' : '#f2a65a'} opacity=".55" />
      ))}
      <path d={line('atl')} stroke="#f6c180" strokeWidth="1.6" fill="none" />
      <path d={line('ctl')} stroke="#6ce8af" strokeWidth="2.6" fill="none" />
      {months.map(([d, i]) => (
        <text key={d.date} x={x(i)} y={H - 4} fontSize="10" textAnchor="middle" fill="#9eafa9">
          {new Date(d.date).toLocaleDateString('es-ES', { month: 'short' })}</text>
      ))}
    </svg>
  );
}

/** Fitness (CTL), fatigue (ATL) and form (TSB) from the whole history (coach/history/load.py). */
export function LoadSection({ report }: { report: LoadReport }) {
  const { today, params: p } = report;
  const [label, advice] = formLabel(today.tsb);
  const methods = report.methods;
  return (
    <section className="panel">
      <div className="panel-heading"><h2>Forma, fatiga y frescura</h2><span>CARGA DE TODO TU HISTORIAL</span></div>
      <div className="session-grid">
        <div><span>Forma (CTL, 42 días)</span><strong>{fmt(today.ctl, 0)}{today.ctlChange7d != null && <small> ({today.ctlChange7d >= 0 ? '+' : ''}{fmt(today.ctlChange7d, 1)} en 7 días)</small>}</strong></div>
        <div><span>Fatiga (ATL, 7 días)</span><strong>{fmt(today.atl, 0)}</strong></div>
        <div><span>Frescura (TSB)</span><strong>{fmt(today.tsb, 0)} · {label}</strong></div>
      </div>
      <p className="tiny">{advice}</p>
      <Chart days={report.days} />
      <div className="profile-legend">
        <span><span className="swatch" style={{ background: '#6ce8af' }} /> Forma</span>
        <span><span className="swatch" style={{ background: '#f6c180' }} /> Fatiga</span>
        <span><span className="swatch" style={{ background: '#7fb6ff' }} /> Fresco / <span className="swatch" style={{ background: '#f2a65a' }} /> cargado</span>
      </div>
      <p className="tiny">
        Carga calculada con potencia en {methods.power ?? 0} actividades, con pulso en {(methods.hr ?? 0) + (methods.hr_avg ?? 0)} y
        estimada por duración en {methods.estimate ?? 0} (sin potencia ni pulso){report.duplicates ? `; ${report.duplicates} grabadas dos veces cuentan una sola vez` : ''}.
      </p>
      <p className="tiny">
        FTP {p.ftp ?? '—'} W ({p.ftp_source ? SOURCE[p.ftp_source] : 'desconocido'}) · pulso máximo {p.hr_max ?? '—'} ({p.hr_max_source ? SOURCE[p.hr_max_source] : 'desconocido'})
        · umbral {p.lthr ?? '—'} ({p.lthr_source ? SOURCE[p.lthr_source] : 'desconocido'}) · reposo {p.hr_rest} ({SOURCE[p.hr_rest_source]}).
        Si conoces tus valores, ponlos en Ajustes → Perfil: la carga se recalcula al momento.
      </p>
    </section>
  );
}
