import { useState } from 'react';
import { api } from '../api';
import { clock, fmt } from '../format';
import type { Telemetry } from '../types';

/**
 * Ramp FTP test without ERG: 5 min easy, then a target that rises every minute; the rider reaches it with the
 * gears until they cannot. FTP = 75 % of the best minute. The adapter runs it (coach/workouts/ramp_test.py).
 */
export function RampTestPanel({ data, power3s, onError }: { data: Telemetry | null; power3s: number | null; onError: (msg: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<number | null>(null);
  const phase = data?.workoutPhase;
  const run = async (action: () => Promise<unknown>, after?: (r: unknown) => void) => {
    setBusy(true);
    try { const r = await action(); after?.(r); onError(''); }
    catch (e) { onError(`Test de FTP: ${e instanceof Error ? e.message : e}`); }
    finally { setBusy(false); }
  };
  const target = data?.targetPowerW ?? null;
  const diff = target && power3s != null ? (power3s - target) / target : null;
  const onTarget = diff != null && Math.abs(diff) <= 0.05;

  return (
    <article className="panel control-panel ramp-panel">
      <div className="panel-heading">
        <h2>Test de FTP</h2>
        <span className={phase === 'RAMP' || phase === 'WARMUP' ? 'live-tag' : ''}>
          {phase === 'WARMUP' ? 'CALENTAMIENTO' : phase === 'RAMP' ? 'RAMPA' : phase === 'DONE' ? 'TERMINADO' : 'RAMPA · SIN ERG'}
        </span>
      </div>

      {!phase && (
        <>
          <p className="tiny">5 minutos suaves y después un objetivo que sube 20 W cada minuto, empezando en
            {' '}{data?.workoutStartW ?? 'unos 100'} W. Lo alcanzas tú subiendo de marcha, y aguantas hasta que no puedas más: al dejar de
            pedalear termina solo. Tu FTP es el 75 % de tu mejor minuto. Dura unos 15–25 minutos.</p>
          <p className="tiny warn">Es un esfuerzo máximo. Hazlo descansado, y si notas mareo, dolor en el pecho o algo raro, para.</p>
          <button className="primary" disabled={busy} onClick={() => void run(() => api.startRampTest(), () => setSaved(null))}>Empezar test de FTP</button>
        </>
      )}

      {phase === 'WARMUP' && (
        <>
          <div className="gear-display"><span>Rueda suave</span><strong>{clock(data?.workoutStepRemainingS)}</strong></div>
          <p className="tiny">Después empieza la rampa en {data?.workoutStartW} W. Ve cogiendo una cadencia cómoda.</p>
          <button disabled={busy} onClick={() => void run(() => api.stopWorkout())}>Cancelar test</button>
        </>
      )}

      {phase === 'RAMP' && (
        <>
          <div className="ramp-target">
            <div><span>Objetivo</span><strong>{fmt(target)} <small>W</small></strong></div>
            <div className={onTarget ? 'ok' : 'off'}><span>Ahora (3 s)</span><strong>{fmt(power3s)} <small>W</small></strong></div>
          </div>
          <p className="tiny">Escalón {data?.workoutStep} · quedan {data?.workoutStepRemainingS} s · siguiente {fmt((target ?? 0) + (data?.workoutStepW ?? 20))} W ·
            mejor minuto {fmt(data?.rampBest60sW)} W</p>
          <p className="tiny">{diff == null ? '' : diff < -0.05 ? 'Por debajo: sube una marcha o la cadencia.' : diff > 0.05 ? 'Por encima: puedes bajar una marcha.' : 'En el objetivo.'}
            {' '}Cuando no puedas más, deja de pedalear: el test termina solo.</p>
          <button disabled={busy} onClick={() => void run(() => api.stopWorkout())}>He terminado</button>
        </>
      )}

      {(phase === 'DONE' || phase === 'ABORTED') && (
        <>
          {phase === 'ABORTED' && <p className="tiny">Test cancelado durante el calentamiento.</p>}
          {phase === 'DONE' && data?.ftpEstimateW != null && (
            <>
              <div className="gear-display"><span>FTP estimado</span><strong>{data.ftpEstimateW}<small> W</small></strong></div>
              <p className="tiny">75 % de tu mejor minuto ({fmt(data.rampBest60sW)} W). {data.rampMaxHeartRate ? `Pulso máximo en el test: ${fmt(data.rampMaxHeartRate)} ppm.` : ''}</p>
              {saved == null
                ? <button className="primary" disabled={busy} onClick={() => void run(() => api.saveTestFtp(), (r) => setSaved((r as { ftpWatts: number }).ftpWatts))}>Guardar como mi FTP</button>
                : <p className="notice">FTP guardado: {saved} W. Ya se calculan IF y TSS, también en el FIT.</p>}
            </>
          )}
          {phase === 'DONE' && data?.ftpEstimateW == null && (
            <p className="tiny">La rampa fue demasiado corta (menos de 3 minutos) para estimar el FTP.</p>
          )}
          <p className="tiny">Sigue rodando suave unos minutos y termina la sesión cuando quieras.</p>
          <button disabled={busy} onClick={() => void run(() => api.clearWorkout())}>Cerrar</button>
        </>
      )}
    </article>
  );
}
