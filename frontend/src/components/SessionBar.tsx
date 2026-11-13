import { useState } from 'react';
import { api } from '../api';
import { clock, fmt } from '../format';
import type { SessionSummary, Telemetry } from '../types';

const STATE_LABEL: Record<string, string> = { IDLE: 'SIN SESIÓN', RUNNING: 'GRABANDO', PAUSED: 'EN PAUSA' };

/** Start / pause / finish a training session. Not shown in REPLAY (nothing new to record). */
export function SessionBar({ data, onError }: { data: Telemetry | null; onError: (msg: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [finished, setFinished] = useState<SessionSummary | null>(null);
  const state = data?.sessionState ?? 'IDLE';
  if (state === 'UNAVAILABLE') return null;

  const run = async (action: 'start' | 'pause' | 'resume' | 'finish') => {
    if (action === 'finish' && !window.confirm('¿Terminar la sesión? Se guardará y aparecerá en «Sesiones».')) return;
    setBusy(true);
    try {
      const result = await api.sessionAction(action);
      if (action === 'finish') setFinished(result as SessionSummary);
      if (action === 'start') setFinished(null);
      onError('');
    } catch (e) {
      onError(`Sesión: ${e instanceof Error ? e.message : e}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={`panel session-bar state-${state.toLowerCase()}`}>
      <div className="session-status">
        <span className="session-dot" />
        <strong>{STATE_LABEL[state] ?? state}</strong>
        {state !== 'IDLE' && (
          <span className="session-figures">
            {clock(data?.sessionElapsedSeconds)} · {fmt(data?.sessionDistanceKm, 2)} km · {fmt(data?.sessionElevationGainM, 0)} m+ · {fmt(data?.sessionWorkKj, 0)} kJ ·
            media {fmt(data?.sessionAvgPowerW, 0)} W
          </span>
        )}
        {state === 'IDLE' && finished && (
          <span className="session-figures">
            Última: {clock(finished.elapsedSeconds)} · {fmt(finished.distanceKm, 2)} km · {fmt(finished.elevationGainM, 0)} m+ · {fmt(finished.workKj, 0)} kJ ·{' '}
            <a href="#/sesiones">ver en Sesiones</a>
          </span>
        )}
      </div>
      <div className="session-actions">
        {state === 'IDLE' && <button className="primary" disabled={busy} onClick={() => void run('start')}>● Iniciar sesión</button>}
        {state === 'RUNNING' && <button disabled={busy} onClick={() => void run('pause')}>⏸ Pausar</button>}
        {state === 'PAUSED' && <button className="primary" disabled={busy} onClick={() => void run('resume')}>▶ Continuar</button>}
        {state !== 'IDLE' && <button disabled={busy} onClick={() => void run('finish')}>■ Terminar</button>}
      </div>
    </section>
  );
}
