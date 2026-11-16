import { useEffect, useState } from 'react';
import { api, sessionFileUrl } from '../api';
import { clock, fmt } from '../format';
import type { LoadReport, SessionSummary } from '../types';

const EFFORTS: [string, string][] = [['5', '5 s'], ['60', '1 min'], ['300', '5 min'], ['1200', '20 min']];

/** Time in each gear, as small bars (gear 1 … 24): which gears were used, at a glance. */
function GearBars({ seconds }: { seconds: Record<string, number> }) {
  const max = Math.max(1, ...Object.values(seconds));
  const gears = Array.from({ length: 24 }, (_, i) => i + 1);
  return (
    <div className="gear-bars" aria-label="Tiempo por marcha">
      <span className="tiny">Marchas</span>
      <div>
        {gears.map((g) => {
          const sec = seconds[String(g)] ?? 0;
          return <i key={g} title={`Marcha ${g}: ${clock(sec)}`} style={{ height: `${sec ? Math.max(8, (sec / max) * 100) : 3}%`, opacity: sec ? 1 : 0.25 }} />;
        })}
      </div>
      <span className="tiny">1 · 12 · 24</span>
    </div>
  );
}

const date = (iso: string) => new Date(iso).toLocaleString('es-ES', { dateStyle: 'medium', timeStyle: 'short' });

/** Finished sessions: summary, downloads and "open in replay". */
export function Sessions() {
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [load, setLoad] = useState<LoadReport | null>(null);
  const [showTests, setShowTests] = useState(false);

  useEffect(() => {
    api.sessions()
      .then((r) => setSessions(r.sessions))
      .catch((e) => setError(`No se pudieron leer las sesiones: ${e instanceof Error ? e.message : e}`));
    api.historyLoad(7).then(setLoad).catch(() => undefined);   // same FTP and load as the History page
  }, []);
  // Sessions of a few seconds or without any work are tests: hidden unless asked for
  const isTest = (s: SessionSummary) => s.elapsedSeconds < 60 || (!s.workKj && (s.distanceKm ?? 0) < 0.05);
  const tests = (sessions ?? []).filter(isTest).length;
  const shown = (sessions ?? []).filter((s) => showTests || !isTest(s));
  const ftp = load?.params.ftp ?? null;
  const ftpNote = load?.params.ftp_source === 'history' ? ' (FTP estimado)' : '';
  const loadOf = (s: SessionSummary) => load?.activities.find((a) => a.id === `app:${s.session}`);

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
      {tests > 0 && (
        <div className="admin-actions">
          <button onClick={() => setShowTests(!showTests)}>{showTests ? 'Ocultar' : 'Mostrar'} {tests} {tests === 1 ? 'sesión de prueba' : 'sesiones de prueba'} (menos de 1 minuto o sin trabajo)</button>
        </div>
      )}
      {shown.map((s) => (
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
            <div><span>IF · TSS{s.ftpWatts ? '' : ftpNote}</span><strong>{s.ftpWatts ? `${fmt(s.intensityFactor, 2)} · ${fmt(s.tss, 0)}`
              : ftp && s.normalizedPowerW ? `${fmt(s.normalizedPowerW / ftp, 2)} · ${fmt(loadOf(s)?.tss, 0)}` : 'sin FTP'}</strong></div>
            <div><span>Tiempo en movimiento</span><strong>{clock(s.movingSeconds)}</strong></div>
            <div><span>Velocidad media</span><strong>{fmt(s.avgSpeedKph, 1)} km/h</strong></div>
            <div><span>Desnivel · VAM</span><strong>{fmt(s.elevationGainM, 0)} m · {s.vamMh == null ? '—' : `${fmt(s.vamMh, 0)} m/h`}</strong></div>
            <div><span>W/kg medio</span><strong>{fmt(s.avgWattsPerKg, 2)}</strong></div>
            <div><span>FTP de esta sesión</span><strong>{s.estimatedFtpW == null ? 'necesita 20 min' : `${fmt(s.estimatedFtpW, 0)} W · ${fmt(s.best20MinWattsPerKg != null ? s.best20MinWattsPerKg * 0.95 : null, 2)} W/kg`}</strong></div>
          </div>
          {s.bestEffortsW && (
            <p className="tiny">Mejores esfuerzos: {EFFORTS.map(([k, label]) => `${label} ${s.bestEffortsW?.[k] == null ? '—' : `${fmt(s.bestEffortsW[k], 0)} W`}`).join(' · ')}</p>
          )}
          {Object.keys(s.gearSeconds ?? {}).length > 0 && <GearBars seconds={s.gearSeconds} />}
          <div className="admin-actions">
            <button disabled={busy} onClick={() => void replay(s)}>Ver en replay</button>
            <a className="button-link primary" href={sessionFileUrl(`${s.session}.fit`)} download
              title="Para intervals.icu, Strava, GoldenCheetah, TrainingPeaks…">Descargar FIT</a>
            {s.files.length > 0 && (
              <details className="more-menu">
                <summary className="button-link">Más ▾</summary>
                <div>
                  {s.files.map((f) => (
                    <a key={f} href={sessionFileUrl(f)} download>
                      {f.endsWith('.csv') ? 'Datos (CSV)' : f.endsWith('_ble_raw.jsonl') ? 'Captura Bluetooth (diagnóstico)' : 'Resumen (JSON)'}
                    </a>
                  ))}
                </div>
              </details>
            )}
            <span className="tiny">{s.finishReason === 'finished by the rider' ? '' : `Terminada: ${s.finishReason}`}</span>
          </div>
        </article>
      ))}
    </div>
  );
}
