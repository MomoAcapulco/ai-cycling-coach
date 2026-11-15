import { useEffect, useState } from 'react';
import { api, sessionFileUrl } from '../api';
import { clock, fmt } from '../format';
import type { SessionSummary } from '../types';

const EFFORTS: [string, string][] = [['5', '5 s'], ['60', '1 min'], ['300', '5 min'], ['1200', '20 min']];

const date = (iso: string) => new Date(iso).toLocaleString('es-ES', { dateStyle: 'medium', timeStyle: 'short' });

/** Finished sessions: summary, downloads and "open in replay". */
export function Sessions() {
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.sessions()
      .then((r) => setSessions(r.sessions))
      .catch((e) => setError(`No se pudieron leer las sesiones: ${e instanceof Error ? e.message : e}`));
  }, []);

  const replay = async (s: SessionSummary) => {
    setBusy(true);
    try {
      await api.saveSettings({ mode: 'REPLAY', replayFile: s.csv });
      window.location.hash = '#/';
    } catch (e) {
      setError(`No se pudo abrir en replay: ${e instanceof Error ? e.message : e}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="admin">
      <div className="heading">
        <div>
          <p className="eyebrow">SESIONES</p>
          <h1>Tus entrenamientos</h1>
          <p className="muted">Se guardan al pulsar «Terminar» en el panel (o al cambiar de ajustes, cerrar la aplicación o llegar a 4 h).</p>
        </div>
      </div>
      {error && <div className="alert">{error}</div>}
      {sessions && sessions.length === 0 && <p className="muted">Todavía no hay sesiones. Inicia una desde el Panel.</p>}
      {sessions?.map((s) => (
        <article className="panel session-card" key={s.session}>
          <div className="panel-heading">
            <h2>{date(s.startedAtUtc)}</h2>
            <span>{clock(s.elapsedSeconds)} · {fmt(s.distanceKm, 2)} km · {fmt(s.elevationGainM, 0)} m+</span>
          </div>
          <div className="session-grid">
            <div><span>Trabajo</span><strong>{fmt(s.workKj, 0)} kJ</strong></div>
            <div><span>Potencia media</span><strong>{fmt(s.avgPowerW, 0)} W</strong></div>
            <div><span>Potencia máx.</span><strong>{fmt(s.maxPowerW, 0)} W</strong></div>
            <div><span>NP</span><strong>{s.normalizedPowerW == null ? '—' : `${fmt(s.normalizedPowerW, 0)} W`}</strong></div>
            <div><span>Cadencia media</span><strong>{fmt(s.avgCadenceRpm, 0)} rpm</strong></div>
            <div><span>Pulso medio / máx.</span><strong>{fmt(s.avgHeartRateBpm, 0)} / {fmt(s.maxHeartRateBpm, 0)}</strong></div>
            <div><span>IF · TSS</span><strong>{s.ftpWatts ? `${fmt(s.intensityFactor, 2)} · ${fmt(s.tss, 0)}` : 'sin FTP'}</strong></div>
            <div><span>Tiempo en movimiento</span><strong>{clock(s.movingSeconds)}</strong></div>
            <div><span>Velocidad media</span><strong>{fmt(s.avgSpeedKph, 1)} km/h</strong></div>
            <div><span>Desnivel · VAM</span><strong>{fmt(s.elevationGainM, 0)} m · {s.vamMh == null ? '—' : `${fmt(s.vamMh, 0)} m/h`}</strong></div>
            <div><span>W/kg medio</span><strong>{fmt(s.avgWattsPerKg, 2)}</strong></div>
            <div><span>FTP estimado</span><strong>{s.estimatedFtpW == null ? 'necesita 20 min' : `${fmt(s.estimatedFtpW, 0)} W · ${fmt(s.best20MinWattsPerKg != null ? s.best20MinWattsPerKg * 0.95 : null, 2)} W/kg`}</strong></div>
          </div>
          {s.bestEffortsW && (
            <p className="tiny">Mejores esfuerzos: {EFFORTS.map(([k, label]) => `${label} ${s.bestEffortsW?.[k] == null ? '—' : `${fmt(s.bestEffortsW[k], 0)} W`}`).join(' · ')}</p>
          )}
          {Object.keys(s.gearSeconds ?? {}).length > 0 && (
            <p className="tiny">Marchas: {Object.entries(s.gearSeconds).map(([g, sec]) => `${g} (${clock(sec)})`).join(' · ')}</p>
          )}
          <div className="admin-actions">
            <button disabled={busy} onClick={() => void replay(s)}>Ver en replay</button>
            <a className="button-link primary" href={sessionFileUrl(`${s.session}.fit`)} download
              title="Para intervals.icu, Strava, GoldenCheetah, TrainingPeaks…">Descargar FIT</a>
            {s.files.map((f) => (
              <a key={f} className="button-link" href={sessionFileUrl(f)} download>
                Descargar {f.endsWith('.csv') ? 'CSV' : f.endsWith('_ble_raw.jsonl') ? 'captura Bluetooth' : 'resumen'}
              </a>
            ))}
            <span className="tiny">{s.finishReason === 'finished by the rider' ? '' : `Terminada: ${s.finishReason}`}</span>
          </div>
        </article>
      ))}
    </div>
  );
}
