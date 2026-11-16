import { useState } from 'react';
import { api } from '../api';
import { clock, fmt } from '../format';
import type { Telemetry } from '../types';
import { WorkoutBlocks, zoneColor } from './WorkoutBlocks';

const KIND: Record<string, string> = { WARMUP: 'CALENTAMIENTO', WORK: 'TRABAJO', REST: 'RECUPERACIÓN', COOLDOWN: 'VUELTA A LA CALMA' };

/** The structured workout being ridden: target, time left, what comes next; at the end, how each block went. */
export function WorkoutPanel({ data, power3s, onError }: { data: Telemetry; power3s: number | null; onError: (msg: string) => void }) {
  const [busy, setBusy] = useState(false);
  const run = async (action: () => Promise<unknown>, confirm?: string) => {
    if (confirm && !window.confirm(confirm)) return;
    setBusy(true);
    try { await action(); onError(''); }
    catch (e) { onError(`Entrenamiento: ${e instanceof Error ? e.message : e}`); }
    finally { setBusy(false); }
  };
  const target = data.targetPowerW ?? null;
  const diff = target && power3s != null ? (power3s - target) / target : null;
  const state = diff == null ? '' : diff < -0.1 ? 'low' : diff > 0.1 ? 'high' : 'ok';
  const cadence = data.cadenceRpm ?? null;
  const ftp = data.workoutFtpW ?? 0;
  const work = (data.workoutResults ?? []).filter((r) => r.kind === 'WORK');

  if (data.workoutPhase === 'RUNNING') {
    return (
      <section className="panel workout-panel">
        <div className="panel-heading">
          <h2>{data.workoutName}</h2>
          <span className="live-tag">{KIND[data.workoutBlockKind ?? ''] ?? ''} · BLOQUE {data.workoutBlock}/{data.workoutBlockCount}</span>
        </div>
        <div className="workout-now">
          <div className="workout-target" style={{ borderColor: target ? zoneColor((target / ftp) * 100) : undefined }}>
            <span>Objetivo</span><strong>{fmt(target)}<small> W</small></strong>
            <em>{data.workoutBlockName}</em>
          </div>
          <div className={`workout-power ${state}`}>
            <span>Ahora (3 s)</span><strong>{fmt(power3s)}<small> W</small></strong>
            <em>{state === 'low' ? 'Por debajo: sube una marcha o la cadencia' : state === 'high' ? 'Por encima: baja una marcha' : state === 'ok' ? 'En el objetivo' : ''}</em>
          </div>
          <div>
            <span>Queda del bloque</span><strong>{clock(data.workoutStepRemainingS)}</strong>
            <em>{data.targetCadenceRpm ? `Cadencia ${data.targetCadenceRpm} rpm · llevas ${fmt(cadence)}` : ''}</em>
          </div>
        </div>
        <WorkoutBlocks blocks={data.workoutPlan ?? []} position={data.workoutElapsedS ?? 0} height={64} />
        <div className="workout-foot">
          <span className="tiny">{clock(data.workoutElapsedS)} de {clock(data.workoutTotalS)}
            {data.workoutNext ? ` · después: ${data.workoutNext.name}, ${clock(data.workoutNext.seconds)} a ${data.workoutNext.targetW} W` : ' · último bloque'}
            {data.sessionState === 'PAUSED' ? ' · EN PAUSA' : ''}</span>
          <button disabled={busy} onClick={() => void run(() => api.stopWorkout(), '¿Terminar el entrenamiento? La sesión sigue grabando.')}>Terminar entrenamiento</button>
        </div>
      </section>
    );
  }

  return (
    <section className="panel workout-panel">
      <div className="panel-heading">
        <h2>{data.workoutName}</h2>
        <span>{data.workoutEndReason === 'completed' ? 'COMPLETADO' : 'TERMINADO'}</span>
      </div>
      <div className="session-grid">
        <div><span>Hecho</span><strong>{clock(data.workoutElapsedS)} de {clock(data.workoutTotalS)}</strong></div>
        <div><span>Cumplimiento en los bloques de trabajo</span><strong>{data.workoutCompliancePct == null ? '—' : `${data.workoutCompliancePct} %`}</strong></div>
        <div><span>FTP usado</span><strong>{ftp} W</strong></div>
      </div>
      {work.length > 0 && (
        <table className="devices">
          <thead><tr><th>Bloque</th><th>Tiempo</th><th>Objetivo</th><th>Media</th><th>Cumplimiento</th><th>En rango (±10 %)</th></tr></thead>
          <tbody>
            {work.map((r, i) => (
              <tr key={i}>
                <td>{r.name}</td><td>{clock(r.seconds)}</td><td>{r.targetW} W</td><td>{r.avgW} W</td>
                <td className={r.compliancePct != null && Math.abs(r.compliancePct - 100) <= 5 ? 'ok-text' : 'warn-text'}>{r.compliancePct ?? '—'} %</td>
                <td>{r.inRangePct} %</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="workout-foot">
        <span className="tiny">La sesión sigue grabando: termínala en la barra de arriba. Queda guardado en Sesiones.</span>
        <button disabled={busy} onClick={() => void run(() => api.clearWorkout())}>Cerrar</button>
      </div>
    </section>
  );
}
